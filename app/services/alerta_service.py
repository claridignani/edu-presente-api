# app/services/alerta_service.py
from __future__ import annotations

from datetime import date
from app.core.datetime_utils import now_arg
from typing import Optional

from fastapi import HTTPException
from sqlmodel import select
from sqlalchemy import func, and_, or_, desc, text, Text
from sqlalchemy import Column

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
# Helpers fechas <-> Text
# -----------------------------
def _fechas_to_db(fechas: list[date] | None) -> str | None:
    if not fechas:
        return None
    return ",".join(str(f) for f in sorted(set(fechas)))


def _fechas_from_db(fechas_str: str | None) -> list[date]:
    if not fechas_str:
        return []
    out = []
    for part in fechas_str.split(","):
        part = part.strip()
        if part:
            try:
                out.append(date.fromisoformat(part))
            except ValueError:
                pass
    return sorted(set(out))


def _merge_fechas(existing: str | None, nuevas: list[date]) -> str:
    """Agrega nuevas fechas a las existentes sin duplicar."""
    old = _fechas_from_db(existing)
    merged = sorted(set(old + nuevas))
    return _fechas_to_db(merged) or ""


# -----------------------------
# Helpers motivos_ausencia <-> JSON string
# -----------------------------
import json as _json

def _build_motivos_ausencia(db, idCurso: int, idAlumno: int, fechas: list[date]) -> str | None:
    """
    Consulta asistencia para las fechas dadas y construye un JSON de motivos.

    Resultados posibles:
      {"general": "Enfermedad", "tieneJustificadas": false}
      {"porFecha": {"2026-03-05": "Enfermedad", "2026-03-06": "Viaje"}, "tieneJustificadas": true}
      None  — si ninguna fecha tiene motivo ni justificación
    """
    if not fechas:
        return None

    rows = db.exec(
        select(
            Asistencia.fecha,
            Asistencia.motivo_ausencia,
            Asistencia.estado,
            Asistencia.certificado_estado,
        )
        .where(
            Asistencia.idCurso == idCurso,
            Asistencia.idAlumno == idAlumno,
            Asistencia.fecha.in_(fechas),
        )
    ).all()

    if not rows:
        return None

    motivos_por_fecha: dict[str, str] = {}
    tiene_justificadas = False

    for row in rows:
        motivo = (getattr(row, "motivo_ausencia", None) or "").strip()
        if motivo:
            motivos_por_fecha[str(row.fecha)] = motivo

        estado_val = str(getattr(row, "estado", "") or "").lower()
        cert_val   = str(getattr(row, "certificado_estado", "") or "").lower()
        if estado_val == "justificado" or cert_val == "aprobado":
            tiene_justificadas = True

    if not motivos_por_fecha and not tiene_justificadas:
        return None

    resultado: dict = {"tieneJustificadas": tiene_justificadas}

    if motivos_por_fecha:
        valores_unicos = set(motivos_por_fecha.values())
        if len(valores_unicos) == 1:
            resultado["general"] = next(iter(valores_unicos))
        else:
            resultado["porFecha"] = motivos_por_fecha

    return _json.dumps(resultado, ensure_ascii=False)



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


# -----------------------------
# Racha consecutiva real hacia atrás
# -----------------------------
def _calcular_racha_consecutiva(
    db, idCurso: int, idAlumno: int, hasta: date, estado: str
) -> int:
    """
    Cuenta cuántos días de CLASE consecutivos (hacia atrás desde `hasta`)
    el alumno tuvo el estado indicado ('Ausente' o 'Tarde').

    Usa las fechas de clase del CURSO (días donde cualquier alumno tiene
    registro) como referencia, NO el calendario. Así los fines de semana
    y feriados no cortan la racha.
    """
    # 1. Obtener todas las fechas de clase del curso hasta `hasta`, desc
    stmt_fechas_clase = (
        select(Asistencia.fecha)
        .where(
            Asistencia.idCurso == idCurso,
            Asistencia.fecha <= hasta,
        )
        .group_by(Asistencia.fecha)
        .order_by(desc(Asistencia.fecha))
        .limit(60)
    )
    fechas_clase = [r for r in db.exec(stmt_fechas_clase).all()]

    if not fechas_clase:
        return 0

    # 2. Obtener el estado del alumno en esas fechas
    stmt_alumno = (
        select(Asistencia.fecha, Asistencia.estado)
        .where(
            Asistencia.idCurso == idCurso,
            Asistencia.idAlumno == idAlumno,
            Asistencia.fecha.in_(fechas_clase),
        )
    )
    estado_map = {row.fecha: row.estado for row in db.exec(stmt_alumno).all()}

    # 3. Recorrer las fechas de clase en orden desc y contar la racha
    racha = 0
    for f in fechas_clase:
        estado_dia = estado_map.get(f)
        if estado_dia == estado:
            racha += 1
        else:
            # Si no tiene registro o tiene otro estado, la racha se corta
            break

    return racha


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


