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
from app.schemas.inscriptos import EstadoInscripcion, AccionPromocion
from app.schemas.movimientos import (
    PromocionarOut,
    MovimientoDetalleOut,
    MovimientoHistorialOut,
    AuditoriaEventoOut,
    TimelineItemOut,
)
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


def _curso_label(nombre: str | None, div: str | None, ciclo: str | None) -> str:
    n = (nombre or "").strip()
    d = (div or "").strip()
    c = (ciclo or "").strip()
    base = f"{n} {d}".strip()
    return f"{base} ({c})".strip() if c else base or "—"


def _accion_to_key_label(accion: str) -> tuple[str, str]:
    a = (accion or "").strip()
    lower = a.lower()

    # Normalizamos acciones de MovimientosPromocionItem
    if lower == "promociona":
        return ("promociona", "Promoción")
    if lower == "repite":
        return ("repite", "Repitencia")
    if lower == "egresa":
        return ("egresa", "Egreso")
    if lower == "baja":
        return ("baja", "Baja")

    # Inscriptos
    if lower == "cambiocurso" or lower == "cambio_curso":
        return ("cambio_curso", "Cambio de curso")

    # fallback
    return (lower.replace(" ", "_") or "evento", a or "Evento")


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
# ✅ Listar últimos movimientos por CUE (ACTAS)
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
            CursoDestino.cicloLectivo.label("dest_ciclo"),
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
        movimientos.append(
            {
                "idMovimiento": m.idMovimiento,
                "fecha": m.fecha,
                "estado": m.estado,
                "created_at": m.created_at,
                "cursoOrigen": f"{row.orig_nombre} {row.orig_div} ({row.orig_ciclo})",
                "cursoDestino": f"{row.dest_nombre} {row.dest_div} ({row.dest_ciclo})",
                "idCursoOrigen": m.idCursoOrigen,
                "idCursoDestino": m.idCursoDestino,
                "director_id": m.director_id,
            }
        )
    return movimientos


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
                "accion": item.MovimientoPromocionItem.accion,
            }
            for item in results
        ],
    }


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
# INSCRIBIR (regla 1-activa por ciclo)
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


# ==========================================================
# ✅ NUEVO: Historial de inscripciones por alumno (para debug/uso)
# ==========================================================
def get_historial_inscripciones_alumno(db: SessionDep, id_alumno: int) -> list[dict]:
    _get_alumno_or_404(db, id_alumno)

    stmt = (
        select(Inscriptos, Curso)
        .join(Curso, Curso.idCurso == Inscriptos.idCurso)
        .where(Inscriptos.idAlumno == id_alumno)
        .order_by(desc(Inscriptos.fechaAlta), desc(Inscriptos.idInscripcion))
    )
    rows = db.exec(stmt).all()

    out = []
    for insc, curso in rows:
        out.append(
            {
                "idInscripcion": insc.idInscripcion,
                "idCurso": insc.idCurso,
                "cicloLectivo": curso.cicloLectivo,
                "cursoNombre": curso.nombre,
                "cursoDivision": curso.division,
                "fechaAlta": insc.fechaAlta,
                "fechaBaja": insc.fechaBaja,
                "activo": insc.activo,
                "estado": str(insc.estado),
            }
        )
    return out


