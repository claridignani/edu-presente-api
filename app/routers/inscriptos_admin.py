from __future__ import annotations

from fastapi import APIRouter
from app.dependencies import SessionDep
from app.schemas.inscriptos_admin import CerrarCicloIn, CerrarCicloOut
from app.services.inscriptos_admin_service import cerrar_ciclo_por_escuela

router = APIRouter(prefix="/inscriptos", tags=["Inscriptos"])

@router.post("/cerrar-ciclo", response_model=CerrarCicloOut)
def post_cerrar_ciclo(payload: CerrarCicloIn, session: SessionDep):
    return cerrar_ciclo_por_escuela(db=session, payload=payload)
