from __future__ import annotations

from datetime import date
from fastapi import HTTPException
from sqlmodel import select
from sqlalchemy import desc

from app.dependencies import SessionDep
from app.models.inscriptos import Inscriptos
from app.models.alumno import Alumno
from app.models.curso import Curso
from app.models.movimiento_promocion import MovimientoPromocion
from app.models.movimiento_promocion_item import MovimientoPromocionItem
from app.schemas.inscriptos import EstadoInscripcion, AccionPromocion
from app.schemas.movimientos import PromocionarOut, MovimientoOut, MovimientoDetalleOut, MovimientoItemOut
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
        # 1) crear cabecera movimiento
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

        # 2) procesar alumnos y registrar ids de inscripciones
        for item in alumnos:
            _get_alumno_or_404(db, item.idAlumno)

            # buscar inscripción activa en origen
            stmt = select(Inscriptos).where(
                Inscriptos.idCurso == idCursoOrigen,
                Inscriptos.idAlumno == item.idAlumno,
                Inscriptos.activo == True,  # noqa: E712
            )
            insc_origen = db.exec(stmt).first()
            id_insc_origen = int(insc_origen.idInscripcion) if insc_origen else None

            # cerrar origen según acción
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

            # crear destino solo si corresponde
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

            # registrar item del movimiento
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
# ✅ Listar últimos movimientos por CUE
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
            # 1) borrar insc destino si existe
            if it.idInscripcionDestino:
                insc_dest = db.get(Inscriptos, it.idInscripcionDestino)
                if insc_dest:
                    db.delete(insc_dest)

            # 2) reabrir origen si existe
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
# INSCRIBIR (con regla 1-activa)
# =========================
def inscribir_alumno(idCurso: int, idAlumno: int, db: SessionDep, fechaAlta: date | None = None):
    curso = _get_curso_or_404(db, idCurso)
    _get_alumno_or_404(db, idAlumno)

    hoy = fechaAlta or date.today()

    # si ya está activo en ESTE curso -> error
    stmt_mismo = select(Inscriptos).where(
        Inscriptos.idCurso == idCurso,
        Inscriptos.idAlumno == idAlumno,
        Inscriptos.activo == True,  # noqa: E712
    )
    if db.exec(stmt_mismo).first():
        raise HTTPException(status_code=400, detail="El alumno ya está inscripto y activo en este curso")

    # si está activo en otro curso del MISMO ciclo -> cerrar como cambio
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


