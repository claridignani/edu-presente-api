# app/models/asistencia.py
from datetime import date
from typing import Optional
from sqlmodel import SQLModel, Field

from app.schemas.asistencia import AsistenciaBase


class Asistencia(AsistenciaBase, SQLModel, table=True):
    __tablename__ = "asistencia"

    idCurso:  int  = Field(foreign_key="curso.idCurso",   primary_key=True, index=True)
    idAlumno: int  = Field(foreign_key="alumno.idAlumno", primary_key=True, index=True)
    fecha:    date = Field(primary_key=True, index=True)

    # ── campos de revisión de certificado (ya en AsistenciaBase, se listan
    #    acá solo para dejar explícito el FK a nivel modelo) ──────────────
    revisado_por: Optional[int] = Field(
        default=None,
        foreign_key="usuario.idUsuario",
        index=True,
    )