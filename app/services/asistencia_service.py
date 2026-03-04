# app/services/asistencia_service.py
from __future__ import annotations

from datetime import date, timedelta
from typing import Annotated, Optional, Iterable

from fastapi import HTTPException, Query
from sqlmodel import select, desc
from sqlalchemy import func, case, and_

from app.dependencies import SessionDep
from app.models.asistencia import Asistencia
from app.models.alumno import Alumno
from app.models.curso import Curso
from app.services.curso_service import get_one_curso
from app.schemas.asistencia import AsistenciaCreate, AsistenciaEstado
from app.services.alerta_service import (
    check_y_crear_alertas_consecutivas_para_curso_fecha,
    check_y_crear_alertas_tardanzas_para_curso_fecha,
)
from app.core.encryption import decrypt, hash_for_search

from collections import defaultdict
from app.models.inscriptos import Inscriptos


# ==========================
# Helpers
# ==========================

def get_one_asistencia(db: SessionDep, idCurso: int, idAlumno: int, fecha: date) -> Optional[Asistencia]:
    return db.get(Asistencia, (idCurso, idAlumno, fecha))


def ensure_curso_exists(db: SessionDep, idCurso: int):
    curso = get_one_curso(idCurso=idCurso, db=db)
    if curso is None:
        raise HTTPException(status_code=404, detail="El curso ingresado no existe")
    return curso


def ensure_alumno_exists(db: SessionDep, idAlumno: int):
    alumno = db.get(Alumno, idAlumno)
    if alumno is None:
        raise HTTPException(status_code=404, detail="El alumno ingresado no existe")
    return alumno


def ensure_alumnos_exist(db: SessionDep, ids_alumnos: Iterable[int]):
    ids = list({int(x) for x in ids_alumnos})
    if not ids:
        return

    stmt = select(Alumno.idAlumno).where(Alumno.idAlumno.in_(ids))
    existentes = set(db.exec(stmt).all())
    faltantes = [i for i in ids if i not in existentes]
    if faltantes:
        raise HTTPException(status_code=404, detail=f"Alumnos inexistentes: {faltantes}")


# ==========================
# Create / Upsert (uno)
# ==========================

def upsert_asistencia(db: SessionDep, payload: AsistenciaCreate) -> Asistencia:
    ensure_curso_exists(db, payload.idCurso)
    ensure_alumno_exists(db, payload.idAlumno)

    existente = get_one_asistencia(db, payload.idCurso, payload.idAlumno, payload.fecha)

    if existente:
        existente.estado = payload.estado
        existente.lluvia = payload.lluvia
        db.add(existente)
        db.commit()
        db.refresh(existente)

        if payload.estado in ("Ausente", "Tarde"):
            check_y_crear_alertas_consecutivas_para_curso_fecha(
                db=db, idCurso=existente.idCurso, fecha=existente.fecha, min_consecutivas=3
            )
            check_y_crear_alertas_tardanzas_para_curso_fecha(
                db=db, idCurso=existente.idCurso, fecha=existente.fecha, umbral=3
            )

        return existente

    nueva = Asistencia.model_validate(payload.model_dump())
    db.add(nueva)
    db.commit()
    db.refresh(nueva)

    if payload.estado in ("Ausente", "Tarde"):
        check_y_crear_alertas_consecutivas_para_curso_fecha(db=db, idCurso=nueva.idCurso, fecha=nueva.fecha, min_consecutivas=3)
        check_y_crear_alertas_tardanzas_para_curso_fecha(db=db, idCurso=nueva.idCurso, fecha=nueva.fecha, umbral=3)

    return nueva


# ==========================
# Bulk Upsert
# ==========================

