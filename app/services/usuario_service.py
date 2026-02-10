from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated

from fastapi import HTTPException, Query
from sqlmodel import select

from app.core.security import get_password_hash
from app.dependencies import SessionDep

from app.models.usuario import Usuario
from app.models.rol import Rol
from app.models.escuela import Escuela
from app.models.curso_docente import CursoDocente

from app.schemas.usuario import UsuarioCreate, UsuarioUpdate
from app.schemas.rol import RolDescripcion, RolEstado

import app.services.invitacion_docente_service as inv_service


def _normalize_mail(mail: str) -> str:
    return str(mail).strip().lower()


def _normalize_cue(cue: str) -> str:
    cue_norm = str(cue).strip().upper().replace(" ", "")
    cue_norm = re.sub(r"[^0-9A-Z]", "", cue_norm)
    return cue_norm


# =========================
# LISTADOS
# =========================
def get_all_usuarios(db: SessionDep, offset: int, limit: Annotated[int, Query(le=100)]):
    return db.exec(select(Usuario).offset(offset).limit(limit)).all()


def get_all_usuarios_admin(db: SessionDep, offset: int = 0, limit: int = 100):
    """
    Devuelve Usuario + Rol + Escuela (outer joins) para el listado admin.
    Incluye usuarios aunque no tengan roles/escuelas.
    Retorna: list[tuple[Usuario, Rol|None, Escuela|None]]
    """
    stmt = (
        select(Usuario, Rol, Escuela)
        .outerjoin(Rol, Rol.idUsuario == Usuario.idUsuario)
        .outerjoin(Escuela, Escuela.CUE == Rol.CUE)
        .offset(offset)
        .limit(limit)
    )
    return db.exec(stmt).all()


def get_usuario_admin_by_id(db: SessionDep, idUsuario: int):
    """
    Igual que get_all_usuarios_admin pero filtrado por usuario.
    """
    stmt = (
        select(Usuario, Rol, Escuela)
        .outerjoin(Rol, Rol.idUsuario == Usuario.idUsuario)
        .outerjoin(Escuela, Escuela.CUE == Rol.CUE)
        .where(Usuario.idUsuario == idUsuario)
    )
    return db.exec(stmt).all()


# =========================
# GETS
# =========================
def get_usuario_by_dni(db: SessionDep, dni: str):
    dni = re.sub(r"\D+", "", str(dni))
    statement = select(Usuario).where(Usuario.dni == dni)
    return db.exec(statement).first()


def get_usuario_by_mail(db: SessionDep, mail: str):
    mail = _normalize_mail(mail)
    statement = select(Usuario).where(Usuario.mailABC == mail)
    return db.exec(statement).first()


def get_one_usuario(idUsuario: int, db: SessionDep):
    return db.get(Usuario, idUsuario)


