#!/usr/bin/env python3
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_HEALTHCHECK_PATH = "/opt/planilla_mkt/healthcheck.json"
DEFAULT_SERVICE_NAME = "planilla-mkt.service"
DEFAULT_MAX_HEALTHCHECK_AGE_SECONDS = "240"
DEFAULT_ALLOWED_STATUSES = "running"


def get_env(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if value is None or str(value).strip() == "":
        raise RuntimeError(f"Missing required environment variable: {name}")
    return str(value).strip()


def parse_iso8601(value: str) -> datetime:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def load_healthcheck(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Healthcheck file not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def health_is_stale(payload: dict, max_age_seconds: int) -> tuple[bool, str]:
    updated_at = payload.get("updated_at")
    if not updated_at:
        return True, "healthcheck missing updated_at"

    age_seconds = (datetime.now(timezone.utc) - parse_iso8601(updated_at)).total_seconds()
    if age_seconds > max_age_seconds:
        return True, f"healthcheck stale: {int(age_seconds)}s > {max_age_seconds}s"

    return False, f"healthcheck fresh: {int(age_seconds)}s"


def status_is_invalid(payload: dict, allowed_statuses: set[str]) -> tuple[bool, str]:
    status = str(payload.get("status", "")).strip().lower()
    if status not in allowed_statuses:
        return True, f"unexpected status: {status or 'empty'}"
    return False, f"status ok: {status}"


def restart_service(service_name: str, reason: str) -> int:
    print(f"[watchdog] restarting {service_name}: {reason}")
    result = subprocess.run(
        ["/usr/bin/systemctl", "restart", service_name],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.stdout.strip():
        print(result.stdout.strip())
    if result.stderr.strip():
        print(result.stderr.strip(), file=sys.stderr)
    return result.returncode


def main() -> int:
    healthcheck_path = Path(get_env("HEALTHCHECK_PATH", DEFAULT_HEALTHCHECK_PATH))
    service_name = get_env("PLANILLA_SERVICE_NAME", DEFAULT_SERVICE_NAME)
    max_age_seconds = int(
        get_env(
            "WATCHDOG_MAX_HEALTHCHECK_AGE_SECONDS",
            DEFAULT_MAX_HEALTHCHECK_AGE_SECONDS,
        )
    )
    allowed_statuses = {
        item.strip().lower()
        for item in get_env("WATCHDOG_ALLOWED_STATUSES", DEFAULT_ALLOWED_STATUSES).split(",")
        if item.strip()
    }

    try:
        payload = load_healthcheck(healthcheck_path)
        stale, stale_reason = health_is_stale(payload, max_age_seconds)
        invalid, invalid_reason = status_is_invalid(payload, allowed_statuses)

        if stale:
            return restart_service(service_name, stale_reason)
        if invalid:
            return restart_service(service_name, invalid_reason)

        print(f"[watchdog] ok: {stale_reason}; {invalid_reason}")
        return 0
    except Exception as exc:
        return restart_service(service_name, f"watchdog error: {exc}")


if __name__ == "__main__":
    sys.exit(main())
