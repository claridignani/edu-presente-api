from enum import Enum
from sqlmodel import SQLModel, Field
from datetime import date
from typing import Optional
from pydantic import field_validator, model_validator
from app.schemas.parentesco import ResponsableConParentescoPublic
from app.core.encryption import encrypt, decrypt, hash_for_search


class AlumnoEstado(Enum):
    Activo = "Activo"
    Inactivo = "Inactivo"


class AlumnoBase(SQLModel):
    nombre: str = Field(max_length=100)
    apellido: str = Field(max_length=100)
    dni: str = Field(index=True, max_length=255)
    dni_hash: Optional[str] = Field(default=None, index=True)
    fecha_nacimiento: str = Field(max_length=255)   # str porque se guarda encriptado
    fecha_ingreso: date = Field()
    direccion: str = Field(max_length=255)
    localidad: Optional[str] = Field(default=None, max_length=100)   # ← nuevo
    provincia: Optional[str] = Field(default=None, max_length=100)   # ← nuevo
    estado: AlumnoEstado = Field(default=AlumnoEstado.Inactivo)


class AlumnoCreate(AlumnoBase):
    idCurso: Optional[int] = None
    CUE: Optional[str] = None
    cicloLectivo: Optional[str] = None

    @field_validator("dni", mode="before")
    @classmethod
    def encrypt_dni(cls, v):
        return encrypt(str(v)) if v else v

    @field_validator("direccion", mode="before")
    @classmethod
    def encrypt_direccion(cls, v):
        return encrypt(str(v)) if v else v

    @field_validator("fecha_nacimiento", mode="before")
    @classmethod
    def encrypt_fecha_nacimiento(cls, v):
        return encrypt(str(v)) if v else v

    @model_validator(mode="after")
    def set_dni_hash(self):
        if self.dni:
            from app.core.encryption import decrypt, hash_for_search
            self.dni_hash = hash_for_search(decrypt(self.dni))
        return self


class AlumnoPublic(AlumnoBase):
    idAlumno: int

    @model_validator(mode="after")
    def decrypt_fields(self):
        self.dni = decrypt(self.dni)
        self.direccion = decrypt(self.direccion)
        self.fecha_nacimiento = decrypt(self.fecha_nacimiento)
        return self


class AlumnoUpdate(SQLModel):
    nombre: Optional[str] = None
    apellido: Optional[str] = None
    dni: Optional[str] = None
    dni_hash: Optional[str] = None
    fecha_nacimiento: Optional[str] = None
    fecha_ingreso: Optional[date] = None
    direccion: Optional[str] = None
    localidad: Optional[str] = None   # ← nuevo
    provincia: Optional[str] = None   # ← nuevo
    estado: Optional[AlumnoEstado] = None

    @field_validator("dni", mode="before")
    @classmethod
    def encrypt_dni(cls, v):
        return encrypt(str(v)) if v else v

    @field_validator("direccion", mode="before")
    @classmethod
    def encrypt_direccion(cls, v):
        return encrypt(str(v)) if v else v

    @field_validator("fecha_nacimiento", mode="before")
    @classmethod
    def encrypt_fecha_nacimiento(cls, v):
        return encrypt(str(v)) if v else v

    @model_validator(mode="after")
    def set_dni_hash(self):
        if self.dni:
            from app.core.encryption import decrypt, hash_for_search
            self.dni_hash = hash_for_search(decrypt(self.dni))
        return self


class AlumnoDetallePublic(SQLModel):
    idAlumno: int
    nombre: str
    apellido: str
    dni: str
    estado: str
    responsable: Optional[ResponsableConParentescoPublic] = None

    @model_validator(mode="after")
    def decrypt_fields(self):
        self.dni = decrypt(self.dni)
        return self


class AlumnoBusquedaDniPublic(SQLModel):
    idAlumno: int
    nombre: str
    apellido: str
    dni: str
    fecha_nacimiento: str
    tiene_inscripcion_activa: bool
    escuela_activa: Optional[str] = None

    @model_validator(mode="after")
    def decrypt_fields(self):
        self.dni = decrypt(self.dni)
        self.fecha_nacimiento = decrypt(self.fecha_nacimiento)
        return self