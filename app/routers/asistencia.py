# app/routers/asistencia.py
from datetime import date
from typing import Annotated, Optional

from fastapi import APIRouter, HTTPException, Query, Depends

from app.dependencies import SessionDep
from app.schemas.asistencia import AsistenciaCreate, AsistenciaPublic, AsistenciaRead  # ← agregar AsistenciaRead
from app.services.asistencia_service import (
    upsert_asistencia,
    upsert_asistencias_bulk,
    get_one_asistencia,
    get_asistencias_by_curso_fecha,
    get_asistencias_by_curso,
    get_asistencias_by_alumno,
    get_asistencias_by_curso_alumno,
    stats_resumen,
    stats_serie,
    stats_distribucion_inasistencias,
    stats_riesgo_por_curso,
    stats_lluvia_comparativo,
    alertas_inasistencias_consecutivas,
    stats_dias_semana,
    stats_alumnos_por_rango,
    upsert_asistencias_por_curso_fecha,
    upsert_asistencias_por_curso_rango
)
from app.services.whatsapp_service import enviar_plantilla_inasistencia
from app.schemas.asistencia_bulk_curso import AsistenciaCursoFechaBulkRequest, AsistenciaCursoRangoBulkRequest
from app.dependencies.auth import get_current_user
from app.models.usuario import Usuario

router = APIRouter(prefix="/asistencias", tags=["Asistencias"])


# ==========================
# Helpers
# ==========================

def _to_read(r) -> AsistenciaRead:
    return AsistenciaRead(
        idCurso=r.idCurso,
        idAlumno=r.idAlumno,
        fecha=r.fecha,
        estado=r.estado,
        lluvia=r.lluvia,
        wamid=r.wamid,
        motivo_ausencia=r.motivo_ausencia,  # ← el campo que faltaba
    )


# ==========================
# Create / Upsert
# ==========================

@router.post("/", response_model=AsistenciaRead)
async def create_or_update_asistencia(payload: AsistenciaCreate, session: SessionDep):
    row = await upsert_asistencia(db=session, payload=payload)
    return _to_read(row)


@router.post("/bulk", response_model=list[AsistenciaRead])
async def create_or_update_asistencias_bulk(payloads: list[AsistenciaCreate], session: SessionDep):
    rows = await upsert_asistencias_bulk(db=session, payloads=payloads)
    return [_to_read(r) for r in rows]


# ==========================
# Estadísticas (Director)
# ==========================

@router.get("/stats/resumen")
def read_stats_resumen(
    session: SessionDep,
    cue: str,
    desde: date,
    hasta: date,
    cursoIds: Optional[list[int]] = Query(default=None),
    curso_ids: Optional[list[int]] = Query(default=None),
    umbral: int = Query(default=20, ge=1),
    umbral_riesgo: int = Query(default=20, ge=1),
    soloLluvia: Optional[bool] = Query(default=None),
):
    cursos = cursoIds if cursoIds is not None else curso_ids
    umb = umbral if umbral is not None else umbral_riesgo

    return stats_resumen(
        db=session,
        cue=cue,
        desde=desde,
        hasta=hasta,
        curso_ids=cursos,
        umbral_riesgo=umb,
        solo_lluvia=soloLluvia,
    )


@router.get("/stats/serie")
def read_stats_serie(
    session: SessionDep,
    cue: str,
    desde: date,
    hasta: date,
    group_by: str = Query(default="day", alias="groupBy", pattern="^(day|week|month)$"),
    curso_ids: Optional[list[int]] = Query(default=None, alias="cursoIds"),
    solo_lluvia: Optional[bool] = Query(default=None, alias="soloLluvia"),
):
    return stats_serie(
        db=session,
        cue=cue,
        desde=desde,
        hasta=hasta,
        group_by=group_by,
        curso_ids=curso_ids,
        solo_lluvia=solo_lluvia,
    )


@router.get("/stats/distribucion")
def read_stats_distribucion(
    session: SessionDep,
    cue: str,
    desde: date,
    hasta: date,
    cursoIds: Optional[list[int]] = Query(default=None),
    curso_ids: Optional[list[int]] = Query(default=None),
):
    cursos = cursoIds if cursoIds is not None else curso_ids

    return stats_distribucion_inasistencias(
        db=session,
        cue=cue,
        desde=desde,
        hasta=hasta,
        curso_ids=cursos,
    )


@router.get("/stats/riesgo")
def read_stats_riesgo_por_curso(
    session: SessionDep,
    cue: str,
    desde: date,
    hasta: date,
    umbral: int = Query(default=20, ge=1),
    cursoIds: Optional[list[int]] = Query(default=None),
    curso_ids: Optional[list[int]] = Query(default=None),
):
    cursos = cursoIds if cursoIds is not None else curso_ids

    return stats_riesgo_por_curso(
        db=session,
        cue=cue,
        desde=desde,
        hasta=hasta,
        umbral=umbral,
        curso_ids=cursos,
    )


@router.get("/stats/lluvia")
def read_stats_lluvia(
    session: SessionDep,
    cue: str,
    desde: date,
    hasta: date,
    cursoIds: Optional[list[int]] = Query(default=None),
    curso_ids: Optional[list[int]] = Query(default=None),
):
    cursos = cursoIds if cursoIds is not None else curso_ids

    return stats_lluvia_comparativo(
        db=session,
        cue=cue,
        desde=desde,
        hasta=hasta,
        curso_ids=cursos,
    )


