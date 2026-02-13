from __future__ import annotations

from datetime import date
from fastapi import HTTPException
from sqlmodel import select

from app.dependencies import SessionDep
from app.models.inscriptos import Inscriptos
from app.models.alumno import Alumno
from app.models.curso import Curso
from app.schemas.inscriptos import EstadoInscripcion, AccionPromocion
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


# =========================
# PROMOCIONAR (fin de ciclo)
# =========================
def promocionar_alumnos(idCursoOrigen: int, idCursoDestino: int, alumnos, db: SessionDep, fecha: date | None = None):
    origen = _get_curso_or_404(db, idCursoOrigen)
    destino = _get_curso_or_404(db, idCursoDestino)

    if origen.cicloLectivo == destino.cicloLectivo:
        raise HTTPException(status_code=400, detail="Curso destino debe ser de OTRO ciclo lectivo")

    hoy = fecha or date.today()

    for item in alumnos:
        _get_alumno_or_404(db, item.idAlumno)

        # cerrar inscripción activa en origen (si existe)
        stmt = select(Inscriptos).where(
            Inscriptos.idCurso == idCursoOrigen,
            Inscriptos.idAlumno == item.idAlumno,
            Inscriptos.activo == True,  # noqa: E712
        )
        insc_origen = db.exec(stmt).first()
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

        # crear en destino solo si corresponde
        if item.accion in (AccionPromocion.Promociona, AccionPromocion.Repite):
            # esto ya respeta "1 activa" porque es otro ciclo, pero igual usamos inscribir estándar
            nueva = inscribir_alumno(idCursoDestino, item.idAlumno, db, fechaAlta=hoy)
            if item.accion == AccionPromocion.Repite:
                nueva.estado = EstadoInscripcion.Repitente
                db.add(nueva)

    db.commit()
    return {"ok": True}
