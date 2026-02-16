from __future__ import annotations
from typing import Annotated
from datetime import datetime

from fastapi import Query, HTTPException
from typing import Optional
from sqlmodel import select
from sqlalchemy import func, and_

from app.dependencies import SessionDep
from app.models.alumno import Alumno
from app.models.curso import Curso
from app.models.inscriptos import Inscriptos
from app.schemas.alumno import AlumnoCreate, AlumnoUpdate
from app.schemas.alumno import AlumnoDetallePublic
from app.models.parentesco import Parentesco
from app.models.responsable import Responsable
from app.schemas.parentesco import ResponsableConParentescoPublic
from app.schemas.alumno_detalle import AlumnoEscuelaDetallePublic, ResponsableMiniPublic
from app.services.curso_service import get_one_curso

# HELPERS

def _clean_str(v: str | None) -> str | None:
    if v is None:
        return None
    return str(v).strip()

def _require_not_empty(value: str | None, field_name: str):
    """
    Si el campo viene (no es None), no puede ser vacío.
    """
    if value is not None and not str(value).strip():
        raise HTTPException(status_code=400, detail=f"El campo '{field_name}' no puede estar vacío")

def _exists_otro_alumno_con_dni(db: SessionDep, dni: str, exclude_id: int) -> bool:
    stmt = select(Alumno).where(Alumno.dni == dni, Alumno.idAlumno != exclude_id)
    return db.exec(stmt).first() is not None


# GET ALL

def get_all_alumnos(db: SessionDep, offset: int, limit: Annotated[int, Query(le=100)]):
    alumnos = db.exec(select(Alumno).offset(offset).limit(limit)).all()
    return alumnos


# GET BY CURSO (INSCRIPTOS)

def get_alumnos_detalle_by_curso(idCurso: int, db: SessionDep):
    stmt = (
        select(
            Alumno,
            Responsable,
            Parentesco.parentesco
        )
        .join(Inscriptos, Inscriptos.idAlumno == Alumno.idAlumno)
        .outerjoin(Parentesco, Parentesco.idAlumno == Alumno.idAlumno)
        .outerjoin(Responsable, Responsable.idResponsable == Parentesco.idResponsable)
        .where(Inscriptos.idCurso == idCurso)
    )

    rows = db.exec(stmt).all()

    alumnos_map = {}

    for alumno, responsable, parentesco in rows:
        if alumno.idAlumno not in alumnos_map:
            alumnos_map[alumno.idAlumno] = {
                "alumno": alumno,
                "responsable": None
            }

        # Tomamos solo el primero (responsable principal)
        if responsable and not alumnos_map[alumno.idAlumno]["responsable"]:
            alumnos_map[alumno.idAlumno]["responsable"] = ResponsableConParentescoPublic(
                idResponsable=responsable.idResponsable,
                nombre=responsable.nombre,
                apellido=responsable.apellido,
                dni=responsable.dni,
                fecha_nacimiento=responsable.fecha_nacimiento,
                email=responsable.email,
                nro_celular=responsable.nro_celular,
                direccion=responsable.direccion,
                parentesco=parentesco,
            )

    return [
        AlumnoDetallePublic(
            idAlumno=a.idAlumno,
            nombre=a.nombre,
            apellido=a.apellido,
            dni=a.dni,
            estado=a.estado,
            responsable=data["responsable"],
        )
        for data in alumnos_map.values()
        for a in [data["alumno"]]
    ]

def get_ciclo_actual() -> str:
    return str(datetime.now().year)


