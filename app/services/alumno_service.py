from __future__ import annotations
from typing import Annotated
from datetime import datetime, date
from sqlalchemy.orm import aliased

from fastapi import Query, HTTPException
from typing import Optional
from sqlmodel import select
from sqlalchemy import func, and_, desc, or_

from app.dependencies import SessionDep
from app.models.curso_docente import CursoDocente
from app.models.escuela import Escuela
from app.models.rol import Rol
from app.schemas.rol import RolDescripcion, RolEstado
from app.models.alumno import Alumno
from app.models.curso import Curso
from app.models.inscriptos import Inscriptos
from app.schemas.alumno import AlumnoCreate, AlumnoUpdate
from app.schemas.alumno import AlumnoDetallePublic
from app.models.parentesco import Parentesco
from app.models.responsable import Responsable
from app.schemas.parentesco import ResponsableConParentescoPublic
from app.schemas.alumno_detalle import AlumnoEscuelaDetallePublic, ResponsableMiniPublic
from app.models.movimiento_promocion import MovimientoPromocion
from app.models.movimiento_promocion_item import MovimientoPromocionItem
from app.services.curso_service import get_one_curso
from app.schemas.alumnos_historial import AlumnoCicloPage, AlumnoCicloRow
from app.schemas.inscriptos import EstadoInscripcion
from app.models.preinscripcion import Preinscripcion
from app.core.encryption import decrypt, hash_for_search


# ==============================================================
# HELPERS INTERNOS
# ==============================================================

def _clean_str(v: str | None) -> str | None:
    if v is None:
        return None
    return str(v).strip()


def _require_not_empty(value: str | None, field_name: str):
    if value is not None and not str(value).strip():
        raise HTTPException(status_code=400, detail=f"El campo '{field_name}' no puede estar vacío")


def _decrypt_alumno(alumno: Alumno) -> dict:
    """Desencripta los campos sensibles de un alumno y devuelve un dict listo para respuesta."""
    return {
        "idAlumno": alumno.idAlumno,
        "nombre": alumno.nombre,
        "apellido": alumno.apellido,
        "dni": decrypt(alumno.dni) if alumno.dni else alumno.dni,
        "fecha_nacimiento": decrypt(alumno.fecha_nacimiento) if alumno.fecha_nacimiento else None,
        "fecha_ingreso": alumno.fecha_ingreso,
        "direccion": decrypt(alumno.direccion) if alumno.direccion else alumno.direccion,
        "estado": alumno.estado,
    }


def _decrypt_responsable_mini(resp, parentesco) -> ResponsableMiniPublic:
    """Construye un ResponsableMiniPublic con los campos desencriptados."""
    return ResponsableMiniPublic(
        idResponsable=resp.idResponsable,
        nombre=resp.nombre,
        apellido=resp.apellido,
        parentesco=parentesco,
        nro_celular=getattr(resp, "nro_celular", None),
        email=getattr(resp, "email", None),
        direccion=decrypt(resp.direccion) if getattr(resp, "direccion", None) else None,
    )


def _decrypt_responsable_con_parentesco(resp, parentesco) -> ResponsableConParentescoPublic:
    """Construye un ResponsableConParentescoPublic con los campos desencriptados."""
    return ResponsableConParentescoPublic(
        idResponsable=resp.idResponsable,
        nombre=resp.nombre,
        apellido=resp.apellido,
        dni=decrypt(resp.dni) if resp.dni else resp.dni,
        fecha_nacimiento=decrypt(resp.fecha_nacimiento) if getattr(resp, "fecha_nacimiento", None) else None,
        email=resp.email,
        nro_celular=resp.nro_celular,
        direccion=decrypt(resp.direccion) if getattr(resp, "direccion", None) else None,
        parentesco=parentesco,
    )


