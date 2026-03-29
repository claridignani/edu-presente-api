from fastapi import APIRouter, HTTPException
from sqlmodel import select, or_
from app.core.security import verify_password, create_access_token
from app.dependencies import SessionDep
from app.models.rol import Rol
from app.models.escuela import Escuela
from app.services.usuario_service import get_usuario_by_dni
from app.schemas.login import LoginRequest, OpcionRol, LoginResponse
import logging

router = APIRouter(prefix="/login", tags=["Login"])
logger = logging.getLogger(__name__)


# ── Login común ───────────────────────────────────────────────────────────────
# Solo entra si tiene al menos un rol activo
@router.post("/", response_model=LoginResponse)
def login(data: LoginRequest, session: SessionDep):
    user = get_usuario_by_dni(db=session, dni=data.dni)
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    if not verify_password(data.password, user.contrasena):
        raise HTTPException(status_code=401, detail="Contraseña incorrecta")

    try:
        statement = (
            select(Rol, Escuela)
            .join(Escuela, Rol.CUE == Escuela.CUE)
            .where(Rol.idUsuario == user.idUsuario)
            .where(or_(Rol.estado == "Activo", Rol.descripcion == "Administrador"))
        )
        resultados = session.exec(statement).all()
    except Exception as e:
        logger.error(f"Error buscando roles: {e}")
        raise HTTPException(status_code=500, detail="Error interno al buscar roles.")

    opciones_validas: list[OpcionRol] = [
        OpcionRol(
            idUsuario=rol.idUsuario,
            descripcion=rol.descripcion,
            CUE=escuela.CUE,
            nombre_escuela=escuela.nombre,
        )
        for rol, escuela in resultados
    ]

    if not opciones_validas:
        # Verificar si tiene roles pendientes o ninguno
        todos = session.exec(
            select(Rol).where(Rol.idUsuario == user.idUsuario)
        ).all()
        if todos:
            raise HTTPException(status_code=403, detail="Tu solicitud está pendiente de aprobación.")
        else:
            raise HTTPException(status_code=403, detail="No tenés roles asignados. Usá 'Solicitar acceso'.")

    token = create_access_token({"sub": str(user.idUsuario)})
    logger.info(f"Login exitoso: usuario {user.idUsuario}")

    return LoginResponse(
        mensaje="Login exitoso",
        usuario_id=user.idUsuario,
        nombre=user.nombre or "",
        apellido=user.apellido or "",
        roles_disponibles=opciones_validas,
        access_token=token,
        token_type="bearer",
    )


# ── Login para solicitar acceso ───────────────────────────────────────────────
# Solo valida que el usuario exista y la contraseña sea correcta
@router.post("/solicitud", response_model=LoginResponse)
def login_solicitud(data: LoginRequest, session: SessionDep):
    user = get_usuario_by_dni(db=session, dni=data.dni)
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    if not verify_password(data.password, user.contrasena):
        raise HTTPException(status_code=401, detail="Contraseña incorrecta")

    token = create_access_token({"sub": str(user.idUsuario)})
    logger.info(f"Login solicitud exitoso: usuario {user.idUsuario}")

    return LoginResponse(
        mensaje="Login exitoso",
        usuario_id=user.idUsuario,
        nombre=user.nombre or "",
        apellido=user.apellido or "",
        roles_disponibles=[],  # no importan los roles acá
        access_token=token,
        token_type="bearer",
    )