# app/services/parentesco_service.py
from fastapi import HTTPException
from sqlmodel import select

from app.dependencies import SessionDep
from app.models.parentesco import Parentesco
from app.models.alumno import Alumno
from app.models.responsable import Responsable
from app.schemas.parentesco import (
    ParentescoCreate,
    ParentescoPublic,
    ResponsableConParentescoPublic,
)


def upsert_parentesco(
    db: SessionDep,
    idAlumno: int,
    idResponsable: int,
    parentesco: str,
) -> ParentescoPublic:
    """
    UPSERT reutilizable:
    - valida Alumno y Responsable
    - si existe vínculo (PK compuesta idAlumno,idResponsable) => actualiza parentesco
    - si no existe => crea
    """
    # Validar alumno
    alumno = db.get(Alumno, idAlumno)
    if not alumno:
        raise HTTPException(status_code=404, detail="Alumno no encontrado")

    # Validar responsable
    resp = db.get(Responsable, idResponsable)
    if not resp:
        raise HTTPException(status_code=404, detail="Responsable no encontrado")

    # UPSERT
    rel = db.get(Parentesco, (idAlumno, idResponsable))
    if rel:
        rel.parentesco = parentesco
        db.add(rel)
        db.commit()
        db.refresh(rel)
        return rel

    rel = Parentesco(
        idAlumno=idAlumno,
        idResponsable=idResponsable,
        parentesco=parentesco,
    )
    db.add(rel)
    db.commit()
    db.refresh(rel)
    return rel


def add_parentesco(db: SessionDep, rel_in: ParentescoCreate) -> ParentescoPublic:
    """
    Mantiene compatibilidad con tu router actual:
    POST /parentescos
    """
    return upsert_parentesco(
        db=db,
        idAlumno=rel_in.idAlumno,
        idResponsable=rel_in.idResponsable,
        parentesco=rel_in.parentesco,
    )


def get_responsables_by_alumno(db: SessionDep, idAlumno: int) -> list[ResponsableConParentescoPublic]:
    stmt = (
        select(Responsable, Parentesco.parentesco)
        .join(Parentesco, Parentesco.idResponsable == Responsable.idResponsable)
        .where(Parentesco.idAlumno == idAlumno)
    )

    rows = db.exec(stmt).all()

    return [
        ResponsableConParentescoPublic(
            idResponsable=r.idResponsable,
            nombre=r.nombre,
            apellido=r.apellido,
            dni=r.dni,
            fecha_nacimiento=r.fecha_nacimiento,
            email=r.email,
            nro_celular=r.nro_celular,
            direccion=r.direccion,
            parentesco=parentesco,
        )
        for r, parentesco in rows
    ]