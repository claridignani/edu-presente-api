from __future__ import annotations
from pydantic import BaseModel
from typing import Optional
from datetime import date
from enum import Enum
from sqlmodel import SQLModel, Field


class EstadoInscripcion(str, Enum):
    Activo = "Activo"
    CambioCurso = "CambioCurso"
    Promocionado = "Promocionado"
    Repitente = "Repitente"
    Egreso = "Egreso"
    Baja = "Baja"
    CierreCiclo = "CierreCiclo"


class InscriptosBase(SQLModel):
    fechaAlta: date
    fechaBaja: date | None = None
    activo: bool = True
    estado: EstadoInscripcion = EstadoInscripcion.Activo


class InscriptosCreate(SQLModel):
    idCurso: int
    idAlumno: int
    # opcionales
    fechaAlta: date | None = None
    estado: EstadoInscripcion | None = None  # si no viene, queda Activo


class InscriptosPublic(InscriptosBase):
    idInscripcion: int
    idCurso: int
    idAlumno: int


# Para mover alumnos entre cursos (mismo ciclo)
class CambioCursoRequest(SQLModel):
    idAlumno: int
    idCursoDestino: int


# Para promoción fin de año
class AccionPromocion(str, Enum):
    Promociona = "Promociona"   # pasa a destino
    Repite = "Repite"           # va a destino (pero estado Repitente)
    Egresa = "Egresa"           # cierra y NO crea en destino
    Baja = "Baja"               # cierra y NO crea en destino


class PromocionItem(SQLModel):
    idAlumno: int
    accion: AccionPromocion


class PromocionarRequest(SQLModel):
    director_id: int
    idCursoOrigen: int
    idCursoDestino: int
    alumnos: list[PromocionItem]
    fecha: date | None = None

class InscripcionHistorialOut(BaseModel):
    idInscripcion: int
    idCurso: int
    cicloLectivo: str
    cursoNombre: str
    cursoDivision: str
    fechaAlta: date
    fechaBaja: Optional[date] = None
    activo: bool
    estado: EstadoInscripcion

