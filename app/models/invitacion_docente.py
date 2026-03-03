from datetime import datetime
from datetime import date as date_only
from sqlmodel import SQLModel, Field

class InvitacionDocente(SQLModel, table=True):
    idInvitacion: int | None = Field(default=None, primary_key=True)

    codigo: str = Field(index=True, unique=True, max_length=64)

    CUE: str = Field(foreign_key="escuela.CUE", index=True)
    idCurso: int = Field(foreign_key="curso.idCurso", index=True)

    tipo: str = Field(default="Suplente", max_length=20)

    # ── docente específico (opcional) ──────────────────────
    idUsuario: int | None = Field(default=None, foreign_key="usuario.idUsuario", nullable=True)

    fechaDesde: date_only | None = None
    fechaHasta: date_only | None = None

    usada: bool = Field(default=False)
    fechaCreacion: datetime = Field(default_factory=datetime.utcnow)
    fechaUso: datetime | None = None