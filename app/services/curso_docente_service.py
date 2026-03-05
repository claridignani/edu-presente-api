from fastapi import HTTPException
from sqlmodel import select
from datetime import datetime
from app.dependencies import SessionDep
from app.models.curso import Curso
from app.models.curso_docente import CursoDocente
from app.schemas.curso_docente import CursoDocenteCreate
from app.schemas.rol import RolDescripcion, RolEstado
from app.models.usuario import Usuario
from app.schemas.curso_docente import CursoDocenteDetalle
from app.services.rol_service import get_one_rol
from app.core.encryption import decrypt
from app.schemas.curso import TurnoCurso  # ← agregar este import


# ── Helper de turno (mismo que en invitacion_docente_service) ──────────────

_FRANJAS: dict[str, set[str]] = {
    TurnoCurso.Manana:      {"Manana"},
    TurnoCurso.Tarde:       {"Tarde"},
    TurnoCurso.DobleTurno:  {"Manana", "Tarde"},
}

def _franjas(turno) -> set[str]:
    return _FRANJAS.get(turno, {str(turno)})

_TURNO_UI = {
    TurnoCurso.Manana:     "Mañana",
    TurnoCurso.Tarde:      "Tarde",
    TurnoCurso.DobleTurno: "Doble turno",
}

def _hay_conflicto_titular(
    db: SessionDep,
    idUsuario: int,
    turno_nuevo,
    excluir_curso: int | None = None,
) -> "Curso | None":
    franjas_nuevas = _franjas(turno_nuevo)

    stmt = (
        select(CursoDocente, Curso)
        .join(Curso, Curso.idCurso == CursoDocente.idCurso)
        .where(
            CursoDocente.idUsuario == idUsuario,
            CursoDocente.tipo == "Titular",
            CursoDocente.estado == "Activo",
        )
    )
    if excluir_curso:
        stmt = stmt.where(CursoDocente.idCurso != excluir_curso)

    for _cd, curso in db.exec(stmt).all():
        if _franjas(curso.turno) & franjas_nuevas:
            return curso

    return None


# ── Función principal ──────────────────────────────────────────────────────

def asignar_docente_a_curso(
    db: SessionDep,
    idCurso: int,
    director_id: int,
    payload: CursoDocenteCreate,
):
    # 1) curso existe + CUE
    curso = db.get(Curso, idCurso)
    if not curso:
        raise HTTPException(status_code=404, detail="Curso no encontrado")
    cue = curso.CUE

    # 2) director activo
    rol_dir = get_one_rol(director_id, cue, db)
    if (
        not rol_dir
        or rol_dir.estado != RolEstado.Activo
        or rol_dir.descripcion != RolDescripcion.Director
    ):
        raise HTTPException(status_code=403, detail="Solo un Director Activo puede asignar docentes")

    # 3) docente activo en la escuela
    rol_doc = get_one_rol(payload.idUsuario, cue, db)
    if (
        not rol_doc
        or rol_doc.estado != RolEstado.Activo
        or rol_doc.descripcion != RolDescripcion.Docente
    ):
        raise HTTPException(status_code=400, detail="El usuario no es Docente Activo en esta escuela")

    # 4) validación de turno para Titular
    if payload.tipo == "Titular":
        conflicto = _hay_conflicto_titular(
            db,
            payload.idUsuario,
            curso.turno,
            excluir_curso=idCurso,   # si es un upsert del mismo curso, no se autoexcluye
        )
        if conflicto:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"El/La docente ya es Titular en turno "
                    f"{_TURNO_UI.get(conflicto.turno, str(conflicto.turno))} "
                    f"({conflicto.nombre} {conflicto.division}) "
                    f"y no puede asumir otro cargo Titular en turno "
                    f"{_TURNO_UI.get(curso.turno, str(curso.turno))}. "
                    f"Un/a docente titular ocupa el turno completo."
                ),
            )

    # 5) upsert
    existente = db.get(CursoDocente, (idCurso, payload.idUsuario))
    if existente:
        existente.tipo = payload.tipo
        existente.fechaDesde = payload.fechaDesde
        existente.fechaHasta = None
        existente.estado = "Activo"
        db.add(existente)
        db.commit()
        db.refresh(existente)
        return existente

    nuevo = CursoDocente(
        idCurso=idCurso,
        idUsuario=payload.idUsuario,
        tipo=payload.tipo,
        fechaDesde=payload.fechaDesde,
        fechaHasta=payload.fechaHasta,
    )
    db.add(nuevo)
    db.commit()
    db.refresh(nuevo)
    return nuevo


def listar_docentes_de_curso(db: SessionDep, idCurso: int):
    stmt = select(CursoDocente).where(
        CursoDocente.idCurso == idCurso,
        CursoDocente.estado == "Activo",  
    )
    return db.exec(stmt).all()

def inactivar_docente_de_curso(db: SessionDep, idCurso: int, idUsuario: int):
    asignacion = db.get(CursoDocente, (idCurso, idUsuario))
    if not asignacion:
        raise HTTPException(status_code=404, detail="La asignación no existe")
    
    asignacion.estado = "Inactivo"
    asignacion.fechaHasta = datetime.now().date() 
    
    db.add(asignacion)
    db.commit()
    db.refresh(asignacion)
    return {"ok": True, "message": "Asignación inactivada correctamente"}

# Modificamos listar_docentes_de_curso para que solo traiga Activos por defecto
def listar_docentes_activos_de_curso(db: SessionDep, idCurso: int):
    stmt = select(CursoDocente).where(
        CursoDocente.idCurso == idCurso,
        CursoDocente.estado == "Activo"
    )
    return db.exec(stmt).all()

def listar_docentes_detalle_de_curso(db, idCurso: int):
    stmt = (
        select(
            CursoDocente.idCurso,
            CursoDocente.idUsuario,
            Usuario.nombre,
            Usuario.apellido,
            Usuario.dni,
            CursoDocente.tipo,
            CursoDocente.fechaDesde,
            CursoDocente.fechaHasta,
            CursoDocente.estado,
        )
        .join(Usuario, Usuario.idUsuario == CursoDocente.idUsuario)
        .where(CursoDocente.idCurso == idCurso)
    )

    rows = db.exec(stmt).all()

    return [
        CursoDocenteDetalle(
            idCurso=r[0],
            idUsuario=r[1],
            nombre=r[2],
            apellido=r[3],
            dni=decrypt(r[4]) if r[4] else r[4],   # ← FIX
            tipo=r[5],
            fechaDesde=r[6],
            fechaHasta=r[7],
            estado=r[8],
        )
        for r in rows
    ]