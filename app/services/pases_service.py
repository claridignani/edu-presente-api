from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import func
from sqlmodel import Session, select

from app.core.encryption import decrypt
from app.models.alumno import Alumno
from app.models.escuela import Escuela
from app.models.inscriptos import Inscriptos
from app.models.pase_entrada import PaseEntrada
from app.models.pase_salida import PaseSalida
from app.schemas.inscriptos import EstadoInscripcion
from app.schemas.pase import (
    AccionPrevia,
    ComprobanteData,
    EstadoPase,
    EstadoPaseEntrada,
    PaseEntradaCreate,
    PaseEntradaListItem,
    PaseEntradaPublic,
    PaseSalidaBulkCreate,
    PaseSalidaCreate,
    PaseSalidaListItem,
    PaseSalidaPublic,
    TipoPase,
)


# ──────────────────────────────────────────
# Helpers internos
# ──────────────────────────────────────────

def _generar_nro_pase(db: Session, cue: str, year: int) -> str:
    """Genera el próximo correlativo: CUE-YYYY-NNNN."""
    prefix = f"{cue}-{year}-%"
    count = db.exec(
        select(func.count(PaseSalida.idPase)).where(
            PaseSalida.nroPase.like(prefix)
        )
    ).one()
    return f"{cue}-{year}-{str(count + 1).zfill(4)}"


def _acciones_to_str(acciones: list[AccionPrevia] | None) -> str | None:
    if not acciones:
        return None
    return ",".join([a.value for a in acciones])


def _str_to_acciones(s: str | None) -> list[AccionPrevia] | None:
    if not s:
        return None
    return [AccionPrevia(x) for x in s.split(",")]


def _get_alumno_or_404(db: Session, idAlumno: int) -> Alumno:
    alumno = db.get(Alumno, idAlumno)
    if not alumno:
        raise HTTPException(status_code=404, detail=f"Alumno {idAlumno} no encontrado")
    return alumno


def _build_pase_public(pase: PaseSalida, alumno: Alumno) -> PaseSalidaPublic:
    return PaseSalidaPublic(
        idPase=pase.idPase,
        idAlumno=pase.idAlumno,
        idInscripcion=pase.idInscripcion,
        idMovimiento=pase.idMovimiento,
        cueOrigen=pase.cueOrigen,
        tipoPase=TipoPase(pase.tipoPase),
        motivo=pase.motivo,
        accionesPrevias=_str_to_acciones(pase.accionesPrevias),
        cueDestino=pase.cueDestino,
        nombreEscuelaDestino=pase.nombreEscuelaDestino,
        nroPase=pase.nroPase,
        fecha=pase.fecha,
        estado=EstadoPase(pase.estado),
        created_at=pase.created_at,
        # dni está encriptado en la DB → desencriptamos para la respuesta
        nombreAlumno=alumno.nombre,
        apellidoAlumno=alumno.apellido,
        dniAlumno=decrypt(alumno.dni),
    )


def _dar_baja_inscripcion(db: Session, idInscripcion: int) -> None:
    inscripcion = db.get(Inscriptos, idInscripcion)
    if inscripcion:
        inscripcion.activo = False
        inscripcion.fechaBaja = date.today()
        inscripcion.estado = EstadoInscripcion.Baja
        db.add(inscripcion)


def _reactivar_inscripcion(db: Session, idInscripcion: int) -> None:
    inscripcion = db.get(Inscriptos, idInscripcion)
    if inscripcion:
        inscripcion.activo = True
        inscripcion.fechaBaja = None
        inscripcion.estado = EstadoInscripcion.Activo
        db.add(inscripcion)


# ──────────────────────────────────────────
# Pase Salida — individual
# Usado desde: editar alumno / detalle alumno
# ──────────────────────────────────────────

def crear_pase_salida(db: Session, payload: PaseSalidaCreate) -> PaseSalidaPublic:
    alumno = _get_alumno_or_404(db, payload.idAlumno)

    if (
        payload.tipoPase == TipoPase.CON_PASE
        and not payload.cueDestino
        and not payload.nombreEscuelaDestino
    ):
        raise HTTPException(
            status_code=422,
            detail="Para CON_PASE se requiere cueDestino o nombreEscuelaDestino.",
        )

    nroPase = _generar_nro_pase(db, payload.cueOrigen, payload.fecha.year)

    pase = PaseSalida(
        idAlumno=payload.idAlumno,
        idInscripcion=payload.idInscripcion,
        idMovimiento=payload.idMovimiento,
        cueOrigen=payload.cueOrigen,
        tipoPase=payload.tipoPase.value,
        motivo=payload.motivo.value,
        accionesPrevias=_acciones_to_str(payload.accionesPrevias),
        cueDestino=payload.cueDestino,
        nombreEscuelaDestino=payload.nombreEscuelaDestino,
        nroPase=nroPase,
        fecha=payload.fecha,
        estado="Activo",
    )
    db.add(pase)

    if payload.idInscripcion:
        _dar_baja_inscripcion(db, payload.idInscripcion)

    db.commit()
    db.refresh(pase)
    return _build_pase_public(pase, alumno)


