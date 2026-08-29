"""The core use case: scan a folder, detect photo vs. video + date, dedupe
by SHA-256, and build a copy/move plan -- then, separately, execute that
plan.

No GUI/Tkinter import anywhere in this module. It talks to the outside
world only through the ProgressReporter protocol, so it's usable headless
(tests, a future CLI, ...) and testable without a display.
"""
from __future__ import annotations

import os
import shutil
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from .dates import get_file_date
from .exif_lookup import get_date_and_gps
from .geocoding import city_for
from .hashdb import HashDb, hash_file
from .models import DateSource, LogTag, MediaKind, Operation, PlanOperation
from .paths import sanitize_component, unique_dest

PHOTO_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.heic', '.gif', '.tiff'}
VIDEO_EXTENSIONS = {'.mp4', '.mov', '.avi', '.mkv', '.flv', '.wmv', '.3gp'}


@dataclass
class _LocatedFile:
    """A file whose GPS resolved to a city, deferred to _plan_located() so
    consecutive same-city days can be merged into one range folder."""
    file: Path
    dt: datetime
    city: str  # already sanitize_component()-cleaned -- see analyze()
    kind: MediaKind
    digest: str


class ProgressReporter(Protocol):
    """What analyze()/apply_plan() need from the outside world -- implemented
    by the GUI (PhotoOrganizerApp) so this module never has to know Tkinter
    exists."""

    def log(self, msg: str = '', tag: LogTag | None = None) -> None: ...
    def set_status(self, text: str) -> None: ...
    def set_progress(self, value: int | None = None, maximum: int | None = None) -> None: ...
    def should_stop(self) -> bool: ...


def _scan_files(in_dir: Path, out_dir: Path) -> list[Path]:
    """Every file under in_dir, excluding anything already under out_dir (so
    an overlapping in_dir/out_dir doesn't re-plan the tool's own previous
    output). Sorted for deterministic ordering."""
    files = []
    for root, dirs, fs in os.walk(in_dir):
        root_p = Path(root)
        try:
            root_p.resolve().relative_to(out_dir)
            dirs[:] = []
            continue
        except ValueError:
            pass
        for f in fs:
            files.append(root_p / f)
    files.sort()
    return files


def _year_root(out_dir: Path, kind: MediaKind, year: int) -> Path:
    """<out_dir>/videos/YYYY for videos, <out_dir>/YYYY for photos -- shared
    by analyze()'s plain-bucket branch and _plan_located()."""
    return out_dir / 'videos' / f'{year:04d}' if kind is MediaKind.VIDEO else out_dir / f'{year:04d}'


def _finalize(src: Path, dest_folder: Path, kind: MediaKind, digest: str,
              used_dests: set[str], reporter: ProgressReporter) -> PlanOperation:
    """Resolve the final (collision-free) destination, log it, and return
    the plan entry -- shared by analyze()'s plain-bucket branch and
    _plan_located()."""
    dest = unique_dest(dest_folder / src.name, used_dests)
    reporter.log(f'[{kind}] {src} -> {dest}', 'ok')
    return PlanOperation(src=src, dest=dest, kind=kind, hash=digest)


def _consecutive_day_runs(days: list[int]) -> list[tuple[int, int]]:
    """Split a sorted, deduplicated list of day-of-month numbers into
    (start, end) ranges of consecutive days -- e.g. [15, 16, 17, 18, 25]
    -> [(15, 18), (25, 25)]. A gap (a day with no located photo) breaks
    the run, so a range only ever covers days that actually have one."""
    runs: list[tuple[int, int]] = []
    start = end = days[0]
    for d in days[1:]:
        if d == end + 1:
            end = d
        else:
            runs.append((start, end))
            start = end = d
    runs.append((start, end))
    return runs


def _plan_located(pending: list[_LocatedFile], out_dir: Path, used_dests: set[str],
                   reporter: ProgressReporter) -> list[PlanOperation]:
    """Turn the deferred GPS-located entries into plan operations, merging
    consecutive same-city days into one range folder -- a 4-day trip with a
    located photo on every day becomes one "2015-04-15-18 Warsaw" folder
    instead of four separate day folders; an isolated day becomes plain
    "2015-04-25 Warsaw". Deferred (rather than decided per-file during the
    scan) because a day only joins a range once every day in it is known
    to have a located photo -- that isn't knowable until the whole folder
    has been scanned."""
    groups: dict[tuple[MediaKind, int, int, str], list[_LocatedFile]] = defaultdict(list)
    for p in pending:
        groups[(p.kind, p.dt.year, p.dt.month, p.city)].append(p)

    ops: list[PlanOperation] = []
    for (kind, year, month, city), items in sorted(groups.items(), key=lambda kv: kv[0]):
        runs = _consecutive_day_runs(sorted({p.dt.day for p in items}))
        for start_day, end_day in runs:
            label = (f'{year:04d}-{month:02d}-{start_day:02d}' if start_day == end_day
                      else f'{year:04d}-{month:02d}-{start_day:02d}-{end_day:02d}')
            # city is already sanitize_component()-cleaned (see analyze()); label
            # is digits/hyphens only -- concatenating them needs no re-sanitizing.
            dest_folder = _year_root(out_dir, kind, year) / f'{month:02d}' / f'{label} {city}'
            for p in items:
                if start_day <= p.dt.day <= end_day:
                    ops.append(_finalize(p.file, dest_folder, kind, p.digest, used_dests, reporter))
    return ops


