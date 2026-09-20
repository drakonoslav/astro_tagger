"""Best-guess creation time for a file.

Preference order (first hit wins, not "earliest"): EXIF -> PDF metadata -> date in filename
-> file-system time. Times without a time zone are assumed UTC and flagged as such.
"""
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional


@dataclass(frozen=True)
class Stamp:
    dt: datetime            # timezone-aware UTC
    source: str             # override | exif | pdf | filename | filesystem
    timezone_assumed: bool  # True when the source carried no zone and UTC was assumed


_warned = set()


def _warn_once(key: str, msg: str) -> None:
    if key not in _warned:
        _warned.add(key)
        print(f"warning: {msg}", file=sys.stderr)


# ---------- EXIF ----------
_EXIF_KEYS = ("DateTimeOriginal", "DateTimeDigitized", "DateTime")
_EXIF_IFD = 0x8769   # the Exif sub-IFD, where DateTimeOriginal/Digitized live


def exif_datetime(path: str) -> Optional[datetime]:
    if os.path.splitext(path)[1].lower() not in (".jpg", ".jpeg", ".tif", ".tiff"):
        return None
    try:
        from PIL import ExifTags, Image
    except ImportError:
        _warn_once("pillow", "Pillow is not installed; EXIF timestamps are unavailable (pip install Pillow)")
        return None
    try:
        with Image.open(path) as im:
            exif = im.getexif()
            tags = {ExifTags.TAGS.get(k, k): v for k, v in exif.items()}
            try:
                tags.update({ExifTags.TAGS.get(k, k): v for k, v in exif.get_ifd(_EXIF_IFD).items()})
            except Exception:
                pass
    except Exception:
        return None
    for key in _EXIF_KEYS:
        s = tags.get(key)
        if isinstance(s, bytes):
            s = s.decode("ascii", "ignore")
        if isinstance(s, str):
            try:
                return datetime.strptime(s.strip().replace("/", ":").replace("-", ":"),
                                         "%Y:%m:%d %H:%M:%S").replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    return None


# ---------- PDF ----------
_PDF_DATE = re.compile(
    r"D:(\d{4})(\d{2})?(\d{2})?(\d{2})?(\d{2})?(\d{2})?(?:(Z)|([+-])(\d{2})'?(\d{2})?'?)?"
)


def parse_pdf_date(val) -> Optional[tuple]:
    """Parse a PDF date string. Returns (utc datetime, zone_was_given) or None."""
    m = _PDF_DATE.match(val) if isinstance(val, str) else None
    if not m:
        return None
    y, mo, d, hh, mm, ss = (int(g) if g else default for g, default in
                            zip(m.groups()[:6], (0, 1, 1, 0, 0, 0)))
    try:
        naive = datetime(y, mo, d, hh, mm, ss)
    except ValueError:
        return None
    if m.group(7):                                   # "Z"
        return naive.replace(tzinfo=timezone.utc), True
    if m.group(8):                                   # +hh'mm'
        offset = timedelta(hours=int(m.group(9)), minutes=int(m.group(10) or 0))
        if m.group(8) == "-":
            offset = -offset
        return (naive - offset).replace(tzinfo=timezone.utc), True
    return naive.replace(tzinfo=timezone.utc), False


def _pdf_stamp(path: str) -> Optional[Stamp]:
    if os.path.splitext(path)[1].lower() != ".pdf":
        return None
    try:
        import pypdf
    except ImportError:
        _warn_once("pypdf", "pypdf is not installed; PDF timestamps are unavailable (pip install pypdf)")
        return None
    try:
        with open(path, "rb") as f:
            info = pypdf.PdfReader(f).metadata or {}
            for key in ("/CreationDate", "/ModDate"):
                parsed = parse_pdf_date(info.get(key))
                if parsed:
                    return Stamp(parsed[0], "pdf", not parsed[1])
    except Exception:
        return None
    return None


# ---------- filename ----------
_FILENAME_PATTERNS = [
    r"(?P<y>20\d{2}|19\d{2})[-_]? (?P<m>\d{2})[-_]? (?P<d>\d{2})[ T_:-]? (?P<H>\d{2})[ _:-]?(?P<M>\d{2})[ _:-]?(?P<S>\d{2})",
    r"(?P<y>20\d{2}|19\d{2})[-_]? (?P<m>\d{2})[-_]? (?P<d>\d{2})",
]


def datetime_from_filename(path: str) -> Optional[datetime]:
    s = os.path.basename(path).replace(".", " ")
    for pat in _FILENAME_PATTERNS:
        m = re.search(pat, s, flags=re.IGNORECASE | re.VERBOSE)
        if not m:
            continue
        g = m.groupdict()
        try:
            return datetime(int(g["y"]), int(g["m"]), int(g["d"]),
                            int(g.get("H") or 0), int(g.get("M") or 0), int(g.get("S") or 0),
                            tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def fs_oldest_datetime(path: str) -> datetime:
    st = os.stat(path)   # Windows: st_ctime is creation time; Unix: metadata-change time
    return datetime.fromtimestamp(min(st.st_mtime, st.st_ctime), tz=timezone.utc)


def best_stamp_for_file(path: str) -> Stamp:
    dt = exif_datetime(path)
    if dt:
        return Stamp(dt, "exif", True)
    stamp = _pdf_stamp(path)
    if stamp:
        return stamp
    dt = datetime_from_filename(path)
    if dt:
        return Stamp(dt, "filename", True)
    return Stamp(fs_oldest_datetime(path), "filesystem", False)
