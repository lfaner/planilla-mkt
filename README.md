# Planilla MKT

Este proyecto actualiza una Google Sheet con cotizaciones de mercado obtenidas desde `pyhomebroker`.

El objetivo operativo es dejarlo listo para correr en un VPS en forma automática, a una hora determinada, con configuración externa al código y sin secretos hardcodeados.

## Estado actual del script

El archivo principal es [prueba-produc.py](<c:/Users/Usuario/OneDrive - Capital Gain Bursatil/Proyectos/Planilla_mkt/prueba-produc.py>).
La lógica principal quedó separada en [planilla_mkt_app.py](<c:/Users/Usuario/OneDrive - Capital Gain Bursatil/Proyectos/Planilla_mkt/planilla_mkt_app.py>).

Flujo real:

1. Lee configuración desde variables de entorno.
2. Configura logging con rotación.
3. Abre la planilla de Google Sheets.
4. Toma tickers desde la hoja 2.
5. Construye `DataFrame`s base para instrumentos y cauciones.
6. Se autentica en HomeBroker.
7. Se suscribe a cotizaciones online.
8. Actualiza Google Sheets solo cuando cambian los datos.
9. Si la conexión o los datos quedan stale, intenta reconectar automáticamente.
10. Escribe un `healthcheck.json` con estado y métricas básicas.

## Cómo resolvimos la ruta del JSON

La ruta ya no está hardcodeada.

El script usa esta lógica:

1. Si existe `GOOGLE_CREDENTIALS_PATH`, usa esa ruta.
2. Si no existe, intenta usar `credenciales_nuevo.json` en el mismo directorio del script.
3. Si el archivo no existe, falla al iniciar con un error explícito.

Esto permite mover el proyecto al VPS sin editar el código.

## Variables de entorno

Archivo de ejemplo: [.env.example](<c:/Users/Usuario/OneDrive - Capital Gain Bursatil/Proyectos/Planilla_mkt/.env.example>)

Variables soportadas:

- `GOOGLE_CREDENTIALS_PATH`: ruta al JSON de la service account de Google.
- `GOOGLE_SHEET_NAME`: nombre de la planilla a abrir.
- `HB_BROKER`: broker de HomeBroker.
- `HB_DNI`: DNI del usuario.
- `HB_USER`: usuario de HomeBroker.
- `HB_PASSWORD`: contraseña de HomeBroker.
- `LOG_LEVEL`: nivel de logging.
- `APP_TIMEZONE`: zona horaria para validar día hábil.
- `LOG_FILE`: archivo principal de logs rotativos.
- `LOG_MAX_BYTES`: tamaño máximo por archivo de log.
- `LOG_BACKUP_COUNT`: cantidad de archivos rotados.
- `HEALTHCHECK_PATH`: archivo JSON con estado del proceso.
- `UPDATE_INTERVAL_SECONDS`: frecuencia del loop de escritura.
- `RECONNECT_DELAY_SECONDS`: espera inicial antes de reconectar.
- `MAX_RECONNECT_DELAY_SECONDS`: tope para backoff de reconexión.
- `STALE_MARKET_DATA_SECONDS`: segundos máximos sin datos antes de forzar reconexión.
- `PLANILLA_SERVICE_NAME`: nombre del servicio `systemd` que controla watchdog/bot.
- `WATCHDOG_MAX_HEALTHCHECK_AGE_SECONDS`: antigüedad máxima aceptada del healthcheck.
- `WATCHDOG_ALLOWED_STATUSES`: estados del healthcheck que el watchdog considera sanos.
- `WATCHDOG_OPERATING_START`: inicio de la ventana operativa para watchdog/bot.
- `WATCHDOG_OPERATING_END`: fin de la ventana operativa para watchdog/bot.
- `TELEGRAM_BOT_TOKEN`: token del bot de Telegram.
- `TELEGRAM_ALLOWED_CHAT_IDS`: chats privados o grupos autorizados, separados por coma.
- `TELEGRAM_BOT_TIMEOUT_SECONDS`: timeout del long polling de Telegram.

Ejemplo:

