"""`astro-tagger tag`: write <file>.astro.json (and optionally <file>.label.txt) next to files."""
import glob
import json
import os
import sys
from datetime import datetime, timezone

from . import __version__
from .config import load_config
from .errors import NoCoverageError
from .hashing import sha256_file
from .state import compute_state, resolve_observer
from .timestamps import Stamp, best_stamp_for_file

SIDECAR_SUFFIXES = (".astro.json", ".label.txt")

_MIME = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".tif": "image/tiff", ".tiff": "image/tiff",
    ".mp4": "video/mp4", ".mov": "video/quicktime", ".mkv": "video/x-matroska",
    ".wav": "audio/wav", ".mp3": "audio/mpeg", ".flac": "audio/flac",
    ".pdf": "application/pdf",
}


def guess_mime(path: str) -> str:
    return _MIME.get(os.path.splitext(path)[1].lower(), "application/octet-stream")


def parse_utc(s: str) -> datetime:
    dt = datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def expand_paths(patterns) -> list:
    out = []
    for p in patterns:
        hits = glob.glob(p)
        out.extend(hits if hits else [p])
    return [p for p in out if os.path.isfile(p) and not p.endswith(SIDECAR_SUFFIXES)]


def build_sidecar(path: str, stamp: Stamp, rec: dict, file_sha: str) -> dict:
    return {
        "type": "astro_sidecar/v2",
        "file": {
            "name": os.path.basename(path),
            "sha256": file_sha,
            "mime": guess_mime(path),
            "bytes": os.path.getsize(path),
        },
        "timestamp": {
            "utc": rec["time"]["utc"],
            "source": stamp.source,
            "timezone_assumed": stamp.timezone_assumed,
        },
        "state": rec,
        "provenance": {
            "tool": {"name": "astro_tagger", "version": __version__},
            "kernel_index": "kernels/index.json",
        },
    }


def format_label(stamp: Stamp, rec: dict, file_sha: str) -> str:
    st, ag = rec["state"], rec["agent"]
    assumed = ", time zone assumed UTC" if stamp.timezone_assumed else ""
    lines = [
        f"UTC: {rec['time']['utc']}  (source: {stamp.source}{assumed})",
        f"Agent: {ag['id']} ({ag['role']}, home body {ag['home_body']})",
        f"Observer method: {rec['method']}" + ("  [PLACEHOLDER]" if rec["observer_is_placeholder"] else ""),
        f"Ephemeris: {rec['ephemeris']}",
        f"Ephemeris SHA256: {rec['ephemeris_sha256'][:16]}...",
        f"File SHA256: {file_sha[:16]}...",
        f"Position [m] (BCRS): {st['r_m']}",
        f"Velocity [m/s] (BCRS): {st['v_m_s']}",
    ]
    pl = rec.get("planetary", {})
    if "latlonh" in pl:
        ll = pl["latlonh"]
        lines.append(f"Site (ITRS, WGS84): lat={ll['lat_deg']:.6f}, lon={ll['lon_deg']:.6f}, alt={ll['h_m']:.2f} m")
    return "\n".join(lines) + "\n"


def run(args) -> int:
    cfg = load_config(cli_site={"lat_deg": args.lat, "lon_deg": args.lon, "alt_m": args.alt})
    obs = resolve_observer(args.agent, cfg)
    files = expand_paths(args.paths)
    if not files:
        print("No files found.", file=sys.stderr)
        return 1

    failures = 0
    for fp in files:
        stamp = Stamp(parse_utc(args.utc), "override", False) if args.utc else best_stamp_for_file(fp)
        try:
            rec = compute_state(stamp.dt, args.policy, obs, sanity=args.sanity,
                                allow_placeholder=args.allow_placeholder)
        except NoCoverageError as e:
            print(f"SKIPPED {fp}: {e} (try --policy longspan or --policy closest)", file=sys.stderr)
            failures += 1
            continue

        file_sha = sha256_file(fp)
        sidecar_path = fp + ".astro.json"
        with open(sidecar_path, "w", encoding="utf-8") as f:
            json.dump(build_sidecar(fp, stamp, rec, file_sha), f, ensure_ascii=False, indent=2)
        print(f"Wrote {sidecar_path}  (UTC={rec['time']['utc']}, source={stamp.source}, method={rec['method']})")

        if args.label:
            label = format_label(stamp, rec, file_sha)
            with open(fp + ".label.txt", "w", encoding="utf-8") as f:
                f.write(label)
            print("----- label -----")
            print(label.rstrip())
            print("-----------------")
    return 1 if failures else 0
