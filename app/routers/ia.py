import os
import json
import re
import requests
from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional
from collections import Counter, defaultdict
from datetime import date as _date
import datetime as _dt

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


# ENDPOINT: /ia/generar-informe-asistencia-alumno
# ─── Schemas ────────────────────────────────────────────────────────────────
 
class RegistroAsistencia(BaseModel):
    """Un registro crudo del alumno (un día)."""
    fecha: str                    # "2025-03-14"
    estado: str                   # Presente | Ausente | Tarde | Justificado
    lluvia: Optional[bool] = None
    motivo_ausencia: Optional[str] = None
 
 
class PeriodoResumen(BaseModel):
    """Resumen pre-calculado de un período (el frontend ya lo tiene)."""
    key: str                      # "T1" | "T2" | "T3" | "ANUAL"
    label: str                    # "Primer Trimestre"
    desde: str
    hasta: str
    diasHabiles: int
    ausencias: int
    tardanzas: int
    justificados: int
    porcentajeAsistencia: float
 
 
class GenerarInformeAsistenciaAlumnoRequest(BaseModel):
    # Datos del alumno
    alumnoNombre: str
    alumnoDni: Optional[str] = None
    curso: str
    cicloLectivo: int
 
    # Datos del responsable
    responsableNombre: Optional[str] = None
    responsableParentesco: Optional[str] = None
 
    # Período solicitado
    periodoKey: str               # "T1" | "T2" | "T3" | "ANUAL"
    periodoLabel: str
    periodoDesde: str
    periodoHasta: str
 
    # Registros crudos del período (ya filtrados por el frontend)
    registros: list[RegistroAsistencia] = Field(default_factory=list)
 
    # Resúmenes de todos los períodos del ciclo (para comparativa)
    periodosResumen: list[PeriodoResumen] = Field(default_factory=list)
 
    # Destinatario del informe
    destinatario: str             # "familia" | "directivos" | "docente"
 
    # Metadatos
    nombreEscuela: Optional[str] = None
    cue: Optional[str] = None
    nombreActor: Optional[str] = None
 
 
# ─── Análisis de patrones (Python puro, no IA) ──────────────────────────────
 
def _analizar_patrones(registros: list[RegistroAsistencia]) -> dict:
    """
    Extrae patrones de los registros crudos antes de pasarlos a Gemini.
    Esto reduce tokens y garantiza que los patrones sean exactos.
    """
    ausencias = [r for r in registros if r.estado == "Ausente"]
    tardanzas = [r for r in registros if r.estado == "Tarde"]
 
    # Días de la semana con más ausencias
    dias_es = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes"]
    dias_ausencias = Counter()
    for r in ausencias:
        try:
            wd = _dt.date.fromisoformat(r.fecha).weekday()  # 0=Lunes
            if 0 <= wd <= 4:
                dias_ausencias[dias_es[wd]] += 1
        except Exception:
            pass
 
    dia_mas_frecuente = dias_ausencias.most_common(1)[0] if dias_ausencias else None
 
    # Rachas consecutivas de ausencias
    fechas_ausencia = sorted(set(r.fecha for r in ausencias))
    rachas = []
    if fechas_ausencia:
        inicio = fechas_ausencia[0]
        prev = _dt.date.fromisoformat(fechas_ausencia[0])
        racha_actual = [fechas_ausencia[0]]
 
        for f in fechas_ausencia[1:]:
            curr = _dt.date.fromisoformat(f)
            diff = (curr - prev).days
            if diff <= 3:  # hasta 3 días de diferencia (fin de semana)
                racha_actual.append(f)
            else:
                if len(racha_actual) >= 3:
                    rachas.append({"inicio": racha_actual[0], "fin": racha_actual[-1], "dias": len(racha_actual)})
                racha_actual = [f]
            prev = curr
 
        if len(racha_actual) >= 3:
            rachas.append({"inicio": racha_actual[0], "fin": racha_actual[-1], "dias": len(racha_actual)})
 
    racha_maxima = max((r["dias"] for r in rachas), default=0)
 
    # Ausencias por mes
    por_mes = Counter()
    for r in ausencias:
        try:
            mes = _dt.date.fromisoformat(r.fecha).strftime("%B %Y")
            por_mes[mes] += 1
        except Exception:
            pass
 
    mes_critico = por_mes.most_common(1)[0] if por_mes else None
 
    # Motivos declarados
    motivos = [r.motivo_ausencia for r in ausencias if r.motivo_ausencia]
    motivos_frecuentes = Counter(motivos).most_common(3)
 
    # Distribución ausencias/tardanzas
    total_registros = len(registros)
    total_ausencias = len(ausencias)
    total_tardanzas = len(tardanzas)
    total_justificados = sum(1 for r in registros if r.estado == "Justificado")
 
    return {
        "total_registros": total_registros,
        "total_ausencias": total_ausencias,
        "total_tardanzas": total_tardanzas,
        "total_justificados": total_justificados,
        "dias_semana_ausencias": dict(dias_ausencias),
        "dia_mas_frecuente": dia_mas_frecuente,
        "rachas_consecutivas": rachas,
        "racha_maxima": racha_maxima,
        "ausencias_por_mes": dict(por_mes),
        "mes_critico": mes_critico,
        "motivos_declarados": motivos_frecuentes,
    }
 
 