# ──────────────────────────────────────────
# Pase Salida — bulk
# Usado desde: flujo mover-alumnos (paso 3)
# ──────────────────────────────────────────

def crear_pases_salida_bulk(
    db: Session, payload: PaseSalidaBulkCreate
) -> list[PaseSalidaPublic]:
    resultados: list[PaseSalidaPublic] = []

    for item in payload.pases:
        alumno = _get_alumno_or_404(db, item.idAlumno)

        if (
            item.tipoPase == TipoPase.CON_PASE
            and not item.cueDestino
            and not item.nombreEscuelaDestino
        ):
            raise HTTPException(
                status_code=422,
                detail=f"Alumno {item.idAlumno}: para CON_PASE se requiere escuela destino.",
            )

        nroPase = _generar_nro_pase(db, payload.cueOrigen, item.fecha.year)

        pase = PaseSalida(
            idAlumno=item.idAlumno,
            idInscripcion=item.idInscripcion,
            idMovimiento=payload.idMovimiento,
            cueOrigen=payload.cueOrigen,
            tipoPase=item.tipoPase.value,
            motivo=item.motivo.value,
            accionesPrevias=_acciones_to_str(item.accionesPrevias),
            cueDestino=item.cueDestino,
            nombreEscuelaDestino=item.nombreEscuelaDestino,
            nroPase=nroPase,
            fecha=item.fecha,
            estado="Activo",
        )
        db.add(pase)

        if item.idInscripcion:
            _dar_baja_inscripcion(db, item.idInscripcion)

        db.flush()  # obtener idPase sin hacer commit todavía
        resultados.append(_build_pase_public(pase, alumno))

    db.commit()
    return resultados


# ──────────────────────────────────────────
# Pase Salida — anular
# ──────────────────────────────────────────

def anular_pase_salida(db: Session, idPase: int) -> PaseSalidaPublic:
    pase = db.get(PaseSalida, idPase)
    if not pase:
        raise HTTPException(status_code=404, detail="Pase no encontrado")
    if pase.estado == "Anulado":
        raise HTTPException(status_code=400, detail="El pase ya está anulado")

    pase.estado = "Anulado"
    db.add(pase)

    if pase.idInscripcion:
        _reactivar_inscripcion(db, pase.idInscripcion)

    db.commit()
    db.refresh(pase)

    alumno = _get_alumno_or_404(db, pase.idAlumno)
    return _build_pase_public(pase, alumno)


# ──────────────────────────────────────────
# Pase Salida — histórico por escuela
# ──────────────────────────────────────────

def listar_salidas(
    db: Session,
    cue: str,
    limit: int = 50,
    offset: int = 0,
) -> list[PaseSalidaListItem]:
    pases = db.exec(
        select(PaseSalida)
        .where(PaseSalida.cueOrigen == cue)
        .order_by(PaseSalida.fecha.desc())
        .offset(offset)
        .limit(limit)
    ).all()

    resultado: list[PaseSalidaListItem] = []
    for p in pases:
        alumno = db.get(Alumno, p.idAlumno)
        if not alumno:
            continue

        destino: str | None = None
        if p.cueDestino and p.nombreEscuelaDestino:
            destino = f"{p.cueDestino} - {p.nombreEscuelaDestino}"
        elif p.nombreEscuelaDestino:
            destino = p.nombreEscuelaDestino

        resultado.append(
            PaseSalidaListItem(
                idPase=p.idPase,
                nroPase=p.nroPase,
                dni=decrypt(alumno.dni),        # ← desencriptamos
                apellidoNombre=f"{alumno.apellido}, {alumno.nombre}",
                fechaPase=p.fecha,
                tipoPase=TipoPase(p.tipoPase),
                motivo=p.motivo,
                establecimientoDestino=destino,
                estado=EstadoPase(p.estado),
            )
        )
    return resultado


# ──────────────────────────────────────────
# Comprobante — datos para PDF en el front
# ──────────────────────────────────────────

