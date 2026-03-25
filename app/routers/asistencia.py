# app/routers/asistencia.py
from datetime import date
from typing import Annotated, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Depends, Response, UploadFile, File
from fastapi.responses import FileResponse
from pathlib import Path

from app.dependencies import SessionDep
from app.schemas.asistencia import AsistenciaCreate, AsistenciaPublic, AsistenciaRead, CertificadoRevisionRequest, NotificacionDocente
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
    stats_justificadas_vs_injustificadas,
    upsert_asistencias_por_curso_fecha,
    upsert_asistencias_por_curso_rango,
    get_notificaciones_docente,
    revisar_certificado,
    stats_motivos_ausencia,
    get_notificaciones_docente_por_usuario,
    get_notificaciones_docente_historial,
    upload_certificado_docente,
)
from app.services.whatsapp_service import enviar_plantilla_inasistencia
from app.schemas.asistencia_bulk_curso import AsistenciaCursoFechaBulkRequest, AsistenciaCursoRangoBulkRequest
from app.dependencies.auth import get_current_user
from app.models.usuario import Usuario


router = APIRouter(prefix="/asistencias", tags=["Asistencias"])

# TTL para cache de estadísticas (5 minutos)
_STATS_CACHE_TTL = 300

# Carpeta de certificados
_UPLOADS_DIR = Path(__file__).resolve().parent.parent.parent / "uploads" / "certificados"


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
        motivo_ausencia=r.motivo_ausencia,
        certificado_path=r.certificado_path,
        certificado_estado=r.certificado_estado,
        justificado_hasta=r.justificado_hasta,
        revisado_por=r.revisado_por,
    )


def _set_cache_headers(response: Response) -> None:
    response.headers["Cache-Control"] = f"private, max-age={_STATS_CACHE_TTL}"


# ==========================
# Create / Upsert
# ==========================

@router.post("/", response_model=AsistenciaRead)
async def create_or_update_asistencia(
    payload: AsistenciaCreate,
    session: SessionDep,
    background_tasks: BackgroundTasks,
):
    row = await upsert_asistencia(db=session, payload=payload, bg=background_tasks)
    return _to_read(row)


@router.post("/bulk", response_model=list[AsistenciaRead])
async def create_or_update_asistencias_bulk(
    payloads: list[AsistenciaCreate],
    session: SessionDep,
    background_tasks: BackgroundTasks,
):
    rows = await upsert_asistencias_bulk(db=session, payloads=payloads, bg=background_tasks)
    return [_to_read(r) for r in rows]


# ==========================
# Estadísticas (Director)
# ⚠️ TODOS los /stats/... deben ir ANTES de las rutas con path params
# ==========================

