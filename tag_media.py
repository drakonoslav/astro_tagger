# tag_media.py — tag media with astro sidecars + a human label
# Now auto-picks the earliest plausible timestamp from the file (EXIF/PDF/name/FS)
#
# Usage examples:
#   python tag_media.py media\*.jpg --policy modern --label
#   python tag_media.py media\clip.mp4 --policy legacy --label
#   python tag_media.py media\scan.pdf --label
#   python tag_media.py media\something.mov --utc 1978-06-12T15:30:00Z --label   # manual override
#   python tag_media.py media\*.jpg --policy modern --agent MarsBase-Alpha --label

import os, sys, glob, json, hashlib, re
from datetime import datetime, timezone
from typing import Tuple, Optional
import numpy as np

from skyfield.api import wgs84
from kernel_store import skyfield_load_ephemeris

ROOT = os.path.dirname(__file__)
CFG_PATH = os.path.join(ROOT, "meta", "config.json")
AGENTS_PATH = os.path.join(ROOT, "meta", "agents.json")

# Optional deps for better timestamps
try:
    from PIL import Image, ExifTags  # pip install Pillow
    _HAVE_PIL = True
except Exception:
    _HAVE_PIL = False

try:
    import pypdf  # pip install pypdf
    _HAVE_PYPDF = True
except Exception:
    _HAVE_PYPDF = False

# ---------- config/helpers ----------
def load_config():
    cfg = {
        "site": {
            "lat_deg": 39.7392,         # Denver defaults; override in meta/config.json
            "lon_deg": -104.9903,
            "alt_m": 1609.0,
            "agent_id": "Agent-LocalSite"
        }
    }
    try:
        with open(CFG_PATH, "r", encoding="utf-8") as f:
            user = json.load(f)
        cfg["site"].update(user.get("site", {}))
    except FileNotFoundError:
        pass
    return cfg

