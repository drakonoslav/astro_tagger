"""
kernel_store.py — ephemeris loader used by tag_media.py and write_state_real.py

Contract (what the other scripts expect):
    skyfield_load_ephemeris(utc_dt, policy="modern") -> (ts, eph, eph_label, ephem_sha256)

    ts          Skyfield timescale
    eph         Skyfield SpiceKernel (supports eph["earth"], eph["mars"], ...)
    eph_label   human-readable name, e.g. "JPL DE440s"
    ephem_sha   SHA-256 of the .bsp actually used (verified against index.json)

Raises RuntimeError("No SPK ephemeris covers JD ...") when nothing covers the date;
write_state_real.py looks for that exact phrase.

Data lives in ./kernel_store/ (the .bsp files plus index.json, which is built by
build_kernel_hashes.py). Policies are defined in index.json and are editable:
    - a named policy is an ordered list of kernel filenames; first one that covers wins
    - "closest" is built in: among all indexed kernels that cover the date, pick the
      one whose coverage midpoint is nearest the date
"""
import os, json, hashlib
from datetime import timezone

from skyfield.api import load
from skyfield.jpllib import SpiceKernel

ROOT = os.path.dirname(os.path.abspath(__file__))
STORE_DIR = os.path.join(ROOT, "kernel_store")
INDEX_PATH = os.path.join(STORE_DIR, "index.json")

_ts = None
_kernels = {}   # filename -> SpiceKernel (opened and hash-verified once per process)


def _timescale():
    global _ts
    if _ts is None:
        _ts = load.timescale()   # built-in tables; no network
    return _ts


def _read_index() -> dict:
    try:
        with open(INDEX_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        raise RuntimeError(
            f"Kernel index not found: {INDEX_PATH}. "
            "Run fetch_kernels.py (or drop .bsp files in kernel_store/) then build_kernel_hashes.py."
        )


def _sha256(path: str, chunk: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def _label(fname: str) -> str:
    stem = os.path.splitext(fname)[0]          # de440s -> "JPL DE440s"
    return f"JPL {stem[:2].upper()}{stem[2:]}"


def _open(fname: str, entry: dict):
    if fname in _kernels:
        return _kernels[fname]
    path = os.path.join(STORE_DIR, fname)
    if not os.path.isfile(path):
        raise RuntimeError(f"Kernel listed in index but missing on disk: {path}")
    actual = _sha256(path)
    if actual != entry["sha256"]:
        raise RuntimeError(
            f"Hash mismatch for {fname}: index says {entry['sha256'][:16]}…, file is {actual[:16]}…. "
            "If you replaced the kernel on purpose, re-run build_kernel_hashes.py."
        )
    _kernels[fname] = SpiceKernel(path)
    return _kernels[fname]


def _choose(index: dict, policy: str, jd_tdb: float) -> str:
    kernels = index.get("kernels", {})
    if not kernels:
        raise RuntimeError(
            "kernel_store/index.json lists no kernels. "
            "Run fetch_kernels.py then build_kernel_hashes.py."
        )

    if policy == "closest":
        names = list(kernels)
    else:
        policies = index.get("policies", {})
        if policy not in policies:
            raise RuntimeError(f"Unknown policy '{policy}'. Defined: {sorted(policies)} + 'closest'")
        names = [n for n in policies[policy] if n in kernels]
        if not names:
            raise RuntimeError(
                f"Policy '{policy}' wants {policies[policy]} but none are indexed. "
                "Download one and re-run build_kernel_hashes.py, or edit the policy in index.json."
            )

    covering = [n for n in names if kernels[n]["start_jd"] <= jd_tdb <= kernels[n]["end_jd"]]
    if not covering:
        raise RuntimeError(f"No SPK ephemeris covers JD {jd_tdb:.3f} under policy '{policy}'")

    if policy == "closest":
        mid = lambda n: 0.5 * (kernels[n]["start_jd"] + kernels[n]["end_jd"])
        return min(covering, key=lambda n: abs(mid(n) - jd_tdb))
    return covering[0]


def skyfield_load_ephemeris(utc_dt, policy: str = "modern"):
    if utc_dt.tzinfo is None:
        utc_dt = utc_dt.replace(tzinfo=timezone.utc)
    ts = _timescale()
    t = ts.from_datetime(utc_dt)

    index = _read_index()
    fname = _choose(index, policy, float(t.tdb))
    eph = _open(fname, index["kernels"][fname])
    return ts, eph, _label(fname), index["kernels"][fname]["sha256"]
