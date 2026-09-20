# Changelog

## 0.2.0

### Changed
- One package with one command: `astro-tagger tag | state | kernels | check` (or `python -m astro_tagger ...`). Replaces `tag_media.py`, `write_state_real.py`, `fetch_kernels.py`, `build_kernel_hashes.py`, `check_setup.py`.
- One shared function, `state.compute_state()`, now produces the state record for both `tag` and `state`. Sidecars and logs can no longer disagree.
- Layout: `meta/` is now `config/`, `kernel_store/` is now `kernels/`, and `kernel_store.py` is now `astro_tagger/ephemeris.py`. All paths come from `paths.py`. `ASTRO_TAGGER_HOME` relocates everything.
- Record schema is `state/v2`, sidecars are `astro_sidecar/v2`. `frame_selection` is replaced by `method`.
- `home_body` is now written `EARTH`, `MARS` (legacy `IAU_MARS` still accepted). Altitude is `alt_m` (`h_m` still accepted).

### Fixed
- **`--agent` now moves the observer** for `tag` as well as `state`. Before, `tag --agent` only stamped an id and role onto an Earth-site record.
- **Frame names.** `ITRF/WGS84` is now frame `ITRS` plus datum `WGS84`. `GCRS` and `ICRS` are no longer listed as present, since the record carries no data in them (`BCRS` already has ICRS axes, now stated explicitly). The invented `IAU_MARS_J2000` and `IAU_MARS/2021` are gone; body-fixed frames use SPICE names like `IAU_MARS`.
- **EXIF capture time was never read.** `DateTimeOriginal` lives in the Exif sub-IFD, which the old code did not look at, so it silently fell through to filename or file-system time.
- PDF dates now honour their time-zone offset.
- The sanity check rejected legitimate positions for Jupiter and beyond. Ranges are now per-method.
- A missing `config.json` no longer silently uses Denver coordinates.
- An unknown `--agent` is now an error instead of silently acting as `CENTRAL`.
- An expedition vessel no longer silently reports an Earth position: it needs `--allow-placeholder`, and the record is marked.
- Tagging a batch skips files outside kernel coverage and continues, instead of aborting.
- Burst logging writes each record to the log file for its own date.
- Sidecars record where the timestamp came from and whether a time zone was assumed.

### Removed
- Empty `meta/soi/`, `media/` and `.gitkeep` placeholders.
- `detect_markers.py` (unrelated to this tool; keep it in its own repo).