def load_agents() -> dict:
    try:
        with open(AGENTS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def file_sha256(path: str, chunk=1024*1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b: break
            h.update(b)
    return h.hexdigest()

def tdb_seconds_since_j2000(ts, t) -> float:
    return float((t.tdb - 2451545.0) * 86400.0)

def site_bcrs_state(eph, t, lat_deg, lon_deg, alt_m) -> Tuple[list, list]:
    earth = eph["earth"]
    topo  = wgs84.latlon(lat_deg, lon_deg, elevation_m=alt_m)
    gcrs  = (earth + topo).at(t)
    r_m   = (np.array(gcrs.position.km)   * 1000.0).tolist()
    v_m_s = (np.array(gcrs.velocity.km_per_s) * 1000.0).tolist()
    return r_m, v_m_s

def guess_mime(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    return {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
        ".tif": "image/tiff", ".tiff": "image/tiff",
        ".mp4": "video/mp4", ".mov": "video/quicktime", ".mkv": "video/x-matroska",
        ".wav": "audio/wav", ".mp3": "audio/mpeg", ".flac": "audio/flac",
        ".pdf": "application/pdf"
    }.get(ext, "application/octet-stream")

# ---------- timestamp extraction ----------
_EXIF_DT_KEYS = {"DateTimeOriginal", "DateTimeDigitized", "CreateDate"}

def exif_datetime(path: str) -> Optional[datetime]:
    if not _HAVE_PIL:
        return None
    ext = os.path.splitext(path)[1].lower()
    if ext not in (".jpg",".jpeg",".tif",".tiff"):
        return None
    try:
        im = Image.open(path)
        exif = im.getexif()
        if not exif:
            return None
        # map tag ids to names
        tagmap = {ExifTags.TAGS.get(k, k): v for k, v in exif.items()}
        for k in _EXIF_DT_KEYS:
            if k in tagmap and isinstance(tagmap[k], str):
                # common EXIF format: "YYYY:MM:DD HH:MM:SS"
                s = tagmap[k].strip()
                s = s.replace("/",":").replace("-",":")
                # handle timezone-less as UTC
                try:
                    dt = datetime.strptime(s, "%Y:%m:%d %H:%M:%S").replace(tzinfo=timezone.utc)
                    return dt
                except Exception:
                    pass
        return None
    except Exception:
        return None

def pdf_creation_datetime(path: str) -> Optional[datetime]:
    if not _HAVE_PYPDF:
        return None
    if os.path.splitext(path)[1].lower() != ".pdf":
        return None
    try:
        with open(path, "rb") as f:
            reader = pypdf.PdfReader(f)
            info = reader.metadata or {}
            # PDF dates look like D:YYYYMMDDHHmmSS+hh'mm'
            for key in ("/CreationDate", "/ModDate"):
                val = info.get(key)
                if not val or not isinstance(val, str):
                    continue
                m = re.match(r"D:(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})", val)
                if m:
                    y,mo,d,hh,mm,ss = map(int, m.groups())
                    return datetime(y,mo,d,hh,mm,ss, tzinfo=timezone.utc)
        return None
    except Exception:
        return None

# YYYYMMDD / YYYY-MM-DD / YYYY_MM_DD … with optional time
_FILENAME_PATTERNS = [
    r"(?P<y>20\d{2}|19\d{2})[-_]? (?P<m>\d{2})[-_]? (?P<d>\d{2})[ T_:-]? (?P<H>\d{2})[ _:-]?(?P<M>\d{2})[ _:-]?(?P<S>\d{2})",
    r"(?P<y>20\d{2}|19\d{2})[-_]? (?P<m>\d{2})[-_]? (?P<d>\d{2})",
]
def datetime_from_filename(path: str) -> Optional[datetime]:
    name = os.path.basename(path)
    s = name.replace(".", " ")
    for pat in _FILENAME_PATTERNS:
        m = re.search(pat, s, flags=re.IGNORECASE | re.VERBOSE)
        if m:
            gd = m.groupdict()
            y = int(gd["y"]); mo = int(gd["m"]); d = int(gd["d"])
            H = int(gd.get("H") or 0); M = int(gd.get("M") or 0); S = int(gd.get("S") or 0)
            try:
                return datetime(y,mo,d,H,M,S, tzinfo=timezone.utc)
            except Exception:
                continue
    return None

def fs_oldest_datetime(path: str) -> datetime:
    st = os.stat(path)
    # On Windows, st_ctime is creation time; on Unix it's metadata change time.
    candidates = [st.st_mtime, st.st_ctime]
    t = min(candidates)
    return datetime.fromtimestamp(t, tz=timezone.utc)

def best_datetime_for_file(path: str) -> datetime:
    # Prefer: EXIF -> PDF -> filename -> filesystem -> now
    for fn in (exif_datetime, pdf_creation_datetime, datetime_from_filename):
        dt = fn(path)
        if dt:
            return dt.astimezone(timezone.utc)
    try:
        return fs_oldest_datetime(path)
    except Exception:
        return datetime.now(timezone.utc)

# ---------- sidecar / label ----------
def format_label(utc_dt, eph_label, sha, r_m, v_m_s, lat_deg, lon_deg, alt_m) -> str:
    return (
        f"UTC: {utc_dt.isoformat().replace('+00:00','Z')}\n"
        f"Ephemeris: {eph_label}\n"
        f"SHA256: {sha[:16]}…\n"
        f"Position [m]: {r_m}\n"
        f"Velocity [m/s]: {v_m_s}\n"
        f"Earth-fixed (ITRF/WGS84): lat={lat_deg:.6f}°, lon={lon_deg:.6f}°, alt={alt_m:.2f} m\n"
    )

def build_sidecar(path, utc_dt, policy, cfg):
    lat = cfg["site"]["lat_deg"]
    lon = cfg["site"]["lon_deg"]
    alt = cfg["site"]["alt_m"]
    agent_id = cfg["site"]["agent_id"]

    ts, eph, eph_label, ephem_sha = skyfield_load_ephemeris(utc_dt, policy=policy)
    t = ts.from_datetime(utc_dt)
    r_m, v_m_s = site_bcrs_state(eph, t, lat, lon, alt)

    sha = file_sha256(path)
    mime = guess_mime(path)

    sidecar = {
        "file": {
            "path": os.path.relpath(path, ROOT).replace("\\", "/"),
            "sha256": sha,
            "mime": mime,
            "original_datetime": utc_dt.isoformat().replace("+00:00","Z"),
        },
        "provenance": {
            "site_config": {
                "lat_deg": lat,
                "lon_deg": lon,
                "alt_m": alt,
                "agent_id": agent_id,
            },
            "kernel_store_index": "kernel_store/index.json",
        },
        "state": {
            "type": "state/v1",
            "id": agent_id,
            "time": {"utc": utc_dt.isoformat().replace("+00:00","Z"),
                     "tdb_s": tdb_seconds_since_j2000(ts, t)},
            "state": {"frame": "BCRS", "r_m": r_m, "v_m_s": v_m_s},
            "ephemeris": eph_label,
            "ephemeris_sha256": ephem_sha,
            "planetary": {
                "body": "IAU_EARTH",
                "inertial_frame": "GCRS",
                "body_fixed_frame": "ITRF/WGS84",
                "latlonh": {"lat_deg": lat, "lon_deg": lon, "h_m": alt},
                "local_enu": {"origin_name": "LocalSite_ENU",
                              "origin_latlonh": {"lat_deg": lat, "lon_deg": lon, "h_m": alt},
                              "r_m": [0,0,0], "v_m_s": [0,0,0]},
            },
            "frames_present": ["ICRS","BCRS","GCRS","ITRF","Local_ENU"],
            "privacy": {"intent": "unknown"},
            "policy": policy,
        },
    }

    label = format_label(utc_dt, eph_label, sha, r_m, v_m_s, lat, lon, alt)
    return sidecar, label

# ---------- CLI ----------
def parse_args(argv):
    import argparse
    p = argparse.ArgumentParser(description="Tag media with astro sidecars + label (auto time from file).")
    p.add_argument("paths", nargs="+", help="files or globs")
    p.add_argument("--utc", help="Override UTC (e.g., 1978-06-12T15:30:00Z)")
    p.add_argument("--policy", default="modern", choices=["legacy","modern","longspan","closest"])
    p.add_argument("--label", action="store_true", help="also write <file>.label.txt and print it")
    # NEW: agent stamping
    p.add_argument("--agent", type=str, help="Agent ID to stamp into sidecar")
    args = p.parse_args(argv[1:])

    # expand globs
    expanded = []
    for pth in args.paths:
        hits = glob.glob(pth)
        if hits: expanded.extend(hits)
        else: expanded.append(pth)
    expanded = [p for p in expanded if os.path.isfile(p)]
    if not expanded:
        print("No files found.")
        sys.exit(1)

    return expanded, args.utc, args.policy, args.label, args.agent

def main():
    files, utc_override, policy, want_label, agent = parse_args(sys.argv)
    cfg = load_config()

    # Load agent registry if the user passed --agent
    agents = load_agents() if agent else {}

    for fp in files:
        if utc_override:
            utc_dt = datetime.fromisoformat(utc_override.replace("Z","+00:00")).astimezone(timezone.utc)
        else:
            utc_dt = best_datetime_for_file(fp)

        sidecar, label = build_sidecar(fp, utc_dt, policy, cfg)

        # If --agent provided, stamp agent id + role into the sidecar
        if agent:
            role = None
            if agent in agents:
                role = agents[agent].get("role")
            sidecar["agent"] = {"id": agent, "role": role}

        sidecar_path = fp + ".astro.json"
        with open(sidecar_path, "w", encoding="utf-8") as f:
            json.dump(sidecar, f, ensure_ascii=False, separators=(",",":"))
        print(f"Wrote {sidecar_path}  (UTC={utc_dt.isoformat().replace('+00:00','Z')})")

        if want_label:
            label_path = fp + ".label.txt"
            with open(label_path, "w", encoding="utf-8") as f:
                f.write(label)
            print(f"Wrote {label_path}")
            print("----- label -----")
            print(label.rstrip())
            print("-----------------")

if __name__ == "__main__":
    main()
