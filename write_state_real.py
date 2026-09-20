# write_state_real.py — agent-aware, role-driven state logger
# Examples:
#   python write_state_real.py --policy modern --agent CENTRAL
#   python write_state_real.py 1978-06-12T15:30:00Z --policy legacy --agent Base-Planetoid
#   python write_state_real.py --policy modern --agent Voyager-2 --mission_id VOY-TEST --mission_phase transit
#   python write_state_real.py --policy modern --agent Voyager-2 --travel_mode runner

import os, sys, json, math
from datetime import datetime, timedelta, timezone
from typing import Tuple, Optional
import numpy as np

from skyfield.api import wgs84
# Your existing ephemeris loader (must be present)
from kernel_store import skyfield_load_ephemeris

# ---------- paths ----------
ROOT = os.path.dirname(os.path.abspath(__file__))
CFG_PATH = os.path.join(ROOT, "meta", "config.json")
AGENTS_PATH = os.path.join(ROOT, "meta", "agents.json")
SOI_DIR = os.path.join(ROOT, "meta", "soi")  # optional future use
LOG_DIR = os.path.join(ROOT, "logs")

# ---------- config / agents ----------
def load_config():
    cfg = {
        "site": {
            "lat_deg": 39.7392, "lon_deg": -104.9903, "h_m": 1609.0,
            "name": "EarthSite", "agent_id": "Agent-LocalSite"
        }
    }
    try:
        with open(CFG_PATH, "r", encoding="utf-8") as f:
            user = json.load(f)
        if "site" in user:
            for k, v in user["site"].items():
                cfg["site"][k] = v
    except FileNotFoundError:
        pass
    return cfg

def load_agents():
    try:
        with open(AGENTS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def get_agent_meta(agent_id: str):
    ag = load_agents().get(agent_id, None)
    if ag is None:
        # fallback to CENTRAL
        return {
            "role": "CENTRAL",
            "home_body": "IAU_EARTH",
            "home_star": "SUN"
        }
    return ag

# ---------- utilities ----------
def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)

def tdb_seconds_since_j2000(ts, t) -> float:
    return float((t.tdb - 2451545.0) * 86400.0)

def map_body_to_skyfield_key(home_body: str) -> Optional[str]:
    """
    Map "IAU_*" body names to Skyfield ephemeris keys.
    Extend as needed.
    """
    if not home_body:
        return None
    key = home_body.upper()
    lut = {
        "IAU_SUN": "sun",
        "IAU_EARTH": "earth",
        "IAU_MOON": "moon",
        "IAU_MERCURY": "mercury",
        "IAU_VENUS": "venus",
        "IAU_MARS": "mars",
        "IAU_JUPITER": "jupiter barycenter",  # jupiter vs barycenter nuance
        "IAU_SATURN": "saturn barycenter",
        "IAU_URANUS": "uranus barycenter",
        "IAU_NEPTUNE": "neptune barycenter",
        "IAU_PLUTO": "pluto barycenter",
    }
    return lut.get(key, None)

def inertial_name_for_body(home_body: str) -> str:
    # Simple convention, adjust if you adopt specific IAU naming
    # E.g. "IAU_MARS" -> "IAU_MARS_J2000"
    return f"{home_body}_J2000"

def compute_soi_stub(bcrs_r_m: list) -> dict:
    """
    Placeholder for SOI logic; returns 'unknown'.
    Implement later using meta/soi/*.json and real body centers.
    """
    return {"in_body": False, "body": None, "note": "SOI logic not implemented"}

def add_stellar_runner_frame(rec: dict, star_id: str):
    """
    Breadcrumb only: mark that this snapshot used a 'runner' (relativistic) frame idea.
    """
    rec.setdefault("stellar_runner", {})["frame"] = f"{star_id}_runner"
    rec.setdefault("frames_present", []).append(f"{star_id}_runner")

