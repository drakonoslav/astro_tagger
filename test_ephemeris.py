from datetime import datetime, timezone

from astro_tagger import ephemeris
from astro_tagger.errors import KernelError, NoCoverageError

from .support import HomeTestCase

INDEX = {
    "policies": {"modern": ["a.bsp", "b.bsp"], "legacy": ["c.bsp"]},
    "kernels": {
        "a.bsp": {"sha256": "x", "start_jd": 100, "end_jd": 200},
        "b.bsp": {"sha256": "x", "start_jd": 0, "end_jd": 1000},
        "c.bsp": {"sha256": "x", "start_jd": 500, "end_jd": 600},
    },
}


class ChooseKernelTests(HomeTestCase):
    def test_first_covering_kernel_in_policy_order_wins(self):
        self.assertEqual(ephemeris.choose_kernel(INDEX, "modern", 150), "a.bsp")
        self.assertEqual(ephemeris.choose_kernel(INDEX, "modern", 300), "b.bsp")

    def test_closest_picks_nearest_midpoint(self):
        self.assertEqual(ephemeris.choose_kernel(INDEX, "closest", 550), "c.bsp")
        self.assertEqual(ephemeris.choose_kernel(INDEX, "closest", 150), "a.bsp")

    def test_no_coverage_message_is_stable(self):
        with self.assertRaises(NoCoverageError) as cm:
            ephemeris.choose_kernel(INDEX, "legacy", 10)
        self.assertIn("No SPK ephemeris covers JD", str(cm.exception))

    def test_unknown_policy(self):
        with self.assertRaises(KernelError):
            ephemeris.choose_kernel(INDEX, "nope", 150)


class LoadTests(HomeTestCase):
    def test_load_returns_label_and_hash(self):
        e = ephemeris.load_ephemeris(datetime(2020, 1, 1, tzinfo=timezone.utc), "modern")
        self.assertEqual(e.label, "JPL DE440s")
        self.assertEqual(len(e.sha256), 64)

    def test_hash_mismatch_is_refused(self):
        (self.home / "kernels" / "de440s.bsp").write_bytes(b"tampered")
        with self.assertRaises(KernelError) as cm:
            ephemeris.load_ephemeris(datetime(2020, 1, 1, tzinfo=timezone.utc), "modern")
        self.assertIn("Hash mismatch", str(cm.exception))

    def test_out_of_range_date(self):
        with self.assertRaises(NoCoverageError):
            ephemeris.load_ephemeris(datetime(1700, 1, 1, tzinfo=timezone.utc), "modern")
