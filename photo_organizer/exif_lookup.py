"""Combined date + GPS lookup: one exiftool subprocess call instead of two
when both are needed (group_by_location mode) -- process-spawn overhead
adds up over a large library. Falls back to dates.get_file_date() /
gps.get_gps() (Pillow / mtime) for whichever piece exiftool didn't
provide, or for the whole thing when exiftool isn't configured.

-f (force-print) is essential here: with 4 tags requested but most files
carrying only some of them, plain -s3 would omit missing tags entirely and
the remaining lines could no longer be matched positionally to which tag
they came from. -f prints "-" for a tag exiftool couldn't read, keeping
one line per requested tag always.

CreateDate is requested alongside DateTimeOriginal for the same reason
dates.py does -- DateTimeOriginal is EXIF-only and doesn't exist in
QuickTime/MP4 metadata, so a video would otherwise never get a real date
from this combined call at all. DateTimeOriginal is preferred when both
resolve.

The Pillow fallback also does one combined Image.open() rather than calling
dates.get_file_date() and gps.get_gps() separately (each of which would
open and EXIF-decode the same file again).
"""
from __future__ import annotations

import subprocess  # nosec B404 -- only ever invoked with a fixed, user-configured exiftool path
from datetime import datetime
from pathlib import Path

from .dates import HAS_PIL, PIL_READABLE, _date_from_pil_exif, parse_exif_datetime
from .gps import NULL_ISLAND, _gps_from_pil_exif
from .models import DateSource

if HAS_PIL:
    from PIL import Image

_MISSING = ('', '-')  # exiftool -f prints "-" for a tag it couldn't read


def get_date_and_gps(path: Path, exiftool_path: str) -> tuple[datetime, DateSource, tuple[float, float] | None]:
    """Return (date, source, gps) -- gps is None if unresolved."""
    dt: datetime | None = None
    source = DateSource.MTIME
    gps: tuple[float, float] | None = None

    if exiftool_path:
        try:
            proc = subprocess.run(  # nosec B603 -- exiftool_path is app-configured, args are fixed/path-only
                [exiftool_path, '-f', '-s3', '-n', '-DateTimeOriginal', '-CreateDate',
                 '-GPSLatitude', '-GPSLongitude', str(path)],
                capture_output=True, text=True, timeout=20,
            )
            lines = (proc.stdout or '').splitlines()
            if len(lines) == 4:
                orig_raw, created_raw, lat_raw, lon_raw = (line.strip() for line in lines)
                for date_raw in (orig_raw, created_raw):
                    if date_raw not in _MISSING:
                        parsed = parse_exif_datetime(date_raw)
                        if parsed:
                            dt, source = parsed, DateSource.EXIF
                            break
                if lat_raw not in _MISSING and lon_raw not in _MISSING:
                    try:
                        coords = float(lat_raw), float(lon_raw)
                        if coords != NULL_ISLAND:
                            gps = coords
                    except ValueError:
                        pass
        except (OSError, subprocess.SubprocessError):
            pass

    if (dt is None or gps is None) and HAS_PIL and path.suffix.lower() in PIL_READABLE:
        try:
            with Image.open(path) as img:
                exif = img.getexif()
                if dt is None:
                    pil_dt = _date_from_pil_exif(exif)
                    if pil_dt:
                        dt, source = pil_dt, DateSource.EXIF
                if gps is None:
                    gps = _gps_from_pil_exif(exif)
        # Same rationale as dates.py/gps.py's own Pillow fallbacks: any
        # decoder failure here just means "nothing more to extract".
        except Exception:  # nosec B110
            pass

    if dt is None:
        dt, source = datetime.fromtimestamp(path.stat().st_mtime), DateSource.MTIME

    return dt, source, gps
