from datetime import datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Sao_Paulo")


def agora() -> datetime:
    """Horario local de Sao Paulo, sem fuso (naive), para gravar no banco."""
    return datetime.now(TZ).replace(tzinfo=None, microsecond=0)
