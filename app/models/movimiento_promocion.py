from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlmodel import SQLModel, Field
from sqlalchemy import Column, Date, DateTime, text


class MovimientoPromocion(SQLModel, table=True):
    __tablename__ = "movimiento_promocion"

    idMovimiento: Optional[int] = Field(default=None, primary_key=True)
    cue: str = Field(max_length=20, nullable=False)

    director_id: int = Field(nullable=False)

    idCursoOrigen: int = Field(nullable=False)
    idCursoDestino: Optional[int] = Field(default=None, nullable=True)

    fecha: date = Field(sa_column=Column(Date, nullable=False))

    estado: str = Field(default="Activo", max_length=20, nullable=False)

    created_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    )
