from typing import List, Optional, TYPE_CHECKING

from pydantic import EmailStr
from sqlmodel import SQLModel, Field, Relationship

from app.models.rol import Rol

if TYPE_CHECKING:
    from .usuario import Usuario


class Escuela(SQLModel, table=True):
    __tablename__ = "escuela"

    # PK
    CUE: str = Field(primary_key=True, max_length=20)

    # Campos obligatorios (según tu DB)
    nombre: str = Field(max_length=255)
    numero: int = Field()

    nivel_educativo: str = Field(max_length=255)
    matricula: str = Field(max_length=255)

    direccion: str = Field(max_length=255)
    codigo_postal: str = Field(max_length=255)
    codigo_provincial: str = Field(max_length=255)

    telefono: str = Field(max_length=15)
    correo_electronico: EmailStr = Field(max_length=255)

    # Opcionales
    localidad: Optional[str] = Field(default=None, max_length=255)
    provincia: Optional[str] = Field(default=None, max_length=255)
    provincia_id: Optional[str] = Field(default=None, max_length=10)
    localidad_id: Optional[str] = Field(default=None, max_length=20)

    usuarios: List["Usuario"] = Relationship(
        back_populates="escuelas",
        link_model=Rol,
    )
