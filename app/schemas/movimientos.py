from __future__ import annotations

from datetime import date, datetime
from pydantic import BaseModel


class MovimientoItemOut(BaseModel):
    idItem: int
    idAlumno: int
    accion: str
    idCursoOrigen: int
    idCursoDestino: int
    idInscripcionOrigen: int | None = None
    idInscripcionDestino: int | None = None


class MovimientoOut(BaseModel):
    idMovimiento: int
    cue: str
    director_id: int
    idCursoOrigen: int
    idCursoDestino: int
    fecha: date
    estado: str
    created_at: datetime | None = None


class MovimientoDetalleOut(MovimientoOut):
    items: list[MovimientoItemOut] = []


class PromocionarOut(BaseModel):
    ok: bool = True
    idMovimiento: int
