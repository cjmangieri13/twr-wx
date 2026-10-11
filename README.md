# twr-wx

Weather-map data for [rhearunswild.com](https://rhearunswild.com): forecast fields from NOAA's HRRR
(3 km, lower 48, to 48 h) and ECMWF IFS open data (0.25°, to 7 days), reprojected to Web Mercator and
packed into PNG "data textures" the site's map colors and animates in the browser.

Public on purpose: GitHub Actions minutes are free for public repos, and nothing here is private.
It holds code and public weather data only.

## Privacy
The output box is fixed (lon -135 to -55, lat 20 to 55) and never follows the trip. A box that
tracked the route would publish where we are heading. Nothing in this repo reads the itinerary.

## What runs
| Workflow | When | Does |
|---|---|---|
| `hrrr` | every hour at :17 | newest HRRR run 0-18 h, plus 19-48 h from the newest 00/06/12/18z run |
| `ecmwf` | every hour at :45 | the newest complete 00z/12z run, 0-168 h; exits in seconds if unchanged |
| `keepalive` | Mondays | commits a heartbeat if the repo has been quiet for 45 days (GitHub disables schedules after 60) |

Each run takes about 1.5 minutes. The output goes to the R2 bucket `twr-public` under `wx/`, served at
`https://live.rhearunswild.com/wx/<model>/latest.json`.

## Output
`wx/<model>/latest.json` is written last, after every texture. It lists the box, the field encodings
and every hour with its run, so a viewer never sees a half-uploaded run. Textures are at
`wx/<model>/<run>/<field>/<fff>.png` (2048 px wide) and `<fff>.h.png` (1024 px). Runs referenced
by the new or the previous `latest.json` are kept; older ones are deleted.

| Field | HRRR | ECMWF | Encoding |
|---|---|---|---|
| temp (°F) | ✓ | ✓ | rg16, 0.1 °F |
| wind (u, v m/s) | ✓ | ✓ | uv8, ±50 m/s |
| gust (mph) | ✓ | ✓ | rg16 |
| cloud (% total, low, high) | ✓ | total only | cloud8 |
| precip (in/h) | ✓ | ✓ (from accumulated tp) | rg16 |
| refc (dBZ, forecast radar) | ✓ | | rg16 |
| cape (J/kg) | ✓ | ✓ (most-unstable CAPE) | rg16 |
| ltng (lightning threat) | ✓ | | rg16 |

Encodings are documented in `wx/encode.py` and copied into each `latest.json`.

**Known gap:** temperatures are the raw model values. Open-Meteo corrects for the difference between
model terrain and real elevation, so in mountain valleys we can read a few degrees colder than it
does (Reno, 2026-10-11: ECMWF 4 °F colder).

## Run it locally
```
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m wx hrrr --local out --max-steps 3      # writes out/wx/hrrr/...
.venv/bin/python tests/geometry.py out                      # textures vs raw HRRR at 300 random pixels
.venv/bin/python tests/rotation.py                          # HRRR wind rotation vs ECMWF
.venv/bin/python tests/spotcheck.py out hrrr                # 8 cities vs Open-Meteo
```

## Setup (once)
Repository secrets (Settings > Secrets and variables > Actions): `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`,
`R2_SECRET_ACCESS_KEY`. The last two come from an R2 API token with Object Read & Write on
`twr-public` only.

Attribution: HRRR, NOAA/NCEP via NOAA Open Data on AWS. ECMWF IFS open data, CC BY 4.0.
