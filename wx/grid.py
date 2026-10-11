"""The fixed output box, in Web Mercator.

PRIVACY: this box never changes and never follows the trip. A box that tracked the route
would publish where Chris is heading. Nothing in this repo reads the itinerary.
"""
from __future__ import annotations

import math
from functools import lru_cache

import numpy as np

WEST, EAST, SOUTH, NORTH = -135.0, -55.0, 20.0, 55.0
SIZES = {"full": 2048, "half": 1024}          # widths; heights follow from the Mercator aspect


def merc_y(lat: float) -> float:
    return math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


def height_for(width: int) -> int:
    xspan = math.radians(EAST - WEST)
    return round(width * (merc_y(NORTH) - merc_y(SOUTH)) / xspan)


@lru_cache(maxsize=4)
def lonlat(width: int) -> tuple[np.ndarray, np.ndarray]:
    """Pixel-center longitudes and latitudes, row 0 = north edge (image order)."""
    h = height_for(width)
    lon = WEST + (EAST - WEST) * (np.arange(width) + 0.5) / width
    y0, y1 = merc_y(NORTH), merc_y(SOUTH)
    ys = y0 + (y1 - y0) * (np.arange(h) + 0.5) / h
    lat = np.degrees(2 * np.arctan(np.exp(ys)) - np.pi / 2)
    return np.meshgrid(lon, lat)


def box() -> dict:
    return {"west": WEST, "east": EAST, "south": SOUTH, "north": NORTH, "proj": "EPSG:3857",
            "sizes": {k: [w, height_for(w)] for k, w in SIZES.items()}}
