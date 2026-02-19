from __future__ import annotations

from typing import Optional
from pydantic import BaseModel

from app.schemas.inscriptos import EstadoInscripcion
from app.schemas.alumno_detalle import ResponsableMiniPublic


class AlumnoCicloRow(BaseModel):
    idAlumno: int
    nombre: str
    apellido: str
    dni: str

    # curso del ciclo consultado
    idCurso: int
    nombreCurso: str

    # curso actual (inscripción activa HOY en la escuela)
    idCursoActual: Optional[int] = None
    cursoActualNombre: Optional[str] = None

    # estado global del alumno (tabla alumno)
    estadoAlumno: str

    # estado en ese ciclo (tabla inscriptos)
    activoInscripcion: bool
    estadoInscripcion: EstadoInscripcion

    responsable: Optional[ResponsableMiniPublic] = None


class AlumnoCicloPage(BaseModel):
    total: int
    items: list[AlumnoCicloRow]
