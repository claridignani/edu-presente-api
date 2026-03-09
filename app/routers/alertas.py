# app/routers/alertas.py
from datetime import date
from typing import Optional

from fastapi import APIRouter, Query, Depends, HTTPException

from app.dependencies import SessionDep
from app.dependencies.auth import get_current_user
from app.dependencies.authz import require_access_to_cue_param

from app.models.usuario import Usuario
from app.models.alerta import EstadoAlerta, MotivoAlerta
from app.models.curso_docente import CursoDocente
from app.models.inscriptos import Inscriptos

from sqlmodel import select as sql_select
from sqlalchemy import and_ as sql_and

from app.schemas.rol import RolDescripcion
from app.schemas.alerta import AlertaListItem, AlertaPatch, AlertaCreate, AlertaResumenAlumno
from app.schemas.intervencion import IntervencionCreate, IntervencionPublic

from app.services.alerta_service import (
    list_alertas,
    list_alertas_docente,
    patch_alerta,
    add_intervencion,
    list_intervenciones,
    create_alerta,
    stats_alertas_activas_por_escuela,
    get_historial_alertas_por_alumno,
)

router = APIRouter(prefix="/alertas", tags=["Alertas"])

ALLOWED_ALERTAS = [RolDescripcion.Director, RolDescripcion.Asistente, RolDescripcion.Administrador]
ALLOWED_DOCENTE = [RolDescripcion.Docente]

MOTIVOS_DOCENTE = {MotivoAlerta.PEDAGOGICO, MotivoAlerta.SALUD, MotivoAlerta.CONDUCTA}


# ── Helpers de validación ────────────────────────────────────────────────────

def _get_cursos_docente(session: SessionDep, docente_id: int) -> list[int]:
    """Cursos activos asignados al docente (tabla curso_docente)."""
    hoy = date.today()
    stmt = sql_select(CursoDocente.idCurso).where(
        sql_and(
            CursoDocente.idUsuario == docente_id,
            CursoDocente.estado == "Activo",
            (CursoDocente.fechaDesde.is_(None) | (CursoDocente.fechaDesde <= hoy)),
            (CursoDocente.fechaHasta.is_(None) | (CursoDocente.fechaHasta >= hoy)),
        )
    )
    return [int(r) for r in session.exec(stmt).all()]


def _alumno_en_curso(session: SessionDep, idAlumno: int, idCurso: int) -> bool:
    """True si el alumno tiene inscripción activa en el curso."""
    hoy = date.today()
    stmt = sql_select(Inscriptos.idInscripcion).where(
        sql_and(
            Inscriptos.idCurso == idCurso,
            Inscriptos.idAlumno == idAlumno,
            Inscriptos.activo.is_(True),
            Inscriptos.fechaAlta <= hoy,
            (Inscriptos.fechaBaja.is_(None) | (Inscriptos.fechaBaja >= hoy)),
        )
    ).limit(1)
    return session.exec(stmt).first() is not None


# ────────────────────────────────────────────────────────────────────────────


@router.get("/", response_model=list[AlertaListItem])
def get_alertas(
    session: SessionDep,
    cue: str,
    _current_user: Usuario = Depends(require_access_to_cue_param(ALLOWED_ALERTAS)),
    q: Optional[str] = None,
    cursoId: Optional[int] = Query(default=None, alias="cursoId"),
    estado: Optional[EstadoAlerta] = None,
    desde: Optional[date] = None,
    hasta: Optional[date] = None,
    archivadas: Optional[bool] = False,
):
    return list_alertas(
        db=session,
        cue=cue,
        q=q,
        curso_id=cursoId,
        estado=estado,
        desde=desde,
        hasta=hasta,
        archivadas=archivadas,
    )


# ── GET /alertas/docente/ ────────────────────────────────────────────────────
@router.get("/docente/", response_model=list[AlertaListItem])
def get_alertas_docente(
    session: SessionDep,
    cue: str,
    archivadas: Optional[bool] = False,
    current_user: Usuario = Depends(require_access_to_cue_param(ALLOWED_DOCENTE)),
):
    return list_alertas_docente(
        db=session,
        cue=cue,
        docente_id=current_user.idUsuario,
        archivadas=archivadas,
    )


