from __future__ import annotations

from pydantic import BaseModel, Field
from app.schemas.curso import TurnoCurso


class CopiarEstructuraCursosIn(BaseModel):
    cue: str = Field(..., min_length=1)
    ciclo_origen: str = Field(..., min_length=1)
    ciclo_destino: str = Field(..., min_length=1)
    director_id: int
    copiar_docentes: bool = False


class CursoMiniOut(BaseModel):
    idCurso: int
    nombre: str
    division: str
    turno: TurnoCurso
    cicloLectivo: str


class CopiarEstructuraCursosOut(BaseModel):
    ok: bool = True
    cue: str
    ciclo_origen: str
    ciclo_destino: str

    cursos_creados: list[CursoMiniOut] = []
    cursos_existentes: list[CursoMiniOut] = []

    docentes_copiados: int = 0
    docentes_omitidos_por_existir: int = 0