# ---------- BCRS state computation ----------
def bcrs_state_for_agent(ts, eph, t, role: str, home_body: str, lat_deg: float, lon_deg: float, h_m: float):
    """
    Returns (r_m, v_m_s, method_note)
    - For CENTRAL or Earth-site: use (earth + topo).at(t)
    - For REMOTE_BASE w/ non-Earth home_body: approximate agent at body center (until you wire site transforms)
    - For EXPEDITION_VESSEL: keep Earth-site placeholder for now (auditable stub)
    """
    role = (role or "CENTRAL").upper()
    method_note = None

    if role == "CENTRAL" or (role == "REMOTE_BASE" and (home_body or "IAU_EARTH") == "IAU_EARTH"):
        earth = eph["earth"]
        topo = wgs84.latlon(lat_deg, lon_deg, elevation_m=h_m)
        gcrs = (earth + topo).at(t)
        r_m = (np.array(gcrs.position.km) * 1000.0).tolist()
        v_m_s = (np.array(gcrs.velocity.km_per_s) * 1000.0).tolist()
        method_note = "earth_topocenter"
        return r_m, v_m_s, method_note

    if role == "REMOTE_BASE" and home_body and home_body != "IAU_EARTH":
        key = map_body_to_skyfield_key(home_body)
        if key and key in eph:
            g = eph[key].at(t)  # body center wrt SSB
            r_m = (np.array(g.position.km) * 1000.0).tolist()
            v_m_s = (np.array(g.velocity.km_per_s) * 1000.0).tolist()
            method_note = f"{home_body}_center_stub"
            return r_m, v_m_s, method_note

    # EXPEDITION_VESSEL (or unknown body) fallback: keep Earth site until you wire trajectories
    earth = eph["earth"]
    topo = wgs84.latlon(lat_deg, lon_deg, elevation_m=h_m)
    gcrs = (earth + topo).at(t)
    r_m = (np.array(gcrs.position.km) * 1000.0).tolist()
    v_m_s = (np.array(gcrs.velocity.km_per_s) * 1000.0).tolist()
    method_note = "expedition_placeholder_earth_topocenter"
    return r_m, v_m_s, method_note