# ── POST /alertas/docente/ ───────────────────────────────────────────────────
@router.post("/docente/", response_model=dict, status_code=201)
def post_alerta_docente(
    cue: str,
    payload: AlertaCreate,
    session: SessionDep,
    current_user: Usuario = Depends(require_access_to_cue_param(ALLOWED_DOCENTE)),
):
    if payload.cue != cue:
        raise HTTPException(status_code=400, detail="CUE inválido")

    # 1. Motivo permitido para docentes
    if payload.motivo not in MOTIVOS_DOCENTE:
        raise HTTPException(
            status_code=403,
            detail=f"Motivo no permitido. Permitidos: {', '.join(m.value for m in MOTIVOS_DOCENTE)}",
        )

    # 2. El curso debe estar asignado al docente en curso_docente
    cursos_docente = _get_cursos_docente(session, current_user.idUsuario)
    if not cursos_docente:
        raise HTTPException(
            status_code=403,
            detail="No tenés cursos asignados en esta institución.",
        )
    if payload.idCurso not in cursos_docente:
        raise HTTPException(
            status_code=403,
            detail="El curso indicado no está asignado a este docente.",
        )

    # 3. El alumno debe estar inscripto activamente en ese curso
    if not _alumno_en_curso(session, payload.idAlumno, payload.idCurso):
        raise HTTPException(
            status_code=403,
            detail="El alumno no está inscripto en ese curso.",
        )

    a = create_alerta(db=session, payload=payload, actor_user_id=current_user.idUsuario)
    return {"ok": True, "idAlerta": a.idAlerta}


@router.post("/", response_model=dict)
def post_alerta(
    cue: str,
    payload: AlertaCreate,
    session: SessionDep,
    current_user: Usuario = Depends(require_access_to_cue_param(ALLOWED_ALERTAS)),
):
    if payload.cue != cue:
        raise HTTPException(status_code=400, detail="CUE inválido")

    a = create_alerta(db=session, payload=payload, actor_user_id=current_user.idUsuario)
    return {"ok": True, "idAlerta": a.idAlerta}


@router.patch("/{idAlerta}", response_model=dict)
def update_alerta(
    idAlerta: int,
    payload: AlertaPatch,
    session: SessionDep,
    current_user: Usuario = Depends(get_current_user),
):
    a = patch_alerta(db=session, idAlerta=idAlerta, patch=payload, actor_user_id=current_user.idUsuario)
    return {"ok": True, "idAlerta": a.idAlerta, "estado": a.estado, "archivada": a.archivada}


@router.get("/{idAlerta}/intervenciones", response_model=list[IntervencionPublic])
def get_intervenciones(
    idAlerta: int,
    session: SessionDep,
    current_user: Usuario = Depends(get_current_user),
):
    return list_intervenciones(db=session, idAlerta=idAlerta)


@router.post("/{idAlerta}/intervenciones", response_model=IntervencionPublic)
def create_intervencion(
    idAlerta: int,
    payload: IntervencionCreate,
    session: SessionDep,
    current_user: Usuario = Depends(get_current_user),
):
    return add_intervencion(
        db=session,
        idAlerta=idAlerta,
        payload=payload,
        actor_user_id=current_user.idUsuario,
    )


@router.get("/stats/riesgo", response_model=list[AlertaListItem])
def get_alertas_riesgo(
    session: SessionDep,
    cue: str,
    _current_user: Usuario = Depends(require_access_to_cue_param(ALLOWED_ALERTAS)),
    desde: Optional[date] = Query(default=None),
    hasta: Optional[date] = Query(default=None),
    cursoIds: Optional[list[int]] = Query(default=None),
):
    return stats_alertas_activas_por_escuela(
        db=session,
        cue=cue,
        desde=desde,
        hasta=hasta,
        curso_ids=cursoIds,)

@router.get("/alumno/{idAlumno}", response_model=list[AlertaResumenAlumno])
def get_historial_alumno(
    idAlumno: int,
    session: SessionDep,
    cue: str = Query(...),
    current_user: Usuario = Depends(require_access_to_cue_param(ALLOWED_ALERTAS)),
):
    return get_historial_alertas_por_alumno(db=session, idAlumno=idAlumno, cue=cue)