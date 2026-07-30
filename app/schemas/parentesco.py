from datetime import date
from typing import Optional
from pydantic import Field
from sqlmodel import SQLModel


class ParentescoBase(SQLModel):
    parentesco: str = Field(max_length=50)


class ParentescoPublic(ParentescoBase):
    idAlumno: int
    idResponsable: int


class ParentescoCreate(ParentescoBase):
    idAlumno: int
    idResponsable: int


class ResponsableConParentescoPublic(SQLModel):
    idResponsable: int
    nombre: str
    apellido: str
    dni: str
    email: str
    nro_celular: str
    direccion: str
    parentesco: str
