from datetime import date
from typing import Optional, List, TYPE_CHECKING

from sqlmodel import SQLModel, Field, Relationship
from app.models.rol import Rol

if TYPE_CHECKING:
    from .escuela import Escuela


class Usuario(SQLModel, table=True):
    __tablename__ = "usuario"

    idUsuario: Optional[int] = Field(default=None, primary_key=True)
    dni: str = Field(index=True, max_length=255)        # ampliado para texto encriptado
    dni_hash: str = Field(default="", index=True, max_length=64)
    cuil: str = Field(index=True, max_length=255)       # ampliado para texto encriptado
    celular: str = Field(max_length=15)                 # no se encripta
    mailABC: str = Field(index=True, unique=True, max_length=255)
    fechaNacimiento: Optional[str] = None               # str porque se guarda encriptado
    nombre: str = Field(max_length=100)
    apellido: str = Field(max_length=100)
    contrasena: str = Field(max_length=255)

    escuelas: List["Escuela"] = Relationship(
        back_populates="usuarios",
        link_model=Rol,
    )