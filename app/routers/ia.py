import os
import json
import re
import requests
from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional

load_dotenv()

router = APIRouter(prefix="/ia", tags=["ia"])

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")


# ══════════════════════════════════════════════════════════════════════════════
# HELPER COMPARTIDO
# ══════════════════════════════════════════════════════════════════════════════

def _get_gemini_model(api_key: str) -> str:
    """Devuelve el nombre completo del modelo flash disponible."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    res = requests.get(url, timeout=10).json()
    modelos = [
        m["name"] for m in res.get("models", [])
        if "generateContent" in m.get("supportedGenerationMethods", [])
    ]
    if not modelos:
        raise Exception("No hay modelos de generación habilitados en esta API Key.")
    return next((m for m in modelos if "flash" in m), modelos[0])


# ══════════════════════════════════════════════════════════════════════════════
# ENDPOINT 1 — /ia/formalizar
# ══════════════════════════════════════════════════════════════════════════════

class FormalizarRequest(BaseModel):
    texto_informal: str


@router.post("/formalizar")
async def formalizar_texto(request: FormalizarRequest):
    if not GEMINI_API_KEY:
        raise HTTPException(status_code=500, detail="API Key no configurada en el servidor")

    try:
        full_model_name = _get_gemini_model(GEMINI_API_KEY)
        print(f"--- Usando modelo: {full_model_name} ---")

        url = f"https://generativelanguage.googleapis.com/v1beta/{full_model_name}:generateContent?key={GEMINI_API_KEY}"

        prompt_text = (
            f"Actúa como un Asistente Social escolar. Analiza la siguiente nota y devuelve un JSON estructurado.\n\n"
            f"Nota: '{request.texto_informal}'\n\n"
            f"Extrae y genera:\n"
            f"1. 'formalText': La nota redactada profesionalmente.\n"
            f"2. 'motivo': El motivo principal de la falta (ej: Salud, Familiar, etc.).\n"
            f"3. 'gravedad': Una escala de 'Baja', 'Media' o 'Alta'.\n"
            f"Responde ÚNICAMENTE el objeto JSON sin formato markdown."
        )

        payload = {"contents": [{"parts": [{"text": prompt_text}]}]}

        response = requests.post(url, json=payload, timeout=30)
        res_data = response.json()

        if response.status_code != 200:
            raise Exception(f"Error de Google: {res_data}")

        raw_text = res_data["candidates"][0]["content"]["parts"][0]["text"]
        clean_json = re.sub(r"```json\s?|```", "", raw_text).strip()

        return json.loads(clean_json)

    except Exception as e:
        print(f"DEBUG FINAL: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


class InformeResponse(BaseModel):
    informe: str    # Markdown listo para convertir a PDF en el frontend


# ══════════════════════════════════════════════════════════════════════════════
# ENDPOINT 3 — /ia/generar-informe-alerta
# ══════════════════════════════════════════════════════════════════════════════

class AccionAlerta(BaseModel):
    fecha: str
    tipo: str
    detalle: str
    actorNombre: Optional[str] = None
    actorRol: Optional[str] = None
    evento: Optional[str] = None
    estadoAnterior: Optional[str] = None
    estadoNuevo: Optional[str] = None


class AlertaResumen(BaseModel):
    """Resumen de una alerta anterior del mismo alumno para detectar patrones."""
    idAlerta: int
    motivo: str
    estado: str
    fechaCreacion: str
    curso: str
    consecutivas: int
    totalIntervenciones: int
    resuelta: bool


class GenerarInformeAlertaRequest(BaseModel):
    # Datos de la alerta actual
    idAlerta: int
    motivo: str
    estado: str
    fechaCreacion: str
    detalle: Optional[str] = None

    # Datos del alumno
    alumnoNombre: str
    alumnoDni: Optional[str] = None
    curso: str

    # Datos del responsable
    responsableNombre: Optional[str] = None
    responsableParentesco: Optional[str] = None
    responsableTelefono: Optional[str] = None

    # Historial de acciones de esta alerta
    acciones: list[AccionAlerta] = Field(default_factory=list)

    # Historial de TODAS las alertas del alumno (para patrones)
    historialAlertas: list[AlertaResumen] = Field(default_factory=list)

    # Metadatos de la escuela
    nombreEscuela: Optional[str] = None
    cue: Optional[str] = None
    nombreActor: Optional[str] = None


def _build_prompt_alerta(req: GenerarInformeAlertaRequest) -> str:
    import datetime as _dt
    escuela = req.nombreEscuela or (f"CUE {req.cue}" if req.cue else "Escuela")
    actor = req.nombreActor or "Personal escolar"
    hoy = _dt.date.today().isoformat()

    # Acciones de la alerta actual
    if req.acciones:
        lineas = []
        for a in req.acciones:
            if a.evento == "CAMBIO_ESTADO":
                lineas.append(f"  - [{a.fecha}] Cambio de estado: {a.estadoAnterior} → {a.estadoNuevo} (por {a.actorNombre or 'sistema'})")
            elif a.evento in ("ARCHIVADO", "DESARCHIVADO"):
                lineas.append(f"  - [{a.fecha}] {a.evento.capitalize()} por {a.actorNombre or 'sistema'}")
            elif a.evento == "CREACION_ALERTA":
                lineas.append(f"  - [{a.fecha}] Alerta creada")
            else:
                lineas.append(f"  - [{a.fecha}] {a.tipo}: {a.detalle} (por {a.actorNombre or a.actorRol or 'personal escolar'})")
        acciones_txt = "\n".join(lineas)
    else:
        acciones_txt = "  (Sin acciones registradas)"

    # Responsable
    responsable_txt = "No registrado"
    if req.responsableNombre:
        responsable_txt = req.responsableNombre
        if req.responsableParentesco:
            responsable_txt += f" ({req.responsableParentesco})"
        if req.responsableTelefono:
            responsable_txt += f" — Tel: {req.responsableTelefono}"

    # Historial de alertas previas del alumno (excluyendo la actual)
    alertas_previas = [h for h in req.historialAlertas if h.idAlerta != req.idAlerta]
    tiene_historial = bool(alertas_previas)

    if tiene_historial:
        lineas_h = []
        for h in alertas_previas:
            estado_str = "Resuelta" if h.resuelta else h.estado
            lineas_h.append(
                f"  - [{h.fechaCreacion}] Motivo: {h.motivo} | Estado: {estado_str} | "
                f"Curso: {h.curso} | Inasistencias/tardanzas: {h.consecutivas} | "
                f"Intervenciones: {h.totalIntervenciones}"
            )
        historial_txt = "\n".join(lineas_h)

        motivos = [h.motivo for h in alertas_previas]
        motivo_frecuente = max(set(motivos), key=motivos.count)
        resueltas = sum(1 for h in alertas_previas if h.resuelta)

        seccion_antecedentes = f"""ALERTAS PREVIAS DEL ALUMNO ({len(alertas_previas)} en total):
