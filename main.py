import gc
from machine import Pin
import onewire, ds18x20, dht, time, network
import urequests

# Secrets
try:
    from secrets import SSID, PASSWORD, INFLUX_TOKEN, KUMA_PUSH_URL
except ImportError:
    raise RuntimeError("Create secrets.py on the Pico with your credentials")

# Config
INFLUX_HOST     = "http://10.10.1.2:8086"
INFLUX_ORG      = "homelab"
INFLUX_BUCKET   = "environment"
INFLUX_URL      = f"{INFLUX_HOST}/api/v2/write?org={INFLUX_ORG}&bucket={INFLUX_BUCKET}&precision=s"

READ_INTERVAL_S    = 60
DHT11_MIN_INTERVAL_MS = 2000

# Hardware 
ow = onewire.OneWire(Pin(14))
ds = ds18x20.DS18X20(ow)
roms = ds.scan()
dht_sensor = dht.DHT11(Pin(15))
wlan = network.WLAN(network.STA_IF)

_last_dht_ticks = time.ticks_ms() - DHT11_MIN_INTERVAL_MS

# Wifi
def connect_wifi():
    wlan.active(True)
    if wlan.isconnected():
        return True
    wlan.connect(SSID, PASSWORD)
    for _ in range(20):
        if wlan.isconnected():
            print("wifi ok, ip:", wlan.ifconfig()[0])
            return True
        time.sleep(1)
    print("wifi failed")
    return False

# Sensors
def read_ds18b20():
    global roms
    if not roms:
        roms = ds.scan()
        if not roms:
            return None
    try:
        ds.convert_temp()
        time.sleep_ms(750)
        return round(ds.read_temp(roms[0]), 3)
    except Exception:
        roms = []
        return None

def read_dht11():
    global _last_dht_ticks
    if time.ticks_diff(time.ticks_ms(), _last_dht_ticks) < DHT11_MIN_INTERVAL_MS:
        return None, None
    try:
        dht_sensor.measure()
        _last_dht_ticks = time.ticks_ms()
        return dht_sensor.temperature(), dht_sensor.humidity()
    except Exception:
        return None, None

# InfluxDB 
def post_influx(temp_main, temp_aux, humidity):
    fields = []
    if temp_main is not None:
        fields.append(f"temp_main_c={temp_main}")
    if temp_aux is not None:
        fields.append(f"temp_aux_c={temp_aux}")
    if humidity is not None:
        fields.append(f"humidity_pct={humidity}")

    if not fields:
        print("influx skipped: no valid sensor data")
        return False

    payload = "environment " + ",".join(fields)
    try:
        r = urequests.post(
            INFLUX_URL,
            headers={
                "Authorization": f"Token {INFLUX_TOKEN}",
                "Content-Type": "text/plain"
            },
            data=payload,
            timeout=10
        )
        ok = r.status_code == 204
        r.close()
        if not ok:
            print("influx error: status", r.status_code)
        return ok
    except Exception as e:
        print("influx error:", e)
        return False

# Kuma
def push_kuma():
    try:
        r = urequests.get(KUMA_PUSH_URL, timeout=5)
        r.close()
    except Exception as e:
        print("kuma error:", e)

# Main 
connect_wifi()

while True:
    if not wlan.isconnected():
        print("wifi lost, reconnecting...")
        connect_wifi()

    temp_main = read_ds18b20()
    temp_aux, humidity = read_dht11()

    parts = []
    parts.append(f"temp_main_c={temp_main if temp_main is not None else 'err'}")
    parts.append(f"temp_aux_c={temp_aux if temp_aux is not None else 'err'}")
    parts.append(f"humidity_pct={humidity if humidity is not None else 'err'}")
    print(",".join(parts))

    ok = post_influx(temp_main, temp_aux, humidity)
    if ok:
        push_kuma()

    gc.collect()
    time.sleep(READ_INTERVAL_S)