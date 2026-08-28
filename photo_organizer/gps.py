"""GPS coordinate extraction from EXIF.

exiftool is tried first when a path to it is given -- it reads GPS from far
more formats than Pillow, including HEIC and videos. Pillow is a fallback
for JPEG/PNG/TIFF. Returns decimal degrees already signed by hemisphere
(south/west negative) -- see geocoding.py for turning that into a place
name.
"""
from __future__ import annotations

import subprocess  # nosec B404 -- only ever invoked with a fixed, user-configured exiftool path
from pathlib import Path

from .dates import HAS_PIL, PIL_READABLE

if HAS_PIL:
    from PIL import Image

# (0, 0) -- off the coast of West Africa -- is what some buggy GPS modules/
# apps write instead of omitting the tag when a fix was never acquired.
# Treated as "no GPS", not a real location.
NULL_ISLAND = (0.0, 0.0)


def _dms_to_decimal(dms: tuple[float, float, float], ref: str) -> float:
    degrees, minutes, seconds = (float(v) for v in dms)
    decimal = degrees + minutes / 60 + seconds / 3600
    return -decimal if ref in ('S', 'W') else decimal


def _gps_from_pil_exif(exif) -> tuple[float, float] | None:
    """Extract GPS from an already-opened Pillow Exif object -- shared with
    exif_lookup.py so a combined date+GPS lookup only opens the image once."""
    gps_ifd = exif.get_ifd(0x8825)  # GPS IFD pointer tag
    lat, lat_ref = gps_ifd.get(2), gps_ifd.get(1)
    lon, lon_ref = gps_ifd.get(4), gps_ifd.get(3)
    if lat and lat_ref and lon and lon_ref:
        coords = _dms_to_decimal(lat, lat_ref), _dms_to_decimal(lon, lon_ref)
        return None if coords == NULL_ISLAND else coords
    return None


def get_gps(path: Path, exiftool_path: str = '') -> tuple[float, float] | None:
    """Return (lat, lon) in decimal degrees, or None if the file has no GPS EXIF."""
    if exiftool_path:
        try:
            # -n on the Composite GPS tags yields signed decimal degrees directly
            # (no separate GPS*Ref parsing needed), one line each for lat/lon.
            proc = subprocess.run(  # nosec B603 -- exiftool_path is app-configured, args are fixed/path-only
                [exiftool_path, '-s3', '-n', '-GPSLatitude', '-GPSLongitude', str(path)],
                capture_output=True, text=True, timeout=20,
            )
            lines = [line.strip() for line in (proc.stdout or '').splitlines() if line.strip()]
            if len(lines) == 2:
                coords = float(lines[0]), float(lines[1])
                if coords != NULL_ISLAND:
                    return coords
        except (OSError, subprocess.SubprocessError, ValueError):
            pass

    if HAS_PIL and path.suffix.lower() in PIL_READABLE:
        try:
            with Image.open(path) as img:
                gps = _gps_from_pil_exif(img.getexif())
                if gps:
                    return gps
        # Same rationale as dates.py's Pillow fallback: any decoder failure
        # here just means "no GPS data available", not a security concern.
        except Exception:  # nosec B110
            pass

    return None
