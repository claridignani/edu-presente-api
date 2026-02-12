from __future__ import annotations

import re
from datetime import date
from typing import Optional, List

from pydantic import EmailStr, field_validator
from sqlmodel import SQLModel, Field

from app.schemas.rol import RolDescripcion, RolPublic, RolEstado


# =========================
# Regex y Helpers
# =========================
DNI_RE = re.compile(r"^\d{7,8}$")
CUIL_RE = re.compile(r"^\d{11}$")
CEL_RE = re.compile(r"^\d{10,15}$")

def _strip_str(v: str) -> str:
    return v.strip() if isinstance(v, str) else v


def _only_digits(v: str) -> str:
    v = _strip_str(v)
    if not isinstance(v, str):
        return v
    return re.sub(r"\D+", "", v)


def _validate_password(pw: str) -> str:
    pw = _strip_str(pw)
    if not isinstance(pw, str) or not pw:
        raise ValueError("La contraseña es obligatoria")

    if len(pw) < 8:
        raise ValueError("La contraseña debe tener al menos 8 caracteres")
    if not re.search(r"[A-Z]", pw):
        raise ValueError("La contraseña debe tener al menos 1 letra mayúscula")
    if not re.search(r"[a-z]", pw):
        raise ValueError("La contraseña debe tener al menos 1 letra minúscula")
    if not re.search(r"\d", pw):
        raise ValueError("La contraseña debe tener al menos 1 número")
    if not re.search(r"[^\w\s]", pw):
        raise ValueError("La contraseña debe tener al menos 1 caracter especial")

    return pw


# ============================================================
# BASE (para registros y actualizaciones)
# ============================================================
class UsuarioBase(SQLModel):
    dni: str = Field(index=True, max_length=8)
    cuil: str = Field(index=True, max_length=11)
    celular: str = Field(max_length=15)
    mailABC: EmailStr = Field(index=True)
    fechaNacimiento: Optional[date] = None
    nombre: str = Field(max_length=100)
    apellido: str = Field(max_length=100)

    @field_validator("dni", mode="before")
    @classmethod
    def validar_dni(cls, v):
        v = _only_digits(v)
        if not isinstance(v, str) or not DNI_RE.match(v):
            raise ValueError("El DNI debe tener 7 u 8 dígitos y solo números")
        return v

    @field_validator("cuil", mode="before")
    @classmethod
    def validar_cuil(cls, v):
        v = _only_digits(v)
        if not isinstance(v, str) or not CUIL_RE.match(v):
            raise ValueError("El CUIL debe tener 11 dígitos y solo números")
        return v

    @field_validator("celular", mode="before")
    @classmethod
    def validar_celular(cls, v):
        v = _only_digits(v)
        if not isinstance(v, str) or not CEL_RE.match(v):
            raise ValueError("El celular debe tener entre 10 y 15 dígitos y solo números")
        return v

    @field_validator("mailABC", mode="before")
    @classmethod
    def normalizar_mail(cls, v):
        v = _strip_str(v)
        if isinstance(v, str):
            v = v.lower()
        return v


# ============================================================
# PUBLIC (Visualización Básica y Tablas)
# ============================================================
class CursoDetallePublic(SQLModel):
    nombre: str
    tipo: str

class UsuarioPublic(SQLModel):
    idUsuario: int
    dni: str
    cuil: Optional[str] = None
    celular: Optional[str] = None
    mailABC: EmailStr
    fechaNacimiento: Optional[date] = None
    nombre: str
    apellido: str
    tipo: str = "Titular"
    cursos: List[CursoDetallePublic] = []

    @field_validator("dni", mode="before")
    @classmethod
    def normalizar_dni_public(cls, v):
        if v is None: return v
        return _only_digits(v)

    @field_validator("cuil", mode="before")
    @classmethod
    def normalizar_cuil_public(cls, v):
        if v is None: return v
        return _only_digits(v)

    @field_validator("celular", mode="before")
    @classmethod
    def normalizar_celular_public(cls, v):
        if v is None: return v
        return _only_digits(v)

    @field_validator("mailABC", mode="before")
    @classmethod
    def normalizar_mail_public(cls, v):
        v = _strip_str(v)
        if isinstance(v, str):
            v = v.lower()
        return v


# ============================================================
# FICHA DETALLADA (Para el "Ojito" del Director)
# ============================================================
class CursoFichaPublic(SQLModel):
    idCurso: int  
    nombre: str
    tipo: str
    desde: Optional[date] = None
    hasta: Optional[date] = None

class DocenteFichaPublic(UsuarioPublic):
    cursos_detalle: List[CursoFichaPublic] = []


# ============================================================
# OPERACIONES (Create / Update)
# ============================================================
class UsuarioCreate(UsuarioBase):
    contrasena: str
    rol: RolDescripcion
    escuelasCUE: List[str]
    codigoInvitacion: Optional[str] = None

    @field_validator("contrasena")
    @classmethod
    def validar_contrasena(cls, v):
        return _validate_password(v)

    @field_validator("escuelasCUE", mode="before")
    @classmethod
    def validar_lista_cue(cls, v):
        if v is None:
            raise ValueError("escuelasCUE es obligatorio")
        return v

    @field_validator("escuelasCUE")
    @classmethod
    def validar_cue_items(cls, cues: List[str]):
        if not isinstance(cues, list) or len(cues) == 0:
            raise ValueError("escuelasCUE debe ser una lista con al menos 1 CUE")
        normalizados = []
        for cue in cues:
            cue_str = re.sub(r"\D", "", str(cue).strip())
            if not cue_str:
                raise ValueError(f"CUE inválido: {cue}")
            normalizados.append(cue_str)
        return normalizados

class UsuarioUpdate(SQLModel):
    nombre: Optional[str] = None
    apellido: Optional[str] = None
    dni: Optional[str] = None
    cuil: Optional[str] = None
    celular: Optional[str] = None
    mailABC: Optional[EmailStr] = None
    fechaNacimiento: Optional[date] = None
    contrasena: Optional[str] = None

    @field_validator("dni", "cuil", "celular", mode="before")
    @classmethod
    def validar_campos_update(cls, v):
        if v is None: return v
        return _only_digits(v)

    @field_validator("contrasena")
    @classmethod
    def validar_contrasena_update(cls, v):
        if v is None: return v
        return _validate_password(v)


# ============================================================
# ADMIN Y ROLES
# ============================================================
class Usuario_Roles(UsuarioPublic):
    rol: RolPublic

class EscuelaMini(SQLModel):
    CUE: str
    nombre: Optional[str] = None

class RolMini(SQLModel):
    descripcion: RolDescripcion
    estado: RolEstado
    CUE: Optional[str] = None
    nombre_escuela: Optional[str] = None

class UsuarioAdminPublic(SQLModel):
    idUsuario: int
    dni: str
    nombre: str
    apellido: str
    mailABC: EmailStr
    roles: List[RolMini] = []
    escuelas: List[EscuelaMini] = []