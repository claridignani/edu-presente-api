# app/schemas/intervencion.py
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import SQLModel

from app.models.intervencion import TipoIntervencion, EventoHistorial
from app.models.alerta import EstadoAlerta


class IntervencionCreate(SQLModel):
    tipo: TipoIntervencion
    detalle: str
    created_by: int | None = None

    detalleFormal: str | None = None
    tags: list[str] | None = None


class IntervencionPublic(SQLModel):
    idIntervencion: int
    idAlerta: int

    # ✅ historial
    evento: EventoHistorial

    # si evento=INTERVENCION
    tipo: TipoIntervencion | None = None
    detalle: str

    # actor
    created_by: int | None = None
    actor_nombre: str | None = None
    actor_rol: str | None = None

    # auditoría de cambios
    estado_anterior: EstadoAlerta | None = None
    estado_nuevo: EstadoAlerta | None = None
    archivada_anterior: bool | None = None
    archivada_nueva: bool | None = None

    detalleFormal: str | None = None
    tags: list[str] | None = None

    created_at: datetime
