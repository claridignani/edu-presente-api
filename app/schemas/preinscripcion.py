from sqlmodel import SQLModel
from datetime import datetime

class PreinscripcionCreate(SQLModel):
    idAlumno: int
    CUE: str
    cicloLectivo: str

class PreinscripcionPublic(SQLModel):
    idPreinscripcion: int
    idAlumno: int
    CUE: str
    cicloLectivo: str
    estado: str
    fechaCreacion: datetime
