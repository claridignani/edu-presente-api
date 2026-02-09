from datetime import date
from typing import Optional
from sqlmodel import SQLModel, Field
from app.schemas.rol import RolDescripcion, RolPublic

class UsuarioBase(SQLModel):
    dni: str = Field(index=True, max_length=8)
    cuil: str = Field(index=True, max_length=11)
    celular: str = Field(max_length=15)
    mailABC: str = Field(index=True)
    fechaNacimiento: date | None = None  
    nombre: str = Field(max_length=100)
    apellido: str = Field(max_length=100)

class UsuarioPublic(UsuarioBase):
    idUsuario: int

class UsuarioCreate(UsuarioBase):
    contrasena: str
    rol: RolDescripcion
    escuelasCUE: list[str] 
    codigoInvitacion: Optional[str] = None

class UsuarioUpdate(SQLModel):
    nombre: str | None = None          
    apellido: str | None = None 
    dni: str | None = None
    cuil: str | None = None
    celular: str | None = None
    mailABC: str | None = None
    fechaNacimiento: date | None = None 
    contrasena: str | None = None

class Usuario_Roles(UsuarioPublic):
    rol: RolPublic
