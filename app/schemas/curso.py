from enum import Enum
from sqlmodel import SQLModel, Field


class TurnoCurso(str, Enum):
    Manana = "Manana"
    Tarde = "Tarde"
    DobleTurno = "DobleTurno"  # ✅ igual a la DB (sin espacio)


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
