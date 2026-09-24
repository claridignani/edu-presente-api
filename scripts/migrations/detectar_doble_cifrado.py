# detectar_doble_cifrado.py
import os
from dotenv import load_dotenv
load_dotenv()

from sqlmodel import create_engine, Session, select
from app.core.config import DATABASE_URL
from app.core.encryption import decrypt

# Importamos todos los modelos relacionados para que SQLAlchemy
# pueda resolver las relaciones (Alumno referencia a Curso, etc.)
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
        afectados = []

        for a in alumnos:
            campos_afectados = []
            if esta_doble_cifrado(a.dni):
                campos_afectados.append("dni")
            if esta_doble_cifrado(a.direccion):
                campos_afectados.append("direccion")
            if esta_doble_cifrado(a.fecha_nacimiento):
                campos_afectados.append("fecha_nacimiento")

            if campos_afectados:
                afectados.append((a.idAlumno, campos_afectados))

        print(f"Total alumnos: {len(alumnos)}")
        print(f"Afectados: {len(afectados)}\n")
        for idAlumno, campos in afectados:
            print(f"  idAlumno={idAlumno} → campos: {', '.join(campos)}")


if __name__ == "__main__":
    main()