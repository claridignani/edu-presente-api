from __future__ import annotations

from fastapi import APIRouter

from app.dependencies import SessionDep
from app.schemas.ciclo_lectivo import CicloLectivoIn, CicloLectivoOut, CicloLectivoUpdate
from app.services.ciclo_lectivo_service import (
    listar_ciclos,
    get_ciclo,
    crear_ciclo,
    actualizar_ciclo,
    eliminar_ciclo,
)

router = APIRouter(prefix="/ciclos-config", tags=["Ciclos Lectivos"])


@router.get("/{cue}", response_model=list[CicloLectivoOut])
def listar(cue: str, db: SessionDep):
    """Lista todos los ciclos lectivos configurados para una escuela."""
    return listar_ciclos(cue, db)


@router.get("/{cue}/{anio}", response_model=CicloLectivoOut)
def obtener(cue: str, anio: int, db: SessionDep):
    """Obtiene el ciclo lectivo de un año específico."""
    return get_ciclo(cue, anio, db)


@router.post("/{cue}", response_model=CicloLectivoOut, status_code=201)
def crear(cue: str, payload: CicloLectivoIn, db: SessionDep):
    """
    Crea un nuevo ciclo lectivo para la escuela.
    Incluye períodos (T1, T2, T3, PROF, ANUAL) y recesos.
    """
    return crear_ciclo(cue, payload, db)


@router.put("/{cue}/{anio}", response_model=CicloLectivoOut)
def actualizar(cue: str, anio: int, payload: CicloLectivoUpdate, db: SessionDep):
    """
    Edita fechas de inicio/fin, períodos y/o recesos de un ciclo.
    Solo los campos enviados se actualizan (períodos y recesos se reemplazan completos).
    """
    return actualizar_ciclo(cue, anio, payload, db)


@router.delete("/{cue}/{anio}")
def eliminar(cue: str, anio: int, db: SessionDep):
    """Elimina un ciclo lectivo y todos sus períodos/recesos."""
    return eliminar_ciclo(cue, anio, db)