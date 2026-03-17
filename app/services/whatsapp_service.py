import asyncio
import re
import logging
import httpx
from pathlib import Path
from fastapi import HTTPException
from app.core.config import VERSION, PHONE_NUMBER_ID, WHATSAPP_TOKEN
from sqlmodel import select, and_
from app.dependencies import SessionDep
from app.models.asistencia import Asistencia
from app.models.parentesco import Parentesco
from app.models.responsable import Responsable

logger = logging.getLogger(__name__)

# Timeout: 10s para conectar, 30s para leer la respuesta
_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=5.0)

# Reintentos automáticos ante fallos de red
_MAX_RETRIES = 3           # intentos totales (1 original + 2 reintentos)
_RETRY_BACKOFF_BASE = 1.0  # espera base en segundos (1s, 2s, 4s)

# Excepciones de red que justifican un reintento
_RETRIABLE_EXCEPTIONS = (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.NetworkError)

# Carpeta base para certificados médicos
_UPLOADS_DIR = Path(__file__).resolve().parent.parent.parent / "uploads" / "certificados"

# Extensiones permitidas según mime_type de Meta
_MIME_TO_EXT = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}


def _normalizar_telefono(telefono: str) -> str:
    """Normaliza un número de teléfono al formato internacional requerido por Meta.

    Reglas de normalización (Argentina):
      1. Eliminar todo carácter no-dígito
      2. Remover 0 inicial (código troncal local)
      3. Agregar código de país 54 si no lo tiene
      4. Remover el 9 de celular argentino (54 9 XXX → 54 XXX)
         Meta acepta ambos formatos, pero usamos sin 9 para consistencia.

    Ejemplos:
      '011-1234-5678'   → '541112345678'
      '5493413763333'   → '543413763333'
      '3413763333'      → '543413763333'
    """
    solo_digitos = re.sub(r"\D", "", str(telefono).strip())
    # Remover 0 inicial (código de área local argentino)
    if solo_digitos.startswith("0"):
        solo_digitos = solo_digitos[1:]
    # Agregar código de país si no lo tiene
    if not solo_digitos.startswith("54"):
        solo_digitos = f"54{solo_digitos}"
    # Remover el 9 de celular argentino: 549XXXXXXXXXX → 54XXXXXXXXXX
    if solo_digitos.startswith("549") and len(solo_digitos) >= 13:
        solo_digitos = "54" + solo_digitos[3:]
    return solo_digitos


# ============================================================
# Enviar plantilla de inasistencia (existente)
# ============================================================

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

    for intento in range(1, _MAX_RETRIES + 1):
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

        except _RETRIABLE_EXCEPTIONS as exc:
            if intento < _MAX_RETRIES:
                espera = _RETRY_BACKOFF_BASE * (2 ** (intento - 1))
                logger.warning(
                    "Intento %d/%d falló para %s (%s): %s — reintentando en %.0fs",
                    intento, _MAX_RETRIES, apellido,
                    _normalizar_telefono(telefono), exc, espera,
                )
                await asyncio.sleep(espera)
            else:
                logger.error(
                    "Todos los reintentos agotados (%d/%d) para %s (%s): %s",
                    intento, _MAX_RETRIES, apellido,
                    _normalizar_telefono(telefono), exc,
                )
                return None

    return None


# ============================================================
# Enviar mensaje de texto libre (dentro de ventana 24h)
# ============================================================

async def enviar_mensaje_texto(telefono: str, texto: str) -> str | None:
    """
    Envía un mensaje de texto libre a un número de WhatsApp.
    Solo funciona dentro de la ventana de 24h (el padre ya respondió).
    Retorna el wamid del mensaje enviado o None si falla.
    """
    if not PHONE_NUMBER_ID or not WHATSAPP_TOKEN:
        logger.error("Falta configuración de WhatsApp para enviar mensaje de texto")
        return None

    url = f"https://graph.facebook.com/{VERSION}/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": _normalizar_telefono(telefono),
        "type": "text",
        "text": {"body": texto},
    }

    telefono_norm = _normalizar_telefono(telefono)

    for intento in range(1, _MAX_RETRIES + 1):
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                response = await client.post(url, headers=headers, json=payload)

            if response.status_code != 200:
                logger.error("Error de Meta al enviar texto: %s", response.text)
                return None

            data = response.json()
            wamid = data["messages"][0]["id"]
            logger.info("Mensaje de texto enviado. wamid: %s", wamid)
            return wamid

        except _RETRIABLE_EXCEPTIONS as exc:
            if intento < _MAX_RETRIES:
                espera = _RETRY_BACKOFF_BASE * (2 ** (intento - 1))
                logger.warning(
                    "Intento %d/%d falló al enviar texto a %s: %s — reintentando en %.0fs",
                    intento, _MAX_RETRIES, telefono_norm, exc, espera,
                )
                await asyncio.sleep(espera)
            else:
                logger.error(
                    "Reintentos agotados (%d/%d) al enviar texto a %s: %s",
                    intento, _MAX_RETRIES, telefono_norm, exc,
                )
                return None

    return None


