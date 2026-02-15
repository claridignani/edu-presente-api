from __future__ import annotations

from typing import Optional
from sqlmodel import SQLModel, Field


class MovimientoPromocionItem(SQLModel, table=True):
    __tablename__ = "movimiento_promocion_item"

    idItem: Optional[int] = Field(default=None, primary_key=True)

    idMovimiento: int = Field(foreign_key="movimiento_promocion.idMovimiento", nullable=False)

    idAlumno: int = Field(nullable=False)
    accion: str = Field(max_length=20, nullable=False)

    idCursoOrigen: int = Field(nullable=False)
    idCursoDestino: int = Field(nullable=False)

    idInscripcionOrigen: Optional[int] = Field(default=None, nullable=True)
    idInscripcionDestino: Optional[int] = Field(default=None, nullable=True)
