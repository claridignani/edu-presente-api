from fastapi import APIRouter, Depends, HTTPException
from app.dependencies import SessionDep
from app.dependencies.auth import get_current_user
from app.models.usuario import Usuario

from app.schemas.alumno import AlumnoPublic
from app.schemas.inscriptos import (
    InscriptosCreate,
    InscriptosPublic,
    PromocionarRequest,
    InscripcionHistorialOut,
)
from app.schemas.movimientos import (
    PromocionarOut,
    MovimientoDetalleOut,
    MovimientoHistorialOut,
)

from app.services import inscriptos_service
from app.services.inscriptos_service import (
    inscribir_alumno,
    desinscribir_alumno,
    get_inscriptos_by_curso,
    promocionar_alumnos,
    listar_movimientos_por_cue,
    detalle_movimiento,
    deshacer_movimiento,
    get_historial_inscripciones_alumno,
)

router = APIRouter(prefix="/inscriptos", tags=["Inscriptos"])


@router.post("/", response_model=InscriptosPublic)
def inscribir(payload: InscriptosCreate, session: SessionDep, current_user: Usuario = Depends(get_current_user)):
    return inscribir_alumno(
        idCurso=payload.idCurso,
        idAlumno=payload.idAlumno,
        db=session,
        fechaAlta=payload.fechaAlta,
    )

@router.delete("/{idCurso}/{idAlumno}", response_model=InscriptosPublic)
def desinscribir(idCurso: int, idAlumno: int, session: SessionDep, current_user: Usuario = Depends(get_current_user)):
    return desinscribir_alumno(idCurso=idCurso, idAlumno=idAlumno, db=session)


@router.get("/curso/{idCurso}", response_model=list[AlumnoPublic])
def listar_inscriptos(idCurso: int, session: SessionDep, solo_activos: bool = True):
    return get_inscriptos_by_curso(idCurso=idCurso, db=session, solo_activos=solo_activos)


@router.post("/promocionar", response_model=PromocionarOut)
def promocionar(payload: PromocionarRequest, session: SessionDep):
    return promocionar_alumnos(
        idCursoOrigen=payload.idCursoOrigen,
        idCursoDestino=payload.idCursoDestino,
        alumnos=payload.alumnos,
        db=session,
        fecha=payload.fecha,
        director_id=payload.director_id,
    )


# últimos movimientos por CUE
@router.get("/movimientos", response_model=list[MovimientoHistorialOut])
def listar_movimientos(cue: str, session: SessionDep, limit: int = 20):
    return listar_movimientos_por_cue(db=session, cue=cue, limit=limit)


@router.get("/movimientos/{idMovimiento}", response_model=MovimientoDetalleOut)
def obtener_detalle(idMovimiento: int, session: SessionDep):
    return detalle_movimiento(db=session, idMovimiento=idMovimiento)


@router.post("/movimientos/{idMovimiento}/deshacer")
def movimiento_deshacer(idMovimiento: int, session: SessionDep):
    return deshacer_movimiento(db=session, idMovimiento=idMovimiento)


@router.get("/alumno/{id_alumno}/timeline")
def leer_timeline_alumno(id_alumno: int, db: SessionDep):
    """
    Retorna la cronología de movimientos (promociones, repitencias, etc) de un alumno.
    """
    return inscriptos_service.get_timeline_alumno(db=db, id_alumno=id_alumno)


@router.get("/auditoria-alumnos")
def listar_auditoria_alumnos(cue: str, session: SessionDep, anio: str = None, accion: str = None):
    """
    Lista plana para auditoría global (movimientos promocionar).
    """
    return inscriptos_service.get_auditoria_alumnos_detalle(
        db=session, cue=cue, anio=anio, accion=accion
    )


@router.get("/alumno/{idAlumno}/historial", response_model=list[InscripcionHistorialOut])
def historial_inscripciones_alumno(idAlumno: int, session: SessionDep):
    return get_historial_inscripciones_alumno(db=session, idAlumno=idAlumno)
