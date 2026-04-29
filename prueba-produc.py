import logging
import os
from pathlib import Path

import gspread
import pandas as pd
from datetime import date, timedelta
import time
from pyhomebroker import HomeBroker

# from dateutil.relativedelta import relativedelta
# import datetime
 

import gspread_dataframe as gdf
from gspread_dataframe import set_with_dataframe

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_GOOGLE_CREDENTIALS = BASE_DIR / "credenciales_nuevo.json"


def get_env(name, default=None, required=False):
    value = os.getenv(name, default)
    if required and (value is None or str(value).strip() == ""):
        raise RuntimeError(f"Falta la variable de entorno requerida: {name}")
    return value


json_credentials = Path(
    get_env("GOOGLE_CREDENTIALS_PATH", str(DEFAULT_GOOGLE_CREDENTIALS))
).expanduser()
if not json_credentials.exists():
    raise FileNotFoundError(
        f"No existe el archivo de credenciales de Google: {json_credentials}"
    )

sheet_name = get_env("GOOGLE_SHEET_NAME", "Planilla_CGB")
gc = gspread.service_account(filename=str(json_credentials))
sh = gc.open(sheet_name)
shtTickers = sh.get_worksheet(1)

## Definimos las funciones para el drive de Datos Original
'''
def getAccionesList():
    if "Acciones" in rng:
        rng.remove("Acciones")
    df1 = rng
    oAcciones = df1
    ACC = pd.DataFrame(
        {"symbol": oAcciones},
        columns=[
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
        ],
    )
    ACC = ACC.set_index("symbol")
    ACC["datetime"] = pd.to_datetime(ACC["datetime"])
    return ACC
'''
def getAccionesList():
    rng = shtTickers.col_values(1)  # Asegúrate de que el índice corresponda a la columna de Acciones.
    if "Acciones" in rng:
        rng.remove("Acciones")
    df1 = rng
    oAcciones = df1
    ACC = pd.DataFrame(
        {"symbol": oAcciones},
        columns=[
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
        ],
    )
    ACC = ACC.set_index("symbol")
    ACC["datetime"] = pd.to_datetime(ACC["datetime"])
    return ACC


'''
def getBonosList():
    rng = shtTickers.col_values(3)
    rng.remove("Bonos")
    df1 = rng
    oBonos = df1
    Bonos = pd.DataFrame(
        {"symbol": oBonos},
        columns=[
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
        ],
    )
    Bonos = Bonos.set_index("symbol")
    Bonos["datetime"] = pd.to_datetime(Bonos["datetime"])
    return Bonos
'''

def getBonosList():
    rng = shtTickers.col_values(3)  # Obtiene los valores de la columna 3

    # Verificar si "Bonos" está en la lista antes de eliminarlo
    if "Bonos" in rng:
        rng.remove("Bonos")

    df1 = rng
    oBonos = df1
    Bonos = pd.DataFrame(
        {"symbol": oBonos},
        columns=[
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
        ],
    )
    Bonos = Bonos.set_index("symbol")

    # Verifica que la columna "datetime" tenga datos antes de convertirla
    if not Bonos.empty and "datetime" in Bonos.columns:
        Bonos["datetime"] = pd.to_datetime(Bonos["datetime"], errors="coerce")

    return Bonos

    
def getCedearsList():
    rng = shtTickers.col_values(5)
    rng.remove("Cedears")
    df1 = rng
    oCedears = df1
    Cedears = pd.DataFrame(
        {"symbol": oCedears},
        columns=[
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
        ],
    )
    Cedears = Cedears.set_index("symbol")
    Cedears["datetime"] = pd.to_datetime(Cedears["datetime"])
    return Cedears

def getLetrasList():
    rng = shtTickers.col_values(7)
    
    rng.remove("Letras")
    df1 = rng
    oLetras = df1
    Letras = pd.DataFrame(
        {"symbol": oLetras},
        columns=[
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
        ],
    )
    Letras = Letras.set_index("symbol")
    Letras["datetime"] = pd.to_datetime(Letras["datetime"])
    return Letras

def getONSList():
    rng = shtTickers.col_values(9)
    rng.remove('ONs')
    df1 = rng
    oONS = df1
    ONS = pd.DataFrame(
        {'symbol' : oONS}, 
        columns=[
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
            'operations',
            'datetime',
        ],
    )
    ONS = ONS.set_index('symbol')
    ONS['datetime'] = pd.to_datetime(ONS['datetime'])
    return ONS

def getOptionsList():
    rng = shtTickers.col_values(11)
    rng.remove('Opciones')
    df1 = rng
    oOpciones = df1
    Opciones = pd.DataFrame(
        {'symbol' : oOpciones},
        columns=[
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
        ],
    )
    Opciones = Opciones.set_index('symbol')
    Opciones['datetime'] = pd.to_datetime(Opciones['datetime'])
    return Opciones


