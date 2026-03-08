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
from app.models.intervencion import Intervencion, EventoHistorial
from app.schemas.alerta import AlertaListItem, AlertaPatch, AlertaCreate
from app.schemas.intervencion import IntervencionCreate, IntervencionPublic
from app.models.usuario import Usuario
from app.models.rol import Rol
from app.core.encryption import decrypt, hash_for_search


# -----------------------------
# Helpers tags <-> varchar(200)
# -----------------------------
def _tags_to_db(tags: list[str] | None) -> str | None:
    if not tags:
        return None
    clean = [t.strip() for t in tags if t and t.strip()]
    if not clean:
        return None
    return ",".join(clean)[:200]


def _tags_from_db(tags: str | None) -> list[str] | None:
    if not tags:
        return None
    parts = [p.strip() for p in tags.split(",")]
    out = [p for p in parts if p]
    return out or None


# -----------------------------
# Snapshot actor (nombre + rol) para auditoría
# -----------------------------
def _actor_snapshot(db: SessionDep, actor_id: int | None, cue: str) -> tuple[str | None, str | None]:
    if not actor_id:
        return (None, None)

    cue_norm = (cue or "").strip()

    u = db.get(Usuario, int(actor_id))
    actor_nombre = None
    if u:
        ape = (u.apellido or "").strip()
        nom = (u.nombre or "").strip()
        actor_nombre = f"{ape}, {nom}".strip(", ").strip() or None

    stmt = select(Rol).where(Rol.idUsuario == int(actor_id), Rol.CUE == cue_norm).limit(1)
    r = db.exec(stmt).first()

    actor_rol = None
    if r:
        desc_val = getattr(r, "descripcion", None)
        actor_rol = desc_val.value if hasattr(desc_val, "value") else (str(desc_val) if desc_val else None)

    return (actor_nombre, actor_rol)


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
    return list(db.exec(stmt).all())


def list_intervenciones(db: SessionDep, idAlerta: int) -> list[IntervencionPublic]:
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
            evento=i.evento,
            tipo=i.tipo,
            detalle=i.detalle,
            created_by=i.created_by,
            actor_nombre=getattr(i, "actor_nombre", None),
            actor_rol=getattr(i, "actor_rol", None),
            estado_anterior=getattr(i, "estado_anterior", None),
            estado_nuevo=getattr(i, "estado_nuevo", None),
            archivada_anterior=getattr(i, "archivada_anterior", None),
            archivada_nueva=getattr(i, "archivada_nueva", None),
            detalleFormal=getattr(i, "detalleFormal", None),
            tags=_tags_from_db(getattr(i, "tags", None)),
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
# Generación automática
# -----------------------------
def check_y_crear_alertas_consecutivas_para_curso_fecha(
    db, idCurso, fecha, min_consecutivas=3
):
    curso = db.get(Curso, idCurso)
    if not curso:
        return

    cue = curso.CUE
    ult_fechas = _ultimas_fechas_clase(db, idCurso=idCurso, hasta=fecha, n=min_consecutivas)
    if len(ult_fechas) < min_consecutivas:
        return
    ult_fechas_sorted = sorted(ult_fechas)

    candidatos = [
        int(x) for x in db.exec(
            select(Asistencia.idAlumno).where(
                Asistencia.idCurso == idCurso,
                Asistencia.fecha == fecha,
                Asistencia.estado == "Ausente",
            )
        ).all()
    ]
    if not candidatos:
        return

    insc_set = set(
        int(x) for x in db.exec(
            select(Inscriptos.idAlumno).where(
                Inscriptos.idCurso == idCurso,
                Inscriptos.idAlumno.in_(candidatos),
                Inscriptos.activo.is_(True),
            )
        ).all()
    )

    alertas_existentes = set(
        int(x) for x in db.exec(
            select(Alerta.idAlumno).where(
                Alerta.cue == cue,
                Alerta.idCurso == idCurso,
                Alerta.idAlumno.in_(candidatos),
                Alerta.motivo == MotivoAlerta.INASISTENCIAS_CONSECUTIVAS,
                Alerta.estado != EstadoAlerta.RESUELTO,
                Alerta.archivada.is_(False),
            )
        ).all()
    )

    rows_cnt = db.exec(
        select(Asistencia.idAlumno, func.count().label("cnt"))
        .where(
            Asistencia.idCurso == idCurso,
            Asistencia.idAlumno.in_(candidatos),
            Asistencia.fecha.in_(ult_fechas_sorted),
            Asistencia.estado == "Ausente",
        )
        .group_by(Asistencia.idAlumno)
    ).all()
    conteo_map = {int(r.idAlumno): int(r.cnt) for r in rows_cnt}

    now = datetime.utcnow()
    for idAlumno in candidatos:
        if idAlumno not in insc_set:
            continue
        if idAlumno in alertas_existentes:
            continue
        if conteo_map.get(idAlumno, 0) != min_consecutivas:
            continue
        db.add(Alerta(
            cue=cue, idCurso=idCurso, idAlumno=idAlumno,
            motivo=MotivoAlerta.INASISTENCIAS_CONSECUTIVAS,
            estado=EstadoAlerta.PENDIENTE,
            consecutivas=min_consecutivas,
            fechaInicioRacha=ult_fechas_sorted[0],
            fechaFinRacha=ult_fechas_sorted[-1],
            archivada=False,
            created_at=now,
            ultimaAccionAt=now,
        ))

    db.commit()


