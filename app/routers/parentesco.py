from fastapi import APIRouter, HTTPException

from app.dependencies import SessionDep
from app.schemas.parentesco import ParentescoPublic, ParentescoCreate
from app.services.parentesco_service import add_parentesco
from app.services.parentesco_service import get_responsables_by_alumno
from app.schemas.parentesco import ResponsableConParentescoPublic

from app.models.parentesco import Parentesco


router = APIRouter(prefix="/parentescos", tags=["Parentescos"])

@router.post("/", response_model=ParentescoPublic)
def create_parentesco(payload: ParentescoCreate, session: SessionDep):
    return add_parentesco(db=session, rel_in=payload)

@router.put("/", response_model=ParentescoPublic)
def update_parentesco(payload: ParentescoCreate, session: SessionDep):
    # UPSERT: si existe, actualiza; si no existe, crea
    rel = session.get(Parentesco, (payload.idAlumno, payload.idResponsable))

    if not rel:
        rel = Parentesco(
            idAlumno=payload.idAlumno,
            idResponsable=payload.idResponsable,
            parentesco=payload.parentesco,
        )
        session.add(rel)
        session.commit()
        session.refresh(rel)
        return rel

    rel.parentesco = payload.parentesco
    session.add(rel)
    session.commit()
    session.refresh(rel)
    return rel


@router.get("/responsables-por-alumno/{idAlumno}", response_model=list[ResponsableConParentescoPublic])
def get_responsables_alumno_route(idAlumno: int, session: SessionDep):
    return get_responsables_by_alumno(db=session, idAlumno=idAlumno)