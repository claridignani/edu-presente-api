from datetime import datetime
from fastapi import HTTPException
from sqlmodel import select
from app.dependencies import SessionDep
from app.models.intervencion import Intervencion, TipoIntervencion


def _tags_to_str(tags: list[str] | None) -> str | None:
    if not tags:
        return None
    cleaned = [t.strip() for t in tags if str(t).strip()]
    return ",".join(cleaned) if cleaned else None


def _str_to_tags(s: str | None) -> list[str] | None:
    if not s:
        return None
    out = [x.strip() for x in s.split(",") if x.strip()]
    return out or None


def crear_intervencion(
    db: SessionDep,
    idAlerta: int,
    tipo: TipoIntervencion,
    detalle: str,
    detalleFormal: str | None,
    tags: list[str] | None,
    creadoPor: int | None = None,
) -> Intervencion:
    if not detalle.strip():
        raise HTTPException(status_code=400, detail="El detalle es obligatorio")

    item = Intervencion(
        idAlerta=idAlerta,
        tipo=tipo,
        detalle=detalle.strip(),
        detalleFormal=detalleFormal.strip() if detalleFormal else None,
        tags=_tags_to_str(tags),
        creadoPor=creadoPor,
        fecha=datetime.utcnow(),
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def listar_intervenciones(db: SessionDep, idAlerta: int) -> list[dict]:
    stmt = select(Intervencion).where(Intervencion.idAlerta == idAlerta).order_by(Intervencion.fecha.desc())
    rows = db.exec(stmt).all()
    return [
        {
            "idIntervencion": r.idIntervencion,
            "idAlerta": r.idAlerta,
            "fecha": r.fecha,
            "tipo": r.tipo,
            "detalle": r.detalle,
            "detalleFormal": r.detalleFormal,
            "tags": _str_to_tags(r.tags),
        }
        for r in rows
    ]
