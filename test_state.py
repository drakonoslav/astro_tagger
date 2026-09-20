import json
from datetime import datetime, timezone

from astro_tagger.config import Config, load_config
from astro_tagger.errors import ConfigError, PlaceholderRequired, SanityError
from astro_tagger.frames import body_fixed_frame, canonical_body
from astro_tagger.state import compute_state

from .support import EARTH_X_KM, FakeEph, HomeTestCase

T = datetime(2020, 1, 1, tzinfo=timezone.utc)


class StateTests(HomeTestCase):
    def test_earth_site_record_and_frame_names(self):
        rec = compute_state(T, "modern", self.observer())
        self.assertEqual(rec["type"], "state/v2")
        self.assertEqual(rec["method"], "earth_topocenter")
        self.assertEqual(rec["state"]["frame"], "BCRS")
        self.assertEqual((rec["state"]["origin"], rec["state"]["axes"], rec["state"]["time_scale"]),
                         ("SSB", "ICRS", "TDB"))
        self.assertEqual(rec["frames_present"], ["BCRS", "ITRS", "Local_ENU"])
        self.assertEqual(rec["planetary"]["body_fixed_frame"], "ITRS")
        self.assertEqual(rec["planetary"]["geodetic_datum"], "WGS84")
        blob = json.dumps(rec)
        self.assertNotIn("ITRF/WGS84", blob)
        self.assertNotIn("GCRS", blob)

    def test_agent_moves_the_observer(self):
        central = compute_state(T, "modern", self.observer())
        base = compute_state(T, "modern", self.observer("Base-Planetoid"))
        self.assertNotEqual(central["state"]["r_m"], base["state"]["r_m"])
        self.assertAlmostEqual(central["state"]["r_m"][0], (EARTH_X_KM + 40.0) * 1000.0)
        self.assertAlmostEqual(base["state"]["r_m"][0], (EARTH_X_KM - 77.85) * 1000.0)
        self.assertEqual(base["planetary"]["latlonh"]["lat_deg"], -77.85)

    def test_site_precedence_cli_over_agent_over_config(self):
        rec = compute_state(T, "modern", self.observer("Base-Planetoid", cli_site={"lat_deg": 10.0}))
        self.assertAlmostEqual(rec["state"]["r_m"][0], (EARTH_X_KM + 10.0) * 1000.0)
        # agent's lon/alt still apply where the CLI is silent
        self.assertEqual(rec["planetary"]["latlonh"]["lon_deg"], 166.67)

    def test_altitude_alias_layers_correctly(self):
        cfg = Config({"lat_deg": 1, "lon_deg": 2, "alt_m": 100}, {}, "CENTRAL")
        self.assertEqual(cfg.earth_site({"h_m": 5}).h_m, 5.0)
        self.assertEqual(cfg.earth_site(None).h_m, 100.0)

    def test_mars_base_is_labelled_an_approximation(self):
        rec = compute_state(T, "modern", self.observer("MarsBase-Alpha"))
        self.assertEqual(rec["method"], "system_barycenter")
        self.assertFalse(rec["site_offset_applied"])
        self.assertEqual(rec["state"]["r_m"], [2.0e11, 0.0, 0.0])
        self.assertEqual(rec["frames_present"], ["BCRS", "IAU_MARS"])
        self.assertFalse(rec["planetary"]["site"]["applied_to_state"])

    def test_legacy_iau_body_names_normalise(self):
        self.assertEqual(canonical_body("IAU_MARS"), "MARS")
        self.assertEqual(canonical_body("mars"), "MARS")
        self.assertEqual(body_fixed_frame("MARS"), "IAU_MARS")
        self.assertEqual(body_fixed_frame("EARTH"), "ITRS")
        with self.assertRaises(ConfigError):
            canonical_body("KRYPTON")

    def test_vessel_needs_explicit_placeholder(self):
        obs = self.observer("Voyager-2")
        with self.assertRaises(PlaceholderRequired):
            compute_state(T, "modern", obs)
        rec = compute_state(T, "modern", obs, allow_placeholder=True)
        self.assertEqual(rec["method"], "placeholder_earth_site")
        self.assertTrue(rec["observer_is_placeholder"])
        self.assertIn("extensions", rec)

    def test_unknown_agent(self):
        with self.assertRaises(ConfigError):
            self.observer("Nope")
        self.write_config({"site": {**self.site, "agent_id": "Nope"}})
        self.assertEqual(self.observer().role, "CENTRAL")   # unnamed default falls back

    def test_cli_site_flags_rejected_for_non_earth_agent(self):
        with self.assertRaises(ConfigError):
            self.observer("MarsBase-Alpha", cli_site={"lat_deg": 1.0})

    def test_missing_and_unedited_config(self):
        (self.home / "config" / "config.json").unlink()
        with self.assertRaises(ConfigError):
            load_config()
        self.assertEqual(load_config({"lat_deg": 1.0, "lon_deg": 2.0}).earth_site().lat_deg, 1.0)
        self.write_config({"site": {"lat_deg": None, "lon_deg": None, "alt_m": 0.0}})
        with self.assertRaises(ConfigError):
            load_config().earth_site()

    def test_sanity_check(self):
        FakeEph.bodies = {**FakeEph.bodies, "earth": ([1.0e5, 0.0, 0.0], [0.0, 29.78, 0.0])}
        with self.assertRaises(SanityError):
            compute_state(T, "modern", self.observer())
        rec = compute_state(T, "modern", self.observer(), sanity=False)
        self.assertEqual(rec["method"], "earth_topocenter")
