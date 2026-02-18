from __future__ import annotations

from datetime import date
from fastapi import HTTPException
from sqlmodel import select
from sqlalchemy import desc, func

from app.dependencies import SessionDep
from app.models.inscriptos import Inscriptos
from app.models.alumno import Alumno
from app.models.curso import Curso
from app.models.movimiento_promocion import MovimientoPromocion
from app.models.movimiento_promocion_item import MovimientoPromocionItem
from app.schemas.inscriptos import EstadoInscripcion, AccionPromocion, InscripcionHistorialOut
from app.schemas.movimientos import PromocionarOut
from app.services.curso_service import get_one_curso


# =========================
# Helpers
# =========================
def _get_curso_or_404(db: SessionDep, idCurso: int) -> Curso:
    curso = get_one_curso(idCurso=idCurso, db=db)
    if curso is None:
        raise HTTPException(status_code=404, detail="Curso no encontrado")
    return curso


def _get_alumno_or_404(db: SessionDep, idAlumno: int) -> Alumno:
    alumno = db.get(Alumno, idAlumno)
    if alumno is None:
        raise HTTPException(status_code=404, detail="Alumno no encontrado")
    return alumno


def _get_inscripcion_activa_en_ciclo(db: SessionDep, idAlumno: int, cicloLectivo: str) -> Inscriptos | None:
    stmt = (
        select(Inscriptos)
        .join(Curso, Curso.idCurso == Inscriptos.idCurso)
        .where(
            Inscriptos.idAlumno == idAlumno,
            Inscriptos.activo == True,  # noqa: E712
            Curso.cicloLectivo == cicloLectivo,
        )
    )
    return db.exec(stmt).first()


def _cerrar_inscripcion(insc: Inscriptos, estado: EstadoInscripcion, fecha: date):
    insc.activo = False
    insc.estado = estado
    insc.fechaBaja = fecha


def _fmt_curso(nombre: str | None, div: str | None, ciclo: str | None) -> str:
    n = (nombre or "").strip()
    d = (div or "").strip()
    c = (ciclo or "").strip()
    base = f"{n} {d}".strip()
    return f"{base} ({c})".strip() if c else base or "—"


def _buscar_destino_cambio_curso(
    db: SessionDep,
    idAlumno: int,
    cicloLectivo: str,
    fecha_desde: date,
    idCurso_origen: int,
):
    """
    Busca la 'siguiente' inscripción del alumno dentro del mismo ciclo,
    posterior (o igual) a fecha_desde, que sea a otro curso.
    """
    stmt = (
        select(Inscriptos, Curso)
        .join(Curso, Curso.idCurso == Inscriptos.idCurso)
        .where(
            Inscriptos.idAlumno == idAlumno,
            Curso.cicloLectivo == cicloLectivo,
            Inscriptos.fechaAlta >= fecha_desde,
            Inscriptos.idCurso != idCurso_origen,
        )
        .order_by(Inscriptos.fechaAlta.asc(), Inscriptos.idInscripcion.asc())
        .limit(1)
    )
    return db.exec(stmt).first()