def upsert_asistencias_bulk(db: SessionDep, payloads: list[AsistenciaCreate]) -> list[Asistencia]:
    if not payloads:
        return []

    cursos_ids = list({p.idCurso for p in payloads})
    for cid in cursos_ids:
        ensure_curso_exists(db, cid)

    ensure_alumnos_exist(db, [p.idAlumno for p in payloads])

    out: list[Asistencia] = []

    for p in payloads:
        existente = get_one_asistencia(db, p.idCurso, p.idAlumno, p.fecha)
        if existente:
            existente.estado = p.estado
            existente.lluvia = p.lluvia
            db.add(existente)
            out.append(existente)
        else:
            nueva = Asistencia.model_validate(p.model_dump())
            db.add(nueva)
            out.append(nueva)

    db.commit()
    for row in out:
        db.refresh(row)
    any_row = out[0]
    check_y_crear_alertas_consecutivas_para_curso_fecha(
        db=db, idCurso=any_row.idCurso, fecha=any_row.fecha, min_consecutivas=3
    )
    check_y_crear_alertas_tardanzas_para_curso_fecha(
        db=db, idCurso=any_row.idCurso, fecha=any_row.fecha, umbral=3
    )
    return out


# ==========================
# Reads
# ==========================

def get_asistencias_by_curso_fecha(db: SessionDep, idCurso: int, fecha: date):
    ensure_curso_exists(db, idCurso)
    stmt = select(Asistencia).where(
        Asistencia.idCurso == idCurso,
        Asistencia.fecha == fecha,
    )
    return db.exec(stmt).all()


def get_asistencias_by_curso(
    db: SessionDep,
    idCurso: int,
    offset: int = 0,
    limit: Annotated[int, Query(le=10000)] = 10000,  
    desde: Optional[date] = None,                    
    hasta: Optional[date] = None,                     
):
    ensure_curso_exists(db, idCurso)
    stmt = select(Asistencia).where(Asistencia.idCurso == idCurso)

    if desde:
        stmt = stmt.where(Asistencia.fecha >= desde)  
    if hasta:
        stmt = stmt.where(Asistencia.fecha <= hasta)

    stmt = stmt.order_by(Asistencia.fecha.desc()).offset(offset).limit(limit)
    return db.exec(stmt).all()


def get_asistencias_by_alumno(db: SessionDep, idAlumno: int, offset: int = 0, limit: int = 200):
    ensure_alumno_exists(db, idAlumno)
    stmt = (
        select(Asistencia)
        .where(Asistencia.idAlumno == idAlumno)
        .order_by(desc(Asistencia.fecha))
        .offset(offset)
        .limit(limit)
    )
    return db.exec(stmt).all()


def get_asistencias_by_curso_alumno(
    db: SessionDep,
    idCurso: int,
    idAlumno: int,
    anio: Optional[int] = None,
    offset: int = 0,
    limit: int = 200,
):
    ensure_curso_exists(db, idCurso)
    ensure_alumno_exists(db, idAlumno)

    stmt = select(Asistencia).where(
        Asistencia.idCurso == idCurso,
        Asistencia.idAlumno == idAlumno,
    )

    if anio:
        desde = date(anio, 1, 1)
        hasta = date(anio, 12, 31)
        stmt = stmt.where(Asistencia.fecha >= desde, Asistencia.fecha <= hasta)

    stmt = stmt.order_by(desc(Asistencia.fecha)).offset(offset).limit(limit)
    return db.exec(stmt).all()


# ==========================
# Estadísticas (Director)
# ==========================

def _base_where(
    cue: str,
    desde: date,
    hasta: date,
    curso_ids: Optional[list[int]] = None,
    solo_lluvia: Optional[bool] = None,
):
    filters = [
        Curso.CUE == cue,
        Asistencia.fecha >= desde,
        Asistencia.fecha <= hasta,
        Asistencia.idCurso == Curso.idCurso,
    ]
    if curso_ids:
        filters.append(Asistencia.idCurso.in_(curso_ids))
    if solo_lluvia is True:
        filters.append(Asistencia.lluvia.is_(True))
    if solo_lluvia is False:
        filters.append(Asistencia.lluvia.is_(False))
    return filters


