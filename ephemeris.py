"""Ephemeris loading: pick a JPL SPK kernel by policy, verify its hash, open it.

Kernels live in kernels/ next to kernels/index.json (built by `astro-tagger kernels index`).
A policy is an ordered list of kernel filenames defined in the index; the first one that
covers the date wins. "closest" is built in: among all indexed kernels that cover the date,
pick the one whose coverage midpoint is nearest.
"""
import json
from datetime import timezone
from typing import Any, NamedTuple

from . import paths
from .errors import KernelError, NoCoverageError
from .hashing import sha256_file


class Ephemeris(NamedTuple):
    ts: Any         # Skyfield timescale
    eph: Any        # Skyfield SpiceKernel (eph["earth"], ...)
    label: str      # e.g. "JPL DE440s"
    sha256: str     # hash of the kernel actually used
    kernel: str     # filename


_ts = None
_kernels: dict = {}   # filename -> opened kernel (hash-verified once per process)


def _timescale():
    global _ts
    if _ts is None:
        from skyfield.api import load
        _ts = load.timescale()   # built-in tables; no network
    return _ts


def read_index() -> dict:
    path = paths.kernel_index_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        raise KernelError(f"Kernel index not found: {path}. Run: astro-tagger kernels fetch")
    except json.JSONDecodeError as e:
        raise KernelError(f"{path} is not valid JSON: {e}")


def kernel_label(fname: str) -> str:
    stem = fname.rsplit(".", 1)[0]          # de440s -> "JPL DE440s"
    return f"JPL {stem[:2].upper()}{stem[2:]}"


def choose_kernel(index: dict, policy: str, jd_tdb: float) -> str:
    kernels = index.get("kernels", {})
    if not kernels:
        raise KernelError("kernels/index.json lists no kernels. Run: astro-tagger kernels fetch")

    if policy == "closest":
        names = list(kernels)
    else:
        policies = index.get("policies", {})
        if policy not in policies:
            raise KernelError(f"Unknown policy '{policy}'. Defined: {sorted(policies)} + 'closest'")
        names = [n for n in policies[policy] if n in kernels]
        if not names:
            raise KernelError(
                f"Policy '{policy}' wants {policies[policy]} but none are indexed. "
                "Fetch one (astro-tagger kernels fetch) or edit the policy in kernels/index.json."
            )

    covering = [n for n in names if kernels[n]["start_jd"] <= jd_tdb <= kernels[n]["end_jd"]]
    if not covering:
        raise NoCoverageError(f"No SPK ephemeris covers JD {jd_tdb:.3f} under policy '{policy}'")

    if policy == "closest":
        def mid(n):
            return 0.5 * (kernels[n]["start_jd"] + kernels[n]["end_jd"])
        return min(covering, key=lambda n: abs(mid(n) - jd_tdb))
    return covering[0]


def _open(fname: str, entry: dict):
    if fname in _kernels:
        return _kernels[fname]
    path = paths.kernels_dir() / fname
    if not path.is_file():
        raise KernelError(f"Kernel listed in index but missing on disk: {path}")
    actual = sha256_file(path)
    if actual != entry["sha256"]:
        raise KernelError(
            f"Hash mismatch for {fname}: index says {entry['sha256'][:16]}..., file is {actual[:16]}.... "
            "If you replaced the kernel on purpose, run: astro-tagger kernels index"
        )
    from skyfield.jpllib import SpiceKernel
    _kernels[fname] = SpiceKernel(str(path))
    return _kernels[fname]


def load_ephemeris(utc_dt, policy: str = "modern") -> Ephemeris:
    if utc_dt.tzinfo is None:
        utc_dt = utc_dt.replace(tzinfo=timezone.utc)
    ts = _timescale()
    t = ts.from_datetime(utc_dt)
    index = read_index()
    fname = choose_kernel(index, policy, float(t.tdb))
    entry = index["kernels"][fname]
    return Ephemeris(ts, _open(fname, entry), kernel_label(fname), entry["sha256"], fname)