def _get_alerta_activa_motivo(db: SessionDep, cue: str, idCurso: int, idAlumno: int, motivo: MotivoAlerta) -> Alerta | None:
    """
    Devuelve la alerta más reciente para el motivo dado, sin importar si está
    archivada o resuelta. Esto permite actualizarla (y desarchivarla) cuando
    llegan nuevas ausencias/tardanzas.
    """
    stmt = (
        select(Alerta)
        .where(
            and_(
                Alerta.cue == cue,
                Alerta.idCurso == idCurso,
                Alerta.idAlumno == idAlumno,
                Alerta.motivo == motivo,
            )
        )
        .order_by(desc(Alerta.created_at))
        .limit(1)
    )
    return db.exec(stmt).first()


# ============================================================
# Generación automática — 4 tipos de alertas
# ============================================================

# ── Helper interno: desarchivar y reactivar si corresponde ──────────────────
def _reactivar_si_archivada(alerta: Alerta) -> None:
    """
    Si la alerta estaba archivada, la desarchiva.
    Si además estaba RESUELTO, la vuelve a PENDIENTE.
    """
    if alerta.archivada:
        alerta.archivada = False
    if alerta.estado == EstadoAlerta.RESUELTO:
        alerta.estado = EstadoAlerta.PENDIENTE


# ── 1. Inasistencias CONSECUTIVAS (umbral: 3 días seguidos) ─────────────────
def check_y_crear_alertas_consecutivas_para_curso_fecha(
    db, idCurso: int, fecha: date, min_consecutivas: int = 3
):
    """
    Detecta alumnos con >= `min_consecutivas` ausencias consecutivas hasta `fecha`.
    - Si ya existe una alerta (activa, archivada o resuelta), la actualiza con
      el contador real de la racha y las fechas acumuladas, y la desarchiva si
      estaba archivada.
    - Si no existe, crea una nueva cuando se alcanza el umbral por primera vez.
    """
    curso = db.get(Curso, idCurso)
    if not curso:
        return

    cue = curso.CUE
    # Tomamos las últimas N fechas de clase para verificar la ventana mínima
    ult_fechas = _ultimas_fechas_clase(db, idCurso=idCurso, hasta=fecha, n=min_consecutivas)
    if len(ult_fechas) < min_consecutivas:
        return
    ult_fechas_sorted = sorted(ult_fechas)

    # Alumnos ausentes HOY (candidatos a tener racha)
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

    # Contar cuántas de las últimas N fechas de clase estuvo ausente cada candidato
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

    now = now_arg()
    for idAlumno in candidatos:
        if idAlumno not in insc_set:
            continue
        # Debe haber estado ausente en TODAS las últimas N fechas (ventana completa)
        if conteo_map.get(idAlumno, 0) < min_consecutivas:
            continue

        # Racha real acumulada hacia atrás desde hoy
        racha_real = _calcular_racha_consecutiva(db, idCurso, idAlumno, fecha, "Ausente")

        alerta_existente = _get_alerta_activa_motivo(
            db, cue, idCurso, idAlumno, MotivoAlerta.INASISTENCIAS_CONSECUTIVAS
        )
        nuevas_fechas_merged = _fechas_from_db(
            _merge_fechas(getattr(alerta_existente, "fechas", None), ult_fechas_sorted)
            if alerta_existente else _fechas_to_db(ult_fechas_sorted)
        ) if alerta_existente else ult_fechas_sorted

        if alerta_existente:
            alerta_existente.consecutivas = racha_real
            alerta_existente.fechas = _merge_fechas(
                getattr(alerta_existente, "fechas", None), ult_fechas_sorted
            )
            alerta_existente.fechaFinRacha = max(
                alerta_existente.fechaFinRacha or ult_fechas_sorted[-1],
                ult_fechas_sorted[-1],
            )
            alerta_existente.ultimaAccionAt = now
            alerta_existente.motivos_ausencia = _build_motivos_ausencia(
                db, idCurso, idAlumno,
                _fechas_from_db(alerta_existente.fechas)
            )
            _reactivar_si_archivada(alerta_existente)
            db.add(alerta_existente)
        else:
            db.add(Alerta(
                cue=cue,
                idCurso=idCurso,
                idAlumno=idAlumno,
                motivo=MotivoAlerta.INASISTENCIAS_CONSECUTIVAS,
                estado=EstadoAlerta.PENDIENTE,
                consecutivas=racha_real,
                fechaInicioRacha=ult_fechas_sorted[0],
                fechaFinRacha=ult_fechas_sorted[-1],
                fechas=_fechas_to_db(ult_fechas_sorted),
                motivos_ausencia=_build_motivos_ausencia(db, idCurso, idAlumno, ult_fechas_sorted),
                archivada=False,
                created_at=now,
                ultimaAccionAt=now,
            ))

    db.commit()


