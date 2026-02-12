from fastapi import HTTPException
from sqlmodel import select
from datetime import datetime
from app.dependencies import SessionDep
from app.models.curso import Curso
from app.models.curso_docente import CursoDocente
from app.schemas.curso_docente import CursoDocenteCreate
from app.schemas.rol import RolDescripcion, RolEstado
from app.services.rol_service import get_one_rol


def asignar_docente_a_curso(
    db: SessionDep,
    idCurso: int,
    director_id: int,
    payload: CursoDocenteCreate,
):
    # 1) curso existe + obtener CUE
    curso = db.get(Curso, idCurso)
    if not curso:
        raise HTTPException(status_code=404, detail="Curso no encontrado")

    cue = curso.CUE

    # 2) validar director activo en esa escuela
    rol_dir = get_one_rol(director_id, cue, db)
    if (
        not rol_dir
        or rol_dir.estado != RolEstado.Activo
        or rol_dir.descripcion != RolDescripcion.Director
    ):
        raise HTTPException(status_code=403, detail="Solo un Director Activo puede asignar docentes")

    # 3) validar que el docente pertenezca a la escuela como Docente Activo
    rol_doc = get_one_rol(payload.idUsuario, cue, db)
    if (
        not rol_doc
        or rol_doc.estado != RolEstado.Activo
        or rol_doc.descripcion != RolDescripcion.Docente
    ):
        raise HTTPException(status_code=400, detail="El usuario no es Docente Activo en esta escuela")

    # 4) upsert (si ya existe, lo actualiza)
    existente = db.get(CursoDocente, (idCurso, payload.idUsuario))
    if existente:
        existente.tipo = payload.tipo
        existente.fechaDesde = payload.fechaDesde
        existente.fechaHasta = payload.fechaHasta
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
    stmt = select(CursoDocente).where(CursoDocente.idCurso == idCurso)
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

