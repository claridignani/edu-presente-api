from __future__ import annotations

import re
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, distinct, or_
from sqlmodel import select

from app.dependencies import SessionDep
from app.models.escuela import Escuela
from app.models.curso import Curso
from app.models.inscriptos import Inscriptos
from app.schemas.escuela import EscuelaCreate, EscuelaPublic, EscuelaUpdate
from app.schemas.curso import CursoCreate, CursoPublic
from app.services.curso_service import add_curso_director, get_cursos_by_cue

router = APIRouter(prefix="/escuelas", tags=["Escuelas"])

TEL_RE = re.compile(r"^\d{10,15}$")


def _validate_cue_or_422(cue: str) -> str:
    cue_norm = re.sub(r"\D", "", str(cue).strip())
    if not cue_norm:
        raise HTTPException(
            status_code=422,
            detail="El CUE es obligatorio y debe contener solo números."
        )
    return cue_norm


def _only_digits(v: str | None) -> str | None:
    if v is None:
        return None
    if not isinstance(v, str):
        v = str(v)
    v = v.strip()
    if v == "":
        return None
    return re.sub(r"\D+", "", v)


def _is_valid_email(v: str | None) -> bool:
    if v is None:
        return False
    if not isinstance(v, str):
        v = str(v)
    v = v.strip()
    return ("@" in v) and ("." in v.split("@")[-1])


def _sanitize_escuela_for_public(e: Escuela) -> dict:
    """
    Prepara un dict "seguro" para serializar con EscuelaPublic sin que explote
    por datos legacy (telefono/email inválidos).
    """
    data = e.model_dump()

    tel = _only_digits(data.get("telefono"))
    if tel is None or not TEL_RE.match(tel):
        data["telefono"] = None
    else:
        data["telefono"] = tel

    mail = data.get("correo_electronico")
    if isinstance(mail, str):
        mail = mail.strip().lower()
    else:
        mail = None

    if not _is_valid_email(mail):
        data["correo_electronico"] = None
    else:
        data["correo_electronico"] = mail

    return data


# =========================================================
# ✅ NUEVO: BUSCAR ESCUELAS (nombre / CUE / localidad / provincia)
# GET /escuelas/buscar?q=...&limit=10
# =========================================================
@router.get("/buscar", response_model=list[EscuelaPublic])
def buscar_escuelas(
    session: SessionDep,
    q: str = Query(..., min_length=1, description="Texto a buscar (nombre, CUE, localidad, provincia)"),
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
):
    q_raw = (q or "").strip()
    if not q_raw:
        return []

    q_digits = re.sub(r"\D", "", q_raw)
    like_text = f"%{q_raw}%"
    like_digits = f"%{q_digits}%" if q_digits else None

    conditions = [
        Escuela.nombre.ilike(like_text),
        Escuela.localidad.ilike(like_text),
    ]

    # Si tu modelo tiene provincia, la incluimos sin romper si no existe
    if hasattr(Escuela, "provincia"):
        conditions.append(getattr(Escuela, "provincia").ilike(like_text))

    # Búsqueda por CUE: si escriben números (o parte)
    if like_digits:
        conditions.append(Escuela.CUE.ilike(like_digits))

    statement = (
        select(Escuela)
        .where(or_(*conditions))
        .order_by(Escuela.nombre)
        .limit(limit)
    )

    escuelas = session.exec(statement).all()

    salida: list[EscuelaPublic] = []
    for e in escuelas:
        salida.append(EscuelaPublic.model_validate(_sanitize_escuela_for_public(e)))
    return salida


@router.get("/escuelas/", response_model=list[EscuelaPublic])
def getAllEscuelas(
    session: SessionDep,
    offset: int = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
):
    """Obtiene la lista de todas las escuelas con paginación."""
    statement = select(Escuela).offset(offset).limit(limit)
    escuelas = session.exec(statement).all()

    salida: list[EscuelaPublic] = []
    for e in escuelas:
        data = _sanitize_escuela_for_public(e)
        salida.append(EscuelaPublic.model_validate(data))
    return salida


@router.post("/escuelas/", response_model=EscuelaPublic)
def create_escuela(escuela: EscuelaCreate, session: SessionDep):
    """Crea una nueva escuela. El CUE debe ser enviado en el cuerpo."""
    cue = _validate_cue_or_422(escuela.CUE)

    escuela_existente = session.get(Escuela, cue)
    if escuela_existente:
        raise HTTPException(status_code=400, detail="Ya existe una escuela con este CUE")

    escuela_data = escuela.model_dump()
    escuela_data["CUE"] = cue

    db_escuela = Escuela.model_validate(escuela_data)
    session.add(db_escuela)
    session.commit()
    session.refresh(db_escuela)

    return EscuelaPublic.model_validate(_sanitize_escuela_for_public(db_escuela))


