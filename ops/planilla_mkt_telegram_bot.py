#!/usr/bin/env python3
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_BOT_TIMEOUT_SECONDS = "30"
DEFAULT_HEALTHCHECK_PATH = "/opt/planilla_mkt/healthcheck.json"
DEFAULT_SERVICE_NAME = "planilla-mkt.service"
TELEGRAM_API_BASE = "https://api.telegram.org"


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
    api_request(
        token,
        "sendMessage",
        {
            "chat_id": str(chat_id),
            "text": text,
        },
    )


def run_systemctl(*args: str) -> tuple[int, str]:
    result = subprocess.run(
        ["/usr/bin/systemctl", *args],
        check=False,
        capture_output=True,
        text=True,
    )
    output = "\n".join(part for part in [result.stdout.strip(), result.stderr.strip()] if part)
    return result.returncode, output


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


def summarize_status(service_name: str) -> str:
    code_active, active = run_systemctl("is-active", service_name)
    code_enabled, enabled = run_systemctl("is-enabled", service_name)
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    return "\n".join(
        [
            f"service: {service_name}",
            f"utc_now: {now}",
            f"is_active: {active or code_active}",
            f"is_enabled: {enabled or code_enabled}",
        ]
    )


def normalize_command(text: str) -> str:
    command = (text or "").strip().split()[0].lower() if text else ""
    if "@" in command:
        command = command.split("@", 1)[0]
    return command


def handle_command(token: str, chat_id: int, text: str, service_name: str, healthcheck_path: Path) -> None:
    command = normalize_command(text)

    if command == "/start":
        send_message(
            token,
            chat_id,
            "Comandos disponibles:\n/status\n/health\n/restart",
        )
        return

    if command == "/status":
        send_message(token, chat_id, summarize_status(service_name))
        return

    if command == "/health":
        payload = read_healthcheck(healthcheck_path)
        send_message(token, chat_id, summarize_health(payload))
        return

    if command == "/restart":
        code, output = run_systemctl("restart", service_name)
        if code == 0:
            send_message(token, chat_id, f"restart ok\n{summarize_status(service_name)}")
        else:
            send_message(token, chat_id, f"restart failed\n{output or 'no output'}")
        return

    send_message(token, chat_id, "Comando no reconocido. Usá /status, /health o /restart")


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

            if chat_id not in allowed_chat_ids:
                if chat_id is not None:
                    send_message(token, int(chat_id), "No autorizado.")
                continue

            try:
                handle_command(token, int(chat_id), text, service_name, healthcheck_path)
            except Exception as exc:
                send_message(token, int(chat_id), f"error: {exc}")

        time.sleep(1)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