def check_y_crear_alertas_tardanzas_para_curso_fecha(
    db, idCurso, fecha, umbral=3
):
    curso = db.get(Curso, idCurso)
    if not curso:
        return

    cue = curso.CUE
    anio = getattr(curso, "cicloLectivo", None) or fecha.year
    desde = date(int(anio), 1, 1)
    hasta = date(int(anio), 12, 31)

    candidatos = [
        int(x) for x in db.exec(
            select(Asistencia.idAlumno).where(
                Asistencia.idCurso == idCurso,
                Asistencia.fecha == fecha,
                Asistencia.estado == "Tarde",
            )
        ).all()
    ]
    if not candidatos:
        return

    insc_set = set(
        int(x) for x in db.exec(
            select(Inscriptos.idAlumno).where(
                Inscriptos.idCurso == idCurso,
                Inscriptos.idAlumno.in_(candidatos),
                Inscriptos.activo.is_(True),
            )
        ).all()
    )

    alertas_existentes = set(
        int(x) for x in db.exec(
            select(Alerta.idAlumno).where(
                Alerta.cue == cue,
                Alerta.idCurso == idCurso,
                Alerta.idAlumno.in_(candidatos),
                Alerta.motivo == MotivoAlerta.LLEGADAS_TARDE,
                Alerta.estado != EstadoAlerta.RESUELTO,
                Alerta.archivada.is_(False),
            )
        ).all()
    )

    rows_tard = db.exec(
        select(
            Asistencia.idAlumno,
            func.count().label("cnt"),
            func.min(Asistencia.fecha).label("minf"),
            func.max(Asistencia.fecha).label("maxf"),
        )
        .where(
            Asistencia.idCurso == idCurso,
            Asistencia.idAlumno.in_(candidatos),
            Asistencia.fecha >= desde,
            Asistencia.fecha <= hasta,
            Asistencia.estado == "Tarde",
        )
        .group_by(Asistencia.idAlumno)
    ).all()
    tardes_map = {int(r.idAlumno): (int(r.cnt), r.minf, r.maxf) for r in rows_tard}

    now = datetime.utcnow()
    for idAlumno in candidatos:
        if idAlumno not in insc_set:
            continue
        if idAlumno in alertas_existentes:
            continue
        cnt, fecha_ini, fecha_fin = tardes_map.get(idAlumno, (0, fecha, fecha))
        if cnt <= umbral:
            continue
        db.add(Alerta(
            cue=cue, idCurso=idCurso, idAlumno=idAlumno,
            motivo=MotivoAlerta.LLEGADAS_TARDE,
            estado=EstadoAlerta.PENDIENTE,
            consecutivas=cnt,
            fechaInicioRacha=fecha_ini or fecha,
            fechaFinRacha=fecha_fin or fecha,
            archivada=False,
            created_at=now,
            ultimaAccionAt=now,
        ))

    db.commit()