# ---------- record builder ----------
def build_record_for_datetime(utc_dt: datetime,
                              policy: str,
                              agent_id: str,
                              mission_id: Optional[str],
                              mission_phase: Optional[str],
                              lat_deg: float, lon_deg: float, h_m: float,
                              sanity: bool = True) -> dict:
    # Load ephemeris
    ts, eph, eph_label, ephem_sha = skyfield_load_ephemeris(utc_dt, policy=policy)
    t = ts.from_datetime(utc_dt)

    # Agent & role / travel metadata
    agent_meta = get_agent_meta(agent_id)
    role = (agent_meta.get("role") or "CENTRAL").upper()  # CENTRAL | REMOTE_BASE | EXPEDITION_VESSEL
    home_body = agent_meta.get("home_body", "IAU_EARTH")
    home_star = agent_meta.get("home_star")
    home_star_runner = agent_meta.get("home_star_runner")
    travel_mode = (agent_meta.get("travel_mode") or "classical").lower()  # classical | runner
    soi_strategy = (agent_meta.get("soi_strategy") or "auto")

    # Merge site override (if agent provides one)
    site = agent_meta.get("site")
    if site and isinstance(site, dict):
        lat_deg = float(site.get("lat_deg", lat_deg))
        lon_deg = float(site.get("lon_deg", lon_deg))
        h_m = float(site.get("h_m", h_m))

    # Compute BCRS state for the agent (with safe fallbacks)
    r_m, v_m_s, bcrs_note = bcrs_state_for_agent(ts, eph, t, role, home_body, lat_deg, lon_deg, h_m)

    # Sanity checks (loose to accommodate different bodies/distances)
    if sanity:
        r_mag = math.sqrt(sum(x*x for x in r_m))
        v_mag = math.sqrt(sum(x*x for x in v_m_s))
        # wide envelopes that include inner planets and spacecraft
        if not (5.0e10 < r_mag < 5.0e11):
            raise ValueError(f"Position magnitude out of broad SSB range: {r_mag:.3e} m (role={role}, note={bcrs_note})")
        if not (0.0 < v_mag < 6.0e4):
            raise ValueError(f"Velocity magnitude out of expected range: {v_mag:.3e} m/s (role={role}, note={bcrs_note})")

    # Build base record
    rec = {
        "type": "state/v1",
        "id": agent_id,
        "time": {
            "utc": utc_dt.isoformat().replace("+00:00","Z"),
            "tdb_s": tdb_seconds_since_j2000(ts, t)
        },
        "state": {"frame": "BCRS", "r_m": r_m, "v_m_s": v_m_s},
        "ephemeris": eph_label,
        "ephemeris_sha256": ephem_sha,
        "agent": {
            "id": agent_id,
            "role": role,
            "home_body": home_body,
            "home_star": home_star,
            "travel_mode": travel_mode if role == "EXPEDITION_VESSEL" else None
        },
        "frames_present": ["ICRS","BCRS"],
        "privacy": {"intent": "unknown"},
    }
    if mission_id:
        rec["mission_id"] = mission_id
    if mission_phase:
        rec["mission_phase"] = mission_phase

    # Frame selection breadcrumbs
    fs = {"strategy": "role_based_v1", "role": role, "bcrs_note": bcrs_note}

    # ----- role-based frames -----
    if role == "CENTRAL":
        # Earth site frames (as you had)
        rec["planetary"] = {
            "body": "IAU_EARTH",
            "inertial_frame": "GCRS",
            "body_fixed_frame": "ITRF/WGS84",
            "latlonh": {"lat_deg": lat_deg, "lon_deg": lon_deg, "h_m": h_m},
            "local_enu": {
                "origin_name": site.get("name","LocalSite_ENU") if isinstance(site, dict) else "LocalSite_ENU",
                "origin_latlonh": {"lat_deg": lat_deg, "lon_deg": lon_deg, "h_m": h_m},
                "r_m": [0,0,0], "v_m_s": [0,0,0]
            }
        }
        rec["frames_present"].extend(["GCRS","ITRF","Local_ENU"])
        fs.update({"locked_to": "EarthSite", "body": "IAU_EARTH", "near_surface": True})

    elif role == "REMOTE_BASE":
        # Fixed base anchored to its home body
        if home_body == "IAU_EARTH":
            rec["planetary"] = {
                "body": "IAU_EARTH",
                "inertial_frame": "GCRS",
                "body_fixed_frame": "ITRF/WGS84",
                "latlonh": {"lat_deg": lat_deg, "lon_deg": lon_deg, "h_m": h_m},
                "local_enu": {
                    "origin_name": site.get("name","LocalSite_ENU") if isinstance(site, dict) else "LocalSite_ENU",
                    "origin_latlonh": {"lat_deg": lat_deg, "lon_deg": lon_deg, "h_m": h_m},
                    "r_m": [0,0,0], "v_m_s": [0,0,0]
                }
            }
            rec["frames_present"].extend(["GCRS","ITRF","Local_ENU"])
            fs.update({"locked_to": "home_body", "body": "IAU_EARTH", "near_surface": True})
        else:
            # Emit planetary inertial frame; body-fixed/site can be added later when kernels exist
            rec["planetary"] = {
                "body": home_body,
                "inertial_frame": inertial_name_for_body(home_body),
                "note": "REMOTE_BASE inertial only; add body-fixed/site when available"
            }
            rec["frames_present"].append(inertial_name_for_body(home_body))
            if site and isinstance(site, dict):
                rec["surface"] = {
                    "body_fixed_frame": f"{home_body}/2021",
                    "latlonh": {
                        "lat_deg": float(site.get("lat_deg", 0.0)),
                        "lon_deg": float(site.get("lon_deg", 0.0)),
                        "h_m": float(site.get("h_m", 0.0))
                    },
                    "local_enu": {
                        "origin_name": site.get("name","Local_ENU"),
                        "r_m": [0,0,0], "v_m_s": [0,0,0]
                    },
                    "note": "Placeholder body-fixed label; no transform computed"
                }
                rec["frames_present"].append(f"{home_body}/2021")
            fs.update({"locked_to": "home_body", "body": home_body, "near_surface": bool(site)})

    elif role == "EXPEDITION_VESSEL":
        if travel_mode == "runner" and home_star_runner:
            add_stellar_runner_frame(rec, home_star_runner)
            fs.update({"soi": "runner_mode", "home_star_runner": home_star_runner})
        else:
            # Classical expedition: leave BCRS; optionally breadcrumb a stellar anchor
            soi = compute_soi_stub(r_m)
            if soi.get("in_body") and soi.get("body"):
                body = soi["body"]
                rec["planetary"] = {
                    "body": body,
                    "inertial_frame": inertial_name_for_body(body),
                    "note": "SOI stub chose this body; near-surface not determined"
                }
                rec["frames_present"].append(inertial_name_for_body(body))
                fs.update({"soi": "in_body_stub", "body": body})
            else:
                # Deep space snapshot; add stellar breadcrumb if known
                if home_star:
                    rec.setdefault("stellar", {})["frame"] = f"{home_star}_centric_stub"
                    rec["frames_present"].append(f"{home_star}_centric_stub")
                fs.update({"soi": "none_stub"})

    rec["frame_selection"] = fs
    # de-dup frames_present while preserving order
    seen = set()
    dedup = []
    for f in rec["frames_present"]:
        if f not in seen:
            seen.add(f); dedup.append(f)
    rec["frames_present"] = dedup

    return rec

