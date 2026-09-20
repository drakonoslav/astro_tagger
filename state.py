"""The one place an observer's state is computed. Both `tag` and `state` call compute_state().

Observer methods (record field "method"):
  earth_topocenter         Earth site (lat/lon/height on WGS84) via Skyfield; the real thing
  body_center              non-Earth base placed at its body's center (kernel has the center)
  system_barycenter        same, but the kernel only has the body's system barycenter
  placeholder_earth_site   expedition vessel with no trajectory: Earth site, opt-in only

For non-Earth bases the site's lat/lon/height are recorded but NOT applied to the state.
Applying them needs the body's rotation model, which is not implemented.
"""
import math
from dataclasses import dataclass
from datetime import timezone
from typing import Optional

from .config import Config, Site, get_agent, site_from_dict
from .ephemeris import load_ephemeris
from .errors import ConfigError, KernelError, PlaceholderRequired, SanityError
from .frames import body_fixed_frame, canonical_body, ephemeris_key, has_body_center

SCHEMA = "state/v2"
ROLES = ("CENTRAL", "REMOTE_BASE", "EXPEDITION_VESSEL")
TRAVEL_MODES = ("classical", "runner")


@dataclass(frozen=True)
class Observer:
    agent_id: str
    role: str
    home_body: str                       # canonical, e.g. "EARTH", "MARS"
    home_star: Optional[str]
    home_star_runner: Optional[str]
    travel_mode: Optional[str]           # vessels only
    site: Optional[Site]                 # Earth site, or a body-fixed site on home_body

    def agent_block(self) -> dict:
        return {
            "id": self.agent_id,
            "role": self.role,
            "home_body": self.home_body,
            "home_star": self.home_star,
            "travel_mode": self.travel_mode,
        }


def resolve_observer(agent_id: Optional[str], cfg: Config, *, travel_mode: Optional[str] = None) -> Observer:
    """Turn an agent id (or the config default) plus site settings into an Observer."""
    explicit = agent_id is not None
    aid = agent_id or cfg.agent_id
    meta = get_agent(aid, explicit)

    role = str(meta.get("role") or "CENTRAL").upper()
    if role not in ROLES:
        raise ConfigError(f"Agent '{aid}': role must be one of {ROLES}, got '{role}'")
    home_body = canonical_body(meta.get("home_body") or "EARTH")
    if role == "CENTRAL" and home_body != "EARTH":
        raise ConfigError(f"Agent '{aid}': a CENTRAL agent must have home_body EARTH")

    mode = str(travel_mode or meta.get("travel_mode") or "classical").lower()
    if mode not in TRAVEL_MODES:
        raise ConfigError(f"travel_mode must be one of {TRAVEL_MODES}, got '{mode}'")

    agent_site = meta.get("site") if isinstance(meta.get("site"), dict) else None

    if role == "EXPEDITION_VESSEL":
        try:
            site = cfg.earth_site(None)      # only used by the opt-in placeholder
        except ConfigError:
            site = None
    elif home_body == "EARTH":
        site = cfg.earth_site(agent_site)
    else:
        if cfg.cli_site:
            raise ConfigError(
                f"--lat/--lon/--alt set an Earth site, but agent '{aid}' is based on {home_body}"
            )
        site = site_from_dict(agent_site, f"agent '{aid}' site") if agent_site else None

    return Observer(
        agent_id=aid,
        role=role,
        home_body=home_body,
        home_star=meta.get("home_star"),
        home_star_runner=meta.get("home_star_runner"),
        travel_mode=mode if role == "EXPEDITION_VESSEL" else None,
        site=site,
    )


# ---------- position ----------

def _vec_m(v) -> list:
    return [float(x) * 1000.0 for x in v]


def _earth_site_bcrs(eph, t, site: Site):
    from skyfield.api import wgs84
    topo = wgs84.latlon(site.lat_deg, site.lon_deg, elevation_m=site.h_m)
    at = (eph["earth"] + topo).at(t)
    return _vec_m(at.position.km), _vec_m(at.velocity.km_per_s)


def _body_bcrs(eph, t, body: str):
    key = ephemeris_key(body)
    try:
        seg = eph[key]
    except Exception as e:
        raise KernelError(f"The kernel does not contain '{key}' (needed for {body}); try another --policy") from e
    at = seg.at(t)
    return _vec_m(at.position.km), _vec_m(at.velocity.km_per_s)


