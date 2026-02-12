from datetime import date
from sqlmodel import SQLModel, Field

class CursoDocente(SQLModel, table=True):
    __tablename__ = "curso_docente"
    idCurso: int = Field(foreign_key="curso.idCurso", primary_key=True)
    idUsuario: int = Field(foreign_key="usuario.idUsuario", primary_key=True)
    tipo: str = Field(default="Titular")  # Titular | Suplente
    fechaDesde: date | None = None
    fechaHasta: date | None = None
    estado: str = Field(default="Activo") # Activo | Inactivo
