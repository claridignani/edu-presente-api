from __future__ import annotations

import re
from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import or_
from sqlmodel import select

from app.dependencies import SessionDep
from app.models.escuela import Escuela
from app.schemas.escuela import EscuelaPublic

router = APIRouter(prefix="/escuelas", tags=["Escuelas (Publico)"])

# Reutilizamos la lógica de sanitizado del router existente
from app.routers.escuela import _sanitize_escuela_for_public

@router.get("/buscar", response_model=list[EscuelaPublic])
def buscar_escuelas_publico(
    session: SessionDep,
    # ✅ permitimos q vacío (así tu front puede llamar q="")
    q: str = Query("", min_length=0, description="Texto a buscar (nombre, CUE, localidad, provincia)"),
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
):
    q_raw = (q or "").strip()
    if not q_raw:
        return []

    q_digits = re.sub(r"\D", "", q_raw)
    like_text = f"%{q_raw}%"
    like_digits = f"%{q_digits}%" if q_digits else None

    conditions = [
        Escuela.nombre.ilike(like_text),
        Escuela.localidad.ilike(like_text),
    ]

    if hasattr(Escuela, "provincia"):
        conditions.append(getattr(Escuela, "provincia").ilike(like_text))

    if like_digits:
        conditions.append(Escuela.CUE.ilike(like_digits))

    statement = (
        select(Escuela)
        .where(or_(*conditions))
        .order_by(Escuela.nombre)
        .limit(limit)
    )

    escuelas = session.exec(statement).all()
    return [EscuelaPublic.model_validate(_sanitize_escuela_for_public(e)) for e in escuelas]