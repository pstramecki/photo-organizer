"""Tests for GPS EXIF extraction. No real exiftool binary needed --
exiftool calls are monkeypatched, same approach as test_dates.py.
"""
from __future__ import annotations

import subprocess

import pytest

from photo_organizer.dates import HAS_PIL
from photo_organizer.gps import get_gps


def test_get_gps_returns_none_without_exiftool_or_matching_pil_data(tmp_path):
    f = tmp_path / 'photo.jpg'
    f.write_bytes(b'not really a jpeg')

    assert get_gps(f, exiftool_path='') is None


def test_get_gps_parses_signed_decimal_output_from_exiftool(tmp_path, monkeypatch):
    f = tmp_path / 'photo.jpg'
    f.write_bytes(b'irrelevant')

    class FakeCompletedProcess:
        stdout = '48.8566\n-122.335\n'

    monkeypatch.setattr(subprocess, 'run', lambda *a, **kw: FakeCompletedProcess())

    assert get_gps(f, exiftool_path='exiftool') == (48.8566, -122.335)


def test_get_gps_returns_none_when_exiftool_errors(tmp_path, monkeypatch):
    f = tmp_path / 'photo.jpg'
    f.write_bytes(b'irrelevant')

    def raise_error(*a, **kw):
        raise OSError('exiftool not found')

    monkeypatch.setattr(subprocess, 'run', raise_error)

    assert get_gps(f, exiftool_path='exiftool') is None


def test_get_gps_treats_null_island_from_exiftool_as_no_gps(tmp_path, monkeypatch):
    f = tmp_path / 'photo.jpg'
    f.write_bytes(b'irrelevant')

    class FakeCompletedProcess:
        stdout = '0.0\n0.0\n'  # some devices write this instead of omitting the tag

    monkeypatch.setattr(subprocess, 'run', lambda *a, **kw: FakeCompletedProcess())

    assert get_gps(f, exiftool_path='exiftool') is None


def test_get_gps_returns_none_when_exiftool_output_is_incomplete(tmp_path, monkeypatch):
    f = tmp_path / 'photo.jpg'
    f.write_bytes(b'irrelevant')

    class OneLineCompletedProcess:
        stdout = '48.8566\n'  # missing the longitude line -- no GPS tag at all

    monkeypatch.setattr(subprocess, 'run', lambda *a, **kw: OneLineCompletedProcess())

    assert get_gps(f, exiftool_path='exiftool') is None


@pytest.mark.skipif(not HAS_PIL, reason='Pillow not installed')
def test_get_gps_reads_dms_coordinates_via_pillow_fallback(tmp_path):
    from PIL import Image

    img = Image.new('RGB', (2, 2), color='blue')
    exif = img.getexif()
    # Paris, roughly: 48 51' 24" N, 2 21' 3" E
    exif[0x8825] = {1: 'N', 2: (48.0, 51.0, 24.0), 3: 'E', 4: (2.0, 21.0, 3.0)}
    f = tmp_path / 'photo.jpg'
    img.save(f, exif=exif)

    lat, lon = get_gps(f, exiftool_path='')

    assert lat == pytest.approx(48.8566, abs=1e-3)
    assert lon == pytest.approx(2.3508, abs=1e-3)


@pytest.mark.skipif(not HAS_PIL, reason='Pillow not installed')
def test_get_gps_applies_negative_sign_for_south_and_west(tmp_path):
    from PIL import Image

    img = Image.new('RGB', (2, 2), color='green')
    exif = img.getexif()
    exif[0x8825] = {1: 'S', 2: (33.0, 52.0, 0.0), 3: 'W', 4: (70.0, 40.0, 0.0)}
    f = tmp_path / 'photo.jpg'
    img.save(f, exif=exif)

    lat, lon = get_gps(f, exiftool_path='')

    assert lat < 0
    assert lon < 0


@pytest.mark.skipif(not HAS_PIL, reason='Pillow not installed')
def test_get_gps_treats_null_island_from_pillow_as_no_gps(tmp_path):
    from PIL import Image

    img = Image.new('RGB', (2, 2), color='purple')
    exif = img.getexif()
    exif[0x8825] = {1: 'N', 2: (0.0, 0.0, 0.0), 3: 'E', 4: (0.0, 0.0, 0.0)}
    f = tmp_path / 'photo.jpg'
    img.save(f, exif=exif)

    assert get_gps(f, exiftool_path='') is None


@pytest.mark.skipif(not HAS_PIL, reason='Pillow not installed')
def test_get_gps_returns_none_when_no_gps_ifd_present(tmp_path):
    from PIL import Image

    img = Image.new('RGB', (2, 2), color='yellow')
    f = tmp_path / 'photo.jpg'
    img.save(f)  # no EXIF at all

    assert get_gps(f, exiftool_path='') is None
