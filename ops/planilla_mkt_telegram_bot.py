#!/usr/bin/env python3
import json
import logging
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, time as datetime_time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


DEFAULT_BOT_TIMEOUT_SECONDS = "30"
DEFAULT_HEALTHCHECK_PATH = "/opt/planilla_mkt/healthcheck.json"
DEFAULT_SERVICE_NAME = "planilla-mkt.service"
DEFAULT_WATCHDOG_TIMER_NAME = "planilla-mkt-watchdog.timer"
DEFAULT_OPERATING_START = "10:30"
DEFAULT_OPERATING_END = "17:00"
TELEGRAM_API_BASE = "https://api.telegram.org"

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


def get_env(name: str, default: str | None = None, required: bool = False) -> str:
    value = os.getenv(name, default)
    if required and (value is None or str(value).strip() == ""):
        raise RuntimeError(f"Missing required environment variable: {name}")
    if value is None:
        return ""
    return str(value).strip()


def api_request(token: str, method: str, params: dict | None = None) -> dict:
    encoded = urllib.parse.urlencode(params or {})
    url = f"{TELEGRAM_API_BASE}/bot{token}/{method}"
    if encoded:
        url = f"{url}?{encoded}"
    with urllib.request.urlopen(url, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def send_message(token: str, chat_id: int, text: str) -> None:
    logger.info("sending telegram message to chat_id=%s text=%r", chat_id, text[:200])
    api_request(
        token,
        "sendMessage",
        {
            "chat_id": str(chat_id),
            "text": text,
        },
    )


def run_systemctl(*args: str) -> tuple[int, str]:
    logger.info("running systemctl %s", " ".join(args))
    result = subprocess.run(
        ["/usr/bin/systemctl", *args],
        check=False,
        capture_output=True,
        text=True,
    )
    output = "\n".join(part for part in [result.stdout.strip(), result.stderr.strip()] if part)
    logger.info("systemctl %s -> code=%s output=%r", " ".join(args), result.returncode, output[:500])
    return result.returncode, output


def parse_hhmm(value: str) -> datetime_time:
    hour, minute = value.split(":", 1)
    return datetime_time(hour=int(hour), minute=int(minute))


def is_business_day(now: datetime) -> tuple[bool, str]:
    if now.weekday() >= 5:
        return False, f"{now.date().isoformat()} es fin de semana"

    try:
        from cgb_utils.feriados import es_feriado
    except ImportError as exc:
        return False, f"no se pudo evaluar feriados: {exc}"

    if es_feriado(now.date()):
        return False, f"{now.date().isoformat()} es feriado"

    return True, f"{now.date().isoformat()} es dia habil"


def is_operating_time(now: datetime) -> tuple[bool, str]:
    start = parse_hhmm(get_env("WATCHDOG_OPERATING_START", DEFAULT_OPERATING_START))
    end = parse_hhmm(get_env("WATCHDOG_OPERATING_END", DEFAULT_OPERATING_END))
    current = now.time().replace(second=0, microsecond=0)

    if start <= current < end:
        return True, f"dentro de horario operativo {start.strftime('%H:%M')}-{end.strftime('%H:%M')}"
    return False, f"fuera de horario operativo {start.strftime('%H:%M')}-{end.strftime('%H:%M')}"


def can_start() -> tuple[bool, str]:
    timezone_name = get_env("APP_TIMEZONE", "America/Argentina/Buenos_Aires")
    now = datetime.now(ZoneInfo(timezone_name))
    business_day, business_reason = is_business_day(now)
    operating_time, operating_reason = is_operating_time(now)

    if not business_day or not operating_time:
        return False, f"{business_reason}; {operating_reason}"

    return True, f"{business_reason}; {operating_reason}"


def summarize_timer(unit_name: str) -> str:
    code, output = run_systemctl(
        "show",
        unit_name,
        "--property=ActiveState",
        "--property=NextElapseUSecRealtime",
        "--property=LastTriggerUSec",
    )
    if code != 0:
        return f"{unit_name}: error: {output or code}"

    values = {}
    for line in output.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key] = value or "n/a"

    return (
        f"{unit_name}: {values.get('ActiveState', 'n/a')}\n"
        f"next: {values.get('NextElapseUSecRealtime', 'n/a')}\n"
        f"last: {values.get('LastTriggerUSec', 'n/a')}"
    )


def read_healthcheck(path: Path) -> dict:
    if not path.exists():
        return {"status": "missing", "detail": f"Healthcheck not found: {path}"}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"status": "invalid", "detail": f"Healthcheck read error: {exc}"}


def summarize_health(payload: dict) -> str:
    lines = [
        f"status: {payload.get('status', 'unknown')}",
        f"updated_at: {payload.get('updated_at', 'n/a')}",
        f"last_error: {payload.get('last_error', 'n/a')}",
        f"last_market_update_at: {payload.get('last_market_update_at', 'n/a')}",
        f"last_sheet_update_at: {payload.get('last_sheet_update_at', 'n/a')}",
        f"reconnect_count: {payload.get('reconnect_count', 'n/a')}",
        f"google_write_count: {payload.get('google_write_count', 'n/a')}",
    ]
    return "\n".join(lines)


