# app/schemas/alumno_detalle.py
from __future__ import annotations
from typing import Optional
from sqlmodel import SQLModel
from pydantic import model_validator

from app.core.encryption import decrypt


class ResponsableMiniPublic(SQLModel):
    idResponsable: int
    nombre: str
    apellido: str
    parentesco: Optional[str] = None
    nro_celular: Optional[str] = None
    email: Optional[str] = None
    direccion: Optional[str] = None

    @model_validator(mode="after")
    def decrypt_fields(self):
        self.direccion = decrypt(self.direccion) if self.direccion else self.direccion
        return self


class AlumnoEscuelaDetallePublic(SQLModel):
    idAlumno: int
    nombre: str
    apellido: str
    dni: str
    estado: str
    direccion: Optional[str] = None
    localidad: Optional[str] = None   # ← agregado
    provincia: Optional[str] = None   # ← agregado
    fecha_nacimiento: Optional[str] = None   # ← agregado (viene encriptado, se desencripta abajo)
    fecha_ingreso: Optional[str] = None      # ← agregado (es date, se serializa como str ISO)
    idCurso: Optional[int] = None
    nombreCurso: Optional[str] = None
    responsable: Optional[ResponsableMiniPublic] = None

    @model_validator(mode="after")
    def decrypt_fields(self):
        self.dni = decrypt(self.dni) if self.dni else self.dni
        self.direccion = decrypt(self.direccion) if self.direccion else self.direccion
        # fecha_nacimiento está encriptada igual que dni/direccion
        self.fecha_nacimiento = decrypt(self.fecha_nacimiento) if self.fecha_nacimiento else self.fecha_nacimiento
        return self