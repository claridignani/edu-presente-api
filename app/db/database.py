import os
from sqlmodel import SQLModel, create_engine
from app.core.config import DATABASE_URL

engine = create_engine(DATABASE_URL)

def create_db_and_tables():
        import app.models.usuario
        import app.models.escuela
        import app.models.rol
        import app.models.curso
        import app.models.alumno
        import app.models.asistencia
        import app.models.responsable
        import app.models.parentesco
        import app.models.curso_docente
        import app.models.invitacion_docente
        import app.models.movimiento_promocion
        import app.models.movimiento_promocion_item
        import app.models.alerta
        import app.models.intervencion
        
        SQLModel.metadata.create_all(engine)