# -----------------------------
# Listado para la grilla (Asistente)
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
        .order_by(desc(Alerta.created_at), desc(Alerta.idAlerta))
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

    # Búsqueda por q: nombre/apellido con ilike, DNI con hash exacto
    if q and q.strip():
        qq = q.strip()
        like = f"%{qq.lower()}%"
        if qq.isdigit():
            dni_hash_q = hash_for_search(qq)
            stmt = stmt.where(
                or_(
                    func.lower(Alumno.nombre).like(like),
                    func.lower(Alumno.apellido).like(like),
                    Alumno.dni_hash == dni_hash_q,        # ← FIX
                )
            )
        else:
            stmt = stmt.where(
                or_(
                    func.lower(Alumno.nombre).like(like),
                    func.lower(Alumno.apellido).like(like),
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
                alumnoDni=decrypt(dni) if dni else dni,    # ← FIX
                idCurso=int(alerta.idCurso),
                created_at=alerta.created_at,
                curso=curso_str,
                motivo=alerta.motivo,
                consecutivas=int(alerta.consecutivas),
                fechaInicioRacha=alerta.fechaInicioRacha,
                fechaFinRacha=alerta.fechaFinRacha,
                estado=alerta.estado,
                ultimaAccionAt=alerta.ultimaAccionAt,
                archivada=bool(alerta.archivada),
                detalle=getattr(alerta, "detalle", None),
            )
        )
    return out


def patch_alerta(
    db: SessionDep,
    idAlerta: int,
    patch: AlertaPatch,
    actor_user_id: int | None = None,
) -> Alerta:
    alerta = db.get(Alerta, idAlerta)
    if not alerta:
        raise HTTPException(status_code=404, detail="Alerta no encontrada")

    data = patch.model_dump(exclude_unset=True)
    actor_id = actor_user_id if actor_user_id is not None else data.pop("actor_id", None)

    prev_estado = alerta.estado
    prev_archivada = bool(alerta.archivada)

    if "estado" in data and data["estado"] == EstadoAlerta.RESUELTO and alerta.estado != EstadoAlerta.RESUELTO:
        alerta.resueltaAt = datetime.utcnow()

    for k, v in data.items():
        setattr(alerta, k, v)

    db.add(alerta)
    db.commit()
    db.refresh(alerta)

    actor_nombre, actor_rol = _actor_snapshot(db, actor_id, alerta.cue)
    hubo_cambio = False

    if "estado" in data and prev_estado != alerta.estado:
        hubo_cambio = True
        ev = Intervencion(
            idAlerta=idAlerta,
            evento=EventoHistorial.CAMBIO_ESTADO,
            tipo=None,
            detalle=f"El estado de la alerta cambió de {prev_estado.value} a {alerta.estado.value}.",
            created_by=actor_id,
            actor_nombre=actor_nombre,
            actor_rol=actor_rol,
            estado_anterior=prev_estado,
            estado_nuevo=alerta.estado,
        )
        db.add(ev)

    if "archivada" in data and prev_archivada != bool(alerta.archivada):
        hubo_cambio = True
        nuevo = bool(alerta.archivada)
        ev = Intervencion(
            idAlerta=idAlerta,
            evento=EventoHistorial.ARCHIVADO if nuevo else EventoHistorial.DESARCHIVADO,
            tipo=None,
            detalle="Alerta archivada" if nuevo else "Alerta desarchivada",
            created_by=actor_id,
            actor_nombre=actor_nombre,
            actor_rol=actor_rol,
            archivada_anterior=prev_archivada,
            archivada_nueva=nuevo,
        )
        db.add(ev)

    if hubo_cambio:
        alerta.ultimaAccionAt = datetime.utcnow()
        db.add(alerta)
        db.commit()
        db.refresh(alerta)

    return alerta