def get_alumnos_detalle_por_escuela(
    db,
    cue: str,
    ciclo_lectivo: Optional[str] = None,
) -> list[AlumnoEscuelaDetallePublic]:

    if not ciclo_lectivo:
        ciclo_lectivo = get_ciclo_actual()

    # subquery → 1 responsable por alumno
    sub_resp = (
        select(
            Parentesco.idAlumno.label("idAlumno"),
            func.min(Parentesco.idResponsable).label("idResponsable"),
        )
        .group_by(Parentesco.idAlumno)
        .subquery()
    )

    stmt = (
        select(
            Alumno,
            Curso,
            Responsable,
            Parentesco.parentesco,
        )
        .join(Inscriptos, Inscriptos.idAlumno == Alumno.idAlumno)
        .join(Curso, Curso.idCurso == Inscriptos.idCurso)
        .outerjoin(sub_resp, sub_resp.c.idAlumno == Alumno.idAlumno)
        .outerjoin(Responsable, Responsable.idResponsable == sub_resp.c.idResponsable)
        .outerjoin(
            Parentesco,
            (Parentesco.idAlumno == Alumno.idAlumno)
            & (Parentesco.idResponsable == sub_resp.c.idResponsable),
        )
        .where(Curso.CUE == cue)
        .where(Curso.cicloLectivo == ciclo_lectivo)
    )

    rows = db.exec(stmt).all()

    out = []

    for alumno, curso, resp, parentesco in rows:
        responsable_public = None

        if resp:
            responsable_public = ResponsableMiniPublic(
                idResponsable=resp.idResponsable,
                nombre=resp.nombre,
                apellido=resp.apellido,
                parentesco=parentesco,
                nro_celular=getattr(resp, "nro_celular", None),
            )

        out.append(
            AlumnoEscuelaDetallePublic(
                idAlumno=alumno.idAlumno,
                nombre=alumno.nombre,
                apellido=alumno.apellido,
                dni=alumno.dni,
                estado=getattr(alumno, "estado", "Activo") or "Activo",
                idCurso=curso.idCurso,
                nombreCurso=f"{curso.nombre} {curso.division}".strip(),
                responsable=responsable_public,
            )
        )

    return out

def get_alumno_detalle_por_id(
    db: SessionDep,
    idAlumno: int,
) -> AlumnoEscuelaDetallePublic:
    """
    Devuelve el detalle completo de 1 alumno (para el dialog de alertas):
    - nombre, apellido, dni, estado
    - curso actual (uno)
    - responsable mini (uno)
    """

    # subquery → 1 responsable por alumno (mismo criterio que por escuela)
    sub_resp = (
        select(
            Parentesco.idAlumno.label("idAlumno"),
            func.min(Parentesco.idResponsable).label("idResponsable"),
        )
        .where(Parentesco.idAlumno == idAlumno)
        .group_by(Parentesco.idAlumno)
        .subquery()
    )

    # Traemos un curso vinculado por Inscriptos (si hay múltiples, tomamos 1)
    stmt = (
        select(
            Alumno,
            Curso,
            Responsable,
            Parentesco.parentesco,
        )
        .join(Inscriptos, Inscriptos.idAlumno == Alumno.idAlumno)
        .join(Curso, Curso.idCurso == Inscriptos.idCurso)
        .outerjoin(sub_resp, sub_resp.c.idAlumno == Alumno.idAlumno)
        .outerjoin(Responsable, Responsable.idResponsable == sub_resp.c.idResponsable)
        .outerjoin(
            Parentesco,
            and_(
                Parentesco.idAlumno == Alumno.idAlumno,
                Parentesco.idResponsable == sub_resp.c.idResponsable,
            ),
        )
        .where(Alumno.idAlumno == idAlumno)
        .limit(1)
    )

    row = db.exec(stmt).first()
    if not row:
        raise HTTPException(status_code=404, detail="Alumno no encontrado o no inscripto a un curso")

    alumno, curso, resp, parentesco = row

    responsable_public = None
    if resp:
        responsable_public = ResponsableMiniPublic(
            idResponsable=resp.idResponsable,
            nombre=resp.nombre,
            apellido=resp.apellido,
            parentesco=parentesco,
            nro_celular=getattr(resp, "nro_celular", None),
        )

    return AlumnoEscuelaDetallePublic(
        idAlumno=alumno.idAlumno,
        nombre=alumno.nombre,
        apellido=alumno.apellido,
        dni=alumno.dni,
        estado=getattr(alumno, "estado", "Activo") or "Activo",
        idCurso=curso.idCurso,
        nombreCurso=f"{curso.nombre} {curso.division}".strip(),
        responsable=responsable_public,
    )


