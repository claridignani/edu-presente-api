# app/routers/reset_password.py
import secrets
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlmodel import select

from app.dependencies import SessionDep
from app.models.password_reset_token import PasswordResetToken
from app.models.usuario import Usuario
from app.core.security import get_password_hash
from app.services.usuario_service import get_usuario_by_dni
from app.services.email_service import send_reset_email

router = APIRouter(prefix="/reset-password", tags=["Reset Password"])
logger = logging.getLogger(__name__)

TOKEN_EXPIRY_MINUTES = 30


# ── Schemas ──────────────────────────────────────────────────────────────────

class SolicitarResetRequest(BaseModel):
    dni: str


class ConfirmarResetRequest(BaseModel):
    token: str
    nueva_contrasena: str


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/solicitar")
def solicitar_reset(data: SolicitarResetRequest, session: SessionDep):
    """
    Recibe el DNI, genera un token temporal y manda el email.
    Siempre responde igual para no revelar si el DNI existe o no.
    """
    usuario = get_usuario_by_dni(db=session, dni=data.dni)

    # Respuesta genérica aunque no exista el usuario (seguridad)
    respuesta = {"mensaje": "Si el DNI está registrado, recibirás un email con las instrucciones."}

    if not usuario:
        logger.warning(f"Reset solicitado para DNI no existente: {data.dni}")
        return respuesta

    if not usuario.mailABC:
        logger.warning(f"Usuario {usuario.idUsuario} sin email registrado.")
        return respuesta

    # Invalidar tokens anteriores del mismo usuario
    tokens_anteriores = session.exec(
        select(PasswordResetToken).where(
            PasswordResetToken.idUsuario == usuario.idUsuario,
            PasswordResetToken.usado == False,
        )
    ).all()
    for t in tokens_anteriores:
        t.usado = True
        session.add(t)

    # Generar token nuevo
    token = secrets.token_urlsafe(16)
    expira_en = datetime.now(timezone.utc) + timedelta(minutes=TOKEN_EXPIRY_MINUTES)

    reset_token = PasswordResetToken(
        idUsuario=usuario.idUsuario,
        token=token,
        expira_en=expira_en,
    )
    session.add(reset_token)
    session.commit()

    # Mandar email
    try:
        send_reset_email(
            email=usuario.mailABC,
            nombre=usuario.nombre,
            token=token,
        )
        logger.info(f"Email enviado a {usuario.mailABC}")
    except Exception as e:
        logger.error(f"Error mandando email: {type(e).__name__}: {e}")
        return respuesta

    logger.info(f"Reset solicitado para usuario {usuario.idUsuario}")
    return respuesta


@router.post("/confirmar")
def confirmar_reset(data: ConfirmarResetRequest, session: SessionDep):
    """
    Valida el token y actualiza la contraseña.
    """
    if len(data.nueva_contrasena) < 4:
        raise HTTPException(status_code=422, detail="La contraseña debe tener al menos 4 caracteres.")

    # Buscar token válido
    reset_token = session.exec(
        select(PasswordResetToken).where(
            PasswordResetToken.token == data.token,
            PasswordResetToken.usado == False,
        )
    ).first()

    if not reset_token:
        raise HTTPException(status_code=400, detail="El enlace no es válido.")

    # Verificar expiración
    ahora = datetime.now(timezone.utc)
    expira = reset_token.expira_en
    if expira.tzinfo is None:
        expira = expira.replace(tzinfo=timezone.utc)

    if ahora > expira:
        reset_token.usado = True
        session.add(reset_token)
        session.commit()
        raise HTTPException(status_code=400, detail="El enlace expiró. Solicitá uno nuevo.")

    # Actualizar contraseña
    usuario = session.get(Usuario, reset_token.idUsuario)
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado.")

    usuario.contrasena = get_password_hash(data.nueva_contrasena)
    reset_token.usado = True

    session.add(usuario)
    session.add(reset_token)
    session.commit()

    logger.info(f"Contraseña actualizada para usuario {usuario.idUsuario}")
    return {"mensaje": "Contraseña actualizada correctamente. Ya podés iniciar sesión."}