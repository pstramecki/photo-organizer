"""Tests for the core use case, exercised the same way any caller (the GUI,
or a future CLI) would: through analyze()/apply_plan() and a
ProgressReporter. No Tkinter anywhere in here -- that's the point of the
split.
"""
from __future__ import annotations

import hashlib
import os
from datetime import datetime
from pathlib import Path

import pytest

from photo_organizer import HashDb, MediaKind, Operation, PlanOperation, analyze, apply_plan
from photo_organizer.dates import get_file_date
from photo_organizer.planner import _consecutive_day_runs


class FakeReporter:
    """Minimal ProgressReporter -- records logs, lets a test flip `stop`."""

    def __init__(self, stop_after: int | None = None):
        self.logs: list[tuple[str, str | None]] = []
        self.stop = False
        self._stop_after = stop_after  # flips `stop` True on the Nth should_stop() call
        self._stop_checks = 0

    def log(self, msg: str = '', tag: str | None = None) -> None:
        self.logs.append((msg, tag))

    def set_status(self, text: str) -> None:
        pass

    def set_progress(self, value: int | None = None, maximum: int | None = None) -> None:
        pass

    def should_stop(self) -> bool:
        self._stop_checks += 1
        if self._stop_after is not None and self._stop_checks >= self._stop_after:
            self.stop = True
        return self.stop

    def has_log_containing(self, needle: str, tag: str | None = None) -> bool:
        return any(needle in msg and (tag is None or t == tag) for msg, t in self.logs)


