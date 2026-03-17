# app/routers/mantenimiento.py

from fastapi import APIRouter
from app.dependencies import SessionDep
from app.services.mantenimiento_service import inactivar_suplencias_vencidas

router = APIRouter(prefix="/mantenimiento", tags=["Mantenimiento"])

@router.post("/inactivar-suplencias-vencidas")
def run_inactivar(session: SessionDep):
    n = inactivar_suplencias_vencidas(session)
    return {"ok": True, "inactivadas": n}