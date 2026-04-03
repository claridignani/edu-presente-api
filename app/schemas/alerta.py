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

    detalle: Optional[str] = Field(default=None, max_length=500)

    # Fechas individuales: "2025-03-01,2025-03-03,..."
    # El frontend las parsea para mostrar chips o lista de días
    fechas: Optional[str] = None
    motivos_ausencia: Optional[str] = None
    estado: EstadoAlerta
    ultimaAccionAt: datetime | None = None
    archivada: bool = False
    asignado_a: Optional[int] = None

class AlertaPatch(SQLModel):
    estado: Optional[EstadoAlerta] = None
    archivada: Optional[bool] = None
    actor_id: Optional[int] = None
    detalle: Optional[str] = Field(default=None, max_length=500)
    asignado_a: Optional[int] = None


class AlertaCreate(SQLModel):
    cue: str

    idAlumno: int
    idCurso: int

    motivo: MotivoAlerta
    estado: EstadoAlerta

    detalle: Optional[str] = Field(default=None, max_length=500)

    created_by: Optional[int] = None
    consecutivas: Optional[int] = 0
    fechaInicioRacha: Optional[date] = None
    fechaFinRacha: Optional[date] = None

    # Fechas individuales opcionales al crear manualmente
    fechas: Optional[str] = None


class AlertaResumenAlumno(SQLModel):
    """Resumen de una alerta para el historial del alumno."""
    idAlerta: int
    motivo: MotivoAlerta
    estado: EstadoAlerta
    fechaCreacion: datetime
    curso: str
    consecutivas: int
    totalIntervenciones: int
    resuelta: bool
    archivada: bool

class AlertaStatsKpis(SQLModel):
    activas: int
    criticos: int
    enSeguimiento: int
    resueltas: int
    sinActividad7dias: int
