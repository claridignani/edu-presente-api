from __future__ import annotations
from typing import Optional
from sqlmodel import SQLModel


class ResponsableMiniPublic(SQLModel):
    idResponsable: int
    nombre: str
    apellido: str
    parentesco: Optional[str] = None
    nro_celular: Optional[str] = None
    email: Optional[str] = None
    direccion: Optional[str] = None


class AlumnoEscuelaDetallePublic(SQLModel):
    idAlumno: int
    nombre: str
    apellido: str
    dni: str
    estado: str
    direccion: Optional[str] = None
    idCurso: int
    nombreCurso: str
    responsable: Optional[ResponsableMiniPublic] = None
