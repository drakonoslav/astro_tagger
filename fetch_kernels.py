"""
fetch_kernels.py — download JPL planetary SPK kernels into kernel_store/, then index them.

Usage:
    python fetch_kernels.py                 # de440s.bsp only (~32 MB, 1849-2150)
    python fetch_kernels.py de440s de421    # several
Known names: de440s, de440 (1550-2650, ~115 MB), de421 (1900-2050, ~17 MB)

If a URL 404s (NAIF occasionally reorganizes), download the .bsp by hand from
https://naif.jpl.nasa.gov/pub/naif/generic_kernels/spk/planets/ into kernel_store/
and run build_kernel_hashes.py yourself.
"""
import os, sys, urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
STORE_DIR = os.path.join(ROOT, "kernel_store")
BASE = "https://naif.jpl.nasa.gov/pub/naif/generic_kernels/spk/planets/"
URLS = {
    "de440s": BASE + "de440s.bsp",
    "de440":  BASE + "de440.bsp",
    "de421":  BASE + "a_old_versions/de421.bsp",
}


def fetch(name):
    if name not in URLS:
        print(f"Unknown kernel '{name}'. Known: {', '.join(URLS)}")
        sys.exit(1)
    dest = os.path.join(STORE_DIR, f"{name}.bsp")
    if os.path.isfile(dest):
        print(f"{name}.bsp already present, skipping")
        return
    print(f"Downloading {URLS[name]}")
    tmp = dest + ".part"

    def hook(blocks, bs, total):
        if total > 0:
            print(f"\r  {min(100, blocks * bs * 100 // total)}%", end="", flush=True)

    urllib.request.urlretrieve(URLS[name], tmp, hook)
    os.replace(tmp, dest)
    print(f"\n  saved {dest}")


def main():
    os.makedirs(STORE_DIR, exist_ok=True)
    for n in (sys.argv[1:] or ["de440s"]):
        fetch(n.lower().replace(".bsp", ""))
    import build_kernel_hashes
    build_kernel_hashes.main()


if __name__ == "__main__":
    main()
