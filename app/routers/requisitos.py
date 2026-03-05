# app/routers/requisitos.py

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select
from sqlalchemy import func

from app.db.database import engine
from app.models.requisito import RequisitoCurso, RequisitoAlumno
from app.models.inscriptos import Inscriptos  # ✅ este es el link_model que ya usás
from app.models.alumno import Alumno

from app.schemas.requisito import (
    RequisitoCursoCreate,
    RequisitoCursoUpdate,
    RequisitoCursoOut,
    RequisitoAlumnoUpdate,
    RequisitoAlumnoOut,
    AlumnoRequisitoRow,
)

router = APIRouter(prefix="/requisitos", tags=["Requisitos"])


# ────────────────────────────────────────────────────────────────
# DB session dependency (SQLModel)
# ────────────────────────────────────────────────────────────────
def get_db():
    with Session(engine) as session:
        yield session


# ══════════════════════════════════════════════════════════════════
# REQUISITOS DEL CURSO
# ══════════════════════════════════════════════════════════════════

@router.get("/curso/{idCurso}", response_model=List[RequisitoCursoOut])
def listar_requisitos_curso(idCurso: int, db: Session = Depends(get_db)):
    requisitos = db.exec(
        select(RequisitoCurso)
        .where(RequisitoCurso.idCurso == idCurso)
        .order_by(RequisitoCurso.creado_en)
    ).all()

    # total alumnos inscriptos al curso
    total = db.exec(
        select(func.count())
        .select_from(Inscriptos)
        .where(Inscriptos.idCurso == idCurso)
    ).one() or 0

    result: List[RequisitoCursoOut] = []
    for req in requisitos:
        cumplen = db.exec(
            select(func.count())
            .select_from(RequisitoAlumno)
            .where(
                RequisitoAlumno.idRequisito == req.idRequisito,
                RequisitoAlumno.cumplido == True,  # noqa: E712
            )
        ).one() or 0

        out = RequisitoCursoOut.model_validate(req)
        out.total_alumnos = int(total)
        out.alumnos_cumplen = int(cumplen)
        result.append(out)

    return result


@router.post("/curso/{idCurso}", response_model=RequisitoCursoOut, status_code=status.HTTP_201_CREATED)
def crear_requisito(idCurso: int, body: RequisitoCursoCreate, db: Session = Depends(get_db)):
    req = RequisitoCurso(idCurso=idCurso, **body.model_dump())
    db.add(req)
    db.commit()
    db.refresh(req)

    alumnos_ids = db.exec(
        select(Inscriptos.idAlumno).where(Inscriptos.idCurso == idCurso)
    ).all()

    # crear estados (si no existen)
    for idAlumno in alumnos_ids:
        existe = db.exec(
            select(RequisitoAlumno).where(
                RequisitoAlumno.idRequisito == req.idRequisito,
                RequisitoAlumno.idAlumno == idAlumno,
            )
        ).first()
        if not existe:
            db.add(RequisitoAlumno(idRequisito=req.idRequisito, idAlumno=idAlumno, cumplido=False))

    db.commit()

    out = RequisitoCursoOut.model_validate(req)
    out.total_alumnos = len(alumnos_ids)
    out.alumnos_cumplen = 0
    return out


@router.put("/curso/item/{idRequisito}", response_model=RequisitoCursoOut)
def actualizar_requisito(idRequisito: int, body: RequisitoCursoUpdate, db: Session = Depends(get_db)):
    req = db.exec(
        select(RequisitoCurso).where(RequisitoCurso.idRequisito == idRequisito)
    ).first()
    if not req:
        raise HTTPException(status_code=404, detail="Requisito no encontrado")

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(req, field, value)

    db.add(req)
    db.commit()
    db.refresh(req)
    return RequisitoCursoOut.model_validate(req)


