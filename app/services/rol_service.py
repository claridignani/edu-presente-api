from sqlmodel import and_, select
from fastapi import HTTPException

from app.models.rol import Rol
from app.models.usuario import Usuario
from app.models.escuela import Escuela
from app.schemas.rol import RolDescripcion, RolEstado, RolUpdate, RolCreate
from app.dependencies import SessionDep


def get_one_rol(idUsuario: int, CUE: str, db: SessionDep) -> Rol | None:
    return db.get(Rol, (idUsuario, CUE))


def create_rol(payload: RolCreate, db: SessionDep) -> Rol:
    # validar usuario
    user = db.get(Usuario, payload.idUsuario)
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no existe")

    # validar escuela
    escuela = db.get(Escuela, payload.CUE)
    if not escuela:
        raise HTTPException(status_code=404, detail="Escuela (CUE) no existe")

    # evitar duplicado PK compuesta
    existente = get_one_rol(idUsuario=payload.idUsuario, CUE=payload.CUE, db=db)
    if existente:
        raise HTTPException(status_code=409, detail="Ya existe un rol para ese usuario en esa escuela")

    nuevo = Rol(
        idUsuario=payload.idUsuario,
        CUE=payload.CUE,
        descripcion=payload.descripcion,
        estado=payload.estado,
    )

    db.add(nuevo)
    db.commit()
    db.refresh(nuevo)
    return nuevo


def change_rol_status(rol: RolUpdate, db: SessionDep) -> Rol:
    db_rol = get_one_rol(idUsuario=rol.idUsuario, CUE=rol.CUE, db=db)

    if not db_rol:
        raise HTTPException(
            status_code=404,
            detail="No existe el rol para ese idUsuario y CUE (primero crealo con POST /roles/)"
        )

    # estado puede venir bool o enum
    if isinstance(rol.estado, bool):
        db_rol.estado = RolEstado.Activo if rol.estado else RolEstado.Rechazado
    else:
        db_rol.estado = rol.estado

    # si mandan descripcion opcional, permitimos actualizarla
    if rol.descripcion is not None:
        db_rol.descripcion = rol.descripcion

    db.add(db_rol)
    db.commit()
    db.refresh(db_rol)
    return db_rol


def get_roles_pendientes(db: SessionDep, rol: RolDescripcion):
    statement = (
        select(Rol, Usuario)
        .select_from(Rol)
        .join(Usuario, (Rol.idUsuario == Usuario.idUsuario))
        .where(and_(Rol.estado == RolEstado.Pendiente, Rol.descripcion == rol.value))
    )
    return db.exec(statement).all()
