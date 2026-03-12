# app/services/asistencia_service.py
from __future__ import annotations

import asyncio
from datetime import date, timedelta
from typing import Annotated, Optional, Iterable

from fastapi import HTTPException, Query, BackgroundTasks
from sqlmodel import Session, select, desc
from sqlalchemy import func, case, and_

from app.dependencies import SessionDep
from app.db.database import engine
from app.models.asistencia import Asistencia
from app.models.alumno import Alumno
from app.models.curso import Curso
from app.services.curso_service import get_one_curso
from app.schemas.asistencia import AsistenciaCreate, AsistenciaEstado
from app.schemas.asistencia import CertificadoRevisionRequest, CertificadoEstado, NotificacionDocente
from app.services.alerta_service import (
    check_y_crear_alertas_consecutivas_para_curso_fecha,
    check_y_crear_alertas_reiteradas_para_curso_fecha,
    check_y_crear_alertas_tardanzas_consecutivas_para_curso_fecha,
    check_y_crear_alertas_tardanzas_para_curso_fecha,
)
from app.core.encryption import decrypt, hash_for_search

from app.services.whatsapp_service import enviar_plantilla_inasistencia
from collections import defaultdict
from app.models.inscriptos import Inscriptos
from app.models.responsable import Responsable
from app.models.parentesco import Parentesco


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


def ensure_alumno_exists(db: SessionDep, idAlumno: int) -> Alumno:
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
# Helpers internos: disparar las 4 alertas automáticas
# ==========================

def _disparar_alertas_automaticas(db: SessionDep, idCurso: int, fecha: date, estado: str) -> None:
    """
    Centraliza las 4 llamadas de generación/actualización de alertas automáticas.
    Se llama después de cada upsert de asistencia con estado Ausente o Tarde.

    Umbrales configurados:
      - Ausencias consecutivas:  3 días seguidos
      - Ausencias reiteradas:   10 ausencias en el año (no necesariamente seguidas)
      - Tardanzas consecutivas:  4 llegadas tarde seguidas
      - Tardanzas reiteradas:   15 llegadas tarde en el año
    """
    if estado == "Ausente":
        check_y_crear_alertas_consecutivas_para_curso_fecha(
            db=db, idCurso=idCurso, fecha=fecha, min_consecutivas=3
        )
        check_y_crear_alertas_reiteradas_para_curso_fecha(
            db=db, idCurso=idCurso, fecha=fecha, umbral=10
        )

    elif estado == "Tarde":
        check_y_crear_alertas_tardanzas_consecutivas_para_curso_fecha(
            db=db, idCurso=idCurso, fecha=fecha, min_consecutivas=4
        )
        check_y_crear_alertas_tardanzas_para_curso_fecha(
            db=db, idCurso=idCurso, fecha=fecha, umbral=15
        )


# ============================================================
# WhatsApp helpers
# ============================================================

def _cargar_datos_whatsapp(
    db: SessionDep,
    ausentes_ids: list[int],
    alumnos_map: dict[int, Alumno],
) -> list[dict]:
    """
    Un único SELECT que trae el primer responsable con teléfono
    para cada alumno ausente. Devuelve una lista de dicts con datos
    primitivos (sin objetos DB) listos para pasar al background task.
    """
    if not ausentes_ids:
        return []

    stmt = (
        select(
            Parentesco.idAlumno,
            Responsable.nro_celular,
        )
        .join(Responsable, Parentesco.idResponsable == Responsable.idResponsable)
        .where(
            Parentesco.idAlumno.in_(ausentes_ids),
            Responsable.nro_celular != "",
        )
        .order_by(Parentesco.idAlumno, Parentesco.idResponsable)
    )
    rows = db.exec(stmt).all()

    primer_telefono: dict[int, str] = {}
    for id_alumno, telefono in rows:
        if id_alumno not in primer_telefono:
            primer_telefono[id_alumno] = telefono

    datos: list[dict] = []
    for id_alumno in ausentes_ids:
        telefono = primer_telefono.get(id_alumno)
        if not telefono:
            continue
        alumno = alumnos_map.get(id_alumno)
        if not alumno:
            continue
        datos.append({
            "idCurso":    None,
            "idAlumno":   id_alumno,
            "fecha":      None,
            "telefono":   telefono,
            "apellido":   alumno.apellido,
            "nombre":     alumno.nombre,
            "dni":        decrypt(alumno.dni) if alumno.dni else "",
        })
    return datos


