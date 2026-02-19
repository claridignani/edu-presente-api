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
# ✅ Snapshot actor (nombre + rol) para auditoría
# -----------------------------
def _actor_snapshot(db: SessionDep, actor_id: int | None, cue: str) -> tuple[str | None, str | None]:
    """
    Devuelve (actor_nombre, actor_rol) para guardar snapshot.
    actor_nombre: "Apellido, Nombre"
    actor_rol: "Asistente" | "Director" | "Docente" | "Administrador"
    """
    if not actor_id:
        return (None, None)

    cue_norm = (cue or "").strip()

    # Usuario
    u = db.get(Usuario, int(actor_id))
    actor_nombre = None
    if u:
        ape = (u.apellido or "").strip()
        nom = (u.nombre or "").strip()
        actor_nombre = f"{ape}, {nom}".strip(", ").strip() or None

    # Rol por CUE
    stmt = select(Rol).where(Rol.idUsuario == int(actor_id), Rol.CUE == cue_norm).limit(1)
    r = db.exec(stmt).first()

    actor_rol = None
    if r:
        desc = getattr(r, "descripcion", None)
        actor_rol = desc.value if hasattr(desc, "value") else (str(desc) if desc else None)

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
    fechas = db.exec(stmt).all()
    return list(fechas)


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
            now = datetime.utcnow()
            alerta.created_at = now
            alerta.ultimaAccionAt = now

            db.add(alerta)

    db.commit()

def check_y_crear_alertas_tardanzas_para_curso_fecha(
    db: SessionDep,
    idCurso: int,
    fecha: date,
    umbral: int = 3,  # "más de 3" => dispara en 4
):
    """
    Crea alerta automática por LLEGADAS_TARDE cuando un alumno acumula
    más de 'umbral' tardanzas dentro del ciclo lectivo del curso (o año de la fecha).
    Se dispara mirando los alumnos que HOY tuvieron estado == "Tarde".
    """
    curso = db.get(Curso, idCurso)
    if not curso:
        return

    cue = curso.CUE

    # Tomamos el año/ciclo lectivo del curso si existe (tu modelo Curso lo tiene),
    # sino usamos el año de la fecha.
    anio = getattr(curso, "cicloLectivo", None) or fecha.year
    desde = date(int(anio), 1, 1)
    hasta = date(int(anio), 12, 31)

    # Alumnos que llegaron tarde en esta fecha (candidatos)
    stmt_tarde_hoy = (
        select(Asistencia.idAlumno)
        .where(
            and_(
                Asistencia.idCurso == idCurso,
                Asistencia.fecha == fecha,
                Asistencia.estado == "Tarde",
            )
        )
    )
    candidatos = [int(x) for x in db.exec(stmt_tarde_hoy).all()]
    if not candidatos:
        return

    for idAlumno in candidatos:
        # Debe estar inscripto/activo ese día
        insc = _inscripcion_activa_para_fecha(db, idCurso, idAlumno, fecha)
        if not insc:
            continue

        # Evitar duplicado activo por este motivo
        if _ya_existe_alerta_activa_motivo(db, cue, idCurso, idAlumno, MotivoAlerta.LLEGADAS_TARDE):
            continue

        # Contar tardanzas en el ciclo/año
        stmt_cnt = (
            select(func.count())
            .select_from(Asistencia)
            .where(
                and_(
                    Asistencia.idCurso == idCurso,
                    Asistencia.idAlumno == idAlumno,
                    Asistencia.fecha >= desde,
                    Asistencia.fecha <= hasta,
                    Asistencia.estado == "Tarde",
                )
            )
        )
        cnt_row = db.exec(stmt_cnt).one()
        cnt = int(cnt_row or 0)

        # "más de 3" => cnt >= 4
        if cnt <= umbral:
            continue

        # Fecha primera y última tardanza del período
        stmt_minmax = (
            select(
                func.min(Asistencia.fecha).label("minf"),
                func.max(Asistencia.fecha).label("maxf"),
            )
            .where(
                and_(
                    Asistencia.idCurso == idCurso,
                    Asistencia.idAlumno == idAlumno,
                    Asistencia.fecha >= desde,
                    Asistencia.fecha <= hasta,
                    Asistencia.estado == "Tarde",
                )
            )
        )
        r = db.exec(stmt_minmax).one()
        fecha_ini = r.minf or fecha
        fecha_fin = r.maxf or fecha

        alerta = Alerta(
            cue=cue,
            idCurso=idCurso,
            idAlumno=idAlumno,
            motivo=MotivoAlerta.LLEGADAS_TARDE,
            estado=EstadoAlerta.PENDIENTE,
            consecutivas=cnt,               # reutilizamos el campo como "cantidad"
            fechaInicioRacha=fecha_ini,     # primera tardanza del período
            fechaFinRacha=fecha_fin,        # última tardanza del período
            archivada=False,
        )
        now = datetime.utcnow()
        alerta.created_at = now
        alerta.ultimaAccionAt = now

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
                created_at=alerta.created_at,
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

    # ✅ sacamos actor_id del patch (no lo seteamos como atributo del modelo Alerta)
    actor_id = data.pop("actor_id", None)

    prev_estado = alerta.estado
    prev_archivada = bool(alerta.archivada)

    # aplicar cambios
    if "estado" in data and data["estado"] == EstadoAlerta.RESUELTO and alerta.estado != EstadoAlerta.RESUELTO:
        alerta.resueltaAt = datetime.utcnow()

    for k, v in data.items():
        setattr(alerta, k, v)

    # ✅ persistimos cambios base
    db.add(alerta)
    db.commit()
    db.refresh(alerta)

    # ✅ registrar eventos si hubo cambios (auditoría)
    actor_nombre, actor_rol = _actor_snapshot(db, actor_id, alerta.cue)

    hubo_cambio = False

    # cambio de estado
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

    # archivar / desarchivar
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

    # ✅ si hubo cambios "reales", actualizamos ultimaAccionAt y comiteamos eventos + timestamp
    if hubo_cambio:
        alerta.ultimaAccionAt = datetime.utcnow()
        db.add(alerta)
        db.commit()
        db.refresh(alerta)

    return alerta

