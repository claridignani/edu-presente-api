from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from sqlmodel import SQLModel, Field
from sqlalchemy import Column, DateTime
from sqlalchemy import Enum as SAEnum

from app.core.datetime_utils import now_arg
from app.models.alerta import EstadoAlerta


class TipoIntervencion(str, Enum):
    Llamado = "Llamado"
    Entrevista = "Entrevista"
    Visita = "Visita"
    Mensaje = "Mensaje"
    Informe = "Informe"
    Otro = "Otro"


class EventoHistorial(str, Enum):
    INTERVENCION = "INTERVENCION"
    CAMBIO_ESTADO = "CAMBIO_ESTADO"
    ARCHIVADO = "ARCHIVADO"
    DESARCHIVADO = "DESARCHIVADO"
    CREACION_ALERTA = "CREACION_ALERTA"


def enum_values(enum_cls):
    return [e.value for e in enum_cls]


class Intervencion(SQLModel, table=True):
    __tablename__ = "intervencion"

    idIntervencion: Optional[int] = Field(default=None, primary_key=True)

    idAlerta: int = Field(foreign_key="alerta.idAlerta", index=True, nullable=False)

    evento: EventoHistorial = Field(
        default=EventoHistorial.INTERVENCION,
        sa_column=Column(
            SAEnum(
                EventoHistorial,
                values_callable=enum_values,
                native_enum=False,
                name="evento_historial"
            ),
            nullable=False,
        ),
    )

    tipo: TipoIntervencion | None = Field(
        default=None,
        sa_column=Column(
            SAEnum(
                TipoIntervencion,
                values_callable=enum_values,
                native_enum=False,
                name="tipo_intervencion"
            ),
            nullable=True,
        ),
    )

    detalle: str = Field(max_length=2000, nullable=False)

    detalleFormal: str | None = Field(default=None, max_length=3000)
    tags: str | None = Field(default=None, max_length=200)

    created_by: int | None = Field(default=None, nullable=True)

    actor_nombre: str | None = Field(default=None, max_length=220)
    actor_rol: str | None = Field(default=None, max_length=40)

    estado_anterior: EstadoAlerta | None = Field(
        default=None,
        sa_column=Column(
            SAEnum(
                EstadoAlerta,
                values_callable=enum_values,
                native_enum=False,
                name="estado_alerta_hist"
            ),
            nullable=True,
        ),
    )

    estado_nuevo: EstadoAlerta | None = Field(
        default=None,
        sa_column=Column(
            SAEnum(
                EstadoAlerta,
                values_callable=enum_values,
                native_enum=False,
                name="estado_alerta_hist2"
            ),
            nullable=True,
        ),
    )

    archivada_anterior: bool | None = Field(default=None, nullable=True)
    archivada_nueva: bool | None = Field(default=None, nullable=True)

    created_at: datetime = Field(
        default_factory=now_arg,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )