"""Test support: a stub Skyfield so tests run without 100 MB kernels.

The stub places Earth at 1.496e8 km on +x and adds the site's lat/lon/height (as km) to it, so
tests can tell exactly which site was used. It checks this project's logic (agents, precedence,
records, CLI wiring), NOT real ephemeris accuracy.
"""
import hashlib
import json
import os
import shutil
import sys
import tempfile
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path

J2000 = datetime(2000, 1, 1, 12, tzinfo=timezone.utc)
REPO = Path(__file__).resolve().parent.parent
EARTH_X_KM = 1.496e8


class _Vec:
    def __init__(self, pos_km, vel_kms):
        self.position = types.SimpleNamespace(km=list(pos_km))
        self.velocity = types.SimpleNamespace(km_per_s=list(vel_kms))


class FakeSeg:
    def __init__(self, pos, vel):
        self.pos, self.vel = list(pos), list(vel)

    def __add__(self, other):
        return FakeSeg([a + b for a, b in zip(self.pos, other.pos)], self.vel)

    def at(self, t):
        return _Vec(self.pos, self.vel)


class FakeEph:
    bodies = {
        "earth": ([EARTH_X_KM, 0.0, 0.0], [0.0, 29.78, 0.0]),
        "mars barycenter": ([2.0e8, 0.0, 0.0], [0.0, 24.0, 0.0]),
        "sun": ([1.0e6, 0.0, 0.0], [0.0, 0.01, 0.0]),
    }

    def __getitem__(self, key):
        if key not in self.bodies:
            raise KeyError(key)
        return FakeSeg(*self.bodies[key])


class FakeTs:
    def from_datetime(self, dt):
        return types.SimpleNamespace(tdb=2451545.0 + (dt - J2000).total_seconds() / 86400.0)


def install_fake_skyfield():
    api = types.ModuleType("skyfield.api")
    api.load = types.SimpleNamespace(timescale=lambda: FakeTs())
    api.wgs84 = types.SimpleNamespace(
        latlon=lambda lat, lon, elevation_m=0.0: FakeSeg([lat, lon, elevation_m / 1000.0], [0.0, 0.0, 0.0]))
    jpl = types.ModuleType("skyfield.jpllib")
    jpl.SpiceKernel = lambda path: FakeEph()
    pkg = types.ModuleType("skyfield")
    pkg.api, pkg.jpllib = api, jpl
    sys.modules.update({"skyfield": pkg, "skyfield.api": api, "skyfield.jpllib": jpl})


class HomeTestCase(unittest.TestCase):
    """Fresh ASTRO_TAGGER_HOME per test, with config, agents, and a fake indexed kernel."""

    site = {"name": "TestSite", "lat_deg": 40.0, "lon_deg": -105.0, "alt_m": 1600.0}

    def setUp(self):
        self._saved_modules = {k: sys.modules.get(k) for k in ("skyfield", "skyfield.api", "skyfield.jpllib")}
        self._saved_env = os.environ.get("ASTRO_TAGGER_HOME")
        self._saved_bodies = dict(FakeEph.bodies)
        install_fake_skyfield()

        self.home = Path(tempfile.mkdtemp())
        os.environ["ASTRO_TAGGER_HOME"] = str(self.home)
        (self.home / "config").mkdir()
        (self.home / "kernels").mkdir()
        self.write_config({"site": {**self.site, "agent_id": "CENTRAL"}})
        shutil.copy(REPO / "config" / "agents.json", self.home / "config" / "agents.json")

        kernel = b"fake kernel bytes"
        (self.home / "kernels" / "de440s.bsp").write_bytes(kernel)
        self.write_index({"de440s.bsp": {
            "sha256": hashlib.sha256(kernel).hexdigest(), "bytes": len(kernel),
            "start_jd": 2396758.5, "end_jd": 2506331.5}})

        from astro_tagger import ephemeris
        ephemeris._ts = None
        ephemeris._kernels.clear()

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)
        if self._saved_env is None:
            os.environ.pop("ASTRO_TAGGER_HOME", None)
        else:
            os.environ["ASTRO_TAGGER_HOME"] = self._saved_env
        FakeEph.bodies = self._saved_bodies
        for k, v in self._saved_modules.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v

    def write_config(self, data):
        (self.home / "config" / "config.json").write_text(json.dumps(data))

    def write_index(self, kernels):
        (self.home / "kernels" / "index.json").write_text(json.dumps({
            "schema": "kernel_index/v1",
            "policies": {"modern": ["de440s.bsp"], "longspan": ["de440s.bsp"]},
            "kernels": kernels}))

    def observer(self, agent=None, cli_site=None, travel_mode=None):
        from astro_tagger.config import load_config
        from astro_tagger.state import resolve_observer
        return resolve_observer(agent, load_config(cli_site), travel_mode=travel_mode)