def add_intervencion(db: SessionDep, idAlerta: int, payload: IntervencionCreate) -> IntervencionPublic:
    alerta = db.get(Alerta, idAlerta)
    if not alerta:
        raise HTTPException(status_code=404, detail="Alerta no encontrada")

    # ✅ snapshot del actor (nombre + rol) según el CUE de la alerta
    actor_nombre, actor_rol = _actor_snapshot(db, payload.created_by, alerta.cue)

    inter = Intervencion(
        idAlerta=idAlerta,
        evento=EventoHistorial.INTERVENCION,
        tipo=payload.tipo,
        detalle=payload.detalle,
        created_by=payload.created_by,
        actor_nombre=actor_nombre,
        actor_rol=actor_rol,
        detalleFormal=getattr(payload, "detalleFormal", None),
        tags=_tags_to_db(getattr(payload, "tags", None)),
    )
    db.add(inter)

    # ✅ actualizar metadata de la alerta
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


def create_alerta(db: SessionDep, payload: AlertaCreate) -> Alerta:
    """
    Crea una alerta manual desde el front (Asistente).
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

    hoy = date.today()
    insc = _inscripcion_activa_para_fecha(db, payload.idCurso, payload.idAlumno, hoy)

    # ✅ Para alertas manuales NO bloqueamos.
    if not insc:
        pass

    # 5) evita duplicado activo por motivo
    if _ya_existe_alerta_activa_motivo(db, payload.cue, payload.idCurso, payload.idAlumno, payload.motivo):
        raise HTTPException(status_code=409, detail="Ya existe una alerta activa para este alumno/curso/motivo")

    # 6) crea alerta
    alerta = Alerta(
        cue=payload.cue,
        idCurso=payload.idCurso,
        idAlumno=payload.idAlumno,
        motivo=payload.motivo,
        estado=payload.estado,
        archivada=False,
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
        
    now = datetime.utcnow()
    alerta.created_at = now
    alerta.ultimaAccionAt = now

    db.add(alerta)
    db.commit()
    db.refresh(alerta)
    return alerta
# -----------------------------
# 📊 Estadísticas Director
# -----------------------------
def stats_alertas_activas_por_escuela(
    db: SessionDep,
    cue: str,
):
    """
    Devuelve alertas activas (no archivadas y no resueltas)
    para usar como 'Alumnos en riesgo' en el panel del Director.
    """

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
            [
                EstadoAlerta.PENDIENTE,
                EstadoAlerta.EN_PROCESO,
                EstadoAlerta.CRITICO,
            ]
        )
    )
        )
        .order_by(desc(Alerta.estado), desc(Alerta.created_at))
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
                created_at=alerta.created_at,
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