# ── 2. Inasistencias REITERADAS (umbral: 10 ausencias en el año) ─────────────
def check_y_crear_alertas_reiteradas_para_curso_fecha(
    db, idCurso: int, fecha: date, umbral: int = 10
):
    """
    Detecta alumnos que acumularon >= `umbral` ausencias en el ciclo lectivo.
    - Si ya existe una alerta (activa, archivada o resuelta), siempre actualiza
      el contador y las fechas, y la desarchiva si estaba archivada.
    - Si no existe y se supera el umbral, crea una nueva.
    """
    curso = db.get(Curso, idCurso)
    if not curso:
        return

    cue = curso.CUE
    anio = getattr(curso, "cicloLectivo", None) or fecha.year
    desde_anio = date(int(anio), 1, 1)
    hasta_anio = date(int(anio), 12, 31)

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

    rows_total = db.exec(
        select(
            Asistencia.idAlumno,
            func.count().label("cnt"),
            func.min(Asistencia.fecha).label("minf"),
            func.max(Asistencia.fecha).label("maxf"),
        )
        .where(
            Asistencia.idCurso == idCurso,
            Asistencia.idAlumno.in_(candidatos),
            Asistencia.fecha >= desde_anio,
            Asistencia.fecha <= hasta_anio,
            Asistencia.estado == "Ausente",
        )
        .group_by(Asistencia.idAlumno)
    ).all()
    totales_map = {int(r.idAlumno): (int(r.cnt), r.minf, r.maxf) for r in rows_total}

    rows_fechas = db.exec(
        select(Asistencia.idAlumno, Asistencia.fecha)
        .where(
            Asistencia.idCurso == idCurso,
            Asistencia.idAlumno.in_(candidatos),
            Asistencia.fecha >= desde_anio,
            Asistencia.fecha <= hasta_anio,
            Asistencia.estado == "Ausente",
        )
        .order_by(Asistencia.idAlumno, Asistencia.fecha)
    ).all()
    fechas_por_alumno: dict[int, list[date]] = {}
    for row in rows_fechas:
        aid = int(row.idAlumno)
        fechas_por_alumno.setdefault(aid, []).append(row.fecha)

    now = now_arg()
    for idAlumno in candidatos:
        if idAlumno not in insc_set:
            continue

        cnt, fecha_ini, fecha_fin = totales_map.get(idAlumno, (0, fecha, fecha))
        todas_las_fechas = fechas_por_alumno.get(idAlumno, [fecha])

        alerta_existente = _get_alerta_activa_motivo(
            db, cue, idCurso, idAlumno, MotivoAlerta.INASISTENCIAS_REITERADAS
        )

        if alerta_existente:
            # Siempre actualizamos contador y fechas
            alerta_existente.consecutivas = cnt
            alerta_existente.fechas = _fechas_to_db(todas_las_fechas)
            alerta_existente.fechaFinRacha = fecha_fin or fecha
            alerta_existente.ultimaAccionAt = now
            alerta_existente.motivos_ausencia = _build_motivos_ausencia(
                db, idCurso, idAlumno, todas_las_fechas
            )
            _reactivar_si_archivada(alerta_existente)
            db.add(alerta_existente)
        elif cnt >= umbral:
            db.add(Alerta(
                cue=cue,
                idCurso=idCurso,
                idAlumno=idAlumno,
                motivo=MotivoAlerta.INASISTENCIAS_REITERADAS,
                estado=EstadoAlerta.PENDIENTE,
                consecutivas=cnt,
                fechaInicioRacha=fecha_ini or fecha,
                fechaFinRacha=fecha_fin or fecha,
                fechas=_fechas_to_db(todas_las_fechas),
                motivos_ausencia=_build_motivos_ausencia(db, idCurso, idAlumno, todas_las_fechas),
                archivada=False,
                created_at=now,
                ultimaAccionAt=now,
            ))

    db.commit()


