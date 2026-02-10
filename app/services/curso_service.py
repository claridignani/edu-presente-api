from __future__ import annotations

from typing import Annotated
from datetime import date
import logging

from fastapi import HTTPException, Query
from sqlalchemy import and_, or_
from sqlmodel import select

from app.dependencies import SessionDep
from app.models.curso import Curso
from app.models.curso_docente import CursoDocente
from app.models.escuela import Escuela
from app.schemas.curso import CursoCreate, CursoUpdate, TurnoCurso
from app.schemas.rol import RolDescripcion, RolEstado
from app.services.rol_service import get_one_rol

logger = logging.getLogger(__name__)

# =========================
# Helpers
# =========================

def normalize_turno(turno) -> TurnoCurso:
    if turno is None:
        return TurnoCurso.Manana

    if isinstance(turno, TurnoCurso):
        return turno

    t = str(turno).strip()

    if t in ("Mañana", "Manana", "manana"):
        return TurnoCurso.Manana
    if t in ("Tarde", "tarde"):
        return TurnoCurso.Tarde
    if t in ("DobleTurno", "Doble turno", "doble turno", "Doble Turno"):
        return TurnoCurso.DobleTurno

    return TurnoCurso.Manana


# =========================
# CRUD Cursos
# =========================

def get_all_cursos(
    db: SessionDep,
    offset: int,
    limit: Annotated[int, Query(le=100)] = 100,
):
    stmt = select(Curso).offset(offset).limit(limit)
    return db.exec(stmt).all()


def add_curso(db: SessionDep, curso: CursoCreate):
    """
    ✅ Compat: no lo uses para crear por escuela.
    Lo dejamos para que NO rompan imports viejos, pero exige que el payload traiga CUE.
    """
    cue = getattr(curso, "CUE", None)
    if not cue:
        raise HTTPException(
            status_code=400,
            detail="Falta CUE. Usar POST /escuelas/escuelas/{cue}/cursos?usuario_id=ID_DIRECTOR",
        )

    db_curso = Curso(
        nombre=curso.nombre,
        cicloLectivo=curso.cicloLectivo,
        division=curso.division,
        turno=normalize_turno(curso.turno),
        CUE=cue,
    )
    db.add(db_curso)
    db.commit()
    db.refresh(db_curso)
    return db_curso


def get_one_curso(idCurso: int, db: SessionDep):
    return db.get(Curso, idCurso)


def delete_one_curso(idCurso: int, db: SessionDep):
    curso = db.get(Curso, idCurso)
    if not curso:
        raise Exception("Curso no encontrado")
    db.delete(curso)
    db.commit()


def change_curso(
    curso_nuevo: CursoUpdate,
    curso_existente: Curso,
    db: SessionDep,
):
    data = curso_nuevo.model_dump(exclude_unset=True)

    if "turno" in data:
        data["turno"] = normalize_turno(data["turno"])

    curso_existente.sqlmodel_update(data)
    db.add(curso_existente)
    db.commit()
    db.refresh(curso_existente)
    return curso_existente


# =========================
# Queries
# =========================

def get_cursos_by_usuario(db: SessionDep, idUsuario: int):
    hoy = date.today()

    stmt = (
        select(Curso, Escuela)
        .select_from(CursoDocente)
        .join(Curso, CursoDocente.idCurso == Curso.idCurso)
        .join(Escuela, Escuela.CUE == Curso.CUE)
        .where(
            CursoDocente.idUsuario == idUsuario,
            or_(CursoDocente.fechaDesde == None, CursoDocente.fechaDesde <= hoy),
            or_(CursoDocente.fechaHasta == None, CursoDocente.fechaHasta >= hoy),
        )
    )

    return db.exec(stmt).all()


def get_cursos_by_cue(db: SessionDep, cue: str):
    stmt = select(Curso).where(Curso.CUE == cue)
    return db.exec(stmt).all()


# =========================
# Crear curso (Director)
# =========================

def add_curso_director(
    db: SessionDep,
    cue: str,
    idUsuarioDirector: int,
    curso: CursoCreate,
):
    rol = get_one_rol(idUsuarioDirector, cue, db)
    if (
        not rol
        or rol.estado != RolEstado.Activo
        or rol.descripcion != RolDescripcion.Director
    ):
        raise HTTPException(status_code=403, detail="Solo un Director Activo puede crear cursos")

    turno_enum = normalize_turno(curso.turno)

    existente = db.exec(
        select(Curso).where(
            and_(
                Curso.CUE == cue,
                Curso.cicloLectivo == curso.cicloLectivo,
                Curso.nombre == curso.nombre,
                Curso.division == curso.division,
                Curso.turno == turno_enum,  
            )
        )
    ).first()

    if existente:
        raise HTTPException(
            status_code=409,
            detail="Ya existe un curso con esos datos (turno incluido).",
        )

    db_curso = Curso(
        nombre=curso.nombre,
        cicloLectivo=curso.cicloLectivo,
        division=curso.division,
        turno=turno_enum,  # 👈 Enum
        CUE=cue,
    )

    db.add(db_curso)
    db.commit()
    db.refresh(db_curso)
    return db_curso
