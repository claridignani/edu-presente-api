# app/schemas/escuela.py
from __future__ import annotations

import re
from typing import List, Optional

from pydantic import EmailStr, field_validator
from sqlmodel import SQLModel, Field

from app.schemas.curso import CursoPublic

TEL_RE = re.compile(r"^\d{10,15}$")


def _strip_str(v: str) -> str:
    return v.strip() if isinstance(v, str) else v


def _only_digits(v: str) -> str:
    v = _strip_str(v)
    if not isinstance(v, str):
        return v
    return re.sub(r"\D+", "", v)


# ==========================
# BASE "de datos" (sin validación dura)
# ==========================
class EscuelaBase(SQLModel):
    nombre: str = Field(max_length=255)
    numero: int = Field()

    nivel_educativo: str = Field(max_length=255)
    matricula: str = Field(max_length=255)

    direccion: str = Field(max_length=255)
    codigo_postal: str = Field(max_length=255)
    codigo_provincial: str = Field(max_length=255)

    # 👇 En salida no queremos que explote por datos viejos => opcionales
    telefono: Optional[str] = Field(default=None, max_length=15)
    correo_electronico: Optional[str] = Field(default=None, max_length=255)

    localidad: Optional[str] = Field(default=None, max_length=255)
    provincia: Optional[str] = Field(default=None, max_length=255)

    provincia_id: Optional[str] = Field(default=None, max_length=10)
    localidad_id: Optional[str] = Field(default=None, max_length=20)


# ==========================
# OUTPUT (tolerante) - para endpoints de escuelas
# ==========================
class EscuelaPublic(EscuelaBase):
    CUE: str


# ⚠️ Usar SOLO cuando tengas la escuela completa
class EscuelaConCursos(EscuelaPublic):
    cursos: List[CursoPublic] = []


# ==========================
# OUTPUT MINI - para docente (escuelas + cursos)
# ==========================
class EscuelaMini(SQLModel):
    CUE: str = Field(max_length=20)
    nombre: str = Field(max_length=255)


class EscuelaMiniConCursos(EscuelaMini):
    cursos: List[CursoPublic] = []


# ==========================
# INPUT (estricto)
# ==========================
class EscuelaCreate(SQLModel):
    CUE: str = Field(index=True, max_length=20)

    nombre: str = Field(max_length=255)
    numero: int = Field()

    nivel_educativo: str = Field(max_length=255)
    matricula: str = Field(max_length=255)

    direccion: str = Field(max_length=255)
    codigo_postal: str = Field(max_length=255)
    codigo_provincial: str = Field(max_length=255)

    telefono: str = Field(max_length=15)
    correo_electronico: EmailStr = Field(max_length=255)

    localidad: Optional[str] = Field(default=None, max_length=255)
    provincia: Optional[str] = Field(default=None, max_length=255)

    provincia_id: Optional[str] = Field(default=None, max_length=10)
    localidad_id: Optional[str] = Field(default=None, max_length=20)

    @field_validator("CUE", mode="before")
    @classmethod
    def validar_cue_create(cls, v):
        if v is None:
            raise ValueError("El CUE es obligatorio")
        cue = re.sub(r"\D", "", str(v).strip())

        if not cue:
            raise ValueError("CUE inválido. Debe contener solo números.")
            
        return cue

    @field_validator("telefono", mode="before")
    @classmethod
    def validar_telefono(cls, v):
        v = _only_digits(v)
        if not isinstance(v, str) or not TEL_RE.match(v):
            raise ValueError("El teléfono debe tener entre 10 y 15 dígitos y solo números")
        return v

    @field_validator("correo_electronico", mode="before")
    @classmethod
    def normalizar_correo(cls, v):
        v = _strip_str(v)
        if isinstance(v, str):
            v = v.lower()
        return v


class EscuelaUpdate(SQLModel):
    nombre: Optional[str] = None
    numero: Optional[int] = None
    nivel_educativo: Optional[str] = None
    matricula: Optional[str] = None
    direccion: Optional[str] = None
    codigo_postal: Optional[str] = None
    codigo_provincial: Optional[str] = None

    telefono: Optional[str] = None
    correo_electronico: Optional[EmailStr] = None

    localidad: Optional[str] = None
    provincia: Optional[str] = None
    provincia_id: Optional[str] = Field(default=None, max_length=10)
    localidad_id: Optional[str] = Field(default=None, max_length=20)

    @field_validator("telefono", mode="before")
    @classmethod
    def validar_telefono_update(cls, v):
        if v is None:
            return None
        v = _only_digits(v)
        if v == "":
            return None
        if not isinstance(v, str) or not TEL_RE.match(v):
            raise ValueError("El teléfono debe tener entre 10 y 15 dígitos y solo números")
        return v

    @field_validator("correo_electronico", mode="before")
    @classmethod
    def normalizar_correo_update(cls, v):
        if v is None:
            return None
        v = _strip_str(v)
        if v == "":
            return None
        if isinstance(v, str):
            v = v.lower()
        return v
