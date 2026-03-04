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
from app.models.preinscripcion import Preinscripcion
from app.services.curso_service import get_one_curso
from app.core.encryption import decrypt


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
# PROMOCIONAR + registrar movimiento
# =========================
def promocionar_alumnos(
    idCursoOrigen: int,
    idCursoDestino: int | None,
    alumnos,
    db: SessionDep,
    fecha: date | None = None,
    director_id: int | None = None,
) -> PromocionarOut:
    origen = _get_curso_or_404(db, idCursoOrigen)

    necesita_destino = any(
        (item.accion in (AccionPromocion.Promociona, AccionPromocion.Repite))
        for item in alumnos
    )

    if necesita_destino and not idCursoDestino:
        raise HTTPException(status_code=422, detail="Falta idCursoDestino (requerido para Promociona/Repite)")

    destino = None
    if necesita_destino:
        destino = _get_curso_or_404(db, int(idCursoDestino))
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
            idCursoDestino=(int(idCursoDestino) if necesita_destino else None),
            fecha=hoy,
            estado="Activo",
        )
        db.add(mov)
        db.flush()

        for item in alumnos:
            _get_alumno_or_404(db, item.idAlumno)

            # ✅ traemos el objeto directamente, sin doble búsqueda
            insc_origen = db.exec(
                select(Inscriptos).where(
                    Inscriptos.idCurso == idCursoOrigen,
                    Inscriptos.idAlumno == item.idAlumno,
                    Inscriptos.activo == True,
                )
            ).first()

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

            db.flush()

            id_insc_destino = None

            if item.accion == AccionPromocion.Promociona:
                estado_dest = EstadoInscripcion.Activo
                existente = db.exec(
                    select(Inscriptos)
                    .where(
                        Inscriptos.idCurso == int(idCursoDestino),
                        Inscriptos.idAlumno == item.idAlumno,
                    )
                    .with_for_update()
                ).first()

                if existente:
                    existente.activo = True
                    existente.fechaBaja = None
                    existente.estado = estado_dest
                    db.add(existente)
                    db.flush()
                    id_insc_destino = int(existente.idInscripcion)
                else:
                    nueva = Inscriptos(
                        idCurso=int(idCursoDestino),
                        idAlumno=item.idAlumno,
                        fechaAlta=hoy,
                        activo=True,
                        estado=estado_dest,
                    )
                    db.add(nueva)
                    db.flush()
                    id_insc_destino = int(nueva.idInscripcion)

            elif item.accion == AccionPromocion.Repite:
                stmt_pre = (
                    select(Preinscripcion)
                    .where(
                        Preinscripcion.idAlumno == item.idAlumno,
                        Preinscripcion.CUE == cue,
                        Preinscripcion.cicloLectivo == str(destino.cicloLectivo),
                    )
                    .order_by(Preinscripcion.fechaCreacion.desc())
                    .limit(1)
                )
                pre = db.exec(stmt_pre).first()

                if pre:
                    pre.estado = "Pendiente"
                    db.add(pre)
                else:
                    db.add(
                        Preinscripcion(
                            idAlumno=item.idAlumno,
                            CUE=cue,
                            cicloLectivo=str(destino.cicloLectivo),
                            estado="Pendiente",
                        )
                    )
                id_insc_destino = None

            it = MovimientoPromocionItem(
                idMovimiento=int(mov.idMovimiento),
                idAlumno=int(item.idAlumno),
                accion=item.accion.value,
                idCursoOrigen=int(idCursoOrigen),
                idCursoDestino=(int(idCursoDestino) if necesita_destino else None),
                idInscripcionOrigen=id_insc_origen,  # ✅ ahora es int o None
                idInscripcionDestino=id_insc_destino,
            )
            db.add(it)

        db.commit()
        return PromocionarOut(ok=True, idMovimiento=int(mov.idMovimiento))

    except Exception:
        db.rollback()
        raise


# =========================
# Listar movimientos por CUE (actas)
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
        .outerjoin(CursoDestino, CursoDestino.idCurso == MovimientoPromocion.idCursoDestino)
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
            "cursoDestino": f"{row.dest_nombre} {row.dest_div} ({row.dest_ciclo})" if row.dest_nombre else "Sin destino (egreso)",
            "idCursoOrigen": m.idCursoOrigen,
            "idCursoDestino": m.idCursoDestino,
            "director_id": m.director_id
        })
    return movimientos


