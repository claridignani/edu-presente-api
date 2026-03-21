from fastapi.exceptions import RequestValidationError
from fastapi import Request
from fastapi.responses import JSONResponse

# En alumno_router.py, antes del endpoint, agregá un exception handler
# O más simple: mirá los logs de uvicorn con --log-level debug
from typing import Annotated, Optional
from fastapi import APIRouter, HTTPException, Query, Depends
from datetime import date

from app.dependencies import SessionDep
from app.dependencies.auth import get_current_user
from app.dependencies.authz import require_access_to_cue_param  # ← import faltante
from app.models.usuario import Usuario
from app.models.curso_docente import CursoDocente
from app.models.inscriptos import Inscriptos
from app.models.alumno import Alumno
from app.models.curso import Curso
from app.schemas.rol import RolDescripcion               # ← import faltante
from app.schemas.alumno import AlumnoPublic, AlumnoCreate, AlumnoUpdate
from app.schemas.parentesco import ResponsableConParentescoPublic
from app.schemas.alumno import AlumnoDetallePublic
from app.schemas.alumno_detalle import AlumnoEscuelaDetallePublic
from app.schemas.alumnos_historial import AlumnoCicloPage
from app.schemas.alumno_masivo import AlumnoMasivoRequest, AlumnoMasivoResponse, AlumnoMasivoItemResult
from app.services.alumno_service import get_certificados_alumno
from app.services.responsable_service import add_responsable, get_responsable_by_dni
from app.services.parentesco_service import upsert_parentesco, get_responsables_by_alumno
from app.core.encryption import decrypt
from app.services.alumno_service import (
    get_all_alumnos,
    get_alumnos_by_curso,
    add_alumno,
    get_one_alumno,
    update_alumno,
    get_alumnos_detalle_por_escuela,
    get_alumnos_detalle_by_curso,
    get_alumno_detalle_por_id,
    get_alumnos_historial_por_ciclo,
    buscar_alumno_por_dni,
)
from sqlmodel import select as sql_select
from sqlalchemy import and_ as sql_and

router = APIRouter(prefix="/alumnos", tags=["Alumnos"])


@router.get("/", response_model=list[AlumnoPublic])
def getAllAlumnos(
    session: SessionDep,
    offset: int = 0,
    limit: Annotated[int, Query(le=100)] = 100
):
    return get_all_alumnos(db=session, offset=offset, limit=limit)


# ── IMPORTANTE: esta ruta debe estar ANTES de /{idAlumno} ───────────────────
@router.get("/docente/", response_model=list[dict])
def get_alumnos_docente(
    cue: str,
    session: SessionDep,
    current_user: Usuario = Depends(require_access_to_cue_param([RolDescripcion.Docente])),
):
    """
    Devuelve los alumnos inscriptos en los cursos activos del docente.
    Usado por el buscador del diálogo Nueva Alerta Docente.
    """
    hoy = date.today()

    stmt_cursos = sql_select(CursoDocente.idCurso).where(
        sql_and(
            CursoDocente.idUsuario == current_user.idUsuario,
            CursoDocente.estado == "Activo",
            (CursoDocente.fechaDesde.is_(None) | (CursoDocente.fechaDesde <= hoy)),
            (CursoDocente.fechaHasta.is_(None) | (CursoDocente.fechaHasta >= hoy)),
        )
    )
    cursos_ids = [int(r) for r in session.exec(stmt_cursos).all()]

    if not cursos_ids:
        return []

    stmt = (
        sql_select(
            Alumno.idAlumno,
            Alumno.nombre,
            Alumno.apellido,
            Alumno.dni,
            Alumno.estado,
            Inscriptos.idCurso,
            Curso.nombre.label("nombreCurso"),
            Curso.division,
            Curso.cicloLectivo,
        )
        .select_from(Inscriptos)
        .join(Alumno, Alumno.idAlumno == Inscriptos.idAlumno)
        .join(Curso, Curso.idCurso == Inscriptos.idCurso)
        .where(
            sql_and(
                Inscriptos.idCurso.in_(cursos_ids),
                Inscriptos.activo.is_(True),
                Inscriptos.fechaAlta <= hoy,
                (Inscriptos.fechaBaja.is_(None) | (Inscriptos.fechaBaja >= hoy)),
            )
        )
        .order_by(Alumno.apellido, Alumno.nombre)
    )

    rows = session.exec(stmt).all()

    out = []
    for idAlumno, nombre, apellido, dni, estado, idCurso, nombreCurso, division, ciclo in rows:
        out.append({
            "idAlumno":    int(idAlumno),
            "nombre":      nombre,
            "apellido":    apellido,
            "dni":         decrypt(dni) if dni else None,
            "estado":      estado,
            "idCurso":     int(idCurso),
            "nombreCurso": f"{nombreCurso} {division} ({ciclo})".strip(),
        })

    return out


@router.get("/cursos/{idCurso}/detalle")
def get_detalle(idCurso: int, session: SessionDep, solo_activos: bool = True):
    return get_alumnos_detalle_by_curso(idCurso=idCurso, db=session, solo_activos=solo_activos)


@router.get("/escuela/{cue}/detalle", response_model=list[AlumnoEscuelaDetallePublic])
def alumnos_detalle_por_escuela(
    cue: str,
    session: SessionDep,
    cicloLectivo: Optional[str] = Query(default=None),
):
    return get_alumnos_detalle_por_escuela(
        db=session,
        cue=cue,
        ciclo_lectivo=cicloLectivo,
    )


