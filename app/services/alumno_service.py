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

# HELPERS

def _clean_str(v: str | None) -> str | None:
    if v is None:
        return None
    return str(v).strip()

def _require_not_empty(value: str | None, field_name: str):
    """
    Si el campo viene (no es None), no puede ser vacío.
    """
    if value is not None and not str(value).strip():
        raise HTTPException(status_code=400, detail=f"El campo '{field_name}' no puede estar vacío")

def _exists_otro_alumno_con_dni(db: SessionDep, dni: str, exclude_id: int) -> bool:
    stmt = select(Alumno).where(Alumno.dni == dni, Alumno.idAlumno != exclude_id)
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
    """
    Docente solo puede operar si tiene asignación Activa en curso_docente.
    También respeta ventana fechaDesde/fechaHasta si están.
    """
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



# GET ALL

def get_all_alumnos(db: SessionDep, offset: int, limit: Annotated[int, Query(le=100)]):
    alumnos = db.exec(select(Alumno).offset(offset).limit(limit)).all()
    return alumnos


# GET BY CURSO (INSCRIPTOS)

def get_alumnos_detalle_by_curso(idCurso: int, db: SessionDep):
    stmt = (
        select(
            Alumno,
            Responsable,
            Parentesco.parentesco
        )
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
            alumnos_map[alumno.idAlumno] = {
                "alumno": alumno,
                "responsable": None
            }

        if responsable and not alumnos_map[alumno.idAlumno]["responsable"]:
            alumnos_map[alumno.idAlumno]["responsable"] = ResponsableConParentescoPublic(
                idResponsable=responsable.idResponsable,
                nombre=responsable.nombre,
                apellido=responsable.apellido,
                dni=responsable.dni,
                fecha_nacimiento=responsable.fecha_nacimiento,
                email=responsable.email,
                nro_celular=responsable.nro_celular,
                direccion=responsable.direccion,
                parentesco=parentesco,
            )

    return [
        AlumnoDetallePublic(
            idAlumno=a.idAlumno,
            nombre=a.nombre,
            apellido=a.apellido,
            dni=a.dni,
            estado=a.estado,
            responsable=data["responsable"],
        )
        for data in alumnos_map.values()
        for a in [data["alumno"]]
    ]

def get_ciclo_actual() -> str:
    return str(datetime.now().year)


def get_alumnos_detalle_por_escuela(
    db,
    cue: str,
    ciclo_lectivo: Optional[str] = None,
) -> list[AlumnoEscuelaDetallePublic]:

    if not ciclo_lectivo:
        ciclo_lectivo = get_ciclo_actual()

    # Responsable "principal"
    sub_resp = (
        select(
            Parentesco.idAlumno.label("idAlumno"),
            func.min(Parentesco.idResponsable).label("idResponsable"),
        )
        .group_by(Parentesco.idAlumno)
        .subquery()
    )

    # =========================
    # A) Alumnos CON curso (inscriptos activos en ese ciclo)
    # =========================
    stmt = (
        select(
            Alumno,
            Curso,
            Responsable,
            Parentesco.parentesco,
        )
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

        responsable_public = None
        if resp:
            responsable_public = ResponsableMiniPublic(
                idResponsable=resp.idResponsable,
                nombre=resp.nombre,
                apellido=resp.apellido,
                parentesco=parentesco,
                nro_celular=getattr(resp, "nro_celular", None),
            )

        out.append(
            AlumnoEscuelaDetallePublic(
                idAlumno=alumno.idAlumno,
                nombre=alumno.nombre,
                apellido=alumno.apellido,
                dni=alumno.dni,
                estado=getattr(alumno, "estado", "Activo") or "Activo",
                idCurso=curso.idCurso,
                nombreCurso=f"{curso.nombre} {curso.division}".strip(),
                responsable=responsable_public,
            )
        )

    # =========================
    # B) Alumnos SIN curso (preinscripción pendiente en ese ciclo)
    # =========================
    stmt_pre = (
        select(
            Alumno,
            Responsable,
            Parentesco.parentesco,
        )
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

    rows_pre = db.exec(stmt_pre).all()

    for alumno, resp, parentesco in rows_pre:
        if int(alumno.idAlumno) in ids_ya:
            continue

        responsable_public = None
        if resp:
            responsable_public = ResponsableMiniPublic(
                idResponsable=resp.idResponsable,
                nombre=resp.nombre,
                apellido=resp.apellido,
                parentesco=parentesco,
                nro_celular=getattr(resp, "nro_celular", None),
            )

        out.append(
            AlumnoEscuelaDetallePublic(
                idAlumno=alumno.idAlumno,
                nombre=alumno.nombre,
                apellido=alumno.apellido,
                dni=alumno.dni,
                estado=getattr(alumno, "estado", "Activo") or "Activo",
                idCurso=None,
                nombreCurso="Sin asignar",
                responsable=responsable_public,
            )
        )

    out.sort(key=lambda x: ((x.apellido or "").lower(), (x.nombre or "").lower()))
    return out

def get_alumno_detalle_por_id(
    db: SessionDep,
    idAlumno: int,
) -> AlumnoEscuelaDetallePublic:
    """
    Devuelve el detalle completo de 1 alumno (para el dialog de alertas):
    - nombre, apellido, dni, estado, direccion
    - curso actual (uno)
    - responsable mini (uno) con email y direccion
    """

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
        select(
            Alumno,
            Curso,
            Responsable,
            Parentesco.parentesco,
        )
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
        .where(Inscriptos.activo == True) 
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
            direccion=getattr(resp, "direccion", None),
        )

    return AlumnoEscuelaDetallePublic(
        idAlumno=alumno.idAlumno,
        nombre=alumno.nombre,
        apellido=alumno.apellido,
        dni=alumno.dni,
        estado=getattr(alumno, "estado", "Activo") or "Activo",
        direccion=getattr(alumno, "direccion", None),

        idCurso=curso.idCurso,
        nombreCurso=f"{curso.nombre} {curso.division}".strip(),
        responsable=responsable_public,
    )


def get_alumnos_by_curso(idCurso: int, db: SessionDep):
    """
    Devuelve los alumnos INSCRIPTOS ACTIVOS a un curso (matrícula actual),
    sin depender de que exista asistencia.
    """
    curso = get_one_curso(idCurso=idCurso, db=db)
    if curso is None:
        raise Exception("El curso ingresado no existe")

    stmt = (
        select(Alumno)
        .join(Inscriptos, Inscriptos.idAlumno == Alumno.idAlumno)
        .where(
            Inscriptos.idCurso == idCurso,
            Inscriptos.activo == True,  
        )
    )
    return db.exec(stmt).all()


# HELPERS

def get_alumno_by_dni(db: SessionDep, dni: str):
    stmt = select(Alumno).where(Alumno.dni == dni)
    return db.exec(stmt).first()

def get_one_alumno(idAlumno: int, db: SessionDep):
    return db.get(Alumno, idAlumno)

# CREATE

def add_alumno(db: SessionDep, alumno_in: AlumnoCreate, current_user):
    user_id = int(current_user.idUsuario)

    def _require_director_or_docente_role_in_cue(cue: str) -> Rol:
        # Admin global pasa sin rol en CUE
        if _is_admin_global(db, user_id):
            return None  # type: ignore

        rol = _has_active_role_in_cue(db, user_id, cue)
        if not rol:
            raise HTTPException(status_code=403, detail="No autorizado para esta escuela")

        # SOLO Director o Docente pueden crear
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

    dni = _clean_str(alumno_in.dni) or ""

    if not dni:
        raise HTTPException(status_code=400, detail="El DNI del alumno es obligatorio")

    existente = get_alumno_by_dni(db, dni)
    if existente:
        raise HTTPException(status_code=400, detail="Ya existe un alumno con ese DNI")

    data = alumno_in.model_dump(exclude={"idCurso", "CUE", "cicloLectivo"})
    data["dni"] = dni 

    _require_not_empty(_clean_str(data.get("nombre")), "nombre")
    _require_not_empty(_clean_str(data.get("apellido")), "apellido")
    _require_not_empty(_clean_str(data.get("direccion")), "direccion")

    db_alumno = Alumno.model_validate(data)

    db.add(db_alumno)
    db.commit()
    db.refresh(db_alumno)

    # 1) Si viene curso => matrícula real (Inscriptos)
    if getattr(alumno_in, "idCurso", None) and alumno_in.idCurso and alumno_in.idCurso > 0:
        curso = get_one_curso(idCurso=alumno_in.idCurso, db=db)
        if curso is None:
            raise HTTPException(status_code=404, detail="El curso ingresado no existe")

        ya = db.exec(
            select(Inscriptos).where(
                Inscriptos.idCurso == alumno_in.idCurso,
                Inscriptos.idAlumno == db_alumno.idAlumno,
                Inscriptos.activo == True,  # si querés evitar duplicados activos
            )
        ).first()

        if not ya:
            insc = Inscriptos(idCurso=alumno_in.idCurso, idAlumno=db_alumno.idAlumno)
            db.add(insc)
            db.commit()

    # 2) Si NO viene curso => preinscripción (Pendiente)
    else:
        cue = _clean_str(getattr(alumno_in, "CUE", None))
        ciclo = _clean_str(getattr(alumno_in, "cicloLectivo", None))

        if cue and ciclo:
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





# UPDATE (con validación DNI único)

def update_alumno(alumno_existente: Alumno, alumno_nuevo: AlumnoUpdate, db: SessionDep):
    data = alumno_nuevo.model_dump(exclude_unset=True)

    # ==========================
    # VALIDAR DNI DUPLICADO
    # ==========================
    if "dni" in data:
        dni_nuevo = data["dni"].strip()
        if not dni_nuevo:
            raise HTTPException(status_code=400, detail="El DNI es obligatorio")

        stmt = select(Alumno).where(
            Alumno.dni == dni_nuevo,
            Alumno.idAlumno != alumno_existente.idAlumno
        )
        existente = db.exec(stmt).first()
        if existente:
            raise HTTPException(
                status_code=400,
                detail="Ya existe otro alumno con ese DNI"
            )

        data["dni"] = dni_nuevo

    # ==========================
    # VALIDAR CAMPOS OBLIGATORIOS
    # ==========================
    campos_obligatorios = [
        "nombre",
        "apellido",
        "fecha_nacimiento",
        "fecha_ingreso",
        "direccion",
        "estado",
    ]

    for campo in campos_obligatorios:
        if campo in data:
            valor = data[campo]
            if valor is None or (isinstance(valor, str) and not valor.strip()):
                raise HTTPException(
                    status_code=400,
                    detail=f"El campo '{campo}' es obligatorio"
                )

    alumno_existente.sqlmodel_update(data)
    db.add(alumno_existente)
    db.commit()
    db.refresh(alumno_existente)
    return alumno_existente

# DELETE

def delete_alumno(db: SessionDep, alumno: Alumno):
    db.delete(alumno)
    db.commit()

def get_timeline_alumno(db: SessionDep, id_alumno: int) -> list[dict]:
    from sqlalchemy.orm import aliased
    # Alias para unir los nombres de cursos origen y destino
    CursoOrigen = aliased(Curso)
    CursoDestino = aliased(Curso)

    stmt = (
        select(
            MovimientoPromocion.fecha,
            MovimientoPromocionItem.accion,
            CursoOrigen.nombre.label("orig_nombre"),
            CursoOrigen.division.label("orig_div"),
            CursoOrigen.cicloLectivo.label("orig_ciclo"),
            CursoDestino.nombre.label("dest_nombre"),
            CursoDestino.division.label("dest_div"),
            CursoDestino.cicloLectivo.label("dest_ciclo")
        )
        .join(MovimientoPromocion, MovimientoPromocion.idMovimiento == MovimientoPromocionItem.idMovimiento)
        .join(CursoOrigen, CursoOrigen.idCurso == MovimientoPromocionItem.idCursoOrigen)
        .outerjoin(CursoDestino, CursoDestino.idCurso == MovimientoPromocionItem.idCursoDestino)
        .where(MovimientoPromocionItem.idAlumno == id_alumno)
        .where(MovimientoPromocion.estado == "Activo")
        .order_by(desc(MovimientoPromocion.fecha))
    )
    
    results = db.exec(stmt).all()
    
    timeline = []
    for r in results:
        detalle_curso = f"De {r.orig_nombre} {r.orig_div} ({r.orig_ciclo})"
        if r.dest_nombre:
            detalle_curso += f" a {r.dest_nombre} {r.dest_div} ({r.dest_ciclo})"
            
        timeline.append({
            "fecha": r.fecha,
            "accion": r.accion,
            "detalle": detalle_curso
        })
    return timeline



def get_alumnos_historial_por_ciclo(
    db: SessionDep,
    cue: str,
    ciclo_lectivo: str,
    q: str | None = None,
    solo_activos: bool = False,
    offset: int = 0,
    limit: int = 20,
) -> AlumnoCicloPage:
    """
    Devuelve matrícula por ciclo lectivo (una fila por alumno),
    tomando la ÚLTIMA inscripción del alumno en ese ciclo (evita duplicados por CambioCurso).

    ✅ Además agrega alumnos SIN CURSO (Preinscripcion Pendiente) para ese CUE + ciclo,
    devolviendo idCurso=0 y nombreCurso="Sin asignar".
    """

    # 1) subquery: última inscripción del alumno en ese ciclo (max idInscripcion)
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

    # 1b) subquery: inscripción ACTIVA actual del alumno en esa escuela (max idInscripcion con activo=True)
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

    # 2) subquery: responsable "principal"
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

    # 3) query base: alumnos con inscripción en el ciclo consultado
    stmt = (
        select(
            Alumno,
            Curso,
            Inscriptos,
            Responsable,
            Parentesco.parentesco,
            CursoActual,
        )
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

    if q:
        term = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                Alumno.nombre.ilike(term),
                Alumno.apellido.ilike(term),
                Alumno.dni.ilike(term),
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
                direccion=getattr(resp, "direccion", None),
            )

        items.append(
            AlumnoCicloRow(
                idAlumno=int(alumno.idAlumno),
                nombre=str(alumno.nombre),
                apellido=str(alumno.apellido),
                dni=str(alumno.dni),

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

    # 4) EXTRA: alumnos sin curso (Preinscripcion Pendiente) en ese ciclo
    #    Solo los agregamos cuando solo_activos=False (si pedís solo activos, no corresponde incluir preinscriptos).
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
            term = f"%{q.strip()}%"
            stmt_pre = stmt_pre.where(
                or_(
                    Alumno.nombre.ilike(term),
                    Alumno.apellido.ilike(term),
                    Alumno.dni.ilike(term),
                )
            )

        rows_pre = db.exec(stmt_pre).all()

        for alumno, resp, parentesco in rows_pre:
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
                    direccion=getattr(resp, "direccion", None),
                )

            items.append(
                AlumnoCicloRow(
                    idAlumno=int(alumno.idAlumno),
                    nombre=str(alumno.nombre),
                    apellido=str(alumno.apellido),
                    dni=str(alumno.dni),

                    idCurso=0,
                    nombreCurso="Sin asignar",

                    # como no hay inscripto en ese ciclo:
                    idCursoActual=None,
                    cursoActualNombre=None,

                    estadoAlumno=str(getattr(alumno, "estado", "Activo") or "Activo"),
                    activoInscripcion=False,
                    estadoInscripcion=EstadoInscripcion.Activo,

                    responsable=responsable_public,
                )
            )

    # 5) ordenar + paginar
    items.sort(key=lambda x: ((x.apellido or "").lower(), (x.nombre or "").lower()))
    total = len(items)
    paged = items[offset : offset + limit]

    return AlumnoCicloPage(total=total, items=paged)