# ==========================================================
# ✅ Timeline unificada (Movimientos + Cambios de curso)
# ==========================================================
def get_timeline_alumno(db: SessionDep, id_alumno: int) -> list[TimelineItemOut]:
    _get_alumno_or_404(db, id_alumno)

    # 1) Traemos historial de inscripciones (para detectar CambioCurso)
    hist = get_historial_inscripciones_alumno(db, id_alumno)

    # armamos lookup por (fechaAlta, cicloLectivo) para detectar destino rápido
    # (muchas veces fechaAlta destino == fechaBaja origen)
    dest_index: dict[tuple[str, str], dict] = {}
    for h in hist:
        key = (str(h["fechaAlta"]), str(h["cicloLectivo"]))
        # nos quedamos con el "más reciente" por si hubiera más de uno
        if key not in dest_index:
            dest_index[key] = h

    timeline: list[TimelineItemOut] = []

    # 1.a) Eventos de Cambio de curso
    for h in hist:
        if str(h.get("estado")) != str(EstadoInscripcion.CambioCurso):
            continue
        if not h.get("fechaBaja"):
            continue

        origen = _curso_label(h.get("cursoNombre"), h.get("cursoDivision"), h.get("cicloLectivo"))

        dest = dest_index.get((str(h["fechaBaja"]), str(h["cicloLectivo"])))
        if dest and int(dest.get("idCurso") or 0) != int(h.get("idCurso") or 0):
            destino = _curso_label(dest.get("cursoNombre"), dest.get("cursoDivision"), dest.get("cicloLectivo"))
            detalle = f"De {origen} a {destino}"
        else:
            # fallback (si no encontramos destino exacto)
            detalle = f"Salida de {origen}"

        timeline.append(
            TimelineItemOut(
                fecha=h["fechaBaja"],
                accionKey="cambio_curso",
                accionLabel="Cambio de curso",
                detalle=detalle,
            )
        )

    # 2) Eventos de promociones (MovimientoPromocionItem)
    from sqlalchemy.orm import aliased

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
            CursoDestino.cicloLectivo.label("dest_ciclo"),
        )
        .join(MovimientoPromocion, MovimientoPromocion.idMovimiento == MovimientoPromocionItem.idMovimiento)
        .join(CursoOrigen, CursoOrigen.idCurso == MovimientoPromocionItem.idCursoOrigen)
        .outerjoin(CursoDestino, CursoDestino.idCurso == MovimientoPromocionItem.idCursoDestino)
        .where(MovimientoPromocionItem.idAlumno == id_alumno)
        .where(MovimientoPromocion.estado == "Activo")
        .order_by(desc(MovimientoPromocion.fecha))
    )

    results = db.exec(stmt).all()
    for r in results:
        origen = _curso_label(r.orig_nombre, r.orig_div, r.orig_ciclo)
        if r.dest_nombre:
            destino = _curso_label(r.dest_nombre, r.dest_div, r.dest_ciclo)
            detalle = f"De {origen} a {destino}"
        else:
            detalle = f"Desde {origen}"

        key, label = _accion_to_key_label(str(r.accion))

        timeline.append(
            TimelineItemOut(
                fecha=r.fecha,
                accionKey=key,
                accionLabel=label,
                detalle=detalle,
            )
        )

    # Orden final (desc)
    timeline.sort(key=lambda x: x.fecha, reverse=True)
    return timeline


