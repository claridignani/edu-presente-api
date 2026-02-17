# app/services/alerta_service.py
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from fastapi import HTTPException
from sqlmodel import select
from sqlalchemy import func, and_, or_, desc

from app.dependencies import SessionDep
from app.models.alerta import Alerta, EstadoAlerta, MotivoAlerta
from app.models.asistencia import Asistencia
from app.models.alumno import Alumno
from app.models.curso import Curso
from app.models.inscriptos import Inscriptos
from app.models.intervencion import Intervencion
from app.schemas.alerta import AlertaListItem, AlertaPatch, AlertaCreate
from app.schemas.intervencion import IntervencionCreate, IntervencionPublic


# -----------------------------
# Helpers tags <-> varchar(200)
# -----------------------------
def _tags_to_db(tags: list[str] | None) -> str | None:
    if not tags:
        return None
    clean = [t.strip() for t in tags if t and t.strip()]
    if not clean:
        return None
    # evita comas raras / espacios
    return ",".join(clean)[:200]


def _tags_from_db(tags: str | None) -> list[str] | None:
    if not tags:
        return None
    parts = [p.strip() for p in tags.split(",")]
    out = [p for p in parts if p]
    return out or None


# -----------------------------
# Días de clase = fechas con asistencia del curso
# -----------------------------
def _ultimas_fechas_clase(db: SessionDep, idCurso: int, hasta: date, n: int) -> list[date]:
    stmt = (
        select(Asistencia.fecha)
        .where(and_(Asistencia.idCurso == idCurso, Asistencia.fecha <= hasta))
        .group_by(Asistencia.fecha)
        .order_by(desc(Asistencia.fecha))
        .limit(n)
    )
    fechas = db.exec(stmt).all()
    return list(fechas)

def list_intervenciones(db: SessionDep, idAlerta: int) -> list[IntervencionPublic]:
    # valida alerta
    alerta = db.get(Alerta, idAlerta)
    if not alerta:
        raise HTTPException(status_code=404, detail="Alerta no encontrada")

    stmt = (
        select(Intervencion)
        .where(Intervencion.idAlerta == idAlerta)
        .order_by(desc(Intervencion.created_at), desc(Intervencion.idIntervencion))
    )
    items = db.exec(stmt).all()

    return [
        IntervencionPublic(
            idIntervencion=int(i.idIntervencion),
            idAlerta=int(i.idAlerta),
            tipo=i.tipo,
            detalle=i.detalle,
            created_by=i.created_by,
            created_at=i.created_at,
        )
        for i in items
    ]

def _inscripcion_activa_para_fecha(db: SessionDep, idCurso: int, idAlumno: int, dia: date) -> Optional[Inscriptos]:
    stmt = (
        select(Inscriptos)
        .where(
            and_(
                Inscriptos.idCurso == idCurso,
                Inscriptos.idAlumno == idAlumno,
                Inscriptos.activo.is_(True),
                Inscriptos.fechaAlta <= dia,
                (Inscriptos.fechaBaja.is_(None) | (Inscriptos.fechaBaja >= dia)),
            )
        )
        .order_by(desc(Inscriptos.fechaAlta))
        .limit(1)
    )
    return db.exec(stmt).first()


def _ya_existe_alerta_activa(db: SessionDep, cue: str, idCurso: int, idAlumno: int) -> bool:
    stmt = (
        select(Alerta.idAlerta)
        .where(
            and_(
                Alerta.cue == cue,
                Alerta.idCurso == idCurso,
                Alerta.idAlumno == idAlumno,
                Alerta.motivo == MotivoAlerta.INASISTENCIAS_CONSECUTIVAS,
                Alerta.estado != EstadoAlerta.RESUELTO,
                Alerta.archivada.is_(False),
            )
        )
        .limit(1)
    )
    return db.exec(stmt).first() is not None

def _ya_existe_alerta_activa_motivo(db: SessionDep, cue: str, idCurso: int, idAlumno: int, motivo: MotivoAlerta) -> bool:
    stmt = (
        select(Alerta.idAlerta)
        .where(
            and_(
                Alerta.cue == cue,
                Alerta.idCurso == idCurso,
                Alerta.idAlumno == idAlumno,
                Alerta.motivo == motivo,
                Alerta.estado != EstadoAlerta.RESUELTO,
                Alerta.archivada.is_(False),
            )
        )
        .limit(1)
    )
    return db.exec(stmt).first() is not None