async def _bg_enviar_whatsapp_y_guardar_wamid(datos_envios: list[dict]) -> None:
    """
    Background task: envía WhatsApp a cada entrada de `datos_envios`
    y persiste el wamid resultante abriendo su propia sesión de DB.
    """
    async def _enviar_uno(d: dict) -> None:
        try:
            wamid = await enviar_plantilla_inasistencia(
                telefono=d["telefono"],
                apellido=d["apellido"],
                nombre=d["nombre"],
                dni=d["dni"],
            )
        except Exception as exc:
            print(f"[BG WhatsApp] Error enviando a {d['apellido']}: {exc}")
            return

        if not wamid:
            return

        if d.get("idCurso") and d.get("idAlumno") and d.get("fecha"):
            with Session(engine) as db_bg:
                asistencia = db_bg.get(
                    Asistencia, (d["idCurso"], d["idAlumno"], d["fecha"])
                )
                if asistencia:
                    asistencia.wamid = wamid
                    db_bg.add(asistencia)
                    db_bg.commit()

    await asyncio.gather(*[_enviar_uno(d) for d in datos_envios])


# ==========================
# Create / Upsert (uno)
# ==========================

async def upsert_asistencia(
    db: SessionDep,
    payload: AsistenciaCreate,
    bg: BackgroundTasks,
) -> Asistencia:
    """
    Crea o actualiza (upsert) una asistencia.
    Dispara las 4 alertas automáticas según el estado registrado.
    """
    ensure_curso_exists(db, payload.idCurso)
    alumno = ensure_alumno_exists(db, payload.idAlumno)

    existente = get_one_asistencia(db, payload.idCurso, payload.idAlumno, payload.fecha)

    if existente:
        ya_notificado = bool(existente.wamid)
        existente.estado = payload.estado
        existente.lluvia = payload.lluvia
        if payload.wamid:
            existente.wamid = payload.wamid
        db.add(existente)
        db.commit()
        db.refresh(existente)

        if payload.estado in ("Ausente", "Tarde"):
            _disparar_alertas_automaticas(db, existente.idCurso, existente.fecha, payload.estado)

        if payload.estado == "Ausente" and not ya_notificado:
            datos = _cargar_datos_whatsapp(db, [alumno.idAlumno], {alumno.idAlumno: alumno})
            for d in datos:
                d["idCurso"] = existente.idCurso
                d["idAlumno"] = existente.idAlumno
                d["fecha"] = existente.fecha
            if datos:
                bg.add_task(_bg_enviar_whatsapp_y_guardar_wamid, datos)

        return existente

    nueva = Asistencia.model_validate(payload.model_dump())
    db.add(nueva)
    db.commit()
    db.refresh(nueva)

    if payload.estado in ("Ausente", "Tarde"):
        _disparar_alertas_automaticas(db, nueva.idCurso, nueva.fecha, payload.estado)

    if payload.estado == "Ausente":
        datos = _cargar_datos_whatsapp(db, [alumno.idAlumno], {alumno.idAlumno: alumno})
        for d in datos:
            d["idCurso"] = nueva.idCurso
            d["idAlumno"] = nueva.idAlumno
            d["fecha"] = nueva.fecha
        if datos:
            bg.add_task(_bg_enviar_whatsapp_y_guardar_wamid, datos)

    return nueva


# ==========================
# Bulk Upsert
# ==========================

