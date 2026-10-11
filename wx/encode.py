"""Pack values into PNG "data textures" the browser decodes on the GPU.

RGB only (no alpha): browsers premultiply alpha, which would corrupt the data bytes.

  rg16     one scalar: v = min + (R*256 + G) * step; R=G=255 is no data. B = 0. Values are rounded to
           `step` first: finer precision is noise that only costs bytes (temperature PNGs were 2.4 MB at 0.003 °F).
  uv8      wind: R = u, G = v, each v = byte / 254 * 2*vmax - vmax (m/s); B = 255 is no data.
  cloud8   cloud cover %: R = total, G = low, B = high, each byte / 2.5; 255 is no data.

Field scales live in FIELDS and are copied into each model's latest.json.
"""
from __future__ import annotations

import io

import numpy as np
from PIL import Image

FIELDS = {
    "temp":   {"enc": "rg16", "min": -60.0, "max": 130.0, "step": 0.1, "unit": "°F", "name": "Temperature"},
    "wind":   {"enc": "uv8", "vmax": 50.0, "unit": "m/s", "name": "Wind"},
    "gust":   {"enc": "rg16", "min": 0.0, "max": 150.0, "step": 0.5, "unit": "mph", "name": "Wind gusts"},
    "cloud":  {"enc": "cloud8", "channels": ["total", "low", "high"], "unit": "%", "name": "Clouds"},
    "precip": {"enc": "rg16", "min": 0.0, "max": 4.0, "step": 0.0005, "unit": "in/h", "name": "Rain and snow"},
    "refc":   {"enc": "rg16", "min": -20.0, "max": 80.0, "step": 0.5, "unit": "dBZ", "name": "Forecast radar"},
    "cape":   {"enc": "rg16", "min": 0.0, "max": 8000.0, "step": 10.0, "unit": "J/kg", "name": "Storm energy (CAPE)"},
    "ltng":   {"enc": "rg16", "min": 0.0, "max": 50.0, "step": 0.01, "unit": "flashes/km²/5 min", "name": "Lightning threat"},
}


def _png(rgb: np.ndarray) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(rgb, "RGB").save(buf, "PNG", optimize=False, compress_level=6)
    return buf.getvalue()


def rg16(v: np.ndarray, lo: float, hi: float, step: float) -> bytes:
    bad = ~np.isfinite(v)
    q = np.clip(np.round((np.clip(np.nan_to_num(v, nan=lo), lo, hi) - lo) / step), 0, 65534).astype(np.uint16)
    q[bad] = 65535
    rgb = np.zeros(v.shape + (3,), np.uint8)
    rgb[..., 0] = q >> 8
    rgb[..., 1] = q & 255
    return _png(rgb)


def uv8(u: np.ndarray, v: np.ndarray, vmax: float) -> bytes:
    bad = ~(np.isfinite(u) & np.isfinite(v))
    f = lambda a: np.clip(np.round((np.nan_to_num(a) + vmax) / (2 * vmax) * 254), 0, 254).astype(np.uint8)
    rgb = np.zeros(u.shape + (3,), np.uint8)
    rgb[..., 0], rgb[..., 1] = f(u), f(v)
    rgb[..., 2] = np.where(bad, 255, 0)
    return _png(rgb)


def cloud8(total: np.ndarray, low: np.ndarray | None, high: np.ndarray | None) -> bytes:
    def ch(a):
        if a is None:
            return np.full(total.shape, 255, np.uint8)
        out = np.clip(np.round(np.nan_to_num(a) * 2.5), 0, 250).astype(np.uint8)
        out[~np.isfinite(a)] = 255
        return out
    return _png(np.dstack([ch(total), ch(low), ch(high)]))


def encode(field: str, arrays: dict) -> bytes:
    F = FIELDS[field]
    if F["enc"] == "rg16":
        return rg16(arrays[field], F["min"], F["max"], F["step"])
    if F["enc"] == "uv8":
        return uv8(arrays["u"], arrays["v"], F["vmax"])
    return cloud8(arrays["cloud"], arrays.get("cloud_low"), arrays.get("cloud_high"))


def decode_rg16(png: bytes, lo: float, step: float) -> np.ndarray:
    """For tests: the inverse of rg16."""
    a = np.asarray(Image.open(io.BytesIO(png)).convert("RGB")).astype(np.int32)
    q = a[..., 0] * 256 + a[..., 1]
    v = lo + q * step
    return np.where(q == 65535, np.nan, v)
