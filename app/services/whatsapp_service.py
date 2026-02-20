import httpx
from fastapi import APIRouter, HTTPException
from app.core.config import VERSION, PHONE_NUMBER_ID, WHATSAPP_TOKEN
from app.schemas.alumno import AlumnoPublic
router = APIRouter()

URL = f"https://graph.facebook.com/{VERSION}/{PHONE_NUMBER_ID}/messages"

async def enviar_plantilla_inasistencia(telefono: str, apellido: str, nombre: str, dni: str):
    # 1. Verificá que PHONE_NUMBER_ID y WHATSAPP_TOKEN no sean None antes de seguir
    if not PHONE_NUMBER_ID or not WHATSAPP_TOKEN:
        raise HTTPException(status_code=500, detail="Falta configuración de WhatsApp en el servidor")

    url_final = f"https://graph.facebook.com/{VERSION}/{PHONE_NUMBER_ID}/messages"
    
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }
    
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual", # Agregamos esto para mayor compatibilidad
        "to": str(telefono).strip(), # Limpiamos espacios
        "type": "template",
        "template": {
            "name": "inasistencia", # <-- ¡ASEGURATE QUE SEA EXACTAMENTE ASÍ EN META!
            "language": {"code": "es_AR"},
            "components": [
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "parameter_name": "apellido", "text": str(apellido)},
                        {"type": "text", "parameter_name": "nombre", "text": str(nombre)},
                        {"type": "text", "parameter_name": "dni", "text": str(dni)},
                    ]
                }
            ]
        }
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(url_final, headers=headers, json=payload)
        
        if response.status_code != 200:
            # Imprimimos el error exacto para debuguear
            print(f"DEBUG - Payload enviado: {payload}")
            print(f"Error de Meta: {response.text}")
            raise HTTPException(status_code=400, detail=f"Meta Error: {response.json()['error']['message']}")
            
        return response.json()