"""
check_setup.py — verify everything tag_media.py / write_state_real.py need is in place.
Usage:  python check_setup.py
"""
import os, sys, json, math, importlib
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.abspath(__file__))
bad = 0


def line(kind, msg):
    global bad
    if kind == "FAIL":
        bad += 1
    print(f"[{kind:>4}] {msg}")


def has(mod):
    try:
        importlib.import_module(mod)
        return True
    except Exception:
        return False


# python packages
for mod, required in (("skyfield", True), ("numpy", True), ("PIL", False), ("pypdf", False)):
    if has(mod):
        line("OK", f"import {mod}")
    else:
        line("FAIL" if required else "WARN",
             f"{mod} missing" + ("" if required else " (EXIF/PDF timestamps will silently fall back)"))

# files / folders
for rel in ("tag_media.py", "write_state_real.py", "kernel_store.py",
            "meta/config.json", "meta/agents.json", "kernel_store/index.json"):
    line("OK" if os.path.isfile(os.path.join(ROOT, rel)) else "FAIL", rel)
for rel in ("media", "logs"):
    line("OK" if os.path.isdir(os.path.join(ROOT, rel)) else "WARN", rel + "/")

# config keys
try:
    with open(os.path.join(ROOT, "meta", "config.json"), encoding="utf-8") as f:
        site = json.load(f).get("site", {})
    for k in ("lat_deg", "lon_deg", "alt_m", "h_m"):
        line("OK" if k in site else "FAIL", f"config site.{k}")
    if site.get("alt_m") != site.get("h_m"):
        line("WARN", "alt_m and h_m differ; tag_media uses alt_m, write_state_real uses h_m")
except Exception as e:
    line("FAIL", f"config.json unreadable: {e}")

# kernels + live test
try:
    import numpy as np
    from kernel_store import skyfield_load_ephemeris
    now = datetime.now(timezone.utc)
    ts, eph, label, sha = skyfield_load_ephemeris(now, policy="modern")
    t = ts.from_datetime(now)
    r = np.array(eph["earth"].at(t).position.km) * 1000.0
    mag = math.sqrt(float((r * r).sum()))
    ok = 1.4e11 < mag < 1.6e11
    line("OK" if ok else "FAIL", f"{label}: Earth is {mag:.3e} m from the solar-system barycenter (sha {sha[:12]}…)")
except Exception as e:
    line("FAIL", f"ephemeris test: {e}")

print("\nAll good." if bad == 0 else f"\n{bad} problem(s) to fix.")
sys.exit(1 if bad else 0)