def _exists_otro_alumno_con_dni(db: SessionDep, dni_plain: str, exclude_id: int) -> bool:
    """Verifica duplicado de DNI usando el hash determinístico."""
    dni_hash = hash_for_search(dni_plain.strip())
    stmt = select(Alumno).where(
        Alumno.dni_hash == dni_hash,
        Alumno.idAlumno != exclude_id
    )
    return db.exec(stmt).first() is not None


def _is_admin_global(session: SessionDep, user_id: int) -> bool:
    stmt = (
        select(Rol)
        .where(Rol.idUsuario == user_id)
        .where(Rol.estado == RolEstado.Activo)
        .where(Rol.descripcion == RolDescripcion.Administrador)
    )
    return session.exec(stmt).first() is not None


def _has_active_role_in_cue(session: SessionDep, user_id: int, cue: str) -> Rol | None:
    stmt = (
        select(Rol)
        .where(Rol.idUsuario == user_id)
        .where(Rol.CUE == cue)
        .where(Rol.estado == RolEstado.Activo)
    )
    return session.exec(stmt).first()


def _require_docente_asignado_a_curso(session: SessionDep, user_id: int, idCurso: int) -> None:
    stmt = (
        select(CursoDocente)
        .where(CursoDocente.idUsuario == user_id)
        .where(CursoDocente.idCurso == idCurso)
        .where(CursoDocente.estado == "Activo")
    )
    cd = session.exec(stmt).first()
    if not cd:
        raise HTTPException(status_code=403, detail="Curso no asignado al docente")

    hoy = date.today()
    if cd.fechaDesde and cd.fechaDesde > hoy:
        raise HTTPException(status_code=403, detail="Asignación docente aún no vigente")
    if cd.fechaHasta and cd.fechaHasta < hoy:
        raise HTTPException(status_code=403, detail="Asignación docente vencida")


# ==============================================================
# GET ALL
# ==============================================================

def get_all_alumnos(db: SessionDep, offset: int, limit: Annotated[int, Query(le=100)]):
    alumnos = db.exec(select(Alumno).offset(offset).limit(limit)).all()
    return alumnos


# ==============================================================
# GET BY CURSO (INSCRIPTOS)
# ==============================================================

def get_alumnos_detalle_by_curso(idCurso: int, db: SessionDep):
    stmt = (
        select(Alumno, Responsable, Parentesco.parentesco)
        .join(Inscriptos, Inscriptos.idAlumno == Alumno.idAlumno)
        .outerjoin(Parentesco, Parentesco.idAlumno == Alumno.idAlumno)
        .outerjoin(Responsable, Responsable.idResponsable == Parentesco.idResponsable)
        .where(Inscriptos.idCurso == idCurso)
        .where(Inscriptos.activo == True)
    )

    rows = db.exec(stmt).all()
    alumnos_map = {}

    for alumno, responsable, parentesco in rows:
        if alumno.idAlumno not in alumnos_map:
            alumnos_map[alumno.idAlumno] = {"alumno": alumno, "responsable": None}

        if responsable and not alumnos_map[alumno.idAlumno]["responsable"]:
            alumnos_map[alumno.idAlumno]["responsable"] = _decrypt_responsable_con_parentesco(
                responsable, parentesco
            )

    return [
        AlumnoDetallePublic(
            idAlumno=a.idAlumno,
            nombre=a.nombre,
            apellido=a.apellido,
            dni=decrypt(a.dni) if a.dni else a.dni,
            estado=a.estado,
            responsable=data["responsable"],
        )
        for data in alumnos_map.values()
        for a in [data["alumno"]]
    ]


def get_ciclo_actual() -> str:
    return str(datetime.now().year)


# ==============================================================
# GET DETALLE POR ESCUELA
# ==============================================================

