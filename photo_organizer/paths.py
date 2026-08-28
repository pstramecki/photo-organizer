"""Where the app's mutable state (hashes.json) lives, and filename-collision
resolution."""
from __future__ import annotations

import random
import re
import sys
from pathlib import Path


def app_dir() -> Path:
    """Directory the running executable lives in (frozen), or the project
    root when running from source -- this file is one level inside the
    ``photo_organizer`` package, so ``.parent.parent`` lands back at the
    repo root."""
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def sanitize_component(name: str) -> str:
    """Strip filesystem-illegal characters from a single path component
    (used for the "YYYY-MM-DD City" location-grouping folder)."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', name)
    return re.sub(r'\s+', ' ', name).strip().rstrip('. ') or 'Unknown'


def unique_dest(dest: Path, used: set[str]) -> Path:
    """Resolve filename collisions against both disk and this run's plan."""
    if str(dest) not in used and not dest.exists():
        used.add(str(dest))
        return dest
    stem, suffix, parent = dest.stem, dest.suffix, dest.parent
    while True:
        # nosec B311 -- filename disambiguation, not a security control.
        candidate = parent / f'{stem}_{random.randint(0, 9999)}{suffix}'  # nosec B311
        if str(candidate) not in used and not candidate.exists():
            used.add(str(candidate))
            return candidate
