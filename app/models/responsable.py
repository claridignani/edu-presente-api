from sqlmodel import Field, Relationship
from app.models.parentesco import Parentesco
from app.schemas.responsable import ResponsableBase
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .alumno import Alumno


class Responsable(ResponsableBase, table=True):
    idResponsable: int | None = Field(default=None, primary_key=True)

    # ✅ DNI único (identidad del responsable)
    dni: str = Field(index=True, unique=True, max_length=20)

    # ✅ Email y celular NO únicos (pueden repetirse / estar vacíos)
    email: str = Field(index=True, unique=False, max_length=255)
    nro_celular: str = Field(index=True, unique=False, max_length=15)

    alumnos: list["Alumno"] = Relationship(
        back_populates="responsables",
        link_model=Parentesco
    )
