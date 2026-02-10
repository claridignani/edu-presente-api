from __future__ import annotations

from typing import Annotated, List

from fastapi import APIRouter, HTTPException, Query

from app.dependencies import SessionDep
from app.schemas.curso import CursoPublic, CursoUpdate
from app.schemas.escuela import EscuelaMiniConCursos  # ✅ CAMBIO
from app.schemas.curso_docente import CursoDocenteCreate, CursoDocentePublic

from app.services.curso_docente_service import asignar_docente_a_curso, listar_docentes_de_curso
from app.services.curso_service import (
    change_curso,
    delete_one_curso,
    get_all_cursos,
    get_cursos_by_usuario,
    get_one_curso,
    get_cursos_by_cue,
)

router = APIRouter(prefix="/cursos", tags=["Cursos"])


@router.get("/", response_model=list[CursoPublic])
def getAllCursos(
    session: SessionDep,
    offset: int = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
):
    """Obtiene la lista de todos los cursos con paginación."""
    return get_all_cursos(session, offset, limit)


@router.post("/", status_code=410)
def create_curso_deprecated():
    raise HTTPException(
        status_code=410,
        detail="Usar POST /escuelas/escuelas/{cue}/cursos?usuario_id=ID_DIRECTOR",
    )


@router.get("/{idCurso}", response_model=CursoPublic)
def read_curso(idCurso: int, session: SessionDep):
    """Obtiene un curso específico por su ID."""
    db_curso = get_one_curso(idCurso, session)
    if not db_curso:
        raise HTTPException(status_code=404, detail="Curso no encontrado")
    return db_curso


@router.patch("/{idCurso}", response_model=CursoPublic)
def update_curso(idCurso: int, curso: CursoUpdate, session: SessionDep):
    """Actualiza los datos de un curso de forma parcial (PATCH)."""
    db_curso = get_one_curso(idCurso, session)
    if not db_curso:
        raise HTTPException(status_code=404, detail="Curso no encontrado")
    db_curso = change_curso(curso_nuevo=curso, curso_existente=db_curso, db=session)
    return db_curso


@router.get("/por-escuela/{cue}", response_model=list[CursoPublic])
def get_cursos_por_escuela(cue: str, session: SessionDep):
    return get_cursos_by_cue(session, cue)


# ✅ CAMBIO: EscuelaMiniConCursos en lugar de EscuelaConCursos
@router.get("/escuelas/{idUsuario}", response_model=List[EscuelaMiniConCursos])
def get_cursos_and_escuelas_by_usuario(idUsuario: int, session: SessionDep):
    """
    Devuelve escuelas (mini) asociadas a ese usuario y, para cada escuela,
    una lista de cursos en los que el usuario tiene participación.
    """
    resultados = get_cursos_by_usuario(db=session, idUsuario=idUsuario)

    agrupados: dict[str, EscuelaMiniConCursos] = {}

    for curso, escuela in resultados:
        cue = getattr(escuela, "CUE", None)
        nombre = getattr(escuela, "nombre", "") or ""

        if not cue:
            # si por algún motivo viene escuela sin CUE, la salteamos
            continue

        if cue not in agrupados:
            agrupados[cue] = EscuelaMiniConCursos(
                CUE=cue,
                nombre=nombre,
                cursos=[],
            )

        # ✅ importante: from_attributes=True para instancias SQLModel
        agrupados[cue].cursos.append(CursoPublic.model_validate(curso, from_attributes=True))

    return list(agrupados.values())


@router.delete("/{idCurso}")
def delete_curso(idCurso: int, session: SessionDep):
    """Elimina un curso por su ID."""
    try:
        delete_one_curso(idCurso, session)
    except Exception:
        raise HTTPException(status_code=404, detail="Curso no encontrado")
    return {"ok": True, "message": f"Curso {idCurso} eliminado correctamente"}


@router.get("/{idCurso}/docentes", response_model=list[CursoDocentePublic])
def get_docentes_de_curso(idCurso: int, session: SessionDep):
    return listar_docentes_de_curso(session, idCurso)


@router.post("/{idCurso}/docentes", response_model=CursoDocentePublic, status_code=201)
def post_asignar_docente(
    idCurso: int,
    payload: CursoDocenteCreate,
    director_id: int,  # query param: ?director_id=7
    session: SessionDep,
):
    return asignar_docente_a_curso(session, idCurso, director_id, payload)
