from datetime import date, datetime, timedelta
import secrets
from fastapi import HTTPException
from sqlmodel import select

from app.dependencies import SessionDep
from app.models.invitacion_docente import InvitacionDocente
from app.models.curso import Curso
from app.models.curso_docente import CursoDocente
from app.schemas.rol import RolDescripcion, RolEstado
from app.services.rol_service import get_one_rol

def _gen_code(cue: str) -> str:
    suf = secrets.token_urlsafe(6).replace("-", "").replace("_", "")[:6].upper()
    return f"DOC-{cue}-{suf}"

def get_invitacion_por_codigo(db: SessionDep, codigo: str) -> InvitacionDocente:
    inv = db.exec(select(InvitacionDocente).where(InvitacionDocente.codigo == codigo)).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Código inválido")
    return inv

def crear_invitacion_docente(
    db: SessionDep,
    director_id: int,
    idCurso: int,
    tipo: str,
    fechaDesde: date | None = None,
    fechaHasta: date | None = None,
):
    # 1) curso existe + CUE
    curso = db.get(Curso, idCurso)
    if not curso:
        raise HTTPException(status_code=404, detail="Curso no encontrado")
    cue = curso.CUE

    # 2) validar director activo en esa escuela (CUE del curso)
    rol_dir = get_one_rol(director_id, cue, db)
    if (not rol_dir) or rol_dir.estado != RolEstado.Activo or rol_dir.descripcion != RolDescripcion.Director:
        raise HTTPException(status_code=403, detail="Solo Director Activo puede generar invitaciones")

    # 3) validar fechas
    tipo = (tipo or "").strip().capitalize()
    hoy = date.today()

    if fechaDesde is None:
        fechaDesde = hoy

    if tipo == "Titular":
        fechaHasta = None
    else:
        # Suplente: default 30 días desde fechaDesde
        if fechaHasta is None:
            fechaHasta = fechaDesde + timedelta(days=30)

    if fechaDesde and fechaHasta and fechaHasta < fechaDesde:
        raise HTTPException(status_code=400, detail="fechaHasta no puede ser menor a fechaDesde")

    # 4) generar único
    for _ in range(10):
        codigo = _gen_code(cue)
        existe = db.exec(select(InvitacionDocente).where(InvitacionDocente.codigo == codigo)).first()
        if not existe:
            inv = InvitacionDocente(
                codigo=codigo,
                CUE=cue,
                idCurso=idCurso,
                tipo=tipo,
                usada=False,
                fechaDesde=fechaDesde,
                fechaHasta=fechaHasta,
            )
            db.add(inv)
            db.commit()
            db.refresh(inv)
            return inv

    raise HTTPException(status_code=500, detail="No se pudo generar código")

def consumir_invitacion_docente(db: SessionDep, idUsuario: int, codigo: str) -> InvitacionDocente:
    inv = get_invitacion_por_codigo(db, codigo)

    if inv.usada:
        raise HTTPException(status_code=409, detail="Código ya utilizado")
    
    hoy = date.today()
    if inv.fechaDesde and hoy < inv.fechaDesde:
        raise HTTPException(status_code=403, detail="El código todavía no está habilitado")
    if inv.fechaHasta and hoy > inv.fechaHasta:
        raise HTTPException(status_code=403, detail="El código ya venció")

    existente = db.get(CursoDocente, (inv.idCurso, idUsuario))
    if existente:
        raise HTTPException(
            status_code=409,
            detail="El docente ya está asignado a este curso"
        )

    db.add(
        CursoDocente(
            idCurso=inv.idCurso,
            idUsuario=idUsuario,
            tipo=inv.tipo,
            fechaDesde=inv.fechaDesde,
            fechaHasta=inv.fechaHasta,
        )
    )

    inv.usada = True
    inv.fechaUso = datetime.utcnow()
    db.add(inv)

    db.commit()
    db.refresh(inv)
    return inv