# =========================
# ✅ PROMOCIONAR + registrar movimiento
# =========================
def promocionar_alumnos(
    idCursoOrigen: int,
    idCursoDestino: int,
    alumnos,
    db: SessionDep,
    fecha: date | None = None,
    director_id: int | None = None,
) -> PromocionarOut:
    origen = _get_curso_or_404(db, idCursoOrigen)
    destino = _get_curso_or_404(db, idCursoDestino)

    if origen.cicloLectivo == destino.cicloLectivo:
        raise HTTPException(status_code=400, detail="Curso destino debe ser de OTRO ciclo lectivo")

    hoy = fecha or date.today()
    cue = str(origen.CUE)

    if director_id is None or int(director_id) <= 0:
        raise HTTPException(status_code=422, detail="Falta director_id válido")

    try:
        mov = MovimientoPromocion(
            cue=cue,
            director_id=int(director_id),
            idCursoOrigen=int(idCursoOrigen),
            idCursoDestino=int(idCursoDestino),
            fecha=hoy,
            estado="Activo",
        )
        db.add(mov)
        db.commit()
        db.refresh(mov)

        for item in alumnos:
            _get_alumno_or_404(db, item.idAlumno)

            stmt = select(Inscriptos).where(
                Inscriptos.idCurso == idCursoOrigen,
                Inscriptos.idAlumno == item.idAlumno,
                Inscriptos.activo == True,  # noqa: E712
            )
            insc_origen = db.exec(stmt).first()
            id_insc_origen = int(insc_origen.idInscripcion) if insc_origen else None

            if insc_origen:
                if item.accion == AccionPromocion.Promociona:
                    _cerrar_inscripcion(insc_origen, EstadoInscripcion.Promocionado, hoy)
                elif item.accion == AccionPromocion.Repite:
                    _cerrar_inscripcion(insc_origen, EstadoInscripcion.Repitente, hoy)
                elif item.accion == AccionPromocion.Egresa:
                    _cerrar_inscripcion(insc_origen, EstadoInscripcion.Egreso, hoy)
                elif item.accion == AccionPromocion.Baja:
                    _cerrar_inscripcion(insc_origen, EstadoInscripcion.Baja, hoy)

                db.add(insc_origen)

            id_insc_destino = None
            if item.accion in (AccionPromocion.Promociona, AccionPromocion.Repite):
                nueva = Inscriptos(
                    idCurso=idCursoDestino,
                    idAlumno=item.idAlumno,
                    fechaAlta=hoy,
                    activo=True,
                    estado=EstadoInscripcion.Repitente
                    if item.accion == AccionPromocion.Repite
                    else EstadoInscripcion.Activo,
                )
                db.add(nueva)
                db.commit()
                db.refresh(nueva)
                id_insc_destino = int(nueva.idInscripcion)

            it = MovimientoPromocionItem(
                idMovimiento=int(mov.idMovimiento),
                idAlumno=int(item.idAlumno),
                accion=str(item.accion),
                idCursoOrigen=int(idCursoOrigen),
                idCursoDestino=int(idCursoDestino),
                idInscripcionOrigen=id_insc_origen,
                idInscripcionDestino=id_insc_destino,
            )
            db.add(it)

        db.commit()
        return PromocionarOut(ok=True, idMovimiento=int(mov.idMovimiento))

    except Exception:
        db.rollback()
        raise


# =========================
# ✅ Listar últimos movimientos por CUE (actas)
# =========================
def listar_movimientos_por_cue(db: SessionDep, cue: str, limit: int = 20) -> list[dict]:
    from sqlalchemy.orm import aliased
    CursoOrigen = aliased(Curso)
    CursoDestino = aliased(Curso)

    stmt = (
        select(
            MovimientoPromocion,
            CursoOrigen.nombre.label("orig_nombre"),
            CursoOrigen.division.label("orig_div"),
            CursoOrigen.cicloLectivo.label("orig_ciclo"),
            CursoDestino.nombre.label("dest_nombre"),
            CursoDestino.division.label("dest_div"),
            CursoDestino.cicloLectivo.label("dest_ciclo")
        )
        .join(CursoOrigen, CursoOrigen.idCurso == MovimientoPromocion.idCursoOrigen)
        .join(CursoDestino, CursoDestino.idCurso == MovimientoPromocion.idCursoDestino)
        .where(MovimientoPromocion.cue == cue)
        .order_by(desc(MovimientoPromocion.created_at))
        .limit(limit)
    )

    results = db.exec(stmt).all()

    movimientos = []
    for row in results:
        m = row.MovimientoPromocion
        movimientos.append({
            "idMovimiento": m.idMovimiento,
            "fecha": m.fecha,
            "estado": m.estado,
            "created_at": m.created_at,
            "cursoOrigen": f"{row.orig_nombre} {row.orig_div} ({row.orig_ciclo})",
            "cursoDestino": f"{row.dest_nombre} {row.dest_div} ({row.dest_ciclo})",
            "idCursoOrigen": m.idCursoOrigen,
            "idCursoDestino": m.idCursoDestino,
            "director_id": m.director_id
        })
    return movimientos