# -----------------------------
# ✅ Generación automática (enganchar desde upsert)
# -----------------------------
def check_y_crear_alertas_consecutivas_para_curso_fecha(
    db: SessionDep,
    idCurso: int,
    fecha: date,
    min_consecutivas: int = 3,
):
    curso = db.get(Curso, idCurso)
    if not curso:
        return

    cue = curso.CUE

    ult_fechas = _ultimas_fechas_clase(db, idCurso=idCurso, hasta=fecha, n=min_consecutivas)
    if len(ult_fechas) < min_consecutivas:
        return

    ult_fechas_sorted = sorted(ult_fechas)

    stmt_ausentes_hoy = (
        select(Asistencia.idAlumno)
        .where(
            and_(
                Asistencia.idCurso == idCurso,
                Asistencia.fecha == fecha,
                Asistencia.estado == "Ausente",
            )
        )
    )
    candidatos = [int(x) for x in db.exec(stmt_ausentes_hoy).all()]
    if not candidatos:
        return

    for idAlumno in candidatos:
        insc = _inscripcion_activa_para_fecha(db, idCurso, idAlumno, fecha)
        if not insc:
            continue

        if _ya_existe_alerta_activa(db, cue, idCurso, idAlumno):
            continue

        stmt_check = (
            select(func.count())
            .select_from(Asistencia)
            .where(
                and_(
                    Asistencia.idCurso == idCurso,
                    Asistencia.idAlumno == idAlumno,
                    Asistencia.fecha.in_(ult_fechas_sorted),
                    Asistencia.estado == "Ausente",
                )
            )
        )
        cnt_row = db.exec(stmt_check).one()
        cnt = int(cnt_row or 0)

        if cnt == min_consecutivas:
            alerta = Alerta(
                cue=cue,
                idCurso=idCurso,
                idAlumno=idAlumno,
                motivo=MotivoAlerta.INASISTENCIAS_CONSECUTIVAS,
                estado=EstadoAlerta.PENDIENTE,
                consecutivas=min_consecutivas,
                fechaInicioRacha=ult_fechas_sorted[0],
                fechaFinRacha=ult_fechas_sorted[-1],
                archivada=False,
            )
            db.add(alerta)

    db.commit()


# -----------------------------
# ✅ Listado para la grilla (Asistente)
# -----------------------------
def list_alertas(
    db: SessionDep,
    cue: str,
    q: str | None = None,
    curso_id: int | None = None,
    estado: EstadoAlerta | None = None,
    desde: date | None = None,
    hasta: date | None = None,
    archivadas: bool | None = False,
):
    stmt = (
        select(
            Alerta,
            Alumno.nombre,
            Alumno.apellido,
            Alumno.dni,
            Curso.nombre.label("cursoNombre"),
            Curso.division,
            Curso.cicloLectivo,
        )
        .select_from(Alerta, Alumno, Curso)
        .where(
            and_(
                Alerta.cue == cue,
                Alerta.idAlumno == Alumno.idAlumno,
                Alerta.idCurso == Curso.idCurso,
            )
        )
        .order_by(desc(Alerta.fechaFinRacha), desc(Alerta.idAlerta))
    )

    if archivadas is False:
        stmt = stmt.where(Alerta.archivada.is_(False))
    elif archivadas is True:
        stmt = stmt.where(Alerta.archivada.is_(True))

    if curso_id:
        stmt = stmt.where(Alerta.idCurso == curso_id)

    if estado:
        stmt = stmt.where(Alerta.estado == estado)

    if desde:
        stmt = stmt.where(Alerta.fechaFinRacha >= desde)

    if hasta:
        stmt = stmt.where(Alerta.fechaFinRacha <= hasta)

    if q and q.strip():
        qq = q.strip().lower()
        stmt = stmt.where(
            or_(
                func.lower(Alumno.nombre).like(f"%{qq}%"),
                func.lower(Alumno.apellido).like(f"%{qq}%"),
                func.lower(Alumno.dni).like(f"%{qq}%"),
            )
        )

    rows = db.exec(stmt).all()

    out: list[AlertaListItem] = []
    for alerta, nom, ape, dni, cursoNom, div, ciclo in rows:
        curso_str = f"{cursoNom} {div} ({ciclo})".strip()
        out.append(
            AlertaListItem(
                idAlerta=int(alerta.idAlerta),
                cue=alerta.cue,
                idAlumno=int(alerta.idAlumno),
                alumnoNombre=f"{ape}, {nom}",
                alumnoDni=dni,
                idCurso=int(alerta.idCurso),
                curso=curso_str,
                motivo=alerta.motivo,
                consecutivas=int(alerta.consecutivas),
                fechaInicioRacha=alerta.fechaInicioRacha,
                fechaFinRacha=alerta.fechaFinRacha,
                estado=alerta.estado,
                ultimaAccionAt=alerta.ultimaAccionAt,
                archivada=bool(alerta.archivada),
            )
        )
    return out