async def upsert_asistencias_bulk(
    db: SessionDep,
    payloads: list[AsistenciaCreate],
    bg: BackgroundTasks,
) -> list[Asistencia]:
    if not payloads:
        return []

    cursos_ids = list({p.idCurso for p in payloads})
    for cid in cursos_ids:
        ensure_curso_exists(db, cid)
    ensure_alumnos_exist(db, [p.idAlumno for p in payloads])

    ausentes_ids_total = list({p.idAlumno for p in payloads if p.estado == "Ausente"})
    alumnos_map: dict[int, Alumno] = {}
    if ausentes_ids_total:
        stmt_a = select(Alumno).where(Alumno.idAlumno.in_(ausentes_ids_total))
        alumnos_map = {a.idAlumno: a for a in db.exec(stmt_a).all()}

    ausentes_ya_notificados: set[int] = set()
    if ausentes_ids_total:
        primera_idCurso = next(p.idCurso for p in payloads if p.estado == "Ausente")
        primera_fecha   = next(p.fecha   for p in payloads if p.estado == "Ausente")
        stmt_wamids = select(Asistencia.idAlumno).where(
            Asistencia.idAlumno.in_(ausentes_ids_total),
            Asistencia.idCurso == primera_idCurso,
            Asistencia.fecha   == primera_fecha,
            Asistencia.wamid   != None,
            Asistencia.wamid   != "",
        )
        ausentes_ya_notificados = set(db.exec(stmt_wamids).all())

    ausentes_ids = [i for i in ausentes_ids_total if i not in ausentes_ya_notificados]
    datos_envio = _cargar_datos_whatsapp(db, ausentes_ids, alumnos_map)

    fecha = payloads[0].fecha
    alumno_ids = [p.idAlumno for p in payloads]
    existentes_map = {
        (r.idCurso, r.idAlumno): r
        for r in db.exec(
            select(Asistencia).where(
                Asistencia.idCurso.in_(cursos_ids),
                Asistencia.idAlumno.in_(alumno_ids),
                Asistencia.fecha == fecha,
            )
        ).all()
    }

    out: list[Asistencia] = []
    for p in payloads:
        existente = existentes_map.get((p.idCurso, p.idAlumno))
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

    # Disparar alertas automáticas para cada estado presente en el bulk
    # Agrupamos por curso+fecha+estado para no repetir llamadas innecesarias
    estados_en_bulk = {p.estado for p in payloads if p.estado in ("Ausente", "Tarde")}
    idCurso_bulk = out[0].idCurso
    fecha_bulk = out[0].fecha

    for estado_bulk in estados_en_bulk:
        _disparar_alertas_automaticas(db, idCurso_bulk, fecha_bulk, estado_bulk)

    ausentes_rows = {row.idAlumno: row for row in out if row.idAlumno in ausentes_ids}
    for d in datos_envio:
        row = ausentes_rows.get(d["idAlumno"])
        if row:
            d["idCurso"] = row.idCurso
            d["fecha"] = row.fecha

    if datos_envio:
        bg.add_task(_bg_enviar_whatsapp_y_guardar_wamid, datos_envio)

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
                func.count(func.distinct(Asistencia.fecha)).label("dias_distintos"),  # ← NUEVO
            )
            .select_from(Asistencia, Curso)
            .where(and_(*where))
        )

        r = db.exec(stmt).one()
        total = int(r.total or 0)
        pres = int(r.presentes or 0)
        aus = int(r.ausentes or 0)
        tar = int(r.tardes or 0)
        dias = int(r.dias_distintos or 0)  # ← NUEVO

        return {
            "total": dias,          # ← CAMBIADO: ahora son días únicos, no registros
            "registros": total,     # ← NUEVO (por si lo necesitás en otro lado)
            "presentes": pres,
            "ausentes": aus,
            "tardes": tar,
            "asistenciaPct": round((pres / total) * 100, 2) if total else 0.0,
            "ausentismoPct": round((aus / total) * 100, 2) if total else 0.0,
        }

    return {"lluvia": calc(True), "sinLluvia": calc(False)}

def stats_motivos_ausencia(
    db: SessionDep,
    cue: str,
    desde: date,
    hasta: date,
    curso_ids: Optional[list[int]] = None,
    top_n: int = 10,
) -> list[dict]:
    where = _base_where(cue, desde, hasta, curso_ids)
    where = list(where) + [
        Asistencia.motivo_ausencia != None,
        Asistencia.motivo_ausencia != "",
    ]

    stmt = (
        select(
            Asistencia.motivo_ausencia.label("motivo"),
            func.count().label("cantidad"),
        )
        .select_from(Asistencia, Curso)
        .where(and_(*where))
        .group_by(Asistencia.motivo_ausencia)
        .order_by(func.count().desc())
        .limit(top_n)
    )

    rows = db.exec(stmt).all()
    total = sum(int(r.cantidad or 0) for r in rows)

    return [
        {
            "motivo": r.motivo,
            "cantidad": int(r.cantidad or 0),
            "pct": round((int(r.cantidad or 0) / total) * 100, 1) if total else 0.0,
        }
        for r in rows
    ]

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
                    "dni": decrypt(last.dni) if last.dni else last.dni,
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


async def upsert_asistencias_por_curso_fecha(
    db: SessionDep,
    idCurso: int,
    fecha: date,
    default_estado: AsistenciaEstado,
    lluvia: bool,
    overrides: list[tuple[int, AsistenciaEstado, bool | None]],
    bg: BackgroundTasks,
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

    return await upsert_asistencias_bulk(db=db, payloads=payloads, bg=bg)


async def upsert_asistencias_por_curso_rango(
    db: SessionDep,
    idCurso: int,
    desde: date,
    hasta: date,
    weekdays: list[int],
    default_estado: AsistenciaEstado,
    lluvia: bool,
    overrides: list[tuple[int, AsistenciaEstado, bool | None]],
    bg: BackgroundTasks,
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
                await upsert_asistencias_bulk(db, buffer, bg)
                total += len(buffer)
                buffer.clear()

    if buffer:
        await upsert_asistencias_bulk(db, buffer, bg)
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
            "dni": decrypt(r.dni) if r.dni else r.dni,
            "curso": f"{r.cursoNombre} {r.division} ({r.cicloLectivo})",
            "ausencias": int(r.faltas or 0),
        }
        for r in rows
    ]