i = 1
fechas = []
while i < 31:
    fecha = date.today() + timedelta(days=i)
    fechas.extend([fecha])
    i += 1

cauciones = pd.DataFrame({'settlement':fechas}, columns=['settlement','last', 'turnover', 'bid_amount', 'bid_rate', 'ask_rate', 'ask_amount'])
cauciones['settlement'] = pd.to_datetime(cauciones['settlement'])
cauciones = cauciones.set_index('settlement')


ACC = getAccionesList()
bonos = getBonosList()
cedears = getCedearsList()
letras = getLetrasList()
ONS = getONSList()
#options = getOptionsList()
#options = options.rename(columns={"bid_size":"bidsize", "ask_size":"asksize"})

'''
everything = ACC.append(bonos)
everything = everything.append(cedears)
everything = everything.append(letras)
everything = everything.append(ONS)
#everything = everything.append(options)
'''

everything = pd.concat([ACC, bonos])
everything = pd.concat([everything, cedears])
everything = pd.concat([everything, letras])
everything = pd.concat([everything, ONS])

listLength = len(everything) + 2
shtTest = sh.get_worksheet(2)
shcauciones = sh.get_worksheet(3)
#shmep = sh.get_worksheet(12)
#shccl = sh.get_worksheet(13)

## Abrimos Drive para Datos Productores

#sh1 = gc.open("Datos Productores - Becerra Bursátil")               
#shtTickers1 = sh1.get_worksheet(0)


#shtTest1 = sh1.get_worksheet(1)
#shcauciones1 = sh1.get_worksheet(2)

## Abrimos Drive para Datos Propios

#sh2 = gc.open("Opciones Financieras")
#shtTickers2 = sh2.get_worksheet(0)

#shTest2 = sh2.get_worksheet(1)
#shcauciones2 = sh2.get_worksheet(2)
#shopciones2 = sh2.get_worksheet(3)

## Conexión a Cocos o a cualquier HB que tengas

broker = int(get_env("HB_BROKER", "284"))
dni = get_env("HB_DNI", required=True)
user = get_env("HB_USER", required=True)
password = get_env("HB_PASSWORD", required=True)


def on_securities(online, quotes):
    global everything
    # print(quotes)
    thisData = quotes
    thisData = thisData.reset_index()
    thisData["symbol"] = thisData["symbol"] + " - " + thisData["settlement"]
    thisData = thisData.drop(["settlement"], axis=1)
    thisData = thisData.set_index("symbol")
    thisData["change"] = thisData["change"] / 100
    thisData["datetime"] = pd.to_datetime(thisData["datetime"])
    everything.update(thisData)


def on_repos(online, quotes):
    global cauciones
    thisData = quotes
    thisData = thisData.reset_index()
    thisData = thisData.set_index("symbol")
    thisData = thisData[['PESOS' in s for s in quotes.index]]
    thisData = thisData.reset_index()
    thisData['settlement'] = pd.to_datetime(thisData['settlement'])
    thisData = thisData.set_index("settlement")
    thisData['last'] = thisData["last"] / 100
    thisData['bid_rate'] = thisData["bid_rate"] / 100
    thisData['ask_rate'] = thisData["ask_rate"] / 100
    thisData = thisData.drop(['open', 'high', 'low', 'volume', 'operations', 'datetime'], axis=1)
    thisData = thisData[['last', 'turnover', 'bid_amount', 'bid_rate', 'ask_rate', 'ask_amount']]
    cauciones.update(thisData)
    
def on_options(online, quotes):
    global options
    thisData = quotes
    thisData = thisData.drop(["expiration", "strike", "kind"], axis = 1)
    thisData["change"] = thisData["change"] / 100
    thisData["datetime"] = pd.to_datetime(thisData["datetime"])
    thisData = thisData.rename(columns={"bid_size" : "bidsize", "ask_size" : "asksize"})
    options.update(thisData)


def on_error(online, error):
    logger.error("Error Message Received: %s", error)


hb = HomeBroker(int(broker), on_options=on_options, on_securities=on_securities, on_repos = on_repos, on_error=on_error)