def analyze(*, in_dir: Path, out_dir: Path, exiftool_path: str, group_by_location: bool = False,
            reporter: ProgressReporter) -> list[PlanOperation]:
    """Scan in_dir, detect photo/video + date (+ location, if enabled),
    dedupe by hash, and build the copy/move plan. Never touches the
    filesystem beyond reading it -- see apply_plan() for the part that
    actually copies/moves files.

    With group_by_location, a file whose GPS EXIF resolves to a city is
    deferred to _plan_located() so consecutive same-city days can be
    merged into one range folder (see there). Files without resolvable
    GPS go straight into the plain year/month bucket, as before.
    """
    plan: list[PlanOperation] = []
    pending: list[_LocatedFile] = []  # resolved after the scan by _plan_located()

    reporter.log('=' * 80, 'h')
    reporter.log(f'Input:    {in_dir}')
    reporter.log(f'Output:   {out_dir}')
    reporter.log(f'exiftool: {exiftool_path or "not found"}', 'dim')
    reporter.log(f'Group by location: {"yes" if group_by_location else "no"}', 'dim')
    reporter.log('=' * 80, 'h')

    hash_db = HashDb(out_dir)
    hash_db.load()
    if hash_db.data:
        reporter.log(f'Loaded {len(hash_db.data)} known hashes from {hash_db.path}', 'dim')

    reporter.set_status('Scanning...')
    files = _scan_files(in_dir, out_dir)
    reporter.log(f'Found {len(files)} files.')
    if not files:
        reporter.set_status('No files found.')
        return plan

    reporter.set_progress(0, len(files))
    used_dests: set[str] = set()
    seen_hashes = set(hash_db.data.keys())
    total = exif_used = mtime_used = videos = duplicates = unrecognized = located = 0

    for i, f in enumerate(files, 1):
        if reporter.should_stop():
            reporter.log('Cancelled.', 'warn')
            break
        reporter.set_status(f'Scanning {i}/{len(files)}: {f.name}')
        total += 1
        ext = f.suffix.lower()

        if ext in VIDEO_EXTENSIONS:
            kind = MediaKind.VIDEO
            videos += 1
        elif ext in PHOTO_EXTENSIONS:
            kind = MediaKind.PHOTO
        else:
            reporter.log(f'[Skipped - unknown extension] {f}', 'dim')
            unrecognized += 1
            reporter.set_progress(i)
            continue

        if group_by_location:
            # One exiftool call for date + GPS instead of two -- see exif_lookup.py.
            dt, source, gps = get_date_and_gps(f, exiftool_path)
        else:
            dt, source = get_file_date(f, exiftool_path)
            gps = None

        if kind is MediaKind.PHOTO:
            if source == DateSource.EXIF:
                exif_used += 1
            else:
                mtime_used += 1

        try:
            digest = hash_file(f)
        except OSError as e:
            reporter.log(f'[Error] Could not read {f}: {e}', 'err')
            reporter.set_progress(i)
            continue

        if digest in seen_hashes:
            reporter.log(f'[Duplicate] {f}', 'warn')
            duplicates += 1
            reporter.set_progress(i)
            continue
        seen_hashes.add(digest)

        # Resolved only now (after the hash-error/duplicate checks above) so a
        # file that never makes it into the plan doesn't still count toward
        # "Grouped by location" below, and so geocoding isn't wasted on a
        # duplicate. (gps is never "Null Island" (0.0, 0.0) here -- that's
        # filtered at the source in gps.py/exif_lookup.py.)
        city = None
        if gps:
            raw_city = city_for(*gps)
            if raw_city:
                # Sanitized once here so the grouping key below and the
                # destination folder name are always derived from the same
                # string -- two raw city names that only differ by
                # filesystem-illegal characters must not silently share a
                # group (and then a folder) just because sanitize_component()
                # happens to collapse both down to the same clean text.
                city = sanitize_component(raw_city)
                located += 1

        if city:
            pending.append(_LocatedFile(file=f, dt=dt, city=city, kind=kind, digest=digest))
        else:
            year_root = _year_root(out_dir, kind, dt.year)
            dest_folder = year_root if kind is MediaKind.VIDEO else year_root / f'{dt:%m}'
            plan.append(_finalize(f, dest_folder, kind, digest, used_dests, reporter))
        reporter.set_progress(i)

    plan.extend(_plan_located(pending, out_dir, used_dests, reporter))

    reporter.log('')
    reporter.log('============= Summary =============', 'h')
    reporter.log(f'Total files scanned  : {total}')
    reporter.log(f'Duplicates skipped   : {duplicates}')
    reporter.log(f'Photos using EXIF    : {exif_used}')
    reporter.log(f'Photos using mtime   : {mtime_used}')
    reporter.log(f'Videos               : {videos}')
    reporter.log(f'Grouped by location  : {located}')
    reporter.log(f'Unrecognized         : {unrecognized}')
    reporter.log(f'Planned operations   : {len(plan)}')
    reporter.log('====================================', 'h')
    reporter.set_status(f'Done. {len(plan)} operations planned.')
    reporter.set_progress(0)
    return plan


