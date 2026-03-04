from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.dependencies import SessionDep
from app.dependencies.auth import get_current_user
from app.models.usuario import Usuario
from app.schemas.pase import (
    ComprobanteData,
    EscuelaSearchResult,
    PaseEntradaCreate,
    PaseEntradaListItem,
    PaseEntradaPublic,
    PaseSalidaBulkCreate,
    PaseSalidaCreate,
    PaseSalidaListItem,
    PaseSalidaPublic,
)
from app.services.pases_service import (
    anular_pase_salida,
    buscar_escuelas,
    confirmar_pase_entrada,
    crear_pase_entrada,
    crear_pase_salida,
    crear_pases_salida_bulk,
    get_comprobante,
    listar_entradas,
    listar_salidas,
)

router = APIRouter(prefix="/pases", tags=["Pases"])


# ──────────────────────────────────────────
# Salida — individual
# Desde: editar alumno / detalle alumno
# ──────────────────────────────────────────

@router.post("/salida", response_model=PaseSalidaPublic, status_code=201)
def crear_pase_salida_endpoint(
    payload: PaseSalidaCreate,
    session: SessionDep,
    current_user: Usuario = Depends(get_current_user),
):
    return crear_pase_salida(db=session, payload=payload)


# ──────────────────────────────────────────
# Salida — bulk
# Desde: flujo mover-alumnos (paso 3), cuando hay alumnos con accion=Baja
# ──────────────────────────────────────────

@router.post("/salida/bulk", response_model=list[PaseSalidaPublic], status_code=201)
def crear_pases_salida_bulk_endpoint(
    payload: PaseSalidaBulkCreate,
    session: SessionDep,
    current_user: Usuario = Depends(get_current_user),
):
    return crear_pases_salida_bulk(db=session, payload=payload)


# ──────────────────────────────────────────
# Salida — histórico por escuela
# ──────────────────────────────────────────

@router.get("/salida/{cue}", response_model=list[PaseSalidaListItem])
def listar_salidas_endpoint(
    cue: str,
    session: SessionDep,
    current_user: Usuario = Depends(get_current_user),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0),
):
    return listar_salidas(db=session, cue=cue, limit=limit, offset=offset)


# ──────────────────────────────────────────
# Salida — anular
# ──────────────────────────────────────────

@router.patch("/salida/{idPase}/anular", response_model=PaseSalidaPublic)
def anular_pase_salida_endpoint(
    idPase: int,
    session: SessionDep,
    current_user: Usuario = Depends(get_current_user),
):
    return anular_pase_salida(db=session, idPase=idPase)


# ──────────────────────────────────────────
# Salida — comprobante (datos para PDF en el front)
# ──────────────────────────────────────────

@router.get("/salida/{idPase}/comprobante", response_model=ComprobanteData)
def get_comprobante_endpoint(
    idPase: int,
    session: SessionDep,
    current_user: Usuario = Depends(get_current_user),
):
    nombre_director = f"{current_user.nombre} {current_user.apellido}"
    return get_comprobante(db=session, idPase=idPase, nombre_director=nombre_director)


# ──────────────────────────────────────────
# Entrada — crear
# Desde: alta de alumno nuevo con pase
# ──────────────────────────────────────────

@router.post("/entrada", response_model=PaseEntradaPublic, status_code=201)
def crear_pase_entrada_endpoint(
    payload: PaseEntradaCreate,
    session: SessionDep,
    current_user: Usuario = Depends(get_current_user),
):
    return crear_pase_entrada(db=session, payload=payload)


# ──────────────────────────────────────────
# Entrada — confirmar
# ──────────────────────────────────────────

@router.patch("/entrada/{idPaseEntrada}/confirmar", response_model=PaseEntradaPublic)
def confirmar_pase_entrada_endpoint(
    idPaseEntrada: int,
    session: SessionDep,
    current_user: Usuario = Depends(get_current_user),
):
    return confirmar_pase_entrada(db=session, idPaseEntrada=idPaseEntrada)


# ──────────────────────────────────────────
# Entrada — histórico por escuela
# ──────────────────────────────────────────

@router.get("/entrada/{cue}", response_model=list[PaseEntradaListItem])
def listar_entradas_endpoint(
    cue: str,
    session: SessionDep,
    current_user: Usuario = Depends(get_current_user),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0),
):
    return listar_entradas(db=session, cue=cue, limit=limit, offset=offset)


# ──────────────────────────────────────────
# Búsqueda de escuelas — parcial por nombre o CUE
# Desde: modal desvinculación (buscador de escuela destino)
#        y alta de alumno (buscador de escuela origen)
# ──────────────────────────────────────────

@router.get("/escuelas/buscar", response_model=list[EscuelaSearchResult])
def buscar_escuelas_endpoint(
    session: SessionDep,
    q: str = Query(min_length=2, description="Nombre o CUE parcial"),
    limit: int = Query(default=10, le=30),
    current_user: Usuario = Depends(get_current_user),
):
    return buscar_escuelas(db=session, q=q, limit=limit)