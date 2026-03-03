from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlmodel import SQLModel, Field
from sqlalchemy import Column, Date, DateTime, text


class PaseEntrada(SQLModel, table=True):
    __tablename__ = "pase_entrada"

    idPaseEntrada: Optional[int] = Field(default=None, primary_key=True)

    # Alumno que ingresa
    idAlumno: int = Field(foreign_key="alumno.idAlumno", nullable=False, index=True)

    # Preinscripción asociada (si el alumno ya estaba preinscripto)
    idPreinscripcion: Optional[int] = Field(
        default=None,
        foreign_key="preinscripcion.idPreinscripcion",
        nullable=True,
    )

    # Escuela receptora
    cueDestino: str = Field(max_length=20, nullable=False, index=True)

    # Escuela de origen (de donde viene el alumno)
    cueOrigen: Optional[str] = Field(default=None, max_length=20, nullable=True)
    nombreEscuelaOrigen: Optional[str] = Field(default=None, max_length=255, nullable=True)

    # Número de pase que trae de la escuela anterior (opcional)
    nroPaseOrigen: Optional[str] = Field(default=None, max_length=30, nullable=True)

    fecha: date = Field(sa_column=Column(Date, nullable=False))

    # Pendiente | Confirmado | Anulado
    estado: str = Field(default="Pendiente", max_length=20, nullable=False)

    created_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(
            DateTime,
            nullable=False,
            server_default=text("CURRENT_TIMESTAMP"),
        ),
    )