# ==========================================================
# ✅ Auditoría unificada por escuela (lista plana)
# ==========================================================
def get_auditoria_trayectorias(
    db: SessionDep,
    cue: str,
    anio: str | None = None,
    accion: str | None = None,
) -> list[AuditoriaEventoOut]:
    """
    Mezcla:
    - Movimientos (Promociona/Repite/Egresa/Baja) desde MovimientoPromocionItem
    - Cambios de curso (CambioCurso) desde Inscriptos
    """
    cue = (cue or "").strip()
    if not cue:
        return []

    eventos: list[AuditoriaEventoOut] = []

    # ---------------------------------------
    # A) Movimientos (ya existente, pero plano)
    # ---------------------------------------
    from sqlalchemy.orm import aliased

    CursoOrigen = aliased(Curso)
    CursoDestino = aliased(Curso)

    stmt_mov = (
        select(
            MovimientoPromocion.fecha,
            MovimientoPromocionItem.accion,
            Alumno.idAlumno,
            Alumno.apellido,
            Alumno.nombre,
            Alumno.dni,
            CursoOrigen.idCurso.label("idCursoOrigen"),
            CursoOrigen.nombre.label("orig_nombre"),
            CursoOrigen.division.label("orig_div"),
            CursoOrigen.cicloLectivo.label("orig_ciclo"),
            CursoDestino.idCurso.label("idCursoDestino"),
            CursoDestino.nombre.label("dest_nombre"),
            CursoDestino.division.label("dest_div"),
            CursoDestino.cicloLectivo.label("dest_ciclo"),
        )
        .join(MovimientoPromocion, MovimientoPromocion.idMovimiento == MovimientoPromocionItem.idMovimiento)
        .join(Alumno, Alumno.idAlumno == MovimientoPromocionItem.idAlumno)
        .join(CursoOrigen, CursoOrigen.idCurso == MovimientoPromocionItem.idCursoOrigen)
        .outerjoin(CursoDestino, CursoDestino.idCurso == MovimientoPromocionItem.idCursoDestino)
        .where(MovimientoPromocion.cue == cue)
        .where(MovimientoPromocion.estado == "Activo")
    )

    if anio:
        stmt_mov = stmt_mov.where(func.year(MovimientoPromocion.fecha) == int(anio))

    if accion:
        stmt_mov = stmt_mov.where(MovimientoPromocionItem.accion == accion)

    stmt_mov = stmt_mov.order_by(desc(MovimientoPromocion.fecha))

    rows_mov = db.exec(stmt_mov).all()
    for r in rows_mov:
        key, label = _accion_to_key_label(str(r.accion))

        curso_origen = _curso_label(r.orig_nombre, r.orig_div, r.orig_ciclo)
        curso_dest = _curso_label(r.dest_nombre, r.dest_div, r.dest_ciclo) if r.dest_nombre else "—"

        detalle = f"De {curso_origen} a {curso_dest}" if r.dest_nombre else f"Desde {curso_origen}"

        eventos.append(
            AuditoriaEventoOut(
                fecha=r.fecha,
                idAlumno=r.idAlumno,
                alumno=f"{r.apellido}, {r.nombre}",
                dni=r.dni,
                accionKey=key,
                accionLabel=label,
                detalle=detalle,
                idCursoOrigen=int(r.idCursoOrigen) if r.idCursoOrigen else None,
                idCursoDestino=int(r.idCursoDestino) if r.idCursoDestino else None,
                cursoOrigen=curso_origen,
                cursoDestino=curso_dest,
            )
        )

    # ---------------------------------------
    # B) Cambios de curso (Inscriptos)
    # ---------------------------------------
    stmt_insc = (
        select(Inscriptos, Curso, Alumno)
        .join(Curso, Curso.idCurso == Inscriptos.idCurso)
        .join(Alumno, Alumno.idAlumno == Inscriptos.idAlumno)
        .where(Curso.CUE == cue)
        .where(Inscriptos.estado == EstadoInscripcion.CambioCurso)
        .where(Inscriptos.fechaBaja.is_not(None))
    )

    if anio:
        stmt_insc = stmt_insc.where(func.year(Inscriptos.fechaBaja) == int(anio))

    # si pidieron filtrar por acción y no es CambioCurso, no agregamos nada
    if accion and accion != "CambioCurso":
        rows_insc = []
    else:
        rows_insc = db.exec(stmt_insc.order_by(desc(Inscriptos.fechaBaja))).all()

    # Para encontrar destino: buscamos inscripción que empieza en fechaBaja (mismo ciclo y alumno)
    # armamos índice de inscripciones por alumno
    by_alumno: dict[int, list[tuple[Inscriptos, Curso, Alumno]]] = {}
    for insc, curso, alu in rows_insc:
        by_alumno.setdefault(int(alu.idAlumno), []).append((insc, curso, alu))

    # También necesitamos todas las inscripciones del alumno (para detectar destino)
    # (lo hacemos por alumno encontrado en rows_insc)
    for id_alumno in list(by_alumno.keys()):
        # traemos todas sus inscripciones (no solo CambioCurso) para buscar destino
        stmt_all = (
            select(Inscriptos, Curso)
            .join(Curso, Curso.idCurso == Inscriptos.idCurso)
            .where(Inscriptos.idAlumno == id_alumno)
        )
        all_rows = db.exec(stmt_all).all()
        idx_dest: dict[tuple[str, str], tuple[Inscriptos, Curso]] = {}
        for insc2, curso2 in all_rows:
            idx_dest[(str(insc2.fechaAlta), str(curso2.cicloLectivo))] = (insc2, curso2)

        for insc, curso, alu in by_alumno[id_alumno]:
            if not insc.fechaBaja:
                continue

            origen = _curso_label(curso.nombre, curso.division, curso.cicloLectivo)
            dest_tuple = idx_dest.get((str(insc.fechaBaja), str(curso.cicloLectivo)))
            if dest_tuple and int(dest_tuple[0].idCurso) != int(insc.idCurso):
                dest_curso = dest_tuple[1]
                destino = _curso_label(dest_curso.nombre, dest_curso.division, dest_curso.cicloLectivo)
                detalle = f"De {origen} a {destino}"
                idCursoDestino = int(dest_curso.idCurso)
                cursoDestino = destino
            else:
                detalle = f"Salida de {origen}"
                idCursoDestino = None
                cursoDestino = None

            eventos.append(
                AuditoriaEventoOut(
                    fecha=insc.fechaBaja,
                    idAlumno=int(alu.idAlumno),
                    alumno=f"{alu.apellido}, {alu.nombre}",
                    dni=alu.dni,
                    accionKey="cambio_curso",
                    accionLabel="Cambio de curso",
                    detalle=detalle,
                    idCursoOrigen=int(curso.idCurso),
                    idCursoDestino=idCursoDestino,
                    cursoOrigen=origen,
                    cursoDestino=cursoDestino,
                )
            )
    eventos.sort(key=lambda x: x.fecha, reverse=True)
    return eventos
