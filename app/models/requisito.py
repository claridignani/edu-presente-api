# app/models/requisito.py

from typing import List, Optional, TYPE_CHECKING
from datetime import datetime
from enum import Enum

from sqlmodel import SQLModel, Field, Relationship
from sqlalchemy import Column, Text

# ⬆️ SIN "from __future__ import annotations"


class TipoRequisito(str, Enum):
    documento    = "documento"
    autorizacion = "autorizacion"


class RequisitoCurso(SQLModel, table=True):
    __tablename__ = "requisitos_curso"

    idRequisito: Optional[int]      = Field(default=None, primary_key=True)
    idCurso:     int                = Field(foreign_key="curso.idCurso")
    nombre:      str                = Field(max_length=150)
    tipo:        TipoRequisito      = Field(default=TipoRequisito.documento)
    obligatorio: bool               = Field(default=True)
    descripcion: Optional[str]      = Field(default=None, sa_column=Column(Text))
    creado_en:   Optional[datetime] = Field(default_factory=datetime.now)

    estados: List["RequisitoAlumno"] = Relationship(
        back_populates="requisito",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )


class RequisitoAlumno(SQLModel, table=True):
    __tablename__ = "requisitos_alumno"

    idRequisito: int = Field(foreign_key="requisitos_curso.idRequisito", primary_key=True)
    idAlumno:    int = Field(foreign_key="alumno.idAlumno", primary_key=True)  

    cumplido:           bool               = Field(default=False)
    fecha_cumplimiento: Optional[datetime] = Field(default=None, nullable=True)
    observacion:        Optional[str]      = Field(default=None, sa_column=Column(Text, nullable=True))
    actualizado_en:     Optional[datetime] = Field(default_factory=datetime.now)  

    requisito: Optional[RequisitoCurso] = Relationship(back_populates="estados")
