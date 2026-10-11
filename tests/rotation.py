"""HRRR winds are grid-relative; wx/hrrr.py rotates them to true north. Check that against ECMWF
(earth-relative on a lat/lon grid) at ~1,900 points with wind over 5 m/s.

  python tests/rotation.py

Pass: median direction error under 12° and median bias under 6° in both the West and the East.
Measured 2026-10-11: rotated 6.1° (bias +2.9° W, +0.4° E); not rotated 12.5° (+18.1° W, -14.1° E).
"""
import datetime as dt
import pathlib
import sys

import eccodes
import numpy as np
from scipy.ndimage import map_coordinates

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from wx import ecmwf, fetch, hrrr  # noqa: E402


def dec(m, ll=False):
    h = eccodes.codes_new_from_message(m)
    out = [eccodes.codes_get_values(h)]
    if ll:
        out += [eccodes.codes_get_array(h, "latitudes"), eccodes.codes_get_array(h, "longitudes")]
    eccodes.codes_release(h)
    return out


def main():
    er = ecmwf.newest_run()
    valid = er + dt.timedelta(hours=24)                      # a time both models cover
    run = valid - dt.timedelta(hours=2)
    while not hrrr.has(run, 2):
        run -= dt.timedelta(hours=1)
    f = int((valid - run).total_seconds() // 3600)
    u = hrrr.url(run, f)
    idx = fetch.noaa_index(u + ".idx")
    ug, lat, lon = dec(fetch.noaa_message(u, idx, hrrr.SEL["u"]), True)
    vg, = dec(fetch.noaa_message(u, idx, hrrr.SEL["v"]))
    lon = np.where(lon > 180, lon - 360, lon)
    k = np.arange(0, ug.size, 997)
    ug, vg, lat, lon = ug[k], vg[k], lat[k], lon[k]
    ei, eu = fetch.ecmwf_index(ecmwf.idx_url(er, 24)), ecmwf.url(er, 24)
    U, m = ecmwf._values(fetch.ecmwf_message(eu, ei, "10u"))
    V, _ = ecmwf._values(fetch.ecmwf_message(eu, ei, "10v"))
    j = (lat - m["lat0"]) / m["dj"] if m["jpos"] else (m["lat0"] - lat) / m["dj"]
    i = ((lon - m["lon0"]) % 360) / m["di"]
    ue, ve = map_coordinates(U, [j, i], order=1), map_coordinates(V, [j, i], order=1)
    d = lambda a, b: (np.degrees(np.arctan2(-a, -b)) + 360) % 360
    ang = np.sin(np.radians(38.5)) * np.radians(lon + 97.5)          # same formula as wx/hrrr.py
    ur, vr = np.cos(ang) * ug + np.sin(ang) * vg, -np.sin(ang) * ug + np.cos(ang) * vg
    diff = (d(ur, vr) - d(ue, ve) + 180) % 360 - 180
    ok = np.hypot(ue, ve) > 5
    w, e = ok & (lon < -110), ok & (lon > -85)
    med, bw, be = np.median(np.abs(diff[ok])), np.median(diff[w]), np.median(diff[e])
    good = med < 12 and abs(bw) < 6 and abs(be) < 6
    print(f"HRRR {run:%Y%m%d%H} +{f}h vs ECMWF {er:%Y%m%d%H} +24h: median |err| {med:.1f}°, bias West {bw:+.1f}°, East {be:+.1f}°  {'PASS' if good else 'FAIL'}")
    sys.exit(0 if good else 1)


if __name__ == "__main__":
    main()
