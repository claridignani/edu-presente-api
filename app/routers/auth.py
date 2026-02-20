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


@router.post("/", response_model=LoginResponse)
def login(data: LoginRequest, session: SessionDep):
    # 1) Buscar usuario
    user = get_usuario_by_dni(db=session, dni=data.dni)

    # 2) Validación
    if not user or not verify_password(plain_password=data.password, hashed_password=user.contrasena):
        logger.warning(f"Login fallido para DNI: {data.dni}")
        raise HTTPException(status_code=401, detail="Credenciales incorrectas")

    # 3) Traer roles + escuela
    try:
        statement = (
            select(Rol, Escuela)
            .join(Escuela, Rol.CUE == Escuela.CUE)
            .where(Rol.idUsuario == user.idUsuario)
            .where(
                or_(
                    Rol.estado == "Activo",
                    Rol.descripcion == "Administrador",
                )
            )
        )
        resultados = session.exec(statement).all()

    except Exception as e:
        logger.error(f"Error buscando roles: {e}")
        raise HTTPException(status_code=500, detail="Error interno al buscar roles.")

    opciones_validas: list[OpcionRol] = []
    for rol, escuela in resultados:
        opciones_validas.append(
            OpcionRol(
                idUsuario=rol.idUsuario,
                descripcion=rol.descripcion,
                CUE=escuela.CUE,
                nombre_escuela=escuela.nombre,
            )
        )

    if not opciones_validas:
        logger.warning(f"Usuario {user.idUsuario} sin roles activos válidos.")
        raise HTTPException(status_code=403, detail="Usuario pendiente de aprobación o sin roles asignados.")

    # ✅ 4) Emitir JWT: el backend ya puede saber “quién fue”
    # sub = idUsuario; NO metemos CUE/rol activo porque eso lo elige el front
    token = create_access_token({"sub": str(user.idUsuario)})

    logger.info(f"Login exitoso: {user.dni}")

    # Nota: esto requiere que LoginResponse tenga access_token y token_type (lo ajustamos abajo)
    return LoginResponse(
        mensaje="Login exitoso",
        usuario_id=user.idUsuario,
        nombre=user.nombre or "",
        apellido=user.apellido or "",
        roles_disponibles=opciones_validas,
        access_token=token,
        token_type="bearer",
    )