def patch_alerta(db: SessionDep, idAlerta: int, patch: AlertaPatch) -> Alerta:
    alerta = db.get(Alerta, idAlerta)
    if not alerta:
        raise HTTPException(status_code=404, detail="Alerta no encontrada")

    data = patch.model_dump(exclude_unset=True)

    if "estado" in data and data["estado"] == EstadoAlerta.RESUELTO:
        alerta.resueltaAt = datetime.utcnow()

    for k, v in data.items():
        setattr(alerta, k, v)

    db.add(alerta)
    db.commit()
    db.refresh(alerta)
    return alerta


def add_intervencion(db: SessionDep, idAlerta: int, payload: IntervencionCreate) -> IntervencionPublic:
    alerta = db.get(Alerta, idAlerta)
    if not alerta:
        raise HTTPException(status_code=404, detail="Alerta no encontrada")

    inter = Intervencion(
        idAlerta=idAlerta,
        tipo=payload.tipo,
        detalle=payload.detalle,
        created_by=payload.created_by,
        # opcional si ya lo sumaste al schema (si no, borrá estas 2 líneas)
        detalleFormal=getattr(payload, "detalleFormal", None),
        tags=",".join(getattr(payload, "tags", []) or []) if getattr(payload, "tags", None) else None,
    )
    db.add(inter)

    alerta.ultimaAccionAt = datetime.utcnow()
    if alerta.estado == EstadoAlerta.PENDIENTE:
        alerta.estado = EstadoAlerta.EN_PROCESO

    db.add(alerta)
    db.commit()
    db.refresh(inter)

    return IntervencionPublic(
        idIntervencion=int(inter.idIntervencion),
        idAlerta=int(inter.idAlerta),
        tipo=inter.tipo,
        detalle=inter.detalle,
        created_by=inter.created_by,
        created_at=inter.created_at,
    )
def create_alerta(db: SessionDep, payload: AlertaCreate) -> Alerta:
    """
    Crea una alerta manual desde el front (Asistente).
    - valida curso y alumno
    - valida que el curso pertenezca al CUE
    - (opcional) valida inscripción activa del alumno en ese curso a la fecha de hoy
    - evita duplicados activos por mismo motivo (no resueltas y no archivadas)
    """
    # 1) valida curso
    curso = db.get(Curso, payload.idCurso)
    if not curso:
        raise HTTPException(status_code=404, detail="Curso no encontrado")

    # 2) valida CUE: el CUE viene del payload y debe coincidir con el curso
    if str(curso.CUE) != str(payload.cue):
        raise HTTPException(status_code=400, detail="El curso no pertenece al CUE indicado")

    # 3) valida alumno
    alumno = db.get(Alumno, payload.idAlumno)
    if not alumno:
        raise HTTPException(status_code=404, detail="Alumno no encontrado")

    # 4) valida inscripción activa (si querés que sea estricta)
    hoy = date.today()
    insc = _inscripcion_activa_para_fecha(db, payload.idCurso, payload.idAlumno, hoy)

    # ✅ Para alertas manuales NO bloqueamos.
    # Si querés, lo dejamos como “soft validation” (log) y seguimos.
    # Si preferís que bloquee solo para motivo INASISTENCIAS_CONSECUTIVAS, también se puede.
    if not insc:
        # no raise
        pass


    # 5) evita duplicado activo por motivo
    if _ya_existe_alerta_activa_motivo(db, payload.cue, payload.idCurso, payload.idAlumno, payload.motivo):
        raise HTTPException(
            status_code=409,
            detail="Ya existe una alerta activa para este alumno/curso/motivo",
        )

    # 6) crea alerta
    alerta = Alerta(
        cue=payload.cue,
        idCurso=payload.idCurso,
        idAlumno=payload.idAlumno,
        motivo=payload.motivo,
        estado=payload.estado,
        archivada=False,
        # para alertas manuales, estas 3 quedan “neutras”
        consecutivas=payload.consecutivas or 0,
        fechaInicioRacha=payload.fechaInicioRacha or hoy,
        fechaFinRacha=payload.fechaFinRacha or hoy,
    )

    # Si tu modelo Alerta tiene campo "detalle", lo seteamos sin romper si no existe
    if hasattr(alerta, "detalle"):
        setattr(alerta, "detalle", payload.detalle)

    # created_by si existe en modelo
    if hasattr(alerta, "created_by"):
        setattr(alerta, "created_by", payload.created_by)

    db.add(alerta)
    db.commit()
    db.refresh(alerta)
    return alerta
