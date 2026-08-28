"""SHA-256 duplicate tracking, persisted as JSON so re-running the tool on
the same input never copies the same photo twice -- even across runs."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


def hash_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(chunk_size), b''):
            h.update(block)
    return h.hexdigest()


class HashDb:
    """digest -> destination path, stored at ``<output_dir>/hashes.json``."""

    def __init__(self, output_dir: Path):
        self.path = output_dir / 'hashes.json'
        self.data: dict[str, str] = {}

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = self.path.read_text(encoding='utf-8')
            if raw.strip():
                self.data = json.loads(raw)
        except (OSError, json.JSONDecodeError):
            self.data = {}

    def save(self) -> None:
        self.path.write_text(
            json.dumps(self.data, indent=2, ensure_ascii=False), encoding='utf-8'
        )

    def __contains__(self, digest: str) -> bool:
        return digest in self.data

    def add(self, digest: str, dest: str) -> None:
        self.data[digest] = dest