# =========================
# ✅ Detalle movimiento
# =========================
def detalle_movimiento(db: SessionDep, idMovimiento: int) -> dict:
    mov = db.get(MovimientoPromocion, idMovimiento)
    if not mov:
        raise HTTPException(status_code=404, detail="Movimiento no encontrado")

    stmt = (
        select(MovimientoPromocionItem, Alumno)
        .join(Alumno, Alumno.idAlumno == MovimientoPromocionItem.idAlumno)
        .where(MovimientoPromocionItem.idMovimiento == idMovimiento)
    )
    results = db.exec(stmt).all()

    co = db.get(Curso, mov.idCursoOrigen)
    cd = db.get(Curso, mov.idCursoDestino)

    return {
        "idMovimiento": mov.idMovimiento,
        "fecha": mov.fecha,
        "estado": mov.estado,
        "cursoOrigen": f"{co.nombre} {co.division}",
        "cursoDestino": f"{cd.nombre} {cd.division}",
        "items": [
            {
                "idItem": item.MovimientoPromocionItem.idItem,
                "idAlumno": item.Alumno.idAlumno,
                "alumno": f"{item.Alumno.apellido}, {item.Alumno.nombre}",
                "dni": item.Alumno.dni,
                "accion": item.MovimientoPromocionItem.accion
            }
            for item in results
        ]
    }


# =========================
# ✅ Deshacer (DELETE destino + reabrir origen)
# =========================
def deshacer_movimiento(db: SessionDep, idMovimiento: int):
    mov = db.get(MovimientoPromocion, idMovimiento)
    if not mov:
        raise HTTPException(status_code=404, detail="Movimiento no encontrado")

    if mov.estado != "Activo":
        raise HTTPException(status_code=400, detail="Este movimiento ya fue deshecho o no está activo")

    items = db.exec(
        select(MovimientoPromocionItem).where(MovimientoPromocionItem.idMovimiento == idMovimiento)
    ).all()

    try:
        for it in items:
            if it.idInscripcionDestino:
                insc_dest = db.get(Inscriptos, it.idInscripcionDestino)
                if insc_dest:
                    db.delete(insc_dest)

            if it.idInscripcionOrigen:
                insc_org = db.get(Inscriptos, it.idInscripcionOrigen)
                if insc_org:
                    insc_org.activo = True
                    insc_org.fechaBaja = None
                    insc_org.estado = EstadoInscripcion.Activo
                    db.add(insc_org)

        mov.estado = "Deshecho"
        db.add(mov)

        db.commit()
        return {"ok": True}

    except Exception:
        db.rollback()
        raise


# =========================
# INSCRIBIR (con regla 1-activa por ciclo)
# =========================
def inscribir_alumno(idCurso: int, idAlumno: int, db: SessionDep, fechaAlta: date | None = None):
    curso = _get_curso_or_404(db, idCurso)
    _get_alumno_or_404(db, idAlumno)

    hoy = fechaAlta or date.today()

    stmt_mismo = select(Inscriptos).where(
        Inscriptos.idCurso == idCurso,
        Inscriptos.idAlumno == idAlumno,
        Inscriptos.activo == True,  # noqa: E712
    )
    if db.exec(stmt_mismo).first():
        raise HTTPException(status_code=400, detail="El alumno ya está inscripto y activo en este curso")

    activa = _get_inscripcion_activa_en_ciclo(db, idAlumno, curso.cicloLectivo)
    if activa and activa.idCurso != idCurso:
        _cerrar_inscripcion(activa, EstadoInscripcion.CambioCurso, hoy)
        db.add(activa)

    nueva = Inscriptos(
        idCurso=idCurso,
        idAlumno=idAlumno,
        fechaAlta=hoy,
        activo=True,
        estado=EstadoInscripcion.Activo,
    )
    db.add(nueva)
    db.commit()
    db.refresh(nueva)
    return nueva


# =========================
# BAJA / DESINSCRIBIR (cierra)
# =========================
def desinscribir_alumno(idCurso: int, idAlumno: int, db: SessionDep, fecha: date | None = None):
    hoy = fecha or date.today()

    stmt = select(Inscriptos).where(
        Inscriptos.idCurso == idCurso,
        Inscriptos.idAlumno == idAlumno,
        Inscriptos.activo == True,  # noqa: E712
    )
    insc = db.exec(stmt).first()
    if not insc:
        raise HTTPException(status_code=404, detail="Inscripción activa no encontrada")

    _cerrar_inscripcion(insc, EstadoInscripcion.Baja, hoy)
    db.add(insc)
    db.commit()
    db.refresh(insc)
    return insc