- Resueltas: {resueltas} de {len(alertas_previas)}
- Motivo más frecuente: {motivo_frecuente}
{historial_txt}"""
        titulo_antecedentes = "## ANTECEDENTES Y PATRONES"
        instruccion_antecedentes = "(Describí objetivamente lo que muestran los datos del historial. No agregues información que no esté aquí.)"
    else:
        seccion_antecedentes = "  (Sin alertas previas registradas para este alumno en esta escuela)"
        titulo_antecedentes = "## ANTECEDENTES"
        instruccion_antecedentes = "(Indicar que es la primera alerta del alumno.)"

    return f"""Sos un asistente escolar experto en redacción institucional formal.
Redactá un informe sobre la siguiente alerta escolar basándote ÚNICAMENTE en los datos provistos.
No inferras ni inventes información. Cada afirmación debe estar respaldada por los datos recibidos.

INSTRUCCIONES DE FORMATO:
- Usá Markdown con encabezados (#, ##, ###), listas con guión (-), negrita (**texto**) y separadores (---).
- El informe debe ser formal, claro y objetivo.
- Respondé ÚNICAMENTE con el Markdown del informe, sin bloques de código ni texto adicional.

DATOS DE LA ALERTA ACTUAL:
- Escuela: {escuela}
- Alumno: {req.alumnoNombre}
- DNI: {req.alumnoDni or 'No registrado'}
- Curso: {req.curso}
- Motivo: {req.motivo}
- Estado actual: {req.estado}
- Fecha de creación: {req.fechaCreacion}
- Observación inicial: {req.detalle or 'Sin observación'}

RESPONSABLE/FAMILIAR:
{responsable_txt}

INTERVENCIONES DE ESTA ALERTA:
{acciones_txt}

{seccion_antecedentes}

ESTRUCTURA ESPERADA:
# INFORME DE ALERTA ESCOLAR — {escuela}
(metadatos: alumno, curso, fecha emisión, generado por)

---

## DESCRIPCIÓN DE LA SITUACIÓN
(narrativa del motivo y estado actual)

## INTERVENCIONES REGISTRADAS
(resumen de las acciones de esta alerta, con fechas y actores. Si no hay, indicarlo.)

{titulo_antecedentes}
{instruccion_antecedentes}

## OBSERVACIONES
(síntesis objetiva del caso)

---

_Informe generado el {hoy} por {actor}_
"""


@router.post("/generar-informe-alerta", response_model=InformeResponse)
def generar_informe_alerta(req: GenerarInformeAlertaRequest):
    if not GEMINI_API_KEY:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY no configurada.")

    try:
        model_name = _get_gemini_model(GEMINI_API_KEY)
        print(f"--- Generando informe de alerta con modelo: {model_name} ---")

        url = f"https://generativelanguage.googleapis.com/v1beta/{model_name}:generateContent?key={GEMINI_API_KEY}"
        prompt = _build_prompt_alerta(req)

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.3,
                "maxOutputTokens": 4096,
            }
        }

        response = requests.post(url, json=payload, timeout=60)
        res_data = response.json()

        if response.status_code != 200:
            raise Exception(f"Error de Google API: {res_data}")

        raw_text = res_data["candidates"][0]["content"]["parts"][0]["text"]

        informe_md = re.sub(r"^```(?:markdown)?\s*", "", raw_text.strip())
        informe_md = re.sub(r"\s*```$", "", informe_md.strip())

        return InformeResponse(informe=informe_md)

    except HTTPException:
        raise
    except Exception as e:
        print(f"ERROR generar_informe_alerta: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# ══════════════════════════════════════════════════════════════════════════════
# ENDPOINT 4 — /ia/generar-informe-completo-alumno
# ══════════════════════════════════════════════════════════════════════════════

class AlertaCompletaItem(BaseModel):
    idAlerta: int
    motivo: str
    estado: str
    fechaCreacion: str
    curso: str
    consecutivas: int
    detalle: Optional[str] = None
    resuelta: bool
    archivada: bool
    intervenciones: list[AccionAlerta] = Field(default_factory=list)


class GenerarInformeCompletoAlumnoRequest(BaseModel):
    alumnoNombre: str
    alumnoDni: Optional[str] = None
    responsableNombre: Optional[str] = None
    responsableParentesco: Optional[str] = None
    responsableTelefono: Optional[str] = None
    alertas: list[AlertaCompletaItem] = Field(default_factory=list)
    nombreEscuela: Optional[str] = None
    cue: Optional[str] = None
    nombreActor: Optional[str] = None


def _build_prompt_completo_alumno(req: GenerarInformeCompletoAlumnoRequest) -> str:
    import datetime as _dt
    escuela   = req.nombreEscuela or (f"CUE {req.cue}" if req.cue else "Escuela")
    actor     = req.nombreActor or "Personal escolar"
    hoy       = _dt.date.today().isoformat()

    responsable_txt = "No registrado"
    if req.responsableNombre:
        responsable_txt = req.responsableNombre
        if req.responsableParentesco:
            responsable_txt += f" ({req.responsableParentesco})"
        if req.responsableTelefono:
            responsable_txt += f" — Tel: {req.responsableTelefono}"

    # Construir bloque de cada alerta con sus intervenciones
    alertas_ordenadas = sorted(req.alertas, key=lambda a: a.fechaCreacion)
    alertas_txt_partes = []

    for i, alerta in enumerate(alertas_ordenadas, 1):
        estado_str = "Resuelta" if alerta.resuelta else alerta.estado
        archivada_str = " (archivada)" if alerta.archivada else ""

        header = (
            f"### Alerta {i} — {alerta.motivo}\n"
            f"- Fecha: {alerta.fechaCreacion}\n"
            f"- Curso: {alerta.curso}\n"
            f"- Estado: {estado_str}{archivada_str}\n"
            f"- Inasistencias/tardanzas registradas: {alerta.consecutivas}\n"
        )
        if alerta.detalle:
            header += f"- Observación: {alerta.detalle}\n"

        if alerta.intervenciones:
            lineas_iv = []
            for iv in alerta.intervenciones:
                if iv.evento == "CAMBIO_ESTADO":
                    lineas_iv.append(
                        f"  - [{iv.fecha}] Cambio de estado: {iv.estadoAnterior} → {iv.estadoNuevo}"
                        f" (por {iv.actorNombre or 'sistema'})"
                    )
                elif iv.evento in ("ARCHIVADO", "DESARCHIVADO"):
                    lineas_iv.append(
                        f"  - [{iv.fecha}] {iv.evento.capitalize()} por {iv.actorNombre or 'sistema'}"
                    )
                elif iv.evento == "CREACION_ALERTA":
                    lineas_iv.append(f"  - [{iv.fecha}] Alerta creada")
                else:
                    lineas_iv.append(
                        f"  - [{iv.fecha}] {iv.tipo}: {iv.detalle}"
                        f" (por {iv.actorNombre or iv.actorRol or 'personal escolar'})"
                    )
            iv_txt = "\n".join(lineas_iv)
            intervenciones_block = f"Intervenciones:\n{iv_txt}"
        else:
            intervenciones_block = "Intervenciones: (Sin intervenciones registradas)"

        alertas_txt_partes.append(header + intervenciones_block)

    alertas_txt = "\n\n".join(alertas_txt_partes)

    # Datos para sección de patrones
    total = len(req.alertas)
    resueltas = sum(1 for a in req.alertas if a.resuelta)
    motivos = [a.motivo for a in req.alertas]
    motivo_frecuente = max(set(motivos), key=motivos.count) if motivos else "N/A"
    criticas = sum(1 for a in req.alertas if "CRITI" in a.estado.upper() or "CRÍTI" in a.estado.upper())

    return f"""Sos un asistente escolar experto en redacción institucional formal.
Redactá un informe completo sobre el historial de alertas del alumno, basándote ÚNICAMENTE en los datos provistos.
No inferras ni inventes información. Cada afirmación debe estar respaldada por los datos recibidos.

INSTRUCCIONES DE FORMATO:
- Usá Markdown: encabezados (#, ##, ###), listas (-), negrita (**texto**), separadores (---).
- El informe debe ser formal, claro y objetivo.
- Respondé ÚNICAMENTE con el Markdown del informe, sin bloques de código ni texto adicional.

DATOS DEL ALUMNO:
- Nombre: {req.alumnoNombre}
- DNI: {req.alumnoDni or 'No registrado'}
- Escuela: {escuela}
- Responsable/Familiar: {responsable_txt}

RESUMEN ESTADÍSTICO:
- Total de alertas: {total}
- Alertas resueltas: {resueltas} de {total}
- Alertas críticas: {criticas}
- Motivo más frecuente: {motivo_frecuente}

HISTORIAL DETALLADO DE ALERTAS (orden cronológico):
{alertas_txt}

ESTRUCTURA ESPERADA DEL INFORME:
# INFORME DE HISTORIAL DE ALERTAS — {req.alumnoNombre}
(metadatos: escuela, responsable, fecha de emisión, generado por)

---

## HISTORIAL DE ALERTAS
(Para cada alerta: redactá un párrafo narrativo con fecha, motivo, estado y un resumen de las intervenciones.
 Seguí el orden cronológico. No copies los datos en crudo, redactalos en prosa formal.)

## ANÁLISIS DE PATRONES
(Basándote en los datos estadísticos y el historial, describí objetivamente:
 frecuencia de alertas, motivos recurrentes, evolución del estado, efectividad de las intervenciones.
 Solo lo que se desprende de los datos. Sin suposiciones.)

## OBSERVACIONES FINALES
(Síntesis objetiva del estado actual del alumno según el historial)

---

_Informe generado el {hoy} por {actor}_
"""


@router.post("/generar-informe-completo-alumno", response_model=InformeResponse)
def generar_informe_completo_alumno(req: GenerarInformeCompletoAlumnoRequest):
    if not GEMINI_API_KEY:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY no configurada.")

    try:
        model_name = _get_gemini_model(GEMINI_API_KEY)
        print(f"--- Generando informe completo alumno con modelo: {model_name} ---")

        url = f"https://generativelanguage.googleapis.com/v1beta/{model_name}:generateContent?key={GEMINI_API_KEY}"
        prompt = _build_prompt_completo_alumno(req)

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 8192,
            }
        }

        response = requests.post(url, json=payload, timeout=90)
        res_data = response.json()

        if response.status_code != 200:
            raise Exception(f"Error de Google API: {res_data}")

        raw_text = res_data["candidates"][0]["content"]["parts"][0]["text"]
        informe_md = re.sub(r"^```(?:markdown)?\s*", "", raw_text.strip())
        informe_md = re.sub(r"\s*```$", "", informe_md.strip())

        return InformeResponse(informe=informe_md)

    except HTTPException:
        raise
    except Exception as e:
        print(f"ERROR generar_informe_completo_alumno: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