def _make_file(path: Path, content: bytes = b'', mtime: datetime | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    if mtime is not None:
        ts = mtime.timestamp()
        os.utime(path, (ts, ts))
    return path


# ---- analyze(): categorization + dating ----

def test_analyze_plans_a_photo_by_mtime_year_month(tmp_path):
    in_dir, out_dir = tmp_path / 'in', tmp_path / 'out'
    _make_file(in_dir / 'a.jpg', b'photo-data', mtime=datetime(2020, 6, 15, 12, 0, 0))

    reporter = FakeReporter()
    plan = analyze(in_dir=in_dir, out_dir=out_dir, exiftool_path='', reporter=reporter)

    assert len(plan) == 1
    assert plan[0].kind == MediaKind.PHOTO
    assert plan[0].dest == out_dir / '2020' / '06' / 'a.jpg'
    assert reporter.has_log_containing('Photos using mtime   : 1')


def test_analyze_plans_a_photo_by_exif_date(tmp_path, monkeypatch):
    from photo_organizer.models import DateSource

    in_dir, out_dir = tmp_path / 'in', tmp_path / 'out'
    _make_file(in_dir / 'a.jpg', b'photo-data')

    monkeypatch.setattr('photo_organizer.planner.get_file_date',
                         lambda path, exiftool_path: (datetime(2017, 4, 9), DateSource.EXIF))

    reporter = FakeReporter()
    plan = analyze(in_dir=in_dir, out_dir=out_dir, exiftool_path='exiftool', reporter=reporter)

    assert plan[0].dest == out_dir / '2017' / '04' / 'a.jpg'
    assert reporter.has_log_containing('Photos using EXIF    : 1')


def test_analyze_plans_a_video_by_mtime_year(tmp_path):
    in_dir, out_dir = tmp_path / 'in', tmp_path / 'out'
    _make_file(in_dir / 'a.mp4', b'video-data', mtime=datetime(2021, 1, 1, 0, 0, 0))

    plan = analyze(in_dir=in_dir, out_dir=out_dir, exiftool_path='', reporter=FakeReporter())

    assert len(plan) == 1
    assert plan[0].kind == MediaKind.VIDEO
    assert plan[0].dest == out_dir / 'videos' / '2021' / 'a.mp4'


def test_analyze_skips_unrecognized_extensions(tmp_path):
    in_dir, out_dir = tmp_path / 'in', tmp_path / 'out'
    _make_file(in_dir / 'readme.txt', b'not media')

    reporter = FakeReporter()
    plan = analyze(in_dir=in_dir, out_dir=out_dir, exiftool_path='', reporter=reporter)

    assert plan == []
    assert reporter.has_log_containing('Skipped - unknown extension')


def test_analyze_returns_empty_plan_when_no_files(tmp_path):
    in_dir, out_dir = tmp_path / 'in', tmp_path / 'out'
    in_dir.mkdir()

    plan = analyze(in_dir=in_dir, out_dir=out_dir, exiftool_path='', reporter=FakeReporter())

    assert plan == []


def test_analyze_excludes_files_already_under_output_dir(tmp_path):
    in_dir, out_dir = tmp_path, tmp_path / 'out'
    _make_file(out_dir / '2019' / '01' / 'already-organized.jpg', b'x')
    _make_file(in_dir / 'new.jpg', b'y', mtime=datetime(2020, 3, 3))

    plan = analyze(in_dir=in_dir, out_dir=out_dir, exiftool_path='', reporter=FakeReporter())

    srcs = {op.src for op in plan}
    assert (out_dir / '2019' / '01' / 'already-organized.jpg') not in srcs
    assert len(plan) == 1


# ---- analyze(): duplicate detection ----

def test_analyze_flags_identical_content_within_the_same_run_as_duplicate(tmp_path):
    in_dir, out_dir = tmp_path / 'in', tmp_path / 'out'
    _make_file(in_dir / 'a.jpg', b'same-bytes', mtime=datetime(2020, 1, 1))
    _make_file(in_dir / 'b.jpg', b'same-bytes', mtime=datetime(2020, 1, 1))

    reporter = FakeReporter()
    plan = analyze(in_dir=in_dir, out_dir=out_dir, exiftool_path='', reporter=reporter)

    assert len(plan) == 1
    assert reporter.has_log_containing('[Duplicate]', tag='warn')


def test_analyze_flags_file_already_known_in_output_hash_db_as_duplicate(tmp_path):
    in_dir, out_dir = tmp_path / 'in', tmp_path / 'out'
    _make_file(in_dir / 'a.jpg', b'same-bytes', mtime=datetime(2020, 1, 1))
    out_dir.mkdir()

    db = HashDb(out_dir)
    digest = hashlib.sha256(b'same-bytes').hexdigest()
    db.add(digest, 'wherever-it-went.jpg')
    db.save()

    reporter = FakeReporter()
    plan = analyze(in_dir=in_dir, out_dir=out_dir, exiftool_path='', reporter=reporter)

    assert plan == []
    assert reporter.has_log_containing('[Duplicate]', tag='warn')


def test_analyze_resolves_filename_collision_between_different_files(tmp_path):
    in_dir, out_dir = tmp_path / 'in', tmp_path / 'out'
    _make_file(in_dir / 'sub1' / 'photo.jpg', b'content-one', mtime=datetime(2020, 6, 1))
    _make_file(in_dir / 'sub2' / 'photo.jpg', b'content-two', mtime=datetime(2020, 6, 1))

    plan = analyze(in_dir=in_dir, out_dir=out_dir, exiftool_path='', reporter=FakeReporter())

    assert len(plan) == 2
    dests = {op.dest for op in plan}
    assert len(dests) == 2  # no collision -- the second got a unique suffix


# ---- analyze(): I/O errors while hashing ----

def test_analyze_logs_error_and_skips_file_when_hashing_fails(tmp_path, monkeypatch):
    in_dir, out_dir = tmp_path / 'in', tmp_path / 'out'
    _make_file(in_dir / 'a.jpg', b'data', mtime=datetime(2020, 1, 1))

    def raise_os_error(path, chunk_size=1024 * 1024):
        raise OSError('permission denied')

    monkeypatch.setattr('photo_organizer.planner.hash_file', raise_os_error)

    reporter = FakeReporter()
    plan = analyze(in_dir=in_dir, out_dir=out_dir, exiftool_path='', reporter=reporter)

    assert plan == []
    assert reporter.has_log_containing('Could not read', tag='err')


# ---- analyze(): cancellation ----

def test_analyze_stops_early_when_already_cancelled(tmp_path):
    in_dir, out_dir = tmp_path / 'in', tmp_path / 'out'
    _make_file(in_dir / 'a.jpg', b'1', mtime=datetime(2020, 1, 1))
    _make_file(in_dir / 'b.jpg', b'2', mtime=datetime(2020, 1, 1))

    reporter = FakeReporter()
    reporter.stop = True

    plan = analyze(in_dir=in_dir, out_dir=out_dir, exiftool_path='', reporter=reporter)

    assert plan == []
    assert reporter.has_log_containing('Cancelled', tag='warn')


def test_analyze_stops_partway_through_and_keeps_what_was_already_planned(tmp_path):
    in_dir, out_dir = tmp_path / 'in', tmp_path / 'out'
    _make_file(in_dir / 'a.jpg', b'1', mtime=datetime(2020, 1, 1))
    _make_file(in_dir / 'b.jpg', b'2', mtime=datetime(2020, 1, 1))
    _make_file(in_dir / 'c.jpg', b'3', mtime=datetime(2020, 1, 1))

    # should_stop() is checked once per file, before it's processed: check #1
    # (file 'a') passes, check #2 (file 'b') trips the cancel.
    reporter = FakeReporter(stop_after=2)

    plan = analyze(in_dir=in_dir, out_dir=out_dir, exiftool_path='', reporter=reporter)

    assert len(plan) == 1
    assert plan[0].src.name == 'a.jpg'
    assert reporter.has_log_containing('Cancelled', tag='warn')


# ---- apply_plan(): copy / move ----

def test_apply_plan_copies_file_and_keeps_source(tmp_path):
    src = tmp_path / 'src.jpg'
    src.write_bytes(b'data')
    out_dir = tmp_path / 'out'
    dest = out_dir / '2020' / '01' / 'src.jpg'
    op = PlanOperation(src=src, dest=dest, kind=MediaKind.PHOTO, hash='deadbeef')

    done, skipped, errors = apply_plan([op], operation=Operation.COPY, out_dir=out_dir, reporter=FakeReporter())

    assert (done, skipped, errors) == (1, 0, 0)
    assert dest.read_bytes() == b'data'
    assert src.exists()  # copy -- source untouched


def test_apply_plan_moves_file_and_removes_source(tmp_path):
    src = tmp_path / 'src.jpg'
    src.write_bytes(b'data')
    out_dir = tmp_path / 'out'
    dest = out_dir / '2020' / '01' / 'src.jpg'
    op = PlanOperation(src=src, dest=dest, kind=MediaKind.PHOTO, hash='deadbeef')

    done, skipped, errors = apply_plan([op], operation=Operation.MOVE, out_dir=out_dir, reporter=FakeReporter())

    assert (done, skipped, errors) == (1, 0, 0)
    assert dest.exists()
    assert not src.exists()


def test_apply_plan_skips_missing_source(tmp_path):
    out_dir = tmp_path / 'out'
    op = PlanOperation(src=tmp_path / 'missing.jpg', dest=out_dir / 'x.jpg', kind=MediaKind.PHOTO, hash='abc')

    done, skipped, errors = apply_plan([op], operation=Operation.COPY, out_dir=out_dir, reporter=FakeReporter())

    assert (done, skipped, errors) == (0, 1, 0)


def test_apply_plan_disambiguates_when_destination_already_exists(tmp_path):
    src = tmp_path / 'src.jpg'
    src.write_bytes(b'new-content')
    out_dir = tmp_path / 'out'
    dest = out_dir / 'x.jpg'
    dest.parent.mkdir(parents=True)
    dest.write_bytes(b'existing-content')
    op = PlanOperation(src=src, dest=dest, kind=MediaKind.PHOTO, hash='abc')

    done, skipped, errors = apply_plan([op], operation=Operation.COPY, out_dir=out_dir, reporter=FakeReporter())

    assert (done, skipped, errors) == (1, 0, 0)
    assert dest.read_bytes() == b'existing-content'  # never overwritten
    siblings = list(out_dir.glob('x_*.jpg'))
    assert len(siblings) == 1
    assert siblings[0].read_bytes() == b'new-content'


def test_apply_plan_stops_when_cancelled_and_copies_nothing(tmp_path):
    src1 = tmp_path / 'a.jpg'; src1.write_bytes(b'1')
    src2 = tmp_path / 'b.jpg'; src2.write_bytes(b'2')
    out_dir = tmp_path / 'out'
    ops = [
        PlanOperation(src=src1, dest=out_dir / 'a.jpg', kind=MediaKind.PHOTO, hash='h1'),
        PlanOperation(src=src2, dest=out_dir / 'b.jpg', kind=MediaKind.PHOTO, hash='h2'),
    ]
    reporter = FakeReporter()
    reporter.stop = True

    done, skipped, errors = apply_plan(ops, operation=Operation.COPY, out_dir=out_dir, reporter=reporter)

    assert (done, skipped, errors) == (0, 0, 0)
    assert src1.exists() and src2.exists()


def test_apply_plan_records_error_when_copy_fails(tmp_path):
    src = tmp_path / 'src.jpg'
    src.write_bytes(b'data')
    out_dir = tmp_path / 'out'
    blocker = tmp_path / 'blocker'
    blocker.write_bytes(b'a file, not a directory')  # dest.parent.mkdir() collides with this
    op = PlanOperation(src=src, dest=blocker / 'dest.jpg', kind=MediaKind.PHOTO, hash='abc')

    done, skipped, errors = apply_plan([op], operation=Operation.COPY, out_dir=out_dir, reporter=FakeReporter())

    assert (done, skipped, errors) == (0, 0, 1)
    assert src.exists()  # untouched -- the copy never happened


def test_apply_plan_saves_hash_database(tmp_path):
    src = tmp_path / 'src.jpg'
    src.write_bytes(b'data')
    out_dir = tmp_path / 'out'
    dest = out_dir / 'x.jpg'
    op = PlanOperation(src=src, dest=dest, kind=MediaKind.PHOTO, hash='known-hash')

    apply_plan([op], operation=Operation.COPY, out_dir=out_dir, reporter=FakeReporter())

    db = HashDb(out_dir)
    db.load()
    assert db.data.get('known-hash') == str(dest)


# ---- _consecutive_day_runs() ----

@pytest.mark.parametrize('days,expected', [
    ([15], [(15, 15)]),
    ([15, 16, 17, 18], [(15, 18)]),
    ([15, 16, 20], [(15, 16), (20, 20)]),
    ([1, 3, 5], [(1, 1), (3, 3), (5, 5)]),
])
def test_consecutive_day_runs(days, expected):
    assert _consecutive_day_runs(days) == expected


# ---- analyze(): location grouping ----
# get_date_and_gps()/city_for() are monkeypatched throughout -- real
# EXIF/GPS/geocoding behavior is covered separately in test_dates.py,
# test_gps.py, test_exif_lookup.py and test_geocoding.py.

def _stub_location(monkeypatch, gps_by_name=None, default_gps=None, track_calls=None):
    """Patch get_date_and_gps() to keep real (mtime-derived) dates -- so
    tests can still set expectations via _make_file(mtime=...) -- while
    controlling just the GPS half. gps_by_name maps filename -> gps
    tuple/None, falling back to default_gps for names not in the map."""
    def fake(f, exiftool_path):
        if track_calls is not None:
            track_calls.append(f)
        dt, source = get_file_date(f, '')
        gps = (gps_by_name or {}).get(f.name, default_gps)
        return dt, source, gps

    monkeypatch.setattr('photo_organizer.planner.get_date_and_gps', fake)


def test_analyze_ignores_location_by_default(tmp_path, monkeypatch):
    in_dir, out_dir = tmp_path / 'in', tmp_path / 'out'
    _make_file(in_dir / 'a.jpg', b'1', mtime=datetime(2015, 4, 28))

    calls = []
    _stub_location(monkeypatch, default_gps=(52.23, 21.01), track_calls=calls)

    plan = analyze(in_dir=in_dir, out_dir=out_dir, exiftool_path='', reporter=FakeReporter())

    assert calls == []  # get_date_and_gps never invoked when group_by_location is False (the default)
    assert plan[0].dest == out_dir / '2015' / '04' / 'a.jpg'


def test_analyze_falls_back_to_plain_bucket_when_city_not_found(tmp_path, monkeypatch):
    in_dir, out_dir = tmp_path / 'in', tmp_path / 'out'
    _make_file(in_dir / 'a.jpg', b'1', mtime=datetime(2015, 4, 28))

    _stub_location(monkeypatch, default_gps=None)

    plan = analyze(in_dir=in_dir, out_dir=out_dir, exiftool_path='', group_by_location=True,
                    reporter=FakeReporter())

    assert plan[0].dest == out_dir / '2015' / '04' / 'a.jpg'


def test_analyze_groups_a_single_located_day_as_yyyy_mm_dd_city(tmp_path, monkeypatch):
    in_dir, out_dir = tmp_path / 'in', tmp_path / 'out'
    _make_file(in_dir / 'a.jpg', b'1', mtime=datetime(2015, 4, 28))

    _stub_location(monkeypatch, default_gps=(52.23, 21.01))
    monkeypatch.setattr('photo_organizer.planner.city_for', lambda lat, lon: 'Warsaw')

    plan = analyze(in_dir=in_dir, out_dir=out_dir, exiftool_path='', group_by_location=True,
                    reporter=FakeReporter())

    assert len(plan) == 1
    assert plan[0].dest == out_dir / '2015' / '04' / '2015-04-28 Warsaw' / 'a.jpg'


def test_analyze_merges_consecutive_located_days_into_a_range_folder(tmp_path, monkeypatch):
    in_dir, out_dir = tmp_path / 'in', tmp_path / 'out'
    for day in (15, 16, 17, 18):
        _make_file(in_dir / f'day{day}.jpg', str(day).encode(), mtime=datetime(2015, 4, day))

    _stub_location(monkeypatch, default_gps=(52.23, 21.01))
    monkeypatch.setattr('photo_organizer.planner.city_for', lambda lat, lon: 'Warsaw')

    plan = analyze(in_dir=in_dir, out_dir=out_dir, exiftool_path='', group_by_location=True,
                    reporter=FakeReporter())

    assert len(plan) == 4
    expected_folder = out_dir / '2015' / '04' / '2015-04-15-18 Warsaw'
    assert all(op.dest.parent == expected_folder for op in plan)


def test_analyze_splits_the_range_at_a_day_with_no_located_photo(tmp_path, monkeypatch):
    in_dir, out_dir = tmp_path / 'in', tmp_path / 'out'
    for day in (15, 16, 20):  # 17-19 have no located photo -- breaks the run
        _make_file(in_dir / f'day{day}.jpg', str(day).encode(), mtime=datetime(2015, 4, day))

    _stub_location(monkeypatch, default_gps=(52.23, 21.01))
    monkeypatch.setattr('photo_organizer.planner.city_for', lambda lat, lon: 'Warsaw')

    plan = analyze(in_dir=in_dir, out_dir=out_dir, exiftool_path='', group_by_location=True,
                    reporter=FakeReporter())

    folders = {op.dest.parent for op in plan}
    assert folders == {
        out_dir / '2015' / '04' / '2015-04-15-16 Warsaw',
        out_dir / '2015' / '04' / '2015-04-20 Warsaw',
    }


def test_analyze_keeps_video_and_photo_location_folders_separate(tmp_path, monkeypatch):
    in_dir, out_dir = tmp_path / 'in', tmp_path / 'out'
    _make_file(in_dir / 'a.jpg', b'1', mtime=datetime(2015, 4, 28))
    _make_file(in_dir / 'a.mp4', b'2', mtime=datetime(2015, 4, 28))

    _stub_location(monkeypatch, default_gps=(52.23, 21.01))
    monkeypatch.setattr('photo_organizer.planner.city_for', lambda lat, lon: 'Warsaw')

    plan = analyze(in_dir=in_dir, out_dir=out_dir, exiftool_path='', group_by_location=True,
                    reporter=FakeReporter())

    dests = {op.kind: op.dest for op in plan}
    assert dests[MediaKind.PHOTO] == out_dir / '2015' / '04' / '2015-04-28 Warsaw' / 'a.jpg'
    assert dests[MediaKind.VIDEO] == out_dir / 'videos' / '2015' / '04' / '2015-04-28 Warsaw' / 'a.mp4'


def test_analyze_logs_grouped_by_location_count(tmp_path, monkeypatch):
    in_dir, out_dir = tmp_path / 'in', tmp_path / 'out'
    _make_file(in_dir / 'a.jpg', b'1', mtime=datetime(2015, 4, 28))

    _stub_location(monkeypatch, default_gps=(52.23, 21.01))
    monkeypatch.setattr('photo_organizer.planner.city_for', lambda lat, lon: 'Warsaw')

    reporter = FakeReporter()
    analyze(in_dir=in_dir, out_dir=out_dir, exiftool_path='', group_by_location=True, reporter=reporter)

    assert reporter.has_log_containing('Grouped by location  : 1')


def test_analyze_does_not_count_a_duplicate_toward_grouped_by_location(tmp_path, monkeypatch):
    # Regression: the "located" count used to increment as soon as a city
    # resolved, before the duplicate check that can still drop the file --
    # overstating how many files actually landed in a location folder.
    in_dir, out_dir = tmp_path / 'in', tmp_path / 'out'
    _make_file(in_dir / 'a.jpg', b'same-bytes', mtime=datetime(2015, 4, 28))
    _make_file(in_dir / 'b.jpg', b'same-bytes', mtime=datetime(2015, 4, 28))  # duplicate of a.jpg

    _stub_location(monkeypatch, default_gps=(52.23, 21.01))
    monkeypatch.setattr('photo_organizer.planner.city_for', lambda lat, lon: 'Warsaw')

    reporter = FakeReporter()
    plan = analyze(in_dir=in_dir, out_dir=out_dir, exiftool_path='', group_by_location=True, reporter=reporter)

    assert len(plan) == 1  # the duplicate never made it into the plan
    assert reporter.has_log_containing('Grouped by location  : 1')  # not 2


def test_analyze_groups_by_the_sanitized_city_name_consistently(tmp_path, monkeypatch):
    # Regression: grouping used to key on the raw city string while the
    # destination folder used the sanitized one, so two raw names that
    # sanitize to the same text could form separate groups yet collide on
    # the same physical folder without the code ever noticing.
    in_dir, out_dir = tmp_path / 'in', tmp_path / 'out'
    _make_file(in_dir / 'a.jpg', b'1', mtime=datetime(2015, 4, 28))
    _make_file(in_dir / 'b.jpg', b'2', mtime=datetime(2015, 4, 29))

    # Different (fake) coordinates per file, so city_for can return two
    # distinct raw names that sanitize down to the identical string.
    _stub_location(monkeypatch, gps_by_name={'a.jpg': (52.23, 21.01), 'b.jpg': (52.24, 21.02)})
    monkeypatch.setattr('photo_organizer.planner.city_for',
                         lambda lat, lon: 'Warsaw?' if lat == 52.23 else 'Warsaw')

    plan = analyze(in_dir=in_dir, out_dir=out_dir, exiftool_path='', group_by_location=True,
                    reporter=FakeReporter())

    assert len(plan) == 2
    # Consecutive days, same sanitized city -> merged into one range folder.
    assert {op.dest.parent for op in plan} == {out_dir / '2015' / '04' / '2015-04-28-29 Warsaw'}