def get_alumnos_by_curso(idCurso: int, db: SessionDep):
    """
    Devuelve los alumnos INSCRIPTOS a un curso (matrícula),
    sin depender de que exista asistencia.
    """
    curso = get_one_curso(idCurso=idCurso, db=db)
    if curso is None:
        raise Exception("El curso ingresado no existe")

    stmt = (
        select(Alumno)
        .join(Inscriptos, Inscriptos.idAlumno == Alumno.idAlumno)
        .where(Inscriptos.idCurso == idCurso)
    )
    return db.exec(stmt).all()


# HELPERS

def get_alumno_by_dni(db: SessionDep, dni: str):
    stmt = select(Alumno).where(Alumno.dni == dni)
    return db.exec(stmt).first()

def get_one_alumno(idAlumno: int, db: SessionDep):
    return db.get(Alumno, idAlumno)

# CREATE

def add_alumno(db: SessionDep, alumno_in: AlumnoCreate):
    dni = _clean_str(alumno_in.dni) or ""

    if not dni:
        raise HTTPException(status_code=400, detail="El DNI del alumno es obligatorio")

    existente = get_alumno_by_dni(db, dni)
    if existente:
        raise HTTPException(status_code=400, detail="Ya existe un alumno con ese DNI")

    # Creamos Alumno ignorando idCurso (la matrícula va por Inscriptos)
    data = alumno_in.model_dump(exclude={"idCurso"})
    data["dni"] = dni  # aseguramos limpio

    # (si querés ser estricto con obligatorios)
    _require_not_empty(_clean_str(data.get("nombre")), "nombre")
    _require_not_empty(_clean_str(data.get("apellido")), "apellido")
    _require_not_empty(_clean_str(data.get("direccion")), "direccion")

    db_alumno = Alumno.model_validate(data)

    db.add(db_alumno)
    db.commit()
    db.refresh(db_alumno)

    # Inscripción automática si viene idCurso
    if getattr(alumno_in, "idCurso", None) and alumno_in.idCurso > 0:
        curso = get_one_curso(idCurso=alumno_in.idCurso, db=db)
        if curso is None:
            raise HTTPException(status_code=404, detail="El curso ingresado no existe")

        ya = db.get(Inscriptos, (alumno_in.idCurso, db_alumno.idAlumno))
        if not ya:
            insc = Inscriptos(idCurso=alumno_in.idCurso, idAlumno=db_alumno.idAlumno)
            db.add(insc)
            db.commit()

    db.refresh(db_alumno)
    return db_alumno


# UPDATE (con validación DNI único)

def update_alumno(alumno_existente: Alumno, alumno_nuevo: AlumnoUpdate, db: SessionDep):
    data = alumno_nuevo.model_dump(exclude_unset=True)

    # ==========================
    # VALIDAR DNI DUPLICADO
    # ==========================
    if "dni" in data:
        dni_nuevo = data["dni"].strip()
        if not dni_nuevo:
            raise HTTPException(status_code=400, detail="El DNI es obligatorio")

        stmt = select(Alumno).where(
            Alumno.dni == dni_nuevo,
            Alumno.idAlumno != alumno_existente.idAlumno
        )
        existente = db.exec(stmt).first()
        if existente:
            raise HTTPException(
                status_code=400,
                detail="Ya existe otro alumno con ese DNI"
            )

        data["dni"] = dni_nuevo

    # ==========================
    # VALIDAR CAMPOS OBLIGATORIOS
    # ==========================
    campos_obligatorios = [
        "nombre",
        "apellido",
        "fecha_nacimiento",
        "fecha_ingreso",
        "direccion",
        "estado",
    ]

    for campo in campos_obligatorios:
        if campo in data:
            valor = data[campo]
            if valor is None or (isinstance(valor, str) and not valor.strip()):
                raise HTTPException(
                    status_code=400,
                    detail=f"El campo '{campo}' es obligatorio"
                )

    alumno_existente.sqlmodel_update(data)
    db.add(alumno_existente)
    db.commit()
    db.refresh(alumno_existente)
    return alumno_existente

# DELETE

def delete_alumno(db: SessionDep, alumno: Alumno):
    db.delete(alumno)
    db.commit()
