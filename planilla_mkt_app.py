import inspect
import json
import logging
import os
import re
import signal
import threading
from dataclasses import dataclass
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

if not hasattr(inspect, "getargspec"):
    inspect.getargspec = inspect.getfullargspec

import gspread
import pandas as pd
import pyRofex
from gspread_dataframe import set_with_dataframe


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
    pyrofex_user: str
    pyrofex_password: str
    pyrofex_account: str
    pyrofex_api_url: str
    pyrofex_ws_url: str
    update_interval_seconds: int
    reconnect_delay_seconds: int
    max_reconnect_delay_seconds: int
    stale_market_data_seconds: int
    healthcheck_path: Path
    debug_print_raw: bool

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
            pyrofex_user=get_env("PYROFEX_USER", required=True),
            pyrofex_password=get_env("PYROFEX_PASSWORD", required=True),
            pyrofex_account=get_env("PYROFEX_ACCOUNT", ""),
            pyrofex_api_url=get_env("PYROFEX_API_URL", required=True),
            pyrofex_ws_url=get_env("PYROFEX_WS_URL", required=True),
            update_interval_seconds=int(get_env("UPDATE_INTERVAL_SECONDS", "10")),
            reconnect_delay_seconds=int(get_env("RECONNECT_DELAY_SECONDS", "15")),
            max_reconnect_delay_seconds=int(get_env("MAX_RECONNECT_DELAY_SECONDS", "300")),
            stale_market_data_seconds=int(get_env("STALE_MARKET_DATA_SECONDS", "180")),
            healthcheck_path=Path(
                get_env("HEALTHCHECK_PATH", str(DEFAULT_HEALTHCHECK_PATH))
            ).expanduser(),
            debug_print_raw=get_env("DEBUG_PRINT_RAW", "false").lower() == "true",
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


def column_values_without_header(worksheet, col_index: int, header: str) -> list[str]:
    values = worksheet.col_values(col_index)
    return [value for value in values if value and value != header]


def price_of(entry):
    if entry is None:
        return None
    if isinstance(entry, dict):
        return entry.get("price")
    if isinstance(entry, list) and len(entry) > 0:
        return entry[0].get("price")
    return None


def size_of(entry):
    if entry is None:
        return None
    if isinstance(entry, dict):
        return entry.get("size")
    if isinstance(entry, list) and len(entry) > 0:
        return entry[0].get("size")
    return None


