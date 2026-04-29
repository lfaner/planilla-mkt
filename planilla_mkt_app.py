import json
import logging
import os
import signal
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

import gspread
import pandas as pd
from gspread_dataframe import set_with_dataframe
from pyhomebroker import HomeBroker


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_GOOGLE_CREDENTIALS = BASE_DIR / "credenciales_nuevo.json"
DEFAULT_LOG_FILE = BASE_DIR / "planilla-mkt.log"
DEFAULT_HEALTHCHECK_PATH = BASE_DIR / "healthcheck.json"
DEFAULT_ENV_FILE = BASE_DIR / ".env"

INSTRUMENT_COLUMNS = [
    "symbol",
    "bid_size",
    "bid",
    "ask",
    "ask_size",
    "last",
    "change",
    "open",
    "high",
    "low",
    "previous_close",
    "turnover",
    "volume",
    "operations",
    "datetime",
]

CAUCIONES_COLUMNS = [
    "settlement",
    "last",
    "turnover",
    "bid_amount",
    "bid_rate",
    "ask_rate",
    "ask_amount",
]

LOGGER = logging.getLogger("planilla_mkt")


def get_env(name, default=None, required=False):
    value = os.getenv(name, default)
    if required and (value is None or str(value).strip() == ""):
        raise RuntimeError(f"Falta la variable de entorno requerida: {name}")
    return value


def load_env_file(env_file: Path = DEFAULT_ENV_FILE) -> None:
    if not env_file.exists():
        return

    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def configure_logging() -> None:
    level_name = get_env("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    log_file = Path(get_env("LOG_FILE", str(DEFAULT_LOG_FILE))).expanduser()
    log_file.parent.mkdir(parents=True, exist_ok=True)
    log_max_bytes = int(get_env("LOG_MAX_BYTES", str(5 * 1024 * 1024)))
    log_backup_count = int(get_env("LOG_BACKUP_COUNT", "5"))

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.handlers.clear()

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=log_max_bytes,
        backupCount=log_backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)


@dataclass
class AppConfig:
    google_credentials_path: Path
    sheet_name: str
    hb_broker: int
    hb_dni: str
    hb_user: str
    hb_password: str
    update_interval_seconds: int
    reconnect_delay_seconds: int
    max_reconnect_delay_seconds: int
    stale_market_data_seconds: int
    healthcheck_path: Path

    @classmethod
    def from_env(cls) -> "AppConfig":
        configured_credentials = Path(
            get_env("GOOGLE_CREDENTIALS_PATH", str(DEFAULT_GOOGLE_CREDENTIALS))
        ).expanduser()
        credentials_path = configured_credentials
        if not credentials_path.exists() and DEFAULT_GOOGLE_CREDENTIALS.exists():
            LOGGER.warning(
                "No existe GOOGLE_CREDENTIALS_PATH=%s. Se usa fallback local %s.",
                configured_credentials,
                DEFAULT_GOOGLE_CREDENTIALS,
            )
            credentials_path = DEFAULT_GOOGLE_CREDENTIALS

        if not credentials_path.exists():
            raise FileNotFoundError(
                f"No existe el archivo de credenciales de Google: {credentials_path}"
            )

        return cls(
            google_credentials_path=credentials_path,
            sheet_name=get_env("GOOGLE_SHEET_NAME", "Planilla_CGB"),
            hb_broker=int(get_env("HB_BROKER", "284")),
            hb_dni=get_env("HB_DNI", required=True),
            hb_user=get_env("HB_USER", required=True),
            hb_password=get_env("HB_PASSWORD", required=True),
            update_interval_seconds=int(get_env("UPDATE_INTERVAL_SECONDS", "10")),
            reconnect_delay_seconds=int(get_env("RECONNECT_DELAY_SECONDS", "15")),
            max_reconnect_delay_seconds=int(get_env("MAX_RECONNECT_DELAY_SECONDS", "300")),
            stale_market_data_seconds=int(get_env("STALE_MARKET_DATA_SECONDS", "180")),
            healthcheck_path=Path(
                get_env("HEALTHCHECK_PATH", str(DEFAULT_HEALTHCHECK_PATH))
            ).expanduser(),
        )


@dataclass
class RuntimeState:
    status: str = "starting"
    last_error: Optional[str] = None
    last_market_update_at: Optional[str] = None
    last_sheet_update_at: Optional[str] = None
    last_successful_connect_at: Optional[str] = None
    reconnect_count: int = 0
    google_write_count: int = 0


def utc_now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def build_instrument_frame(symbols) -> pd.DataFrame:
    frame = pd.DataFrame({"symbol": list(symbols)}, columns=INSTRUMENT_COLUMNS)
    frame = frame.set_index("symbol")
    frame["datetime"] = pd.to_datetime(frame["datetime"], errors="coerce")
    return frame