# =========================
# Detalle movimiento
# ✅ FIX: decrypt(item.Alumno.dni) en lugar de item.Alumno.dni
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
    cd = db.get(Curso, mov.idCursoDestino) if mov.idCursoDestino else None

    return {
        "idMovimiento": mov.idMovimiento,
        "fecha": mov.fecha,
        "estado": mov.estado,
        "cursoOrigen": f"{co.nombre} {co.division}",
        "cursoDestino": f"{cd.nombre} {cd.division}" if cd else "Sin destino (egreso)",
        "items": [
            {
                "idItem": item.MovimientoPromocionItem.idItem,
                "idAlumno": item.Alumno.idAlumno,
                "alumno": f"{item.Alumno.apellido}, {item.Alumno.nombre}",
                # ✅ FIX #1: DNI descifrado en detalle de acta
                "dni": decrypt(item.Alumno.dni) if item.Alumno.dni else "—",
                "accion": item.MovimientoPromocionItem.accion
            }
            for item in results
        ]
    }


# =========================
# Deshacer movimiento
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
        with db.no_autoflush:
            for it in items:
                # ── 1. Eliminar inscripción destino registrada ──
                if it.idInscripcionDestino:
                    insc_dest = db.get(Inscriptos, it.idInscripcionDestino)
                    if insc_dest:
                        db.delete(insc_dest)

                # ── 2. Eliminar cualquier otra activa en curso destino ──
                if mov.idCursoDestino:
                    otras = db.exec(
                        select(Inscriptos).where(
                            Inscriptos.idAlumno == it.idAlumno,
                            Inscriptos.idCurso == mov.idCursoDestino,
                            Inscriptos.activo == True,
                        )
                    ).all()
                    for otra in otras:
                        db.delete(otra)

                # ── 3. Reactivar inscripción origen (solo si no hay ya una activa en ese curso) ──
                if it.idInscripcionOrigen:
                    insc_org = db.get(Inscriptos, it.idInscripcionOrigen)
                    if insc_org:
                        # Verificar si ya existe otra inscripción activa del alumno en ese curso
                        ya_activa = db.exec(
                            select(Inscriptos).where(
                                Inscriptos.idAlumno == it.idAlumno,
                                Inscriptos.idCurso == insc_org.idCurso,
                                Inscriptos.activo == True,
                                Inscriptos.idInscripcion != insc_org.idInscripcion,
                            )
                        ).first()

                        if not ya_activa:
                            insc_org.activo = True
                            insc_org.fechaBaja = None
                            insc_org.estado = EstadoInscripcion.Activo
                            db.add(insc_org)
                        # si ya_activa existe, dejamos esa y no tocamos insc_org

        db.flush()
        mov.estado = "Deshecho"
        db.add(mov)
        db.commit()
        return {"ok": True}

    except Exception:
        db.rollback()
        raise
# =========================
# Inscribir
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

    activa = _get_inscripcion_activa_en_ciclo(db, idAlumno, str(curso.cicloLectivo))
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

    stmt_pre = (
        select(Preinscripcion)
        .where(
            Preinscripcion.idAlumno == idAlumno,
            Preinscripcion.CUE == str(curso.CUE),
            Preinscripcion.cicloLectivo == str(curso.cicloLectivo),
            Preinscripcion.estado == "Pendiente",
        )
        .order_by(Preinscripcion.fechaCreacion.desc())
        .limit(1)
    )
    pre = db.exec(stmt_pre).first()
    if pre:
        pre.estado = "Asignada"
        db.add(pre)

    db.commit()
    db.refresh(nueva)
    return nueva


# =========================
# Desinscribir
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
# Listar inscriptos por curso
# =========================
def get_inscriptos_by_curso(idCurso: int, db: SessionDep, solo_activos: bool = True):
    _get_curso_or_404(db, idCurso)

    stmt = (
        select(
            Alumno.idAlumno.label("idAlumno"),
            Alumno.nombre.label("nombre"),
            Alumno.apellido.label("apellido"),
            Alumno.dni.label("dni"),
            getattr(Alumno, "fecha_nacimiento", None).label("fecha_nacimiento") if hasattr(Alumno, "fecha_nacimiento") else func.null().label("fecha_nacimiento"),
            getattr(Alumno, "direccion", None).label("direccion") if hasattr(Alumno, "direccion") else func.null().label("direccion"),
            # ✅ la key que tu response_model está pidiendo:
            Inscriptos.fechaAlta.label("fecha_ingreso"),
            # extras (no molestan, y sirven):
            Inscriptos.idInscripcion.label("idInscripcion"),
            Inscriptos.idCurso.label("idCurso"),
            Inscriptos.activo.label("activo"),
            Inscriptos.estado.label("estado"),
            Inscriptos.fechaBaja.label("fechaBaja"),
        )
        .select_from(Inscriptos)
        .join(Alumno, Alumno.idAlumno == Inscriptos.idAlumno)
        .where(Inscriptos.idCurso == idCurso)
    )

    if solo_activos:
        stmt = stmt.where(Inscriptos.activo == True)  # noqa: E712

    rows = db.exec(stmt).all()

    out = []
    for r in rows:
        m = r._mapping

        dni_raw = m.get("dni")
        fn_raw = m.get("fecha_nacimiento")
        dir_raw = m.get("direccion")

        out.append({
            "idAlumno": int(m["idAlumno"]),
            "nombre": m.get("nombre"),
            "apellido": m.get("apellido"),
            "dni": decrypt(dni_raw) if dni_raw else None,
            "fecha_nacimiento": decrypt(fn_raw) if fn_raw else None,
            "direccion": decrypt(dir_raw) if dir_raw else None,

            # ✅ requerido por tu response_model
            "fecha_ingreso": m.get("fecha_ingreso"),

            # extras
            "idInscripcion": int(m["idInscripcion"]) if m.get("idInscripcion") is not None else None,
            "idCurso": int(m["idCurso"]) if m.get("idCurso") is not None else None,
            "activo": bool(m.get("activo")),
            "estado": m.get("estado"),
            "fechaBaja": m.get("fechaBaja"),
        })

    return out


