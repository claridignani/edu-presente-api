from sqlmodel import Field, Relationship
from app.models.parentesco import Parentesco
from app.schemas.responsable import ResponsableBase
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .alumno import Alumno


class Responsable(ResponsableBase, table=True):
    idResponsable: int | None = Field(default=None, primary_key=True)

    dni: str = Field(index=True, unique=True, max_length=255)   # ampliado
    dni_hash: str = Field(default="", index=True, max_length=64)
    fecha_nacimiento: Optional[str] = Field(default=None)        # str, no date
    email: str = Field(index=True, max_length=255)
    nro_celular: str = Field(index=True, max_length=15)
    direccion: str = Field(max_length=255)                       # ampliado

    alumnos: list["Alumno"] = Relationship(
        back_populates="responsables",
        link_model=Parentesco
    )