@router.get("/escuelas/{cue}", response_model=EscuelaPublic)
def read_escuela(cue: str, session: SessionDep):
    """Obtiene una escuela específica por su CUE."""
    cue = _validate_cue_or_422(cue)

    db_escuela = session.get(Escuela, cue)
    if not db_escuela:
        raise HTTPException(status_code=404, detail="Escuela no encontrada")

    return EscuelaPublic.model_validate(_sanitize_escuela_for_public(db_escuela))


@router.patch("/escuelas/{cue}", response_model=EscuelaPublic)
def update_escuela(cue: str, escuela: EscuelaUpdate, session: SessionDep):
    """Actualiza los datos de una escuela de forma parcial (PATCH)."""
    cue = _validate_cue_or_422(cue)

    db_escuela = session.get(Escuela, cue)
    if not db_escuela:
        raise HTTPException(status_code=404, detail="Escuela no encontrada")

    escuela_data = escuela.model_dump(exclude_unset=True)

    # 🔒 No permitir cambiar la PK por PATCH
    escuela_data.pop("CUE", None)

    db_escuela.sqlmodel_update(escuela_data)

    session.add(db_escuela)
    session.commit()
    session.refresh(db_escuela)

    return EscuelaPublic.model_validate(_sanitize_escuela_for_public(db_escuela))


@router.delete("/escuelas/{cue}")
def delete_escuela(cue: str, session: SessionDep):
    """Elimina una escuela por su CUE."""
    cue = _validate_cue_or_422(cue)

    db_escuela = session.get(Escuela, cue)
    if not db_escuela:
        raise HTTPException(status_code=404, detail="Escuela no encontrada")

    session.delete(db_escuela)
    session.commit()
    return {"ok": True, "message": f"Escuela con CUE {cue} eliminada correctamente"}


@router.get("/escuelas/{cue}/cursos", response_model=list[CursoPublic])
def listar_cursos_escuela(cue: str, session: SessionDep):
    cue = _validate_cue_or_422(cue)
    return get_cursos_by_cue(session, cue)


@router.post("/escuelas/{cue}/cursos", response_model=CursoPublic, status_code=201)
def crear_curso_escuela(
    cue: str,
    curso: CursoCreate,
    usuario_id: Annotated[int, Query(..., ge=1, description="ID del usuario Director")],
    session: SessionDep,
):
    cue = _validate_cue_or_422(cue)

    nuevo = add_curso_director(
        db=session,
        cue=cue,
        idUsuarioDirector=usuario_id,
        curso=curso,
    )
    if not nuevo:
        raise HTTPException(
            status_code=403,
            detail="Solo un Director Activo puede crear cursos",
        )
    return nuevo


@router.get("/escuelas/{cue}/stats")
def escuela_stats(cue: str, session: SessionDep):
    """
    Devuelve métricas para el Admin:
    - cursos_total: cantidad de cursos de la escuela
    - inscripciones_total: filas totales en Inscriptos (histórico)
    - inscripciones_activas: filas con estado='Activo'
    - alumnos_total: alumnos únicos (histórico)
    - alumnos_activos: alumnos únicos con estado='Activo' (matrícula actual)
    """
    cue = _validate_cue_or_422(cue)

    db_escuela = session.get(Escuela, cue)
    if not db_escuela:
        raise HTTPException(status_code=404, detail="Escuela no encontrada")

    cursos_total = session.exec(
        select(func.count(Curso.idCurso)).where(Curso.CUE == cue)
    ).one()

    inscripciones_total = session.exec(
        select(func.count())
        .select_from(Inscriptos)
        .join(Curso, Curso.idCurso == Inscriptos.idCurso)
        .where(Curso.CUE == cue)
    ).one()

    inscripciones_activas = session.exec(
        select(func.count())
        .select_from(Inscriptos)
        .join(Curso, Curso.idCurso == Inscriptos.idCurso)
        .where(
            (Curso.CUE == cue) &
            (Inscriptos.estado == "Activo")
        )
    ).one()

    alumnos_total = session.exec(
        select(func.count(distinct(Inscriptos.idAlumno)))
        .select_from(Inscriptos)
        .join(Curso, Curso.idCurso == Inscriptos.idCurso)
        .where(Curso.CUE == cue)
    ).one()

    alumnos_activos = session.exec(
        select(func.count(distinct(Inscriptos.idAlumno)))
        .select_from(Inscriptos)
        .join(Curso, Curso.idCurso == Inscriptos.idCurso)
        .where(
            (Curso.CUE == cue) &
            (Inscriptos.estado == "Activo")
        )
    ).one()

    return {
        "CUE": cue,
        "cursos_total": int(cursos_total or 0),
        "inscripciones_total": int(inscripciones_total or 0),
        "inscripciones_activas": int(inscripciones_activas or 0),
        "alumnos_total": int(alumnos_total or 0),
        "alumnos_activos": int(alumnos_activos or 0),
    }