def get_alumnos_detalle_por_escuela(
    db,
    cue: str,
    ciclo_lectivo: Optional[str] = None,
) -> list[AlumnoEscuelaDetallePublic]:

    if not ciclo_lectivo:
        ciclo_lectivo = get_ciclo_actual()

    sub_resp = (
        select(
            Parentesco.idAlumno.label("idAlumno"),
            func.min(Parentesco.idResponsable).label("idResponsable"),
        )
        .group_by(Parentesco.idAlumno)
        .subquery()
    )

    # A) Alumnos CON curso
    stmt = (
        select(Alumno, Curso, Responsable, Parentesco.parentesco)
        .join(Inscriptos, Inscriptos.idAlumno == Alumno.idAlumno)
        .join(Curso, Curso.idCurso == Inscriptos.idCurso)
        .outerjoin(sub_resp, sub_resp.c.idAlumno == Alumno.idAlumno)
        .outerjoin(Responsable, Responsable.idResponsable == sub_resp.c.idResponsable)
        .outerjoin(
            Parentesco,
            (Parentesco.idAlumno == Alumno.idAlumno)
            & (Parentesco.idResponsable == sub_resp.c.idResponsable),
        )
        .where(Curso.CUE == cue)
        .where(Curso.cicloLectivo == ciclo_lectivo)
        .where(Inscriptos.activo == True)  # noqa: E712
    )

    rows = db.exec(stmt).all()
    out: list[AlumnoEscuelaDetallePublic] = []
    ids_ya: set[int] = set()

    for alumno, curso, resp, parentesco in rows:
        ids_ya.add(int(alumno.idAlumno))
        responsable_public = _decrypt_responsable_mini(resp, parentesco) if resp else None

        out.append(
            AlumnoEscuelaDetallePublic(
                idAlumno=alumno.idAlumno,
                nombre=alumno.nombre,
                apellido=alumno.apellido,
                dni=decrypt(alumno.dni) if alumno.dni else alumno.dni,
                estado=getattr(alumno, "estado", "Activo") or "Activo",
                idCurso=curso.idCurso,
                nombreCurso=f"{curso.nombre} {curso.division}".strip(),
                responsable=responsable_public,
            )
        )

    # B) Alumnos SIN curso (preinscripción pendiente)
    stmt_pre = (
        select(Alumno, Responsable, Parentesco.parentesco)
        .join(Preinscripcion, Preinscripcion.idAlumno == Alumno.idAlumno)
        .outerjoin(sub_resp, sub_resp.c.idAlumno == Alumno.idAlumno)
        .outerjoin(Responsable, Responsable.idResponsable == sub_resp.c.idResponsable)
        .outerjoin(
            Parentesco,
            (Parentesco.idAlumno == Alumno.idAlumno)
            & (Parentesco.idResponsable == sub_resp.c.idResponsable),
        )
        .where(Preinscripcion.CUE == cue)
        .where(Preinscripcion.cicloLectivo == ciclo_lectivo)
        .where(Preinscripcion.estado == "Pendiente")
    )

    for alumno, resp, parentesco in db.exec(stmt_pre).all():
        if int(alumno.idAlumno) in ids_ya:
            continue
        responsable_public = _decrypt_responsable_mini(resp, parentesco) if resp else None

        out.append(
            AlumnoEscuelaDetallePublic(
                idAlumno=alumno.idAlumno,
                nombre=alumno.nombre,
                apellido=alumno.apellido,
                dni=decrypt(alumno.dni) if alumno.dni else alumno.dni,
                estado=getattr(alumno, "estado", "Activo") or "Activo",
                idCurso=None,
                nombreCurso="Sin asignar",
                responsable=responsable_public,
            )
        )

    out.sort(key=lambda x: ((x.apellido or "").lower(), (x.nombre or "").lower()))
    return out


# ==============================================================
# GET DETALLE POR ID
# ==============================================================

