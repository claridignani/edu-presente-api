from __future__ import annotations

from datetime import date
from sqlmodel import SQLModel, Field
from sqlalchemy import Column
from sqlalchemy import Enum as SAEnum

from app.schemas.inscriptos import EstadoInscripcion


class Inscriptos(SQLModel, table=True):
    __tablename__ = "inscriptos"

    idInscripcion: int | None = Field(default=None, primary_key=True)

    idCurso: int = Field(foreign_key="curso.idCurso", index=True)
    idAlumno: int = Field(foreign_key="alumno.idAlumno", index=True)

    fechaAlta: date = Field(default_factory=date.today)
    fechaBaja: date | None = Field(default=None)

    activo: bool = Field(default=True, index=True)

    estado: EstadoInscripcion = Field(
        sa_column=Column(SAEnum(EstadoInscripcion, name="estado_inscripcion")),
        default=EstadoInscripcion.Activo,
    )
