# app/scheduler.py

from apscheduler.schedulers.background import BackgroundScheduler
from app.dependencies.session import get_session
from app.services.mantenimiento_service import inactivar_suplencias_vencidas
import logging

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()

def job_suplencias():
    with next(get_session()) as db:
        n = inactivar_suplencias_vencidas(db)
        logger.info(f"[scheduler] suplencias vencidas inactivadas: {n}")

def start_scheduler():
    scheduler.add_job(job_suplencias, trigger="cron", hour=0, minute=5)  # 00:05 cada día
    scheduler.start()
    logger.info("[scheduler] APScheduler iniciado")