```env
GOOGLE_CREDENTIALS_PATH=/opt/planilla_mkt/credenciales_nuevo.json
GOOGLE_SHEET_NAME=Planilla_CGB
HB_BROKER=284
HB_DNI=tu_dni
HB_USER=tu_usuario
HB_PASSWORD=tu_password
LOG_LEVEL=INFO
APP_TIMEZONE=America/Argentina/Buenos_Aires
LOG_FILE=/opt/planilla_mkt/planilla-mkt.log
LOG_MAX_BYTES=5242880
LOG_BACKUP_COUNT=5
HEALTHCHECK_PATH=/opt/planilla_mkt/healthcheck.json
UPDATE_INTERVAL_SECONDS=10
RECONNECT_DELAY_SECONDS=15
MAX_RECONNECT_DELAY_SECONDS=300
STALE_MARKET_DATA_SECONDS=180
PLANILLA_SERVICE_NAME=planilla-mkt.service
WATCHDOG_MAX_HEALTHCHECK_AGE_SECONDS=240
WATCHDOG_ALLOWED_STATUSES=starting,running,reconnecting
WATCHDOG_OPERATING_START=10:30
WATCHDOG_OPERATING_END=17:00
TELEGRAM_BOT_TOKEN=tu_token
TELEGRAM_ALLOWED_CHAT_IDS=123456789,-1001234567890
TELEGRAM_BOT_TIMEOUT_SECONDS=30
```

## Dependencias

Archivo: [requirements.txt](<c:/Users/Usuario/OneDrive - Capital Gain Bursatil/Proyectos/Planilla_mkt/requirements.txt>)

Instalación:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

## Estructura recomendada en el VPS

```text
/opt/planilla_mkt/
├── .env
├── business_day_gate.py
├── healthcheck.json
├── ops
│   ├── planilla_mkt_telegram_bot.py
│   └── planilla_mkt_watchdog.py
├── planilla-mkt-start.service
├── planilla-mkt-start.timer
├── planilla-mkt-stop.service
├── planilla-mkt-stop.timer
├── planilla-mkt.log
├── planilla_mkt_app.py
├── prueba-produc.py
├── requirements.txt
└── credenciales_nuevo.json
```

## Puesta en marcha manual

### 1. Copiar archivos al VPS

Copiar al menos:

- `prueba-produc.py`
- `requirements.txt`
- `credenciales_nuevo.json`
- `.env`
- `business_day_gate.py`
- `planilla_mkt_app.py`
- `planilla-mkt.service`
- `planilla-mkt-start.service`
- `planilla-mkt-stop.service`
- `planilla-mkt-start.timer`
- `planilla-mkt-stop.timer`
- `ops/planilla_mkt_watchdog.py`
- `ops/planilla_mkt_telegram_bot.py`

### 2. Crear el entorno e instalar dependencias

```bash
mkdir -p /opt/planilla_mkt
cd /opt/planilla_mkt
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 3. Probar ejecución

```bash
cd /opt/planilla_mkt
source .venv/bin/activate
python prueba-produc.py
```

El script carga automáticamente `.env` si existe en el mismo directorio.

Si está bien configurado:

1. Se autentica en HomeBroker.
2. Abre la planilla.
3. Empieza a actualizar Google Sheets.
4. Queda corriendo hasta que lo detengas.

## Mejoras de resiliencia

El runtime ahora incorpora:

1. Reintentos y reconexión automática a HomeBroker con backoff.
2. Manejo de `SIGINT` y `SIGTERM` para apagado ordenado.
3. Logging rotativo con `RotatingFileHandler`.
4. Health check basado en archivo JSON.
5. Métricas básicas:
   - `status`
   - `last_market_update_at`
   - `last_sheet_update_at`
   - `last_successful_connect_at`
   - `reconnect_count`
   - `google_write_count`

Podés inspeccionar el health check así:

```bash
cat /opt/planilla_mkt/healthcheck.json
```

## Automatización recomendada

Como el proceso no termina solo, para producción conviene usar `systemd` y no lanzar el script directo desde `cron`.

### Servicio `systemd`

Archivo listo en el repo: [planilla-mkt.service](<c:/Users/Usuario/OneDrive - Capital Gain Bursatil/Proyectos/Planilla_mkt/planilla-mkt.service>)

Copiarlo al VPS:

```bash
sudo cp /opt/planilla_mkt/planilla-mkt.service /etc/systemd/system/planilla-mkt.service
```

Contenido:

```ini
[Unit]
Description=Planilla MKT
After=network.target
Wants=network.target

