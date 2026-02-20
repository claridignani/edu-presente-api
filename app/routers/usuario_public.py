# app/routers/usuario_public.py
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.dependencies import SessionDep
from app.schemas.usuario import UsuarioCreate, UsuarioPublic
from app.services.usuario_service import add_usuario, get_usuario_by_dni

router = APIRouter(prefix="/usuarios", tags=["Usuarios (Publico)"])

# =========================
# CREAR USUARIO (PUBLICO - SIN JWT)
# =========================
@router.post("/", response_model=UsuarioPublic, status_code=201)
def create_public(usuario: UsuarioCreate, session: SessionDep):
    usuario_existente = get_usuario_by_dni(session, usuario.dni)
    if usuario_existente:
        raise HTTPException(status_code=400, detail="Ya existe un usuario con este DNI")
    return add_usuario(usuario, session)

# =========================
# OBTENER USUARIO POR DNI (PUBLICO - SI TU FRONT LO USA EN REGISTRO/SOLICITAR)
# =========================
@router.get("/dni/{dni}", response_model=UsuarioPublic)
def read_by_dni_public(dni: str, session: SessionDep):
    usuario = get_usuario_by_dni(session, dni)
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    return usuario