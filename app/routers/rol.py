# app/routers/rol.py
from typing import List

from fastapi import APIRouter, HTTPException

from app.dependencies import SessionDep
from app.schemas.rol import RolCreate, RolDescripcion, RolPublic, RolUpdate, RolEstado
from app.schemas.usuario import Usuario_Roles
from app.services.rol_service import (
    change_rol_status,
    get_roles_pendientes,
    create_rol,
)

router = APIRouter(prefix="/roles", tags=["Roles"])


# =========================================================
# ✅ SOLICITAR / VINCULAR USUARIO ↔ ESCUELA + ROL (CREA PENDIENTE)
# =========================================================
@router.post("/", response_model=RolPublic, status_code=201)
def vincular_usuario_escuela(payload: RolCreate, session: SessionDep):
    """
    Crea el vínculo Usuario-Escuela (tabla rol) como SOLICITUD:
    - Fuerza estado = Pendiente (el front NO puede crear Activo/Rechazado)
    - 404 si usuario o escuela no existen
    - 409 si ya existe el vínculo (idUsuario, CUE)
    """
    try:
        # 🔒 Fuerza Pendiente siempre, sin importar lo que mande el front
        payload.estado = RolEstado.Pendiente

        db_rol = create_rol(payload=payload, db=session)
        return RolPublic.model_validate(db_rol)

    except HTTPException:
        # si service ya levanta HTTPException, la dejamos pasar
        raise
    except ValueError as e:
        # validaciones típicas
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        # fallback seguro
        msg = str(e) or "Error creando el rol"
        # si tu service tira mensajes específicos, intentamos mapear:
        if "ya existe" in msg.lower() or "existe el vínculo" in msg.lower() or "duplic" in msg.lower():
            raise HTTPException(status_code=409, detail=msg)
        if "no existe" in msg.lower() or "no encontrado" in msg.lower():
            raise HTTPException(status_code=404, detail=msg)
        raise HTTPException(status_code=500, detail="Error interno creando el rol")


# =========================================================
# ✅ APROBAR/RECHAZAR / CAMBIAR ESTADO (y opcional descripcion)
# =========================================================
@router.post("/update", response_model=RolPublic)
def change_rol_estado(rol: RolUpdate, session: SessionDep):
    """
    Actualiza un rol existente (idUsuario + CUE):
    - Si estado viene bool: true -> Activo / false -> Rechazado
    - Si estado viene enum: lo setea directamente
    - Si viene descripcion: la actualiza también
    """
    try:
        db_rol = change_rol_status(rol=rol, db=session)
        return RolPublic.model_validate(db_rol)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=404, detail="idUsuario o CUE incorrectos")


# =========================================================
# PENDIENTES POR TIPO
# =========================================================
@router.get("/docentes/pendientes", response_model=List[Usuario_Roles])
def get_docentes_estado_pendiente(session: SessionDep):
    """Docentes con rol Pendiente. Devuelve lista de usuarios con su rol."""
    rol_elegido = RolDescripcion.Docente
    resultados = get_roles_pendientes(db=session, rol=rol_elegido)

    docentes_roles: list[Usuario_Roles] = []
    for rol, docente in resultados:
        docente_db = docente.model_dump()
        rol_db = RolPublic.model_validate(rol)
        docentes_roles.append(Usuario_Roles(**docente_db, rol=rol_db))

    return docentes_roles


@router.get("/directores/pendientes", response_model=List[Usuario_Roles])
def get_directores_estado_pendiente(session: SessionDep):
    """Directores con rol Pendiente. Devuelve lista de usuarios con su rol."""
    rol_elegido = RolDescripcion.Director
    resultados = get_roles_pendientes(db=session, rol=rol_elegido)

    director_roles: list[Usuario_Roles] = []
    for rol, director in resultados:
        director_db = director.model_dump()
        rol_db = RolPublic.model_validate(rol)
        director_roles.append(Usuario_Roles(**director_db, rol=rol_db))

    return director_roles


@router.get("/administradores/pendientes", response_model=List[Usuario_Roles])
def get_administradores_estado_pendiente(session: SessionDep):
    """Administradores con rol Pendiente. Devuelve lista de usuarios con su rol."""
    rol_elegido = RolDescripcion.Administrador
    resultados = get_roles_pendientes(db=session, rol=rol_elegido)

    administrador_roles: list[Usuario_Roles] = []
    for rol, administrador in resultados:
        administrador_db = administrador.model_dump()
        rol_db = RolPublic.model_validate(rol)
        administrador_roles.append(Usuario_Roles(**administrador_db, rol=rol_db))

    return administrador_roles


@router.get("/asistentes/pendientes", response_model=List[Usuario_Roles])
def get_asistentes_estado_pendiente(session: SessionDep):
    """Asistentes con rol Pendiente. Devuelve lista de usuarios con su rol."""
    rol_elegido = RolDescripcion.Asistente
    resultados = get_roles_pendientes(db=session, rol=rol_elegido)

    asistente_roles: list[Usuario_Roles] = []
    for rol, asistente in resultados:
        asistente_db = asistente.model_dump()
        rol_db = RolPublic.model_validate(rol)
        asistente_roles.append(Usuario_Roles(**asistente_db, rol=rol_db))

    return asistente_roles
