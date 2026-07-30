# migrate_encrypt.py
import os
from dotenv import load_dotenv
load_dotenv()

from sqlmodel import create_engine, Session, select
from app.core.config import DATABASE_URL
from app.core.encryption import encrypt, decrypt, hash_for_search
from app.models.alumno import Alumno
from app.models.curso import Curso
from app.models.usuario import Usuario
from app.models.responsable import Responsable
from app.models.escuela import Escuela

engine = create_engine(DATABASE_URL)


def ya_encriptado(valor: str) -> bool:
    """Fernet siempre empieza con 'gAAAAA', detectamos si ya fue encriptado."""
    if not valor:
        return False
    return str(valor).startswith("gAAAAA")


def migrar_alumnos(session: Session):
    alumnos = session.exec(select(Alumno)).all()
    migrados = 0
    for alumno in alumnos:
        cambio = False

        if alumno.dni and not ya_encriptado(alumno.dni):
            alumno.dni = encrypt(alumno.dni)
            cambio = True

        if alumno.fecha_nacimiento and not ya_encriptado(str(alumno.fecha_nacimiento)):
            alumno.fecha_nacimiento = encrypt(str(alumno.fecha_nacimiento))
            cambio = True

        if alumno.direccion and not ya_encriptado(alumno.direccion):
            alumno.direccion = encrypt(alumno.direccion)
            cambio = True

        # Siempre recalculamos el hash sobre el valor ya encriptado
        if alumno.dni:
            dni_plain = decrypt(alumno.dni)
            nuevo_hash = hash_for_search(dni_plain)
            if getattr(alumno, "dni_hash", "") != nuevo_hash:
                alumno.dni_hash = nuevo_hash
                cambio = True

        if cambio:
            session.add(alumno)
            migrados += 1

    session.commit()
    print(f"Alumnos migrados: {migrados}/{len(alumnos)}")


def migrar_usuarios(session: Session):
    usuarios = session.exec(select(Usuario)).all()
    migrados = 0
    for usuario in usuarios:
        cambio = False

        if usuario.dni and not ya_encriptado(usuario.dni):
            usuario.dni = encrypt(usuario.dni)
            cambio = True

        if usuario.cuil and not ya_encriptado(usuario.cuil):
            usuario.cuil = encrypt(usuario.cuil)
            cambio = True

        if usuario.fechaNacimiento and not ya_encriptado(str(usuario.fechaNacimiento)):
            usuario.fechaNacimiento = encrypt(str(usuario.fechaNacimiento))
            cambio = True

        # Siempre recalculamos el hash sobre el valor ya encriptado
        if usuario.dni:
            dni_plain = decrypt(usuario.dni)
            nuevo_hash = hash_for_search(dni_plain)
            if getattr(usuario, "dni_hash", "") != nuevo_hash:
                usuario.dni_hash = nuevo_hash
                cambio = True

        if cambio:
            session.add(usuario)
            migrados += 1

    session.commit()
    print(f"Usuarios migrados: {migrados}/{len(usuarios)}")


def migrar_responsables(session: Session):
    responsables = session.exec(select(Responsable)).all()
    migrados = 0
    for responsable in responsables:
        cambio = False

        if responsable.dni and not ya_encriptado(responsable.dni):
            responsable.dni = encrypt(responsable.dni)
            cambio = True

        if responsable.direccion and not ya_encriptado(responsable.direccion):
            responsable.direccion = encrypt(responsable.direccion)
            cambio = True

        # Siempre recalculamos el hash sobre el valor ya encriptado
        if responsable.dni:
            dni_plain = decrypt(responsable.dni)
            nuevo_hash = hash_for_search(dni_plain)
            if getattr(responsable, "dni_hash", "") != nuevo_hash:
                responsable.dni_hash = nuevo_hash
                cambio = True

        if cambio:
            session.add(responsable)
            migrados += 1

    session.commit()
    print(f"Responsables migrados: {migrados}/{len(responsables)}")


if __name__ == "__main__":
    print("Iniciando migracion de encriptacion...")
    with Session(engine) as session:
        migrar_alumnos(session)
        migrar_usuarios(session)
        migrar_responsables(session)
    print("Migracion completada.")