def get_alumno_detalle_por_id(db: SessionDep, idAlumno: int) -> AlumnoEscuelaDetallePublic:
    # Elegir un responsable "principal" (el de menor idResponsable) SOLO para este alumno
    sub_resp = (
        select(
            Parentesco.idAlumno.label("idAlumno"),
            func.min(Parentesco.idResponsable).label("idResponsable"),
        )
        .where(Parentesco.idAlumno == idAlumno)
        .group_by(Parentesco.idAlumno)
        .subquery()
    )

    stmt = (
        select(Alumno, Curso, Responsable, Parentesco.parentesco)
        .join(Inscriptos, Inscriptos.idAlumno == Alumno.idAlumno)
        .join(Curso, Curso.idCurso == Inscriptos.idCurso)
        .outerjoin(sub_resp, sub_resp.c.idAlumno == Alumno.idAlumno)
        .outerjoin(Responsable, Responsable.idResponsable == sub_resp.c.idResponsable)
        .outerjoin(
            Parentesco,
            and_(
                Parentesco.idAlumno == Alumno.idAlumno,
                Parentesco.idResponsable == sub_resp.c.idResponsable,
            ),
        )
        # ✅ ESTE ERA EL BUG: faltaba filtrar por el idAlumno del path
        .where(Alumno.idAlumno == idAlumno)
        # solo inscripción activa
        .where(Inscriptos.activo == True)  # noqa: E712
        # si tiene varias inscripciones activas (raro), tomamos la más nueva
        .order_by(desc(Inscriptos.fechaAlta), desc(Inscriptos.idInscripcion))
        .limit(1)
    )

    row = db.exec(stmt).first()
    if not row:
        raise HTTPException(status_code=404, detail="Alumno no encontrado o no inscripto a un curso")

    alumno, curso, resp, parentesco = row

    responsable_public = None
    if resp:
        responsable_public = ResponsableMiniPublic(
            idResponsable=resp.idResponsable,
            nombre=resp.nombre,
            apellido=resp.apellido,
            parentesco=parentesco,
            nro_celular=getattr(resp, "nro_celular", None),
            email=getattr(resp, "email", None),
            direccion=decrypt(resp.direccion) if getattr(resp, "direccion", None) else None,
        )

    return AlumnoEscuelaDetallePublic(
        idAlumno=alumno.idAlumno,
        nombre=alumno.nombre,
        apellido=alumno.apellido,
        dni=decrypt(alumno.dni) if alumno.dni else alumno.dni,
        estado=getattr(alumno, "estado", "Activo") or "Activo",
        direccion=decrypt(alumno.direccion) if getattr(alumno, "direccion", None) else None,
        idCurso=curso.idCurso,
        nombreCurso=f"{curso.nombre} {curso.division}".strip(),
        responsable=responsable_public,
    )


# ==============================================================
# GET BY CURSO
# ==============================================================

def get_alumnos_by_curso(idCurso: int, db: SessionDep):
    curso = get_one_curso(idCurso=idCurso, db=db)
    if curso is None:
        raise Exception("El curso ingresado no existe")

    stmt = (
        select(Alumno)
        .join(Inscriptos, Inscriptos.idAlumno == Alumno.idAlumno)
        .where(Inscriptos.idCurso == idCurso, Inscriptos.activo == True)
    )
    return db.exec(stmt).all()


# ==============================================================
# HELPERS DE BÚSQUEDA
# ==============================================================

def get_alumno_by_dni(db: SessionDep, dni: str):
    """Busca un alumno por DNI usando el hash determinístico."""
    dni_hash = hash_for_search(dni.strip())
    stmt = select(Alumno).where(Alumno.dni_hash == dni_hash)
    return db.exec(stmt).first()


def get_one_alumno(idAlumno: int, db: SessionDep):
    return db.get(Alumno, idAlumno)


# ==============================================================
# CREATE
# ==============================================================

