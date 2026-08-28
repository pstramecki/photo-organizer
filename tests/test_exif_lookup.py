"""Tests for the combined date+GPS exiftool lookup. No real exiftool
binary needed -- exiftool calls are monkeypatched, same approach as
test_dates.py/test_gps.py. The exact `-f -s3 -n` positional output this
mocks (and the DateTimeOriginal/CreateDate/GPS behavior it models) was
verified against a real exiftool binary while building this module,
including against a real hand-built MP4 to confirm CreateDate is what
QuickTime/MP4 files actually carry instead of DateTimeOriginal.
"""
from __future__ import annotations

import subprocess
from datetime import datetime

import pytest

from photo_organizer.dates import HAS_PIL
from photo_organizer.exif_lookup import get_date_and_gps
from photo_organizer.models import DateSource


class _FakeCompletedProcess:
    def __init__(self, stdout: str):
        self.stdout = stdout


def test_get_date_and_gps_parses_all_four_tags_from_one_call(tmp_path, monkeypatch):
    f = tmp_path / 'photo.jpg'
    f.write_bytes(b'irrelevant')
    calls = []

    def fake_run(args, **kw):
        calls.append(args)
        return _FakeCompletedProcess('2015:04:28 12:00:00\n-\n48.8566\n2.3522\n')

    monkeypatch.setattr(subprocess, 'run', fake_run)

    dt, source, gps = get_date_and_gps(f, exiftool_path='exiftool')

    assert dt == datetime(2015, 4, 28, 12, 0, 0)
    assert source == DateSource.EXIF
    assert gps == (48.8566, 2.3522)
    assert len(calls) == 1  # one subprocess call for date, GPS, and the video-date fallback


def test_get_date_and_gps_falls_back_to_createdate_for_a_video_with_no_datetimeoriginal(tmp_path, monkeypatch):
    # Regression: DateTimeOriginal is EXIF-only and doesn't exist in
    # QuickTime/MP4 metadata -- a video would otherwise never get a real
    # date from this combined call and would silently use mtime instead.
    f = tmp_path / 'video.mp4'
    f.write_bytes(b'irrelevant')

    monkeypatch.setattr(subprocess, 'run',
                         lambda *a, **kw: _FakeCompletedProcess('-\n2015:04:28 12:00:00\n48.8566\n2.3522\n'))

    dt, source, gps = get_date_and_gps(f, exiftool_path='exiftool')

    assert dt == datetime(2015, 4, 28, 12, 0, 0)
    assert source == DateSource.EXIF
    assert gps == (48.8566, 2.3522)


def test_get_date_and_gps_prefers_datetimeoriginal_over_createdate(tmp_path, monkeypatch):
    f = tmp_path / 'photo.jpg'
    f.write_bytes(b'irrelevant')

    monkeypatch.setattr(subprocess, 'run',
                         lambda *a, **kw: _FakeCompletedProcess(
                             '2019:07:04 10:00:00\n2019:07:04 09:00:00\n-\n-\n'))

    dt, source, gps = get_date_and_gps(f, exiftool_path='exiftool')

    assert dt == datetime(2019, 7, 4, 10, 0, 0)  # DateTimeOriginal wins


def test_get_date_and_gps_handles_dash_placeholder_for_missing_gps(tmp_path, monkeypatch):
    f = tmp_path / 'photo.jpg'
    f.write_bytes(b'irrelevant')

    monkeypatch.setattr(subprocess, 'run',
                         lambda *a, **kw: _FakeCompletedProcess('2018:01:02 03:04:05\n-\n-\n-\n'))

    dt, source, gps = get_date_and_gps(f, exiftool_path='exiftool')

    assert dt == datetime(2018, 1, 2, 3, 4, 5)
    assert source == DateSource.EXIF
    assert gps is None


def test_get_date_and_gps_handles_dash_placeholder_for_missing_date(tmp_path, monkeypatch):
    f = tmp_path / 'photo.jpg'
    f.write_bytes(b'irrelevant')

    monkeypatch.setattr(subprocess, 'run',
                         lambda *a, **kw: _FakeCompletedProcess('-\n-\n48.8566\n2.3522\n'))

    dt, source, gps = get_date_and_gps(f, exiftool_path='exiftool')

    assert source == DateSource.MTIME  # no date from exiftool -- falls back to mtime
    assert gps == (48.8566, 2.3522)


