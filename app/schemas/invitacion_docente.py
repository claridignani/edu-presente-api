from datetime import datetime, date
from typing import Optional
from sqlmodel import SQLModel, Field

class InvitacionDocenteCreate(SQLModel):
    director_id: int
    idCurso: int
    tipo: str = Field(default="Suplente", max_length=20)
    idUsuario: Optional[int] = None    # ← NUEVO
    fechaDesde: date | None = None
    fechaHasta: date | None = None

class InvitacionDocentePublic(SQLModel):
    idInvitacion: int
    codigo: str
    CUE: str
    idCurso: int
    tipo: str
    idUsuario: Optional[int] = None    # ← NUEVO
    fechaDesde: date | None = None
    fechaHasta: date | None = None
    usada: bool
    fechaCreacion: datetime
    fechaUso: datetime | None = None

class InvitacionDocentePreview(SQLModel):
    codigo: str
    CUE: str
    idCurso: int
    tipo: str
    fechaDesde: date | None = None
    fechaHasta: date | None = None
    usada: bool

class InvitacionDocenteConsumirIn(SQLModel):
    idUsuario: int
    codigo: str

class InvitacionDocenteConsumirOut(SQLModel):
    ok: bool
    CUE: str
    idCurso: int
    tipo: str
    fechaDesde: date | None = None
    fechaHasta: date | None = None