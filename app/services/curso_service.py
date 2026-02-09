from typing import Annotated
from sqlmodel import Session, and_, select
from fastapi import HTTPException
from sqlalchemy import or_
from datetime import date
import logging
from fastapi import Query
from app.core.security import get_password_hash
from app.models.curso import Curso
from app.dependencies import SessionDep
from app.models.rol import Rol
from app.models.curso_docente import CursoDocente
from app.models.escuela import Escuela
from app.schemas.curso import CursoCreate, CursoUpdate
from app.schemas.rol import RolDescripcion, RolEstado
from app.services.rol_service import get_one_rol

logger = logging.getLogger()

def get_all_cursos(db: SessionDep, offset: int, limit: Annotated[int, Query(le=100)]):
    statement = select(Curso).offset(offset).limit(limit)
    cursos = db.exec(statement).all()
    return cursos
    

def add_curso(db: SessionDep, curso: CursoCreate):
    rol = get_one_rol(curso.idUsuario, curso.CUE, db)
    logger.info(rol)
    if not rol or rol.estado.value != "Activo":
        return None
    db_curso = Curso.model_validate(curso)
    db_curso.password = get_password_hash(curso.password)
    db.add(db_curso)
    db.commit()
    db.refresh(db_curso)
    return db_curso

def get_one_curso(idCurso: int, db: SessionDep):
    db_curso = db.get(Curso, idCurso)
    return db_curso

def delete_one_curso(idCurso: int, db: SessionDep):
    db_curso = db.get(Curso, idCurso)
    if not db_curso:
        raise Exception("Curso no encontrado")
    db.delete(db_curso)
    db.commit()

def change_curso(curso_nuevo: CursoUpdate, curso_existente: Curso, db: SessionDep):
    # Extraemos solo los campos presentes en la solicitud JSON
    curso_data = curso_nuevo.model_dump(exclude_unset=True)
    if curso_nuevo.password:
        curso_data["password"] = get_password_hash(curso_nuevo.password)
    # Actualización atómica de SQLModel
    curso_existente.sqlmodel_update(curso_data)
    db.add(curso_existente)
    db.commit()
    db.refresh(curso_existente)
    return curso_existente

def get_cursos_by_usuario(db: SessionDep, idUsuario: int):
    hoy = date.today()
    statement = (
        select(Curso, Escuela)
        .select_from(CursoDocente)
        .join(Curso, CursoDocente.idCurso == Curso.idCurso)
        .join(Escuela, Escuela.CUE == Curso.CUE)
        .where(CursoDocente.idUsuario == idUsuario, or_(CursoDocente.fechaDesde == None, CursoDocente.fechaDesde <= hoy),
            or_(CursoDocente.fechaHasta == None, CursoDocente.fechaHasta >= hoy),)
    )
    return db.exec(statement).all()


def get_cursos_by_cue(db, cue: str):
    statement = (select(Curso).where(Curso.CUE == cue))
    return db.exec(statement).all()

def add_curso_director(db: SessionDep, cue: str, idUsuarioDirector: int, curso: CursoCreate):
    # 1️⃣ validar que sea director activo
    rol = get_one_rol(idUsuarioDirector, cue, db)

    if (
        not rol
        or rol.estado != RolEstado.Activo
        or rol.descripcion != RolDescripcion.Director
    ):
        return None

    # 2️⃣ validar curso único (CUE + ciclo + nombre + división + turno)
    existente = db.exec(
        select(Curso).where(
            and_(
                Curso.CUE == cue,
                Curso.cicloLectivo == curso.cicloLectivo,
                Curso.nombre == curso.nombre,
                Curso.division == curso.division,
                Curso.turno == curso.turno,
            )
        )
    ).first()

    if existente:
        raise HTTPException(
            status_code=409,
            detail="Ya existe un curso con esos datos (turno incluido)."
        )

    db_curso = Curso(
        nombre=curso.nombre,
        cicloLectivo=curso.cicloLectivo,
        division=curso.division,
        CUE=cue,
        password=get_password_hash(curso.password),
    )

    db.add(db_curso)
    db.commit()
    db.refresh(db_curso)
    return db_curso