# ── 3. Llegadas tarde CONSECUTIVAS (umbral: 4 tardanzas seguidas) ────────────
def check_y_crear_alertas_tardanzas_consecutivas_para_curso_fecha(
    db, idCurso: int, fecha: date, min_consecutivas: int = 4
):
    """
    Detecta alumnos con >= `min_consecutivas` llegadas tarde consecutivas hasta `fecha`.
    - Si ya existe una alerta (activa, archivada o resuelta), la actualiza con
      el contador real de la racha y la desarchiva si estaba archivada.
    - Si no existe, crea una nueva cuando se alcanza el umbral por primera vez.
    """
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

    rows_cnt = db.exec(
        select(Asistencia.idAlumno, func.count().label("cnt"))
        .where(
            Asistencia.idCurso == idCurso,
            Asistencia.idAlumno.in_(candidatos),
            Asistencia.fecha.in_(ult_fechas_sorted),
            Asistencia.estado == "Tarde",
        )
        .group_by(Asistencia.idAlumno)
    ).all()
    conteo_map = {int(r.idAlumno): int(r.cnt) for r in rows_cnt}

    now = now_arg()
    for idAlumno in candidatos:
        if idAlumno not in insc_set:
            continue
        # Debe haber llegado tarde en TODAS las últimas N fechas (ventana completa)
        if conteo_map.get(idAlumno, 0) < min_consecutivas:
            continue

        # Racha real acumulada hacia atrás desde hoy
        racha_real = _calcular_racha_consecutiva(db, idCurso, idAlumno, fecha, "Tarde")

        alerta_existente = _get_alerta_activa_motivo(
            db, cue, idCurso, idAlumno, MotivoAlerta.LLEGADAS_TARDE
        )
        if alerta_existente:
            alerta_existente.consecutivas = racha_real
            alerta_existente.fechas = _merge_fechas(
                getattr(alerta_existente, "fechas", None), ult_fechas_sorted
            )
            alerta_existente.fechaFinRacha = max(
                alerta_existente.fechaFinRacha or ult_fechas_sorted[-1],
                ult_fechas_sorted[-1],
            )
            alerta_existente.ultimaAccionAt = now
            _reactivar_si_archivada(alerta_existente)
            db.add(alerta_existente)
        else:
            db.add(Alerta(
                cue=cue,
                idCurso=idCurso,
                idAlumno=idAlumno,
                motivo=MotivoAlerta.LLEGADAS_TARDE,
                estado=EstadoAlerta.PENDIENTE,
                consecutivas=racha_real,
                fechaInicioRacha=ult_fechas_sorted[0],
                fechaFinRacha=ult_fechas_sorted[-1],
                fechas=_fechas_to_db(ult_fechas_sorted),
                detalle=f"{racha_real} llegadas tarde consecutivas",
                archivada=False,
                created_at=now,
                ultimaAccionAt=now,
            ))

    db.commit()


