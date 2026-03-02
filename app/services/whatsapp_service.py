import re
import logging
import httpx
from fastapi import HTTPException
from app.core.config import VERSION, PHONE_NUMBER_ID, WHATSAPP_TOKEN
from sqlmodel import select
from app.dependencies import SessionDep
from app.models.asistencia import Asistencia

logger = logging.getLogger(__name__)

# Timeout: 10s para conectar, 30s para leer la respuesta
_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=5.0)


def _normalizar_telefono(telefono: str) -> str:
    """Normaliza un número de teléfono al formato internacional requerido por Meta.
    Ejemplo: '011-1234-5678' -> '5411 12345678', '5491112345678' -> '5491112345678'
    """
    solo_digitos = re.sub(r"\D", "", str(telefono).strip())
    # Remover 0 inicial (código de área local argentino)
    if solo_digitos.startswith("0"):
        solo_digitos = solo_digitos[1:]
    # Agregar código de país si no lo tiene
    if not solo_digitos.startswith("54"):
        solo_digitos = f"54{solo_digitos}"
    return solo_digitos


async def enviar_plantilla_inasistencia(telefono: str, apellido: str, nombre: str, dni: str) -> str | None:
    """
    Envía la plantilla de inasistencia por WhatsApp.
    Retorna el wamid si el envío fue exitoso, o None si hubo un error de red.
    Lanza HTTPException sólo ante errores de configuración o respuesta inválida de Meta.
    """
    if not PHONE_NUMBER_ID or not WHATSAPP_TOKEN:
        raise HTTPException(status_code=500, detail="Falta configuración de WhatsApp en el servidor")

    url_final = f"https://graph.facebook.com/{VERSION}/{PHONE_NUMBER_ID}/messages"

    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": _normalizar_telefono(telefono),
        "type": "template",
        "template": {
            "name": "inasistencia",
            "language": {"code": "es_AR"},
            "components": [
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "parameter_name": "apellido", "text": str(apellido)},
                        {"type": "text", "parameter_name": "nombre", "text": str(nombre)},
                        {"type": "text", "parameter_name": "dni", "text": str(dni)},
                    ],
                }
            ],
        },
    }

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.post(url_final, headers=headers, json=payload)

        if response.status_code != 200:
            logger.error("Error de Meta al enviar WhatsApp. Payload: %s | Respuesta: %s", payload, response.text)
            raise HTTPException(
                status_code=400,
                detail=f"Meta Error: {response.json()['error']['message']}",
            )

        data = response.json()
        mensaje_id = data["messages"][0]["id"]
        logger.info("WhatsApp enviado con éxito. wamid: %s", mensaje_id)
        return mensaje_id

    except httpx.ConnectTimeout:
        logger.warning(
            "Timeout al conectar con la API de WhatsApp para %s (%s). "
            "Verificar conectividad o estado de Meta.",
            apellido, _normalizar_telefono(telefono),
        )
        return None
    except httpx.ReadTimeout:
        logger.warning(
            "Timeout leyendo respuesta de Meta para %s (%s).",
            apellido, _normalizar_telefono(telefono),
        )
        return None
    except httpx.NetworkError as exc:
        logger.warning("Error de red al enviar WhatsApp a %s: %s", apellido, exc)
        return None
    
async def procesar_respuesta_padre(wamid: str, motivo: str, db: SessionDep):
    """
    Recibe el identificador del mensaje de Meta y el motivo seleccionado por el tutor.
    Busca la inasistencia original y la actualiza en la base de datos.
    """
    statement = select(Asistencia).where(Asistencia.wamid == wamid)
    inasistencia = db.exec(statement).first()
    
    if inasistencia:
        inasistencia.motivo_ausencia = motivo
        db.add(inasistencia)
        db.commit()
        
        print(f"✅ ÉXITO: Motivo '{motivo}' registrado para la asistencia ID: {inasistencia.idAlumno}")
    else:
        print(f"⚠️ WAMID recibido pero no se encontró la inasistencia en la BD: {wamid}")
