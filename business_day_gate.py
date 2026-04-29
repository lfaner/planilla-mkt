import logging
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

try:
    from cgb_utils.feriados import es_feriado
except ImportError as exc:
    logger.error(
        "No se pudo importar cgb_utils. Instala dependencias con 'pip install -r requirements.txt'."
    )
    raise


def main() -> int:
    timezone_name = os.getenv("APP_TIMEZONE", "America/Argentina/Buenos_Aires")
    today = datetime.now(ZoneInfo(timezone_name)).date()

    if today.weekday() >= 5:
        logger.info("No se ejecuta: %s es fin de semana", today.isoformat())
        return 1

    if es_feriado(today):
        logger.info("No se ejecuta: %s es feriado", today.isoformat())
        return 1

    logger.info("Dia habil detectado: %s", today.isoformat())
    return 0


if __name__ == "__main__":
    sys.exit(main())
