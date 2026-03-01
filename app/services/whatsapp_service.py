import re
import httpx
from fastapi import HTTPException
from app.core.config import VERSION, PHONE_NUMBER_ID, WHATSAPP_TOKEN
from sqlmodel import select
from app.dependencies import SessionDep
from app.models.asistencia import Asistencia


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



async def enviar_plantilla_inasistencia(telefono: str, apellido: str, nombre: str, dni: str):
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
                    ]
                }
            ]
        }
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(url_final, headers=headers, json=payload)
        
        if response.status_code != 200:
            print(f"DEBUG - Payload enviado: {payload}")
            print(f"Error de Meta: {response.text}")
            raise HTTPException(status_code=400, detail=f"Meta Error: {response.json()['error']['message']}")
            
        # 3. Si todo salió bien (status 200), extraemos la data
        data = response.json()
        
        # 4. Capturamos el wamid y lo retornamos
        mensaje_id = data["messages"][0]["id"] 
        print(f"Mensaje enviado con éxito. ID: {mensaje_id}")
        
        return mensaje_id
    
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