def test_get_date_and_gps_treats_null_island_as_no_gps(tmp_path, monkeypatch):
    f = tmp_path / 'photo.jpg'
    f.write_bytes(b'irrelevant')

    monkeypatch.setattr(subprocess, 'run',
                         lambda *a, **kw: _FakeCompletedProcess('2015:04:28 12:00:00\n-\n0.0\n0.0\n'))

    dt, source, gps = get_date_and_gps(f, exiftool_path='exiftool')

    assert source == DateSource.EXIF  # the date still resolved fine
    assert gps is None


def test_get_date_and_gps_falls_back_to_mtime_and_none_when_exiftool_finds_nothing(tmp_path, monkeypatch):
    f = tmp_path / 'photo.jpg'
    f.write_bytes(b'irrelevant')

    monkeypatch.setattr(subprocess, 'run', lambda *a, **kw: _FakeCompletedProcess('-\n-\n-\n-\n'))

    dt, source, gps = get_date_and_gps(f, exiftool_path='exiftool')

    assert source == DateSource.MTIME
    assert gps is None


def test_get_date_and_gps_falls_back_when_exiftool_errors(tmp_path, monkeypatch):
    f = tmp_path / 'photo.jpg'
    f.write_bytes(b'irrelevant')

    def raise_error(*a, **kw):
        raise OSError('exiftool not found')

    monkeypatch.setattr(subprocess, 'run', raise_error)

    dt, source, gps = get_date_and_gps(f, exiftool_path='exiftool')

    assert source == DateSource.MTIME
    assert gps is None


def test_get_date_and_gps_falls_back_when_gps_lines_are_not_numeric(tmp_path, monkeypatch):
    f = tmp_path / 'photo.jpg'
    f.write_bytes(b'irrelevant')

    # Malformed/unexpected exiftool output -- shouldn't crash the scan.
    monkeypatch.setattr(subprocess, 'run',
                         lambda *a, **kw: _FakeCompletedProcess(
                             '2015:04:28 12:00:00\n-\nnot-a-number\nalso-bad\n'))

    dt, source, gps = get_date_and_gps(f, exiftool_path='exiftool')

    assert source == DateSource.EXIF  # the date still parsed fine
    assert gps is None


def test_get_date_and_gps_falls_back_when_output_has_wrong_line_count(tmp_path, monkeypatch):
    f = tmp_path / 'photo.jpg'
    f.write_bytes(b'irrelevant')

    # Only 3 lines instead of the expected 4 -- can't be trusted positionally.
    monkeypatch.setattr(subprocess, 'run',
                         lambda *a, **kw: _FakeCompletedProcess('2015:04:28 12:00:00\n-\n48.8566\n'))

    dt, source, gps = get_date_and_gps(f, exiftool_path='exiftool')

    assert source == DateSource.MTIME
    assert gps is None


@pytest.mark.skipif(not HAS_PIL, reason='Pillow not installed')
def test_get_date_and_gps_reads_both_from_one_pillow_image_open_without_exiftool(tmp_path):
    from PIL import Image

    img = Image.new('RGB', (2, 2), color='red')
    exif = img.getexif()
    exif[36867] = '2018:01:02 03:04:05'  # DateTimeOriginal
    exif[0x8825] = {1: 'N', 2: (48.0, 51.0, 24.0), 3: 'E', 4: (2.0, 21.0, 3.0)}
    f = tmp_path / 'photo.jpg'
    img.save(f, exif=exif)

    dt, source, gps = get_date_and_gps(f, exiftool_path='')

    assert dt == datetime(2018, 1, 2, 3, 4, 5)
    assert source == DateSource.EXIF
    assert gps == pytest.approx((48.8566, 2.3508), abs=1e-3)


def test_get_date_and_gps_skips_exiftool_entirely_without_a_path(tmp_path, monkeypatch):
    f = tmp_path / 'photo.jpg'
    f.write_bytes(b'irrelevant')
    calls = []
    monkeypatch.setattr(subprocess, 'run', lambda *a, **kw: calls.append(1))

    dt, source, gps = get_date_and_gps(f, exiftool_path='')

    assert calls == []
    assert source == DateSource.MTIME
    assert gps is None
