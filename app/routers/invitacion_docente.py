from fastapi import APIRouter

from app.dependencies import SessionDep
from app.schemas.invitacion_docente import (
    InvitacionDocenteCreate,
    InvitacionDocentePublic,
    InvitacionDocentePreview,
    InvitacionDocenteConsumirIn,
    InvitacionDocenteConsumirOut,
)

import app.services.invitacion_docente_service as inv_service

router = APIRouter(prefix="/invitaciones", tags=["Invitaciones"])


@router.post("/docentes", response_model=InvitacionDocentePublic, status_code=201)
def generar_invitacion_docente(payload: InvitacionDocenteCreate, session: SessionDep):
    inv = inv_service.crear_invitacion_docente(
        db=session,
        director_id=payload.director_id,
        idCurso=payload.idCurso,
        tipo=payload.tipo,
        fechaDesde=payload.fechaDesde,
        fechaHasta=payload.fechaHasta,
    )
    return inv


@router.get("/docentes/{codigo}", response_model=InvitacionDocentePreview)
def preview_invitacion_docente(codigo: str, session: SessionDep):
    inv = inv_service.get_invitacion_por_codigo(session, codigo)
    return inv


@router.post("/docentes/consumir", response_model=InvitacionDocenteConsumirOut)
def consumir_codigo_docente(payload: InvitacionDocenteConsumirIn, session: SessionDep):
    inv = inv_service.consumir_invitacion_docente(session, payload.idUsuario, payload.codigo)
    return {
        "ok": True,
        "CUE": inv.CUE,
        "idCurso": inv.idCurso,
        "tipo": inv.tipo,
        "fechaDesde": inv.fechaDesde,
        "fechaHasta": inv.fechaHasta,
    }

