from enum import Enum
from sqlmodel import SQLModel, Field


class RolEstado(str, Enum):
    Activo = "Activo"
    Pendiente = "Pendiente"
    Rechazado = "Rechazado"


class RolDescripcion(str, Enum):
    Director = "Director"
    Docente = "Docente"
    Administrador = "Administrador"
    Asistente = "Asistente"


class RolBase(SQLModel):
    descripcion: RolDescripcion = Field(default=RolDescripcion.Docente)
    estado: RolEstado = Field(default=RolEstado.Pendiente)


class RolPublic(RolBase):
    CUE: str
    idUsuario: int  


class RolCreate(RolBase):
    idUsuario: int
    CUE: str


class RolUpdate(SQLModel):
    idUsuario: int
    CUE: str
    estado: RolEstado  
    descripcion: RolDescripcion | None = None
