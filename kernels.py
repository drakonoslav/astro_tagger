"""`astro-tagger kernels ...`: fetch JPL SPK kernels and index them (hash + date coverage)."""
import json
import os
import urllib.request

from . import paths
from .errors import KernelError
from .hashing import sha256_file

BASE = "https://naif.jpl.nasa.gov/pub/naif/generic_kernels/spk/planets/"
KNOWN = {
    "de440s": BASE + "de440s.bsp",                      # 1849-2150, ~32 MB
    "de440":  BASE + "de440.bsp",                       # 1550-2650, ~115 MB
    "de421":  BASE + "a_old_versions/de421.bsp",        # 1900-2050, ~17 MB
}
DEFAULT_POLICIES = {
    "modern":   ["de440s.bsp", "de440.bsp"],
    "legacy":   ["de421.bsp"],
    "longspan": ["de440.bsp"],
}


def _coverage_jd(path) -> tuple:
    from skyfield.jpllib import SpiceKernel
    k = SpiceKernel(str(path))
    segs = k.spk.segments
    start = max(s.start_jd for s in segs)      # intersection across segments: conservative
    end = min(s.end_jd for s in segs)
    try:
        k.close()
    except Exception:
        pass
    return float(start), float(end)


def build_index() -> dict:
    kdir = paths.kernels_dir()
    kdir.mkdir(parents=True, exist_ok=True)
    files = sorted(f for f in os.listdir(kdir) if f.lower().endswith(".bsp"))
    if not files:
        raise KernelError(f"No .bsp files in {kdir}. Run: astro-tagger kernels fetch")

    index_path = paths.kernel_index_path()
    try:
        with open(index_path, "r", encoding="utf-8") as f:
            index = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        index = {}
    index["schema"] = "kernel_index/v1"
    index.setdefault("policies", DEFAULT_POLICIES)
    index["kernels"] = {}

    for fname in files:
        path = kdir / fname
        print(f"Indexing {fname} ...")
        start, end = _coverage_jd(path)
        index["kernels"][fname] = {
            "sha256": sha256_file(path),
            "bytes": os.path.getsize(path),
            "start_jd": start,
            "end_jd": end,
        }
        print(f"  JD {start:.1f} .. {end:.1f}")

    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2)
    print(f"Wrote {index_path} ({len(files)} kernel(s))")
    return index


def fetch(name: str) -> None:
    name = name.lower().removesuffix(".bsp")
    if name not in KNOWN:
        raise KernelError(f"Unknown kernel '{name}'. Known: {', '.join(KNOWN)}")
    kdir = paths.kernels_dir()
    kdir.mkdir(parents=True, exist_ok=True)
    dest = kdir / f"{name}.bsp"
    if dest.is_file():
        print(f"{name}.bsp already present, skipping")
        return
    print(f"Downloading {KNOWN[name]}")
    tmp = str(dest) + ".part"

    def hook(blocks, bs, total):
        if total > 0:
            print(f"\r  {min(100, blocks * bs * 100 // total)}%", end="", flush=True)

    try:
        urllib.request.urlretrieve(KNOWN[name], tmp, hook)
    except Exception as e:
        raise KernelError(
            f"Download failed ({e}). Get the file by hand from {BASE} into {kdir}, "
            "then run: astro-tagger kernels index"
        )
    os.replace(tmp, dest)
    print(f"\n  saved {dest}")


def show() -> None:
    from .ephemeris import read_index
    index = read_index()
    print("Policies:")
    for name, kernels in index.get("policies", {}).items():
        print(f"  {name:9s} {kernels}")
    print("Indexed kernels:")
    for fname, e in index.get("kernels", {}).items():
        print(f"  {fname:12s} JD {e['start_jd']:.1f}..{e['end_jd']:.1f}  sha256 {e['sha256'][:16]}...")
    if not index.get("kernels"):
        print("  (none) run: astro-tagger kernels fetch")


def run(args) -> int:
    if args.kernels_cmd == "fetch":
        for n in (args.names or ["de440s"]):
            fetch(n)
        build_index()
    elif args.kernels_cmd == "index":
        build_index()
    else:
        show()
    return 0