def _observer_bcrs(eph, t, obs: Observer, allow_placeholder: bool):
    if obs.role == "EXPEDITION_VESSEL":
        if not allow_placeholder:
            raise PlaceholderRequired(
                f"Agent '{obs.agent_id}' is an EXPEDITION_VESSEL and no trajectory support exists yet, "
                "so its position would be a placeholder. Re-run with --allow-placeholder to record "
                "an Earth-site placeholder (the record is marked as such)."
            )
        if obs.site is None:
            raise ConfigError("The placeholder needs a configured Earth site (config/config.json)")
        r, v = _earth_site_bcrs(eph, t, obs.site)
        return r, v, "placeholder_earth_site"
    if obs.home_body == "EARTH":
        r, v = _earth_site_bcrs(eph, t, obs.site)
        return r, v, "earth_topocenter"
    r, v = _body_bcrs(eph, t, obs.home_body)
    return r, v, ("body_center" if has_body_center(obs.home_body) else "system_barycenter")


def _check_sanity(r_m, v_m_s, method: str, obs: Observer) -> None:
    r = math.sqrt(sum(x * x for x in r_m))
    v = math.sqrt(sum(x * x for x in v_m_s))
    if method in ("earth_topocenter", "placeholder_earth_site"):
        r_lo, r_hi, v_lo, v_hi = 1.4e11, 1.6e11, 2.8e4, 3.2e4      # Earth's orbit, with margin
    else:
        r_lo, r_hi, v_lo, v_hi = 0.0, 1.0e13, 0.0, 1.0e5           # anywhere out to Pluto
    if not (r_lo < r < r_hi):
        raise SanityError(f"Position magnitude {r:.3e} m is implausible (agent={obs.agent_id}, method={method})")
    if not (v_lo < v < v_hi):
        raise SanityError(f"Velocity magnitude {v:.3e} m/s is implausible (agent={obs.agent_id}, method={method})")


# ---------- record ----------

def _iso_z(dt) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def compute_state(utc_dt, policy: str, obs: Observer, *, sanity: bool = True,
                  allow_placeholder: bool = False, mission_id: Optional[str] = None,
                  mission_phase: Optional[str] = None) -> dict:
    """Return a state/v2 record for `obs` at `utc_dt`."""
    if utc_dt.tzinfo is None:
        utc_dt = utc_dt.replace(tzinfo=timezone.utc)
    utc_dt = utc_dt.astimezone(timezone.utc)

    ephem = load_ephemeris(utc_dt, policy)
    t = ephem.ts.from_datetime(utc_dt)
    r_m, v_m_s, method = _observer_bcrs(ephem.eph, t, obs, allow_placeholder)
    if sanity:
        _check_sanity(r_m, v_m_s, method, obs)

    rec = {
        "type": SCHEMA,
        "id": obs.agent_id,
        "time": {"utc": _iso_z(utc_dt), "tdb_s": float((t.tdb - 2451545.0) * 86400.0)},
        "state": {
            "frame": "BCRS", "origin": "SSB", "axes": "ICRS", "time_scale": "TDB",
            "r_m": r_m, "v_m_s": v_m_s,
        },
        "method": method,
        "site_offset_applied": method in ("earth_topocenter", "placeholder_earth_site"),
        "observer_is_placeholder": method == "placeholder_earth_site",
        "ephemeris": ephem.label,
        "ephemeris_sha256": ephem.sha256,
        "policy": policy,
        "agent": obs.agent_block(),
        "frames_present": ["BCRS"],
        "privacy": {"intent": "unknown"},
    }
    if mission_id:
        rec["mission_id"] = mission_id
    if mission_phase:
        rec["mission_phase"] = mission_phase

    if method == "earth_topocenter":
        rec["planetary"] = {
            "body": "EARTH",
            "body_fixed_frame": "ITRS",
            "geodetic_datum": "WGS84",
            "latlonh": obs.site.latlonh(),
            "local_enu": {"origin_name": obs.site.name, "origin_latlonh": obs.site.latlonh()},
        }
        rec["frames_present"] += ["ITRS", "Local_ENU"]
    elif method in ("body_center", "system_barycenter"):
        rec["planetary"] = {"body": obs.home_body, "body_fixed_frame": body_fixed_frame(obs.home_body)}
        if obs.site:
            rec["planetary"]["site"] = {"name": obs.site.name, **obs.site.latlonh(), "applied_to_state": False}
            rec["frames_present"].append(body_fixed_frame(obs.home_body))
    elif method == "placeholder_earth_site":
        rec["placeholder_note"] = "No trajectory available; state is the configured Earth site, not the vessel."
        if obs.travel_mode == "runner" and obs.home_star_runner:
            rec["extensions"] = {"stellar_runner": {"star": obs.home_star_runner, "status": "breadcrumb_only"}}
        elif obs.home_star:
            rec["extensions"] = {"stellar_anchor": {"star": obs.home_star, "status": "breadcrumb_only"}}

    return rec