def add_alumno(db: SessionDep, alumno_in: AlumnoCreate, current_user):
    user_id = int(current_user.idUsuario)

    def _require_director_or_docente_role_in_cue(cue: str) -> Rol:
        if _is_admin_global(db, user_id):
            return None  # type: ignore

        rol = _has_active_role_in_cue(db, user_id, cue)
        if not rol:
            raise HTTPException(status_code=403, detail="No autorizado para esta escuela")

        if rol.descripcion not in (RolDescripcion.Director, RolDescripcion.Docente):
            raise HTTPException(status_code=403, detail="Rol no autorizado para crear alumnos")

        return rol

    if getattr(alumno_in, "idCurso", None) and alumno_in.idCurso and alumno_in.idCurso > 0:
        curso = get_one_curso(idCurso=alumno_in.idCurso, db=db)
        if curso is None:
            raise HTTPException(status_code=404, detail="El curso ingresado no existe")

        cue_curso = getattr(curso, "CUE", None)
        if not cue_curso:
            raise HTTPException(status_code=400, detail="El curso no tiene CUE")

        rol = _require_director_or_docente_role_in_cue(cue_curso)

        if rol and rol.descripcion == RolDescripcion.Docente:
            _require_docente_asignado_a_curso(db, user_id, int(alumno_in.idCurso))
    else:
        if _is_admin_global(db, user_id):
            pass
        else:
            cue = _clean_str(getattr(alumno_in, "CUE", None))
            if not cue:
                raise HTTPException(status_code=400, detail="Falta CUE para preinscripción")

            rol = _has_active_role_in_cue(db, user_id, cue)
            if not rol:
                raise HTTPException(status_code=403, detail="No autorizado para esta escuela")

            if rol.descripcion != RolDescripcion.Director:
                raise HTTPException(status_code=403, detail="Solo Director puede crear preinscripciones")

    # dni ya viene encriptado desde AlumnoCreate (via field_validator)
    # pero para buscar duplicados necesitamos el valor plain → lo desencriptamos
    dni_encriptado = alumno_in.dni or ""
    if not dni_encriptado:
        raise HTTPException(status_code=400, detail="El DNI del alumno es obligatorio")

    dni_plain = decrypt(dni_encriptado)
    existente = get_alumno_by_dni(db, dni_plain)

    if existente:
        stmt_check = (
            select(Inscriptos)
            .where(Inscriptos.idAlumno == existente.idAlumno)
            .where(Inscriptos.activo == True)
        )
        if db.exec(stmt_check).first():
            raise HTTPException(
                status_code=400,
                detail="El alumno ya tiene una inscripción activa en otra escuela"
            )
        db_alumno = existente
    else:
        data = alumno_in.model_dump(exclude={"idCurso", "CUE", "cicloLectivo"})

        # Validar campos obligatorios (sobre valores plain para el mensaje de error)
        _require_not_empty(_clean_str(data.get("nombre")), "nombre")
        _require_not_empty(_clean_str(data.get("apellido")), "apellido")
        _require_not_empty(_clean_str(data.get("direccion")), "direccion")

        db_alumno = Alumno.model_validate(data)
        db.add(db_alumno)
        db.commit()
        db.refresh(db_alumno)

    # 1) Si viene curso → matrícula real
    if getattr(alumno_in, "idCurso", None) and alumno_in.idCurso and alumno_in.idCurso > 0:
        curso = get_one_curso(idCurso=alumno_in.idCurso, db=db)
        if curso is None:
            raise HTTPException(status_code=404, detail="El curso ingresado no existe")

        ya = db.exec(
            select(Inscriptos).where(
                Inscriptos.idCurso == alumno_in.idCurso,
                Inscriptos.idAlumno == db_alumno.idAlumno,
                Inscriptos.activo == True,
            )
        ).first()

        if not ya:
            insc = Inscriptos(idCurso=alumno_in.idCurso, idAlumno=db_alumno.idAlumno)
            db.add(insc)
            db.commit()

    # 2) Si NO viene curso → preinscripción
    else:
        cue = _clean_str(getattr(alumno_in, "CUE", None))
        ciclo = _clean_str(getattr(alumno_in, "cicloLectivo", None))

        if cue and ciclo:
            pre_existente = db.exec(
                select(Preinscripcion).where(
                    Preinscripcion.idAlumno == db_alumno.idAlumno,
                    Preinscripcion.CUE == cue,
                    Preinscripcion.cicloLectivo == ciclo,
                    Preinscripcion.estado == "Pendiente",
                )
            ).first()

            if not pre_existente:
                pre = Preinscripcion(
                    idAlumno=db_alumno.idAlumno,
                    CUE=cue,
                    cicloLectivo=ciclo,
                    estado="Pendiente",
                )
                db.add(pre)
                db.commit()

    db.refresh(db_alumno)
    return db_alumno


