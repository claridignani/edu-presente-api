from fastapi import HTTPException
from sqlmodel import select
from sqlalchemy import func, or_

from app.dependencies import SessionDep
from app.models.responsable import Responsable
from app.schemas.responsable import ResponsableCreate, ResponsableUpdate
from app.core.encryption import decrypt, hash_for_search


# ==============================================================
# HELPERS
# ==============================================================

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

def _decrypt_responsable(resp: Responsable) -> dict:
    """Desencripta los campos sensibles de un responsable para armar respuestas manuales."""
    return {
        "idResponsable": resp.idResponsable,
        "nombre": resp.nombre,
        "apellido": resp.apellido,
        "dni": decrypt(resp.dni) if resp.dni else resp.dni,
        "fecha_nacimiento": decrypt(resp.fecha_nacimiento) if resp.fecha_nacimiento else None,
        "email": resp.email,
        "nro_celular": resp.nro_celular,
        "direccion": decrypt(resp.direccion) if resp.direccion else resp.direccion,
    }


# ==============================================================
# GETTERS
# ==============================================================

def get_one_responsable(idResponsable: int, db: SessionDep):
    return db.get(Responsable, idResponsable)

def get_responsable_by_dni(db: SessionDep, dni: str) -> Responsable | None:
    """Busca responsable por DNI usando el hash determinístico."""
    dni_clean = _clean_str(dni) or ""
    if not dni_clean:
        return None
    dni_hash = hash_for_search(dni_clean)
    stmt = select(Responsable).where(Responsable.dni_hash == dni_hash)
    return db.exec(stmt).first()


# ==============================================================
# SEARCH (Nombre / Apellido / DNI)
# ==============================================================

def search_responsables(db: SessionDep, q: str, limit: int = 10) -> list[Responsable]:
    """
    Búsqueda por nombre/apellido con ilike.
    Si q es numérico, busca por dni_hash (exacto).
    """
    query = _clean_str(q) or ""
    if len(query) < 2:
        return []

    q_norm = query.lower()
    like = f"%{q_norm}%"

    if query.isdigit():
        # Búsqueda exacta por DNI usando hash
        dni_hash = hash_for_search(query)
        stmt = (
            select(Responsable)
            .where(Responsable.dni_hash == dni_hash)
            .limit(int(limit))
        )
    else:
        # Búsqueda parcial por nombre o apellido
        stmt = (
            select(Responsable)
            .where(
                or_(
                    func.lower(Responsable.nombre).like(like),
                    func.lower(Responsable.apellido).like(like),
                )
            )
            .limit(int(limit))
        )

    return list(db.exec(stmt).all())


# ==============================================================
# CREATE
# ==============================================================

def add_responsable(db: SessionDep, responsable_in: ResponsableCreate):
    # dni, fecha_nacimiento y direccion ya llegan encriptados desde ResponsableCreate
    # Para validaciones y búsquedas necesitamos el valor plain
    dni_encriptado = responsable_in.dni or ""
    if not dni_encriptado:
        raise HTTPException(status_code=400, detail="El DNI es obligatorio")

    dni_plain = decrypt(dni_encriptado)

    nombre = _clean_str(responsable_in.nombre) or ""
    apellido = _clean_str(responsable_in.apellido) or ""
    email = _clean_email(responsable_in.email) or ""
    nro = _clean_str(responsable_in.nro_celular) or ""
    direccion_encriptada = responsable_in.direccion or ""

    # Validaciones obligatorias
    if not dni_plain:
        raise HTTPException(status_code=400, detail="El DNI es obligatorio")
    if not nombre:
        raise HTTPException(status_code=400, detail="El nombre es obligatorio")
    if not apellido:
        raise HTTPException(status_code=400, detail="El apellido es obligatorio")
    if not email:
        raise HTTPException(status_code=400, detail="El email es obligatorio")
    if not nro:
        raise HTTPException(status_code=400, detail="El nro_celular es obligatorio")
    if not direccion_encriptada:
        raise HTTPException(status_code=400, detail="La dirección es obligatoria")

    # Reutilizar por DNI si ya existe
    existente = get_responsable_by_dni(db=db, dni=dni_plain)
    if existente:
        return existente

    # Crear nuevo — los campos encriptados ya vienen bien desde el schema
    data = responsable_in.model_dump()
    data["nombre"] = nombre
    data["apellido"] = apellido
    data["email"] = email
    data["nro_celular"] = nro
    # Aseguramos que el dni_hash esté seteado
    data["dni_hash"] = hash_for_search(dni_plain)

    db_resp = Responsable.model_validate(data)
    db.add(db_resp)
    db.commit()
    db.refresh(db_resp)
    return db_resp


# ==============================================================
# UPDATE
# ==============================================================

def update_responsable(db: SessionDep, responsable_existente: Responsable, responsable_nuevo: ResponsableUpdate):
    data = responsable_nuevo.model_dump(exclude_unset=True)

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

    # dni y direccion llegan encriptados desde ResponsableUpdate (field_validator)
    if "dni" in data and data["dni"]:
        dni_plain = decrypt(data["dni"])
        _require_not_empty(dni_plain, "dni")

        # Verificar unicidad usando hash
        dni_hash = hash_for_search(dni_plain)
        rid = int(responsable_existente.idResponsable)
        stmt = select(Responsable).where(
            Responsable.dni_hash == dni_hash,
            Responsable.idResponsable != rid,
        )
        if db.exec(stmt).first():
            raise HTTPException(status_code=400, detail="Ya existe otro responsable con ese DNI")

        # Actualizar el hash también
        data["dni_hash"] = dni_hash

    if "direccion" in data and data["direccion"]:
        # ya viene encriptada, solo validamos que no sea vacía desencriptando
        direccion_plain = decrypt(data["direccion"])
        _require_not_empty(direccion_plain, "direccion")

    responsable_existente.sqlmodel_update(data)
    db.add(responsable_existente)
    db.commit()
    db.refresh(responsable_existente)
    return responsable_existente


# ==============================================================
# DELETE
# ==============================================================

def delete_responsable(db: SessionDep, responsable: Responsable):
    db.delete(responsable)
    db.commit()