# ============================================================
# Descargar media desde la API de Meta
# ============================================================

async def descargar_media_whatsapp(media_id: str) -> tuple[bytes, str] | None:
    """
    Dado un media_id de Meta, descarga el archivo en 2 pasos:
    1. GET /{media_id} → obtiene la URL temporal del archivo
    2. GET {url_temporal} con Authorization → descarga los bytes

    Retorna (bytes, mime_type) o None si falla.
    """
    if not WHATSAPP_TOKEN:
        logger.error("Falta WHATSAPP_TOKEN para descargar media")
        return None

    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}

    for intento in range(1, _MAX_RETRIES + 1):
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                # Paso 1: obtener URL temporal
                meta_url = f"https://graph.facebook.com/{VERSION}/{media_id}"
                resp_meta = await client.get(meta_url, headers=headers)

                if resp_meta.status_code != 200:
                    logger.error("Error obteniendo URL de media %s: %s", media_id, resp_meta.text)
                    return None

                data = resp_meta.json()
                download_url = data.get("url")
                mime_type = data.get("mime_type", "image/jpeg")

                if not download_url:
                    logger.error("URL de descarga vacía para media %s", media_id)
                    return None

                # Paso 2: descargar los bytes
                resp_file = await client.get(download_url, headers=headers)

                if resp_file.status_code != 200:
                    logger.error("Error descargando media desde URL temporal: %s", resp_file.status_code)
                    return None

                return resp_file.content, mime_type

        except _RETRIABLE_EXCEPTIONS as exc:
            if intento < _MAX_RETRIES:
                espera = _RETRY_BACKOFF_BASE * (2 ** (intento - 1))
                logger.warning(
                    "Intento %d/%d falló al descargar media %s: %s — reintentando en %.0fs",
                    intento, _MAX_RETRIES, media_id, exc, espera,
                )
                await asyncio.sleep(espera)
            else:
                logger.error(
                    "Reintentos agotados (%d/%d) al descargar media %s: %s",
                    intento, _MAX_RETRIES, media_id, exc,
                )
                return None

    return None


# ============================================================
# Helpers internos
# ============================================================

def _obtener_telefono_responsable(db: SessionDep, id_alumno: int) -> str | None:
    """
    Busca el teléfono del primer responsable con celular registrado
    para el alumno dado. Devuelve el nro_celular tal cual está en la DB
    (el mismo formato que se usó al enviar la plantilla de inasistencia).
    """
    stmt = (
        select(Responsable.nro_celular)
        .join(Parentesco, Parentesco.idResponsable == Responsable.idResponsable)
        .where(
            Parentesco.idAlumno == id_alumno,
            Responsable.nro_celular != "",
        )
        .order_by(Parentesco.idResponsable)
        .limit(1)
    )
    return db.exec(stmt).first()


# ============================================================
# Procesar respuesta del padre (botón de motivo)
# ============================================================

