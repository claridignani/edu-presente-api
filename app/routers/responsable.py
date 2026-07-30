# app/routers/responsable.py
from fastapi import APIRouter, HTTPException, status, Query

from app.dependencies import SessionDep
from app.schemas.responsable import (
    ResponsablePublic,
    ResponsableCreate,
    ResponsableUpdate,
)

from app.services.responsable_service import (
    add_responsable,
    get_one_responsable,
    get_responsable_by_dni,
    update_responsable,
    search_responsables,   # ✅ NUEVO
)

router = APIRouter(prefix="/responsables", tags=["Responsables"])


# =========================
# CREATE
# =========================

@router.post("/", response_model=ResponsablePublic, status_code=status.HTTP_201_CREATED)
def create_responsable(payload: ResponsableCreate, session: SessionDep):
    return add_responsable(db=session, responsable_in=payload)


# =========================
# SEARCH (Nombre / Apellido / DNI)
# =========================

@router.get("/buscar", response_model=list[ResponsablePublic])
def buscar_responsables(
    q: str = Query(..., min_length=2, max_length=60),
    limit: int = Query(default=10, ge=1, le=30),
    session: SessionDep = None,
):
    return search_responsables(db=session, q=q, limit=limit)


# =========================
# GET BY DNI
# =========================

@router.get("/dni/{dni}", response_model=ResponsablePublic)
def get_responsable_by_dni_route(dni: str, session: SessionDep):
    r = get_responsable_by_dni(db=session, dni=dni)
    if not r:
        raise HTTPException(status_code=404, detail="Responsable no encontrado")
    return r


# =========================
# GET BY ID
# =========================

@router.get("/{idResponsable}", response_model=ResponsablePublic)
def get_responsable(idResponsable: int, session: SessionDep):
    r = get_one_responsable(idResponsable=idResponsable, db=session)
    if not r:
        raise HTTPException(status_code=404, detail="Responsable no encontrado")
    return r


# =========================
# UPDATE
# =========================

@router.put("/{idResponsable}", response_model=ResponsablePublic)
def update_responsable_by_id(
    idResponsable: int,
    payload: ResponsableUpdate,
    session: SessionDep,
):
    responsable = get_one_responsable(idResponsable=idResponsable, db=session)
    if not responsable:
        raise HTTPException(status_code=404, detail="Responsable no encontrado")

    return update_responsable(
        db=session,
        responsable_existente=responsable,
        responsable_nuevo=payload,
    )