@router.get("/stats/resumen")
def read_stats_resumen(
    response: Response,
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
    _set_cache_headers(response)
    cursos = cursoIds if cursoIds is not None else curso_ids
    umb = umbral if umbral is not None else umbral_riesgo
    return stats_resumen(
        db=session, cue=cue, desde=desde, hasta=hasta,
        curso_ids=cursos, umbral_riesgo=umb, solo_lluvia=soloLluvia,
    )


@router.get("/stats/serie")
def read_stats_serie(
    response: Response,
    session: SessionDep,
    cue: str,
    desde: date,
    hasta: date,
    group_by: str = Query(default="day", alias="groupBy", pattern="^(day|week|month)$"),
    curso_ids: Optional[list[int]] = Query(default=None, alias="cursoIds"),
    solo_lluvia: Optional[bool] = Query(default=None, alias="soloLluvia"),
):
    _set_cache_headers(response)
    return stats_serie(
        db=session, cue=cue, desde=desde, hasta=hasta,
        group_by=group_by, curso_ids=curso_ids, solo_lluvia=solo_lluvia,
    )


@router.get("/stats/distribucion")
def read_stats_distribucion(
    response: Response,
    session: SessionDep,
    cue: str,
    desde: date,
    hasta: date,
    cursoIds: Optional[list[int]] = Query(default=None),
    curso_ids: Optional[list[int]] = Query(default=None),
):
    _set_cache_headers(response)
    cursos = cursoIds if cursoIds is not None else curso_ids
    return stats_distribucion_inasistencias(
        db=session, cue=cue, desde=desde, hasta=hasta, curso_ids=cursos,
    )


@router.get("/stats/motivos")
def read_stats_motivos(
    response: Response,
    session: SessionDep,
    cue: str,
    desde: date,
    hasta: date,
    cursoIds: Optional[list[int]] = Query(default=None),
    curso_ids: Optional[list[int]] = Query(default=None),
    topN: int = Query(default=10, ge=1, le=50),
):
    _set_cache_headers(response)
    cursos = cursoIds if cursoIds is not None else curso_ids
    return stats_motivos_ausencia(
        db=session, cue=cue, desde=desde, hasta=hasta, curso_ids=cursos, top_n=topN,
    )


@router.get("/stats/riesgo")
def read_stats_riesgo_por_curso(
    response: Response,
    session: SessionDep,
    cue: str,
    desde: date,
    hasta: date,
    umbral: int = Query(default=20, ge=1),
    cursoIds: Optional[list[int]] = Query(default=None),
    curso_ids: Optional[list[int]] = Query(default=None),
):
    _set_cache_headers(response)
    cursos = cursoIds if cursoIds is not None else curso_ids
    return stats_riesgo_por_curso(
        db=session, cue=cue, desde=desde, hasta=hasta, umbral=umbral, curso_ids=cursos,
    )


@router.get("/stats/lluvia")
def read_stats_lluvia(
    response: Response,
    session: SessionDep,
    cue: str,
    desde: date,
    hasta: date,
    cursoIds: Optional[list[int]] = Query(default=None),
    curso_ids: Optional[list[int]] = Query(default=None),
):
    _set_cache_headers(response)
    cursos = cursoIds if cursoIds is not None else curso_ids
    return stats_lluvia_comparativo(
        db=session, cue=cue, desde=desde, hasta=hasta, curso_ids=cursos,
    )


@router.get("/stats/dias-semana")
def read_stats_dias_semana(
    response: Response,
    session: SessionDep,
    cue: str,
    desde: date,
    hasta: date,
    cursoIds: Optional[list[int]] = Query(default=None),
    curso_ids: Optional[list[int]] = Query(default=None),
    soloLluvia: Optional[bool] = Query(default=None),
):
    _set_cache_headers(response)
    cursos = cursoIds if cursoIds is not None else curso_ids
    return stats_dias_semana(
        db=session, cue=cue, desde=desde, hasta=hasta,
        curso_ids=cursos, solo_lluvia=soloLluvia,
    )


@router.get("/stats/justificadas")
def read_stats_justificadas(
    response: Response,
    session: SessionDep,
    cue: str,
    desde: date,
    hasta: date,
    cursoIds: Optional[list[int]] = Query(default=None),
    curso_ids: Optional[list[int]] = Query(default=None),
):
    _set_cache_headers(response)
    cursos = cursoIds if cursoIds is not None else curso_ids
    return stats_justificadas_vs_injustificadas(
        db=session, cue=cue, desde=desde, hasta=hasta, curso_ids=cursos,
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
    # Sin cache — es interactivo
    cursos = cursoIds if cursoIds is not None else curso_ids
    return stats_alumnos_por_rango(
        db=session, cue=cue, desde=desde, hasta=hasta, rango=rango, curso_ids=cursos,
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
        db=session, cue=cue, desde=desde, hasta=hasta, min_consecutivas=min,
    )


# ==========================
# Notificaciones del docente
# ⚠️ DEBEN ir ANTES de /{idCurso}/{fecha} para evitar conflictos de rutas
# ==========================

@router.get(
    "/docente/notificaciones",
    response_model=list[NotificacionDocente],
    summary="Notificaciones de todos los cursos del docente",
)
def read_notificaciones_docente_por_usuario(
    session: SessionDep,
    current_user: Usuario = Depends(get_current_user),
):
    return get_notificaciones_docente_por_usuario(
        db=session,
        idUsuario=current_user.idUsuario,
    )


@router.get(
    "/docente/notificaciones/historial",
    response_model=list[NotificacionDocente],
    summary="Historial de notificaciones del docente (últimos 30 días, todos los estados)",
)
def read_notificaciones_docente_historial(
    session: SessionDep,
    dias: int = Query(default=30, ge=1, le=365),
    current_user: Usuario = Depends(get_current_user),
):
    return get_notificaciones_docente_historial(
        db=session,
        idUsuario=current_user.idUsuario,
        dias=dias,
    )


# ==========================
# Certificado — servir imagen
# ⚠️ Debe ir ANTES de /{idCurso}/... para evitar conflictos
# ==========================

@router.get(
    "/certificado/imagen/{filename}",
    summary="Descargar imagen de certificado médico",
)
def get_certificado_imagen(
    filename: str,
    current_user: Usuario = Depends(get_current_user),
):
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Nombre de archivo inválido")

    filepath = _UPLOADS_DIR / filename
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Certificado no encontrado")

    return FileResponse(str(filepath))


# ==========================
# Reads (con path params)
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
        db=session, idCurso=idCurso, idAlumno=idAlumno,
        anio=anio, offset=offset, limit=limit,
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
    limit: Annotated[int, Query(le=10000)] = 10000,
    desde: Optional[date] = Query(default=None),
    hasta: Optional[date] = Query(default=None),
):
    rows = get_asistencias_by_curso(db=session, idCurso=idCurso, offset=offset, limit=limit)
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
    background_tasks: BackgroundTasks,
    current_user: Usuario = Depends(get_current_user),
):
    overrides = [(o.idAlumno, o.estado, o.lluvia) for o in payload.overrides]
    return await upsert_asistencias_por_curso_fecha(
        db=session, idCurso=idCurso, fecha=payload.fecha,
        default_estado=payload.default_estado, lluvia=payload.lluvia,
        overrides=overrides, bg=background_tasks,
    )


