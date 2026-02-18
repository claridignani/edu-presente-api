from __future__ import annotations
from datetime import date, datetime
from pydantic import BaseModel

# --- Esquema para los Alumnos dentro del detalle ---
class MovimientoItemOut(BaseModel):
    idItem: int
    idAlumno: int 
    idCursoOrigen: int | None = None
    idCursoDestino: int | None = None
    alumno: str | None = None
    dni: str | None = None
    accion: str
    idInscripcionOrigen: int | None = None
    idInscripcionDestino: int | None = None

# --- Esquema para la lista general del Historial ---
class MovimientoHistorialOut(BaseModel):
    idMovimiento: int
    fecha: date
    estado: str
    created_at: datetime | None = None
    cursoOrigen: str 
    cursoDestino: str
    idCursoOrigen: int | None = None  
    idCursoDestino: int | None = None 
    director_id: int | None = None 

# --- Esquema para el detalle completo al hacer clic ---
class MovimientoDetalleOut(MovimientoHistorialOut):
    items: list[MovimientoItemOut] = []

# --- Otros esquemas existentes ---
class MovimientoOut(BaseModel):
    idMovimiento: int
    cue: str
    director_id: int
    idCursoOrigen: int
    idCursoDestino: int
    fecha: date
    estado: str
    created_at: datetime | None = None

class PromocionarOut(BaseModel):
    ok: bool = True
    idMovimiento: int