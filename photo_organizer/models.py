"""Typed data shapes shared across the planner and GUI."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Literal

LogTag = Literal['h', 'warn', 'err', 'ok', 'dim']


class MediaKind(StrEnum):
    PHOTO = 'Photo'
    VIDEO = 'Video'


class DateSource(StrEnum):
    EXIF = 'exif'
    MTIME = 'mtime'


class Operation(StrEnum):
    """Copy or move. verb_ing/verb_past exist because naive string
    concatenation gets 'Moveing' wrong -- English isn't that regular."""
    COPY = 'Copy'
    MOVE = 'Move'

    @property
    def verb_ing(self) -> str:
        return 'Copying' if self is Operation.COPY else 'Moving'

    @property
    def verb_past(self) -> str:
        return 'Copied' if self is Operation.COPY else 'Moved'


@dataclass
class PlanOperation:
    """One planned copy/move: src -> dest, with the SHA-256 already computed
    during analyze() so apply_plan() can record it in the hash database
    without re-reading the file."""
    src: Path
    dest: Path
    kind: MediaKind
    hash: str
