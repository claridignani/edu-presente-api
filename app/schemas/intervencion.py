# app/schemas/intervencion.py
from __future__ import annotations

from datetime import datetime
from typing import Optional, List

from sqlmodel import SQLModel

from app.models.intervencion import TipoIntervencion


class IntervencionCreate(SQLModel):
    tipo: TipoIntervencion
    detalle: str
    created_by: int | None = None

    # opcionales (para persistir IA + chips)
    detalleFormal: str | None = None
    tags: list[str] | None = None


class IntervencionPublic(SQLModel):
    idIntervencion: int
    idAlerta: int
    tipo: TipoIntervencion
    detalle: str
    created_by: int | None = None

    detalleFormal: str | None = None
    tags: list[str] | None = None

    created_at: datetime