def append_jsonl(path: str, obj: dict):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, separators=(",",":"), ensure_ascii=False) + "\n")

# ---------- CLI ----------
def parse_args(argv, cfg):
    # defaults from config
    lat = float(cfg["site"]["lat_deg"])
    lon = float(cfg["site"]["lon_deg"])
    alt = float(cfg["site"]["h_m"])
    default_agent = cfg["site"].get("agent_id", "CENTRAL")

    policy = "modern"
    utc_dt = datetime.now(timezone.utc)
    fps = None
    frames = None
    agent_id = default_agent
    mission_id = None
    mission_phase = None
    travel_mode_override = None
    sanity = True

    i = 1
    if len(argv) > 1 and not argv[1].startswith("--"):
        utc_dt = datetime.fromisoformat(argv[1].replace("Z","+00:00")).astimezone(timezone.utc)
        i = 2
    while i < len(argv):
        a = argv[i]
        if a in ("--policy",) and i+1 < len(argv): policy = argv[i+1]; i += 2; continue
        if a.startswith("--policy="): policy = a.split("=",1)[1]; i += 1; continue
        if a == "--fps" and i+1 < len(argv): fps = float(argv[i+1]); i += 2; continue
        if a == "--frames" and i+1 < len(argv): frames = int(argv[i+1]); i += 2; continue
        if a == "--lat" and i+1 < len(argv): lat = float(argv[i+1]); i += 2; continue
        if a == "--lon" and i+1 < len(argv): lon = float(argv[i+1]); i += 2; continue
        if a == "--alt" and i+1 < len(argv): alt = float(argv[i+1]); i += 2; continue
        if a in ("--agent","--agent-id") and i+1 < len(argv): agent_id = argv[i+1]; i += 2; continue
        if a == "--mission_id" and i+1 < len(argv): mission_id = argv[i+1]; i += 2; continue
        if a == "--mission_phase" and i+1 < len(argv): mission_phase = argv[i+1]; i += 2; continue
        if a == "--travel_mode" and i+1 < len(argv): travel_mode_override = argv[i+1]; i += 2; continue
        if a == "--no_sanity": sanity = False; i += 1; continue
        i += 1

    # If user overrides travel mode, inject into the agent record on the fly
    if travel_mode_override:
        agents = load_agents()
        meta = agents.get(agent_id, {})
        meta = dict(meta)
        meta["travel_mode"] = travel_mode_override
        agents[agent_id] = meta
        # we don't write back to disk; we just carry this override into build
        # easiest way: stash it in a global to be picked by get_agent_meta?
        # simpler: return it to main() and pass down
        return utc_dt, policy, lat, lon, alt, agent_id, mission_id, mission_phase, sanity, meta

    return utc_dt, policy, lat, lon, alt, agent_id, mission_id, mission_phase, sanity, None

