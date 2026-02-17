from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.db.database import create_db_and_tables
from app.routers import usuario
from app.routers import escuela
from app.routers import curso
from app.routers import auth
from app.routers import rol
from app.routers import alumno
from app.routers import asistencia
from app.routers import inscriptos
from app.routers import responsable
from app.routers import parentesco
from app.routers import invitacion_docente
from app.routers.inscriptos_admin import router as inscriptos_admin_router
from app.routers.alertas import router as alertas_router
app = FastAPI()

origins = [
        "http://localhost:4200"
]

app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"],)

@app.on_event("startup")
def on_startup():
    create_db_and_tables()


app.include_router(usuario.router)
app.include_router(escuela.router)
app.include_router(curso.router)
app.include_router(auth.router)
app.include_router(rol.router)
app.include_router(alumno.router)
app.include_router(asistencia.router)
app.include_router(inscriptos.router)
app.include_router(responsable.router)
app.include_router(parentesco.router)
app.include_router(invitacion_docente.router)
app.include_router(inscriptos_admin_router)
app.include_router(alertas_router)


