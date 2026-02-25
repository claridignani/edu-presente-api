from fastapi import HTTPException
from sqlmodel import select
from sqlalchemy import func, or_

from app.dependencies import SessionDep
from app.models.responsable import Responsable
from app.schemas.responsable import ResponsableCreate, ResponsableUpdate


# =========================
# HELPERS
# =========================

def _clean_str(v: str | None) -> str | None:
    if v is None:
        return None
    return str(v).strip()

def _clean_email(v: str | None) -> str | None:
    if v is None:
        return None
    return str(v).strip().lower()

def _require_not_empty(value: str | None, field_name: str):
    if value is not None and not str(value).strip():
        raise HTTPException(status_code=400, detail=f"El campo '{field_name}' no puede estar vacío")

def _exists_responsable_by_field(
    db: SessionDep,
    field,
    value: str,
    exclude_id: int | None = None,
) -> bool:
    stmt = select(Responsable).where(field == value)
    if exclude_id is not None:
        stmt = stmt.where(Responsable.idResponsable != exclude_id)
    return db.exec(stmt).first() is not None


# =========================
# GETTERS
# =========================

def get_one_responsable(idResponsable: int, db: SessionDep):
    return db.get(Responsable, idResponsable)

def get_responsable_by_dni(db: SessionDep, dni: str):
    dni_clean = _clean_str(dni) or ""
    stmt = select(Responsable).where(Responsable.dni == dni_clean)
    return db.exec(stmt).first()


# =========================
# SEARCH (Nombre / Apellido / DNI)
# =========================

def search_responsables(db: SessionDep, q: str, limit: int = 10) -> list[Responsable]:
    query = _clean_str(q) or ""
    if len(query) < 2:
        return []

    q_norm = query.lower()
    like = f"%{q_norm}%"

    stmt = (
        select(Responsable)
        .where(
            or_(
                func.lower(Responsable.nombre).like(like),
                func.lower(Responsable.apellido).like(like),
                func.lower(Responsable.dni).like(like),
            )
        )
        .limit(int(limit))
    )

    return list(db.exec(stmt).all())


# =========================
# CREATE
# =========================
"""
Regla de negocio:
- Un Responsable representa a una persona.
- Una persona puede estar asociada a muchos alumnos (por Parentesco).
- DNI identifica (único) y si ya existe, se REUTILIZA (no error).
- Email/celular son OBLIGATORIOS, pero NO únicos.
"""

def add_responsable(db: SessionDep, responsable_in: ResponsableCreate):
    dni = _clean_str(responsable_in.dni) or ""
    nombre = _clean_str(responsable_in.nombre) or ""
    apellido = _clean_str(responsable_in.apellido) or ""
    email = _clean_email(responsable_in.email) or ""
    nro = _clean_str(responsable_in.nro_celular) or ""
    direccion = _clean_str(responsable_in.direccion) or ""

    # =========================
    # VALIDACIONES OBLIGATORIAS
    # =========================
    if not dni:
        raise HTTPException(status_code=400, detail="El DNI es obligatorio")
    if not nombre:
        raise HTTPException(status_code=400, detail="El nombre es obligatorio")
    if not apellido:
        raise HTTPException(status_code=400, detail="El apellido es obligatorio")
    if not email:
        raise HTTPException(status_code=400, detail="El email es obligatorio")
    if not nro:
        raise HTTPException(status_code=400, detail="El nro_celular es obligatorio")
    if not direccion:
        raise HTTPException(status_code=400, detail="La dirección es obligatoria")

    # =========================
    # REUTILIZAR POR DNI
    # =========================
    existente = get_responsable_by_dni(db=db, dni=dni)
    if existente:
        return existente

    # =========================
    # CREAR NUEVO
    # =========================
    data = responsable_in.model_dump()
    data["dni"] = dni
    data["nombre"] = nombre
    data["apellido"] = apellido
    data["email"] = email
    data["nro_celular"] = nro
    data["direccion"] = direccion

    db_resp = Responsable.model_validate(data)
    db.add(db_resp)
    db.commit()
    db.refresh(db_resp)
    return db_resp


# =========================
# UPDATE
# =========================

def update_responsable(db: SessionDep, responsable_existente: Responsable, responsable_nuevo: ResponsableUpdate):
    data = responsable_nuevo.model_dump(exclude_unset=True)

    # limpieza + no vacíos (si vienen)
    if "dni" in data:
        data["dni"] = _clean_str(data["dni"])
        _require_not_empty(data["dni"], "dni")

    if "email" in data:
        data["email"] = _clean_email(data["email"])
        _require_not_empty(data["email"], "email")

    if "nro_celular" in data:
        data["nro_celular"] = _clean_str(data["nro_celular"])
        _require_not_empty(data["nro_celular"], "nro_celular")

    if "nombre" in data:
        data["nombre"] = _clean_str(data["nombre"])
        _require_not_empty(data["nombre"], "nombre")

    if "apellido" in data:
        data["apellido"] = _clean_str(data["apellido"])
        _require_not_empty(data["apellido"], "apellido")

    if "direccion" in data:
        data["direccion"] = _clean_str(data["direccion"])
        _require_not_empty(data["direccion"], "direccion")

    # ✅ Solo validamos DNI como único (porque en DB es único)
    rid = int(responsable_existente.idResponsable)

    if data.get("dni"):
        if _exists_responsable_by_field(db, Responsable.dni, data["dni"], exclude_id=rid):
            raise HTTPException(status_code=400, detail="Ya existe otro responsable con ese DNI")

    # ❌ NO validamos unicidad para email/celular

    responsable_existente.sqlmodel_update(data)
    db.add(responsable_existente)
    db.commit()
    db.refresh(responsable_existente)
    return responsable_existente


# =========================
# DELETE
# =========================

def delete_responsable(db: SessionDep, responsable: Responsable):
    db.delete(responsable)
    db.commit()
