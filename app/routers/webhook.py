from fastapi import APIRouter, Response, Query, Request
from app.core.config import VERIFY_TOKEN

router = APIRouter(prefix="/webhook", tags=["Webhook"])

# 2. Creamos el endpoint GET específicamente para la verificación de Meta
@router.get("/whatsapp")
async def verificar_webhook(
    # FastAPI extrae mágicamente los parámetros que manda Meta por la URL
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
    hub_verify_token: str = Query(None, alias="hub.verify_token")
):
    # 3. Comparamos lo que mandó Meta con nuestro token
    if hub_mode == "subscribe" and hub_verify_token == VERIFY_TOKEN:
        print("✅ WEBHOOK VERIFICADO POR META")
        
        # 4. OBLIGATORIO: Devolver el challenge en texto plano (status 200)
        return Response(content=hub_challenge, status_code=200)
    
    # Si alguien más intenta adivinar tu URL, le damos un error 403 (Prohibido)
    print("❌ Error de verificación de Webhook")
    return Response(content="Token inválido", status_code=403)


@router.post("/whatsapp")
async def recibir_respuesta_padre(request: Request): # Más adelante agregamos: session: SessionDep
    try:
        # 1. Capturamos el JSON que nos manda Meta
        body = await request.json()
        
        # 2. Navegamos por la estructura del JSON de WhatsApp
        if body.get("object") == "whatsapp_business_account":
            entry = body.get("entry", [{}])[0]
            changes = entry.get("changes", [{}])[0]
            value = changes.get("value", {})
            
            # 3. Verificamos si adentro del evento viene un mensaje
            if "messages" in value:
                mensaje = value["messages"][0]
                
                # Sacamos el número de teléfono del padre
                telefono_padre = mensaje["from"] 
                
                # Verificamos qué tipo de mensaje mandó
                tipo_mensaje = mensaje.get("type")
                
                # 4. Si el mensaje es un click en un botón de nuestra plantilla
                if tipo_mensaje == "button":
                    # Extraemos qué botón tocó (ej: "Enfermedad", "Viaje")
                    motivo_seleccionado = mensaje["button"]["payload"]
                    
                    print(f"✅ RECIBIDO: El número {telefono_padre} seleccionó: {motivo_seleccionado}")
                    
                    # ----------------------------------------------------------------
                    # ACÁ ADENTRO IRA LA LÓGICA DE BASE DE DATOS Y RESPUESTAS
                    # ----------------------------------------------------------------
                    if motivo_seleccionado == "Enfermedad":
                        print("-> Lógica para pedir foto del certificado médico...")
                        # await pedir_comprobante_whatsapp(telefono_padre)
                    else:
                        print("-> Lógica para confirmar otro motivo...")
                        # await enviar_mensaje_texto(telefono_padre, "Motivo registrado con éxito.")

        # 5. OBLIGATORIO: Siempre devolver 200 OK rápido para que Meta no penalice ni reintente
        return Response(status_code=200)
        
    except Exception as e:
        print(f"❌ Error procesando el webhook: {e}")
        # Aunque haya error interno, le decimos 200 a Meta para que no se trabe
        return Response(status_code=200)