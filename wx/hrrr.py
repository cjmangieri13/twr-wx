"""HRRR (NOAA, 3 km, lower 48): hourly runs to 18 h, 48 h at 00/06/12/18z.

Source: NOAA Open Data on AWS, noaa-hrrr-bdp-pds, wrfsfc files, one GRIB message per field
read by byte range via the .idx files.
"""
from __future__ import annotations

import datetime as dt
from functools import lru_cache

import eccodes
import numpy as np
from pyproj import Proj
from scipy.ndimage import map_coordinates

from . import fetch, grid
from .gribs import LOCK

BASE = "https://noaa-hrrr-bdp-pds.s3.amazonaws.com"
NAME = "HRRR (NOAA, 3 km)"
ATTRIBUTION = "HRRR: NOAA/NCEP, via NOAA Open Data on AWS"
FIELDS = ["temp", "wind", "gust", "cloud", "precip", "refc", "cape", "ltng"]

# idx selectors; the time part ("anl" or "N hour fcst") is matched loosely except for precipitation
SEL = {
    "temp": r":TMP:2 m above ground:", "u": r":UGRD:10 m above ground:", "v": r":VGRD:10 m above ground:",
    "gust": r":GUST:surface:", "cloud": r":TCDC:entire atmosphere:", "cloud_low": r":LCDC:low cloud layer:",
    "cloud_high": r":HCDC:high cloud layer:", "refc": r":REFC:entire atmosphere:", "cape": r":CAPE:surface:",
    "ltng": r":LTNG:entire atmosphere:",
}


def url(run: dt.datetime, f: int) -> str:
    return f"{BASE}/hrrr.{run:%Y%m%d}/conus/hrrr.t{run:%H}z.wrfsfcf{f:02d}.grib2"


def has(run: dt.datetime, f: int) -> bool:
    return fetch.exists(url(run, f) + ".idx")


def newest_runs(now: dt.datetime | None = None) -> tuple[dt.datetime, dt.datetime | None]:
    """(newest run with f18, newest 00/06/12/18z run with f48)."""
    now = (now or dt.datetime.utcnow()).replace(minute=0, second=0, microsecond=0)
    newest = next((now - dt.timedelta(hours=h) for h in range(0, 8) if has(now - dt.timedelta(hours=h), 18)), None)
    if newest is None:
        raise RuntimeError("no HRRR run with f18 in the last 8 hours")
    syn = None
    for h in range(0, 19):
        c = newest - dt.timedelta(hours=h)
        if c.hour % 6 == 0 and has(c, 48):
            syn = c
            break
    return newest, syn


# ---- projection: Lambert conformal, read from each GRIB header; the pixel lookup is cached per grid
def _proj(sample: bytes) -> dict:
    with LOCK:
        h = eccodes.codes_new_from_message(sample)
        g = lambda k: eccodes.codes_get(h, k)
        assert g("jScansPositively") == 1 and g("iScansNegatively") == 0, "unexpected HRRR scan order"
        p = dict(lat1=g("Latin1InDegrees"), lat2=g("Latin2InDegrees"), lad=g("LaDInDegrees"), lov=g("LoVInDegrees") - 360,
                 R=g("radius"), lon00=g("longitudeOfFirstGridPointInDegrees") - 360, lat00=g("latitudeOfFirstGridPointInDegrees"),
                 dx=g("DxInMetres"), dy=g("DyInMetres"), grid_rel=bool(g("uvRelativeToGrid")))
        eccodes.codes_release(h)
        return p


@lru_cache(maxsize=4)
def _coords(width: int, key: tuple):
    p = dict(key)
    P = Proj(proj="lcc", lat_1=p["lat1"], lat_2=p["lat2"], lat_0=p["lad"], lon_0=p["lov"], R=p["R"])
    x0, y0 = P(p["lon00"], p["lat00"])
    lon, lat = grid.lonlat(width)
    x, y = P(lon, lat)
    return np.stack([(y - y0) / p["dy"], (x - x0) / p["dx"]])


def _values(msg: bytes) -> np.ndarray:
    with LOCK:
        h = eccodes.codes_new_from_message(msg)
        v = eccodes.codes_get_values(h).astype(np.float32)
        nx, ny = eccodes.codes_get(h, "Nx"), eccodes.codes_get(h, "Ny")
        if eccodes.codes_get(h, "bitmapPresent"):
            v[v == eccodes.codes_get(h, "missingValue")] = np.nan
        eccodes.codes_release(h)
        return v.reshape(ny, nx)


def step(run: dt.datetime, f: int, widths: list[int]) -> dict[int, dict[str, np.ndarray]]:
    """Every field for one forecast hour, resampled onto each output width."""
    u = url(run, f)
    idx = fetch.noaa_index(u + ".idx")
    msgs = {k: fetch.noaa_message(u, idx, pat) for k, pat in SEL.items()}
    if f > 0:
        msgs["precip"] = fetch.noaa_message(u, idx, rf":APCP:surface:{f - 1}-{f} hour acc fcst:")
    p = _proj(msgs["temp"])
    key = tuple(sorted((k, v) for k, v in p.items() if k != "grid_rel"))
    out = {}
    for w in widths:
        C = _coords(w, key)
        rs = lambda m: map_coordinates(_values(m), C, order=1, cval=np.nan, mode="constant") if m else None
        a = {k: rs(m) for k, m in msgs.items()}
        if p["grid_rel"]:                       # grid-relative winds -> earth-relative
            lon, _ = grid.lonlat(w)
            ang = np.sin(np.radians(p["lat1"])) * np.radians(lon - p["lov"])
            c, s = np.cos(ang), np.sin(ang)
            a["u"], a["v"] = c * a["u"] + s * a["v"], -s * a["u"] + c * a["v"]
        a["temp"] = (a["temp"] - 273.15) * 9 / 5 + 32
        if a.get("gust") is not None:
            a["gust"] = a["gust"] * 2.23694
        if a.get("precip") is not None:
            a["precip"] = a["precip"] / 25.4        # kg/m2 (mm) in the hour -> inches per hour
        out[w] = {k: v for k, v in a.items() if v is not None}
    return out
