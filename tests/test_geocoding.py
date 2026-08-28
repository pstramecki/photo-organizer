"""Tests for offline reverse geocoding. Uses the real reverse_geocoder
lookup (it's a local dataset, no network) except where noted."""
from __future__ import annotations

import importlib
import sys

import pytest

from photo_organizer.geocoding import HAS_GEOCODER, city_for


@pytest.mark.skipif(not HAS_GEOCODER, reason='reverse_geocoder not installed')
def test_city_for_resolves_a_well_known_coordinate():
    assert city_for(48.8566, 2.3522) == 'Paris'


@pytest.mark.skipif(not HAS_GEOCODER, reason='reverse_geocoder not installed')
def test_city_for_returns_a_string_for_a_remote_ocean_coordinate():
    # No city is truly "at" this point, but reverse_geocoder always returns
    # its single nearest match rather than nothing -- confirms city_for()
    # doesn't crash on an edge-case input.
    assert isinstance(city_for(0.0, -140.0), str)


def test_city_for_returns_none_when_geocoder_unavailable(monkeypatch):
    monkeypatch.setattr('photo_organizer.geocoding.HAS_GEOCODER', False)
    assert city_for(48.8566, 2.3522) is None


def test_city_for_returns_none_when_lookup_raises(monkeypatch):
    rg = pytest.importorskip('reverse_geocoder')

    def raise_error(coord):
        raise RuntimeError('dataset not loaded')

    monkeypatch.setattr('photo_organizer.geocoding.HAS_GEOCODER', True)
    monkeypatch.setattr(rg, 'search', raise_error)

    assert city_for(48.8566, 2.3522) is None


def test_city_for_does_not_import_reverse_geocoder_at_module_load(monkeypatch):
    # HAS_GEOCODER must be derivable without importing the (numpy/scipy-heavy)
    # package -- see the module docstring for why this matters for startup time.
    monkeypatch.delitem(sys.modules, 'reverse_geocoder', raising=False)
    monkeypatch.delitem(sys.modules, 'photo_organizer.geocoding', raising=False)
    importlib.import_module('photo_organizer.geocoding')

    assert 'reverse_geocoder' not in sys.modules
