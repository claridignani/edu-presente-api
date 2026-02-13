from __future__ import annotations

from datetime import date
from fastapi import HTTPException
from sqlmodel import select

from app.dependencies import SessionDep
from app.models.curso import Curso
from app.models.inscriptos import Inscriptos
from app.schemas.inscriptos import EstadoInscripcion
from app.schemas.inscriptos_admin import CerrarCicloIn, CerrarCicloOut
from app.schemas.rol import RolDescripcion, RolEstado
from app.services.rol_service import get_one_rol


def cerrar_ciclo_por_escuela(db: SessionDep, payload: CerrarCicloIn) -> CerrarCicloOut:
    cue = str(payload.cue).strip()
    ciclo = str(payload.ciclo_lectivo).strip()
    hoy = payload.fecha or date.today()

    # validar director activo
    rol_dir = get_one_rol(payload.director_id, cue, db)
    if (
        not rol_dir
        or rol_dir.estado != RolEstado.Activo
        or rol_dir.descripcion != RolDescripcion.Director
    ):
        raise HTTPException(status_code=403, detail="Solo un Director Activo puede cerrar el ciclo")

    # buscar inscripciones activas del ciclo+escuela
    stmt = (
        select(Inscriptos)
        .join(Curso, Curso.idCurso == Inscriptos.idCurso)
        .where(
            Curso.CUE == cue,
            Curso.cicloLectivo == ciclo,
            Inscriptos.activo == True,  # noqa: E712
        )
    )
    inscs = db.exec(stmt).all()

    for i in inscs:
        i.activo = False
        i.fechaBaja = hoy
        i.estado = EstadoInscripcion.CierreCiclo
        db.add(i)

    db.commit()

    return CerrarCicloOut(cue=cue, ciclo_lectivo=ciclo, cerradas=len(inscs))
