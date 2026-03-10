# app/schemas/asistencia.py
from datetime import date
from enum import Enum
from typing import Optional
from sqlmodel import SQLModel, Field


class AsistenciaEstado(str, Enum):
    Presente    = "Presente"
    Ausente     = "Ausente"
    Tarde       = "Tarde"
    Justificado = "Justificado"   # ← nuevo


class CertificadoEstado(str, Enum):
    pendiente  = "pendiente"
    aprobado   = "aprobado"
    rechazado  = "rechazado"


class AsistenciaBase(SQLModel):
    estado:             AsistenciaEstado        = Field(...)
    lluvia:             bool                    = Field(default=False)
    wamid:              Optional[str]           = Field(default=None)
    motivo_ausencia:    Optional[str]           = Field(default=None)
    certificado_path:   Optional[str]           = Field(default=None)
    # ── campos nuevos ──────────────────────────────────────
    certificado_estado: Optional[CertificadoEstado] = Field(default=None)
    justificado_hasta:  Optional[date]          = Field(default=None)
    revisado_por:       Optional[int]           = Field(default=None)


# Schema de LECTURA completo (frontend / historial / stats)
class AsistenciaRead(AsistenciaBase):
    idCurso:  int
    idAlumno: int
    fecha:    date


class AsistenciaPublic(AsistenciaBase):
    idAlumno: int


class AsistenciaCreate(AsistenciaBase):
    fecha:    date
    idAlumno: int
    idCurso:  int


# ── Revisión de certificado por parte del docente ──────────
class CertificadoRevisionRequest(SQLModel):
    """
    Payload que envía el docente al aprobar o rechazar un certificado.
    - accion: 'aprobado' o 'rechazado'
    - dias_justificacion: solo obligatorio cuando accion == 'aprobado'
      El backend calcula justificado_hasta = fecha_inasistencia + dias
    """
    accion:             CertificadoEstado
    dias_justificacion: Optional[int] = Field(default=None, ge=1, le=365)


# ── Notificación para la campanita del docente ─────────────
class NotificacionDocente(SQLModel):
    """
    Ítem que aparece en el panel de notificaciones del docente.
    Agrupa toda la info necesaria para mostrar la tarjeta y abrir el modal.
    """
    idCurso:            int
    idAlumno:           int
    fecha:              date
    alumnoNombre:       str
    curso:              str             # "Primero A (2025)"
    motivo_ausencia:    Optional[str]
    certificado_path:   Optional[str]
    certificado_estado: Optional[str]   # pendiente | aprobado | rechazado | None
    justificado_hasta:  Optional[date]
    # tipo de notificación para que el frontend sepa qué ícono/color mostrar
    tipo_notif:         str             # "respuesta" | "certificado_pendiente" | "certificado_revisado"