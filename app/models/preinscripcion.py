from datetime import datetime
from sqlmodel import SQLModel, Field, Relationship
from typing import Optional

class Preinscripcion(SQLModel, table=True):
    idPreinscripcion: int | None = Field(default=None, primary_key=True)

    idAlumno: int = Field(foreign_key="alumno.idAlumno", index=True)
    CUE: str = Field(index=True)
    cicloLectivo: str = Field(index=True)

    estado: str = Field(default="Pendiente")  # Pendiente | Asignada
    fechaCreacion: datetime = Field(default_factory=datetime.utcnow)
