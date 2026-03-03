from datetime import date, datetime, timedelta
import secrets
import re
from fastapi import HTTPException
from sqlmodel import select

from app.dependencies import SessionDep
from app.models.invitacion_docente import InvitacionDocente
from app.models.curso import Curso
from app.models.curso_docente import CursoDocente
from app.schemas.rol import RolDescripcion, RolEstado
from app.services.rol_service import get_one_rol


# ── Helpers de turno ──────────────────────────────────────────────────────────

# Franjas horarias que ocupa cada valor de Curso.turno
_TURNOS_OCUPADOS: dict[str, set[str]] = {
    "Manana":     {"Manana"},
    "Tarde":      {"Tarde"},
    "DobleTurno": {"Manana", "Tarde"},   # bloquea ambos
}


def _franjas(turno) -> set[str]:
    t = turno.value if hasattr(turno, "value") else str(turno)
    return _TURNOS_OCUPADOS.get(t, {t})


_TURNO_UI = {"Manana": "Mañana", "Tarde": "Tarde", "DobleTurno": "Doble turno"}


def _hay_conflicto_turno(
    db: SessionDep,
    idUsuario: int,
    turno_nuevo,
    excluir_curso: int | None = None,
) -> "Curso | None":
    franjas_nuevas = _franjas(turno_nuevo)

    stmt = (
        select(CursoDocente, Curso)
        .join(Curso, Curso.idCurso == CursoDocente.idCurso)
        .where(
            CursoDocente.idUsuario == idUsuario,
            CursoDocente.estado == "Activo",
            # ← sin filtro de tipo, aplica a Titular y Suplente
        )
    )
    if excluir_curso:
        stmt = stmt.where(CursoDocente.idCurso != excluir_curso)

    for _cd, curso in db.exec(stmt).all():
        if _franjas(curso.turno) & franjas_nuevas:
            return curso

    return None



# ── Helpers internos ──────────────────────────────────────────────────────────

def _gen_code(cue: str) -> str:
    cue_clean = re.sub(r"\D", "", str(cue))
    suf = secrets.token_urlsafe(6).replace("-", "").replace("_", "")[:6].upper()
    return f"DOC-{cue_clean}-{suf}"


def get_invitacion_por_codigo(db: SessionDep, codigo: str) -> InvitacionDocente:
    inv = db.exec(
        select(InvitacionDocente).where(InvitacionDocente.codigo == codigo)
    ).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Código inválido")
    return inv


# ── Crear invitación ──────────────────────────────────────────────────────────

def crear_invitacion_docente(
    db: SessionDep,
    director_id: int,
    idCurso: int,
    tipo: str,
    idUsuario: int | None = None,
    fechaDesde: date | None = None,
    fechaHasta: date | None = None,
):
    # 1) curso existe
    curso = db.get(Curso, idCurso)
    if not curso:
        raise HTTPException(status_code=404, detail="Curso no encontrado")
    cue = curso.CUE

    # 2) director activo
    rol_dir = get_one_rol(director_id, cue, db)
    if (
        not rol_dir
        or rol_dir.estado != RolEstado.Activo
        or rol_dir.descripcion != RolDescripcion.Director
    ):
        raise HTTPException(status_code=403, detail="Solo un Director Activo puede generar invitaciones")

    tipo = (tipo or "").strip().capitalize()

    # 3) Si se especificó un docente concreto, validar turno ya acá
    if idUsuario:
        conflicto = _hay_conflicto_turno(db, idUsuario, curso.turno)
        if conflicto:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"El/La docente ya es Titular en turno "
                    f"{_TURNO_UI.get(conflicto.turno, str(conflicto.turno))} "
                    f"({conflicto.nombre} {conflicto.division}) "
                    f"y no puede asumir otro cargo Titular en turno "
                    f"{_TURNO_UI.get(curso.turno, str(curso.turno))}."
                ),
            )

        # Verificar que no esté ya asignado al curso
        existente = db.get(CursoDocente, (idCurso, idUsuario))
        if existente and existente.estado == "Activo":
            raise HTTPException(
                status_code=409,
                detail="El/La docente ya está asignado/a a este curso.",
            )

    # 4) Para Titular sin docente específico: verificar que el curso no tenga ya un titular
    if tipo == "Titular" and not idUsuario:
        titular_existente = db.exec(
            select(CursoDocente).where(
                CursoDocente.idCurso == idCurso,
                CursoDocente.tipo == "Titular",
                CursoDocente.estado == "Activo",
            )
        ).first()
        if titular_existente:
            raise HTTPException(
                status_code=409,
                detail=(
                    "El curso ya tiene un/a Titular asignado/a. "
                    "Quitá esa asignación antes de generar una nueva invitación Titular."
                ),
            )

    # 5) fechas
    hoy = date.today()
    fechaDesde = fechaDesde or hoy
    if tipo == "Titular":
        fechaHasta = None
    else:
        fechaHasta = fechaHasta or (fechaDesde + timedelta(days=30))

    if fechaDesde and fechaHasta and fechaHasta < fechaDesde:
        raise HTTPException(status_code=400, detail="fechaHasta no puede ser menor a fechaDesde")

    # 6) código único
    for _ in range(10):
        codigo = _gen_code(cue)
        if not db.exec(
            select(InvitacionDocente).where(InvitacionDocente.codigo == codigo)
        ).first():
            inv = InvitacionDocente(
                codigo=codigo,
                CUE=cue,
                idCurso=idCurso,
                tipo=tipo,
                idUsuario=idUsuario,   # ← NUEVO
                usada=False,
                fechaDesde=fechaDesde,
                fechaHasta=fechaHasta,
            )
            db.add(inv)
            db.commit()
            db.refresh(inv)
            return inv

    raise HTTPException(status_code=500, detail="No se pudo generar el código")