def add_intervencion(
    db: SessionDep,
    idAlerta: int,
    payload: IntervencionCreate,
    actor_user_id: int | None = None,
) -> IntervencionPublic:
    alerta = db.get(Alerta, idAlerta)
    if not alerta:
        raise HTTPException(status_code=404, detail="Alerta no encontrada")

    actor_id = actor_user_id if actor_user_id is not None else getattr(payload, "created_by", None)
    actor_nombre, actor_rol = _actor_snapshot(db, actor_id, alerta.cue)

    inter = Intervencion(
        idAlerta=idAlerta,
        evento=EventoHistorial.INTERVENCION,
        tipo=payload.tipo,
        detalle=payload.detalle,
        created_by=actor_id,
        actor_nombre=actor_nombre,
        actor_rol=actor_rol,
        detalleFormal=getattr(payload, "detalleFormal", None),
        tags=_tags_to_db(getattr(payload, "tags", None)),
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
        evento=inter.evento,
        tipo=inter.tipo,
        detalle=inter.detalle,
        created_by=inter.created_by,
        actor_nombre=inter.actor_nombre,
        actor_rol=inter.actor_rol,
        estado_anterior=getattr(inter, "estado_anterior", None),
        estado_nuevo=getattr(inter, "estado_nuevo", None),
        archivada_anterior=getattr(inter, "archivada_anterior", None),
        archivada_nueva=getattr(inter, "archivada_nueva", None),
        detalleFormal=getattr(inter, "detalleFormal", None),
        tags=_tags_from_db(getattr(inter, "tags", None)),
        created_at=inter.created_at,
    )


def create_alerta(
    db: SessionDep,
    payload: AlertaCreate,
    actor_user_id: int | None = None,
) -> Alerta:
    curso = db.get(Curso, payload.idCurso)
    if not curso:
        raise HTTPException(status_code=404, detail="Curso no encontrado")

    if str(curso.CUE) != str(payload.cue):
        raise HTTPException(status_code=400, detail="El curso no pertenece al CUE indicado")

    alumno = db.get(Alumno, payload.idAlumno)
    if not alumno:
        raise HTTPException(status_code=404, detail="Alumno no encontrado")

    hoy = date.today()
    _inscripcion_activa_para_fecha(db, payload.idCurso, payload.idAlumno, hoy)

    if _ya_existe_alerta_activa_motivo(db, payload.cue, payload.idCurso, payload.idAlumno, payload.motivo):
        raise HTTPException(status_code=409, detail="Ya existe una alerta activa para este alumno/curso/motivo")

    alerta = Alerta(
        cue=payload.cue,
        idCurso=payload.idCurso,
        idAlumno=payload.idAlumno,
        motivo=payload.motivo,
        estado=payload.estado,
        detalle=payload.detalle,
        archivada=False,
        consecutivas=payload.consecutivas or 0,
        fechaInicioRacha=payload.fechaInicioRacha or hoy,
        fechaFinRacha=payload.fechaFinRacha or hoy,
    )

    if hasattr(alerta, "detalle"):
        setattr(alerta, "detalle", payload.detalle)

    actor_id = actor_user_id if actor_user_id is not None else getattr(payload, "created_by", None)
    if hasattr(alerta, "created_by"):
        setattr(alerta, "created_by", actor_id)

    now = datetime.utcnow()
    alerta.created_at = now
    alerta.ultimaAccionAt = now

    db.add(alerta)
    db.commit()
    db.refresh(alerta)
    return alerta


