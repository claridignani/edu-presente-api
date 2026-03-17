# services/mantenimiento_service.py

from datetime import date
from app.models.curso_docente import CursoDocente
from sqlmodel import select

def inactivar_suplencias_vencidas(db) -> int:
    hoy = date.today()
    stmt = select(CursoDocente).where(
        CursoDocente.tipo == "Suplente",
        CursoDocente.estado == "Activo",
        CursoDocente.fechaHasta != None,
        CursoDocente.fechaHasta < hoy,
    )
    vencidas = db.exec(stmt).all()
    for cd in vencidas:
        cd.estado = "Inactivo"
        db.add(cd)
    db.commit()
    return len(vencidas)