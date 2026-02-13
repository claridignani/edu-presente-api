from fastapi import HTTPException
from sqlmodel import select

from app.dependencies import SessionDep
from app.models.parentesco import Parentesco
from app.models.alumno import Alumno
from app.models.responsable import Responsable
from app.schemas.parentesco import ParentescoCreate, ParentescoPublic, ResponsableConParentescoPublic


def add_parentesco(db: SessionDep, rel_in: ParentescoCreate) -> ParentescoPublic:
    # Validar alumno
    alumno = db.get(Alumno, rel_in.idAlumno)
    if not alumno:
        raise HTTPException(status_code=404, detail="Alumno no encontrado")

    # Validar responsable
    resp = db.get(Responsable, rel_in.idResponsable)
    if not resp:
        raise HTTPException(status_code=404, detail="Responsable no encontrado")

    # ✅ UPSERT: si ya existe el vínculo, actualizamos parentesco (no error)
    ya = db.get(Parentesco, (rel_in.idAlumno, rel_in.idResponsable))
    if ya:
        ya.parentesco = rel_in.parentesco
        db.add(ya)
        db.commit()
        db.refresh(ya)
        return ya

    # Crear vínculo nuevo
    rel = Parentesco.model_validate(rel_in.model_dump())
    db.add(rel)
    db.commit()
    db.refresh(rel)
    return rel


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
            fecha_nacimiento=r.fecha_nacimiento,  # ✅ ahora lo devolvemos
            email=r.email,
            nro_celular=r.nro_celular,
            direccion=r.direccion,
            parentesco=parentesco,
        )
        for r, parentesco in rows
    ]