def stats_resumen(
    db: SessionDep,
    cue: str,
    desde: date,
    hasta: date,
    curso_ids: Optional[list[int]] = None,
    umbral_riesgo: int = 20,
    solo_lluvia: Optional[bool] = None,
):
    where = _base_where(cue, desde, hasta, curso_ids, solo_lluvia)
    presentes_expr = case((Asistencia.estado.in_(["Presente", "Tarde"]), 1), else_=0)
    ausentes_expr = case((Asistencia.estado == "Ausente", 1), else_=0)
    tardes_expr = case((Asistencia.estado == "Tarde", 1), else_=0)

    stmt = (
        select(
            func.sum(presentes_expr).label("presentes"),
            func.sum(ausentes_expr).label("ausentes"),
            func.sum(tardes_expr).label("tardes"),
            func.count().label("total_registros"),
            func.count(func.distinct(Asistencia.idAlumno)).label("alumnos_distintos"),
        )
        .select_from(Asistencia, Curso)
        .where(and_(*where))
    )

    row = db.exec(stmt).one()
    presentes = int(row.presentes or 0)
    ausentes = int(row.ausentes or 0)
    tardes = int(row.tardes or 0)
    total = int(row.total_registros or 0)
    alumnos_distintos = int(row.alumnos_distintos or 0)

    asistencia_pct = round((presentes / total) * 100, 2) if total else 0.0

    sub = (
        select(
            Asistencia.idAlumno.label("idAlumno"),
            func.sum(ausentes_expr).label("faltas"),
        )
        .select_from(Asistencia, Curso)
        .where(and_(*where))
        .group_by(Asistencia.idAlumno)
        .subquery()
    )

    alumnos_riesgo = int(db.exec(select(func.count()).select_from(sub).where(sub.c.faltas >= umbral_riesgo)).one() or 0)
    riesgo_pct = round((alumnos_riesgo / alumnos_distintos) * 100, 2) if alumnos_distintos else 0.0

    stmt_total_alumnos = (
        select(func.count(func.distinct(Inscriptos.idAlumno)))
        .select_from(Inscriptos, Curso)
        .where(
            and_(
                Curso.CUE == cue,
                Inscriptos.idCurso == Curso.idCurso,
                Inscriptos.activo.is_(True),
            )
        )
    )
    total_alumnos_escuela = int(db.exec(stmt_total_alumnos).one() or 0)

    stmt_cursos = (
        select(
            Curso.idCurso,
            Curso.nombre,
            Curso.cicloLectivo,
            Curso.division,
            func.sum(ausentes_expr).label("ausentes"),
            func.sum(tardes_expr).label("tardes"),
            func.count().label("total"),
        )
        .select_from(Asistencia, Curso)
        .where(and_(*where))
        .group_by(Curso.idCurso, Curso.nombre, Curso.cicloLectivo, Curso.division)
    )

    cursos = db.exec(stmt_cursos).all()
    cursos_out = []
    for c in cursos:
        total_c = int(c.total or 0)
        aus_c = int(c.ausentes or 0)
        tar_c = int(c.tardes or 0)
        aus_pct = round((aus_c / total_c) * 100, 2) if total_c else 0.0
        cursos_out.append({
            "idCurso": c.idCurso,
            "curso": f"{c.nombre} {c.division} ({c.cicloLectivo})",
            "ausentes": aus_c,
            "tardes": tar_c,
            "total": total_c,
            "ausentismoPct": aus_pct,
        })
    cursos_out.sort(key=lambda x: x["ausentismoPct"], reverse=True)

    return {
        "desde": str(desde),
        "hasta": str(hasta),
        "kpis": {
            "presentes": presentes,
            "ausentes": ausentes,
            "tardes": tardes,
            "totalRegistros": total,
            "asistenciaPct": asistencia_pct,
            "alumnosDistintos": alumnos_distintos,
            "alumnosRiesgo": alumnos_riesgo,
            "riesgoPct": riesgo_pct,
            "totalAlumnosEscuela": total_alumnos_escuela,
        },
        "topCursosAusentismo": cursos_out[:5],
    }


