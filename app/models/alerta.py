# app/models/alerta.py
from __future__ import annotations

from datetime import datetime, date
from enum import Enum
from typing import Optional

from sqlmodel import SQLModel, Field
from sqlalchemy import Column, DateTime, text
from sqlalchemy import Enum as SAEnum


class EstadoAlerta(str, Enum):
    PENDIENTE = "PENDIENTE"
    EN_PROCESO = "EN_PROCESO"
    CRITICO = "CRITICO"
    RESUELTO = "RESUELTO"


class MotivoAlerta(str, Enum):
    INASISTENCIAS_CONSECUTIVAS = "INASISTENCIAS_CONSECUTIVAS"
    INASISTENCIAS_REITERADAS   = "INASISTENCIAS_REITERADAS"
    LLEGADAS_TARDE             = "LLEGADAS_TARDE"
    CONDUCTA                   = "CONDUCTA"
    SALUD                      = "SALUD"
    FAMILIAR                   = "FAMILIAR"
    PEDAGOGICO                 = "PEDAGOGICO"
    OTRO                       = "OTRO"


def enum_values(enum_cls):
    return [e.value for e in enum_cls]


class Alerta(SQLModel, table=True):
    __tablename__ = "alerta"

    idAlerta: Optional[int] = Field(default=None, primary_key=True)

    cue: str = Field(foreign_key="escuela.CUE", max_length=20, nullable=False, index=True)

    idCurso:  int = Field(foreign_key="curso.idCurso",   index=True, nullable=False)
    idAlumno: int = Field(foreign_key="alumno.idAlumno", index=True, nullable=False)

    # ✅ FK al usuario que creó la alerta — necesario para filtrar alertas del docente
    created_by: Optional[int] = Field(
        default=None,
        foreign_key="usuario.idUsuario",
        index=True,
        nullable=True,
    )

    motivo: MotivoAlerta = Field(
        sa_column=Column(
            SAEnum(
                MotivoAlerta,
                values_callable=enum_values,
                native_enum=False,
                name="motivo_alerta",
            ),
            nullable=False,
        ),
        default=MotivoAlerta.INASISTENCIAS_CONSECUTIVAS,
    )

    estado: EstadoAlerta = Field(
        sa_column=Column(
            SAEnum(
                EstadoAlerta,
                values_callable=enum_values,
                native_enum=False,
                name="estado_alerta",
            ),
            nullable=False,
        ),
        default=EstadoAlerta.PENDIENTE,
    )

    consecutivas: int = Field(default=0, nullable=False)

    fechaInicioRacha: Optional[date] = Field(default=None)
    fechaFinRacha:    Optional[date] = Field(default=None)

    archivada: bool = Field(default=False, index=True, nullable=False)
    detalle: Optional[str] = Field(default=None, max_length=500)

    ultimaAccionAt: Optional[datetime] = Field(default=None)
    resueltaAt:     Optional[datetime] = Field(default=None)

    created_at: datetime = Field(
        sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    )