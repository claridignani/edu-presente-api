from datetime import date
from typing import Optional, List, TYPE_CHECKING

from sqlmodel import SQLModel, Field, Relationship
from app.models.rol import Rol

if TYPE_CHECKING:
    from .escuela import Escuela


class Usuario(SQLModel, table=True):
    __tablename__ = "usuario"

    idUsuario: Optional[int] = Field(default=None, primary_key=True)
    dni: str = Field(index=True, max_length=8)
    cuil: str = Field(index=True, max_length=11)
    celular: str = Field(max_length=15)
    mailABC: str = Field(index=True, unique=True, max_length=255)
    fechaNacimiento: Optional[date] = None
    nombre: str = Field(max_length=100)
    apellido: str = Field(max_length=100)
    contrasena: str = Field(max_length=255)

    escuelas: List["Escuela"] = Relationship(
        back_populates="usuarios",
        link_model=Rol,
    )
