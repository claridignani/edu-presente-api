from fastapi import APIRouter

from app.dependencies import SessionDep
from app.schemas.invitacion_docente import InvitacionDocentePreview
import app.services.invitacion_docente_service as inv_service

router = APIRouter(prefix="/invitaciones", tags=["Invitaciones (Publico)"])


@router.get("/docentes/{codigo}", response_model=InvitacionDocentePreview)
def preview_invitacion_docente_publico(codigo: str, session: SessionDep):
    # Si el service ya lanza HTTPException cuando no existe / está usada, perfecto.
    # Si devuelve None, ajustamos después.
    inv = inv_service.get_invitacion_por_codigo(session, codigo)
    return inv