from fastapi import APIRouter, Response, Query, Request
from app.core.config import VERIFY_TOKEN
from app.dependencies import SessionDep
from app.services.whatsapp_service import procesar_respuesta_padre

router = APIRouter(prefix="/webhook", tags=["Webhook"])

@router.get("/whatsapp")
async def verificar_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
    hub_verify_token: str = Query(None, alias="hub.verify_token")
):
    if hub_mode == "subscribe" and hub_verify_token == VERIFY_TOKEN:
        print("✅ WEBHOOK VERIFICADO POR META")
        
        return Response(content=hub_challenge, status_code=200)
    
    print("❌ Error de verificación de Webhook")
    return Response(content="Token inválido", status_code=403)


"""
Esta funcion se deja comentada, sirve como prueba para ver por consola los mensajes 
si se descomenta esta función se debe comentar la siguiente función denominada recibir_respuesta_padre

@router.post("/whatsapp")
async def recibir_respuesta_padre(request: Request): 
    try:
        body = await request.json()
        
        if body.get("object") == "whatsapp_business_account":
            entry = body.get("entry", [{}])[0]
            changes = entry.get("changes", [{}])[0]
            value = changes.get("value", {})
            
            if "messages" in value:
                mensaje = value["messages"][0]
                
                telefono_padre = mensaje["from"] 
                tipo_mensaje = mensaje.get("type")
                
                if tipo_mensaje == "button":
                    motivo_seleccionado = mensaje["button"]["payload"]
                    
                    print(f"✅ RECIBIDO: El número {telefono_padre} seleccionó: {motivo_seleccionado}")
                    if motivo_seleccionado == "Enfermedad":
                        print("-> Lógica para pedir foto del certificado médico...")
                    else:
                        print("-> Lógica para confirmar otro motivo...")

        return Response(status_code=200)
        
    except Exception as e:
        print(f"❌ Error procesando el webhook: {e}")
        return Response(status_code=200)
"""


@router.post("/whatsapp")
async def recibir_respuesta_padre(request: Request, session: SessionDep):
    try:
        body = await request.json()
        
        if body.get("object") == "whatsapp_business_account":
            entry = body.get("entry", [{}])[0]
            changes = entry.get("changes", [{}])[0]
            value = changes.get("value", {})
            
            if "messages" in value:
                mensaje = value["messages"][0]
                
                if mensaje.get("type") == "button":
                    motivo_seleccionado = mensaje["button"]["payload"]
                    wamid_original = mensaje.get("context", {}).get("id")
                    
                    if wamid_original:
                        await procesar_respuesta_padre(
                            wamid=wamid_original, 
                            motivo=motivo_seleccionado, 
                            db=session
                        )

        # Obligatorio responder rápido a Meta
        return Response(status_code=200)
        
    except Exception as e:
        print(f"❌ Error procesando el webhook: {e}")
        return Response(status_code=200)