[Service]
Type=simple
User=planilla
WorkingDirectory=/opt/planilla_mkt
EnvironmentFile=/opt/planilla_mkt/.env
Environment=PYTHONUNBUFFERED=1
ExecCondition=/opt/planilla_mkt/.venv/bin/python /opt/planilla_mkt/business_day_gate.py
ExecStart=/opt/planilla_mkt/.venv/bin/python /opt/planilla_mkt/prueba-produc.py
Restart=always
RestartSec=15
KillSignal=SIGTERM
TimeoutStopSec=30
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

Notas:

- Ajustá `User=planilla` al usuario real del VPS.
- `ExecCondition` evita que el servicio arranque en fines de semana o feriados incluso si alguien ejecuta `systemctl start planilla-mkt`.
- Los logs persistentes del proceso quedan en `LOG_FILE` y la salida estándar queda en `journalctl`.

### Comandos de control

```bash
sudo systemctl daemon-reload
sudo systemctl start planilla-mkt
sudo systemctl status planilla-mkt
sudo journalctl -u planilla-mkt -f
```

## Scheduling con `systemd timer`

Se agregaron estos archivos:

- [business_day_gate.py](<c:/Users/Usuario/OneDrive - Capital Gain Bursatil/Proyectos/Planilla_mkt/business_day_gate.py>)
- [planilla-mkt-start.service](<c:/Users/Usuario/OneDrive - Capital Gain Bursatil/Proyectos/Planilla_mkt/planilla-mkt-start.service>)
- [planilla-mkt-stop.service](<c:/Users/Usuario/OneDrive - Capital Gain Bursatil/Proyectos/Planilla_mkt/planilla-mkt-stop.service>)
- [planilla-mkt-start.timer](<c:/Users/Usuario/OneDrive - Capital Gain Bursatil/Proyectos/Planilla_mkt/planilla-mkt-start.timer>)
- [planilla-mkt-stop.timer](<c:/Users/Usuario/OneDrive - Capital Gain Bursatil/Proyectos/Planilla_mkt/planilla-mkt-stop.timer>)

Comportamiento:

1. El timer de arranque dispara a las 10:30 de `America/Argentina/Buenos_Aires`.
2. Antes de arrancar, `business_day_gate.py` verifica:
   - que no sea sábado o domingo
   - que `cgb_utils.feriados.es_feriado(fecha)` devuelva `False`
3. Si no es día hábil, el arranque se omite.
4. El timer de detención dispara a las 17:00 de `America/Argentina/Buenos_Aires`.
5. La misma validación de día hábil se aplica al stop.

Instalación de units y timers en el VPS:

```bash
sudo timedatectl set-timezone America/Argentina/Buenos_Aires
sudo cp /opt/planilla_mkt/planilla-mkt.service /etc/systemd/system/
sudo cp /opt/planilla_mkt/planilla-mkt-start.service /etc/systemd/system/
sudo cp /opt/planilla_mkt/planilla-mkt-stop.service /etc/systemd/system/
sudo cp /opt/planilla_mkt/planilla-mkt-start.timer /etc/systemd/system/
sudo cp /opt/planilla_mkt/planilla-mkt-stop.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now planilla-mkt-start.timer
sudo systemctl enable --now planilla-mkt-stop.timer
```

La hora del timer depende de la timezone del VPS. Por eso el servidor debe quedar configurado en `America/Argentina/Buenos_Aires`.

Verificación:

```bash
sudo systemctl list-timers | grep planilla-mkt
sudo systemctl status planilla-mkt-start.timer
sudo systemctl status planilla-mkt-stop.timer
```

## Watchdog operativo

El watchdog vive en `ops/planilla_mkt_watchdog.py` y se ejecuta con `planilla-mkt-watchdog.timer`.

Su función es revisar `healthcheck.json` y reiniciar `planilla-mkt.service` si:

1. El healthcheck está vencido.
2. El estado del proceso no está en `WATCHDOG_ALLOWED_STATUSES`.
3. La revisión ocurre en día hábil y dentro de la ventana `WATCHDOG_OPERATING_START` a `WATCHDOG_OPERATING_END`.

