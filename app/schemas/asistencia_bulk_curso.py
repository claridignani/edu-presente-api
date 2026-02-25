from datetime import date
from typing import List, Optional
from pydantic import BaseModel, Field
from app.schemas.asistencia import AsistenciaEstado

class AsistenciaOverride(BaseModel):
    idAlumno: int
    estado: AsistenciaEstado
    lluvia: Optional[bool] = None

class AsistenciaCursoFechaBulkRequest(BaseModel):
    fecha: date
    default_estado: AsistenciaEstado = AsistenciaEstado.Presente
    lluvia: bool = False
    overrides: List[AsistenciaOverride] = Field(default_factory=list)

class AsistenciaCursoRangoBulkRequest(BaseModel):
    desde: date
    hasta: date
    # por defecto Lun–Vie
    weekdays: List[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4])  # 0=Lun ... 6=Dom

    default_estado: AsistenciaEstado = AsistenciaEstado.Presente
    lluvia: bool = False
    overrides: List[AsistenciaOverride] = Field(default_factory=list)

    # opcional: si querés cargar SOLO algunos alumnos (ej tus 3)
    solo_alumnos: Optional[List[int]] = None