# =========================
# CREATE
# =========================
def add_usuario(usuario: UsuarioCreate, db: SessionDep):
    # --------------------------------------------------
    # 1) Normalizaciones
    # --------------------------------------------------
    dni_norm = re.sub(r"\D+", "", str(usuario.dni))
    mail_norm = _normalize_mail(usuario.mailABC)

    # --------------------------------------------------
    # 2) Registro con código de invitación (solo docentes nuevos)
    # --------------------------------------------------
    invitacion = None

    if usuario.codigoInvitacion:
        # Si ya existe el usuario, no puede registrarse “de nuevo” con código
        if get_usuario_by_dni(db, dni_norm) or get_usuario_by_mail(db, mail_norm):
            raise HTTPException(
                status_code=409,
                detail=(
                    "Este código es para docentes nuevos. "
                    "Si ya tenés cuenta, iniciá sesión y cargalo desde tu panel docente."
                ),
            )

        invitacion = inv_service.get_invitacion_por_codigo(db, usuario.codigoInvitacion)

        if invitacion.usada:
            raise HTTPException(status_code=409, detail="El código de invitación ya fue utilizado")

        # Forzar rol y escuela desde la invitación
        rol_final = RolDescripcion.Docente
        escuelas_finales = [invitacion.CUE]

    else:
        # Registro normal: validar unicidad
        if get_usuario_by_dni(db, dni_norm):
            raise HTTPException(status_code=400, detail="Ya existe un usuario con este DNI")
        if get_usuario_by_mail(db, mail_norm):
            raise HTTPException(status_code=400, detail="Ya existe un usuario con este email")

        rol_final = usuario.rol
        escuelas_finales = usuario.escuelasCUE

    # --------------------------------------------------
    # 3) Crear usuario
    # --------------------------------------------------
    usuario_data = usuario.model_dump(exclude={"escuelasCUE", "rol", "codigoInvitacion"})
    usuario_data["dni"] = dni_norm
    usuario_data["mailABC"] = mail_norm

    db_usuario = Usuario.model_validate(usuario_data)
    db_usuario.contrasena = get_password_hash(usuario.contrasena)

    db.add(db_usuario)
    db.flush()  # obtiene idUsuario

    # --------------------------------------------------
    # 4) Crear roles (estado default = Pendiente)
    # --------------------------------------------------
    for cue in escuelas_finales:
        cue_norm = _normalize_cue(cue)
        nuevo_rol = Rol(
            descripcion=rol_final,
            idUsuario=db_usuario.idUsuario,
            CUE=cue_norm,
            estado=RolEstado.Pendiente,
        )
        db.add(nuevo_rol)

    # --------------------------------------------------
    # 5) Si vino por invitación → asignar al curso y marcar usada
    # --------------------------------------------------
    if invitacion:
        existente = db.get(CursoDocente, (invitacion.idCurso, db_usuario.idUsuario))
        if existente:
            raise HTTPException(status_code=409, detail="El usuario ya está asignado a este curso")

        curso_docente = CursoDocente(
            idCurso=invitacion.idCurso,
            idUsuario=db_usuario.idUsuario,
            tipo=invitacion.tipo,
            fechaDesde=invitacion.fechaDesde,
            fechaHasta=invitacion.fechaHasta,
        )
        db.add(curso_docente)

        invitacion.usada = True
        invitacion.fechaUso = datetime.utcnow()
        db.add(invitacion)

    db.commit()
    db.refresh(db_usuario)
    return db_usuario


# =========================
# UPDATE
# =========================
def change_usuario(usuario_nuevo: UsuarioUpdate, usuario_existente: Usuario, db: SessionDep):
    usuario_data = usuario_nuevo.model_dump(exclude_unset=True)

    # Si actualiza mail, normalizar
    if "mailABC" in usuario_data and usuario_data["mailABC"]:
        usuario_data["mailABC"] = _normalize_mail(usuario_data["mailABC"])

    # Si actualiza contraseña, se hashea
    if usuario_nuevo.contrasena:
        usuario_data["contrasena"] = get_password_hash(usuario_nuevo.contrasena)

    # Unicidad DNI
    if "dni" in usuario_data and usuario_data["dni"]:
        usuario_data["dni"] = re.sub(r"\D+", "", str(usuario_data["dni"]))
        otro = get_usuario_by_dni(db, usuario_data["dni"])
        if otro and otro.idUsuario != usuario_existente.idUsuario:
            raise HTTPException(status_code=400, detail="Ya existe un usuario con este DNI")

    # Unicidad mail
    if "mailABC" in usuario_data and usuario_data["mailABC"]:
        otro = get_usuario_by_mail(db, usuario_data["mailABC"])
        if otro and otro.idUsuario != usuario_existente.idUsuario:
            raise HTTPException(status_code=400, detail="Ya existe un usuario con este email")

    usuario_existente.sqlmodel_update(usuario_data)
    db.add(usuario_existente)
    db.commit()
    db.refresh(usuario_existente)
    return usuario_existente


# =========================
# DELETE
# =========================
def delete_one_usuario(usuario: Usuario, db: SessionDep):
    # Si tu DB NO tiene cascade, borrar roles explícitamente
    roles = db.exec(select(Rol).where(Rol.idUsuario == usuario.idUsuario)).all()
    for r in roles:
        db.delete(r)

    db.delete(usuario)
    db.commit()


# =========================
# FILTRO POR ESCUELA + ROL
# =========================
def get_usuarios_by_escuela(tipo: RolDescripcion, CUE: str, db: SessionDep):
    cue = _normalize_cue(CUE)

    statement = (
        select(Usuario)
        .select_from(Usuario)
        .join(Rol, Rol.idUsuario == Usuario.idUsuario)
        .where(
            Rol.estado == RolEstado.Activo,
            Rol.descripcion == tipo,
            Rol.CUE == cue,
        )
    )
    return db.exec(statement).all()