# ==============================================================
# UPDATE
# ==============================================================

def update_alumno(alumno_existente: Alumno, alumno_nuevo: AlumnoUpdate, db: SessionDep):
    data = alumno_nuevo.model_dump(exclude_unset=True)

    # Validar DNI duplicado usando hash
    if "dni" in data:
        dni_encriptado = data["dni"]
        if not dni_encriptado:
            raise HTTPException(status_code=400, detail="El DNI es obligatorio")

        dni_plain = decrypt(dni_encriptado)

        if _exists_otro_alumno_con_dni(db, dni_plain, alumno_existente.idAlumno):
            raise HTTPException(status_code=400, detail="Ya existe otro alumno con ese DNI")

        # Actualizar también el hash
        data["dni_hash"] = hash_for_search(dni_plain)

    # Validar campos obligatorios
    campos_obligatorios = ["nombre", "apellido", "fecha_nacimiento", "fecha_ingreso", "direccion", "estado"]
    for campo in campos_obligatorios:
        if campo in data:
            valor = data[campo]
            if valor is None or (isinstance(valor, str) and not valor.strip()):
                raise HTTPException(status_code=400, detail=f"El campo '{campo}' es obligatorio")

    alumno_existente.sqlmodel_update(data)
    db.add(alumno_existente)
    db.commit()
    db.refresh(alumno_existente)
    return alumno_existente


# ==============================================================
# DELETE
# ==============================================================

def delete_alumno(db: SessionDep, alumno: Alumno):
    db.delete(alumno)
    db.commit()


# ==============================================================
# HISTORIAL POR CICLO
# ==============================================================

