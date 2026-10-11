"""Do our textures put HRRR's values in the right place? Decode the temperature texture at random
pixels and compare with HRRR itself at each pixel's exact lat/lon (eccodes' 4 nearest points,
inverse-distance weighted). This checks projection, resampling, orientation and encoding together.

  python tests/geometry.py out
Pass: median error under 0.3 °F and 95th percentile under 1.5 °F.
"""
import datetime as dt
import json
import pathlib
import sys

import eccodes
import numpy as np
from PIL import Image

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from wx import fetch, grid, hrrr  # noqa: E402


def main(root):
    man = json.loads((pathlib.Path(root) / "wx/hrrr/latest.json").read_text())
    h0 = man["hours"][1]
    F = man["fields"]["temp"]
    img = np.asarray(Image.open(pathlib.Path(root) / man["path"].format(run=h0["run"], field="temp", f=f"{h0['f']:03d}", size=""))).astype(np.int32)
    q = img[..., 0] * 256 + img[..., 1]
    run = dt.datetime.strptime(h0["run"], "%Y%m%d%H")
    u = hrrr.url(run, h0["f"])
    msg = fetch.noaa_message(u, fetch.noaa_index(u + ".idx"), hrrr.SEL["temp"])
    g = eccodes.codes_new_from_message(msg)
    lon, lat = grid.lonlat(img.shape[1])
    rng = np.random.default_rng(7)
    errs = []
    while len(errs) < 300:
        y, x = rng.integers(0, img.shape[0]), rng.integers(0, img.shape[1])
        if q[y, x] == 65535:
            continue
        near = eccodes.codes_grib_find_nearest(g, float(lat[y, x]), float(lon[y, x]), is_lsm=False, npoints=4)
        wts = np.array([1 / max(n["distance"], 1e-3) for n in near])
        ref = (np.array([n["value"] for n in near]) @ wts / wts.sum() - 273.15) * 9 / 5 + 32
        errs.append(abs(F["min"] + q[y, x] * F["step"] - ref))
    e = np.array(errs)
    ok = np.median(e) < 0.3 and np.percentile(e, 95) < 1.5
    print(f"300 random pixels vs raw HRRR: median {np.median(e):.2f} °F, 95th pct {np.percentile(e, 95):.2f} °F, max {e.max():.2f} °F  {'PASS' if ok else 'FAIL'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "out")
