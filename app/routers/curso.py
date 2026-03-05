from __future__ import annotations

from typing import Annotated, List
from datetime import date as _date

from fastapi import APIRouter, HTTPException, Query, Depends
from sqlalchemy import func
from sqlmodel import select

from app.dependencies import SessionDep
from app.dependencies.auth import get_current_user
from app.models.usuario import Usuario
from app.models.curso import Curso
from app.models.curso_docente import CursoDocente
from app.models.inscriptos import Inscriptos

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
    stmt = (
        select(Rol)
        .where(Rol.idUsuario == user_id)
        .where(Rol.estado == RolEstado.Activo)
        .where(Rol.descripcion == RolDescripcion.Administrador)
    )
    return session.exec(stmt).first() is not None


def _require_access_to_cue(session: SessionDep, user_id: int, cue: str) -> None:
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
    current_user: Usuario = Depends(get_current_user),
):
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
    current_user: Usuario = Depends(get_current_user),
):
    _require_access_to_cue(session, current_user.idUsuario, cue)
    return get_cursos_by_cue(session, cue, cicloLectivo)


# ==========================
# ✅ NUEVO — Resumen optimizado
# Devuelve cursos + cantidad alumnos + docentes activos
# en UNA sola respuesta (3 queries en lugar de N*3 requests)
# IMPORTANTE: debe estar ANTES de /{idCurso} para que FastAPI
# no interprete "resumen" como un idCurso numérico.
# ==========================
@router.get("/por-escuela/{cue}/resumen")
def get_cursos_resumen(
    cue: str,
    session: SessionDep,
    cicloLectivo: str | None = None,
    current_user: Usuario = Depends(get_current_user),
):
    """
    Endpoint optimizado para la vista de cursos del director.
    Reemplaza las N llamadas individuales a:
      - /alumnos/cursos/{id}        (cantidad alumnos)
      - /cursos/{id}/docentes       (docentes del curso)
      - /usuarios/{id}              (nombre de cada docente)
    """
    _require_access_to_cue(session, current_user.idUsuario, cue)

    # 1) Cursos de la escuela filtrados por ciclo
    stmt_cursos = select(Curso).where(Curso.CUE == cue)
    if cicloLectivo:
        stmt_cursos = stmt_cursos.where(Curso.cicloLectivo == cicloLectivo)
    cursos = session.exec(stmt_cursos).all()

    if not cursos:
        return []

    curso_ids = [c.idCurso for c in cursos]

    # 2) Contar alumnos activos por curso — una sola query con GROUP BY
    stmt_alumnos = (
        select(Inscriptos.idCurso, func.count(Inscriptos.idAlumno).label("total"))
        .where(
            Inscriptos.idCurso.in_(curso_ids),
            Inscriptos.activo == True,
        )
        .group_by(Inscriptos.idCurso)
    )
    counts_map: dict[int, int] = {
        row.idCurso: row.total
        for row in session.exec(stmt_alumnos).all()
    }

    # 3) Docentes activos de esos cursos — una sola query con JOIN
    hoy = _date.today()
    stmt_docentes = (
        select(CursoDocente, Usuario)
        .join(Usuario, CursoDocente.idUsuario == Usuario.idUsuario)
        .where(
            CursoDocente.idCurso.in_(curso_ids),
            CursoDocente.estado == "Activo",
            (CursoDocente.fechaDesde == None) | (CursoDocente.fechaDesde <= hoy),
            (CursoDocente.fechaHasta == None) | (CursoDocente.fechaHasta >= hoy),
        )
    )
    docentes_map: dict[int, list[dict]] = {}
    for cd, u in session.exec(stmt_docentes).all():
        docentes_map.setdefault(cd.idCurso, []).append({
            "idUsuario": u.idUsuario,
            "nombre":    u.nombre,
            "apellido":  u.apellido,
            "tipo":      cd.tipo or "Titular",
        })

    # 4) Armar y devolver respuesta
    return [
        {
            "idCurso":         c.idCurso,
            "nombre":          c.nombre,
            "division":        c.division,
            "turno":           c.turno,
            "cicloLectivo":    c.cicloLectivo,
            "cantidadAlumnos": counts_map.get(c.idCurso, 0),
            "docentes":        docentes_map.get(c.idCurso, []),
        }
        for c in cursos
    ]


@router.post("/copiar-estructura", response_model=CopiarEstructuraCursosOut)
def post_copiar_estructura(
    payload: CopiarEstructuraCursosIn,
    session: SessionDep,
    current_user: Usuario = Depends(get_current_user),
):
    return copiar_estructura_cursos(db=session, payload=payload)


@router.post("/bulk-delete", response_model=CursosBulkDeleteOut)
def bulk_delete(
    payload: CursosBulkDeleteIn,
    session: SessionDep,
    current_user: Usuario = Depends(get_current_user),
):
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
    current_user: Usuario = Depends(get_current_user),
):
    if current_user.idUsuario != idUsuario and not _is_admin_global(session, current_user.idUsuario):
        raise HTTPException(status_code=403, detail="No autorizado")

    resultados = get_cursos_by_usuario(db=session, idUsuario=idUsuario)

    agrupados: dict[str, EscuelaMiniConCursos] = {}

    for curso, escuela, cd in resultados:
        cue    = getattr(escuela, "CUE", None)
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
    current_user: Usuario = Depends(get_current_user),
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
    current_user: Usuario = Depends(get_current_user),
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
    current_user: Usuario = Depends(get_current_user),
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
    current_user: Usuario = Depends(get_current_user),
):
    return listar_docentes_de_curso(session, idCurso)


@router.get("/{idCurso}/docentes-detalle", response_model=list[CursoDocenteDetalle])
def get_docentes_detalle_de_curso(
    idCurso: int,
    session: SessionDep,
    current_user: Usuario = Depends(get_current_user),
):
    return listar_docentes_detalle_de_curso(session, idCurso)


@router.post("/{idCurso}/docentes", response_model=CursoDocentePublic, status_code=201)
def post_asignar_docente(
    idCurso: int,
    payload: CursoDocenteCreate,
    director_id: int,
    session: SessionDep,
    current_user: Usuario = Depends(get_current_user),
):
    return asignar_docente_a_curso(session, idCurso, director_id, payload)