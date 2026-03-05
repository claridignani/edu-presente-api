from fastapi import APIRouter
from app.dependencies import SessionDep
from app.models.preinscripcion import Preinscripcion
from app.models.alumno import Alumno
from sqlmodel import select
from app.core.encryption import decrypt  # agregar este import

router = APIRouter(prefix="/preinscripciones", tags=["Preinscripciones"])

@router.get("/escuela/{cue}")
def get_preinscripciones_escuela(
    cue: str,
    cicloLectivo: str,
    session: SessionDep
):
    stmt = (
        select(Preinscripcion, Alumno)
        .join(Alumno, Alumno.idAlumno == Preinscripcion.idAlumno)
        .where(Preinscripcion.CUE == cue)
        .where(Preinscripcion.cicloLectivo == cicloLectivo)
        .where(Preinscripcion.estado == "Pendiente")
    )

    rows = session.exec(stmt).all()

    return [
        {
            "idAlumno": alumno.idAlumno,
            "nombre": alumno.nombre,
            "apellido": alumno.apellido,
            "dni": decrypt(alumno.dni) if alumno.dni else None,  # ← fix
            "estado": "Pendiente",
            "idCurso": 0,
            "nombreCurso": "Sin asignar",
        }
        for pre, alumno in rows
    ]