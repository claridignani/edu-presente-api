from __future__ import annotations

from datetime import date
import re
from typing import Annotated, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, field_validator

from app.dependencies import SessionDep
from app.schemas.usuario import UsuarioCreate, UsuarioPublic, UsuarioUpdate, DocenteFichaPublic
from app.services.curso_docente_service import inactivar_docente_de_curso
from app.schemas.rol import RolDescripcion, RolPublic
from app.schemas.cursos_admin import CursoMiniOut
from app.core.security import verify_password, get_password_hash

from app.services.usuario_service import (
    add_usuario,
    change_usuario,
    delete_one_usuario,
    get_all_usuarios,
    get_one_usuario,
    get_usuario_by_dni,
    get_usuarios_by_escuela,
    get_all_usuarios_admin,
    get_usuario_admin_by_id,
    get_detalle_docente,
    get_historial_asignaciones,
    get_ciclos_lectivos_por_escuela,
    get_cursos_por_escuela_y_ciclo,

)

router = APIRouter(prefix="/usuarios", tags=["Usuarios"])

def _validate_cue_or_422(cue: str) -> str:
    cue_norm = re.sub(r"\D", "", str(cue).strip())
    
    if not cue_norm:
        raise HTTPException(
            status_code=422,
            detail="El CUE es obligatorio y debe contener solo números."
        )
    return cue_norm


# Reglas de contraseña (igual que en schema)
def _validate_password_or_422(pw: str) -> str:
    if not isinstance(pw, str) or not pw.strip():
        raise HTTPException(status_code=422, detail="La contraseña es obligatoria")

    pw = pw.strip()
    if len(pw) < 8:
        raise HTTPException(status_code=422, detail="La contraseña debe tener al menos 8 caracteres")
    if not re.search(r"[A-Z]", pw):
        raise HTTPException(status_code=422, detail="La contraseña debe tener al menos 1 letra mayúscula")
    if not re.search(r"[a-z]", pw):
        raise HTTPException(status_code=422, detail="La contraseña debe tener al menos 1 letra minúscula")
    if not re.search(r"\d", pw):
        raise HTTPException(status_code=422, detail="La contraseña debe tener al menos 1 número")
    if not re.search(r"[^\w\s]", pw):
        raise HTTPException(status_code=422, detail="La contraseña debe tener al menos 1 caracter especial")

    return pw


# =========================
# RESPUESTA ADMIN (usuario + roles + escuela)
# =========================
class UsuarioRolEscuelaOut(BaseModel):
    CUE: str
    nombre_escuela: Optional[str] = None
    rol: RolPublic


class UsuarioAdminOut(UsuarioPublic):
    roles: List[UsuarioRolEscuelaOut] = []


def _map_admin_rows(rows) -> list[UsuarioAdminOut]:
    """
    rows: list[tuple[Usuario, Rol|None, Escuela|None]]
    Agrupa por usuario y arma roles[].
    """
    agrupados: dict[int, UsuarioAdminOut] = {}

    for usuario, rol, escuela in rows:
        if usuario.idUsuario not in agrupados:
            base = UsuarioPublic.model_validate(usuario)
            agrupados[usuario.idUsuario] = UsuarioAdminOut(**base.model_dump(), roles=[])

        if rol is None:
            continue

        rol_public = RolPublic.model_validate(rol)

        agrupados[usuario.idUsuario].roles.append(
            UsuarioRolEscuelaOut(
                CUE=rol.CUE,
                nombre_escuela=getattr(escuela, "nombre", None) if escuela is not None else None,
                rol=rol_public,
            )
        )

    return list(agrupados.values())


# =========================
# LISTAR USUARIOS (BÁSICO)
# =========================
@router.get("/", response_model=list[UsuarioPublic])
def get_all(
    session: SessionDep,
    offset: int = 0,
    limit: Annotated[int, Query(le=100)] = 100,
):
    return get_all_usuarios(session, offset, limit)

@router.get("/usuarios", response_model=list[UsuarioPublic])
def get_all_alias(
    session: SessionDep,
    offset: int = 0,
    limit: Annotated[int, Query(le=100)] = 100,
):
    return get_all_usuarios(session, offset, limit)

@router.patch("/quitar-curso/{idCurso}/{idUsuario}")
def quitar_curso(idCurso: int, idUsuario: int, session: SessionDep):
    """Endpoint para inactivar la relación docente-curso"""
    return inactivar_docente_de_curso(session, idCurso, idUsuario)

# =========================
# LISTAR USUARIOS (ADMIN: con roles + escuela)
# =========================
@router.get("/admin", response_model=list[UsuarioAdminOut])
def get_all_admin(
    session: SessionDep,
    offset: int = 0,
    limit: Annotated[int, Query(le=200)] = 200,
):
    rows = get_all_usuarios_admin(session, offset=offset, limit=limit)
    return _map_admin_rows(rows)


@router.get("/admin/usuarios", response_model=list[UsuarioAdminOut])
def get_all_admin_alias(
    session: SessionDep,
    offset: int = 0,
    limit: Annotated[int, Query(le=200)] = 200,
):
    rows = get_all_usuarios_admin(session, offset=offset, limit=limit)
    return _map_admin_rows(rows)


