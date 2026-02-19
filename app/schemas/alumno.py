from enum import Enum
from sqlmodel import SQLModel, Field
from datetime import date
from typing import Optional
from app.schemas.parentesco import ResponsableConParentescoPublic

class AlumnoEstado(Enum):
    Activo = "Activo"
    Inactivo = "Inactivo"

class AlumnoBase(SQLModel):
    nombre: str = Field(max_length=100)
    apellido: str = Field(max_length=100)
    dni: str = Field(index=True, max_length=8)
    fecha_nacimiento: date = Field(nullable=False)
    fecha_ingreso: date = Field()
    direccion: str = Field(max_length=100)
    estado: AlumnoEstado = Field(default=AlumnoEstado.Inactivo)

class AlumnoPublic(AlumnoBase):
    idAlumno: int

class AlumnoCreate(AlumnoBase):
    idCurso: Optional[int] = None
    CUE: Optional[str] = None
    cicloLectivo: Optional[str] = None

class AlumnoUpdate(SQLModel):
    nombre: str | None = None
    apellido: str | None = None
    dni: str | None = None
    fecha_nacimiento: date | None = None
    fecha_ingreso: date | None = None
    direccion: str | None = None
    estado: AlumnoEstado | None = None

class AlumnoDetallePublic(SQLModel):
    idAlumno: int
    nombre: str
    apellido: str
    dni: str
    estado: str
    responsable: Optional[ResponsableConParentescoPublic] = None