Fuera de la ventana operativa, o en fines de semana/feriados, el watchdog termina OK y no levanta HomeBroker. Esto evita reconexiones fuera de mercado.

Configuración recomendada:

```env
WATCHDOG_MAX_HEALTHCHECK_AGE_SECONDS=240
WATCHDOG_ALLOWED_STATUSES=starting,running,reconnecting
WATCHDOG_OPERATING_START=10:30
WATCHDOG_OPERATING_END=17:00
```

Unidad instalada:

```ini
[Unit]
Description=Planilla MKT watchdog
After=network.target
Wants=network.target

[Service]
Type=oneshot
EnvironmentFile=/opt/planilla_mkt/.env
ExecStart=/opt/planilla_mkt/.venv/bin/python /opt/planilla_mkt/ops/planilla_mkt_watchdog.py
```

Timer recomendado:

```ini
[Unit]
Description=Periodic watchdog for Planilla MKT

[Timer]
OnBootSec=2min
OnUnitActiveSec=1min
Unit=planilla-mkt-watchdog.service

[Install]
WantedBy=timers.target
```

Instalación:

```bash
# Crear /etc/systemd/system/planilla-mkt-watchdog.service con el contenido anterior.
# Crear /etc/systemd/system/planilla-mkt-watchdog.timer con el contenido anterior.
sudo systemctl daemon-reload
sudo systemctl enable --now planilla-mkt-watchdog.timer
```

## Bot de Telegram

El bot vive en `ops/planilla_mkt_telegram_bot.py` y permite controlar `planilla-mkt.service` desde chats autorizados.

Comandos disponibles:

- `/status`: muestra estado del servicio, watchdog, ventana operativa y próximos timers.
- `/health`: muestra el contenido resumido de `healthcheck.json`.
- `/start_service`: intenta iniciar `planilla-mkt.service`.
- `/stop`: detiene `planilla-mkt.service`.
- `/restart`: intenta reiniciar `planilla-mkt.service`.

`/start_service` y `/restart` respetan la misma ventana operativa que el watchdog. Fuera de día hábil u horario de mercado, el bot bloquea la acción. `/stop` queda permitido en cualquier momento.

Para habilitar chats privados o grupos:

```env
TELEGRAM_BOT_TOKEN=tu_token
TELEGRAM_ALLOWED_CHAT_IDS=123456789,-1001234567890
TELEGRAM_BOT_TIMEOUT_SECONDS=30
```

En grupos, Telegram puede enviar comandos con mención al bot, por ejemplo `/status@NombreDelBot`; el bot normaliza ese formato.

Unidad instalada:

```ini
[Unit]
Description=Planilla MKT Telegram control bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/opt/planilla_mkt
EnvironmentFile=/opt/planilla_mkt/.env
ExecStart=/opt/planilla_mkt/.venv/bin/python /opt/planilla_mkt/ops/planilla_mkt_telegram_bot.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

Dependencia importante:

`business_day_gate.py` usa `cgb_utils.feriados`. Por eso `requirements.txt` ahora incluye:

```text
cgb-utils @ git+https://github.com/lfaner/cgb-utils.git
```

Instalá dependencias nuevamente en el VPS si ya habías creado el entorno:

```bash
source /opt/planilla_mkt/.venv/bin/activate
pip install -r /opt/planilla_mkt/requirements.txt
```

## Qué cambió para producción

Se aplicaron estos cambios:

1. La ruta del JSON pasó a ser configurable.
2. Las credenciales de HomeBroker salieron del código.
3. El nombre de la planilla pasó a ser configurable.
4. La lógica de negocio se separó en `planilla_mkt_app.py`.
5. Se agregó logging rotativo.
6. Se agregó reconexión automática.
7. Se agregó apagado ordenado por señales.
8. Se agregó `healthcheck.json` con métricas básicas.
9. Se agregó `requirements.txt`.
10. Se agregó `.env.example`.
11. Se agregaron servicios y timers `systemd` para arranque y stop automáticos.
12. Se agregó validación de día hábil usando `cgb_utils.feriados`.
13. Se agregó watchdog operativo con ventana de mercado para evitar reconexiones fuera de horario.
14. Se agregó bot de Telegram para consultar estado, healthcheck y controlar el servicio desde chats autorizados.
