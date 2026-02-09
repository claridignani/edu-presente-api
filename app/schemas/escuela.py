from typing import List
from sqlmodel import SQLModel, Field

from app.schemas.curso import CursoPublic



class EscuelaBase(SQLModel):
    nombre: str = Field(max_length=255)
    numero: int = Field()
    nivel_educativo: str = Field(max_length=255)
    matricula: str = Field(max_length=255)
    direccion: str = Field(max_length=255)
    localidad: str | None = Field(default=None, max_length=255)
    provincia: str | None = Field(default=None, max_length=255)
    codigo_postal: str = Field(max_length=255)
    codigo_provincial: str = Field(max_length=255)
    telefono: str = Field(max_length=15)
    correo_electronico: str = Field(index=True,max_length=255)
    provincia_id: str | None = Field(default=None, max_length=10)
    localidad_id: str | None = Field(default=None, max_length=20)


class EscuelaPublic(EscuelaBase):
    CUE: str

class EscuelaConCursos(EscuelaPublic):
    cursos: List[CursoPublic]

class EscuelaCreate(EscuelaBase):
    CUE: str = Field(min_length=9, max_length=9)

class EscuelaUpdate(SQLModel):
    CUE: str | None = None
    nombre: str | None = None
    numero: int | None = None
    nivel_educativo: str | None= None
    matricula: str | None= None
    direccion: str|None = None
    localidad: str | None = None
    provincia: str | None = None
    codigo_postal: str | None= None
    codigo_provincial: str | None= None
    telefono: str | None= None
    correo_electronico: str | None= None
    provincia_id: str | None = None
    localidad_id: str | None = None


