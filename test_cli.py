import hashlib
import io
import json
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from unittest import mock

from astro_tagger import cli
from astro_tagger.tag import expand_paths
from astro_tagger.timestamps import Stamp

from .support import HomeTestCase


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        try:
            code = cli.main(list(argv))
        except SystemExit as e:
            code = e.code
    return code, out.getvalue(), err.getvalue()


class TagTests(HomeTestCase):
    def make(self, name, data=b"hello"):
        p = self.home / name
        p.write_bytes(data)
        return p

    def test_sidecar_contents(self):
        f = self.make("IMG_20200101_123000.jpg", b"not really a jpeg")
        code, out, err = run("tag", str(f), "--label")
        self.assertEqual(code, 0, err)
        sc = json.loads((self.home / "IMG_20200101_123000.jpg.astro.json").read_text())
        self.assertEqual(sc["type"], "astro_sidecar/v2")
        self.assertEqual(sc["file"]["sha256"], hashlib.sha256(b"not really a jpeg").hexdigest())
        self.assertEqual(sc["timestamp"], {"utc": "2020-01-01T12:30:00Z", "source": "filename",
                                           "timezone_assumed": True})
        self.assertEqual(sc["state"]["type"], "state/v2")
        self.assertTrue((self.home / "IMG_20200101_123000.jpg.label.txt").exists())
        self.assertIn("source: filename", out)

    def test_utc_override_is_recorded(self):
        f = self.make("plain.bin")
        code, _, err = run("tag", str(f), "--utc", "1978-06-12T15:30:00Z")
        self.assertEqual(code, 0, err)
        sc = json.loads((self.home / "plain.bin.astro.json").read_text())
        self.assertEqual(sc["timestamp"]["source"], "override")
        self.assertFalse(sc["timestamp"]["timezone_assumed"])

    def test_agent_changes_the_sidecar_observer(self):
        f = self.make("a.bin")
        run("tag", str(f), "--utc", "2020-01-01T00:00:00Z")
        central = json.loads((self.home / "a.bin.astro.json").read_text())["state"]
        run("tag", str(f), "--utc", "2020-01-01T00:00:00Z", "--agent", "Base-Planetoid")
        base = json.loads((self.home / "a.bin.astro.json").read_text())["state"]
        self.assertNotEqual(central["state"]["r_m"], base["state"]["r_m"])
        self.assertEqual(base["agent"]["id"], "Base-Planetoid")
        run("tag", str(f), "--utc", "2020-01-01T00:00:00Z", "--agent", "MarsBase-Alpha")
        mars = json.loads((self.home / "a.bin.astro.json").read_text())["state"]
        self.assertEqual(mars["method"], "system_barycenter")

    def test_unknown_agent_is_an_error(self):
        f = self.make("b.bin")
        code, _, err = run("tag", str(f), "--agent", "Nope")
        self.assertEqual(code, 1)
        self.assertIn("Unknown agent", err)
        self.assertFalse((self.home / "b.bin.astro.json").exists())

    def test_uncovered_file_is_skipped_but_batch_continues(self):
        old, new = self.make("old.bin"), self.make("new.bin")
        stamps = {"old.bin": Stamp(datetime(1700, 1, 1, tzinfo=timezone.utc), "exif", True),
                  "new.bin": Stamp(datetime(2000, 1, 1, tzinfo=timezone.utc), "exif", True)}
        with mock.patch("astro_tagger.tag.best_stamp_for_file", lambda p: stamps[p.rsplit("/", 1)[-1]]):
            code, _, err = run("tag", str(old), str(new))
        self.assertEqual(code, 1)
        self.assertIn("SKIPPED", err)
        self.assertFalse((self.home / "old.bin.astro.json").exists())
        self.assertTrue((self.home / "new.bin.astro.json").exists())

    def test_generated_files_are_not_retagged(self):
        f = self.make("c.bin")
        self.make("c.bin.astro.json")
        self.make("c.bin.label.txt")
        self.assertEqual(expand_paths([str(self.home / "c.bin*")]), [str(f)])

    def test_bad_utc_is_a_usage_error(self):
        f = self.make("d.bin")
        code, _, err = run("tag", str(f), "--utc", "yesterday")
        self.assertEqual(code, 2)


class StateCommandTests(HomeTestCase):
    def read_log(self, day):
        p = self.home / "logs" / f"states-{day}.jsonl"
        return [json.loads(line) for line in p.read_text().splitlines()]

    def test_single_record(self):
        code, out, err = run("state", "2020-01-01T00:00:00Z", "--agent", "CENTRAL")
        self.assertEqual(code, 0, err)
        (rec,) = self.read_log("2020-01-01")
        self.assertEqual(rec["type"], "state/v2")
        self.assertIn("Method:   earth_topocenter", out)

    def test_burst_rolls_over_midnight(self):
        code, _, err = run("state", "2020-01-01T23:59:59Z", "--fps", "1", "--frames", "3")
        self.assertEqual(code, 0, err)
        self.assertEqual(len(self.read_log("2020-01-01")), 1)
        self.assertEqual(len(self.read_log("2020-01-02")), 2)

    def test_burst_flags_must_come_together(self):
        code, _, _ = run("state", "--fps", "2")
        self.assertEqual(code, 2)

    def test_vessel_requires_flag(self):
        code, _, err = run("state", "2020-01-01T00:00:00Z", "--agent", "Voyager-2")
        self.assertEqual(code, 1)
        self.assertIn("--allow-placeholder", err)
        code, out, _ = run("state", "2020-01-01T00:00:00Z", "--agent", "Voyager-2", "--allow-placeholder")
        self.assertEqual(code, 0)
        self.assertIn("[PLACEHOLDER]", out)

    def test_check_command_passes_with_fake_setup(self):
        code, out, _ = run("check")
        self.assertEqual(code, 0, out)
        self.assertIn("agent MarsBase-Alpha: system_barycenter", out)
        self.assertIn("agent Voyager-2: needs --allow-placeholder", out)
