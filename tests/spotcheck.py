"""Decode our textures at a few cities and compare with Open-Meteo's copy of the same model run.

  python tests/spotcheck.py out hrrr      (or: ... out ecmwf)

Pass: temperature within 1.5 °F, wind speed within 2 mph. Direction is printed, not judged: Open-Meteo's
HRRR winds are not rotated from the HRRR grid to true north (checked 2026-10-11), so they read up to
~15° off near the coasts. tests/rotation.py checks our rotation against ECMWF instead.
Our values blend the four nearest grid cells; Open-Meteo takes the nearest one, so a sharp local
gradient (a coast, a city) can still differ by a few degrees. Look before calling it a bug.
"""
import io
import json
import math
import pathlib
import sys

import numpy as np
import requests
from PIL import Image

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from wx import grid  # noqa: E402

CITIES = {"Seattle": (47.61, -122.33), "Reno": (39.53, -119.81), "Denver": (39.74, -104.99), "Bismarck": (46.81, -100.78),
          "Chicago": (41.88, -87.63), "Ithaca": (42.44, -76.50), "Atlanta": (33.75, -84.39), "Houston": (29.76, -95.37)}
OM = {"hrrr": "gfs_hrrr", "ecmwf": "ecmwf_ifs025"}


def pix(lat, lon, w):
    h = grid.height_for(w)
    x = (lon - grid.WEST) / (grid.EAST - grid.WEST) * w
    y = (grid.merc_y(grid.NORTH) - grid.merc_y(lat)) / (grid.merc_y(grid.NORTH) - grid.merc_y(grid.SOUTH)) * h
    return int(y), int(x)


def main(root, model):
    man = json.loads((pathlib.Path(root) / f"wx/{model}/latest.json").read_text())
    F = man["fields"]
    hour = next(h for h in man["hours"] if "wind" in h["fields"] and h["f"] > 0)
    w = man["box"]["sizes"]["full"][0]
    load = lambda field: np.asarray(Image.open(pathlib.Path(root) / man["path"].format(run=hour["run"], field=field, f=f"{hour['f']:03d}", size=""))).astype(np.int32)
    T, Wd = load("temp"), load("wind")
    t_iso = hour["t"][:13] + ":00"
    fails = 0
    print(f"{model} run {hour['run']} +{hour['f']}h valid {hour['t']}")
    for name, (lat, lon) in CITIES.items():
        y, x = pix(lat, lon, w)
        q = T[y, x, 0] * 256 + T[y, x, 1]
        if q == 65535:
            print(f"  {name:9s} no data"); continue
        temp = F["temp"]["min"] + q * F["temp"]["step"]
        vm = F["wind"]["vmax"]
        u, v = (Wd[y, x, 0] / 254 * 2 * vm - vm), (Wd[y, x, 1] / 254 * 2 * vm - vm)
        spd = math.hypot(u, v) * 2.23694
        dirn = (math.degrees(math.atan2(-u, -v)) + 360) % 360          # direction the wind comes FROM
        r = requests.get("https://api.open-meteo.com/v1/forecast", params=dict(latitude=lat, longitude=lon, models=OM[model],
                         hourly="temperature_2m,wind_speed_10m,wind_direction_10m", temperature_unit="fahrenheit",
                         wind_speed_unit="mph", timezone="UTC", past_days=1, forecast_days=2), timeout=60).json()
        i = r["hourly"]["time"].index(t_iso)
        ot, os_, od = r["hourly"]["temperature_2m"][i], r["hourly"]["wind_speed_10m"][i], r["hourly"]["wind_direction_10m"][i]
        dd = abs((dirn - od + 180) % 360 - 180)
        ok = abs(temp - ot) <= 1.5 and abs(spd - os_) <= 2
        fails += not ok
        print(f"  {name:9s} ours {temp:5.1f}°F {spd:4.1f} mph from {dirn:3.0f}° | Open-Meteo {ot:5.1f}°F {os_:4.1f} mph from {od:3.0f}°  {'ok' if ok else 'CHECK'}")
    print(f"{len(CITIES) - fails} of {len(CITIES)} within tolerance")


if __name__ == "__main__":
    main(*sys.argv[1:3])
