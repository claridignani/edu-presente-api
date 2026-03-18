from __future__ import annotations
from typing import Optional
from datetime import date
from sqlmodel import Field
from app.schemas.rol import RolBase


class Rol(RolBase, table=True):
    __tablename__ = "rol"

    idUsuario: int = Field(foreign_key="usuario.idUsuario", primary_key=True)
    CUE: str = Field(foreign_key="escuela.CUE", primary_key=True, max_length=20)
    fechaBaja: Optional[date] = Field(default=None, nullable=True)
    motivoBaja: Optional[str] = Field(default=None, nullable=True)