def build_cauciones_frame() -> pd.DataFrame:
    fechas = [date.today() + timedelta(days=offset) for offset in range(1, 31)]
    frame = pd.DataFrame({"settlement": fechas}, columns=CAUCIONES_COLUMNS)
    frame["settlement"] = pd.to_datetime(frame["settlement"], errors="coerce")
    return frame.set_index("settlement")


def column_values_without_header(worksheet, col_index: int, header: str) -> list[str]:
    values = worksheet.col_values(col_index)
    return [value for value in values if value and value != header]


class PlanillaMarketApp:
    def __init__(self, config: AppConfig):
        self.config = config
        self.stop_event = threading.Event()
        self.runtime_state = RuntimeState()
        self.lock = threading.Lock()
        self.prev_data = None
        self.gc = None
        self.sheet = None
        self.tickers_ws = None
        self.market_ws = None
        self.cauciones_ws = None
        self.everything = pd.DataFrame()
        self.cauciones = pd.DataFrame()
        self.hb = None

    def install_signal_handlers(self) -> None:
        def _handle_signal(signum, _frame):
            LOGGER.info("Senal recibida: %s. Iniciando shutdown ordenado.", signum)
            self.stop_event.set()

        signal.signal(signal.SIGINT, _handle_signal)
        signal.signal(signal.SIGTERM, _handle_signal)

    def write_healthcheck(self) -> None:
        self.config.healthcheck_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "status": self.runtime_state.status,
            "last_error": self.runtime_state.last_error,
            "last_market_update_at": self.runtime_state.last_market_update_at,
            "last_sheet_update_at": self.runtime_state.last_sheet_update_at,
            "last_successful_connect_at": self.runtime_state.last_successful_connect_at,
            "reconnect_count": self.runtime_state.reconnect_count,
            "google_write_count": self.runtime_state.google_write_count,
            "pid": os.getpid(),
            "updated_at": utc_now_iso(),
        }
        self.config.healthcheck_path.write_text(
            json.dumps(payload, ensure_ascii=True, indent=2),
            encoding="utf-8",
        )

    def set_status(self, status: str, error: Optional[str] = None) -> None:
        self.runtime_state.status = status
        self.runtime_state.last_error = error
        self.write_healthcheck()

    def setup_google(self) -> None:
        LOGGER.info("Inicializando cliente de Google Sheets")
        self.gc = gspread.service_account(filename=str(self.config.google_credentials_path))
        self.sheet = self.gc.open(self.config.sheet_name)
        self.tickers_ws = self.sheet.get_worksheet(1)
        self.market_ws = self.sheet.get_worksheet(2)
        self.cauciones_ws = self.sheet.get_worksheet(3)

    def load_market_definitions(self) -> None:
        LOGGER.info("Cargando tickers desde Google Sheets")
        acciones = build_instrument_frame(
            column_values_without_header(self.tickers_ws, 1, "Acciones")
        )
        bonos = build_instrument_frame(
            column_values_without_header(self.tickers_ws, 3, "Bonos")
        )
        cedears = build_instrument_frame(
            column_values_without_header(self.tickers_ws, 5, "Cedears")
        )
        letras = build_instrument_frame(
            column_values_without_header(self.tickers_ws, 7, "Letras")
        )
        ons = build_instrument_frame(column_values_without_header(self.tickers_ws, 9, "ONs"))

        self.everything = pd.concat([acciones, bonos, cedears, letras, ons])
        self.cauciones = build_cauciones_frame()
        self.prev_data = None

    def update_market_timestamp(self) -> None:
        self.runtime_state.last_market_update_at = utc_now_iso()

    def on_securities(self, _online, quotes):
        with self.lock:
            current = quotes.reset_index()
            current["symbol"] = current["symbol"] + " - " + current["settlement"]
            current = current.drop(["settlement"], axis=1)
            current = current.set_index("symbol")
            current["change"] = current["change"] / 100
            current["datetime"] = pd.to_datetime(current["datetime"], errors="coerce")
            self.everything.update(current)
            self.update_market_timestamp()

    def on_repos(self, _online, quotes):
        with self.lock:
            current = quotes.reset_index()
            current = current.set_index("symbol")
            current = current[["PESOS" in value for value in quotes.index]]
            current = current.reset_index()
            current["settlement"] = pd.to_datetime(current["settlement"], errors="coerce")
            current = current.set_index("settlement")
            current["last"] = current["last"] / 100
            current["bid_rate"] = current["bid_rate"] / 100
            current["ask_rate"] = current["ask_rate"] / 100
            current = current.drop(
                ["open", "high", "low", "volume", "operations", "datetime"], axis=1
            )
            current = current[
                ["last", "turnover", "bid_amount", "bid_rate", "ask_rate", "ask_amount"]
            ]
            self.cauciones.update(current)
            self.update_market_timestamp()

    def on_error(self, _online, error):
        message = f"HomeBroker envio error: {error}"
        LOGGER.error(message)
        self.runtime_state.last_error = message
        self.write_healthcheck()

    def connect_homebroker(self) -> None:
        LOGGER.info("Conectando a HomeBroker")
        self.hb = HomeBroker(
            self.config.hb_broker,
            on_securities=self.on_securities,
            on_repos=self.on_repos,
            on_error=self.on_error,
        )
        self.hb.auth.login(
            dni=self.config.hb_dni,
            user=self.config.hb_user,
            password=self.config.hb_password,
            raise_exception=True,
        )
        self.hb.online.connect()
        self.hb.online.subscribe_securities("bluechips", "24hs")
        self.hb.online.subscribe_securities("bluechips", "SPOT")
        self.hb.online.subscribe_securities("government_bonds", "24hs")
        self.hb.online.subscribe_securities("government_bonds", "SPOT")
        self.hb.online.subscribe_securities("cedears", "24hs")
        self.hb.online.subscribe_securities("cedears", "SPOT")
        self.hb.online.subscribe_securities("general_board", "24hs")
        self.hb.online.subscribe_securities("general_board", "SPOT")
        self.hb.online.subscribe_securities("short_term_government_bonds", "24hs")
        self.hb.online.subscribe_securities("short_term_government_bonds", "SPOT")
        self.hb.online.subscribe_securities("corporate_bonds", "24hs")
        self.hb.online.subscribe_securities("corporate_bonds", "SPOT")
        self.hb.online.subscribe_repos()
        self.runtime_state.last_successful_connect_at = utc_now_iso()
        LOGGER.info("Conexion a HomeBroker establecida")

    def disconnect_homebroker(self) -> None:
        if not self.hb:
            return
        LOGGER.info("Cerrando conexion con HomeBroker")
        online = getattr(self.hb, "online", None)
        if online and hasattr(online, "disconnect"):
            try:
                online.disconnect()
            except Exception:
                LOGGER.exception("Error al desconectar HomeBroker")
        self.hb = None

    def refresh_google_handles(self) -> None:
        self.setup_google()

    def update_google_sheets(self) -> None:
        with self.lock:
            current_data = self.everything.reset_index().fillna("0")
            cauciones_data = self.cauciones.reset_index().fillna("0")

        if current_data.equals(self.prev_data):
            return

        try:
            set_with_dataframe(self.market_ws, current_data)
            set_with_dataframe(
                self.cauciones_ws,
                cauciones_data,
                row=2,
                col=2,
                include_column_header=False,
            )
        except Exception:
            LOGGER.exception("Fallo la escritura a Google Sheets. Reabriendo cliente.")
            self.refresh_google_handles()
            set_with_dataframe(self.market_ws, current_data)
            set_with_dataframe(
                self.cauciones_ws,
                cauciones_data,
                row=2,
                col=2,
                include_column_header=False,
            )

        self.prev_data = current_data
        self.runtime_state.last_sheet_update_at = utc_now_iso()
        self.runtime_state.google_write_count += 1
        LOGGER.info("Google Sheets actualizado")
        self.write_healthcheck()

    def ensure_market_is_fresh(self) -> None:
        last_reference = (
            self.runtime_state.last_market_update_at
            or self.runtime_state.last_successful_connect_at
        )
        if not last_reference:
            return

        last_market_dt = datetime.fromisoformat(last_reference.replace("Z", ""))
        age_seconds = (datetime.utcnow() - last_market_dt).total_seconds()
        if age_seconds > self.config.stale_market_data_seconds:
            raise RuntimeError(
                f"Datos de mercado vencidos hace {int(age_seconds)}s. Forzando reconexion."
            )

    def run_connected_loop(self) -> None:
        self.set_status("running")
        while not self.stop_event.is_set():
            self.update_google_sheets()
            self.ensure_market_is_fresh()
            self.stop_event.wait(self.config.update_interval_seconds)

    def initialize(self) -> None:
        self.setup_google()
        self.load_market_definitions()
        self.write_healthcheck()

    def run(self) -> None:
        self.install_signal_handlers()
        self.initialize()

        retry_delay = self.config.reconnect_delay_seconds
        while not self.stop_event.is_set():
            try:
                self.connect_homebroker()
                retry_delay = self.config.reconnect_delay_seconds
                self.run_connected_loop()
            except Exception as exc:
                self.runtime_state.reconnect_count += 1
                error_message = str(exc)
                LOGGER.exception("Fallo de runtime. Se intentara reconectar: %s", error_message)
                self.set_status("reconnecting", error_message)
                if self.stop_event.wait(retry_delay):
                    break
                retry_delay = min(
                    retry_delay * 2,
                    self.config.max_reconnect_delay_seconds,
                )
            finally:
                self.disconnect_homebroker()

        self.set_status("stopped")
        LOGGER.info("Proceso finalizado")


def run() -> None:
    load_env_file()
    configure_logging()
    config = AppConfig.from_env()
    app = PlanillaMarketApp(config)
    app.run()
