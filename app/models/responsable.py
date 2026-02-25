from sqlmodel import Field, Relationship
from app.models.parentesco import Parentesco
from app.schemas.responsable import ResponsableBase
from typing import TYPE_CHECKING, Optional
from datetime import date

if TYPE_CHECKING:
    from .alumno import Alumno


class Responsable(ResponsableBase, table=True):
    idResponsable: int | None = Field(default=None, primary_key=True)

    dni: str = Field(index=True, unique=True, max_length=20)
    fecha_nacimiento: Optional[date] = Field(default=None, nullable=True)  # ← opcional

    email: str = Field(index=True, unique=False, max_length=255)
    nro_celular: str = Field(index=True, unique=False, max_length=15)

    alumnos: list["Alumno"] = Relationship(
        back_populates="responsables",
        link_model=Parentesco
    )