# =========================
# LISTAR INSCRIPTOS (activos por defecto)
# =========================
def get_inscriptos_by_curso(idCurso: int, db: SessionDep, solo_activos: bool = True):
    _get_curso_or_404(db, idCurso)

    stmt = (
        select(Alumno)
        .join(Inscriptos, Inscriptos.idAlumno == Alumno.idAlumno)
        .where(Inscriptos.idCurso == idCurso)
    )
    if solo_activos:
        stmt = stmt.where(Inscriptos.activo == True)  # noqa: E712

    return db.exec(stmt).all()


# =========================
# ✅ TIMELINE: Movimientos + Cambios de curso (desde Inscriptos)
# =========================
def get_timeline_alumno(db: SessionDep, id_alumno: int) -> list[dict]:
    from sqlalchemy.orm import aliased
    CursoOrigen = aliased(Curso)
    CursoDestino = aliased(Curso)

    # 1) movimientos "oficiales"
    stmt_mov = (
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
    )
    movs = db.exec(stmt_mov).all()

    timeline: list[dict] = []
    for r in movs:
        detalle = f"De {_fmt_curso(r.orig_nombre, r.orig_div, r.orig_ciclo)}"
        if r.dest_nombre:
            detalle += f" a {_fmt_curso(r.dest_nombre, r.dest_div, r.dest_ciclo)}"
        timeline.append({"fecha": r.fecha, "accion": r.accion, "detalle": detalle})

    # 2) cambios de curso (detectados por inscriptos)
    stmt_cc = (
        select(Inscriptos, Curso)
        .join(Curso, Curso.idCurso == Inscriptos.idCurso)
        .where(
            Inscriptos.idAlumno == id_alumno,
            Inscriptos.estado == EstadoInscripcion.CambioCurso,
            Inscriptos.fechaBaja.is_not(None),
        )
        .order_by(desc(Inscriptos.fechaBaja))
    )
    cambios = db.exec(stmt_cc).all()

    for insc_origen, curso_origen in cambios:
        destino = _buscar_destino_cambio_curso(
            db=db,
            idAlumno=id_alumno,
            cicloLectivo=str(curso_origen.cicloLectivo),
            fecha_desde=insc_origen.fechaBaja,
            idCurso_origen=int(insc_origen.idCurso),
        )

        dest_text = "—"
        if destino:
            insc_dest, curso_dest = destino
            dest_text = _fmt_curso(curso_dest.nombre, curso_dest.division, curso_dest.cicloLectivo)

        detalle = f"De {_fmt_curso(curso_origen.nombre, curso_origen.division, curso_origen.cicloLectivo)} a {dest_text}"
        timeline.append({
            "fecha": insc_origen.fechaBaja,
            "accion": "CambioCurso",
            "detalle": detalle
        })

    # 3) ordenar final por fecha desc
    timeline.sort(key=lambda x: x["fecha"], reverse=True)
    return timeline


