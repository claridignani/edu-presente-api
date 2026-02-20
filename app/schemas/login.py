from pydantic import BaseModel
from typing import List, Optional


class LoginRequest(BaseModel):
    dni: str
    password: str


class OpcionRol(BaseModel):
    idUsuario: Optional[int] = None
    descripcion: str
    CUE: str
    nombre_escuela: str


class LoginResponse(BaseModel):
    mensaje: str
    usuario_id: Optional[int] = None
    nombre: str
    apellido: str
    roles_disponibles: List[OpcionRol]
    access_token: str
    token_type: str = "bearer"
