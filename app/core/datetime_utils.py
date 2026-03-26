from datetime import datetime
from zoneinfo import ZoneInfo

ARG_TZ = ZoneInfo("America/Argentina/Buenos_Aires")

def now_arg() -> datetime:
    return datetime.now(ARG_TZ)