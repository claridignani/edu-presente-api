# app/routers/alertas.py
from datetime import date
from typing import Optional

from fastapi import APIRouter, Query, Depends, HTTPException

from app.dependencies import SessionDep
from app.dependencies.auth import get_current_user
from app.dependencies.authz import require_access_to_cue_param

from app.models.usuario import Usuario
from app.models.alerta import EstadoAlerta

from app.schemas.rol import RolDescripcion
from app.schemas.alerta import AlertaListItem, AlertaPatch, AlertaCreate
from app.schemas.intervencion import IntervencionCreate, IntervencionPublic

from app.services.alerta_service import (
    list_alertas,
    patch_alerta,
    add_intervencion,
    list_intervenciones,
    create_alerta,
    stats_alertas_activas_por_escuela,
)

router = APIRouter(prefix="/alertas", tags=["Alertas"])

ALLOWED_ALERTAS = [RolDescripcion.Director, RolDescripcion.Asistente, RolDescripcion.Administrador]


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


# ── MODIFICADO: ahora acepta desde, hasta y cursoIds ────────────────────────
@router.get("/stats/riesgo", response_model=list[AlertaListItem])
def get_alertas_riesgo(
    session: SessionDep,
    cue: str,
    _current_user: Usuario = Depends(require_access_to_cue_param(ALLOWED_ALERTAS)),
    desde: Optional[date] = Query(default=None),
    hasta: Optional[date] = Query(default=None),
    cursoIds: Optional[list[int]] = Query(default=None),
):
    """
    Alertas activas (no archivadas) para una escuela.
    Filtra opcionalmente por período (fechaInicioRacha) y cursos.
    """
    return stats_alertas_activas_por_escuela(
        db=session,
        cue=cue,
        desde=desde,
        hasta=hasta,
        curso_ids=cursoIds,
    )
# ─────────────────────────────────────────────────────────────────────────────