def stats_serie(
    db: SessionDep,
    cue: str,
    desde: date,
    hasta: date,
    group_by: str = "day",
    curso_ids: Optional[list[int]] = None,
    solo_lluvia: Optional[bool] = None,
):
    where = _base_where(cue, desde, hasta, curso_ids, solo_lluvia)

    presentes_expr = case((Asistencia.estado.in_(["Presente", "Tarde"]), 1), else_=0)
    ausentes_expr = case((Asistencia.estado == "Ausente", 1), else_=0)
    tardes_expr = case((Asistencia.estado == "Tarde", 1), else_=0)

    if group_by == "month":
        bucket = func.date_format(Asistencia.fecha, "%Y-%m").label("bucket")
    elif group_by == "week":
        bucket = func.date_format(Asistencia.fecha, "%x-W%v").label("bucket")
    else:
        bucket = func.date_format(Asistencia.fecha, "%Y-%m-%d").label("bucket")

    stmt = (
        select(
            bucket,
            func.sum(presentes_expr).label("presentes"),
            func.sum(ausentes_expr).label("ausentes"),
            func.sum(tardes_expr).label("tardes"),
            func.count().label("total"),
        )
        .select_from(Asistencia, Curso)
        .where(and_(*where))
        .group_by(bucket)
        .order_by(bucket)
    )

    rows = db.exec(stmt).all()
    out = []
    for r in rows:
        total = int(r.total or 0)
        pres = int(r.presentes or 0)
        aus = int(r.ausentes or 0)
        tar = int(r.tardes or 0)
        asistencia_pct = round((pres / total) * 100, 2) if total else 0.0
        out.append({
            "bucket": r.bucket,
            "presentes": pres,
            "ausentes": aus,
            "tardes": tar,
            "total": total,
            "asistenciaPct": asistencia_pct,
        })
    return out


def stats_distribucion_inasistencias(
    db: SessionDep,
    cue: str,
    desde: date,
    hasta: date,
    curso_ids: Optional[list[int]] = None,
    buckets: Optional[list[tuple[int, int | None]]] = None,
):
    if buckets is None:
        buckets = [(0, 10), (11, 20), (21, 30), (31, 44), (45, 56), (57, None)]

    where = _base_where(cue, desde, hasta, curso_ids)
    ausentes_expr = case((Asistencia.estado == "Ausente", 1), else_=0)

    sub = (
        select(
            Asistencia.idAlumno.label("idAlumno"),
            func.sum(ausentes_expr).label("faltas"),
        )
        .select_from(Asistencia, Curso)
        .where(and_(*where))
        .group_by(Asistencia.idAlumno)
        .subquery()
    )

    total_alumnos = int(db.exec(select(func.count()).select_from(sub)).one() or 0)

    out = []
    for a, b in buckets:
        if b is None:
            stmt = select(func.count()).select_from(sub).where(sub.c.faltas >= a)
            label = f"{a}+"
        else:
            stmt = select(func.count()).select_from(sub).where(sub.c.faltas >= a, sub.c.faltas <= b)
            label = f"{a}-{b}"

        n = int(db.exec(stmt).one() or 0)
        pct = round((n / total_alumnos) * 100, 2) if total_alumnos else 0.0
        out.append({"rango": label, "alumnos": n, "pct": pct})

    return {"totalAlumnos": total_alumnos, "distribucion": out}


