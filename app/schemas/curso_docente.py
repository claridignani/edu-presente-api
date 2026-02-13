from datetime import date
from sqlmodel import SQLModel, Field
from typing import Optional

class CursoDocenteCreate(SQLModel):
    idUsuario: int
    tipo: str = Field(default="Titular")  # Titular | Suplente
    fechaDesde: date | None = None
    fechaHasta: date | None = None

class CursoDocentePublic(SQLModel):
    idCurso: int
    idUsuario: int
    tipo: str
    fechaDesde: date | None = None
    fechaHasta: date | None = None

class CursoDocenteDetalle(SQLModel):
    idCurso: int
    idUsuario: int
    nombre: str
    apellido: str
    dni: str
    tipo: str
    fechaDesde: Optional[date] = None
    fechaHasta: Optional[date] = None
    estado: str