def get_comprobante(
    db: Session,
    idPase: int,
    nombre_director: str = "",
) -> ComprobanteData:
    pase = db.get(PaseSalida, idPase)
    if not pase:
        raise HTTPException(status_code=404, detail="Pase no encontrado")

    alumno = _get_alumno_or_404(db, pase.idAlumno)
    escuela_origen = db.get(Escuela, pase.cueOrigen)
    nombre_origen = escuela_origen.nombre if escuela_origen else pase.cueOrigen

    return ComprobanteData(
        nroPase=pase.nroPase,
        fecha=pase.fecha,
        nombreAlumno=alumno.nombre,
        apellidoAlumno=alumno.apellido,
        dniAlumno=decrypt(alumno.dni),          # ← desencriptamos
        cueOrigen=pase.cueOrigen,
        nombreEscuelaOrigen=nombre_origen,
        cueDestino=pase.cueDestino,
        nombreEscuelaDestino=pase.nombreEscuelaDestino,
        tipoPase=TipoPase(pase.tipoPase),
        motivo=pase.motivo,
        accionesPrevias=_str_to_acciones(pase.accionesPrevias),
        nombreDirector=nombre_director,
    )


# ──────────────────────────────────────────
# Pase Entrada — crear
# Usado desde: alta de alumno nuevo con pase
# ──────────────────────────────────────────

def crear_pase_entrada(db: Session, payload: PaseEntradaCreate) -> PaseEntradaPublic:
    _get_alumno_or_404(db, payload.idAlumno)

    pase = PaseEntrada(
        idAlumno=payload.idAlumno,
        idPreinscripcion=payload.idPreinscripcion,
        cueDestino=payload.cueDestino,
        cueOrigen=payload.cueOrigen,
        nombreEscuelaOrigen=payload.nombreEscuelaOrigen,
        nroPaseOrigen=payload.nroPaseOrigen,
        fecha=payload.fecha,
        estado="Pendiente",
    )
    db.add(pase)
    db.commit()
    db.refresh(pase)
    return PaseEntradaPublic.model_validate(pase)


# ──────────────────────────────────────────
# Pase Entrada — confirmar
# ──────────────────────────────────────────

def confirmar_pase_entrada(db: Session, idPaseEntrada: int) -> PaseEntradaPublic:
    pase = db.get(PaseEntrada, idPaseEntrada)
    if not pase:
        raise HTTPException(status_code=404, detail="Pase de entrada no encontrado")
    if pase.estado == "Confirmado":
        raise HTTPException(status_code=400, detail="El pase ya está confirmado")

    pase.estado = "Confirmado"
    db.add(pase)
    db.commit()
    db.refresh(pase)
    return PaseEntradaPublic.model_validate(pase)


# ──────────────────────────────────────────
# Pase Entrada — histórico por escuela
# ──────────────────────────────────────────

def listar_entradas(
    db: Session,
    cue: str,
    limit: int = 50,
    offset: int = 0,
) -> list[PaseEntradaListItem]:
    pases = db.exec(
        select(PaseEntrada)
        .where(PaseEntrada.cueDestino == cue)
        .order_by(PaseEntrada.fecha.desc())
        .offset(offset)
        .limit(limit)
    ).all()

    resultado: list[PaseEntradaListItem] = []
    for p in pases:
        alumno = db.get(Alumno, p.idAlumno)
        if not alumno:
            continue

        escuela_origen: str | None = None
        if p.cueOrigen and p.nombreEscuelaOrigen:
            escuela_origen = f"{p.cueOrigen} - {p.nombreEscuelaOrigen}"
        elif p.nombreEscuelaOrigen:
            escuela_origen = p.nombreEscuelaOrigen

        resultado.append(
            PaseEntradaListItem(
                idPaseEntrada=p.idPaseEntrada,
                dni=decrypt(alumno.dni),        # ← desencriptamos
                apellidoNombre=f"{alumno.apellido}, {alumno.nombre}",
                fechaPase=p.fecha,
                escuelaOrigen=escuela_origen or "Sin pase",
                estado=EstadoPaseEntrada(p.estado),
            )
        )
    return resultado


# ──────────────────────────────────────────
# Búsqueda de escuelas (parcial por nombre o CUE)
# ──────────────────────────────────────────

def buscar_escuelas(db: Session, q: str, limit: int = 10) -> list[Escuela]:
    term = f"%{q}%"
    return db.exec(
        select(Escuela)
        .where(Escuela.nombre.ilike(term) | Escuela.CUE.ilike(term))
        .limit(limit)
    ).all()