from enum import Enum
from sqlmodel import SQLModel, Field
from typing import List
from pydantic import BaseModel

class TurnoCurso(str, Enum):
    Manana = "Manana"
    Tarde = "Tarde"
    DobleTurno = "DobleTurno"  


class CursoBase(SQLModel):
    nombre: str = Field(max_length=255)
    cicloLectivo: str = Field(max_length=50)
    division: str = Field(max_length=50)
    turno: TurnoCurso


class CursoPublic(CursoBase):
    idCurso: int
    CUE: str


class CursoCreate(CursoBase):
    pass


class CursoUpdate(SQLModel):
    nombre: str | None = None
    cicloLectivo: str | None = None
    division: str | None = None
    turno: TurnoCurso | None = None

class CursosBulkDeleteIn(BaseModel):
    cue: str
    director_id: int
    ids: List[int]
    solo_vacios: bool = True

class CursosBulkDeleteOut(BaseModel):
    ok: bool
    eliminados: List[int] = []
    omitidos: List[dict] = []