# ==========================
# Notificaciones del docente
# ==========================

def get_notificaciones_docente(
    db: SessionDep,
    idCurso: int,
) -> list[NotificacionDocente]:
    stmt = (
        select(
            Asistencia,
            Alumno.nombre.label("alumno_nombre"),
            Alumno.apellido.label("alumno_apellido"),
            Curso.nombre.label("curso_nombre"),
            Curso.division.label("curso_division"),
            Curso.cicloLectivo.label("ciclo_lectivo"),
        )
        .join(Alumno, Alumno.idAlumno == Asistencia.idAlumno)
        .join(Curso,  Curso.idCurso   == Asistencia.idCurso)
        .where(
            Asistencia.idCurso == idCurso,
            Asistencia.estado  == "Ausente",
            Asistencia.motivo_ausencia != None,
        )
        .order_by(Asistencia.fecha.desc())
    )

    rows = db.exec(stmt).all()
    resultado: list[NotificacionDocente] = []

    for row in rows:
        asistencia: Asistencia = row[0]
        alumno_nombre  = f"{row.alumno_apellido}, {row.alumno_nombre}"
        curso_str      = f"{row.curso_nombre} {row.curso_division} ({row.ciclo_lectivo})"

        if asistencia.certificado_estado in (
            CertificadoEstado.aprobado, CertificadoEstado.rechazado
        ):
            tipo = "certificado_revisado"
        elif asistencia.certificado_path and (
            asistencia.certificado_estado == CertificadoEstado.pendiente
            or asistencia.certificado_estado is None
        ):
            tipo = "certificado_pendiente"
        else:
            tipo = "respuesta"

        resultado.append(
            NotificacionDocente(
                idCurso=asistencia.idCurso,
                idAlumno=asistencia.idAlumno,
                fecha=asistencia.fecha,
                alumnoNombre=alumno_nombre,
                curso=curso_str,
                motivo_ausencia=asistencia.motivo_ausencia,
                certificado_path=asistencia.certificado_path,
                certificado_estado=(
                    asistencia.certificado_estado.value
                    if asistencia.certificado_estado else None
                ),
                justificado_hasta=asistencia.justificado_hasta,
                tipo_notif=tipo,
            )
        )

    orden = {"certificado_pendiente": 0, "respuesta": 1, "certificado_revisado": 2}
    resultado.sort(key=lambda n: orden.get(n.tipo_notif, 9))

    return resultado


# ==========================
# Revisión de certificado
# ==========================

def revisar_certificado(
    db: SessionDep,
    idCurso: int,
    idAlumno: int,
    fecha: date,
    payload: CertificadoRevisionRequest,
    revisado_por_id: int,
) -> Asistencia:
    asistencia = db.get(Asistencia, (idCurso, idAlumno, fecha))
    if not asistencia:
        raise HTTPException(status_code=404, detail="Asistencia no encontrada")

    if not asistencia.certificado_path:
        raise HTTPException(
            status_code=400,
            detail="Esta inasistencia no tiene certificado médico adjunto"
        )

    asistencia.certificado_estado = payload.accion
    asistencia.revisado_por       = revisado_por_id

    if payload.accion == CertificadoEstado.aprobado:
        if not payload.dias_justificacion:
            raise HTTPException(
                status_code=400,
                detail="Se requieren los días de justificación para aprobar"
            )

        justificado_hasta = fecha + timedelta(days=payload.dias_justificacion - 1)
        asistencia.justificado_hasta = justificado_hasta

        stmt_rango = select(Asistencia).where(
            Asistencia.idCurso  == idCurso,
            Asistencia.idAlumno == idAlumno,
            Asistencia.estado   == "Ausente",
            Asistencia.fecha    >= fecha,
            Asistencia.fecha    <= justificado_hasta,
        )
        inasistencias_en_rango = db.exec(stmt_rango).all()

        for inasistencia in inasistencias_en_rango:
            inasistencia.estado = AsistenciaEstado.Justificado
            db.add(inasistencia)

    db.add(asistencia)
    db.commit()
    db.refresh(asistencia)

    return asistencia