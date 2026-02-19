# app/schemas/alerta.py
from __future__ import annotations

from datetime import date, datetime
from typing import Optional
from sqlmodel import SQLModel

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

    estado: EstadoAlerta
    ultimaAccionAt: datetime | None = None
    archivada: bool = False



class AlertaPatch(SQLModel):
    estado: Optional[EstadoAlerta] = None
    archivada: Optional[bool] = None
    actor_id: Optional[int] = None


class AlertaCreate(SQLModel):
    cue: str

    idAlumno: int
    idCurso: int

    motivo: MotivoAlerta
    estado: EstadoAlerta
    detalle: Optional[str] = None
    created_by: Optional[int] = None
    consecutivas: Optional[int] = 0
    fechaInicioRacha: Optional[date] = None
    fechaFinRacha: Optional[date] = None