# ─── Constructor del prompt ──────────────────────────────────────────────────
 
def _build_prompt_asistencia(req: GenerarInformeAsistenciaAlumnoRequest) -> str:
    hoy = _dt.date.today().isoformat()
    escuela = req.nombreEscuela or (f"CUE {req.cue}" if req.cue else "Escuela")
    actor = req.nombreActor or "Personal escolar"
    patrones = _analizar_patrones(req.registros)
 
    # ── Tono según destinatario ──────────────────────────────────────────────
    tonos = {
        "familia": (
            "Escribí en un tono cálido, claro y comprensivo. "
            "Evitá tecnicismos. Usá frases como 'queremos acompañar a su hijo/a' y 'estamos a disposición'. "
            "El objetivo es informar y abrir el diálogo, no alarmar ni culpabilizar."
        ),
        "directivos": (
            "Escribí en tono institucional y analítico. "
            "Incluí porcentajes, patrones detectados y su impacto potencial en la trayectoria escolar. "
            "El objetivo es brindar una visión objetiva para la toma de decisiones."
        ),
        "docente": (
            "Escribí en tono profesional y directo entre colegas. "
            "Destacá patrones concretos y sugerí cuándo podría ser útil una intervención o seguimiento. "
            "El objetivo es que el docente tenga el contexto completo del alumno."
        ),
    }
    instruccion_tono = tonos.get(req.destinatario, tonos["directivos"])
 
    # ── Resumen de períodos para comparativa ────────────────────────────────
    if req.periodosResumen:
        lineas_periodos = []
        for p in req.periodosResumen:
            lineas_periodos.append(
                f"  - {p.label}: {p.ausencias} ausencias, {p.tardanzas} tardanzas, "
                f"{p.justificados} justificadas → {p.porcentajeAsistencia}% asistencia ({p.diasHabiles} días hábiles)"
            )
        comparativa_txt = "\n".join(lineas_periodos)
    else:
        comparativa_txt = "  (Sin datos comparativos de otros períodos)"
 
    # ── Rachas ──────────────────────────────────────────────────────────────
    if patrones["rachas_consecutivas"]:
        rachas_txt = ", ".join(
            f"{r['dias']} días seguidos ({r['inicio']} al {r['fin']})"
            for r in patrones["rachas_consecutivas"]
        )
    else:
        rachas_txt = "Sin rachas de 3 o más días consecutivos detectadas"
 
    # ── Día más frecuente ────────────────────────────────────────────────────
    dia_freq_txt = (
        f"{patrones['dia_mas_frecuente'][0]} ({patrones['dia_mas_frecuente'][1]} ausencias)"
        if patrones["dia_mas_frecuente"]
        else "Sin patrón claro por día de la semana"
    )
 
    # ── Mes crítico ──────────────────────────────────────────────────────────
    mes_critico_txt = (
        f"{patrones['mes_critico'][0]} ({patrones['mes_critico'][1]} ausencias)"
        if patrones["mes_critico"]
        else "Sin mes crítico identificado"
    )
 
    # ── Motivos declarados ───────────────────────────────────────────────────
    if patrones["motivos_declarados"]:
        motivos_txt = ", ".join(f'"{m}" ({c} vez{"" if c == 1 else "es"})' for m, c in patrones["motivos_declarados"])
    else:
        motivos_txt = "Sin motivos declarados registrados"
 
    # ── Estructuras del informe según destinatario ───────────────────────────
    estructuras = {
        "familia": """
# COMUNICADO DE ASISTENCIA ESCOLAR
## {escuela}
(nombre del alumno, curso, período, fecha de emisión)
 
---
 
## Estimada familia de {alumno}
 
(Párrafo inicial cálido que explica el motivo del comunicado.)
 
## Situación de asistencia en {periodo}
(Explicar en lenguaje simple: cuántos días faltó, cuántos tardó, qué porcentaje asistió.
 Comparar brevemente con otros períodos si hay datos. Mencionar si hay rachas o patrones preocupantes,
 sin alarmismo.)
 
## Lo que observamos
(Describir el patrón más relevante —si lo hay— de forma comprensiva.
 Ej: "notamos que las ausencias se concentran en..." Solo si los datos lo muestran.)
 
## Próximos pasos
(Invitar al diálogo. Mencionar que la escuela está a disposición.
 Si la situación es crítica, sugerir una reunión. Tono siempre propositivo.)
 
---
_Emitido el {hoy} — {escuela}_
""",
        "directivos": """
# INFORME DE ASISTENCIA — {alumno}
## {escuela} | Ciclo {ciclo}
(curso, período analizado, fecha de emisión, generado por)
 
---
 
## RESUMEN EJECUTIVO
(2-3 líneas con los datos más relevantes: % asistencia, ausencias totales, estado de alerta.)
 
## DATOS DEL PERÍODO ANALIZADO
(Tabla narrativa: días hábiles, presencias, ausencias, tardanzas, justificadas, % asistencia.)
 
## COMPARATIVA POR PERÍODOS
(Si hay datos de otros trimestres: evolución del porcentaje. ¿Mejoró? ¿Empeoró? ¿Estable?)
 
## ANÁLISIS DE PATRONES
(Día de semana predominante, rachas consecutivas, mes crítico. Solo si los datos los muestran.
 Cada patrón con su dato concreto.)
 
## OBSERVACIONES
(Síntesis objetiva. ¿Requiere seguimiento? ¿Intervención del equipo de orientación?)
 
---
_Informe generado el {hoy} por {actor}_
""",
        "docente": """
# REPORTE DE ASISTENCIA — {alumno}
## {curso} | {periodo}
(datos rápidos: escuela, ciclo, fecha)
 
---
 
## RESUMEN DEL PERÍODO
(Datos concretos: ausencias, tardanzas, justificadas, % asistencia, días hábiles.)
 
## COMPARATIVA CON OTROS PERÍODOS
(Si hay datos: cómo evolucionó respecto a trimestres anteriores.)
 
## PATRONES DETECTADOS
(Día de semana, rachas, concentración mensual. Con números exactos.
 Si no hay patrones claros, indicarlo.)
 
## CONTEXTO ADICIONAL
(Motivos declarados si los hay. Relación lluvia/ausencias si es relevante.)
 
## SUGERENCIAS PARA SEGUIMIENTO
(Breve: ¿Cuándo conviene hacer un seguimiento? ¿Hablar con la familia?
 Solo si los datos lo justifican. Tono de colega, no de protocolo.)
 
---
_Reporte generado el {hoy}_
""",
    }
 
    estructura = estructuras.get(req.destinatario, estructuras["directivos"])
 
    return f"""Sos un asistente escolar experto en redacción institucional.
Redactá un informe de asistencia escolar basándote ÚNICAMENTE en los datos provistos.
No inferras causas ni inventes información. Cada afirmación debe surgir de los datos.
 
TONO Y ESTILO:
{instruccion_tono}
 
INSTRUCCIONES DE FORMATO:
- Usá Markdown: encabezados (#, ##), listas (-), negrita (**texto**), separadores (---).
- Respondé ÚNICAMENTE con el Markdown del informe, sin bloques de código ni texto adicional.
- Completá los paréntesis de la estructura con la narrativa correspondiente. No los dejes como placeholder.
 
DATOS DEL ALUMNO:
- Nombre: {req.alumnoNombre}
- DNI: {req.alumnoDni or 'No registrado'}
- Curso: {req.curso}
- Responsable: {req.responsableNombre or 'No registrado'}{f' ({req.responsableParentesco})' if req.responsableParentesco else ''}
- Escuela: {escuela}
- Ciclo lectivo: {req.cicloLectivo}
 
PERÍODO ANALIZADO:
- Período: {req.periodoLabel} ({req.periodoKey})
- Desde: {req.periodoDesde} | Hasta: {req.periodoHasta}
 
ESTADÍSTICAS DEL PERÍODO:
- Días con registro: {patrones['total_registros']}
- Ausencias: {patrones['total_ausencias']}
- Tardanzas: {patrones['total_tardanzas']}
- Justificadas: {patrones['total_justificados']}
 
PATRONES DETECTADOS (calculados sobre los registros crudos):
- Día de semana con más ausencias: {dia_freq_txt}
- Ausencias por mes: {dict(patrones['ausencias_por_mes']) or 'Sin datos'}
- Mes con más ausencias: {mes_critico_txt}
- Rachas consecutivas (≥3 días): {rachas_txt}
- Racha máxima: {patrones['racha_maxima']} días
- Motivos declarados por la familia (vía WhatsApp): {motivos_txt}
 
COMPARATIVA POR PERÍODOS DEL CICLO {req.cicloLectivo}:
{comparativa_txt}
 
ESTRUCTURA ESPERADA DEL INFORME (completá los paréntesis con narrativa real):
{estructura}
"""
 
 
# ─── Endpoint ────────────────────────────────────────────────────────────────
 
