from __future__ import annotations

from typing import Annotated
from datetime import date
import logging

from fastapi import HTTPException, Query
from sqlalchemy import and_, or_
from sqlmodel import select
from sqlalchemy import func

from app.dependencies import SessionDep
from app.models.curso import Curso
from app.models.curso_docente import CursoDocente
from app.models.inscriptos import Inscriptos
from app.models.escuela import Escuela
from app.schemas.curso import CursoCreate, CursoUpdate, TurnoCurso
from app.schemas.rol import RolDescripcion, RolEstado
from app.schemas.cursos_admin import (
    CopiarEstructuraCursosIn,
    CopiarEstructuraCursosOut,
    CursoMiniOut,
)
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

def get_cursos_by_cue(db: SessionDep, cue: str, cicloLectivo: str | None = None):
    stmt = select(Curso).where(Curso.CUE == cue)
    if cicloLectivo:
        stmt = stmt.where(Curso.cicloLectivo == cicloLectivo)
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

def copiar_estructura_cursos(db: SessionDep, payload: CopiarEstructuraCursosIn) -> CopiarEstructuraCursosOut:
    cue = str(payload.cue).strip()
    ciclo_origen = str(payload.ciclo_origen).strip()
    ciclo_destino = str(payload.ciclo_destino).strip()

    if ciclo_origen == ciclo_destino:
        raise HTTPException(status_code=400, detail="El ciclo destino debe ser distinto al ciclo origen")

    # 1) validar director activo
    rol_dir = get_one_rol(payload.director_id, cue, db)
    if (
        not rol_dir
        or rol_dir.estado != RolEstado.Activo
        or rol_dir.descripcion != RolDescripcion.Director
    ):
        raise HTTPException(status_code=403, detail="Solo un Director Activo puede copiar estructura de cursos")
    
    # 1.5) validar que el ciclo destino NO exista aún en esa escuela (modo estricto)
    existe_destino = db.exec(
        select(Curso.idCurso).where(
            and_(
                Curso.CUE == cue,
                Curso.cicloLectivo == ciclo_destino,
            )
        ).limit(1)
    ).first()

    if existe_destino:
        raise HTTPException(
            status_code=409,
            detail=f"Ya existen cursos para el ciclo {ciclo_destino} en la escuela {cue}. No se puede copiar estructura.",
        )

    # 2) traer cursos origen
    cursos_origen = db.exec(
        select(Curso).where(
            and_(
                Curso.CUE == cue,
                Curso.cicloLectivo == ciclo_origen,
            )
        ).order_by(Curso.nombre, Curso.division)
    ).all()

    if not cursos_origen:
        raise HTTPException(status_code=404, detail="No hay cursos en el ciclo origen para esa escuela")

    out = CopiarEstructuraCursosOut(
        cue=cue,
        ciclo_origen=ciclo_origen,
        ciclo_destino=ciclo_destino,
        cursos_creados=[],
        cursos_existentes=[],
        docentes_copiados=0,
        docentes_omitidos_por_existir=0,
    )

    # helper para mapear salida
    def _mini(c: Curso) -> CursoMiniOut:
        return CursoMiniOut(
            idCurso=int(c.idCurso),
            nombre=c.nombre,
            division=c.division,
            turno=c.turno,
            cicloLectivo=c.cicloLectivo,
        )

    # 3) por cada curso origen → crear si no existe el gemelo en destino
    mapa_origen_a_destino: dict[int, int] = {}  # idCursoOrigen -> idCursoDestino

    for c in cursos_origen:
        turno_enum = normalize_turno(c.turno)

        existente = db.exec(
            select(Curso).where(
                and_(
                    Curso.CUE == cue,
                    Curso.cicloLectivo == ciclo_destino,
                    Curso.nombre == c.nombre,
                    Curso.division == c.division,
                    Curso.turno == turno_enum,
                )
            )
        ).first()

        if existente:
            out.cursos_existentes.append(_mini(existente))
            mapa_origen_a_destino[int(c.idCurso)] = int(existente.idCurso)
            continue

        nuevo = Curso(
            CUE=cue,
            nombre=c.nombre,
            division=c.division,
            turno=turno_enum,
            cicloLectivo=ciclo_destino,
        )
        db.add(nuevo)
        db.commit()
        db.refresh(nuevo)

        out.cursos_creados.append(_mini(nuevo))
        mapa_origen_a_destino[int(c.idCurso)] = int(nuevo.idCurso)

    # 4) copiar docentes (opcional)
    if payload.copiar_docentes:
        for c in cursos_origen:
            id_origen = int(c.idCurso)
            id_destino = mapa_origen_a_destino[id_origen]

            docentes_origen = db.exec(
                select(CursoDocente).where(
                    CursoDocente.idCurso == id_origen,
                    CursoDocente.estado == "Activo",
                )
            ).all()

            for d in docentes_origen:
                # no pisar existentes en destino
                existe_dest = db.get(CursoDocente, (id_destino, d.idUsuario))
                if existe_dest:
                    out.docentes_omitidos_por_existir += 1
                    continue

                nuevo_cd = CursoDocente(
                    idCurso=id_destino,
                    idUsuario=d.idUsuario,
                    tipo=d.tipo,
                    # nuevo ciclo: sin fechas por defecto
                    fechaDesde=None,
                    fechaHasta=None,
                    estado="Activo",
                )
                db.add(nuevo_cd)
                out.docentes_copiados += 1

        db.commit()

    return out

def bulk_delete_cursos_director(
    db,
    cue: str,
    director_id: int,
    ids: list[int],
    solo_vacios: bool = True,
):
    # 1) validar director activo
    rol_dir = get_one_rol(director_id, cue, db)
    if (
        not rol_dir
        or rol_dir.estado != RolEstado.Activo
        or rol_dir.descripcion != RolDescripcion.Director
    ):
        raise HTTPException(status_code=403, detail="Solo un Director Activo puede eliminar cursos")

    eliminados: list[int] = []
    omitidos: list[dict] = []

    if not ids:
        return {"ok": True, "eliminados": [], "omitidos": []}

    # 2) traer cursos y validar cue
    cursos = db.exec(select(Curso).where(Curso.idCurso.in_(ids))).all()
    cursos_map = {c.idCurso: c for c in cursos}

    for idc in ids:
        curso = cursos_map.get(idc)
        if not curso:
            omitidos.append({"idCurso": idc, "motivo": "No existe"})
            continue

        if curso.CUE != cue:
            omitidos.append({"idCurso": idc, "motivo": "No pertenece a esta escuela"})
            continue

        if solo_vacios:
            # alumnos?
            cant_insc = db.exec(
                select(func.count()).select_from(Inscriptos).where(Inscriptos.idCurso == idc)
            ).one()
            if cant_insc and int(cant_insc) > 0:
                omitidos.append({"idCurso": idc, "motivo": "Tiene alumnos asignados"})
                continue

            # docentes asignados (aunque estén inactivos, igual lo consideramos “tiene relación”)
            cant_doc = db.exec(
                select(func.count()).select_from(CursoDocente).where(CursoDocente.idCurso == idc)
            ).one()
            if cant_doc and int(cant_doc) > 0:
                omitidos.append({"idCurso": idc, "motivo": "Tiene docentes asignados"})
                continue

        db.delete(curso)
        eliminados.append(idc)

    db.commit()
    return {"ok": True, "eliminados": eliminados, "omitidos": omitidos}

