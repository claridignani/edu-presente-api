from __future__ import annotations
from typing import List, Optional
from pydantic import BaseModel


# ── Períodos ──────────────────────────────────────────────────────

class PeriodoIn(BaseModel):
    key: str          # 'T1' | 'T2' | 'T3' | 'PROF' | 'ANUAL'
    label: str
    short_label: str
    desde: str        # yyyy-MM-dd
    hasta: str        # yyyy-MM-dd
    color: str = "#6b7280"


class PeriodoOut(PeriodoIn):
    id: int


# ── Recesos ───────────────────────────────────────────────────────

class RecesoIn(BaseModel):
    desde: str        # yyyy-MM-dd
    hasta: str        # yyyy-MM-dd
    label: str = "Receso"


class RecesoOut(RecesoIn):
    id: int


# ── Ciclo lectivo ─────────────────────────────────────────────────

class CicloLectivoIn(BaseModel):
    anio: int
    inicio: str       # yyyy-MM-dd
    fin: str          # yyyy-MM-dd
    periodos: List[PeriodoIn] = []
    recesos: List[RecesoIn] = []


class CicloLectivoOut(BaseModel):
    id: int
    CUE: str
    anio: int
    inicio: str
    fin: str
    periodos: List[PeriodoOut] = []
    recesos: List[RecesoOut] = []


# ── Payload de actualización parcial ─────────────────────────────

class CicloLectivoUpdate(BaseModel):
    inicio: Optional[str] = None
    fin: Optional[str] = None
    periodos: Optional[List[PeriodoIn]] = None   # reemplaza todos los períodos
    recesos: Optional[List[RecesoIn]] = None     # reemplaza todos los recesos