@router.post("/generar-informe-asistencia-alumno", response_model=InformeResponse)
def generar_informe_asistencia_alumno(req: GenerarInformeAsistenciaAlumnoRequest):
    """
    Genera un informe de asistencia personalizado para un alumno.
    Acepta registros crudos día a día y produce un Markdown adaptado
    al destinatario (familia / directivos / docente).
    """
    if not GEMINI_API_KEY:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY no configurada.")
 
    try:
        model_name = _get_gemini_model(GEMINI_API_KEY)
        print(f"--- Generando informe de asistencia con modelo: {model_name} ---")
 
        url = f"https://generativelanguage.googleapis.com/v1beta/{model_name}:generateContent?key={GEMINI_API_KEY}"
        prompt = _build_prompt_asistencia(req)
 
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.35,
                "maxOutputTokens": 4096,
            },
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
        print(f"ERROR generar_informe_asistencia_alumno: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    

# ENDPOINT: /ia/generar-informe-curso
# ─── Schemas ────────────────────────────────────────────────────────────────

class AlumnoResumenCurso(BaseModel):
    """Resumen de un alumno dentro del informe de curso."""
    idAlumno:             int
    apellido:             str
    nombre:               str
    diasHabiles:          int
    ausencias:            int
    tardanzas:            int
    porcentajeAsistencia: float
    alerta:               str   # "ok" | "warning" | "danger"


class GenerarInformeCursoRequest(BaseModel):
    # Datos del curso
    cursoNombre:   str
    cicloLectivo:  int

    # Período analizado
    periodoKey:    str
    periodoLabel:  str
    periodoDesde:  str
    periodoHasta:  str

    # Resúmenes de alumnos (filasFiltradas del frontend)
    alumnos:       list[AlumnoResumenCurso] = Field(default_factory=list)

    # Destinatario
    destinatario:  str   # "familia" | "directivos" | "docente"

    # Metadatos
    nombreEscuela: Optional[str] = None
    cue:           Optional[str] = None
    nombreActor:   Optional[str] = None


# ─── Análisis estadístico del curso ───────────────────────────

def _analizar_curso(alumnos: list[AlumnoResumenCurso]) -> dict:
    """Calcula estadísticas del grupo antes de pasarlas a Gemini."""
    if not alumnos:
        return {}

    total = len(alumnos)
    ok      = [a for a in alumnos if a.alerta == "ok"]
    warning = [a for a in alumnos if a.alerta == "warning"]
    danger  = [a for a in alumnos if a.alerta == "danger"]

    porcentajes  = [a.porcentajeAsistencia for a in alumnos]
    promedio     = round(sum(porcentajes) / total, 1)
    minimo       = min(porcentajes)
    maximo       = max(porcentajes)

    total_ausencias = sum(a.ausencias for a in alumnos)
    total_tardanzas = sum(a.tardanzas for a in alumnos)

    # Alumno con más ausencias
    peor = max(alumnos, key=lambda a: a.ausencias)

    # Alumno con mejor asistencia (entre los que tienen registros)
    mejor = max(alumnos, key=lambda a: a.porcentajeAsistencia)

    # Top 5 en riesgo (danger primero, luego warning, por ausencias desc)
    en_riesgo = sorted(
        danger + warning,
        key=lambda a: (-a.ausencias, a.porcentajeAsistencia)
    )[:5]

    # Días hábiles (todos deberían tener el mismo valor)
    dias_habiles = alumnos[0].diasHabiles if alumnos else 0

    return {
        "total_alumnos":    total,
        "dias_habiles":     dias_habiles,
        "regulares":        len(ok),
        "atencion":         len(warning),
        "riesgo":           len(danger),
        "pct_regulares":    round(len(ok)      / total * 100, 1),
        "pct_atencion":     round(len(warning) / total * 100, 1),
        "pct_riesgo":       round(len(danger)  / total * 100, 1),
        "promedio_asistencia": promedio,
        "minimo_asistencia":   round(minimo, 1),
        "maximo_asistencia":   round(maximo, 1),
        "total_ausencias":     total_ausencias,
        "total_tardanzas":     total_tardanzas,
        "promedio_ausencias":  round(total_ausencias / total, 1),
        "alumno_mas_ausencias": f"{peor.apellido}, {peor.nombre} ({peor.ausencias} ausencias, {peor.porcentajeAsistencia}%)",
        "alumno_mejor_asistencia": f"{mejor.apellido}, {mejor.nombre} ({mejor.porcentajeAsistencia}%)",
        "alumnos_en_riesgo": [
            f"{a.apellido}, {a.nombre} — {a.ausencias} ausencias ({a.porcentajeAsistencia}%)"
            for a in en_riesgo
        ],
    }


# ─── Constructor del prompt ──────────────────────────────────────────────────

def _build_prompt_curso(req: GenerarInformeCursoRequest) -> str:
    import datetime as _dt
    hoy    = _dt.date.today().isoformat()
    escuela = req.nombreEscuela or (f"CUE {req.cue}" if req.cue else "Escuela")
    actor   = req.nombreActor or "Personal escolar"
    stats   = _analizar_curso(req.alumnos)

    # ── Tono según destinatario ──────────────────────────────────────────────
    tonos = {
        "familia": (
            "Escribí en tono claro, accesible y constructivo. "
            "El objetivo es informar a las familias sobre la situación general del curso, "
            "sin exponer datos individuales de otros alumnos. "
            "Usá lenguaje positivo y propositivo."
        ),
        "directivos": (
            "Escribí en tono institucional y analítico. "
            "Incluí todos los indicadores estadísticos, identificá los alumnos en riesgo por nombre "
            "y sugerí acciones concretas de intervención. "
            "El objetivo es dar una visión completa para la toma de decisiones."
        ),
        "docente": (
            "Escribí en tono profesional y directo entre colegas. "
            "Destacá los alumnos que requieren seguimiento con sus datos concretos. "
            "Incluí una sección de sugerencias prácticas para el aula. "
            "El objetivo es que el docente tenga el panorama completo del grupo."
        ),
    }
    instruccion_tono = tonos.get(req.destinatario, tonos["directivos"])

    # ── Lista de alumnos en riesgo para el prompt ────────────────────────────
    riesgo_txt = "\n".join(f"  - {r}" for r in stats.get("alumnos_en_riesgo", []))
    if not riesgo_txt:
        riesgo_txt = "  (Ningún alumno en riesgo o atención)"

    # ── Distribución completa del curso ─────────────────────────────────────
    alumnos_ordenados = sorted(req.alumnos, key=lambda a: a.porcentajeAsistencia)
    dist_txt = "\n".join(
        f"  - {a.apellido}, {a.nombre}: {a.ausencias} ausencias, "
        f"{a.tardanzas} tardanzas → {a.porcentajeAsistencia}% "
        f"({'RIESGO' if a.alerta == 'danger' else 'ATENCIÓN' if a.alerta == 'warning' else 'Regular'})"
        for a in alumnos_ordenados
    )

    # ── Estructuras según destinatario ───────────────────────────────────────
    estructuras = {
        "familia": f"""
# INFORME DE ASISTENCIA — {req.cursoNombre}
## {escuela} | {req.periodoLabel} {req.cicloLectivo}
(fecha de emisión)

---

## SITUACIÓN GENERAL DEL CURSO
(Describí en lenguaje accesible la asistencia promedio del grupo.
 Mencioná cuántos alumnos asisten regularmente. Tono positivo.)

## ASPECTOS A MEJORAR
(Si hay alumnos en riesgo o atención, mencionalo de forma genérica
 — sin nombres — e invitá a las familias a estar atentas y en contacto con la escuela.)

## COMPROMISOS DE LA ESCUELA
(Breve párrafo indicando que la escuela hace seguimiento y está disponible.)

---
_Informe generado el {hoy} — {escuela}_
""",
        "directivos": f"""
# INFORME DE ASISTENCIA — {req.cursoNombre}
## {escuela} | {req.periodoLabel} {req.cicloLectivo}
(docente/actor, fecha de emisión)

---

## RESUMEN EJECUTIVO
(2-3 líneas con los datos más importantes: promedio, % en riesgo, estado general.)

## INDICADORES DEL PERÍODO
(Narrativa con todos los datos estadísticos: días hábiles, promedio de asistencia,
 distribución por estado, total de ausencias y tardanzas del grupo.)

## ALUMNOS QUE REQUIEREN INTERVENCIÓN
(Lista con nombre, ausencias y porcentaje de cada alumno en riesgo o atención.
 Ordenados por gravedad. Solo si los datos lo muestran.)

## ANÁLISIS Y OBSERVACIONES
(Síntesis objetiva del estado del curso. ¿Es una situación crítica, normal, buena?
 ¿Hay algún patrón llamativo en los datos?)

## ACCIONES SUGERIDAS
(2-3 acciones concretas basadas en los datos. Solo si los datos lo justifican.)

---
_Informe generado el {hoy} por {actor}_
""",
        "docente": f"""
# REPORTE DE ASISTENCIA — {req.cursoNombre}
## {req.periodoLabel} {req.cicloLectivo}
(escuela, fecha)

---

## RESUMEN DEL GRUPO
(Datos concretos: total alumnos, días hábiles, promedio asistencia,
 distribución regular/atención/riesgo.)

## ALUMNOS EN SEGUIMIENTO
(Para cada alumno en riesgo o atención: nombre, ausencias, %, estado.
 Tono de colega — datos directos sin rodeos.)

## PANORAMA GENERAL
(¿Cómo está el grupo en general? ¿Mejoró, empeoró, estable?
 Solo lo que los datos muestran.)

## SUGERENCIAS
(Breves acciones prácticas para el aula o para hablar con familias específicas.
 Solo si los datos lo justifican.)

---
_Reporte generado el {hoy}_
""",
    }

    estructura = estructuras.get(req.destinatario, estructuras["directivos"])

    return f"""Sos un asistente escolar experto en redacción institucional.
Redactá un informe de asistencia de un curso completo basándote ÚNICAMENTE en los datos provistos.
No inferras ni inventes información. Cada afirmación debe estar respaldada por los datos.

TONO Y ESTILO:
{instruccion_tono}

INSTRUCCIONES DE FORMATO:
- Usá Markdown: encabezados (#, ##), listas (-), negrita (**texto**), separadores (---).
- Respondé ÚNICAMENTE con el Markdown del informe, sin bloques de código ni texto adicional.
- Completá los paréntesis de la estructura con narrativa real, no los dejes como placeholder.

DATOS DEL CURSO:
- Curso: {req.cursoNombre}
- Escuela: {escuela}
- Ciclo lectivo: {req.cicloLectivo}
- Período: {req.periodoLabel} ({req.periodoDesde} al {req.periodoHasta})

ESTADÍSTICAS DEL GRUPO:
- Total de alumnos: {stats.get('total_alumnos', 0)}
- Días hábiles en el período: {stats.get('dias_habiles', 0)}
- Promedio de asistencia: {stats.get('promedio_asistencia', 0)}%
- Mínimo: {stats.get('minimo_asistencia', 0)}% | Máximo: {stats.get('maximo_asistencia', 0)}%
- Regulares (≥80%): {stats.get('regulares', 0)} alumnos ({stats.get('pct_regulares', 0)}%)
- En atención (70-79%): {stats.get('atencion', 0)} alumnos ({stats.get('pct_atencion', 0)}%)
- En riesgo (<70%): {stats.get('riesgo', 0)} alumnos ({stats.get('pct_riesgo', 0)}%)
- Total ausencias del grupo: {stats.get('total_ausencias', 0)}
- Total tardanzas del grupo: {stats.get('total_tardanzas', 0)}
- Promedio de ausencias por alumno: {stats.get('promedio_ausencias', 0)}
- Alumno con más ausencias: {stats.get('alumno_mas_ausencias', 'N/A')}
- Mejor asistencia: {stats.get('alumno_mejor_asistencia', 'N/A')}

ALUMNOS EN RIESGO O ATENCIÓN (para destinatario directivos/docente):
{riesgo_txt}

DISTRIBUCIÓN COMPLETA DEL CURSO (orden por asistencia ascendente):
{dist_txt}

ESTRUCTURA ESPERADA:
{estructura}
"""


# ─── Endpoint ────────────────────────────────────────────────────────────────

@router.post("/generar-informe-curso", response_model=InformeResponse)
def generar_informe_curso(req: GenerarInformeCursoRequest):
    """
    Genera un informe de asistencia para un curso completo.
    Recibe el resumen ya calculado por el frontend (filasFiltradas)
    y produce un Markdown adaptado al destinatario.
    """
    if not GEMINI_API_KEY:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY no configurada.")

    if not req.alumnos:
        raise HTTPException(status_code=400, detail="No hay alumnos en el request.")

    try:
        model_name = _get_gemini_model(GEMINI_API_KEY)
        print(f"--- Generando informe de curso con modelo: {model_name} ---")

        url = f"https://generativelanguage.googleapis.com/v1beta/{model_name}:generateContent?key={GEMINI_API_KEY}"
        prompt = _build_prompt_curso(req)

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.3,
                "maxOutputTokens": 4096,
            },
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
        print(f"ERROR generar_informe_curso: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))