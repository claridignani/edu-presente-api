from __future__ import annotations

from datetime import date
from pydantic import BaseModel, Field


class CerrarCicloIn(BaseModel):
    cue: str = Field(..., min_length=1)
    ciclo_lectivo: str = Field(..., min_length=1)
    director_id: int
    fecha: date | None = None


class CerrarCicloOut(BaseModel):
    ok: bool = True
    cue: str
    ciclo_lectivo: str
    cerradas: int