def rebuild_hash_index(out_dir: Path, reporter: ProgressReporter) -> int:
    """Hash every file already under out_dir and merge into hashes.json --
    a one-time catch-up for files that ended up there some other way than
    through this tool (a manual copy, a migration, a lost hashes.json), so
    a future analyze() correctly recognizes them as duplicates instead of
    copying them in again under a different name.

    Unlike analyze(), this writes hashes.json immediately -- it's a
    standalone maintenance action with its own confirmation in the GUI,
    not part of the Analyze/Apply flow, so it isn't gated by Dry Run.
    Returns the number of newly-added hashes.
    """
    hash_db = HashDb(out_dir)
    hash_db.load()
    known_before = len(hash_db.data)

    reporter.log('=' * 80, 'h')
    reporter.log(f'Rebuilding hash index from: {out_dir}', 'h')
    reporter.log('=' * 80, 'h')

    if not out_dir.exists():
        reporter.log('Output folder does not exist yet -- nothing to index.', 'warn')
        reporter.set_status('Nothing to index.')
        return 0

    files = sorted(p for p in out_dir.rglob('*') if p.is_file() and p.name != 'hashes.json')
    reporter.log(f'Found {len(files)} existing files.')
    reporter.set_progress(0, len(files))

    added = 0
    for i, f in enumerate(files, 1):
        if reporter.should_stop():
            reporter.log('Cancelled.', 'warn')
            break
        reporter.set_status(f'Hashing {i}/{len(files)}: {f.name}')
        try:
            digest = hash_file(f)
        except OSError as e:
            reporter.log(f'[Error] Could not read {f}: {e}', 'err')
            reporter.set_progress(i)
            continue
        if digest not in hash_db:
            hash_db.add(digest, str(f))
            added += 1
        reporter.set_progress(i)

    hash_db.save()
    reporter.log('')
    reporter.log(f'Indexed {len(files)} existing files -- {added} new, '
                 f'{known_before} already known, {len(hash_db.data)} total tracked.', 'h')
    reporter.set_status(f'Hash index rebuilt: {added} new hashes added.')
    reporter.set_progress(0)
    return added


def apply_plan(plan: list[PlanOperation], *, operation: Operation, out_dir: Path,
                reporter: ProgressReporter) -> tuple[int, int, int]:
    """Copy or move every planned file. An existing destination is
    disambiguated with a random suffix rather than overwritten. Returns
    (done, skipped, errors)."""
    hash_db = HashDb(out_dir)
    hash_db.load()

    reporter.log('')
    reporter.log(f'*** APPLYING -- {operation.verb_ing.lower()} files ***', 'h')
    reporter.set_progress(0, len(plan))
    done = skipped = errors = 0

    for i, op in enumerate(plan, 1):
        if reporter.should_stop():
            reporter.log('Cancelled.', 'warn')
            break
        reporter.set_status(f'{operation.verb_ing} {i}/{len(plan)}: {op.src.name}')
        dest = op.dest
        try:
            if not op.src.exists():
                reporter.log(f'  MISSING source: {op.src}', 'warn')
                skipped += 1
            else:
                if dest.exists():
                    dest = unique_dest(dest, set())
                dest.parent.mkdir(parents=True, exist_ok=True)
                if operation == Operation.MOVE:
                    shutil.move(str(op.src), str(dest))
                else:
                    shutil.copy2(str(op.src), str(dest))
                hash_db.add(op.hash, str(dest))
                reporter.log(f'  OK: {dest}', 'ok')
                done += 1
        except OSError as e:
            reporter.log(f'  ERROR: {op.src} -> {dest}: {e}', 'err')
            errors += 1
        reporter.set_progress(i)

    try:
        hash_db.save()
        reporter.log(f'[Info] Saved hash database to {hash_db.path}', 'dim')
    except OSError as e:
        reporter.log(f'[Error] Failed to save hash database: {e}', 'err')

    reporter.log('')
    reporter.log(f'Done. {operation.verb_past}: {done}   Skipped: {skipped}   Errors: {errors}', 'h')
    reporter.set_status(f'Applied. {operation.verb_past}: {done}, Skipped: {skipped}, Errors: {errors}')
    reporter.set_progress(0)
    return done, skipped, errors
