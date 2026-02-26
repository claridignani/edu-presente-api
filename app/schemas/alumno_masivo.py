# app/schemas/alumno_masivo.py
from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel, Field

from app.schemas.alumno import AlumnoCreate
from app.schemas.responsable import ResponsableCreate


class AlumnoMasivoItem(BaseModel):
    alumno: AlumnoCreate
    responsable: ResponsableCreate
    parentesco: str = Field(..., min_length=2, max_length=50)


class AlumnoMasivoRequest(BaseModel):
    items: List[AlumnoMasivoItem] = Field(..., min_length=1, max_length=200)


class AlumnoMasivoItemResult(BaseModel):
    index: int
    ok: bool
    message: str
    idAlumno: Optional[int] = None
    idResponsable: Optional[int] = None
    alumnoDni: Optional[str] = None
    responsableDni: Optional[str] = None


class AlumnoMasivoResponse(BaseModel):
    total: int
    ok: int
    failed: int
    results: List[AlumnoMasivoItemResult]