@router.get("/{usuario_id}/admin", response_model=UsuarioAdminOut)
def read_admin(usuario_id: int, session: SessionDep):
    rows = get_usuario_admin_by_id(session, usuario_id)
    if not rows:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    # rows puede tener varias filas por roles → lo mapeamos y devolvemos el 1ero
    return _map_admin_rows(rows)[0]


# =========================
# CREAR USUARIO
# =========================
@router.post("/", response_model=UsuarioPublic, status_code=201)
def create(usuario: UsuarioCreate, session: SessionDep):
    usuario_existente = get_usuario_by_dni(session, usuario.dni)
    if usuario_existente:
        raise HTTPException(status_code=400, detail="Ya existe un usuario con este DNI")
    return add_usuario(usuario, session)

# =========================
# OBTENER USUARIO POR DNI
# =========================
@router.get("/dni/{dni}", response_model=UsuarioPublic)
def read_by_dni(dni: str, session: SessionDep):
    usuario = get_usuario_by_dni(session, dni)
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    return usuario

# =========================
# OBTENER USUARIO POR ID (BÁSICO)
# =========================
@router.get("/detalle-completo", response_model=DocenteFichaPublic)
def get_detalle(usuario_id: int, cue: str, session: SessionDep):
    detalle = get_detalle_docente(usuario_id, cue, session)
    if not detalle:
        raise HTTPException(status_code=404, detail="Docente no encontrado")
    return detalle

@router.get("/{usuario_id}", response_model=UsuarioPublic)
def read(usuario_id: int, session: SessionDep):
    usuario = get_one_usuario(usuario_id, session)
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    return usuario

# =========================
# ACTUALIZAR USUARIO (EDITAR PERFIL)
# =========================
@router.patch("/{usuario_id}", response_model=UsuarioPublic)
def update(usuario_id: int, usuario: UsuarioUpdate, session: SessionDep):
    usuario_db = get_one_usuario(usuario_id, session)
    if not usuario_db:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    return change_usuario(usuario, usuario_db, session)


# =========================
# CAMBIAR CONTRASEÑA (SEGURO)
# =========================
class CambiarContrasenaIn(BaseModel):
    currentPassword: str
    newPassword: str

    @field_validator("newPassword")
    @classmethod
    def validar_new_password(cls, v: str):
        _validate_password_or_422(v)
        return v


@router.post("/{usuario_id}/cambiar-contrasena")
def cambiar_contrasena(usuario_id: int, payload: CambiarContrasenaIn, session: SessionDep):
    usuario_db = get_one_usuario(usuario_id, session)
    if not usuario_db:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    if not verify_password(payload.currentPassword, usuario_db.contrasena):
        raise HTTPException(status_code=400, detail="Contraseña actual incorrecta")

    usuario_db.contrasena = get_password_hash(payload.newPassword)
    session.add(usuario_db)
    session.commit()
    session.refresh(usuario_db)

    return {"ok": True}


# =========================
# ELIMINAR USUARIO
# =========================
@router.delete("/{usuario_id}", status_code=204)
def delete(usuario_id: int, session: SessionDep):
    usuario_db = get_one_usuario(usuario_id, session)
    if not usuario_db:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    delete_one_usuario(usuario_db, session)
    return None


# =========================
# USUARIOS POR ESCUELA
# =========================
@router.get("/escuelas/{CUE}/docentes/", response_model=list[UsuarioPublic])
def get_docentes_por_escuela(CUE: str, session: SessionDep):
    cue = _validate_cue_or_422(CUE)
    rol = RolDescripcion.Docente
    return get_usuarios_by_escuela(tipo=rol, CUE=cue, db=session)


@router.get("/escuelas/{CUE}/asistentes/", response_model=list[UsuarioPublic])
def get_asistentes_por_escuela(CUE: str, session: SessionDep):
    cue = _validate_cue_or_422(CUE)
    rol = RolDescripcion.Asistente
    return get_usuarios_by_escuela(tipo=rol, CUE=cue, db=session)

class CursoFichaPublic(BaseModel):
    nombre: str
    tipo: str
    desde: Optional[date] = None
    hasta: Optional[date] = None

class DocenteFichaPublic(UsuarioPublic):
    cursos_detalle: List[CursoFichaPublic] = []

@router.get("/historial-asignaciones/{cue}")
def historial_asignaciones(
    cue: str,
    session: SessionDep,
    usuario_id: int | None = None,
    ciclo_lectivo: str | None = None,
    curso_id: int | None = None,
):
    return get_historial_asignaciones(
        db=session,
        cue=cue,
        usuario_id=usuario_id,
        ciclo_lectivo=ciclo_lectivo,
        curso_id=curso_id,
    )

@router.get("/ciclos-lectivos/{cue}", response_model=list[str])
def ciclos_lectivos_por_escuela(cue: str, session: SessionDep):
    return get_ciclos_lectivos_por_escuela(db=session, cue=cue)

@router.get(
    "/cursos-por-ciclo/{cue}",
    response_model=list[CursoMiniOut]
)
def cursos_por_ciclo(
    cue: str,
    ciclo_lectivo: str,
    session: SessionDep,
):
    return get_cursos_por_escuela_y_ciclo(
        db=session,
        cue=cue,
        ciclo_lectivo=ciclo_lectivo,
    )