from __future__ import annotations

from fastapi import APIRouter
from app.dependencies import SessionDep
from app.schemas.alumno import AlumnoPublic
from app.schemas.inscriptos import (
    InscriptosCreate,
    InscriptosPublic,
    PromocionarRequest,
)
from app.services.inscriptos_service import (
    inscribir_alumno,
    desinscribir_alumno,
    get_inscriptos_by_curso,
    promocionar_alumnos,
)

router = APIRouter(prefix="/inscriptos", tags=["Inscriptos"])


@router.post("/", response_model=InscriptosPublic)
def inscribir(payload: InscriptosCreate, session: SessionDep):
    return inscribir_alumno(
        idCurso=payload.idCurso,
        idAlumno=payload.idAlumno,
        db=session,
        fechaAlta=payload.fechaAlta,
    )


@router.delete("/{idCurso}/{idAlumno}", response_model=InscriptosPublic)
def desinscribir(idCurso: int, idAlumno: int, session: SessionDep):
    return desinscribir_alumno(idCurso=idCurso, idAlumno=idAlumno, db=session)


@router.get("/curso/{idCurso}", response_model=list[AlumnoPublic])
def listar_inscriptos(idCurso: int, session: SessionDep, solo_activos: bool = True):
    return get_inscriptos_by_curso(idCurso=idCurso, db=session, solo_activos=solo_activos)


@router.post("/promocionar")
def promocionar(payload: PromocionarRequest, session: SessionDep):
    return promocionar_alumnos(
        idCursoOrigen=payload.idCursoOrigen,
        idCursoDestino=payload.idCursoDestino,
        alumnos=payload.alumnos,
        db=session,
        fecha=payload.fecha,
    )
