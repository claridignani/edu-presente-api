from __future__ import annotations

from typing import Annotated, List

from fastapi import APIRouter, HTTPException, Query, Depends
from sqlmodel import select

from app.dependencies import SessionDep
from app.dependencies.auth import get_current_user
from app.models.usuario import Usuario

from app.models.rol import Rol
from app.schemas.rol import RolDescripcion, RolEstado

from app.schemas.curso import CursoPublic, CursoUpdate, CursoAsignadoPublic
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


# ==========================
# Helpers de autorización
# ==========================
def _is_admin_global(session: SessionDep, user_id: int) -> bool:
    # Admin "global": si tiene al menos un rol Administrador Activo en alguna escuela
    stmt = (
        select(Rol)
        .where(Rol.idUsuario == user_id)
        .where(Rol.estado == RolEstado.Activo)
        .where(Rol.descripcion == RolDescripcion.Administrador)
    )
    return session.exec(stmt).first() is not None


def _require_access_to_cue(session: SessionDep, user_id: int, cue: str) -> None:
    # Permite si tiene rol Activo en ese CUE (cualquier rol) o si es Administrador en ese CUE
    stmt = (
        select(Rol)
        .where(Rol.idUsuario == user_id)
        .where(Rol.CUE == cue)
        .where(Rol.estado == RolEstado.Activo)
    )
    r = session.exec(stmt).first()
    if not r:
        raise HTTPException(status_code=403, detail="No autorizado para esta escuela")


# ==========================
# Endpoints
# ==========================
@router.get("/", response_model=list[CursoPublic])
def getAllCursos(
    session: SessionDep,
    offset: int = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
    current_user: Usuario = Depends(get_current_user),  # 🔒 protegido
):
    # si querés que esto sea solo admin, lo cambiamos después
    return get_all_cursos(session, offset, limit)


@router.post("/", status_code=410)
def create_curso_deprecated():
    raise HTTPException(
        status_code=410,
        detail="Usar POST /escuelas/escuelas/{cue}/cursos?usuario_id=ID_DIRECTOR",
    )


@router.get("/por-escuela/{cue}", response_model=list[CursoPublic])
def get_cursos_por_escuela(
    cue: str,
    session: SessionDep,
    cicloLectivo: str | None = None,
    current_user: Usuario = Depends(get_current_user),  # 🔒 protegido
):
    # 🔒 Solo usuarios con rol activo en esa escuela
    _require_access_to_cue(session, current_user.idUsuario, cue)
    return get_cursos_by_cue(session, cue, cicloLectivo)


@router.post("/copiar-estructura", response_model=CopiarEstructuraCursosOut)
def post_copiar_estructura(
    payload: CopiarEstructuraCursosIn,
    session: SessionDep,
    current_user: Usuario = Depends(get_current_user),  # 🔒 protegido
):
    # si esto debe ser Director/Admin, lo endurecemos después
    return copiar_estructura_cursos(db=session, payload=payload)


@router.post("/bulk-delete", response_model=CursosBulkDeleteOut)
def bulk_delete(
    payload: CursosBulkDeleteIn,
    session: SessionDep,
    current_user: Usuario = Depends(get_current_user),  # 🔒 protegido
):
    # si esto debe ser Director/Admin, lo endurecemos después
    return bulk_delete_cursos_director(
        db=session,
        cue=payload.cue,
        director_id=payload.director_id,
        ids=payload.ids,
        solo_vacios=payload.solo_vacios,
    )


@router.get("/escuelas/{idUsuario}", response_model=List[EscuelaMiniConCursos])
def get_cursos_and_escuelas_by_usuario(
    idUsuario: int,
    session: SessionDep,
    current_user: Usuario = Depends(get_current_user),  # 🔒 protegido
):
    # 🔒 Un docente solo puede pedir "sus" cursos.
    # Admin puede pedir los de cualquiera.
    if current_user.idUsuario != idUsuario and not _is_admin_global(session, current_user.idUsuario):
        raise HTTPException(status_code=403, detail="No autorizado")

    resultados = get_cursos_by_usuario(db=session, idUsuario=idUsuario)

    agrupados: dict[str, EscuelaMiniConCursos] = {}

    for curso, escuela, cd in resultados:
        cue = getattr(escuela, "CUE", None)
        nombre = getattr(escuela, "nombre", "") or ""

        if not cue:
            continue

        if cue not in agrupados:
            agrupados[cue] = EscuelaMiniConCursos(CUE=cue, nombre=nombre, cursos=[])

        base = CursoPublic.model_validate(curso, from_attributes=True).model_dump()
        agrupados[cue].cursos.append(
            CursoAsignadoPublic(**base, tipoDocente=getattr(cd, "tipo", None))
        )

    return list(agrupados.values())


@router.get("/{idCurso}", response_model=CursoPublic)
def read_curso(
    idCurso: int,
    session: SessionDep,
    current_user: Usuario = Depends(get_current_user),  # 🔒 protegido
):
    db_curso = get_one_curso(idCurso, session)
    if not db_curso:
        raise HTTPException(status_code=404, detail="Curso no encontrado")
    return db_curso


@router.patch("/{idCurso}", response_model=CursoPublic)
def update_curso(
    idCurso: int,
    curso: CursoUpdate,
    session: SessionDep,
    current_user: Usuario = Depends(get_current_user),  # 🔒 protegido
):
    db_curso = get_one_curso(idCurso, session)
    if not db_curso:
        raise HTTPException(status_code=404, detail="Curso no encontrado")
    db_curso = change_curso(curso_nuevo=curso, curso_existente=db_curso, db=session)
    return db_curso


@router.delete("/{idCurso}")
def delete_curso(
    idCurso: int,
    session: SessionDep,
    current_user: Usuario = Depends(get_current_user),  # 🔒 protegido
):
    try:
        delete_one_curso(idCurso, session)
    except Exception:
        raise HTTPException(status_code=404, detail="Curso no encontrado")
    return {"ok": True, "message": f"Curso {idCurso} eliminado correctamente"}


@router.get("/{idCurso}/docentes", response_model=list[CursoDocentePublic])
def get_docentes_de_curso(
    idCurso: int,
    session: SessionDep,
    current_user: Usuario = Depends(get_current_user),  # 🔒 protegido
):
    return listar_docentes_de_curso(session, idCurso)


@router.get("/{idCurso}/docentes-detalle", response_model=list[CursoDocenteDetalle])
def get_docentes_detalle_de_curso(
    idCurso: int,
    session: SessionDep,
    current_user: Usuario = Depends(get_current_user),  # 🔒 protegido
):
    return listar_docentes_detalle_de_curso(session, idCurso)


@router.post("/{idCurso}/docentes", response_model=CursoDocentePublic, status_code=201)
def post_asignar_docente(
    idCurso: int,
    payload: CursoDocenteCreate,
    director_id: int,
    session: SessionDep,
    current_user: Usuario = Depends(get_current_user),  # 🔒 protegido
):
    return asignar_docente_a_curso(session, idCurso, director_id, payload)