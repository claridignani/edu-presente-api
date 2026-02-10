from typing import TYPE_CHECKING
from sqlmodel import Field, Relationship, SQLModel
from sqlalchemy import Column
from sqlalchemy import Enum as SAEnum

from app.schemas.curso import TurnoCurso
from app.models.inscriptos import Inscriptos

if TYPE_CHECKING:
    from .alumno import Alumno


def enum_values(enum_cls):
    return [e.value for e in enum_cls]


class Curso(SQLModel, table=True):
    __tablename__ = "curso"

    idCurso: int | None = Field(default=None, primary_key=True)
    CUE: str = Field(nullable=False, foreign_key="escuela.CUE")

    nombre: str = Field(max_length=255)
    cicloLectivo: str = Field(max_length=50)
    division: str = Field(max_length=50)
    turno: TurnoCurso = Field(
        default=TurnoCurso.Manana,
        sa_column=Column(
            SAEnum(
                TurnoCurso,
                values_callable=enum_values,   
                native_enum=True,              
                validate_strings=True,
            ),
            nullable=False,
        ),
    )

    alumnos: list["Alumno"] = Relationship(
        back_populates="cursos",
        link_model=Inscriptos
    )
