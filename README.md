# astro_tagger

**Stamp any file with where it was in the solar system when it was made, and bind that record to the file's exact contents.**

A small Python tool that turns "this photo is from about 1978" into a durable, reproducible record: the file's SHA-256, the timestamp and where it came from, an observer position and velocity computed from a named JPL ephemeris, and the SHA-256 of the exact ephemeris file used. Files are never modified. Everything lands in a sidecar next to them.

## What it's good for

- **Archival provenance that still makes sense in 50 years.** Calendars, time zones and file systems change. A barycentric position, TDB seconds since J2000 and a hashed ephemeris don't.
- **Reproducibility.** Each sidecar names the kernel and pins its SHA-256. Anyone with the same kernel can recompute the numbers and check them.
- **Recovering "when was this made?" for messy media.** It prefers EXIF capture time, then PDF metadata, then a date in the filename, then file-system times, and the sidecar records which one it used and whether a time zone had to be assumed. `--utc` overrides it, which is handy for scans of old material.
- **Non-destructive tagging.** Originals are untouched. You get `<file>.astro.json` and, with `--label`, a human-readable `<file>.label.txt`.
- **Multi-agent or mission-style state logs.** `astro-tagger state` appends role-aware records (central site, remote base, expedition vessel) to daily JSONL logs, and `--agent` moves the observer for both commands. It suits simulations, worldbuilding, and anything that needs a consistent "where is everyone, in which frame" record.

## What it is not

- **Not a trusted timestamp.** A timestamp is only as good as its source. EXIF and file-system times can be wrong or edited. The file hash ties a sidecar to a file's contents, but anyone can regenerate a sidecar. For proof of time you can defend, add an external timestamping authority.
- **One Earth site per run.** Every file in a run gets the same site (from config, the agent, or `--lat/--lon/--alt`), not per-file GPS.
- **Non-Earth sites are approximated.** A base on Mars is placed at its body's center (or system barycenter where the kernel has only that). The site's lat/lon is recorded but not applied, and the record says so.
- **No spacecraft trajectories yet.** An expedition vessel has no real position source. It only runs with `--allow-placeholder`, and the record is marked as a placeholder.
- **Coverage depends on your kernels.** A date outside every kernel's range is skipped with a clear message.

## Quick start

Requires Python 3.9+.

```bash
pip install -r requirements.txt
cp config/config.example.json config/config.json     # Windows: copy config\config.example.json config\config.json
# edit config/config.json: set your site's lat_deg, lon_deg, alt_m
python -m astro_tagger kernels fetch                  # downloads de440s.bsp (~32 MB) and indexes it
python -m astro_tagger check                          # should print all OK
```

Optional: `pip install -e .` gives you a plain `astro-tagger` command in place of `python -m astro_tagger`.

## Commands

```bash
# tag files (globs are expanded by the tool, so quote them)
astro-tagger tag photo.jpg --label
astro-tagger tag "media/*.jpg" --policy modern
astro-tagger tag clip.mov --utc 1978-06-12T15:30:00Z --label     # manual timestamp
astro-tagger tag photo.jpg --agent MarsBase-Alpha                 # observer moves with the agent

# log agent states to logs/states-YYYY-MM-DD.jsonl
astro-tagger state --agent CENTRAL
astro-tagger state 1978-06-12T15:30:00Z --policy legacy --agent Base-Planetoid
astro-tagger state --agent CENTRAL --fps 10 --frames 100          # burst
astro-tagger state --agent Voyager-2 --allow-placeholder --mission-id VOY-TEST --mission-phase transit

# kernels and setup
astro-tagger kernels fetch [de440s de440 de421]
astro-tagger kernels index      # after adding a .bsp by hand
astro-tagger kernels list
astro-tagger check
```

Site precedence, highest first: `--lat/--lon/--alt` > the agent's `site` in `config/agents.json` > `config/config.json`.

## How `--agent` places the observer

| Agent role | Home body | Observer position | `method` in the record |
|---|---|---|---|
| `CENTRAL` | Earth | Your Earth site, full topocentric | `earth_topocenter` |
| `REMOTE_BASE` | Earth | The agent's own Earth site, full topocentric | `earth_topocenter` |
| `REMOTE_BASE` | another body | The body's center | `body_center` |
| `REMOTE_BASE` | Mars, outer planets, Pluto | The body's system barycenter (kernels lack the center) | `system_barycenter` |
| `EXPEDITION_VESSEL` | any | Earth-site placeholder, only with `--allow-placeholder` | `placeholder_earth_site` |