def sheet_symbol_to_rofex_ticker(sheet_symbol: str) -> str:
    normalized = re.sub(r"\s+", " ", sheet_symbol.strip())
    match = re.match(r"^(.*?)\s*-\s*(spot|ci|24\s*hs|48\s*hs)$", normalized, re.IGNORECASE)

    if match:
        ticker = match.group(1).strip()
        plazo_raw = re.sub(r"\s+", "", match.group(2).lower())
        plazo_rofex = "CI" if plazo_raw in ("spot", "ci") else plazo_raw
    else:
        ticker = normalized
        plazo_rofex = "24hs"

    return f"MERV - XMEV - {ticker} - {plazo_rofex}"


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
        self.everything = pd.DataFrame()
        self.rofex_to_sheet_symbol = {}
        self.instrumentos_rofex = []
        self.valid_symbols = set()
        self.debug_message_count = 0

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

        everything = pd.concat([acciones, bonos, cedears, letras, ons])
        duplicated = everything.index[everything.index.duplicated(keep="first")].tolist()
        if duplicated:
            LOGGER.warning(
                "Se encontraron %s tickers duplicados; se ignoran repeticiones: %s",
                len(duplicated),
                ", ".join(sorted(set(duplicated))),
            )
        self.everything = everything[~everything.index.duplicated(keep="first")]
        self.prev_data = None

    def prepare_instruments(self) -> None:
        self.rofex_to_sheet_symbol = {}
        candidate_tickers = []

        for sheet_symbol in self.everything.index:
            rofex_ticker = sheet_symbol_to_rofex_ticker(sheet_symbol)
            self.rofex_to_sheet_symbol[rofex_ticker] = sheet_symbol
            candidate_tickers.append(rofex_ticker)

        LOGGER.info("%s tickers traducidos a formato pyRofex", len(candidate_tickers))
        if self.config.debug_print_raw:
            for sheet_symbol in list(self.everything.index)[:5]:
                LOGGER.info(
                    "Ticker traducido: %s -> %s",
                    sheet_symbol,
                    sheet_symbol_to_rofex_ticker(sheet_symbol),
                )

        instrument_data = pyRofex.get_all_instruments(environment=pyRofex.Environment.LIVE)
        valid_symbols = set()
        for item in instrument_data.get("instruments", []):
            inst_id = item.get("instrumentId", {})
            symbol = inst_id.get("symbol")
            if symbol:
                valid_symbols.add(symbol)

        self.valid_symbols = valid_symbols
        self.instrumentos_rofex = [
            ticker for ticker in candidate_tickers if ticker in self.valid_symbols
        ]
        invalid_tickers = [
            ticker for ticker in candidate_tickers if ticker not in self.valid_symbols
        ]

        LOGGER.info("%s instrumentos validos detectados en pyRofex", len(self.valid_symbols))
        LOGGER.info("%s tickers validos se van a suscribir", len(self.instrumentos_rofex))
        if invalid_tickers:
            LOGGER.warning(
                "%s tickers no existen en pyRofex y se excluyen: %s",
                len(invalid_tickers),
                ", ".join(
                    f"{ticker} (planilla: {self.rofex_to_sheet_symbol[ticker]})"
                    for ticker in invalid_tickers
                ),
            )

    def update_market_timestamp(self) -> None:
        self.runtime_state.last_market_update_at = utc_now_iso()

    def market_data_handler(self, message):
        if self.config.debug_print_raw and self.debug_message_count < 10:
            self.debug_message_count += 1
            LOGGER.info(
                "Mensaje crudo pyRofex:\n%s",
                json.dumps(message, ensure_ascii=True, indent=2, default=str),
            )

        try:
            instrument = message.get("instrumentId", {})
            rofex_ticker = instrument.get("symbol")
            sheet_symbol = self.rofex_to_sheet_symbol.get(rofex_ticker)

            if sheet_symbol is None or sheet_symbol not in self.everything.index:
                return

            md = message.get("marketData", {})
            row = {
                "bid": price_of(md.get("BI")),
                "bid_size": size_of(md.get("BI")),
                "ask": price_of(md.get("OF")),
                "ask_size": size_of(md.get("OF")),
                "last": price_of(md.get("LA")),
                "open": price_of(md.get("OP")),
                "high": price_of(md.get("HI")),
                "low": price_of(md.get("LO")),
                "previous_close": price_of(md.get("CL")),
                "volume": md.get("NV") if md.get("NV") is not None else md.get("EV"),
                "datetime": pd.Timestamp.now(),
            }

            with self.lock:
                for col, val in row.items():
                    if val is not None:
                        self.everything.at[sheet_symbol, col] = val
            self.update_market_timestamp()
        except Exception as exc:
            LOGGER.exception("Error procesando mensaje de pyRofex: %s", exc)

    def error_handler(self, message):
        error_message = f"pyRofex devolvio error: {message}"
        LOGGER.error(error_message)
        self.runtime_state.last_error = error_message
        self.write_healthcheck()

    def exception_handler(self, exc):
        error_message = f"Excepcion en websocket pyRofex: {exc}"
        LOGGER.error(error_message)
        self.runtime_state.last_error = error_message
        self.write_healthcheck()

    def connect_pyrofex(self) -> None:
        LOGGER.info("Conectando a pyRofex")
        pyRofex._set_environment_parameter(
            "url",
            self.config.pyrofex_api_url,
            pyRofex.Environment.LIVE,
        )
        pyRofex._set_environment_parameter(
            "ws",
            self.config.pyrofex_ws_url,
            pyRofex.Environment.LIVE,
        )
        pyRofex.initialize(
            user=self.config.pyrofex_user,
            password=self.config.pyrofex_password,
            account=self.config.pyrofex_account,
            environment=pyRofex.Environment.LIVE,
        )
        self.prepare_instruments()
        pyRofex.init_websocket_connection(
            market_data_handler=self.market_data_handler,
            error_handler=self.error_handler,
            exception_handler=self.exception_handler,
            environment=pyRofex.Environment.LIVE,
        )
        pyRofex.market_data_subscription(
            tickers=self.instrumentos_rofex,
            entries=[
                pyRofex.MarketDataEntry.BIDS,
                pyRofex.MarketDataEntry.OFFERS,
                pyRofex.MarketDataEntry.LAST,
                pyRofex.MarketDataEntry.OPENING_PRICE,
                pyRofex.MarketDataEntry.CLOSING_PRICE,
                pyRofex.MarketDataEntry.HIGH_PRICE,
                pyRofex.MarketDataEntry.LOW_PRICE,
                pyRofex.MarketDataEntry.NOMINAL_VOLUME,
            ],
            depth=1,
            environment=pyRofex.Environment.LIVE,
        )
        self.runtime_state.last_successful_connect_at = utc_now_iso()
        self.runtime_state.last_error = None
        LOGGER.info("Conexion a pyRofex establecida")

    def disconnect_pyrofex(self) -> None:
        LOGGER.info("Cerrando conexion con pyRofex")
        try:
            pyRofex.close_websocket_connection(environment=pyRofex.Environment.LIVE)
        except Exception:
            LOGGER.exception("Error al cerrar websocket pyRofex")

    def refresh_google_handles(self) -> None:
        self.setup_google()

    def update_google_sheets(self) -> None:
        with self.lock:
            current_data = self.everything.reset_index().fillna("0")

        if current_data.equals(self.prev_data):
            return

        try:
            set_with_dataframe(self.market_ws, current_data)
        except Exception:
            LOGGER.exception("Fallo la escritura a Google Sheets. Reabriendo cliente.")
            self.refresh_google_handles()
            set_with_dataframe(self.market_ws, current_data)

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
                self.connect_pyrofex()
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
                self.disconnect_pyrofex()

        self.set_status("stopped")
        LOGGER.info("Proceso finalizado")


def run() -> None:
    load_env_file()
    configure_logging()
    config = AppConfig.from_env()
    app = PlanillaMarketApp(config)
    app.run()