logger.info("Iniciando autenticacion en HomeBroker")
hb.auth.login(dni=dni, user=user, password=password, raise_exception=True)
logger.info("Conexion a HomeBroker establecida")
hb.online.connect()
hb.online.subscribe_options()
hb.online.subscribe_securities("bluechips", "24hs")  # Acciones del Panel lider - 24hs
hb.online.subscribe_securities("bluechips", "SPOT")  # Acciones del Panel lider - Contado Inmediato
hb.online.subscribe_securities("government_bonds", "24hs")  # Bonos - 24hs
hb.online.subscribe_securities("government_bonds", "SPOT")  # Bonos - Contado Inmediato
hb.online.subscribe_securities("cedears", "24hs")  # CEDEARS - 24hs
hb.online.subscribe_securities("cedears", "SPOT")  # CEDEARS - Contado Inmediato
hb.online.subscribe_securities("general_board", "24hs")  # Acciones del Panel general - 24hs
hb.online.subscribe_securities("general_board", "SPOT")  # Acciones del Panel general - Contado Inmediato
hb.online.subscribe_securities("short_term_government_bonds", "24hs")  # LETRAS - 24hs
hb.online.subscribe_securities("short_term_government_bonds", "SPOT")  # LETRAS - Contado Inmediato
hb.online.subscribe_securities('corporate_bonds', '24hs')               # Obligaciones Negociables - 24hs
hb.online.subscribe_securities('corporate_bonds', 'SPOT')               # Obligaciones Negociables - Contado Inmediato
hb.online.subscribe_repos()

#data_1 = hb.history.get_intraday_history('AL30')[['date','close']].set_index('date')
#data_d = hb.history.get_intraday_history('AL30D')[['date','close']].set_index('date')
#data_c = hb.history.get_intraday_history('AL30C')[['date','close']].set_index('date')

#data_mep = (data_1['close'] / data_d['close']) .dropna().to_frame().rename(columns={'close' : 'MEP'})
#data_cable = (data_1['close'] / data_c['close']).dropna().to_frame().rename(columns={'close' : 'CCL'})

# everything1 = everything.reset_index()
# everything2 = everything1.fillna('0')

# set_with_dataframe(shtTest, everything2)

#everything = everything.append(options)
'''
while True:
    try:
        # Editamos cosas del Original
        everything2 = everything.reset_index().fillna("0")
        cauciones1 = cauciones.reset_index().fillna("0")
        #shmep1 = data_mep.reset_index().fillna("0")
        #shccl1 = data_cable.reset_index().fillna("0")
        
        set_with_dataframe(shtTest, everything2)
        set_with_dataframe(shcauciones, cauciones1, row = 2, col = 2, include_column_header=False)
        
        #data_1 = hb.history.get_intraday_history('GD30')[['date','close']].set_index('date')
        #data_d = hb.history.get_intraday_history('GD30D')[['date','close']].set_index('date')
        #data_c = hb.history.get_intraday_history('GD30C')[['date','close']].set_index('date')
        #data_mep = (data_1['close'] / data_d['close']).dropna().to_frame().rename(columns={'close' : 'MEP'})
        #data_cable = (data_1['close'] / data_c['close']).dropna().to_frame().rename(columns={'close' : 'CCL'})

        
        #set_with_dataframe(shmep, data_mep, row = 2, col = 2,include_index=True, include_column_header=False)
        #set_with_dataframe(shccl, data_cable, row = 2, col = 2,include_index=True, include_column_header=False)
        
        # Editamos cosas del datos Productor

        everything3 = everything.reset_index().fillna("0")
        cauciones2 = cauciones.reset_index().fillna("0")

        #set_with_dataframe(shtTest1, everything3)
        #set_with_dataframe(shcauciones1, cauciones2, row=2, col=2, include_column_header=False)
        
        # Editamos cosas de datos propios
        
        #everything4 = everything.reset_index().fillna("0")
        #cauciones3 = cauciones.reset_index().fillna("0")
        #options1 = options.reset_index().fillna("0")
        
        #set_with_dataframe(shTest2, everything4)
        #set_with_dataframe(shcauciones2, cauciones3, row=2, col=2, include_column_header=False)
        #set_with_dataframe(shopciones2, options1)
    
        time.sleep(1)
    except:
        print("Error")

while True:
    try:
        # Editamos cosas del Original
        everything2 = everything.reset_index().fillna("0")
        cauciones1 = cauciones.reset_index().fillna("0")
        
        set_with_dataframe(shtTest, everything2)
        set_with_dataframe(shcauciones, cauciones1, row=2, col=2, include_column_header=False)

        # Puedes incluir otras actualizaciones aquí si las necesitas
        
        time.sleep(1)
    except Exception as e:
        print(f"Error: {e}")

'''
prev_data = None
while True:
    try:
        current_data = everything.reset_index().fillna("0")
        if not current_data.equals(prev_data):  # Solo actualiza si los datos cambian
            set_with_dataframe(shtTest, current_data)
            prev_data = current_data
            logger.info("Google Sheets actualizado")

        time.sleep(10)
    except Exception as e:
        logger.exception("Error en el loop principal: %s", e)