async def procesar_respuesta_padre(wamid: str, motivo: str, telefono: str, db: SessionDep):
    """
    Recibe el identificador del mensaje de Meta y el motivo seleccionado por el tutor.
    Busca la inasistencia original y la actualiza en la base de datos.
    Si el motivo es 'Enfermedad', envía un mensaje pidiendo el certificado médico.

    Nota: `telefono` viene del campo "from" del webhook (WhatsApp ID del padre).
    Para enviar mensajes usamos el teléfono original de la DB (el mismo que se usó
    para la plantilla), evitando problemas de formato en modo test de Meta.
    """
    statement = select(Asistencia).where(Asistencia.wamid == wamid)
    inasistencia = db.exec(statement).first()

    if inasistencia:
        inasistencia.motivo_ausencia = motivo
        db.add(inasistencia)
        db.commit()

        print(f"✅ ÉXITO: Motivo '{motivo}' registrado para la asistencia ID: {inasistencia.idAlumno}")

        # Buscar el teléfono original del responsable en la DB
        # (el mismo formato que se usó para enviar la plantilla inicial)
        telefono_db = _obtener_telefono_responsable(db, inasistencia.idAlumno)
        telefono_destino = telefono_db or telefono  # fallback al del webhook

        # Si el motivo es Enfermedad, pedir certificado médico
        if motivo == "Enfermedad":
            wamid_texto = await enviar_mensaje_texto(
                telefono=telefono_destino,
                texto=(
                    "📋 Por favor, envíe una *foto del certificado médico* "
                    "como respuesta a este mensaje. ¡Gracias!"
                ),
            )
            if wamid_texto:
                print(f"📷 Solicitado certificado médico al número {telefono_destino}")
            else:
                print(f"❌ No se pudo enviar solicitud de certificado al número {telefono_destino}")
        else:
            # Para otros motivos, confirmar recepción
            wamid_texto = await enviar_mensaje_texto(
                telefono=telefono_destino,
                texto="✅ Recibido. ¡Gracias por informarnos!",
            )
            if wamid_texto:
                print(f"✅ Confirmación enviada al número {telefono_destino}")
            else:
                print(f"❌ No se pudo enviar confirmación al número {telefono_destino}")
    else:
        print(f"⚠️ WAMID recibido pero no se encontró la inasistencia en la BD: {wamid}")


# ============================================================
# Procesar imagen de certificado médico
# ============================================================

async def procesar_imagen_certificado(media_id: str, telefono: str, db: SessionDep):
    """
    Recibe un media_id de una imagen enviada por el padre.
    1. Busca la inasistencia más reciente con motivo 'Enfermedad' vinculada al teléfono
       que aún no tenga certificado (sin restricción de fecha).
    2. Descarga la imagen desde la API de Meta.
    3. La guarda en uploads/certificados/.
    4. Actualiza certificado_path y certificado_estado = 'pendiente' en la DB.
       → El estado 'pendiente' es la señal para que aparezca en la campanita del docente.
    """
    telefono_normalizado = _normalizar_telefono(telefono)

    stmt = (
        select(Asistencia)
        .join(Parentesco, Asistencia.idAlumno == Parentesco.idAlumno)
        .join(Responsable, Parentesco.idResponsable == Responsable.idResponsable)
        .where(
            and_(
                Asistencia.estado          == "Ausente",
                Asistencia.motivo_ausencia == "Enfermedad",
                Asistencia.certificado_path == None,
            )
        )
        .order_by(Asistencia.fecha.desc())
    )
    resultados = db.exec(stmt).all()

    inasistencia = None
    for row in resultados:
        stmt_tel = (
            select(Responsable.nro_celular)
            .join(Parentesco, Parentesco.idResponsable == Responsable.idResponsable)
            .where(Parentesco.idAlumno == row.idAlumno)
        )
        telefonos = db.exec(stmt_tel).all()
        for tel in telefonos:
            if _normalizar_telefono(tel) == telefono_normalizado:
                inasistencia = row
                break
        if inasistencia:
            break

    if not inasistencia:
        print(f"⚠️ Imagen recibida de {telefono} pero no se encontró inasistencia por enfermedad sin certificado")
        return

    resultado = await descargar_media_whatsapp(media_id)
    if not resultado:
        print(f"❌ No se pudo descargar la imagen con media_id: {media_id}")
        return

    contenido, mime_type = resultado
    extension = _MIME_TO_EXT.get(mime_type, "jpg")

    _UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{inasistencia.idCurso}_{inasistencia.idAlumno}_{inasistencia.fecha}.{extension}"
    filepath = _UPLOADS_DIR / filename
    filepath.write_bytes(contenido)

    # ✅ Guardar SOLO el nombre del archivo (no la ruta absoluta)
    inasistencia.certificado_path   = filename
    inasistencia.certificado_estado = "pendiente"
    db.add(inasistencia)
    db.commit()

    print(f"✅ Certificado médico guardado y marcado como pendiente: {filepath}")
    print(f"   Alumno ID: {inasistencia.idAlumno}, Curso: {inasistencia.idCurso}, Fecha: {inasistencia.fecha}")

    # Confirmar recepción del certificado al padre
    telefono_db = _obtener_telefono_responsable(db, inasistencia.idAlumno)
    telefono_destino = telefono_db or telefono  # fallback al del webhook
    wamid_conf = await enviar_mensaje_texto(
        telefono=telefono_destino,
        texto="✅ Certificado recibido. ¡Gracias!",
    )
    if wamid_conf:
        print(f"✅ Confirmación de certificado enviada al número {telefono_destino}")
    else:
        print(f"❌ No se pudo enviar confirmación de certificado al número {telefono_destino}")


