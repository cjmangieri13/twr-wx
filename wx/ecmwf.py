"""ECMWF IFS open data (0.25°, CC BY 4.0): 00z and 12z runs, 3-hourly to 144 h, then 6-hourly.
We publish to 168 h (7 days). Source: data.ecmwf.int, read by byte range via the .index files.
"""
from __future__ import annotations

import datetime as dt
from functools import lru_cache

import eccodes
import numpy as np
from scipy.ndimage import map_coordinates

from . import fetch, grid

BASE = "https://data.ecmwf.int/forecasts"
NAME = "ECMWF IFS (European, 0.25°)"
ATTRIBUTION = "ECMWF IFS open data, CC BY 4.0"
FIELDS = ["temp", "wind", "gust", "cloud", "precip", "cape"]
STEPS = list(range(0, 145, 3)) + list(range(150, 169, 6))
PARAMS = {"temp": "2t", "u": "10u", "v": "10v", "gust": "10fg", "cloud": "tcc", "tp": "tp", "cape": "mucape"}


def url(run: dt.datetime, s: int) -> str:
    return f"{BASE}/{run:%Y%m%d}/{run:%H}z/ifs/0p25/oper/{run:%Y%m%d%H}0000-{s}h-oper-fc.grib2"


def idx_url(run: dt.datetime, s: int) -> str:
    return url(run, s)[: -len(".grib2")] + ".index"


def newest_run(now: dt.datetime | None = None) -> dt.datetime:
    now = now or dt.datetime.utcnow()
    c = now.replace(hour=12 if now.hour >= 12 else 0, minute=0, second=0, microsecond=0)
    for _ in range(6):
        if fetch.exists(idx_url(c, STEPS[-1])):
            return c
        c -= dt.timedelta(hours=12)
    raise RuntimeError("no complete ECMWF run in the last 3 days")


def _values(msg: bytes):
    h = eccodes.codes_new_from_message(msg)
    g = lambda k: eccodes.codes_get(h, k)
    v = eccodes.codes_get_values(h).astype(np.float32)
    if g("bitmapPresent"):
        v[v == g("missingValue")] = np.nan
    meta = dict(ni=g("Ni"), nj=g("Nj"), lat0=g("latitudeOfFirstGridPointInDegrees"), lon0=g("longitudeOfFirstGridPointInDegrees"),
                di=g("iDirectionIncrementInDegrees"), dj=g("jDirectionIncrementInDegrees"), jpos=g("jScansPositively"))
    eccodes.codes_release(h)
    return v.reshape(meta["nj"], meta["ni"]), meta


@lru_cache(maxsize=4)
def _coords(width: int, lat0: float, lon0: float, di: float, dj: float, jpos: int, ni: int):
    lon, lat = grid.lonlat(width)
    j = (lat - lat0) / dj if jpos else (lat0 - lat) / dj
    i = ((lon - lon0) % 360) / di
    return np.stack([j, i])


def step(run: dt.datetime, s: int, widths: list[int]) -> dict[int, dict[str, np.ndarray]]:
    u = url(run, s)
    idx = fetch.ecmwf_index(idx_url(run, s))
    out = {}
    raw = {k: fetch.ecmwf_message(u, idx, p) for k, p in PARAMS.items()}
    dec = {k: _values(m) for k, m in raw.items() if m}
    for w in widths:
        a = {}
        for k, (v, m) in dec.items():
            C = _coords(w, m["lat0"], m["lon0"], m["di"], m["dj"], m["jpos"], m["ni"])
            a[k] = map_coordinates(v, C, order=1, cval=np.nan, mode="constant")
        a["temp"] = (a["temp"] - 273.15) * 9 / 5 + 32
        if "gust" in a:
            a["gust"] = a["gust"] * 2.23694
        if "cloud" in a and np.nanmax(a["cloud"]) <= 1.01:
            a["cloud"] = a["cloud"] * 100
        out[w] = a
    return out


def precip_rate(tp_now: np.ndarray, tp_prev: np.ndarray | None, hours: int) -> np.ndarray | None:
    """tp is accumulated metres since the run started; the rate is inches per hour over the step."""
    if tp_prev is None or hours <= 0:
        return None
    return np.clip(tp_now - tp_prev, 0, None) / hours * 39.3701


def tp_only(run: dt.datetime, s: int, widths: list[int]) -> dict[int, np.ndarray]:
    """Just the accumulated precipitation at a step, for differencing."""
    m = fetch.ecmwf_message(url(run, s), fetch.ecmwf_index(idx_url(run, s)), "tp")
    if not m:
        return {}
    v, meta = _values(m)
    return {w: map_coordinates(v, _coords(w, meta["lat0"], meta["lon0"], meta["di"], meta["dj"], meta["jpos"], meta["ni"]),
                               order=1, cval=np.nan, mode="constant") for w in widths}