# ── 4. Llegadas tarde REITERADAS (umbral: 15 en el año) ─────────────────────
def check_y_crear_alertas_tardanzas_para_curso_fecha(
    db, idCurso: int, fecha: date, umbral: int = 15
):
    """
    Detecta alumnos que acumularon > `umbral` llegadas tarde en el ciclo lectivo.
    - Si ya existe una alerta (activa, archivada o resuelta), actualiza el contador
      y la desarchiva si estaba archivada.
    - Si no existe y se supera el umbral, crea una nueva.
    """
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

    rows_fechas = db.exec(
        select(Asistencia.idAlumno, Asistencia.fecha)
        .where(
            Asistencia.idCurso == idCurso,
            Asistencia.idAlumno.in_(candidatos),
            Asistencia.fecha >= desde,
            Asistencia.fecha <= hasta,
            Asistencia.estado == "Tarde",
        )
        .order_by(Asistencia.idAlumno, Asistencia.fecha)
    ).all()
    fechas_por_alumno: dict[int, list[date]] = {}
    for row in rows_fechas:
        aid = int(row.idAlumno)
        fechas_por_alumno.setdefault(aid, []).append(row.fecha)

    now = now_arg()
    for idAlumno in candidatos:
        if idAlumno not in insc_set:
            continue

        cnt, fecha_ini, fecha_fin = tardes_map.get(idAlumno, (0, fecha, fecha))
        todas_las_fechas = fechas_por_alumno.get(idAlumno, [fecha])

        alerta_existente = _get_alerta_activa_motivo(
            db, cue, idCurso, idAlumno, MotivoAlerta.LLEGADAS_TARDE
        )

        if alerta_existente:
            # Actualizar si hay más tardanzas que las registradas
            if cnt > int(alerta_existente.consecutivas or 0):
                alerta_existente.consecutivas = cnt
                alerta_existente.fechas = _fechas_to_db(todas_las_fechas)
                alerta_existente.fechaFinRacha = fecha_fin or fecha
                alerta_existente.ultimaAccionAt = now
                _reactivar_si_archivada(alerta_existente)
                db.add(alerta_existente)
        elif cnt > umbral:
            db.add(Alerta(
                cue=cue,
                idCurso=idCurso,
                idAlumno=idAlumno,
                motivo=MotivoAlerta.LLEGADAS_TARDE,
                estado=EstadoAlerta.PENDIENTE,
                consecutivas=cnt,
                fechaInicioRacha=fecha_ini or fecha,
                fechaFinRacha=fecha_fin or fecha,
                fechas=_fechas_to_db(todas_las_fechas),
                detalle=f"{cnt} llegadas tarde acumuladas en el año",
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

    if q and q.strip():
        qq = q.strip()
        like = f"%{qq.lower()}%"
        if qq.isdigit():
            dni_hash_q = hash_for_search(qq)
            stmt = stmt.where(
                or_(
                    func.lower(Alumno.nombre).like(like),
                    func.lower(Alumno.apellido).like(like),
                    Alumno.dni_hash == dni_hash_q,
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
                alumnoDni=decrypt(dni) if dni else dni,
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
                fechas=getattr(alerta, "fechas", None),
                motivos_ausencia=getattr(alerta, "motivos_ausencia", None),
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
        alerta.resueltaAt = now_arg()

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
        alerta.ultimaAccionAt = now_arg()
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

    alerta.ultimaAccionAt = now_arg()
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
        fechas=getattr(payload, "fechas", None),
    )

    actor_id = actor_user_id if actor_user_id is not None else getattr(payload, "created_by", None)
    if hasattr(alerta, "created_by"):
        setattr(alerta, "created_by", actor_id)

    now = now_arg()
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
                alumnoDni=decrypt(dni) if dni else dni,
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
                fechas=getattr(alerta, "fechas", None),
                motivos_ausencia=getattr(alerta, "motivos_ausencia", None),
            )
        )

    return out


def get_historial_alertas_por_alumno(
    db: SessionDep,
    idAlumno: int,
    cue: str,
) -> list:
    from app.schemas.alerta import AlertaResumenAlumno

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
                fechas=getattr(alerta, "fechas", None),
                motivos_ausencia=getattr(alerta, "motivos_ausencia", None),
            )
        )
    return out

