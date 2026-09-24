# reparar_doble_cifrado.py
import os
from dotenv import load_dotenv
load_dotenv()

from sqlmodel import create_engine, Session, select
from app.core.config import DATABASE_URL
from app.core.encryption import decrypt, hash_for_search

from app.models.alumno import Alumno
from app.models.curso import Curso
from app.models.usuario import Usuario
from app.models.responsable import Responsable
from app.models.escuela import Escuela

engine = create_engine(DATABASE_URL)


def esta_doble_cifrado(valor: str) -> bool:
    if not valor or not str(valor).startswith("gAAAAA"):
        return False
    paso1 = decrypt(valor)
    return str(paso1).startswith("gAAAAA")


def main():
    with Session(engine) as session:
        alumnos = session.exec(select(Alumno)).all()
        reparados = 0

        for a in alumnos:
            cambio = False

            if esta_doble_cifrado(a.dni):
                a.dni = decrypt(a.dni)
                cambio = True

            if esta_doble_cifrado(a.direccion):
                a.direccion = decrypt(a.direccion)
                cambio = True

            if esta_doble_cifrado(a.fecha_nacimiento):
                a.fecha_nacimiento = decrypt(a.fecha_nacimiento)
                cambio = True

            if cambio and a.dni:
                dni_plano = decrypt(a.dni)
                a.dni_hash = hash_for_search(dni_plano)

            if cambio:
                session.add(a)
                reparados += 1
                print(f"Reparado idAlumno={a.idAlumno}")

        session.commit()
        print(f"\nTotal reparados: {reparados}")


if __name__ == "__main__":
    main()