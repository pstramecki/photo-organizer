"""Tests for SHA-256 hashing and the JSON-backed duplicate database."""
from __future__ import annotations

import hashlib

from photo_organizer.hashdb import HashDb, hash_file


def test_hash_file_matches_hashlib_reference(tmp_path):
    f = tmp_path / 'a.bin'
    f.write_bytes(b'hello world')
    assert hash_file(f) == hashlib.sha256(b'hello world').hexdigest()


def test_hash_file_reads_in_chunks_for_large_files(tmp_path):
    f = tmp_path / 'big.bin'
    content = b'x' * 5000
    f.write_bytes(content)
    assert hash_file(f, chunk_size=64) == hashlib.sha256(content).hexdigest()


def test_hashdb_round_trips_through_disk(tmp_path):
    db = HashDb(tmp_path)
    db.add('deadbeef', str(tmp_path / 'photo.jpg'))
    db.save()

    reloaded = HashDb(tmp_path)
    reloaded.load()

    assert 'deadbeef' in reloaded
    assert reloaded.data['deadbeef'] == str(tmp_path / 'photo.jpg')


def test_hashdb_load_missing_file_is_a_noop(tmp_path):
    db = HashDb(tmp_path)
    db.load()
    assert db.data == {}


def test_hashdb_load_corrupt_json_falls_back_to_empty(tmp_path):
    (tmp_path / 'hashes.json').write_text('{not valid json', encoding='utf-8')
    db = HashDb(tmp_path)
    db.load()
    assert db.data == {}


def test_hashdb_load_empty_file_is_a_noop(tmp_path):
    (tmp_path / 'hashes.json').write_text('', encoding='utf-8')
    db = HashDb(tmp_path)
    db.load()
    assert db.data == {}


def test_hashdb_contains(tmp_path):
    db = HashDb(tmp_path)
    db.add('abc123', 'somewhere')
    assert 'abc123' in db
    assert 'nope' not in db