# ============================================================
# Re-sincronización de alertas automáticas existentes
# ============================================================

def resync_alertas_automaticas(
    db,
    cue: str | None = None,
    idAlerta: int | None = None,
) -> dict:
    """
    Recalcula el contador `consecutivas`, las `fechas` acumuladas y
    `fechaFinRacha` de todas las alertas automáticas
    (INASISTENCIAS_CONSECUTIVAS, INASISTENCIAS_REITERADAS, LLEGADAS_TARDE).

    Parámetros opcionales:
      - cue:      limita la resync a una escuela
      - idAlerta: limita la resync a una alerta puntual (útil desde el endpoint)
    """
    MOTIVOS_AUTO = [
        MotivoAlerta.INASISTENCIAS_CONSECUTIVAS,
        MotivoAlerta.INASISTENCIAS_REITERADAS,
        MotivoAlerta.LLEGADAS_TARDE,
    ]

    stmt = select(Alerta).where(Alerta.motivo.in_(MOTIVOS_AUTO))
    if cue:
        stmt = stmt.where(Alerta.cue == cue)
    if idAlerta:
        stmt = stmt.where(Alerta.idAlerta == idAlerta)

    alertas: list[Alerta] = list(db.exec(stmt).all())
    now = now_arg()
    actualizadas = 0

    for alerta in alertas:
        curso = db.get(Curso, alerta.idCurso)
        if not curso:
            continue

        anio = getattr(curso, "cicloLectivo", None) or (
            alerta.fechaInicioRacha.year if alerta.fechaInicioRacha else now.year
        )
        desde_anio = date(int(anio), 1, 1)
        hasta_anio = date(int(anio), 12, 31)

        # ── CONSECUTIVAS (ausencias) ──────────────────────────────────────
        if alerta.motivo == MotivoAlerta.INASISTENCIAS_CONSECUTIVAS:
            # Última fecha de clase donde el alumno estuvo ausente
            ultima_fecha = db.exec(
                select(func.max(Asistencia.fecha)).where(
                    Asistencia.idCurso == alerta.idCurso,
                    Asistencia.idAlumno == alerta.idAlumno,
                    Asistencia.estado == "Ausente",
                )
            ).one()
            if not ultima_fecha:
                continue

            racha = _calcular_racha_consecutiva(
                db, alerta.idCurso, alerta.idAlumno, ultima_fecha, "Ausente"
            )
            if racha == 0:
                continue

            # Fechas de clase de la racha actual (las últimas N fechas de clase)
            fechas_clase_desc = db.exec(
                select(Asistencia.fecha)
                .where(Asistencia.idCurso == alerta.idCurso)
                .group_by(Asistencia.fecha)
                .order_by(desc(Asistencia.fecha))
                .limit(racha)
            ).all()
            fechas_racha = sorted(fechas_clase_desc)

            estado_map = {
                row.fecha: row.estado
                for row in db.exec(
                    select(Asistencia.fecha, Asistencia.estado).where(
                        Asistencia.idCurso == alerta.idCurso,
                        Asistencia.idAlumno == alerta.idAlumno,
                        Asistencia.fecha.in_(fechas_racha),
                    )
                ).all()
            }
            fechas_ausentes = [f for f in fechas_racha if estado_map.get(f) == "Ausente"]

            alerta.consecutivas = racha
            alerta.fechas = _merge_fechas(getattr(alerta, "fechas", None), fechas_ausentes)
            alerta.fechaFinRacha = ultima_fecha
            if fechas_ausentes:
                alerta.fechaInicioRacha = min(
                    alerta.fechaInicioRacha or fechas_ausentes[0],
                    fechas_ausentes[0],
                )
            alerta.ultimaAccionAt = now
            db.add(alerta)
            actualizadas += 1

        # ── LLEGADAS TARDE (consecutivas y reiteradas comparten motivo) ───
        elif alerta.motivo == MotivoAlerta.LLEGADAS_TARDE:
            ultima_fecha = db.exec(
                select(func.max(Asistencia.fecha)).where(
                    Asistencia.idCurso == alerta.idCurso,
                    Asistencia.idAlumno == alerta.idAlumno,
                    Asistencia.estado == "Tarde",
                )
            ).one()
            if not ultima_fecha:
                continue

            racha = _calcular_racha_consecutiva(
                db, alerta.idCurso, alerta.idAlumno, ultima_fecha, "Tarde"
            )

            fechas_clase_desc = db.exec(
                select(Asistencia.fecha)
                .where(Asistencia.idCurso == alerta.idCurso)
                .group_by(Asistencia.fecha)
                .order_by(desc(Asistencia.fecha))
                .limit(max(racha, 1))
            ).all()
            fechas_racha = sorted(fechas_clase_desc)

            estado_map = {
                row.fecha: row.estado
                for row in db.exec(
                    select(Asistencia.fecha, Asistencia.estado).where(
                        Asistencia.idCurso == alerta.idCurso,
                        Asistencia.idAlumno == alerta.idAlumno,
                        Asistencia.fecha.in_(fechas_racha),
                    )
                ).all()
            }
            fechas_tarde = [f for f in fechas_racha if estado_map.get(f) == "Tarde"]

            # También contamos el total del año para reiteradas
            cnt_anio = db.exec(
                select(func.count()).where(
                    Asistencia.idCurso == alerta.idCurso,
                    Asistencia.idAlumno == alerta.idAlumno,
                    Asistencia.fecha >= desde_anio,
                    Asistencia.fecha <= hasta_anio,
                    Asistencia.estado == "Tarde",
                )
            ).one() or 0

            nuevo_contador = max(racha, int(cnt_anio))
            if nuevo_contador > int(alerta.consecutivas or 0):
                alerta.consecutivas = nuevo_contador
                alerta.fechas = _merge_fechas(getattr(alerta, "fechas", None), fechas_tarde)
                alerta.fechaFinRacha = ultima_fecha
                alerta.ultimaAccionAt = now
                db.add(alerta)
                actualizadas += 1

        # ── REITERADAS (ausencias) ────────────────────────────────────────
        elif alerta.motivo == MotivoAlerta.INASISTENCIAS_REITERADAS:
            row_total = db.exec(
                select(
                    func.count().label("cnt"),
                    func.max(Asistencia.fecha).label("maxf"),
                )
                .where(
                    Asistencia.idCurso == alerta.idCurso,
                    Asistencia.idAlumno == alerta.idAlumno,
                    Asistencia.fecha >= desde_anio,
                    Asistencia.fecha <= hasta_anio,
                    Asistencia.estado == "Ausente",
                )
            ).one()

            cnt = int(row_total.cnt or 0)
            if cnt == 0:
                continue

            todas_las_fechas = [
                row.fecha for row in db.exec(
                    select(Asistencia.fecha).where(
                        Asistencia.idCurso == alerta.idCurso,
                        Asistencia.idAlumno == alerta.idAlumno,
                        Asistencia.fecha >= desde_anio,
                        Asistencia.fecha <= hasta_anio,
                        Asistencia.estado == "Ausente",
                    ).order_by(Asistencia.fecha)
                ).all()
            ]

            alerta.consecutivas = cnt
            alerta.fechas = _fechas_to_db(todas_las_fechas)
            alerta.fechaFinRacha = row_total.maxf or alerta.fechaFinRacha
            alerta.ultimaAccionAt = now
            db.add(alerta)
            actualizadas += 1

    db.commit()
    return {"actualizadas": actualizadas, "total_evaluadas": len(alertas)}