def consumir_invitacion_docente(
    db: SessionDep, idUsuario: int, codigo: str
) -> InvitacionDocente:
    inv = get_invitacion_por_codigo(db, codigo)

    if inv.usada:
        raise HTTPException(status_code=409, detail="Código ya utilizado")

    # ── Si la invitación es para un docente específico, verificar que sea él ──
    if inv.idUsuario and inv.idUsuario != idUsuario:
        raise HTTPException(
            status_code=403,
            detail="Este código fue generado para otro/a docente.",
        )

    hoy = date.today()
    if inv.fechaDesde and hoy < inv.fechaDesde:
        raise HTTPException(status_code=403, detail="El código todavía no está habilitado")
    if inv.fechaHasta and hoy > inv.fechaHasta:
        raise HTTPException(status_code=403, detail="El código ya venció")

    # ── ya asignado al mismo curso ────────────────────────────────
    existente = db.get(CursoDocente, (inv.idCurso, idUsuario))
    if existente and existente.estado == "Activo":
        raise HTTPException(
            status_code=409, detail="El/La docente ya está asignado/a a este curso"
        )

    # ── validación de turno ─────────────────────────
    curso = db.get(Curso, inv.idCurso)
    turno_nuevo = curso.turno if curso else ""
    conflicto = _hay_conflicto_turno(db, idUsuario, turno_nuevo)
    if conflicto:
            raise HTTPException(
            status_code=409,
            detail=(
                f"El/La docente ya tiene asignado el turno "
                f"{_TURNO_UI.get(str(conflicto.turno.value if hasattr(conflicto.turno, 'value') else conflicto.turno), str(conflicto.turno))} "
                f"({conflicto.nombre} {conflicto.division}) "
                f"y no puede tomar otro curso en turno "
                f"{_TURNO_UI.get(str(turno_nuevo.value if hasattr(turno_nuevo, 'value') else turno_nuevo), str(turno_nuevo))}."
            ),
        )

    # ── registrar ─────────────────────────────────────────────────
    if existente:
        existente.tipo = inv.tipo
        existente.fechaDesde = inv.fechaDesde
        existente.fechaHasta = inv.fechaHasta
        existente.estado = "Activo"
        db.add(existente)
    else:
        db.add(CursoDocente(
            idCurso=inv.idCurso,
            idUsuario=idUsuario,
            tipo=inv.tipo,
            fechaDesde=inv.fechaDesde,
            fechaHasta=inv.fechaHasta,
        ))

    inv.usada = True
    inv.fechaUso = datetime.utcnow()
    db.add(inv)
    db.commit()
    db.refresh(inv)
    return inv