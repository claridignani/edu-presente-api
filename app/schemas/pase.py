from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel


# ──────────────────────────────────────────
# Enums
# ──────────────────────────────────────────

class TipoPase(str, Enum):
    CON_PASE = "CON_PASE"
    SIN_PASE = "SIN_PASE"


class MotivoBaja(str, Enum):
    MUDANZA = "MUDANZA"
    DISTANCIA_A_LA_ESCUELA = "DISTANCIA_A_LA_ESCUELA"
    DIFICULTADES_ECONOMICAS = "DIFICULTADES_ECONOMICAS"
    SITUACION_DE_SALUD = "SITUACION_DE_SALUD"
    TRABAJO_MADRE_PADRE_TUTOR = "TRABAJO_MADRE_PADRE_TUTOR"
    OTRO_MOTIVO = "OTRO_MOTIVO"


class AccionPrevia(str, Enum):
    CONTACTO_ADULTOS = "CONTACTO_ADULTOS"
    PLAN_ESTRATEGIAS = "PLAN_ESTRATEGIAS"
    ARTICULACION_EOE = "ARTICULACION_EOE"
    OTRO_TIPO_ACCION = "OTRO_TIPO_ACCION"
    NINGUNA = "NINGUNA"


class EstadoPase(str, Enum):
    ACTIVO = "Activo"
    ANULADO = "Anulado"


class EstadoPaseEntrada(str, Enum):
    PENDIENTE = "Pendiente"
    CONFIRMADO = "Confirmado"
    ANULADO = "Anulado"


# ──────────────────────────────────────────
# Pase Salida — Requests
# ──────────────────────────────────────────

class PaseSalidaCreate(BaseModel):
    idAlumno: int
    idInscripcion: Optional[int] = None
    idMovimiento: Optional[int] = None      # si viene del flujo mover-alumnos
    cueOrigen: str
    tipoPase: TipoPase
    motivo: MotivoBaja
    accionesPrevias: Optional[list[AccionPrevia]] = None    # solo SIN_PASE
    cueDestino: Optional[str] = None                        # solo CON_PASE
    nombreEscuelaDestino: Optional[str] = None              # solo CON_PASE
    fecha: date


class PaseSalidaBulkCreate(BaseModel):
    """Múltiples bajas desde el flujo mover-alumnos (paso 3)."""
    idMovimiento: Optional[int] = None
    cueOrigen: str
    pases: list[PaseSalidaCreate]


# ──────────────────────────────────────────
# Pase Salida — Responses
# ──────────────────────────────────────────

class PaseSalidaPublic(BaseModel):
    idPase: int
    idAlumno: int
    idInscripcion: Optional[int]
    idMovimiento: Optional[int]
    cueOrigen: str
    tipoPase: TipoPase
    motivo: MotivoBaja
    accionesPrevias: Optional[list[AccionPrevia]]
    cueDestino: Optional[str]
    nombreEscuelaDestino: Optional[str]
    nroPase: str
    fecha: date
    estado: EstadoPase
    created_at: Optional[datetime]
    # Datos del alumno enriquecidos en el service
    nombreAlumno: Optional[str] = None
    apellidoAlumno: Optional[str] = None
    dniAlumno: Optional[str] = None         # ya desencriptado

    model_config = {"from_attributes": True}


class PaseSalidaListItem(BaseModel):
    """Row para el histórico de salidas."""
    idPase: int
    nroPase: str
    dni: str                                # ya desencriptado
    apellidoNombre: str
    fechaPase: date
    tipoPase: TipoPase
    motivo: MotivoBaja
    establecimientoDestino: Optional[str]   # "CUE - nombre" o None
    estado: EstadoPase

    model_config = {"from_attributes": True}


# ──────────────────────────────────────────
# Comprobante (datos para generar PDF en el front)
# ──────────────────────────────────────────

class ComprobanteData(BaseModel):
    nroPase: str
    fecha: date
    nombreAlumno: str
    apellidoAlumno: str
    dniAlumno: str                          # ya desencriptado
    cueOrigen: str
    nombreEscuelaOrigen: str
    cueDestino: Optional[str]
    nombreEscuelaDestino: Optional[str]
    tipoPase: TipoPase
    motivo: MotivoBaja
    accionesPrevias: Optional[list[AccionPrevia]]
    nombreDirector: str


# ──────────────────────────────────────────
# Pase Entrada — Requests
# ──────────────────────────────────────────

class PaseEntradaCreate(BaseModel):
    idAlumno: int
    idPreinscripcion: Optional[int] = None
    cueDestino: str
    cueOrigen: Optional[str] = None
    nombreEscuelaOrigen: Optional[str] = None
    nroPaseOrigen: Optional[str] = None
    fecha: date


# ──────────────────────────────────────────
# Pase Entrada — Responses
# ──────────────────────────────────────────

class PaseEntradaPublic(BaseModel):
    idPaseEntrada: int
    idAlumno: int
    idPreinscripcion: Optional[int]
    cueDestino: str
    cueOrigen: Optional[str]
    nombreEscuelaOrigen: Optional[str]
    nroPaseOrigen: Optional[str]
    fecha: date
    estado: EstadoPaseEntrada
    created_at: Optional[datetime]

    model_config = {"from_attributes": True}


class PaseEntradaListItem(BaseModel):
    """Row para el histórico de ingresos."""
    idPaseEntrada: int
    dni: str                                # ya desencriptado
    apellidoNombre: str
    fechaPase: date
    escuelaOrigen: Optional[str]            # "CUE - nombre" o "Sin pase"
    estado: EstadoPaseEntrada

    model_config = {"from_attributes": True}


# ──────────────────────────────────────────
# Búsqueda de escuelas
# ──────────────────────────────────────────

class EscuelaSearchResult(BaseModel):
    CUE: str
    nombre: str
    localidad: Optional[str]
    provincia: Optional[str]

    model_config = {"from_attributes": True}