# astro_tagger

**Stamp any file with where it was in the solar system when it was made, and bind that record to the file's exact contents.**

A small Python toolkit that turns "this photo is from about 1978" into a durable, reproducible record: the file's SHA-256, the timestamp and how it was chosen, an observer position and velocity computed from a named JPL ephemeris, and the SHA-256 of the exact ephemeris file used. Files are never modified. Everything lands in a sidecar next to them.

In 2076 nobody will trust “taken 12 June 1978.” They might still trust: these bits, this kernel hash, this TDB, this BCRS state.

1.  It’s a receipt, not a notary. The math is reproducible; the time source is only as good as EXIF / filename / --utc. Say that in the same breath as the hook. That’s what makes it hardcore instead of marketing.
2.  The capsule is the sidecar + the kernel hash, not the original file. Originals stay untouched. The durable object is <file>.astro.json.

## What it's good for

- **Archival provenance that still makes sense in 50 years.** Calendars, time zones and file systems change. Barycentric position, TDB seconds since J2000 and a hashed ephemeris don't.
- **Reproducibility.** The sidecar names the kernel and pins its SHA-256. Anyone with the same kernel can recompute the numbers and check them.
- **Recovering "when was this made?" for messy media.** For each file it picks the earliest plausible timestamp from EXIF, then PDF metadata, then the date in the filename, then file-system times. `--utc` overrides it manually, which is handy for scans of old material.
- **Non-destructive tagging.** Originals are untouched. You get `<file>.astro.json` and, with `--label`, a human-readable `<file>.label.txt`.
- **Multi-agent or mission-style state logs.** `write_state_real.py` appends role-aware state records (central site, remote base, expedition vessel) to daily JSONL logs. It suits simulations, worldbuilding, and anything that needs a consistent "where is everyone, and in which frame" record.

## What it is not

Be honest with yourself and any reader about these limits:

- **Not a trusted timestamp.** The timestamp is only as good as its source. EXIF and file-system times can be wrong or edited, and time-zone-less times are assumed UTC. The file hash ties a sidecar to a file's contents, but anyone can regenerate a sidecar. For legal-grade proof of time, add an external timestamping authority.
- **One configured site.** Every file is stamped with the location in `meta/config.json`, not per-file GPS.
- **Parts of the state logger are stubs.** Sphere-of-influence logic, the expedition-vessel path (which uses an Earth placeholder), and "runner" frames are breadcrumbs for future work. A remote base on another body is approximated at the body's center.
- **Coverage depends on the kernel you have.** A date outside a kernel's range fails with "No SPK ephemeris covers JD ...".

## Quick start

Requires Python 3.9+.

```bash
pip install -r requirements.txt
cp meta/config.example.json meta/config.json     # Windows: copy meta\config.example.json meta\config.json
# edit meta/config.json with your site's lat/lon/altitude
python fetch_kernels.py                          # downloads de440s.bsp (~32 MB) and indexes it
python check_setup.py                            # should print all OK
```

Tag some files:

```bash
python tag_media.py media/photo.jpg --policy modern --label
python tag_media.py "media/*.jpg" --policy modern --label
python tag_media.py media/clip.mov --utc 1978-06-12T15:30:00Z --label   # manual timestamp
python tag_media.py media/photo.jpg --agent MarsBase-Alpha --label      # stamp an agent id + role
```

Log agent states:

```bash
python write_state_real.py --policy modern --agent CENTRAL
python write_state_real.py 1978-06-12T15:30:00Z --policy legacy --agent Base-Planetoid
python write_state_real.py --agent Voyager-2 --mission_id VOY-TEST --mission_phase transit
python write_state_real.py --agent CENTRAL --fps 10 --frames 100        # burst of records
```

## What a sidecar contains

Illustrative and abbreviated, with placeholder values:

```json
{
  "file": { "path": "media/photo.jpg", "sha256": "…", "mime": "image/jpeg",
            "original_datetime": "1978-06-12T15:30:00Z" },
  "provenance": { "site_config": { "lat_deg": 0.0, "lon_deg": 0.0, "alt_m": 0.0, "agent_id": "Agent-LocalSite" },
                  "kernel_store_index": "kernel_store/index.json" },
  "state": {
    "time": { "utc": "1978-06-12T15:30:00Z", "tdb_s": -0.0 },
    "state": { "frame": "BCRS", "r_m": [0, 0, 0], "v_m_s": [0, 0, 0] },
    "ephemeris": "JPL DE440s",
    "ephemeris_sha256": "…",
    "frames_present": ["ICRS", "BCRS", "GCRS", "ITRF", "Local_ENU"],
    "policy": "modern"
  }
}
```

## Ephemeris policies

Policies live in `kernel_store/index.json` and are editable. Each is an ordered list of kernel files, and the first one that covers the date wins.

| Policy | Default kernels | Notes |
|---|---|---|
| `modern` | `de440s.bsp`, then `de440.bsp` | de440s covers 1849 to 2150 |
| `longspan` | `de440.bsp` | covers 1550 to 2650 (~120 MB) |
| `legacy` | `de421.bsp` | covers 1900 to 2050 |
| `closest` | any indexed kernel | built in; picks the covering kernel whose midpoint is nearest the date |

`kernel_store.py` verifies each kernel's SHA-256 against `index.json` on first use. If a kernel is swapped or corrupted, it refuses to run.

The kernels are **not** in this repo (see `.gitignore`). `fetch_kernels.py` downloads them from NASA JPL NAIF, or you can place `.bsp` files in `kernel_store/` yourself and run `python build_kernel_hashes.py`.

## Layout

```
astro_tagger/
  tag_media.py            tag files with sidecars + labels
  write_state_real.py     role-aware agent state logger -> logs/*.jsonl
  kernel_store.py         ephemeris loader: skyfield_load_ephemeris()
  build_kernel_hashes.py  index + hash kernels in kernel_store/
  fetch_kernels.py        download kernels, then index them
  check_setup.py          verify the whole setup
  meta/
    config.example.json   copy to config.json and edit
    agents.json           agent registry (roles, home bodies, sites)
    soi/                  reserved for future SOI logic
  kernel_store/           .bsp files (not committed) + index.json
  media/                  files to tag
  logs/                   state logs
  extras/detect_markers.py  standalone orange-fiducial detector (needs opencv-python)
```

## Status

Early, personal-scale tool: small, readable, and useful as is. Roadmap ideas: real SOI logic, body-fixed frames for non-Earth bases, per-file sites, and optional external timestamp anchoring.

## Credits

Built on [Skyfield](https://rhodesmill.org/skyfield/) and the JPL DE planetary ephemerides from NASA JPL's NAIF.

## License

Add a `LICENSE` file before publishing (MIT is a common choice).
