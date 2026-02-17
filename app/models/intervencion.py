# app/models/intervencion.py
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from sqlmodel import SQLModel, Field
from sqlalchemy import Column, DateTime, text
from sqlalchemy import Enum as SAEnum


class TipoIntervencion(str, Enum):
    Llamado = "Llamado"
    Entrevista = "Entrevista"
    Visita = "Visita"
    Mensaje = "Mensaje"
    Informe = "Informe"
    Otro = "Otro"


def enum_values(enum_cls):
    return [e.value for e in enum_cls]


class Intervencion(SQLModel, table=True):
    __tablename__ = "intervencion"

    idIntervencion: Optional[int] = Field(default=None, primary_key=True)

    idAlerta: int = Field(foreign_key="alerta.idAlerta", index=True, nullable=False)

    tipo: TipoIntervencion | None = Field(
        default=None,
        sa_column=Column(
            SAEnum(TipoIntervencion, values_callable=enum_values, native_enum=False),
            nullable=True,
        ),
    )

    detalle: str = Field(max_length=2000, nullable=False)

    # existen en DB
    detalleFormal: str | None = Field(default=None, max_length=3000)
    tags: str | None = Field(default=None, max_length=200)

    created_by: int | None = Field(default=None, nullable=True)

    # existe en DB y tiene default CURRENT_TIMESTAMP
    created_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    )