def get_alumnos_historial_por_ciclo(
    db: SessionDep,
    cue: str,
    ciclo_lectivo: str,
    q: str | None = None,
    solo_activos: bool = False,
    offset: int = 0,
    limit: int = 20,
) -> AlumnoCicloPage:

    sub_last_insc = (
        select(
            Inscriptos.idAlumno.label("idAlumno"),
            func.max(Inscriptos.idInscripcion).label("lastId"),
        )
        .join(Curso, Curso.idCurso == Inscriptos.idCurso)
        .where(Curso.CUE == cue)
        .where(Curso.cicloLectivo == ciclo_lectivo)
        .group_by(Inscriptos.idAlumno)
        .subquery()
    )

    sub_current_active = (
        select(
            Inscriptos.idAlumno.label("idAlumno"),
            func.max(Inscriptos.idInscripcion).label("currentId"),
        )
        .join(Curso, Curso.idCurso == Inscriptos.idCurso)
        .where(Curso.CUE == cue)
        .where(Inscriptos.activo == True)  # noqa: E712
        .group_by(Inscriptos.idAlumno)
        .subquery()
    )

    sub_resp = (
        select(
            Parentesco.idAlumno.label("idAlumno"),
            func.min(Parentesco.idResponsable).label("idResponsable"),
        )
        .group_by(Parentesco.idAlumno)
        .subquery()
    )

    CursoActual = aliased(Curso)
    InscActual = aliased(Inscriptos)

    stmt = (
        select(Alumno, Curso, Inscriptos, Responsable, Parentesco.parentesco, CursoActual)
        .join(sub_last_insc, sub_last_insc.c.idAlumno == Alumno.idAlumno)
        .join(Inscriptos, Inscriptos.idInscripcion == sub_last_insc.c.lastId)
        .join(Curso, Curso.idCurso == Inscriptos.idCurso)
        .outerjoin(sub_current_active, sub_current_active.c.idAlumno == Alumno.idAlumno)
        .outerjoin(InscActual, InscActual.idInscripcion == sub_current_active.c.currentId)
        .outerjoin(CursoActual, CursoActual.idCurso == InscActual.idCurso)
        .outerjoin(sub_resp, sub_resp.c.idAlumno == Alumno.idAlumno)
        .outerjoin(Responsable, Responsable.idResponsable == sub_resp.c.idResponsable)
        .outerjoin(
            Parentesco,
            (Parentesco.idAlumno == Alumno.idAlumno)
            & (Parentesco.idResponsable == sub_resp.c.idResponsable),
        )
        .where(Curso.CUE == cue)
        .where(Curso.cicloLectivo == ciclo_lectivo)
    )

    if solo_activos:
        stmt = stmt.where(Inscriptos.activo == True)  # noqa: E712

    # Búsqueda por q: nombre/apellido con ilike, DNI con hash exacto
    if q:
        q_clean = q.strip()
        term = f"%{q_clean}%"
        if q_clean.isdigit():
            dni_hash_q = hash_for_search(q_clean)
            stmt = stmt.where(
                or_(
                    Alumno.nombre.ilike(term),
                    Alumno.apellido.ilike(term),
                    Alumno.dni_hash == dni_hash_q,
                )
            )
        else:
            stmt = stmt.where(
                or_(
                    Alumno.nombre.ilike(term),
                    Alumno.apellido.ilike(term),
                )
            )

    rows = db.exec(stmt).all()
    items: list[AlumnoCicloRow] = []
    ids_incluidos: set[int] = set()

    for alumno, curso, insc, resp, parentesco, curso_actual in rows:
        ids_incluidos.add(int(alumno.idAlumno))

        responsable_public = None
        if resp:
            responsable_public = ResponsableMiniPublic(
                idResponsable=int(resp.idResponsable),
                nombre=str(resp.nombre),
                apellido=str(resp.apellido),
                parentesco=parentesco,
                nro_celular=getattr(resp, "nro_celular", None),
                email=getattr(resp, "email", None),
                direccion=decrypt(resp.direccion) if getattr(resp, "direccion", None) else None,
            )

        items.append(
            AlumnoCicloRow(
                idAlumno=int(alumno.idAlumno),
                nombre=str(alumno.nombre),
                apellido=str(alumno.apellido),
                dni=decrypt(alumno.dni) if alumno.dni else str(alumno.dni),
                idCurso=int(curso.idCurso),
                nombreCurso=f"{curso.nombre} {curso.division}".strip(),
                estadoAlumno=str(getattr(alumno, "estado", "Activo") or "Activo"),
                activoInscripcion=bool(insc.activo),
                estadoInscripcion=insc.estado,
                idCursoActual=int(curso_actual.idCurso) if curso_actual else None,
                cursoActualNombre=(f"{curso_actual.nombre} {curso_actual.division}".strip() if curso_actual else None),
                responsable=responsable_public,
            )
        )

    # Preinscriptos sin curso
    if not solo_activos:
        stmt_pre = (
            select(Alumno, Responsable, Parentesco.parentesco)
            .join(Preinscripcion, Preinscripcion.idAlumno == Alumno.idAlumno)
            .outerjoin(sub_resp, sub_resp.c.idAlumno == Alumno.idAlumno)
            .outerjoin(Responsable, Responsable.idResponsable == sub_resp.c.idResponsable)
            .outerjoin(
                Parentesco,
                (Parentesco.idAlumno == Alumno.idAlumno)
                & (Parentesco.idResponsable == sub_resp.c.idResponsable),
            )
            .where(Preinscripcion.CUE == cue)
            .where(Preinscripcion.cicloLectivo == ciclo_lectivo)
            .where(Preinscripcion.estado == "Pendiente")
        )

        if q:
            q_clean = q.strip()
            term = f"%{q_clean}%"
            if q_clean.isdigit():
                dni_hash_q = hash_for_search(q_clean)
                stmt_pre = stmt_pre.where(
                    or_(
                        Alumno.nombre.ilike(term),
                        Alumno.apellido.ilike(term),
                        Alumno.dni_hash == dni_hash_q,
                    )
                )
            else:
                stmt_pre = stmt_pre.where(
                    or_(
                        Alumno.nombre.ilike(term),
                        Alumno.apellido.ilike(term),
                    )
                )

        for alumno, resp, parentesco in db.exec(stmt_pre).all():
            if int(alumno.idAlumno) in ids_incluidos:
                continue

            responsable_public = None
            if resp:
                responsable_public = ResponsableMiniPublic(
                    idResponsable=int(resp.idResponsable),
                    nombre=str(resp.nombre),
                    apellido=str(resp.apellido),
                    parentesco=parentesco,
                    nro_celular=getattr(resp, "nro_celular", None),
                    email=getattr(resp, "email", None),
                    direccion=decrypt(resp.direccion) if getattr(resp, "direccion", None) else None,
                )

            items.append(
                AlumnoCicloRow(
                    idAlumno=int(alumno.idAlumno),
                    nombre=str(alumno.nombre),
                    apellido=str(alumno.apellido),
                    dni=decrypt(alumno.dni) if alumno.dni else str(alumno.dni),
                    idCurso=0,
                    nombreCurso="Sin asignar",
                    idCursoActual=None,
                    cursoActualNombre=None,
                    estadoAlumno=str(getattr(alumno, "estado", "Activo") or "Activo"),
                    activoInscripcion=False,
                    estadoInscripcion=EstadoInscripcion.Activo,
                    responsable=responsable_public,
                )
            )

    items.sort(key=lambda x: ((x.apellido or "").lower(), (x.nombre or "").lower()))
    total = len(items)
    paged = items[offset: offset + limit]
    return AlumnoCicloPage(total=total, items=paged)


