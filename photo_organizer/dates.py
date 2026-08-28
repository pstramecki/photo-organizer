"""EXIF-first date detection, with graceful fallbacks.

exiftool (external binary, https://exiftool.org) is tried first when a path
to it is given -- it reads EXIF from far more formats than Pillow, including
HEIC and videos. Pillow is a fallback for JPEG/PNG/TIFF EXIF when exiftool
isn't available. If neither works, the file's last-modified time is used.

Both DateTimeOriginal and CreateDate are requested: DateTimeOriginal is an
EXIF tag and simply doesn't exist in QuickTime/MP4 metadata, so a video
with no DateTimeOriginal at all would silently fall through to mtime
without also trying CreateDate (its QuickTime/MP4 equivalent) -- verified
against a real exiftool binary and a real video's CreateDate while
building this. DateTimeOriginal is preferred when both are present.
"""
from __future__ import annotations

import re
import shutil
import subprocess  # nosec B404 -- only ever invoked with a fixed, user-configured exiftool path, see get_file_date()
from datetime import datetime
from pathlib import Path

from .models import DateSource

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

PIL_READABLE = {'.jpg', '.jpeg', '.png', '.tiff'}
EXIF_DATETIME_ORIGINAL = 36867
EXIF_DATETIME = 306

EXIF_DATE_RE = re.compile(r'^(\d{4}):(\d{2}):(\d{2})(?:\s+(\d{2}):(\d{2}):(\d{2}))?')


def find_exiftool() -> str:
    """Locate exiftool on PATH or in common Windows install locations."""
    found = shutil.which('exiftool') or shutil.which('exiftool.exe')
    if found:
        return found
    for candidate in (
        r'C:\Program Files\exiftool\exiftool.exe',
        r'C:\Program Files (x86)\exiftool\exiftool.exe',
        r'C:\Tools\ExifTool\exiftool.exe',
    ):
        if Path(candidate).exists():
            return candidate
    return ''


def parse_exif_datetime(raw: str) -> datetime | None:
    """Parse exiftool/EXIF-style "YYYY:MM:DD[ HH:MM:SS]" into a datetime."""
    m = EXIF_DATE_RE.match(raw.strip())
    if not m:
        return None
    y, mo, d, h, mi, s = m.groups()
    try:
        if h is not None:
            return datetime(int(y), int(mo), int(d), int(h), int(mi), int(s))
        return datetime(int(y), int(mo), int(d))
    except ValueError:
        return None


def _date_from_pil_exif(exif) -> datetime | None:
    """Extract the date from an already-opened Pillow Exif object -- shared
    with exif_lookup.py so a combined date+GPS lookup only opens the image
    once."""
    raw = exif.get(EXIF_DATETIME_ORIGINAL) or exif.get(EXIF_DATETIME)
    return parse_exif_datetime(str(raw)) if raw else None


def get_file_date(path: Path, exiftool_path: str = '') -> tuple[datetime, DateSource]:
    """Return (datetime, source). Tries exiftool, then Pillow, then mtime."""
    if exiftool_path:
        try:
            # -f keeps the two tags positionally distinguishable even when
            # only one of them resolves (see module docstring).
            proc = subprocess.run(  # nosec B603 -- exiftool_path is app-configured, args are fixed/path-only
                [exiftool_path, '-f', '-s3', '-DateTimeOriginal', '-CreateDate', str(path)],
                capture_output=True, text=True, timeout=20,
            )
            lines = (proc.stdout or '').splitlines()
            if len(lines) == 2:
                for raw in (line.strip() for line in lines):
                    if raw and raw != '-':
                        dt = parse_exif_datetime(raw)
                        if dt:
                            return dt, DateSource.EXIF
        except (OSError, subprocess.SubprocessError):
            pass

    if HAS_PIL and path.suffix.lower() in PIL_READABLE:
        try:
            with Image.open(path) as img:
                dt = _date_from_pil_exif(img.getexif())
                if dt:
                    return dt, DateSource.EXIF
        # Pillow can raise many decoder-specific exception types on malformed
        # images; any failure here just means "fall back to mtime" below.
        except Exception:  # nosec B110
            pass

    return datetime.fromtimestamp(path.stat().st_mtime), DateSource.MTIME