@router.post("/cursos/{idCurso}/bulk-rango")
async def cargar_asistencia_curso_bulk_rango(
    idCurso: int,
    payload: AsistenciaCursoRangoBulkRequest,
    session: SessionDep,
    background_tasks: BackgroundTasks,
    current_user: Usuario = Depends(get_current_user),
):
    overrides = [(o.idAlumno, o.estado, o.lluvia) for o in payload.overrides]
    total = await upsert_asistencias_por_curso_rango(
        db=session, idCurso=idCurso, desde=payload.desde, hasta=payload.hasta,
        weekdays=payload.weekdays, default_estado=payload.default_estado,
        lluvia=payload.lluvia, overrides=overrides,
        solo_alumnos=payload.solo_alumnos, bg=background_tasks,
    )
    return {"ok": True, "registros": total}


# ==========================
# Notificaciones por curso (legacy)
# ==========================

@router.get(
    "/cursos/{idCurso}/notificaciones-docente",
    response_model=list[NotificacionDocente],
    summary="Notificaciones de respuestas WPP para la campanita del docente (por curso)",
)
def read_notificaciones_docente(
    idCurso: int,
    session: SessionDep,
    current_user: Usuario = Depends(get_current_user),
):
    return get_notificaciones_docente(db=session, idCurso=idCurso)


# ==========================
# Certificado — upload desde el docente
# ⚠️ Debe ir ANTES del PATCH genérico de certificado
# ==========================

@router.post(
    "/{idCurso}/{idAlumno}/{fecha}/certificado/upload",
    response_model=AsistenciaRead,
    summary="Subir imagen de certificado médico desde el frontend (docente)",
)
async def upload_certificado(
    idCurso:  int,
    idAlumno: int,
    fecha:    date,
    session:  SessionDep,
    file:     UploadFile = File(...),
    current_user: Usuario = Depends(get_current_user),
):
    row = await upload_certificado_docente(
        db=session, idCurso=idCurso, idAlumno=idAlumno, fecha=fecha, file=file,
    )
    return _to_read(row)


# ==========================
# Revisión de certificado
# ==========================

@router.patch(
    "/{idCurso}/{idAlumno}/{fecha}/certificado",
    response_model=AsistenciaRead,
    summary="Aprobar o rechazar un certificado médico",
)
def patch_certificado(
    idCurso:  int,
    idAlumno: int,
    fecha:    date,
    payload:  CertificadoRevisionRequest,
    session:  SessionDep,
    current_user: Usuario = Depends(get_current_user),
):
    row = revisar_certificado(
        db=session, idCurso=idCurso, idAlumno=idAlumno,
        fecha=fecha, payload=payload, revisado_por_id=current_user.idUsuario,
    )
    return _to_read(row)


# ==========================
# Servir certificados (protegido con JWT)
# ==========================

_CERTIFICADOS_DIR = Path(__file__).resolve().parent.parent.parent / "uploads" / "certificados"

# Extensiones válidas para certificados médicos
_VALID_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


@router.get(
    "/certificados/{filename}",
    summary="Obtener imagen de certificado médico (requiere JWT)",
)
def get_certificado_image(
    filename: str,
    current_user: Usuario = Depends(get_current_user),
):
    # Prevenir path traversal
    safe_name = Path(filename).name
    if safe_name != filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Nombre de archivo inválido")

    filepath = _CERTIFICADOS_DIR / safe_name

    if not filepath.exists() or not filepath.is_file():
        raise HTTPException(status_code=404, detail="Certificado no encontrado")

    # Validar extensión
    if filepath.suffix.lower() not in _VALID_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Tipo de archivo no permitido")

    return FileResponse(filepath)


# ==========================
# ⚠️ Rutas genéricas AL FINAL — deben ir después de todas las específicas
# ==========================

@router.get("/{idCurso}/{fecha}", response_model=list[AsistenciaRead])
def read_asistencias_by_curso_fecha(
    idCurso: int,
    fecha: date,
    session: SessionDep,
):
    rows = get_asistencias_by_curso_fecha(db=session, idCurso=idCurso, fecha=fecha)
    return [_to_read(r) for r in rows]