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
from pathlib import Path
from typing import Protocol

from .dates import get_file_date
from .hashdb import HashDb, hash_file
from .models import DateSource, LogTag, MediaKind, Operation, PlanOperation
from .paths import unique_dest

PHOTO_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.heic', '.gif', '.tiff'}
VIDEO_EXTENSIONS = {'.mp4', '.mov', '.avi', '.mkv', '.flv', '.wmv', '.3gp'}


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


def analyze(*, in_dir: Path, out_dir: Path, exiftool_path: str,
            reporter: ProgressReporter) -> list[PlanOperation]:
    """Scan in_dir, detect photo/video + date, dedupe by hash, and build the
    copy/move plan. Never touches the filesystem beyond reading it -- see
    apply_plan() for the part that actually copies/moves files."""
    plan: list[PlanOperation] = []

    reporter.log('=' * 80, 'h')
    reporter.log(f'Input:    {in_dir}')
    reporter.log(f'Output:   {out_dir}')
    reporter.log(f'exiftool: {exiftool_path or "not found"}', 'dim')
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
    total = exif_used = mtime_used = videos = duplicates = unrecognized = 0

    for i, f in enumerate(files, 1):
        if reporter.should_stop():
            reporter.log('Cancelled.', 'warn')
            break
        reporter.set_status(f'Scanning {i}/{len(files)}: {f.name}')
        total += 1
        ext = f.suffix.lower()

        if ext in VIDEO_EXTENSIONS:
            dt, _source = get_file_date(f, exiftool_path)
            dest_folder = out_dir / 'videos' / f'{dt:%Y}'
            kind = MediaKind.VIDEO
            videos += 1
        elif ext in PHOTO_EXTENSIONS:
            dt, source = get_file_date(f, exiftool_path)
            dest_folder = out_dir / f'{dt:%Y}' / f'{dt:%m}'
            kind = MediaKind.PHOTO
            if source == DateSource.EXIF:
                exif_used += 1
            else:
                mtime_used += 1
        else:
            reporter.log(f'[Skipped - unknown extension] {f}', 'dim')
            unrecognized += 1
            reporter.set_progress(i)
            continue

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

        dest = unique_dest(dest_folder / f.name, used_dests)
        plan.append(PlanOperation(src=f, dest=dest, kind=kind, hash=digest))
        reporter.log(f'[{kind}] {f} -> {dest}', 'ok')
        reporter.set_progress(i)

    reporter.log('')
    reporter.log('============= Summary =============', 'h')
    reporter.log(f'Total files scanned  : {total}')
    reporter.log(f'Duplicates skipped   : {duplicates}')
    reporter.log(f'Photos using EXIF    : {exif_used}')
    reporter.log(f'Photos using mtime   : {mtime_used}')
    reporter.log(f'Videos               : {videos}')
    reporter.log(f'Unrecognized         : {unrecognized}')
    reporter.log(f'Planned operations   : {len(plan)}')
    reporter.log('====================================', 'h')
    reporter.set_status(f'Done. {len(plan)} operations planned.')
    reporter.set_progress(0)
    return plan


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