# =========================
# Timeline alumno
# =========================
def get_timeline_alumno(db: SessionDep, id_alumno: int) -> list[dict]:
    from sqlalchemy.orm import aliased

    CursoOrigen = aliased(Curso)
    CursoDestino = aliased(Curso)

    timeline: list[dict] = []

    stmt_mov = (
        select(
            MovimientoPromocion.fecha,
            MovimientoPromocionItem.accion,
            CursoOrigen.nombre.label("orig_nombre"),
            CursoOrigen.division.label("orig_div"),
            CursoOrigen.cicloLectivo.label("orig_ciclo"),
            CursoDestino.nombre.label("dest_nombre"),
            CursoDestino.division.label("dest_div"),
            CursoDestino.cicloLectivo.label("dest_ciclo"),
        )
        .join(MovimientoPromocion, MovimientoPromocion.idMovimiento == MovimientoPromocionItem.idMovimiento)
        .join(CursoOrigen, CursoOrigen.idCurso == MovimientoPromocionItem.idCursoOrigen)
        .outerjoin(CursoDestino, CursoDestino.idCurso == MovimientoPromocionItem.idCursoDestino)
        .where(MovimientoPromocionItem.idAlumno == id_alumno)
        .where(MovimientoPromocion.estado == "Activo")
    )
    movs = db.exec(stmt_mov).all()

    for r in movs:
        accion = str(r.accion or "").strip()
        orig_txt = _fmt_curso(r.orig_nombre, r.orig_div, r.orig_ciclo)
        dest_txt = _fmt_curso(r.dest_nombre, r.dest_div, r.dest_ciclo) if r.dest_nombre else None

        if accion == "Promociona":
            detalle = f"De {orig_txt}"
            if dest_txt:
                detalle += f" a {dest_txt}"
        elif accion == "Repite":
            detalle = f"Repite en {orig_txt} "
        elif accion == "Baja":
            detalle = f"Baja en {orig_txt}"
        elif accion == "Egresa":
            detalle = f"Egresa de {orig_txt}"
        else:
            detalle = f"De {orig_txt}"
            if dest_txt:
                detalle += f" a {dest_txt}"

        timeline.append({"fecha": r.fecha, "accion": accion, "detalle": detalle})

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
            _, curso_dest = destino
            dest_text = _fmt_curso(curso_dest.nombre, curso_dest.division, curso_dest.cicloLectivo)

        detalle = f"De {_fmt_curso(curso_origen.nombre, curso_origen.division, curso_origen.cicloLectivo)} a {dest_text}"
        timeline.append({
            "fecha": insc_origen.fechaBaja,
            "accion": "CambioCurso",
            "detalle": detalle
        })

    stmt_pre = (
        select(Preinscripcion)
        .where(Preinscripcion.idAlumno == id_alumno)
        .order_by(desc(Preinscripcion.fechaCreacion))
    )
    pres = db.exec(stmt_pre).all()

    pre_map: dict[str, Preinscripcion] = {}
    for p in pres:
        key = f"{p.CUE}|{p.cicloLectivo}"
        if key not in pre_map:
            pre_map[key] = p

    if pre_map:
        stmt_insc = (
            select(Inscriptos, Curso)
            .join(Curso, Curso.idCurso == Inscriptos.idCurso)
            .where(Inscriptos.idAlumno == id_alumno)
            .order_by(desc(Inscriptos.fechaAlta), desc(Inscriptos.idInscripcion))
        )
        inscs = db.exec(stmt_insc).all()

        for insc, curso in inscs:
            key = f"{curso.CUE}|{curso.cicloLectivo}"
            pre = pre_map.get(key)
            if not pre:
                continue
            if str(pre.estado or "").strip().lower() != "asignada":
                continue

            detalle = f"Ciclo {curso.cicloLectivo}: asignado a {_fmt_curso(curso.nombre, curso.division, curso.cicloLectivo)}"
            timeline.append({
                "fecha": insc.fechaAlta,
                "accion": "AsignacionCurso",
                "detalle": detalle,
            })

    timeline.sort(key=lambda x: x["fecha"], reverse=True)
    return timeline


