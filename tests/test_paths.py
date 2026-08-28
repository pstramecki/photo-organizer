"""Tests for filename-collision resolution and the app-data directory."""
from __future__ import annotations

import sys
from pathlib import Path

from photo_organizer.paths import app_dir, unique_dest


def test_unique_dest_returns_same_path_when_free(tmp_path):
    dest = tmp_path / 'photo.jpg'
    used: set[str] = set()

    assert unique_dest(dest, used) == dest
    assert str(dest) in used


def test_unique_dest_suffixes_when_path_exists_on_disk(tmp_path):
    dest = tmp_path / 'photo.jpg'
    dest.write_bytes(b'already here')

    result = unique_dest(dest, set())

    assert result != dest
    assert result.parent == dest.parent
    assert result.suffix == dest.suffix
    assert not result.exists()


def test_unique_dest_suffixes_when_path_already_claimed_in_used_set(tmp_path):
    dest = tmp_path / 'photo.jpg'
    used = {str(dest)}

    result = unique_dest(dest, used)

    assert result != dest
    assert str(result) in used


def test_unique_dest_never_returns_the_same_candidate_twice(tmp_path):
    used: set[str] = set()
    first = unique_dest(tmp_path / 'photo.jpg', used)
    second = unique_dest(tmp_path / 'photo.jpg', used)

    assert first != second


def test_app_dir_returns_a_path():
    assert isinstance(app_dir(), Path)


def test_app_dir_returns_executable_parent_when_frozen(monkeypatch):
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'executable', str(Path('/opt/PhotoOrganizer/PhotoOrganizer')))

    assert app_dir() == Path('/opt/PhotoOrganizer')
