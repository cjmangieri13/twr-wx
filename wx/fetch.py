"""HTTP with retries, and byte-range reads of single GRIB messages via the index files."""
from __future__ import annotations

import json
import re
import time

import requests

S = requests.Session()
S.headers["User-Agent"] = "twr-wx (rhearunswild.com weather map; github.com/cjmangieri13/twr-wx)"


def get(url: str, *, headers: dict | None = None, ok404: bool = False, tries: int = 4) -> requests.Response | None:
    for n in range(tries):
        try:
            r = S.get(url, headers=headers or {}, timeout=60)
            if r.status_code == 404 and ok404:
                return None
            if r.status_code in (200, 206):
                return r
        except requests.RequestException:
            pass
        time.sleep(2 * (n + 1))
    raise RuntimeError(f"GET failed after {tries} tries: {url}")


def exists(url: str) -> bool:
    try:
        return S.head(url, timeout=30).status_code == 200
    except requests.RequestException:
        return False


def ranged(url: str, start: int, end: int | None) -> bytes:
    rng = f"bytes={start}-{'' if end is None else end}"
    return get(url, headers={"Range": rng}).content


# ---- NOAA text index: "n:offset:d=YYYYMMDDHH:VAR:level:time:" one message per line
def noaa_index(idx_url: str) -> list[tuple[int, int | None, str]]:
    lines = get(idx_url).text.strip().splitlines()
    offs = [int(l.split(":")[1]) for l in lines]
    return [(offs[i], offs[i + 1] - 1 if i + 1 < len(offs) else None, lines[i]) for i in range(len(lines))]


def noaa_message(grib_url: str, index: list, pattern: str) -> bytes | None:
    rx = re.compile(pattern)
    for a, b, line in index:
        if rx.search(line):
            return ranged(grib_url, a, b)
    return None


# ---- ECMWF JSON-lines index: {"param":..., "levtype":..., "_offset":..., "_length":...}
def ecmwf_index(idx_url: str) -> list[dict]:
    r = get(idx_url, ok404=True)
    return [json.loads(l) for l in r.text.splitlines()] if r else []


def ecmwf_message(grib_url: str, index: list[dict], param: str, levtype: str = "sfc") -> bytes | None:
    for e in index:
        if e.get("param") == param and e.get("levtype") == levtype:
            return ranged(grib_url, e["_offset"], e["_offset"] + e["_length"] - 1)
    return None
