"""
build_kernel_hashes.py — scan kernel_store/*.bsp and (re)write kernel_store/index.json

Records each kernel's SHA-256 and TDB Julian-date coverage. Existing 'policies' in the
index are preserved; a default set is added if there are none.

Usage:  python build_kernel_hashes.py
"""
import os, sys, json, hashlib

from skyfield.jpllib import SpiceKernel

ROOT = os.path.dirname(os.path.abspath(__file__))
STORE_DIR = os.path.join(ROOT, "kernel_store")
INDEX_PATH = os.path.join(STORE_DIR, "index.json")

DEFAULT_POLICIES = {
    "modern":   ["de440s.bsp", "de440.bsp"],
    "legacy":   ["de421.bsp"],
    "longspan": ["de440.bsp"],
}


def sha256_file(path, chunk=1024 * 1024):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def coverage_jd(path):
    k = SpiceKernel(path)
    segs = k.spk.segments
    start = max(s.start_jd for s in segs)   # intersection across segments = conservative
    end = min(s.end_jd for s in segs)
    try:
        k.close()
    except Exception:
        pass
    return float(start), float(end)


def main():
    os.makedirs(STORE_DIR, exist_ok=True)
    files = sorted(f for f in os.listdir(STORE_DIR) if f.lower().endswith(".bsp"))
    if not files:
        print(f"No .bsp files in {STORE_DIR}. Run fetch_kernels.py first.")
        sys.exit(1)

    try:
        with open(INDEX_PATH, "r", encoding="utf-8") as f:
            index = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        index = {}

    index["schema"] = "kernel_index/v1"
    index.setdefault("policies", DEFAULT_POLICIES)
    index["kernels"] = {}

    for fname in files:
        path = os.path.join(STORE_DIR, fname)
        print(f"Hashing {fname} ...")
        start, end = coverage_jd(path)
        index["kernels"][fname] = {
            "sha256": sha256_file(path),
            "bytes": os.path.getsize(path),
            "start_jd": start,
            "end_jd": end,
        }
        print(f"  JD {start:.1f} .. {end:.1f}")

    with open(INDEX_PATH, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2)
    print(f"Wrote {INDEX_PATH} ({len(files)} kernel(s))")


if __name__ == "__main__":
    main()
