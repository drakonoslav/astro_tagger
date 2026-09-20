import os
import tempfile
import unittest
from datetime import datetime, timezone

from astro_tagger import timestamps as ts


class FilenameTests(unittest.TestCase):
    def test_date_and_time(self):
        self.assertEqual(ts.datetime_from_filename("IMG_20200102_030405.jpg"),
                         datetime(2020, 1, 2, 3, 4, 5, tzinfo=timezone.utc))

    def test_date_only_with_separators(self):
        self.assertEqual(ts.datetime_from_filename("scan 1978-06-12.pdf"),
                         datetime(1978, 6, 12, tzinfo=timezone.utc))

    def test_impossible_date_is_ignored(self):
        self.assertIsNone(ts.datetime_from_filename("file_20231301.jpg"))


class PdfDateTests(unittest.TestCase):
    def test_offset_is_honoured(self):
        self.assertEqual(ts.parse_pdf_date("D:20200101120000+02'00'"),
                         (datetime(2020, 1, 1, 10, tzinfo=timezone.utc), True))
        self.assertEqual(ts.parse_pdf_date("D:20200101120000-05'30'"),
                         (datetime(2020, 1, 1, 17, 30, tzinfo=timezone.utc), True))

    def test_z_and_missing_zone(self):
        self.assertEqual(ts.parse_pdf_date("D:20200101120000Z"),
                         (datetime(2020, 1, 1, 12, tzinfo=timezone.utc), True))
        self.assertEqual(ts.parse_pdf_date("D:20200101120000"),
                         (datetime(2020, 1, 1, 12, tzinfo=timezone.utc), False))

    def test_partial_and_malformed(self):
        self.assertEqual(ts.parse_pdf_date("D:2020")[0], datetime(2020, 1, 1, tzinfo=timezone.utc))
        self.assertIsNone(ts.parse_pdf_date("garbage"))
        self.assertIsNone(ts.parse_pdf_date(None))


class ExifTests(unittest.TestCase):
    def test_capture_time_lives_in_the_exif_subifd(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow not installed")
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "x.jpg")
            exif = Image.Exif()
            exif[0x0132] = "2001:02:03 04:05:06"                    # DateTime (IFD0)
            exif.get_ifd(0x8769)[0x9003] = "1999:12:31 23:59:58"    # DateTimeOriginal (Exif sub-IFD)
            Image.new("RGB", (4, 4)).save(path, exif=exif)
            stamp = ts.best_stamp_for_file(path)
            self.assertEqual(stamp.source, "exif")
            self.assertEqual(stamp.dt, datetime(1999, 12, 31, 23, 59, 58, tzinfo=timezone.utc))
            self.assertTrue(stamp.timezone_assumed)

    def test_filesystem_fallback(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "nothing.bin")
            with open(path, "wb") as f:
                f.write(b"x")
            stamp = ts.best_stamp_for_file(path)
            self.assertEqual(stamp.source, "filesystem")
            self.assertFalse(stamp.timezone_assumed)


if __name__ == "__main__":
    unittest.main()