def stats_riesgo_por_curso(
    db: SessionDep,
    cue: str,
    desde: date,
    hasta: date,
    umbral: int = 20,
    curso_ids: Optional[list[int]] = None,
):
    where = _base_where(cue, desde, hasta, curso_ids)
    ausentes_expr = case((Asistencia.estado == "Ausente", 1), else_=0)

    sub = (
        select(
            Asistencia.idCurso.label("idCurso"),
            Asistencia.idAlumno.label("idAlumno"),
            func.sum(ausentes_expr).label("faltas"),
        )
        .select_from(Asistencia, Curso)
        .where(and_(*where))
        .group_by(Asistencia.idCurso, Asistencia.idAlumno)
        .subquery()
    )

    stmt = (
        select(
            Curso.idCurso,
            Curso.nombre,
            Curso.cicloLectivo,
            Curso.division,
            func.count().label("alumnosRiesgo"),
        )
        .select_from(sub, Curso)
        .where(
            and_(
                sub.c.idCurso == Curso.idCurso,
                Curso.CUE == cue,
                sub.c.faltas >= umbral,
            )
        )
        .group_by(Curso.idCurso, Curso.nombre, Curso.cicloLectivo, Curso.division)
        .order_by(func.count().desc())
    )

    rows = db.exec(stmt).all()
    return [
        {
            "idCurso": r.idCurso,
            "curso": f"{r.nombre} {r.division} ({r.cicloLectivo})",
            "alumnosRiesgo": int(r.alumnosRiesgo or 0),
        }
        for r in rows
    ]


def stats_lluvia_comparativo(
    db: SessionDep,
    cue: str,
    desde: date,
    hasta: date,
    curso_ids: Optional[list[int]] = None,
):
    def calc(solo_lluvia: bool):
        where = _base_where(cue, desde, hasta, curso_ids, solo_lluvia=solo_lluvia)

        presentes_expr = case((Asistencia.estado.in_(["Presente", "Tarde"]), 1), else_=0)
        ausentes_expr = case((Asistencia.estado == "Ausente", 1), else_=0)
        tardes_expr = case((Asistencia.estado == "Tarde", 1), else_=0)

        stmt = (
            select(
                func.sum(presentes_expr).label("presentes"),
                func.sum(ausentes_expr).label("ausentes"),
                func.sum(tardes_expr).label("tardes"),
                func.count().label("total"),
            )
            .select_from(Asistencia, Curso)
            .where(and_(*where))
        )

        r = db.exec(stmt).one()
        total = int(r.total or 0)
        pres = int(r.presentes or 0)
        aus = int(r.ausentes or 0)
        tar = int(r.tardes or 0)

        return {
            "total": total,
            "presentes": pres,
            "ausentes": aus,
            "tardes": tar,
            "asistenciaPct": round((pres / total) * 100, 2) if total else 0.0,
            "ausentismoPct": round((aus / total) * 100, 2) if total else 0.0,
        }

    return {"lluvia": calc(True), "sinLluvia": calc(False)}


def alertas_inasistencias_consecutivas(
    db: SessionDep,
    cue: str,
    desde: date,
    hasta: date,
    min_consecutivas: int = 3,
):
    stmt = (
        select(
            Asistencia.idAlumno,
            Asistencia.idCurso,
            Asistencia.fecha,
            Asistencia.estado,
            Alumno.nombre,
            Alumno.apellido,
            Alumno.dni,
            Curso.nombre.label("cursoNombre"),
            Curso.division,
            Curso.cicloLectivo,
        )
        .select_from(Asistencia, Curso, Alumno)
        .where(
            and_(
                Curso.CUE == cue,
                Asistencia.idCurso == Curso.idCurso,
                Asistencia.idAlumno == Alumno.idAlumno,
                Asistencia.fecha >= desde,
                Asistencia.fecha <= hasta,
            )
        )
        .order_by(Asistencia.idAlumno, Asistencia.idCurso, Asistencia.fecha)
    )

    rows = db.exec(stmt).all()

    por_key = defaultdict(list)
    for r in rows:
        por_key[(r.idAlumno, r.idCurso)].append(r)

    alertas = []

    for (idAlumno, idCurso), items in por_key.items():
        streak = 0
        best_streak = 0
        best_end = None
        prev_fecha = None

        for it in items:
            is_consecutive_day = (
                prev_fecha is None or (it.fecha - prev_fecha) == timedelta(days=1)
            )

            if not is_consecutive_day:
                streak = 0

            if it.estado == "Ausente":
                streak += 1
                if streak >= best_streak:
                    best_streak = streak
                    best_end = it.fecha
            else:
                streak = 0

            prev_fecha = it.fecha

        if best_streak >= min_consecutivas and best_end is not None:
            last = items[-1]
            alumno_nombre = f"{last.apellido}, {last.nombre}"
            curso_str = f"{last.cursoNombre} {last.division} ({last.cicloLectivo})"

            alertas.append(
                {
                    "idAlumno": idAlumno,
                    "idCurso": idCurso,
                    "alumnoNombre": alumno_nombre,
                    "dni": decrypt(last.dni) if last.dni else last.dni,   # ← FIX
                    "curso": curso_str,
                    "fechaFinRacha": str(best_end),
                    "consecutivas": int(best_streak),
                    "motivo": f"{best_streak} inasistencias consecutivas",
                    "estado": "Pendiente",
                }
            )

    alertas.sort(key=lambda x: (x["consecutivas"], x["fechaFinRacha"]), reverse=True)
    return alertas