# ==============================================================
# BUSCAR POR DNI
# ==============================================================

def buscar_alumno_por_dni(db: SessionDep, dni: str, current_user) -> dict:
    user_id = int(current_user.idUsuario)

    if not _is_admin_global(db, user_id):
        stmt_rol = (
            select(Rol)
            .where(Rol.idUsuario == user_id)
            .where(Rol.estado == RolEstado.Activo)
            .where(Rol.descripcion == RolDescripcion.Director)
        )
        if not db.exec(stmt_rol).first():
            raise HTTPException(status_code=403, detail="Solo el Director puede buscar alumnos por DNI")

    alumno = get_alumno_by_dni(db, dni.strip())
    if not alumno:
        raise HTTPException(status_code=404, detail="No existe ningún alumno con ese DNI")

    stmt_insc = (
        select(Inscriptos, Curso)
        .join(Curso, Curso.idCurso == Inscriptos.idCurso)
        .where(Inscriptos.idAlumno == alumno.idAlumno)
        .where(Inscriptos.activo == True)
        .limit(1)
    )
    row = db.exec(stmt_insc).first()

    tiene_activa = row is not None
    escuela_activa = None

    if row:
        insc, curso = row
        escuela = db.exec(select(Escuela).where(Escuela.CUE == curso.CUE)).first()
        escuela_activa = escuela.nombre if escuela else f"CUE {curso.CUE}"

    return {
        "idAlumno": alumno.idAlumno,
        "nombre": alumno.nombre,
        "apellido": alumno.apellido,
        "dni": decrypt(alumno.dni) if alumno.dni else alumno.dni,
        "fecha_nacimiento": decrypt(alumno.fecha_nacimiento) if alumno.fecha_nacimiento else None,
        "tiene_inscripcion_activa": tiene_activa,
        "escuela_activa": escuela_activa,
    }