"""Build and publish the weather-map textures.

  python -m wx hrrr  [--local DIR] [--max-steps N] [--force]
  python -m wx ecmwf [--local DIR] [--max-steps N] [--force]

Without --local it writes to R2 (see store.R2). Each model keeps its own wx/<model>/latest.json,
written LAST, so a viewer never sees a half-uploaded run. Runs referenced by the new or the
previous latest.json are kept; older ones are deleted.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import json
import os
import sys
import time

import numpy as np

from . import ecmwf, encode, grid, hrrr
from . import store as st

W = [grid.SIZES["full"], grid.SIZES["half"]]
SUFFIX = {grid.SIZES["full"]: "", grid.SIZES["half"]: ".h"}
NEEDS = {"wind": ["u", "v"]}


def tkey(model: str, run: str, field: str, f: int, w: int) -> str:
    return f"wx/{model}/{run}/{field}/{f:03d}{SUFFIX[w]}.png"


def iso(t: dt.datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def rid(t: dt.datetime) -> str:
    return t.strftime("%Y%m%d%H")


def upload(S, model: str, run: str, f: int, by_w: dict, fields: list[str]) -> list[str]:
    done = []
    for field in fields:
        if not all(n in by_w[W[0]] for n in NEEDS.get(field, [field])):
            continue
        for w in W:
            S.put(tkey(model, run, field, f, w), encode.encode(field, by_w[w]), "image/png")
        done.append(field)
    return done


def finish(S, model: str, mod, prev: dict | None, hours: list[dict], extra: dict):
    hours = sorted({h["t"]: h for h in hours}.values(), key=lambda h: h["t"])
    man = {
        "model": model, "name": mod.NAME, "attribution": mod.ATTRIBUTION, "generated": iso(dt.datetime.utcnow()),
        "box": grid.box(), "fields": {k: encode.FIELDS[k] for k in mod.FIELDS},
        "path": "wx/" + model + "/{run}/{field}/{f}{size}.png", "sizes": {"full": "", "half": ".h"},
        "hours": hours, **extra,
    }
    S.put(f"wx/{model}/latest.json", json.dumps(man, separators=(",", ":")).encode(), "application/json", st.SHORT)
    keep = {h["run"] for h in hours} | {h["run"] for h in (prev or {}).get("hours", [])}
    for r in S.runs(f"wx/{model}"):
        if r not in keep:
            S.delete_prefix(f"wx/{model}/{r}")
            print(f"  deleted old run {r}")
    print(f"{model}: latest.json has {len(hours)} hours, {hours[0]['t']} to {hours[-1]['t']}")


def pool(jobs, fn, workers=4):
    ok, bad = [], []
    with cf.ThreadPoolExecutor(workers) as ex:
        futs = {ex.submit(fn, j): j for j in jobs}
        for fu in cf.as_completed(futs):
            try:
                r = fu.result()
                if r:
                    ok.append(r)
            except Exception as e:                 # one bad hour shouldn't sink the run
                bad.append((futs[fu], repr(e)[:200]))
    for j, e in bad:
        print(f"  FAILED {j}: {e}", file=sys.stderr)
    if jobs and len(bad) > len(jobs) * 0.2:
        raise SystemExit(f"{len(bad)} of {len(jobs)} hours failed; latest.json left as it was")
    return ok


def run_hrrr(S, a):
    newest, syn = hrrr.newest_runs()
    prev = S.get_json("wx/hrrr/latest.json")
    nid, sid = rid(newest), syn and rid(syn)
    if prev and prev.get("newest") == nid and prev.get("syn") == sid and not a.force:
        print(f"hrrr: nothing new (newest {nid}, 48 h run {sid})")
        return
    jobs = [(newest, f) for f in range(19)]
    reuse = []
    if syn:
        first = int((newest + dt.timedelta(hours=19) - syn).total_seconds() // 3600)
        reuse = [h for h in (prev or {}).get("hours", []) if h["run"] == sid and h["f"] >= first]
        have = {h["f"] for h in reuse}
        jobs += [(syn, f) for f in range(max(first, 0), 49) if f not in have]
    if a.max_steps:
        jobs = jobs[: a.max_steps]
    print(f"hrrr: newest {nid}, 48 h run {sid}; {len(jobs)} hours to build, {len(reuse)} reused")

    def one(job):
        run, f = job
        t0 = time.time()
        by_w = hrrr.step(run, f, W)
        done = upload(S, "hrrr", rid(run), f, by_w, hrrr.FIELDS)
        print(f"  {rid(run)} f{f:02d}: {len(done)} fields in {time.time() - t0:.1f}s")
        return {"t": iso(run + dt.timedelta(hours=f)), "run": rid(run), "f": f, "fields": done}

    built = pool(jobs, one)
    finish(S, "hrrr", hrrr, prev, reuse + built, {"newest": nid, "syn": sid})


def run_ecmwf(S, a):
    run = ecmwf.newest_run()
    prev = S.get_json("wx/ecmwf/latest.json")
    r = rid(run)
    if prev and prev.get("run") == r and not a.force:
        print(f"ecmwf: nothing new (run {r})")
        return
    steps = ecmwf.STEPS[: a.max_steps] if a.max_steps else ecmwf.STEPS
    print(f"ecmwf: run {r}; {len(steps)} steps to build")

    def one(s):
        t0 = time.time()
        by_w = ecmwf.step(run, s, W)
        i = ecmwf.STEPS.index(s)
        if i > 0:                                   # precipitation = this step's total minus the last one's
            ps = ecmwf.STEPS[i - 1]
            prev_tp = ecmwf.tp_only(run, ps, W)
            for w in W:
                rate = ecmwf.precip_rate(by_w[w].get("tp"), prev_tp.get(w), s - ps) if "tp" in by_w[w] else None
                if rate is not None:
                    by_w[w]["precip"] = rate
        done = upload(S, "ecmwf", r, s, by_w, ecmwf.FIELDS)
        print(f"  {r} +{s:03d}h: {len(done)} fields in {time.time() - t0:.1f}s")
        return {"t": iso(run + dt.timedelta(hours=s)), "run": r, "f": s, "fields": done}

    built = pool(steps, one)
    finish(S, "ecmwf", ecmwf, prev, built, {"run": r})


def main():
    ap = argparse.ArgumentParser(prog="python -m wx")
    ap.add_argument("model", choices=["hrrr", "ecmwf"])
    ap.add_argument("--local", help="write to this folder instead of R2")
    ap.add_argument("--max-steps", type=int, default=0, help="testing: only the first N hours")
    ap.add_argument("--force", action="store_true", help="rebuild even if latest.json already has this run")
    a = ap.parse_args()
    if not a.local and not all(os.environ.get(k) for k in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY")):
        # before setup, don't fail (and email) every hour; once live, the site's Worker alarms on stale data
        print("R2 secrets not set (Settings > Secrets and variables > Actions); nothing published")
        return
    S = st.open_store(a.local)
    t0 = time.time()
    (run_hrrr if a.model == "hrrr" else run_ecmwf)(S, a)
    print(f"done in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
