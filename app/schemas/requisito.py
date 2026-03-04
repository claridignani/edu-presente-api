# app/schemas/requisito.py

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from enum import Enum


class TipoRequisito(str, Enum):
    documento    = "documento"
    autorizacion = "autorizacion"


# ── Requisito del curso ───────────────────────────────────────────

class RequisitoCursoCreate(BaseModel):
    nombre:      str            = Field(..., min_length=2, max_length=150)
    tipo:        TipoRequisito  = TipoRequisito.documento
    obligatorio: bool           = True
    descripcion: Optional[str]  = None


class RequisitoCursoUpdate(BaseModel):
    nombre:      Optional[str]           = None
    tipo:        Optional[TipoRequisito] = None
    obligatorio: Optional[bool]          = None
    descripcion: Optional[str]           = None


class RequisitoCursoOut(BaseModel):
    idRequisito: int
    idCurso:     int
    nombre:      str
    tipo:        TipoRequisito
    obligatorio: bool
    descripcion: Optional[str]
    creado_en:   Optional[datetime]

    # Stats calculados en el endpoint
    total_alumnos:    int = 0
    alumnos_cumplen:  int = 0

    class Config:
        from_attributes = True


# ── Estado por alumno ─────────────────────────────────────────────

class RequisitoAlumnoUpdate(BaseModel):
    cumplido:    bool
    observacion: Optional[str] = None


class RequisitoAlumnoOut(BaseModel):
    idRequisito:       int
    idAlumno:          int
    nombre:            str           # denormalizado para el front
    tipo:              TipoRequisito
    obligatorio:       bool
    descripcion:       Optional[str]
    cumplido:          bool
    fecha_cumplimiento: Optional[datetime]
    observacion:       Optional[str]

    class Config:
        from_attributes = True


# ── Vista resumen por curso (para la pestaña del curso) ───────────

class AlumnoRequisitoRow(BaseModel):
    idAlumno:    int
    nombre:      str
    apellido:    str
    cumplido:    bool
    observacion: Optional[str]
    fecha_cumplimiento: Optional[datetime]

    class Config:
        from_attributes = True