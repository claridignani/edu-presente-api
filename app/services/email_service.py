# app/services/email_service.py
import os
from fastapi_mail import FastMail, MessageSchema, ConnectionConfig, MessageType

# ── Config desde variables de entorno ────────────────────────────────────────
# Agregá estas variables a tu .env:
#
#   MAIL_USERNAME=tu_cuenta@gmail.com
#   MAIL_PASSWORD=tu_app_password         # contraseña de aplicación, NO la de tu cuenta
#   MAIL_FROM=tu_cuenta@gmail.com
#   MAIL_FROM_NAME=EduPresente
#   FRONTEND_URL=http://localhost:4200     # en prod: tu dominio real

conf = ConnectionConfig(
    MAIL_USERNAME=os.environ["MAIL_USERNAME"],
    MAIL_PASSWORD=os.environ["MAIL_PASSWORD"],
    MAIL_FROM=os.environ["MAIL_FROM"],
    MAIL_FROM_NAME=os.environ.get("MAIL_FROM_NAME", "EduPresente"),
    MAIL_PORT=587,
    MAIL_SERVER="smtp.gmail.com",
    MAIL_STARTTLS=True,
    MAIL_SSL_TLS=False,
    USE_CREDENTIALS=True,
)

FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:4200")


def send_reset_email(email: str, nombre: str, token: str) -> None:
    """Manda el email de recuperación de contraseña de forma sincrónica."""
    import asyncio

    reset_link = f"{FRONTEND_URL}/reset-password?token={token}"

    html_body = f"""
    <div style="font-family: Arial, sans-serif; max-width: 480px; margin: 0 auto; padding: 32px; background: #f0f7ff; border-radius: 16px;">
      <div style="text-align: center; margin-bottom: 24px;">
        <h1 style="color: #007bff; font-size: 28px; font-weight: 800; margin: 0;">EduPresente</h1>
        <p style="color: #00bcd4; font-size: 14px; margin: 4px 0 0;">Sistema de Gestión Escolar</p>
      </div>

      <div style="background: #ffffff; border-radius: 12px; padding: 28px;">
        <p style="color: #2c3e50; font-size: 15px; margin: 0 0 12px;">Hola <strong>{nombre}</strong>,</p>
        <p style="color: #2c3e50; font-size: 15px; margin: 0 0 24px;">
          Recibimos una solicitud para restablecer tu contraseña.
          Hacé clic en el botón para crear una nueva:
        </p>

        <div style="text-align: center; margin: 28px 0;">
        <a href="{reset_link}" style="background: #007bff; color: #ffffff; text-decoration: none; padding: 14px 32px; border-radius: 24px; font-size: 16px; font-weight: 700; display: inline-block;">Restablecer contraseña</a>
        </div>
        <p style="text-align:center; margin: 12px 0 0; font-size: 12px; color: #6c757d;">
        O copiá este enlace en tu navegador:<br>
        <span style="color: #007bff; word-break: break-all;">{reset_link}</span>
        </p>

        <p style="color: #6c757d; font-size: 13px; margin: 24px 0 0;">
          Este enlace expira en <strong>30 minutos</strong>.<br>
          Si no solicitaste esto, podés ignorar este mensaje.
        </p>
      </div>

      <p style="color: #a0aec0; font-size: 12px; text-align: center; margin-top: 20px;">
        EduPresente — Sistema de Gestión Escolar
      </p>
    </div>
    """

    message = MessageSchema(
        subject="Restablecer contraseña — EduPresente",
        recipients=[email],
        body=html_body,
        subtype=MessageType.html,
    )

    fm = FastMail(conf)
    asyncio.run(fm.send_message(message))