@router.get("/escuela/{cue}/historial", response_model=AlumnoCicloPage)
def alumnos_historial_por_ciclo(
    cue: str,
    session: SessionDep,
    cicloLectivo: str = Query(...),
    q: str | None = Query(default=None),
    soloActivos: bool = Query(default=False),
    offset: int = 0,
    limit: Annotated[int, Query(ge=1, le=1000)] = 20,
):
    return get_alumnos_historial_por_ciclo(
        db=session,
        cue=cue,
        ciclo_lectivo=cicloLectivo,
        q=q,
        solo_activos=soloActivos,
        offset=offset,
        limit=limit,
    )


@router.get("/buscar-por-dni/{dni}")
def buscar_alumno_por_dni_endpoint(
    dni: str,
    session: SessionDep,
    current_user: Usuario = Depends(get_current_user),
):
    return buscar_alumno_por_dni(db=session, dni=dni, current_user=current_user)


@router.get("/cursos/{idCurso}", response_model=list[AlumnoPublic])
def getAlumnosByCurso(
    idCurso: int,
    session: SessionDep,
    offset: int = 0,
    limit: Annotated[int, Query(le=100)] = 100
):
    try:
        return get_alumnos_by_curso(idCurso=idCurso, db=session)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))
    
@router.get("/{idAlumno}/certificados", response_model=list[dict])
def get_certificados(idAlumno: int, session: SessionDep):
    return get_certificados_alumno(db=session, idAlumno=idAlumno)


@router.post("/", response_model=AlumnoPublic)
def create_alumno(
    alumno: AlumnoCreate,
    session: SessionDep,
    current_user: Usuario = Depends(get_current_user),
):
    return add_alumno(db=session, alumno_in=alumno, current_user=current_user)


# ── /{idAlumno} SIEMPRE al final para no interceptar rutas con prefijo ───────
@router.get("/{idAlumno}", response_model=AlumnoPublic)
def getAlumnoById(idAlumno: int, session: SessionDep):
    alumno = get_one_alumno(idAlumno=idAlumno, db=session)
    if not alumno:
        raise HTTPException(status_code=404, detail="Alumno no encontrado")
    return alumno


@router.get("/{idAlumno}/detalle", response_model=AlumnoEscuelaDetallePublic)
def alumno_detalle_por_id(
    idAlumno: int,
    session: SessionDep,
):
    return get_alumno_detalle_por_id(db=session, idAlumno=idAlumno)


@router.get("/{idAlumno}/responsables", response_model=list[ResponsableConParentescoPublic])
def getResponsablesAlumno(idAlumno: int, session: SessionDep):
    return get_responsables_by_alumno(db=session, idAlumno=idAlumno)


@router.put("/{idAlumno}", response_model=AlumnoPublic)
def updateAlumnoById(
    idAlumno: int,
    alumno: AlumnoUpdate,
    session: SessionDep
):
    alumno_existente = get_one_alumno(idAlumno=idAlumno, db=session)
    if not alumno_existente:
        raise HTTPException(status_code=404, detail="Alumno no encontrado")

    return update_alumno(
        alumno_existente=alumno_existente,
        alumno_nuevo=alumno,
        db=session
    )


@router.post("/cursos/{idCurso}/alta-masiva", response_model=AlumnoMasivoResponse)
def alta_masiva_alumnos_en_curso(
    idCurso: int,
    payload: AlumnoMasivoRequest,
    session: SessionDep,
    current_user: Usuario = Depends(get_current_user),
):
    results: list[AlumnoMasivoItemResult] = []
    ok_count = 0
    failed_count = 0

    for i, item in enumerate(payload.items):
        try:
            alumno_data = item.alumno.model_dump()
            alumno_data["idCurso"] = idCurso

            alumno_in = AlumnoCreate(**alumno_data)
            db_alumno = add_alumno(db=session, alumno_in=alumno_in, current_user=current_user)

            resp_dni = (item.responsable.dni or "").strip()
            if not resp_dni:
                raise HTTPException(status_code=400, detail="El DNI del responsable es obligatorio")

            db_resp = get_responsable_by_dni(db=session, dni=resp_dni)
            if not db_resp:
                db_resp = add_responsable(db=session, responsable_in=item.responsable)

            upsert_parentesco(
                db=session,
                idAlumno=int(db_alumno.idAlumno),
                idResponsable=int(db_resp.idResponsable),
                parentesco=item.parentesco,
            )

            ok_count += 1
            results.append(
                AlumnoMasivoItemResult(
                    index=i,
                    ok=True,
                    message="Creado/actualizado OK",
                    idAlumno=int(db_alumno.idAlumno),
                    idResponsable=int(db_resp.idResponsable),
                    alumnoDni=decrypt(db_alumno.dni) if db_alumno.dni else None,
                    responsableDni=decrypt(db_resp.dni) if db_resp.dni else None,
                )
            )

        except HTTPException as e:
            session.rollback()
            failed_count += 1
            results.append(
                AlumnoMasivoItemResult(
                    index=i,
                    ok=False,
                    message=f"{e.detail}",
                    alumnoDni=decrypt(getattr(item.alumno, "dni", None)),
                    responsableDni=decrypt(getattr(item.responsable, "dni", None)),
                )
            )

        except Exception as e:
            session.rollback()
            failed_count += 1
            results.append(
                AlumnoMasivoItemResult(
                    index=i,
                    ok=False,
                    message=f"Error inesperado: {str(e)}",
                    alumnoDni=decrypt(getattr(item.alumno, "dni", None)),
                    responsableDni=decrypt(getattr(item.responsable, "dni", None)),
                )
            )

    return AlumnoMasivoResponse(
        total=len(payload.items),
        ok=ok_count,
        failed=failed_count,
        results=results,
    )