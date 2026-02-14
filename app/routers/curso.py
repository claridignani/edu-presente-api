from __future__ import annotations

from typing import Annotated, List
from fastapi import APIRouter, HTTPException, Query

from app.dependencies import SessionDep
from app.schemas.curso import CursoPublic, CursoUpdate
from app.schemas.escuela import EscuelaMiniConCursos
from app.schemas.curso_docente import CursoDocenteCreate, CursoDocentePublic, CursoDocenteDetalle
from app.schemas.cursos_admin import CopiarEstructuraCursosIn, CopiarEstructuraCursosOut
from app.services.curso_service import copiar_estructura_cursos
from app.schemas.curso import CursosBulkDeleteIn, CursosBulkDeleteOut
from app.services.curso_service import bulk_delete_cursos_director

from app.services.curso_docente_service import (
    asignar_docente_a_curso,
    listar_docentes_de_curso,
    listar_docentes_detalle_de_curso,
)

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
    return get_all_cursos(session, offset, limit)


@router.post("/", status_code=410)
def create_curso_deprecated():
    raise HTTPException(
        status_code=410,
        detail="Usar POST /escuelas/escuelas/{cue}/cursos?usuario_id=ID_DIRECTOR",
    )


@router.get("/por-escuela/{cue}", response_model=list[CursoPublic])
def get_cursos_por_escuela(cue: str, session: SessionDep):
    return get_cursos_by_cue(session, cue)

@router.post("/copiar-estructura", response_model=CopiarEstructuraCursosOut)
def post_copiar_estructura(payload: CopiarEstructuraCursosIn, session: SessionDep):
    return copiar_estructura_cursos(db=session, payload=payload)

@router.post("/bulk-delete", response_model=CursosBulkDeleteOut)
def bulk_delete(payload: CursosBulkDeleteIn, session: SessionDep):
    return bulk_delete_cursos_director(
        db=session,
        cue=payload.cue,
        director_id=payload.director_id,
        ids=payload.ids,
        solo_vacios=payload.solo_vacios,
    )

@router.get("/escuelas/{idUsuario}", response_model=List[EscuelaMiniConCursos])
def get_cursos_and_escuelas_by_usuario(idUsuario: int, session: SessionDep):
    resultados = get_cursos_by_usuario(db=session, idUsuario=idUsuario)

    agrupados: dict[str, EscuelaMiniConCursos] = {}

    for curso, escuela in resultados:
        cue = getattr(escuela, "CUE", None)
        nombre = getattr(escuela, "nombre", "") or ""

        if not cue:
            continue

        if cue not in agrupados:
            agrupados[cue] = EscuelaMiniConCursos(CUE=cue, nombre=nombre, cursos=[])

        agrupados[cue].cursos.append(CursoPublic.model_validate(curso, from_attributes=True))

    return list(agrupados.values())


@router.get("/{idCurso}", response_model=CursoPublic)
def read_curso(idCurso: int, session: SessionDep):
    db_curso = get_one_curso(idCurso, session)
    if not db_curso:
        raise HTTPException(status_code=404, detail="Curso no encontrado")
    return db_curso


@router.patch("/{idCurso}", response_model=CursoPublic)
def update_curso(idCurso: int, curso: CursoUpdate, session: SessionDep):
    db_curso = get_one_curso(idCurso, session)
    if not db_curso:
        raise HTTPException(status_code=404, detail="Curso no encontrado")
    db_curso = change_curso(curso_nuevo=curso, curso_existente=db_curso, db=session)
    return db_curso


@router.delete("/{idCurso}")
def delete_curso(idCurso: int, session: SessionDep):
    try:
        delete_one_curso(idCurso, session)
    except Exception:
        raise HTTPException(status_code=404, detail="Curso no encontrado")
    return {"ok": True, "message": f"Curso {idCurso} eliminado correctamente"}


@router.get("/{idCurso}/docentes", response_model=list[CursoDocentePublic])
def get_docentes_de_curso(idCurso: int, session: SessionDep):
    return listar_docentes_de_curso(session, idCurso)


@router.get("/{idCurso}/docentes-detalle", response_model=list[CursoDocenteDetalle])
def get_docentes_detalle_de_curso(idCurso: int, session: SessionDep):
    return listar_docentes_detalle_de_curso(session, idCurso)


@router.post("/{idCurso}/docentes", response_model=CursoDocentePublic, status_code=201)
def post_asignar_docente(
    idCurso: int,
    payload: CursoDocenteCreate,
    director_id: int,
    session: SessionDep,
):
    return asignar_docente_a_curso(session, idCurso, director_id, payload)