# =========================
# Historial inscripciones alumno
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


# =========================
# ✅ FIX #2: Auditoría global — decrypt en AMBOS bloques
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
                # ✅ FIX: decrypt en lugar de r.dni crudo
                "dni": decrypt(r.dni) if r.dni else "—",
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
                "idMovimiento": None,
                "fecha": insc_origen.fechaBaja,
                "idAlumno": int(alumno.idAlumno),
                "alumno": f"{alumno.apellido}, {alumno.nombre}",
                # ✅ FIX: decrypt en lugar de alumno.dni crudo
                "dni": decrypt(alumno.dni) if alumno.dni else "—",
                "accion": "CambioCurso",
                "cursoOrigen": f"{curso_origen.nombre} {curso_origen.division}",
                "cursoDestino": dest_txt
            })

    auditoria.sort(key=lambda x: x["fecha"], reverse=True)
    return auditoria


# =========================
# Auditoría individual alumno
# =========================
def get_auditoria_alumno(db: SessionDep, idAlumno: int) -> list[dict]:
    from sqlalchemy.orm import aliased

    _get_alumno_or_404(db, idAlumno)

    CursoOrigen = aliased(Curso)
    CursoDestino = aliased(Curso)

    out: list[dict] = []

    stmt = (
        select(
            MovimientoPromocion.fecha,
            MovimientoPromocion.idMovimiento,
            MovimientoPromocionItem.accion,
            CursoOrigen.nombre.label("orig_nombre"),
            CursoOrigen.division.label("orig_div"),
            CursoOrigen.cicloLectivo.label("orig_ciclo"),
            CursoDestino.nombre.label("dest_nombre"),
            CursoDestino.division.label("dest_div"),
            CursoDestino.cicloLectivo.label("dest_ciclo"),
        )
        .join(MovimientoPromocion, MovimientoPromocion.idMovimiento == MovimientoPromocionItem.idMovimiento)
        .join(CursoOrigen, CursoOrigen.idCurso == MovimientoPromocionItem.idCursoOrigen)
        .outerjoin(CursoDestino, CursoDestino.idCurso == MovimientoPromocionItem.idCursoDestino)
        .where(MovimientoPromocion.estado == "Activo")
        .where(MovimientoPromocionItem.idAlumno == idAlumno)
        .order_by(desc(MovimientoPromocion.fecha), desc(MovimientoPromocion.idMovimiento))
    )

    rows = db.exec(stmt).all()
    for r in rows:
        curso_origen = _fmt_curso(r.orig_nombre, r.orig_div, r.orig_ciclo)
        curso_dest = _fmt_curso(r.dest_nombre, r.dest_div, r.dest_ciclo) if r.dest_nombre else "—"
        out.append({
            "fecha": r.fecha,
            "accion": str(r.accion),
            "cursoOrigen": curso_origen,
            "cursoDestino": curso_dest,
            "idMovimiento": int(r.idMovimiento) if r.idMovimiento else None,
        })

    stmt_cc = (
        select(Inscriptos, Curso)
        .join(Curso, Curso.idCurso == Inscriptos.idCurso)
        .where(
            Inscriptos.idAlumno == idAlumno,
            Inscriptos.estado == EstadoInscripcion.CambioCurso,
            Inscriptos.fechaBaja.is_not(None),
        )
        .order_by(desc(Inscriptos.fechaBaja), desc(Inscriptos.idInscripcion))
    )

    cambios = db.exec(stmt_cc).all()
    for insc_origen, curso_origen in cambios:
        destino = _buscar_destino_cambio_curso(
            db=db,
            idAlumno=idAlumno,
            cicloLectivo=str(curso_origen.cicloLectivo),
            fecha_desde=insc_origen.fechaBaja,
            idCurso_origen=int(insc_origen.idCurso),
        )

        dest_txt = "—"
        if destino:
            _, curso_dest = destino
            dest_txt = _fmt_curso(curso_dest.nombre, curso_dest.division, curso_dest.cicloLectivo)

        out.append({
            "fecha": insc_origen.fechaBaja,
            "accion": "CambioCurso",
            "cursoOrigen": _fmt_curso(curso_origen.nombre, curso_origen.division, curso_origen.cicloLectivo),
            "cursoDestino": dest_txt,
            "idMovimiento": None,
        })

    out.sort(key=lambda x: x["fecha"] or date.min, reverse=True)
    return out