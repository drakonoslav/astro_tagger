"""Site and agent configuration.

Site precedence (highest first): command-line flags > agent 'site' > config/config.json.
Altitude may be written alt_m or h_m; alt_m is canonical.
"""
import json
from dataclasses import dataclass
from typing import Optional

from . import paths
from .errors import ConfigError

DEFAULT_AGENT_ID = "CENTRAL"
DEFAULT_AGENT_META = {"role": "CENTRAL", "home_body": "EARTH", "home_star": "SUN"}


@dataclass(frozen=True)
class Site:
    lat_deg: float
    lon_deg: float
    h_m: float = 0.0
    name: str = "LocalSite"

    def latlonh(self) -> dict:
        return {"lat_deg": self.lat_deg, "lon_deg": self.lon_deg, "h_m": self.h_m}


def _canon(d: Optional[dict]) -> dict:
    """Normalise altitude key names so dicts can be layered."""
    out = dict(d or {})
    if "h_m" in out:
        h = out.pop("h_m")
        out.setdefault("alt_m", h)
    return out


def site_from_dict(d: dict, label: str = "site") -> Site:
    d = _canon(d)
    lat, lon, h = d.get("lat_deg"), d.get("lon_deg"), d.get("alt_m")
    if lat is None or lon is None:
        raise ConfigError(f"{label}: lat_deg and lon_deg must be set (edit {paths.config_path()})")
    try:
        lat, lon = float(lat), float(lon)
        h = 0.0 if h is None else float(h)
    except (TypeError, ValueError):
        raise ConfigError(f"{label}: lat_deg, lon_deg and alt_m must be numbers")
    if not -90.0 <= lat <= 90.0:
        raise ConfigError(f"{label}: lat_deg {lat} is outside -90..90")
    if not -180.0 <= lon <= 180.0:
        raise ConfigError(f"{label}: lon_deg {lon} is outside -180..180")
    return Site(lat, lon, h, str(d.get("name") or "LocalSite"))


@dataclass(frozen=True)
class Config:
    file_site: dict
    cli_site: dict
    agent_id: str

    def earth_site(self, agent_site: Optional[dict] = None) -> Site:
        merged = {**_canon(self.file_site), **_canon(agent_site), **_canon(self.cli_site)}
        return site_from_dict(merged, "site")


def _read_json(path) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        raise ConfigError(f"{path} is not valid JSON: {e}")


def load_config(cli_site: Optional[dict] = None) -> Config:
    cli = {k: v for k, v in (cli_site or {}).items() if v is not None}
    path = paths.config_path()
    data = {}
    if path.is_file():
        data = _read_json(path)
    elif not ("lat_deg" in cli and "lon_deg" in cli):
        raise ConfigError(
            f"No site configured. Copy {paths.config_example_path()} to {path} and set your "
            "location, or pass --lat and --lon."
        )
    site = data.get("site") or {}
    agent_id = str(site.get("agent_id") or data.get("agent_id") or DEFAULT_AGENT_ID)
    return Config(dict(site), cli, agent_id)


def load_agents() -> dict:
    path = paths.agents_path()
    if not path.is_file():
        return {}
    return _read_json(path)


def get_agent(agent_id: str, explicit: bool) -> dict:
    """Look up an agent. An unknown id is an error if the user asked for it by name;
    the config's default agent silently falls back to CENTRAL."""
    agents = load_agents()
    if agent_id in agents:
        return agents[agent_id]
    if explicit:
        known = ", ".join(sorted(agents)) or "(none defined)"
        raise ConfigError(f"Unknown agent '{agent_id}'. Known agents: {known}")
    return dict(DEFAULT_AGENT_META)