# -----------------------------
# Estadísticas Director
# -----------------------------
def stats_alertas_activas_por_escuela(
    db: SessionDep,
    cue: str,
    desde: Optional[date] = None,
    hasta: Optional[date] = None,
    curso_ids: Optional[list[int]] = None,
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
                Alerta.archivada.is_(False),
                Alerta.estado.in_(
                    [EstadoAlerta.PENDIENTE, EstadoAlerta.EN_PROCESO, EstadoAlerta.CRITICO]
                ),
            )
        )
    )

    if desde:
        stmt = stmt.where(Alerta.fechaInicioRacha >= desde)
    if hasta:
        stmt = stmt.where(Alerta.fechaInicioRacha <= hasta)
    if curso_ids:
        stmt = stmt.where(Alerta.idCurso.in_(curso_ids))

    stmt = stmt.order_by(desc(Alerta.estado), desc(Alerta.created_at))
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
                alumnoDni=decrypt(dni) if dni else dni,    # ← FIX
                idCurso=int(alerta.idCurso),
                created_at=alerta.created_at,
                curso=curso_str,
                motivo=alerta.motivo,
                consecutivas=int(alerta.consecutivas),
                fechaInicioRacha=alerta.fechaInicioRacha,
                fechaFinRacha=alerta.fechaFinRacha,
                detalle=getattr(alerta, "detalle", None),
                estado=alerta.estado,
                ultimaAccionAt=alerta.ultimaAccionAt,
                archivada=bool(alerta.archivada),
            )
        )

    return out
def get_historial_alertas_por_alumno(
    db: SessionDep,
    idAlumno: int,
    cue: str,
) -> list:
    from app.schemas.alerta import AlertaResumenAlumno
    from sqlalchemy import func

    sub_intervenciones = (
        select(
            Intervencion.idAlerta.label("idAlerta"),
            func.count(Intervencion.idIntervencion).label("total"),
        )
        .group_by(Intervencion.idAlerta)
        .subquery()
    )

    stmt = (
        select(
            Alerta,
            Curso.nombre.label("cursoNombre"),
            Curso.division,
            sub_intervenciones.c.total.label("totalIntervenciones"),
        )
        .join(Curso, Curso.idCurso == Alerta.idCurso)
        .outerjoin(sub_intervenciones, sub_intervenciones.c.idAlerta == Alerta.idAlerta)
        .where(
            and_(
                Alerta.idAlumno == idAlumno,
                Alerta.cue == cue,
            )
        )
        .order_by(desc(Alerta.created_at))
    )

    rows = db.exec(stmt).all()

    return [
        AlertaResumenAlumno(
            idAlerta=int(alerta.idAlerta),
            motivo=alerta.motivo,
            estado=alerta.estado,
            fechaCreacion=alerta.created_at,
            curso=f"{cursoNombre} {division}".strip(),
            consecutivas=int(alerta.consecutivas),
            totalIntervenciones=int(totalIntervenciones or 0),
            resuelta=alerta.estado == EstadoAlerta.RESUELTO,
            archivada=bool(alerta.archivada),
        )
        for alerta, cursoNombre, division, totalIntervenciones in rows
    ]


def list_alertas_docente(
    db: SessionDep,
    cue: str,
    docente_id: int,
    archivadas: bool = False,
) -> list[AlertaListItem]:
    motivos_permitidos = [
        MotivoAlerta.PEDAGOGICO,
        MotivoAlerta.SALUD,
        MotivoAlerta.CONDUCTA,
    ]

    has_created_by = (
        hasattr(Alerta, "created_by") and
        "created_by" in Alerta.__table__.columns
    )

    conditions = [
        Alerta.cue == cue,
        Alerta.idAlumno == Alumno.idAlumno,
        Alerta.idCurso == Curso.idCurso,
        Alerta.motivo.in_(motivos_permitidos),
    ]

    if has_created_by:
        conditions.append(Alerta.created_by == docente_id)

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
        .where(and_(*conditions))
        .order_by(desc(Alerta.created_at), desc(Alerta.idAlerta))
    )

    if not archivadas:
        stmt = stmt.where(Alerta.archivada.is_(False))
    else:
        stmt = stmt.where(Alerta.archivada.is_(True))

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
                alumnoDni=decrypt(dni) if dni else None,
                idCurso=int(alerta.idCurso),
                created_at=alerta.created_at,
                curso=curso_str,
                motivo=alerta.motivo,
                consecutivas=int(alerta.consecutivas),
                fechaInicioRacha=alerta.fechaInicioRacha,
                fechaFinRacha=alerta.fechaFinRacha,
                estado=alerta.estado,
                ultimaAccionAt=alerta.ultimaAccionAt,
                archivada=bool(alerta.archivada),
                detalle=getattr(alerta, "detalle", None),
            )
        )
    return out