# =========================
# ✅ AUDITORÍA: Movimientos + Cambios de curso (desde Inscriptos)
# =========================
def get_auditoria_alumnos_detalle(
    db: SessionDep,
    cue: str,
    anio: str = None,
    accion: str = None
) -> list[dict]:
    from sqlalchemy.orm import aliased

    CursoOrigen = aliased(Curso)
    CursoDestino = aliased(Curso)

    auditoria: list[dict] = []

    # 1) Movimientos (Promociona/Repite/Egresa/Baja)
    if accion is None or accion != "CambioCurso":
        stmt = (
            select(
                MovimientoPromocion.fecha,
                MovimientoPromocion.idMovimiento,
                MovimientoPromocionItem.accion,
                Alumno.apellido,
                Alumno.nombre,
                Alumno.dni,
                Alumno.idAlumno,
                CursoOrigen.nombre.label("orig_nombre"),
                CursoOrigen.division.label("orig_div"),
                CursoDestino.nombre.label("dest_nombre"),
                CursoDestino.division.label("dest_div")
            )
            .join(MovimientoPromocion, MovimientoPromocion.idMovimiento == MovimientoPromocionItem.idMovimiento)
            .join(Alumno, Alumno.idAlumno == MovimientoPromocionItem.idAlumno)
            .join(CursoOrigen, CursoOrigen.idCurso == MovimientoPromocionItem.idCursoOrigen)
            .outerjoin(CursoDestino, CursoDestino.idCurso == MovimientoPromocionItem.idCursoDestino)
            .where(MovimientoPromocion.cue == cue)
            .where(MovimientoPromocion.estado == "Activo")
        )

        if anio:
            stmt = stmt.where(func.year(MovimientoPromocion.fecha) == int(anio))
        if accion:
            stmt = stmt.where(MovimientoPromocionItem.accion == accion)

        stmt = stmt.order_by(desc(MovimientoPromocion.fecha))
        results = db.exec(stmt).all()

        for r in results:
            auditoria.append({
                "idMovimiento": r.idMovimiento,
                "fecha": r.fecha,
                "idAlumno": r.idAlumno,
                "alumno": f"{r.apellido}, {r.nombre}",
                "dni": r.dni,
                "accion": r.accion,
                "cursoOrigen": f"{r.orig_nombre} {r.orig_div}",
                "cursoDestino": f"{r.dest_nombre} {r.dest_div}" if r.dest_nombre else "—"
            })

    # 2) Cambios de curso (desde inscriptos)
    if accion is None or accion == "CambioCurso":
        stmt_cc = (
            select(Inscriptos, Alumno, Curso)
            .join(Alumno, Alumno.idAlumno == Inscriptos.idAlumno)
            .join(Curso, Curso.idCurso == Inscriptos.idCurso)
            .where(
                Curso.CUE == cue,
                Inscriptos.estado == EstadoInscripcion.CambioCurso,
                Inscriptos.fechaBaja.is_not(None),
            )
            .order_by(desc(Inscriptos.fechaBaja))
        )

        if anio:
            stmt_cc = stmt_cc.where(func.year(Inscriptos.fechaBaja) == int(anio))

        rows = db.exec(stmt_cc).all()
        for insc_origen, alumno, curso_origen in rows:
            destino = _buscar_destino_cambio_curso(
                db=db,
                idAlumno=int(alumno.idAlumno),
                cicloLectivo=str(curso_origen.cicloLectivo),
                fecha_desde=insc_origen.fechaBaja,
                idCurso_origen=int(insc_origen.idCurso),
            )

            dest_txt = "—"
            if destino:
                _, curso_dest = destino
                dest_txt = f"{curso_dest.nombre} {curso_dest.division}"

            auditoria.append({
                "idMovimiento": None,  # no es un acta
                "fecha": insc_origen.fechaBaja,
                "idAlumno": int(alumno.idAlumno),
                "alumno": f"{alumno.apellido}, {alumno.nombre}",
                "dni": alumno.dni,
                "accion": "CambioCurso",
                "cursoOrigen": f"{curso_origen.nombre} {curso_origen.division}",
                "cursoDestino": dest_txt
            })

    # orden final por fecha desc
    auditoria.sort(key=lambda x: x["fecha"], reverse=True)
    return auditoria


# =========================
# HISTORIAL INSCRIPCIONES (sin duplicado)
# =========================
def get_historial_inscripciones_alumno(db: SessionDep, idAlumno: int) -> list[InscripcionHistorialOut]:
    _get_alumno_or_404(db, idAlumno)

    stmt = (
        select(Inscriptos, Curso)
        .join(Curso, Curso.idCurso == Inscriptos.idCurso)
        .where(Inscriptos.idAlumno == idAlumno)
        .order_by(desc(Inscriptos.fechaAlta), desc(Inscriptos.idInscripcion))
    )

    rows = db.exec(stmt).all()

    out: list[InscripcionHistorialOut] = []
    for insc, curso in rows:
        out.append(
            InscripcionHistorialOut(
                idInscripcion=int(insc.idInscripcion),
                idCurso=int(insc.idCurso),
                cicloLectivo=str(curso.cicloLectivo),
                cursoNombre=str(curso.nombre),
                cursoDivision=str(curso.division),
                fechaAlta=insc.fechaAlta,
                fechaBaja=insc.fechaBaja,
                activo=bool(insc.activo),
                estado=insc.estado,
            )
        )
    return out