def stats_dias_semana(
    db: SessionDep,
    cue: str,
    desde: date,
    hasta: date,
    curso_ids: Optional[list[int]] = None,
    solo_lluvia: Optional[bool] = None,
):
    where = _base_where(cue, desde, hasta, curso_ids, solo_lluvia)
    where = list(where) + [Asistencia.estado == "Ausente"]

    weekday_num = func.weekday(Asistencia.fecha).label("weekday_num")

    stmt = (
        select(weekday_num, func.count().label("ausentes"))
        .select_from(Asistencia, Curso)
        .where(and_(*where))
        .group_by(weekday_num)
        .order_by(weekday_num)
    )

    rows = db.exec(stmt).all()
    names_es = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes"]
    out_map = {i: 0 for i in range(0, 5)}

    for r in rows:
        wd = int(r.weekday_num)
        if 0 <= wd <= 4:
            out_map[wd] = int(r.ausentes or 0)

    return [{"dia": names_es[i], "ausentes": out_map[i]} for i in range(0, 5)]


def get_alumnos_activos_de_curso(db: SessionDep, idCurso: int) -> list[int]:
    ensure_curso_exists(db, idCurso)

    stmt = (
        select(Inscriptos.idAlumno)
        .where(Inscriptos.idCurso == idCurso, Inscriptos.activo.is_(True))
    )
    rows = db.exec(stmt).all()
    return [int(r[0] if isinstance(r, tuple) else r) for r in rows]


def upsert_asistencias_por_curso_fecha(
    db: SessionDep,
    idCurso: int,
    fecha: date,
    default_estado: AsistenciaEstado,
    lluvia: bool,
    overrides: list[tuple[int, AsistenciaEstado, bool | None]],
) -> list[Asistencia]:
    ids = get_alumnos_activos_de_curso(db, idCurso)
    if not ids:
        raise HTTPException(
            status_code=400,
            detail="El curso no tiene alumnos activos para cargar asistencia",
        )

    override_map: dict[int, tuple[AsistenciaEstado, bool | None]] = {
        int(idAlumno): (estado, lluv_individual)
        for (idAlumno, estado, lluv_individual) in overrides
    }

    payloads: list[AsistenciaCreate] = []
    for idAlumno in ids:
        if idAlumno in override_map:
            estado, lluv_individual = override_map[idAlumno]
            payloads.append(AsistenciaCreate(
                idCurso=idCurso, idAlumno=idAlumno, fecha=fecha,
                estado=estado,
                lluvia=(lluv_individual if lluv_individual is not None else lluvia),
            ))
        else:
            payloads.append(AsistenciaCreate(
                idCurso=idCurso, idAlumno=idAlumno, fecha=fecha,
                estado=default_estado, lluvia=lluvia,
            ))

    return upsert_asistencias_bulk(db=db, payloads=payloads)


