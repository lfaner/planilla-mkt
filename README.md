# Planilla MKT

Este proyecto actualiza una Google Sheet con cotizaciones de mercado obtenidas desde `pyhomebroker`.

El objetivo operativo es dejarlo listo para correr en un VPS en forma automática, a una hora determinada, con configuración externa al código y sin secretos hardcodeados.

## Estado actual del script

El archivo principal es [prueba-produc.py](<c:/Users/Usuario/OneDrive - Capital Gain Bursatil/Proyectos/Planilla_mkt/prueba-produc.py>).

Flujo real:

1. Lee configuración desde variables de entorno.
2. Abre la planilla de Google Sheets.
3. Toma tickers desde la hoja 2.
4. Construye `DataFrame`s base para instrumentos y cauciones.
5. Se autentica en HomeBroker.
6. Se suscribe a cotizaciones online.
7. Entra en un `while True`.
8. Cada 10 segundos, si hubo cambios, actualiza Google Sheets.

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
├── planilla-mkt-start.service
├── planilla-mkt-start.timer
├── planilla-mkt-stop.service
├── planilla-mkt-stop.timer
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
- `planilla-mkt.service`
- `planilla-mkt-start.service`
- `planilla-mkt-stop.service`
- `planilla-mkt-start.timer`
- `planilla-mkt-stop.timer`

### 2. Crear el entorno e instalar dependencias

```bash
mkdir -p /opt/planilla_mkt
cd /opt/planilla_mkt
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 3. Cargar variables de entorno

```bash
set -a
source /opt/planilla_mkt/.env
set +a
```

### 4. Probar ejecución

```bash
cd /opt/planilla_mkt
source .venv/bin/activate
set -a
source .env
set +a
python prueba-produc.py
```

Si está bien configurado:

1. Se autentica en HomeBroker.
2. Abre la planilla.
3. Empieza a actualizar Google Sheets.
4. Queda corriendo hasta que lo detengas.

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
ExecStart=/opt/planilla_mkt/.venv/bin/python /opt/planilla_mkt/prueba-produc.py
Restart=always
RestartSec=15
StandardOutput=append:/var/log/planilla-mkt.log
StandardError=append:/var/log/planilla-mkt.error.log

[Install]
WantedBy=multi-user.target
```

Notas:

- Ajustá `User=planilla` al usuario real del VPS.
- Si tu sistema no soporta `append:` en `StandardOutput`, usá `journalctl`.

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
4. Se agregó logging básico.
5. Se agregó `requirements.txt`.
6. Se agregó `.env.example`.
7. Se agregaron servicios y timers `systemd` para arranque y stop automáticos.
8. Se agregó validación de día hábil usando `cgb_utils.feriados`.

## Qué falta para una versión todavía más robusta

Esto ya deja el script en un estado razonable para producción simple. Lo siguiente sería la segunda etapa:

1. Reintentos y reconexión automática a HomeBroker.
2. Manejo de apagado ordenado con señales.
3. Separar el script en funciones o módulos.
4. Métricas o health check.
5. Rotación de logs.
