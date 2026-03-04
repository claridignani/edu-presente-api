from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware

from app.db.database import create_db_and_tables
from app.dependencies.auth import get_current_user

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
from app.routers.ia import router as ia_router
from app.routers.inscriptos_admin import router as inscriptos_admin_router
from app.routers.alertas import router as alertas_router
from app.routers.preinscripcion import router as preinscripcion_router

from app.routers.escuela_public import router as escuela_public_router
from app.routers.invitacion_public import router as invitacion_public_router
from app.routers.usuario_public import router as usuario_public_router
from app.routers import requisitos


from dotenv import load_dotenv
load_dotenv()
import logging

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

app = FastAPI()

origins = [
    "http://localhost:4200",
    "http://127.0.0.1:4200",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def on_startup():
    create_db_and_tables()

# ✅ PUBLICO (sin JWT)
app.include_router(auth.router)
app.include_router(escuela_public_router)
app.include_router(invitacion_public_router)
app.include_router(usuario_public_router)
app.include_router(preinscripcion_router)

# ✅ PRIVADO (con JWT)
auth_dep = [Depends(get_current_user)]

app.include_router(usuario.router, dependencies=auth_dep)
app.include_router(escuela.router, dependencies=auth_dep)
app.include_router(curso.router, dependencies=auth_dep)
app.include_router(rol.router, dependencies=auth_dep)
app.include_router(alumno.router, dependencies=auth_dep)
app.include_router(asistencia.router, dependencies=auth_dep)
app.include_router(inscriptos.router, dependencies=auth_dep)
app.include_router(responsable.router, dependencies=auth_dep)
app.include_router(parentesco.router, dependencies=auth_dep)
app.include_router(invitacion_docente.router, dependencies=auth_dep)
app.include_router(inscriptos_admin_router, dependencies=auth_dep)
app.include_router(alertas_router, dependencies=auth_dep)
app.include_router(ia_router, dependencies=auth_dep)
app.include_router(requisitos.router, dependencies=auth_dep)