"""Tests for EXIF-first date detection and its fallbacks. No real exiftool
binary or network access needed -- exiftool calls are monkeypatched.
"""
from __future__ import annotations

import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import pytest

from photo_organizer.dates import HAS_PIL, find_exiftool, get_file_date, parse_exif_datetime
from photo_organizer.models import DateSource


@pytest.mark.parametrize('raw,expected', [
    ('2020:03:03 16:29:01', datetime(2020, 3, 3, 16, 29, 1)),
    ('2020:03:03', datetime(2020, 3, 3)),
    ('  2020:03:03 16:29:01  ', datetime(2020, 3, 3, 16, 29, 1)),
])
def test_parse_exif_datetime_valid(raw, expected):
    assert parse_exif_datetime(raw) == expected


@pytest.mark.parametrize('raw', ['', 'not a date', '0000:00:00 00:00:00'])
def test_parse_exif_datetime_invalid_returns_none(raw):
    assert parse_exif_datetime(raw) is None


def test_get_file_date_falls_back_to_mtime_without_exiftool_or_matching_pil_data(tmp_path):
    f = tmp_path / 'photo.jpg'
    f.write_bytes(b'not really a jpeg')

    dt, source = get_file_date(f, exiftool_path='')

    assert source == DateSource.MTIME


def test_get_file_date_uses_exiftool_when_available(tmp_path, monkeypatch):
    f = tmp_path / 'photo.jpg'
    f.write_bytes(b'irrelevant')

    class FakeCompletedProcess:
        stdout = '2019:07:04 10:00:00\n-\n'  # DateTimeOriginal present, CreateDate missing

    monkeypatch.setattr(subprocess, 'run', lambda *a, **kw: FakeCompletedProcess())

    dt, source = get_file_date(f, exiftool_path='exiftool')

    assert source == DateSource.EXIF
    assert dt == datetime(2019, 7, 4, 10, 0, 0)


def test_get_file_date_falls_back_to_createdate_when_datetimeoriginal_missing(tmp_path, monkeypatch):
    # Regression: DateTimeOriginal is EXIF-only and doesn't exist in
    # QuickTime/MP4 metadata -- verified against a real exiftool binary and
    # a real video's CreateDate. Without this fallback, videos never got a
    # real exiftool date at all and silently used file mtime instead.
    f = tmp_path / 'video.mp4'
    f.write_bytes(b'irrelevant')

    class FakeCompletedProcess:
        stdout = '-\n2015:04:28 12:00:00\n'  # DateTimeOriginal missing, CreateDate present

    monkeypatch.setattr(subprocess, 'run', lambda *a, **kw: FakeCompletedProcess())

    dt, source = get_file_date(f, exiftool_path='exiftool')

    assert source == DateSource.EXIF
    assert dt == datetime(2015, 4, 28, 12, 0, 0)


def test_get_file_date_prefers_datetimeoriginal_over_createdate_when_both_present(tmp_path, monkeypatch):
    f = tmp_path / 'photo.jpg'
    f.write_bytes(b'irrelevant')

    class FakeCompletedProcess:
        stdout = '2019:07:04 10:00:00\n2019:07:04 09:00:00\n'  # deliberately different

    monkeypatch.setattr(subprocess, 'run', lambda *a, **kw: FakeCompletedProcess())

    dt, source = get_file_date(f, exiftool_path='exiftool')

    assert dt == datetime(2019, 7, 4, 10, 0, 0)  # DateTimeOriginal wins


def test_get_file_date_falls_back_when_exiftool_errors(tmp_path, monkeypatch):
    f = tmp_path / 'photo.jpg'
    f.write_bytes(b'irrelevant')

    def raise_error(*a, **kw):
        raise OSError('exiftool not found')

    monkeypatch.setattr(subprocess, 'run', raise_error)

    dt, source = get_file_date(f, exiftool_path='exiftool')

    assert source == DateSource.MTIME


def test_get_file_date_falls_back_when_exiftool_returns_nothing(tmp_path, monkeypatch):
    f = tmp_path / 'photo.jpg'
    f.write_bytes(b'irrelevant')

    class EmptyCompletedProcess:
        stdout = ''

    monkeypatch.setattr(subprocess, 'run', lambda *a, **kw: EmptyCompletedProcess())

    dt, source = get_file_date(f, exiftool_path='exiftool')

    assert source == DateSource.MTIME


@pytest.mark.skipif(not HAS_PIL, reason='Pillow not installed')
def test_get_file_date_reads_exif_via_pillow_fallback(tmp_path):
    from PIL import Image

    img = Image.new('RGB', (2, 2), color='red')
    exif = img.getexif()
    exif[36867] = '2018:01:02 03:04:05'  # DateTimeOriginal
    f = tmp_path / 'photo.jpg'
    img.save(f, exif=exif)

    dt, source = get_file_date(f, exiftool_path='')

    assert source == DateSource.EXIF
    assert dt == datetime(2018, 1, 2, 3, 4, 5)


def test_find_exiftool_prefers_the_path_lookup(monkeypatch):
    monkeypatch.setattr(shutil, 'which', lambda name: '/usr/bin/exiftool' if name == 'exiftool' else None)

    assert find_exiftool() == '/usr/bin/exiftool'


def test_find_exiftool_falls_back_to_known_install_locations(monkeypatch):
    monkeypatch.setattr(shutil, 'which', lambda name: None)
    monkeypatch.setattr(Path, 'exists', lambda self: str(self) == r'C:\Tools\ExifTool\exiftool.exe')

    assert find_exiftool() == r'C:\Tools\ExifTool\exiftool.exe'


def test_find_exiftool_returns_empty_string_when_not_found(monkeypatch):
    monkeypatch.setattr(shutil, 'which', lambda name: None)
    monkeypatch.setattr(Path, 'exists', lambda self: False)

    assert find_exiftool() == ''
