from sqlmodel import and_, select
from app.models.rol import Rol
from app.models.usuario import Usuario
from app.schemas.rol import RolDescripcion, RolEstado, RolUpdate
from app.dependencies import SessionDep

def get_one_rol(idUsuario: int, CUE: str, db: SessionDep):
    db_rol = db.get(Rol, (idUsuario, CUE))
    return db_rol

def change_rol_status(rol: RolUpdate, db: SessionDep):
    db_rol = get_one_rol(idUsuario=rol.idUsuario, CUE=rol.CUE, db=db)
    if not db_rol:
        raise Exception("El idUsuario o el CUE de la escuela son incorrectos")
    if isinstance(rol.estado, bool):
        db_rol.estado = RolEstado.Activo if rol.estado else RolEstado.Rechazado
    else:
        db_rol.estado = rol.estado
        
    db.add(db_rol)
    db.commit()
    db.refresh(db_rol)
    return db_rol

def get_roles_pendientes(db: SessionDep, rol: RolDescripcion):
    statement = select(Rol, Usuario).select_from(Rol).join(Usuario, (Rol.idUsuario == Usuario.idUsuario)).where(and_(Rol.estado == RolEstado.Pendiente, Rol.descripcion == rol.value))
    resultados = db.exec(statement).all()
    return resultados
