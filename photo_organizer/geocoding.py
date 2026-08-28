"""Reverse geocoding: turn GPS coordinates into a city name, entirely
offline (no API key, no network call -- a photo's location never leaves
your machine). Needs the optional `reverse_geocoder` package (pulls in
numpy/scipy and a bundled ~35k-city dataset); without it, location
grouping in the planner is simply skipped.

The import itself is deferred to city_for() rather than done at module
load: reverse_geocoder pulls in numpy/scipy, and every current build
bundles it (see --collect-all reverse_geocoder in the build scripts), so
importing it eagerly here would add that startup cost to every launch of
the packaged app even for users who never tick "Group by location".
HAS_GEOCODER only checks the package is *findable* -- cheap, no import.
"""
from __future__ import annotations

import importlib.util

HAS_GEOCODER = importlib.util.find_spec('reverse_geocoder') is not None


def city_for(lat: float, lon: float) -> str | None:
    """Nearest city name for a coordinate pair, or None if unavailable."""
    if not HAS_GEOCODER:
        return None
    try:
        import reverse_geocoder as rg
        result = rg.search((lat, lon))[0]
        return result.get('name') or None
    # reverse_geocoder ships no documented exception type for lookup
    # failures; degrade to "no location" rather than aborting the run.
    except Exception:  # nosec B110
        return None