def summarize_status(service_name: str, watchdog_timer_name: str) -> str:
    code_active, active = run_systemctl("is-active", service_name)
    code_enabled, enabled = run_systemctl("is-enabled", service_name)
    _code_watchdog, watchdog = run_systemctl("is-active", watchdog_timer_name)
    _can_control, schedule_reason = can_start_or_restart()
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    return "\n".join(
        [
            f"service: {service_name}",
            f"utc_now: {now}",
            f"is_active: {active or code_active}",
            f"is_enabled: {enabled or code_enabled}",
            f"watchdog_timer: {watchdog or 'unknown'}",
            f"schedule: {schedule_reason}",
            "",
            summarize_timer("planilla-mkt-start.timer"),
            "",
            summarize_timer("planilla-mkt-stop.timer"),
        ]
    )


def normalize_command(text: str) -> str:
    command = (text or "").strip().split()[0].lower() if text else ""
    if "@" in command:
        command = command.split("@", 1)[0]
    return command


def control_service(action: str, service_name: str, enforce_schedule: bool = True) -> str:
    watchdog_timer_name = get_env("WATCHDOG_TIMER_NAME", DEFAULT_WATCHDOG_TIMER_NAME)

    if action == "start" and enforce_schedule:
        allowed, reason = can_start()
        if not allowed:
            return f"{action} bloqueado\n{reason}"

    if action == "stop":
        watchdog_code, watchdog_output = run_systemctl("stop", watchdog_timer_name)
        if watchdog_code != 0:
            return f"{action} failed\nno se pudo detener {watchdog_timer_name}: {watchdog_output or watchdog_code}"

    code, output = run_systemctl(action, service_name)
    if code == 0 and action == "start":
        watchdog_code, watchdog_output = run_systemctl("start", watchdog_timer_name)
        if watchdog_code != 0:
            return f"{action} partial\n{service_name} ok pero no se pudo iniciar {watchdog_timer_name}: {watchdog_output or watchdog_code}"

    if code == 0:
        return f"{action} ok\n{summarize_status(service_name, watchdog_timer_name)}"
    return f"{action} failed\n{output or 'no output'}"


def handle_command(token: str, chat_id: int, text: str, service_name: str, healthcheck_path: Path) -> None:
    command = normalize_command(text)
    logger.info("received telegram command chat_id=%s raw=%r normalized=%r", chat_id, text, command)

    if command == "/start":
        send_message(token, chat_id, control_service("start", service_name))
        return

    if command == "/status":
        send_message(
            token,
            chat_id,
            summarize_status(
                service_name,
                get_env("WATCHDOG_TIMER_NAME", DEFAULT_WATCHDOG_TIMER_NAME),
            ),
        )
        return

    if command == "/health":
        payload = read_healthcheck(healthcheck_path)
        send_message(token, chat_id, summarize_health(payload))
        return

    if command == "/stop":
        send_message(token, chat_id, control_service("stop", service_name, enforce_schedule=False))
        return

    send_message(
        token,
        chat_id,
        "Comando no reconocido. Usa /start, /status, /health o /stop",
    )


def main() -> int:
    token = get_env("TELEGRAM_BOT_TOKEN", required=True)
    allowed_chat_ids = {
        int(item.strip())
        for item in get_env("TELEGRAM_ALLOWED_CHAT_IDS", required=True).split(",")
        if item.strip()
    }
    timeout_seconds = int(get_env("TELEGRAM_BOT_TIMEOUT_SECONDS", DEFAULT_BOT_TIMEOUT_SECONDS))
    service_name = get_env("PLANILLA_SERVICE_NAME", DEFAULT_SERVICE_NAME)
    healthcheck_path = Path(get_env("HEALTHCHECK_PATH", DEFAULT_HEALTHCHECK_PATH))

    offset = None
    while True:
        params = {"timeout": str(timeout_seconds)}
        if offset is not None:
            params["offset"] = str(offset)

        response = api_request(token, "getUpdates", params)
        for item in response.get("result", []):
            offset = int(item["update_id"]) + 1
            message = item.get("message") or {}
            chat = message.get("chat") or {}
            chat_id = chat.get("id")
            text = message.get("text", "")

            logger.info("received telegram update_id=%s chat_id=%s text=%r", item.get("update_id"), chat_id, text)

            if chat_id not in allowed_chat_ids:
                if chat_id is not None:
                    logger.warning("unauthorized chat_id=%s", chat_id)
                    send_message(token, int(chat_id), "No autorizado.")
                continue

            try:
                handle_command(token, int(chat_id), text, service_name, healthcheck_path)
            except Exception as exc:
                logger.exception("error handling command chat_id=%s text=%r", chat_id, text)
                send_message(token, int(chat_id), f"error: {exc}")

        time.sleep(1)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