def main():
    cfg = load_config()
    res = parse_args(sys.argv, cfg)
    (utc_dt, policy, lat, lon, alt, agent_id, mission_id,
     mission_phase, sanity, agent_override) = res

    ensure_dir(LOG_DIR)
    day_str = utc_dt.date().isoformat()
    log_path = os.path.join(LOG_DIR, f"states-{day_str}.jsonl")

    # If we have an overridden agent meta from CLI, use it; else standard lookup
    if agent_override is not None:
        agent_meta = agent_override
    else:
        agent_meta = get_agent_meta(agent_id)

    try:
        # Single or burst
        if "--fps" in sys.argv and "--frames" in sys.argv:
            # Re-parse FPS/frames because we didn't keep them if not needed above
            # (this keeps the code straightforward and robust)
            fps = None; frames = None
            i = 1
            while i < len(sys.argv):
                if sys.argv[i] == "--fps" and i+1 < len(sys.argv):
                    fps = float(sys.argv[i+1]); i += 2; continue
                if sys.argv[i] == "--frames" and i+1 < len(sys.argv):
                    frames = int(sys.argv[i+1]); i += 2; continue
                i += 1

            if fps is None or frames is None:
                raise ValueError("Both --fps and --frames are required for burst mode.")

            dt = utc_dt
            step = timedelta(seconds=1.0/float(fps))
            last_rec = None
            for _ in range(frames):
                rec = build_record_for_datetime(dt, policy, agent_id, mission_id, mission_phase,
                                                lat, lon, alt, sanity=sanity)
                # inject agent_override role/mode if provided
                if agent_override:
                    rec["agent"]["role"] = (agent_override.get("role") or rec["agent"]["role"])
                    if "travel_mode" in agent_override:
                        rec["agent"]["travel_mode"] = agent_override["travel_mode"]
                append_jsonl(log_path, rec)
                last_rec = rec
                dt += step

            # summary
            print(f"Appended {frames} records → {log_path}")
            if last_rec:
                print(f"Ephemeris: {last_rec['ephemeris']}")
                print(f"Agent:     {last_rec['agent']}")
                print(f"Frames:    {', '.join(last_rec['frames_present'])}")
                print(f"Policy:    {policy}")
                print(f"SHA256:    {last_rec['ephemeris_sha256'][:16]}…")

        else:
            rec = build_record_for_datetime(utc_dt, policy, agent_id, mission_id, mission_phase,
                                            lat, lon, alt, sanity=sanity)
            # inject agent_override
            if agent_override:
                rec["agent"]["role"] = (agent_override.get("role") or rec["agent"]["role"])
                if "travel_mode" in agent_override:
                    rec["agent"]["travel_mode"] = agent_override["travel_mode"]

            append_jsonl(log_path, rec)
            print(f"Appended state → {log_path}")
            print(f"UTC:      {rec['time']['utc']}")
            print(f"Agent:    {rec['agent']}")
            print(f"Frames:   {', '.join(rec['frames_present'])}")
            print(f"Ephem:    {rec['ephemeris']}")
            print(f"Policy:   {policy}")
            print(f"SHA256:   {rec['ephemeris_sha256'][:16]}…")

    except RuntimeError as e:
        msg = str(e)
        if "No SPK ephemeris covers" in msg or "No SPK ephemeris covers JD" in msg:
            print("ERROR: No ephemeris in kernel_store covers the requested date/time.")
            print("       Try --policy longspan or add an appropriate SPK then run build_kernel_hashes.py")
        else:
            raise

if __name__ == "__main__":
    main()
