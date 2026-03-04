from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlmodel import SQLModel, Field
from sqlalchemy import Column, Date, DateTime, text


class PaseSalida(SQLModel, table=True):
    __tablename__ = "pase_salida"

    idPase: Optional[int] = Field(default=None, primary_key=True)

    # Alumno e inscripción activa al momento de la baja
    idAlumno: int = Field(foreign_key="alumno.idAlumno", nullable=False, index=True)
    idInscripcion: Optional[int] = Field(
        default=None,
        foreign_key="inscriptos.idInscripcion",
        nullable=True,
    )

    # Movimiento de promoción (si viene del flujo mover-alumnos, si no es None)
    idMovimiento: Optional[int] = Field(
        default=None,
        foreign_key="movimiento_promocion.idMovimiento",
        nullable=True,
    )

    # Escuela que emite el pase
    cueOrigen: str = Field(max_length=20, nullable=False, index=True)

    # CON_PASE | SIN_PASE
    tipoPase: str = Field(max_length=20, nullable=False)

    # Motivo de la baja
    motivo: str = Field(max_length=50, nullable=False)

    # Acciones previas al abandono (solo SIN_PASE) — guardamos como string CSV
    # ej: "CONTACTO_ADULTOS,ARTICULACION_EOE"
    accionesPrevias: Optional[str] = Field(default=None, nullable=True)

    # Escuela destino (solo CON_PASE)
    cueDestino: Optional[str] = Field(default=None, max_length=20, nullable=True)
    nombreEscuelaDestino: Optional[str] = Field(default=None, max_length=255, nullable=True)

    # Número correlativo: CUE-YYYY-NNNN
    nroPase: str = Field(max_length=30, nullable=False, unique=True, index=True)

    fecha: date = Field(sa_column=Column(Date, nullable=False))

    # Activo | Anulado
    estado: str = Field(default="Activo", max_length=20, nullable=False)

    created_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(
            DateTime,
            nullable=False,
            server_default=text("CURRENT_TIMESTAMP"),
        ),
    )