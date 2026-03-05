from typing import Optional
from sqlmodel import Field, SQLModel


class CicloLectivoConfig(SQLModel, table=True):
    __tablename__ = "ciclo_lectivo_config"

    id: Optional[int] = Field(default=None, primary_key=True)
    CUE: str = Field(index=True)
    anio: int = Field(index=True)
    inicio: str   # yyyy-MM-dd
    fin: str      # yyyy-MM-dd


class PeriodoCiclo(SQLModel, table=True):
    __tablename__ = "periodo_ciclo"

    id: Optional[int] = Field(default=None, primary_key=True)
    ciclo_id: int = Field(foreign_key="ciclo_lectivo_config.id", index=True)
    key: str
    label: str
    short_label: str
    desde: str        # yyyy-MM-dd
    hasta: str        # yyyy-MM-dd
    color: str = Field(default="#6b7280")


class RecesoCiclo(SQLModel, table=True):
    __tablename__ = "receso_ciclo"

    id: Optional[int] = Field(default=None, primary_key=True)
    ciclo_id: int = Field(foreign_key="ciclo_lectivo_config.id", index=True)
    desde: str        # yyyy-MM-dd
    hasta: str        # yyyy-MM-dd
    label: str = Field(default="Receso")