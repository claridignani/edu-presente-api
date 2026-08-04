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
    dni: Optional[str] = None
    email: Optional[str] = None
    nro_celular: Optional[str] = None
    direccion: Optional[str] = None
    parentesco: str

