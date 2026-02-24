from typing import Optional
from sqlmodel import SQLModel, Field
from datetime import date


class ResponsableBase(SQLModel):
    nombre: str = Field(max_length=100)
    apellido: str = Field(max_length=100)
    dni: str = Field(index=True, max_length=20)
    fecha_nacimiento: Optional[date] = Field(default=None)  
    email: str = Field(index=True, max_length=255)
    nro_celular: str = Field(max_length=15)
    direccion: str = Field(max_length=100)

class ResponsablePublic(ResponsableBase):
    idResponsable: int

class ResponsableCreate(ResponsableBase):
    pass

class ResponsableUpdate(SQLModel):
    nombre: str | None = None
    apellido: str | None = None
    dni: str | None = None
    fecha_nacimiento: date | None = None
    email: str | None = None
    nro_celular: str | None = None
    direccion: str | None = None
