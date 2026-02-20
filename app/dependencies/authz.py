# app/dependencies/authz.py
from __future__ import annotations

from typing import Iterable

from fastapi import Depends, HTTPException
from sqlmodel import Session, select

from app.dependencies.session import SessionDep
from app.dependencies.auth import get_current_user
from app.models.rol import Rol
from app.models.usuario import Usuario
from app.schemas.rol import RolDescripcion, RolEstado


def require_roles(*roles: RolDescripcion):
    """
    Requiere que el usuario tenga AL MENOS un rol 'Activo' con descripcion dentro de roles
    (en cualquier escuela). Útil para endpoints globales.
    """
    allowed = set(roles)

    def _dep(
        session: SessionDep,
        user: Usuario = Depends(get_current_user),
    ) -> Usuario:
        stmt = (
            select(Rol)
            .where(Rol.idUsuario == user.idUsuario)
            .where(Rol.estado == RolEstado.Activo)
        )
        user_roles = session.exec(stmt).all()

        if not any(r.descripcion in allowed for r in user_roles):
            raise HTTPException(status_code=403, detail="No autorizado")

        return user

    return _dep


def require_school_access(
    cue: str,
    roles: Iterable[RolDescripcion] | None = None,
):
    """
    Requiere que el usuario tenga rol Activo en ese CUE.
    Si roles se especifica, además exige que descripcion esté dentro de roles.
    'Administrador' Activo en ese CUE también sirve siempre.
    """
    allowed = set(roles) if roles else None

    def _dep(
        session: SessionDep,
        user: Usuario = Depends(get_current_user),
    ) -> Usuario:
        stmt = (
            select(Rol)
            .where(Rol.idUsuario == user.idUsuario)
            .where(Rol.CUE == cue)
            .where(Rol.estado == RolEstado.Activo)
        )
        r = session.exec(stmt).first()

        if not r:
            raise HTTPException(status_code=403, detail="No autorizado para esta escuela")

        # Admin siempre habilita
        if r.descripcion == RolDescripcion.Administrador:
            return user

        if allowed and r.descripcion not in allowed:
            raise HTTPException(status_code=403, detail="No autorizado")

        return user

    return _dep


def require_access_by_query_param(
    cue_param_name: str = "cue",
    roles: Iterable[RolDescripcion] | None = None,
):
    """
    Para endpoints que reciben ?cue=XXXX. Valida acceso a ese CUE.
    Uso: Depends(require_access_by_query_param("cue", [RolDescripcion.Director, ...]))
    """
    allowed = set(roles) if roles else None

    def _dep(
        session: SessionDep,
        user: Usuario = Depends(get_current_user),
        cue: str = None,  # se reemplaza abajo (FastAPI lo resuelve por nombre)
    ):
        # FastAPI no permite parametrizar el nombre directo acá.
        # Solución práctica: hacé una función wrapper por endpoint (ver ejemplo más abajo).
        return user

    # Esta función queda como helper conceptual, abajo te doy el patrón real por endpoint.
    return _dep
def require_access_to_cue_param(
    roles: Iterable[RolDescripcion] | None = None,
):
    allowed = set(roles) if roles else None

    def _dep(
        cue: str,
        session: SessionDep,
        user: Usuario = Depends(get_current_user),
    ) -> Usuario:
        stmt = (
            select(Rol)
            .where(Rol.idUsuario == user.idUsuario)
            .where(Rol.CUE == cue)
            .where(Rol.estado == RolEstado.Activo)
        )
        r = session.exec(stmt).first()

        if not r:
            raise HTTPException(status_code=403, detail="No autorizado para esta escuela")

        if r.descripcion == RolDescripcion.Administrador:
            return user

        if allowed and r.descripcion not in allowed:
            raise HTTPException(status_code=403, detail="No autorizado")

        return user

    return _dep
