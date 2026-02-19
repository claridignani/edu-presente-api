# app/routers/alertas.py
from datetime import date
from typing import Optional

from fastapi import APIRouter, Query
from app.dependencies import SessionDep

from app.models.alerta import EstadoAlerta
from app.schemas.alerta import AlertaListItem, AlertaPatch, AlertaCreate
from app.schemas.intervencion import IntervencionCreate, IntervencionPublic
from app.services.alerta_service import (
    list_alertas,
    patch_alerta,
    add_intervencion,
    list_intervenciones,
    create_alerta,
    stats_alertas_activas_por_escuela
) 
router = APIRouter(prefix="/alertas", tags=["Alertas"])


@router.get("/", response_model=list[AlertaListItem])
def get_alertas(
    session: SessionDep,
    cue: str,
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
    payload: AlertaCreate,
    session: SessionDep,
):
    a = create_alerta(db=session, payload=payload)
    return {"ok": True, "idAlerta": a.idAlerta}


@router.patch("/{idAlerta}", response_model=dict)
def update_alerta(
    idAlerta: int,
    payload: AlertaPatch,
    session: SessionDep,
):
    a = patch_alerta(db=session, idAlerta=idAlerta, patch=payload)
    return {"ok": True, "idAlerta": a.idAlerta, "estado": a.estado, "archivada": a.archivada}

@router.get("/{idAlerta}/intervenciones", response_model=list[IntervencionPublic])
def get_intervenciones(
    idAlerta: int,
    session: SessionDep,
):
    return list_intervenciones(db=session, idAlerta=idAlerta)

@router.post("/{idAlerta}/intervenciones", response_model=IntervencionPublic)
def create_intervencion(
    idAlerta: int,
    payload: IntervencionCreate,
    session: SessionDep,
):
    return add_intervencion(db=session, idAlerta=idAlerta, payload=payload)

@router.get("/stats/riesgo", response_model=list[AlertaListItem])
def get_alertas_riesgo(
    session: SessionDep,
    cue: str,
):
    return stats_alertas_activas_por_escuela(
        db=session,
        cue=cue,
    )