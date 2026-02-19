# app/schemas/alerta.py
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlmodel import SQLModel, Field

from app.models.alerta import EstadoAlerta, MotivoAlerta


class AlertaListItem(SQLModel):
    idAlerta: int
    cue: str

    idAlumno: int
    alumnoNombre: str
    alumnoDni: str | None = None

    idCurso: int
    curso: str

    motivo: MotivoAlerta
    consecutivas: int

    created_at: datetime

    fechaFinRacha: date
    fechaInicioRacha: date

    detalle: Optional[str] = Field(default=None, max_length=500)  # ✅

    estado: EstadoAlerta
    ultimaAccionAt: datetime | None = None
    archivada: bool = False


class AlertaPatch(SQLModel):
    estado: Optional[EstadoAlerta] = None
    archivada: Optional[bool] = None
    actor_id: Optional[int] = None
    detalle: Optional[str] = Field(default=None, max_length=500)  # ✅


class AlertaCreate(SQLModel):
    cue: str

    idAlumno: int
    idCurso: int

    motivo: MotivoAlerta
    estado: EstadoAlerta

    detalle: Optional[str] = Field(default=None, max_length=500)  # ✅ UNA sola vez

    created_by: Optional[int] = None
    consecutivas: Optional[int] = 0
    fechaInicioRacha: Optional[date] = None
    fechaFinRacha: Optional[date] = None
