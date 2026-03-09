from __future__ import annotations

from fastapi import HTTPException
from sqlmodel import select

from app.dependencies import SessionDep
from app.models.ciclo_lectivo import CicloLectivoConfig, PeriodoCiclo, RecesoCiclo
from app.schemas.ciclo_lectivo import (
    CicloLectivoIn,
    CicloLectivoOut,
    CicloLectivoUpdate,
    PeriodoOut,
    RecesoOut,
)


# ── Helpers ───────────────────────────────────────────────────────

def _to_out(ciclo: CicloLectivoConfig, db: SessionDep) -> CicloLectivoOut:
    periodos = db.exec(
        select(PeriodoCiclo).where(PeriodoCiclo.ciclo_id == ciclo.id)
    ).all()
    recesos = db.exec(
        select(RecesoCiclo).where(RecesoCiclo.ciclo_id == ciclo.id)
    ).all()

    return CicloLectivoOut(
        id=ciclo.id,
        CUE=ciclo.CUE,
        anio=ciclo.anio,
        inicio=ciclo.inicio,
        fin=ciclo.fin,
        periodos=[PeriodoOut(id=p.id, key=p.key, label=p.label, short_label=p.short_label, desde=p.desde, hasta=p.hasta, color=p.color) for p in periodos],
        recesos=[RecesoOut(id=r.id, desde=r.desde, hasta=r.hasta, label=r.label) for r in recesos],
    )


def _delete_periodos_y_recesos(ciclo_id: int, db: SessionDep) -> None:
    for p in db.exec(select(PeriodoCiclo).where(PeriodoCiclo.ciclo_id == ciclo_id)).all():
        db.delete(p)
    for r in db.exec(select(RecesoCiclo).where(RecesoCiclo.ciclo_id == ciclo_id)).all():
        db.delete(r)
    db.flush()


# ── CRUD ──────────────────────────────────────────────────────────

def listar_ciclos(cue: str, db: SessionDep) -> list[CicloLectivoOut]:
    ciclos = db.exec(
        select(CicloLectivoConfig)
        .where(CicloLectivoConfig.CUE == cue)
        .order_by(CicloLectivoConfig.anio.desc())
    ).all()
    return [_to_out(c, db) for c in ciclos]


def get_ciclo(cue: str, anio: int, db: SessionDep) -> CicloLectivoOut:
    ciclo = db.exec(
        select(CicloLectivoConfig)
        .where(CicloLectivoConfig.CUE == cue, CicloLectivoConfig.anio == anio)
    ).first()
    if not ciclo:
        raise HTTPException(status_code=404, detail=f"No hay ciclo lectivo {anio} para la escuela {cue}")
    return _to_out(ciclo, db)


def crear_ciclo(cue: str, payload: CicloLectivoIn, db: SessionDep) -> CicloLectivoOut:
    existente = db.exec(
        select(CicloLectivoConfig)
        .where(CicloLectivoConfig.CUE == cue, CicloLectivoConfig.anio == payload.anio)
    ).first()
    if existente:
        raise HTTPException(
            status_code=409,
            detail=f"Ya existe un ciclo lectivo {payload.anio} para esta escuela. Usá PUT para editarlo.",
        )

    ciclo = CicloLectivoConfig(CUE=cue, anio=payload.anio, inicio=payload.inicio, fin=payload.fin)
    db.add(ciclo)
    db.flush()

    for p in payload.periodos:
        db.add(PeriodoCiclo(ciclo_id=ciclo.id, key=p.key, label=p.label, short_label=p.short_label, desde=p.desde, hasta=p.hasta, color=p.color))
    for r in payload.recesos:
        db.add(RecesoCiclo(ciclo_id=ciclo.id, desde=r.desde, hasta=r.hasta, label=r.label))

    db.commit()
    db.refresh(ciclo)
    return _to_out(ciclo, db)


def actualizar_ciclo(cue: str, anio: int, payload: CicloLectivoUpdate, db: SessionDep) -> CicloLectivoOut:
    ciclo = db.exec(
        select(CicloLectivoConfig)
        .where(CicloLectivoConfig.CUE == cue, CicloLectivoConfig.anio == anio)
    ).first()
    if not ciclo:
        raise HTTPException(status_code=404, detail=f"No hay ciclo lectivo {anio} para la escuela {cue}")

    if payload.inicio is not None:
        ciclo.inicio = payload.inicio
    if payload.fin is not None:
        ciclo.fin = payload.fin

    db.add(ciclo)
    db.flush()

    # Reemplaza períodos si vienen en el payload
    if payload.periodos is not None:
        for p in db.exec(select(PeriodoCiclo).where(PeriodoCiclo.ciclo_id == ciclo.id)).all():
            db.delete(p)
        db.flush()
        for p in payload.periodos:
            db.add(PeriodoCiclo(ciclo_id=ciclo.id, key=p.key, label=p.label, short_label=p.short_label, desde=p.desde, hasta=p.hasta, color=p.color))

    # Reemplaza recesos si vienen en el payload
    if payload.recesos is not None:
        for r in db.exec(select(RecesoCiclo).where(RecesoCiclo.ciclo_id == ciclo.id)).all():
            db.delete(r)
        db.flush()
        for r in payload.recesos:
            db.add(RecesoCiclo(ciclo_id=ciclo.id, desde=r.desde, hasta=r.hasta, label=r.label))

    db.commit()
    db.refresh(ciclo)
    return _to_out(ciclo, db)


def eliminar_ciclo(cue: str, anio: int, db: SessionDep) -> dict:
    ciclo = db.exec(
        select(CicloLectivoConfig)
        .where(CicloLectivoConfig.CUE == cue, CicloLectivoConfig.anio == anio)
    ).first()
    if not ciclo:
        raise HTTPException(status_code=404, detail=f"No hay ciclo lectivo {anio} para la escuela {cue}")

    _delete_periodos_y_recesos(ciclo.id, db)
    db.delete(ciclo)
    db.commit()
    return {"ok": True, "anio": anio}