@router.get("/stats/dias-semana")
def read_stats_dias_semana(
    session: SessionDep,
    cue: str,
    desde: date,
    hasta: date,
    cursoIds: Optional[list[int]] = Query(default=None),
    curso_ids: Optional[list[int]] = Query(default=None),
    soloLluvia: Optional[bool] = Query(default=None),
):
    cursos = cursoIds if cursoIds is not None else curso_ids

    return stats_dias_semana(
        db=session,
        cue=cue,
        desde=desde,
        hasta=hasta,
        curso_ids=cursos,
        solo_lluvia=soloLluvia,
    )


@router.get("/stats/alumnos-por-rango")
def read_stats_alumnos_por_rango(
    session: SessionDep,
    cue: str,
    desde: date,
    hasta: date,
    rango: str = Query(..., description="Formato: '0-10', '11-20', '57+'"),
    cursoIds: Optional[list[int]] = Query(default=None),
    curso_ids: Optional[list[int]] = Query(default=None),
):
    cursos = cursoIds if cursoIds is not None else curso_ids

    return stats_alumnos_por_rango(
        db=session,
        cue=cue,
        desde=desde,
        hasta=hasta,
        rango=rango,
        curso_ids=cursos,
    )


# ==========================
# Alertas (Asistente Social)
# ==========================

@router.get("/alertas/consecutivas")
def read_alertas_inasistencias_consecutivas(
    session: SessionDep,
    cue: str,
    desde: date,
    hasta: date,
    min: int = Query(default=3, ge=2, le=30),
):
    return alertas_inasistencias_consecutivas(
        db=session,
        cue=cue,
        desde=desde,
        hasta=hasta,
        min_consecutivas=min,
    )


# ==========================
# Reads
# ==========================

@router.get("/one/{idCurso}/{idAlumno}/{fecha}", response_model=AsistenciaRead)
def read_one_asistencia(
    idCurso: int,
    idAlumno: int,
    fecha: date,
    session: SessionDep,
):
    row = get_one_asistencia(db=session, idCurso=idCurso, idAlumno=idAlumno, fecha=fecha)
    if not row:
        raise HTTPException(status_code=404, detail="Asistencia no encontrada")
    return _to_read(row)


@router.get("/curso/{idCurso}/alumno/{idAlumno}", response_model=list[AsistenciaRead])
def read_asistencias_by_curso_alumno(
    idCurso: int,
    idAlumno: int,
    session: SessionDep,
    anio: Optional[int] = None,
    offset: int = 0,
    limit: Annotated[int, Query(le=500)] = 200,
):
    rows = get_asistencias_by_curso_alumno(
        db=session,
        idCurso=idCurso,
        idAlumno=idAlumno,
        anio=anio,
        offset=offset,
        limit=limit,
    )
    return [_to_read(r) for r in rows]


@router.get("/alumno/{idAlumno}", response_model=list[AsistenciaRead])
def read_asistencias_by_alumno(
    idAlumno: int,
    session: SessionDep,
    offset: int = 0,
    limit: Annotated[int, Query(le=500)] = 200,
):
    rows = get_asistencias_by_alumno(db=session, idAlumno=idAlumno, offset=offset, limit=limit)
    return [_to_read(r) for r in rows]


@router.get("/curso/{idCurso}", response_model=list[AsistenciaRead])
def read_asistencias_by_curso(
    idCurso: int,
    session: SessionDep,
    offset: int = 0,
    limit: Annotated[int, Query(le=200)] = 100,
):
    rows = get_asistencias_by_curso(db=session, idCurso=idCurso, offset=offset, limit=limit)
    return [_to_read(r) for r in rows]


@router.get("/{idCurso}/{fecha}", response_model=list[AsistenciaRead])
def read_asistencias_by_curso_fecha(
    idCurso: int,
    fecha: date,
    session: SessionDep,
):
    rows = get_asistencias_by_curso_fecha(db=session, idCurso=idCurso, fecha=fecha)
    return [_to_read(r) for r in rows]


# ==========================
# Notificaciones / Bulk
# ==========================

@router.post("/asistencia/notificar")
async def registrar_asistencia(
    telefono: str,
    apellido: str,
    nombre: str,
    dni: str,
    session: SessionDep,
    current_user: Usuario = Depends(get_current_user),
):
    await enviar_plantilla_inasistencia(telefono=telefono, apellido=apellido, nombre=nombre, dni=dni)
    return {"ok": True}


@router.post("/cursos/{idCurso}/bulk-fecha", response_model=list[AsistenciaPublic])
async def cargar_asistencia_curso_bulk_fecha(
    idCurso: int,
    payload: AsistenciaCursoFechaBulkRequest,
    session: SessionDep,
    current_user: Usuario = Depends(get_current_user),
):
    overrides = [(o.idAlumno, o.estado, o.lluvia) for o in payload.overrides]

    return await upsert_asistencias_por_curso_fecha(
        db=session,
        idCurso=idCurso,
        fecha=payload.fecha,
        default_estado=payload.default_estado,
        lluvia=payload.lluvia,
        overrides=overrides,
    )


@router.post("/cursos/{idCurso}/bulk-rango")
async def cargar_asistencia_curso_bulk_rango(
    idCurso: int,
    payload: AsistenciaCursoRangoBulkRequest,
    session: SessionDep,
    current_user: Usuario = Depends(get_current_user),
):
    overrides = [(o.idAlumno, o.estado, o.lluvia) for o in payload.overrides]

    total = await upsert_asistencias_por_curso_rango(
        db=session,
        idCurso=idCurso,
        desde=payload.desde,
        hasta=payload.hasta,
        weekdays=payload.weekdays,
        default_estado=payload.default_estado,
        lluvia=payload.lluvia,
        overrides=overrides,
        solo_alumnos=payload.solo_alumnos,
    )
    return {"ok": True, "registros": total}