@router.delete("/curso/item/{idRequisito}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_requisito(idRequisito: int, db: Session = Depends(get_db)):
    req = db.exec(
        select(RequisitoCurso).where(RequisitoCurso.idRequisito == idRequisito)
    ).first()
    if not req:
        raise HTTPException(status_code=404, detail="Requisito no encontrado")

    db.delete(req)
    db.commit()
    return None


# ══════════════════════════════════════════════════════════════════
# ESTADO POR ALUMNO
# ══════════════════════════════════════════════════════════════════

@router.get("/alumno/{idAlumno}", response_model=List[RequisitoAlumnoOut])
def listar_requisitos_alumno(idAlumno: int, db: Session = Depends(get_db)):
    cursos_ids = db.exec(
        select(Inscriptos.idCurso).where(Inscriptos.idAlumno == idAlumno)
    ).all()

    if not cursos_ids:
        return []

    requisitos = db.exec(
        select(RequisitoCurso)
        .where(RequisitoCurso.idCurso.in_(cursos_ids))
        .order_by(RequisitoCurso.idCurso, RequisitoCurso.creado_en)
    ).all()

    result: List[RequisitoAlumnoOut] = []
    for req in requisitos:
        estado = db.exec(
            select(RequisitoAlumno).where(
                RequisitoAlumno.idRequisito == req.idRequisito,
                RequisitoAlumno.idAlumno == idAlumno,
            )
        ).first()

        if not estado:
            estado = RequisitoAlumno(idRequisito=req.idRequisito, idAlumno=idAlumno, cumplido=False)
            db.add(estado)
            db.commit()
            db.refresh(estado)

        result.append(
            RequisitoAlumnoOut(
                idRequisito=req.idRequisito,
                idAlumno=idAlumno,
                nombre=req.nombre,
                tipo=req.tipo,
                obligatorio=req.obligatorio,
                descripcion=req.descripcion,
                cumplido=estado.cumplido,
                fecha_cumplimiento=estado.fecha_cumplimiento,
                observacion=estado.observacion,
            )
        )

    return result


@router.put("/alumno/{idAlumno}/{idRequisito}", response_model=RequisitoAlumnoOut)
def actualizar_estado_alumno(
    idAlumno: int,
    idRequisito: int,
    body: RequisitoAlumnoUpdate,
    db: Session = Depends(get_db),
):
    req = db.exec(
        select(RequisitoCurso).where(RequisitoCurso.idRequisito == idRequisito)
    ).first()
    if not req:
        raise HTTPException(status_code=404, detail="Requisito no encontrado")

    estado = db.exec(
        select(RequisitoAlumno).where(
            RequisitoAlumno.idRequisito == idRequisito,
            RequisitoAlumno.idAlumno == idAlumno,
        )
    ).first()

    if not estado:
        estado = RequisitoAlumno(idRequisito=idRequisito, idAlumno=idAlumno, cumplido=False)
        db.add(estado)

    estado.cumplido = body.cumplido
    estado.observacion = body.observacion
    estado.fecha_cumplimiento = datetime.now() if body.cumplido else None

    db.add(estado)
    db.commit()
    db.refresh(estado)

    return RequisitoAlumnoOut(
        idRequisito=req.idRequisito,
        idAlumno=idAlumno,
        nombre=req.nombre,
        tipo=req.tipo,
        obligatorio=req.obligatorio,
        descripcion=req.descripcion,
        cumplido=estado.cumplido,
        fecha_cumplimiento=estado.fecha_cumplimiento,
        observacion=estado.observacion,
    )


# ══════════════════════════════════════════════════════════════════
# VISTA: alumnos × requisito
# ══════════════════════════════════════════════════════════════════

@router.get("/curso/item/{idRequisito}/alumnos", response_model=List[AlumnoRequisitoRow])
def alumnos_por_requisito(idRequisito: int, db: Session = Depends(get_db)):
    req = db.exec(
        select(RequisitoCurso).where(RequisitoCurso.idRequisito == idRequisito)
    ).first()
    if not req:
        raise HTTPException(status_code=404, detail="Requisito no encontrado")

    rows = db.exec(
        select(Alumno)
        .join(Inscriptos, Inscriptos.idAlumno == Alumno.idAlumno)
        .where(Inscriptos.idCurso == req.idCurso)
    ).all()

    result: List[AlumnoRequisitoRow] = []
    for alumno in rows:
        estado = db.exec(
            select(RequisitoAlumno).where(
                RequisitoAlumno.idRequisito == idRequisito,
                RequisitoAlumno.idAlumno == alumno.idAlumno,
            )
        ).first()

        result.append(
            AlumnoRequisitoRow(
                idAlumno=alumno.idAlumno,
                nombre=alumno.nombre,
                apellido=alumno.apellido,
                cumplido=estado.cumplido if estado else False,
                observacion=estado.observacion if estado else None,
                fecha_cumplimiento=estado.fecha_cumplimiento if estado else None,
            )
        )

    result.sort(key=lambda x: (x.apellido, x.nombre))
    return result


# ══════════════════════════════════════════════════════════════════
# HOOK: crear estados al inscribir alumno en curso
# ══════════════════════════════════════════════════════════════════

def crear_estados_para_nuevo_alumno(idCurso: int, idAlumno: int, db: Session):
    requisitos = db.exec(
        select(RequisitoCurso).where(RequisitoCurso.idCurso == idCurso)
    ).all()

    for req in requisitos:
        existe = db.exec(
            select(RequisitoAlumno).where(
                RequisitoAlumno.idRequisito == req.idRequisito,
                RequisitoAlumno.idAlumno == idAlumno,
            )
        ).first()
        if not existe:
            db.add(RequisitoAlumno(idRequisito=req.idRequisito, idAlumno=idAlumno, cumplido=False))

    db.commit()