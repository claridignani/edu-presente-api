from __future__ import annotations

from typing import Annotated
from datetime import date, datetime

from fastapi import HTTPException, Query
from sqlmodel import select

from app.core.security import get_password_hash
from app.dependencies import SessionDep

from app.models.usuario import Usuario
from app.models.rol import Rol
from app.models.curso_docente import CursoDocente

from app.schemas.usuario import UsuarioCreate, UsuarioUpdate
from app.schemas.rol import RolDescripcion, RolEstado

import app.services.invitacion_docente_service as inv_service


def get_all_usuarios(db: SessionDep, offset: int, limit: Annotated[int, Query(le=100)]):
    return db.exec(select(Usuario).offset(offset).limit(limit)).all()


def get_usuario_by_dni(db: SessionDep, dni: str):
    return db.exec(select(Usuario).where(Usuario.dni == dni)).first()


def get_usuario_by_mail(db: SessionDep, mail: str):
    return db.exec(select(Usuario).where(Usuario.mailABC == mail)).first()


def get_one_usuario(idUsuario: int, db: SessionDep):
    return db.get(Usuario, idUsuario)


# CREATE
def add_usuario(usuario: UsuarioCreate, db: SessionDep):
    # --------------------------------------------------
    # 1) Validaciones de unicidad
    # --------------------------------------------------
    dni_existente = get_usuario_by_dni(db, usuario.dni)
    mail_existente = get_usuario_by_mail(db, usuario.mailABC)

    # --------------------------------------------------
    # 2) Registro con código de invitación
    #    (solo para usuarios nuevos)
    # --------------------------------------------------
    invitacion = None

    if usuario.codigoInvitacion:
        # ✅ Si ya existe el usuario, NO puede registrarse de nuevo con código.
        if dni_existente or mail_existente:
            raise HTTPException(
                status_code=409,
                detail="Este código es para docentes nuevos. Si ya tenés cuenta, iniciá sesión y cargalo desde tu panel docente.",
            )

        invitacion = inv_service.get_invitacion_por_codigo(db, usuario.codigoInvitacion)

        if invitacion.usada:
            raise HTTPException(status_code=409, detail="El código de invitación ya fue utilizado")

        # Forzar rol y escuela desde la invitación
        rol_final = RolDescripcion.Docente
        escuelas_finales = [invitacion.CUE]
    else:
        # ✅ Registro normal: acá sí aplican las validaciones de unicidad
        if dni_existente:
            raise HTTPException(status_code=400, detail="Ya existe un usuario con este DNI")

        if mail_existente:
            raise HTTPException(status_code=400, detail="Ya existe un usuario con este email")

        rol_final = usuario.rol
        escuelas_finales = usuario.escuelasCUE

    # --------------------------------------------------
    # 3) Crear usuario
    # --------------------------------------------------
    usuario_data = usuario.model_dump(exclude={"escuelasCUE", "rol", "codigoInvitacion"})
    db_usuario = Usuario.model_validate(usuario_data)
    db_usuario.contrasena = get_password_hash(usuario.contrasena)

    db.add(db_usuario)
    db.flush()  # obtiene idUsuario

    # --------------------------------------------------
    # 4) Crear roles (estado default = Pendiente)
    # --------------------------------------------------
    for cue in escuelas_finales:
        nuevo_rol = Rol(
            descripcion=rol_final,
            idUsuario=db_usuario.idUsuario,
            CUE=cue,
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


def change_usuario(usuario_nuevo: UsuarioUpdate, usuario_existente: Usuario, db: SessionDep):
    usuario_data = usuario_nuevo.model_dump(exclude_unset=True)

    if usuario_nuevo.contrasena:
        usuario_data["contrasena"] = get_password_hash(usuario_nuevo.contrasena)

    if "dni" in usuario_data and usuario_data["dni"]:
        otro = get_usuario_by_dni(db, usuario_data["dni"])
        if otro and otro.idUsuario != usuario_existente.idUsuario:
            raise HTTPException(status_code=400, detail="Ya existe un usuario con este DNI")

    if "mailABC" in usuario_data and usuario_data["mailABC"]:
        otro = get_usuario_by_mail(db, usuario_data["mailABC"])
        if otro and otro.idUsuario != usuario_existente.idUsuario:
            raise HTTPException(status_code=400, detail="Ya existe un usuario con este email")

    usuario_existente.sqlmodel_update(usuario_data)
    db.add(usuario_existente)
    db.commit()
    db.refresh(usuario_existente)
    return usuario_existente


def delete_one_usuario(usuario: Usuario, db: SessionDep):
    db.delete(usuario)
    db.commit()


def get_usuarios_by_escuela(tipo: RolDescripcion, CUE: str, db: SessionDep):
    statement = (
        select(Usuario)
        .select_from(Usuario)
        .join(Rol, Rol.idUsuario == Usuario.idUsuario)
        .where(
            Rol.estado == RolEstado.Activo,
            Rol.descripcion == tipo,
            Rol.CUE == CUE,
        )
    )
    return db.exec(statement).all()