An unknown `--agent` is an error, not a silent fallback.

## What a record contains

Both `tag` (inside the sidecar) and `state` (in the log) use the same `state/v2` record. Illustrative and abbreviated:

```json
{
  "type": "state/v2",
  "id": "CENTRAL",
  "time": { "utc": "1978-06-12T15:30:00Z", "tdb_s": -0.0 },
  "state": { "frame": "BCRS", "origin": "SSB", "axes": "ICRS", "time_scale": "TDB",
             "r_m": [0, 0, 0], "v_m_s": [0, 0, 0] },
  "method": "earth_topocenter",
  "site_offset_applied": true,
  "observer_is_placeholder": false,
  "ephemeris": "JPL DE440s",
  "ephemeris_sha256": "...",
  "policy": "modern",
  "agent": { "id": "CENTRAL", "role": "CENTRAL", "home_body": "EARTH", "home_star": "SUN", "travel_mode": null },
  "planetary": { "body": "EARTH", "body_fixed_frame": "ITRS", "geodetic_datum": "WGS84",
                 "latlonh": { "lat_deg": 0.0, "lon_deg": 0.0, "h_m": 0.0 },
                 "local_enu": { "origin_name": "MySite", "origin_latlonh": { "lat_deg": 0.0, "lon_deg": 0.0, "h_m": 0.0 } } },
  "frames_present": ["BCRS", "ITRS", "Local_ENU"]
}
```

A sidecar wraps it with the file's name, SHA-256, size and MIME type, and a `timestamp` block giving the source (`exif`, `pdf`, `filename`, `filesystem`, or `override`) and whether the time zone was assumed to be UTC.

Frame conventions: **BCRS** here means origin at the solar-system barycenter, ICRS axes, TDB time. **ITRS** is the Earth-fixed frame, with coordinates on the **WGS84** datum. Body-fixed frames of other bodies use SPICE names such as `IAU_MARS`. `frames_present` lists only frames the record actually carries data for.

## Ephemeris policies

Defined in `kernels/index.json` and editable. Each policy is an ordered list of kernel files, and the first one covering the date wins.

| Policy | Default kernels | Notes |
|---|---|---|
| `modern` | `de440s.bsp`, then `de440.bsp` | de440s covers 1849 to 2150 |
| `longspan` | `de440.bsp` | covers 1550 to 2650 (~120 MB) |
| `legacy` | `de421.bsp` | covers 1900 to 2050 |
| `closest` | any indexed kernel | built in; picks the covering kernel whose midpoint is nearest the date |

Each kernel's SHA-256 is checked against `kernels/index.json` the first time it is used. A swapped or corrupted kernel is refused.

The kernels are **not** in this repo. `astro-tagger kernels fetch` downloads them from NASA JPL NAIF, or place `.bsp` files in `kernels/` and run `astro-tagger kernels index`. Commit the resulting `kernels/index.json`: it records which kernel versions your records were made with.

## Layout

```
astro_tagger/         the package
  cli.py              command-line entry point
  state.py            compute_state(): the one function both commands use
  ephemeris.py        kernel selection, hash check, loading
  timestamps.py       EXIF / PDF / filename / file-system time
  tag.py  statelog.py the `tag` and `state` commands
  kernels.py  check.py
  config.py  frames.py  paths.py  errors.py  hashing.py
config/               config.example.json, agents.json (config.json is yours, not committed)
kernels/              index.json (committed) + *.bsp (not committed)
logs/                 state logs (created on demand, not committed)
tests/
```

The tool's home directory is the repo root when run from a checkout. Set `ASTRO_TAGGER_HOME` to use another location (an installed copy defaults to `~/.astro_tagger`).

## Development

```bash
python -m unittest discover -s tests -t .
```

The tests use a stub Skyfield so they run without downloading kernels. They cover this project's logic (agents, site precedence, record contents, timestamps, CLI behavior), not the accuracy of real ephemeris output. Run `astro-tagger check` for a live end-to-end test against your real kernels.

## Status

A small, finished personal tool. Known gaps: sphere-of-influence logic, body-fixed site positions on other bodies, spacecraft trajectories, and external timestamp anchoring.

## Credits

Built on [Skyfield](https://rhodesmill.org/skyfield/) and the JPL DE planetary ephemerides from NASA JPL's NAIF.

## License

MIT. See [LICENSE.md](LICENSE.md).
