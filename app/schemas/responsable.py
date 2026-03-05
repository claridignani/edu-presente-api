from typing import Optional
from sqlmodel import SQLModel, Field
from datetime import date
from pydantic import field_validator, model_validator
from app.core.encryption import encrypt, decrypt, hash_for_search


class ResponsableBase(SQLModel):
    nombre: str = Field(max_length=100)
    apellido: str = Field(max_length=100)
    dni: str = Field(index=True, max_length=255)            # ampliado para encriptado
    dni_hash: Optional[str] = Field(default=None, index=True)
    fecha_nacimiento: Optional[str] = Field(default=None)   # str porque se guarda encriptado
    email: str = Field(index=True, max_length=255)          # no se encripta
    nro_celular: str = Field(max_length=15)                 # no se encripta
    direccion: str = Field(max_length=255)                  # ampliado para encriptado
    localidad: Optional[str] = Field(default=None, max_length=100)   # ← nuevo
    provincia: Optional[str] = Field(default=None, max_length=100)   # ← nuevo


class ResponsablePublic(SQLModel):
    idResponsable: int
    nombre: str
    apellido: str
    dni: str
    fecha_nacimiento: Optional[str] = None
    email: str
    nro_celular: str
    direccion: str
    localidad: Optional[str] = None   # ← nuevo
    provincia: Optional[str] = None   # ← nuevo

    @model_validator(mode="after")
    def decrypt_fields(self):
        if self.dni:
            self.dni = decrypt(self.dni)
        if self.fecha_nacimiento:
            self.fecha_nacimiento = decrypt(self.fecha_nacimiento)
        if self.direccion:
            self.direccion = decrypt(self.direccion)
        return self


class ResponsableCreate(ResponsableBase):

    @field_validator("dni", mode="before")
    @classmethod
    def encrypt_dni(cls, v):
        return encrypt(str(v)) if v else v

    @field_validator("fecha_nacimiento", mode="before")
    @classmethod
    def encrypt_fecha(cls, v):
        return encrypt(str(v)) if v else v

    @field_validator("direccion", mode="before")
    @classmethod
    def encrypt_direccion(cls, v):
        return encrypt(str(v)) if v else v

    @model_validator(mode="after")
    def set_dni_hash(self):
        if self.dni:
            from app.core.encryption import decrypt, hash_for_search
            self.dni_hash = hash_for_search(decrypt(self.dni))
        return self


class ResponsableUpdate(SQLModel):
    nombre: str | None = None
    apellido: str | None = None
    dni: str | None = None
    dni_hash: str | None = None
    fecha_nacimiento: str | None = None     # str porque se encripta
    email: str | None = None
    nro_celular: str | None = None
    direccion: str | None = None
    localidad: str | None = None   # ← nuevo
    provincia: str | None = None   # ← nuevo

    @field_validator("dni", mode="before")
    @classmethod
    def encrypt_dni(cls, v):
        return encrypt(str(v)) if v else v

    @field_validator("fecha_nacimiento", mode="before")
    @classmethod
    def encrypt_fecha(cls, v):
        return encrypt(str(v)) if v else v

    @field_validator("direccion", mode="before")
    @classmethod
    def encrypt_direccion(cls, v):
        return encrypt(str(v)) if v else v

    @model_validator(mode="after")
    def set_dni_hash(self):
        if self.dni:
            from app.core.encryption import decrypt, hash_for_search
            self.dni_hash = hash_for_search(decrypt(self.dni))
        return self