def upsert_asistencias_por_curso_rango(
    db: SessionDep,
    idCurso: int,
    desde: date,
    hasta: date,
    weekdays: list[int],
    default_estado: AsistenciaEstado,
    lluvia: bool,
    overrides: list[tuple[int, AsistenciaEstado, bool | None]],
    solo_alumnos: list[int] | None = None,
    chunk_size: int = 500,
) -> int:
    if hasta < desde:
        raise HTTPException(status_code=400, detail="hasta no puede ser menor que desde")

    ids = get_alumnos_activos_de_curso(db, idCurso)
    if solo_alumnos:
        solo_set = set(int(x) for x in solo_alumnos)
        ids = [i for i in ids if i in solo_set]

    if not ids:
        raise HTTPException(status_code=400, detail="No hay alumnos para cargar asistencia en este curso")

    override_map: dict[int, tuple[AsistenciaEstado, bool | None]] = {
        int(idAlumno): (estado, lluv_individual)
        for (idAlumno, estado, lluv_individual) in overrides
    }

    fechas: list[date] = []
    d = desde
    wset = set(int(x) for x in weekdays)
    while d <= hasta:
        if d.weekday() in wset:
            fechas.append(d)
        d += timedelta(days=1)

    buffer: list[AsistenciaCreate] = []
    total = 0

    for f in fechas:
        for idAlumno in ids:
            if idAlumno in override_map:
                est, lluv_ind = override_map[idAlumno]
                buffer.append(AsistenciaCreate(
                    idCurso=idCurso, idAlumno=idAlumno, fecha=f,
                    estado=est,
                    lluvia=(lluv_ind if lluv_ind is not None else lluvia),
                ))
            else:
                buffer.append(AsistenciaCreate(
                    idCurso=idCurso, idAlumno=idAlumno, fecha=f,
                    estado=default_estado, lluvia=lluvia,
                ))

            if len(buffer) >= chunk_size:
                upsert_asistencias_bulk(db, buffer)
                total += len(buffer)
                buffer.clear()

    if buffer:
        upsert_asistencias_bulk(db, buffer)
        total += len(buffer)

    return total


import re as _re

def stats_alumnos_por_rango(
    db: SessionDep,
    cue: str,
    desde: date,
    hasta: date,
    rango: str,
    curso_ids: Optional[list[int]] = None,
) -> list[dict]:
    m_range = _re.match(r'^(\d+)-(\d+)$', rango)
    m_plus  = _re.match(r'^(\d+)\+$', rango)

    if m_range:
        min_faltas = int(m_range.group(1))
        max_faltas = int(m_range.group(2))
    elif m_plus:
        min_faltas = int(m_plus.group(1))
        max_faltas = 999999
    else:
        return []

    where = _base_where(cue, desde, hasta, curso_ids)
    ausentes_expr = case((Asistencia.estado == "Ausente", 1), else_=0)

    sub = (
        select(
            Asistencia.idAlumno.label("idAlumno"),
            Asistencia.idCurso.label("idCurso"),
            func.sum(ausentes_expr).label("faltas"),
        )
        .select_from(Asistencia, Curso)
        .where(and_(*where))
        .group_by(Asistencia.idAlumno, Asistencia.idCurso)
        .subquery()
    )

    stmt = (
        select(
            sub.c.idAlumno,
            sub.c.faltas,
            Alumno.nombre,
            Alumno.apellido,
            Alumno.dni,
            Curso.nombre.label("cursoNombre"),
            Curso.division,
            Curso.cicloLectivo,
        )
        .select_from(sub)
        .join(Alumno, Alumno.idAlumno == sub.c.idAlumno)
        .join(Curso, Curso.idCurso == sub.c.idCurso)
        .where(and_(sub.c.faltas >= min_faltas, sub.c.faltas <= max_faltas))
        .order_by(sub.c.faltas.desc(), Alumno.apellido)
    )

    rows = db.exec(stmt).all()

    return [
        {
            "idAlumno": r.idAlumno,
            "nombre": f"{r.apellido}, {r.nombre}",
            "dni": decrypt(r.dni) if r.dni else r.dni,       # ← FIX
            "curso": f"{r.cursoNombre} {r.division} ({r.cicloLectivo})",
            "ausencias": int(r.faltas or 0),
        }
        for r in rows
    ]