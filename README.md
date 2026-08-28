# Photo Organizer

A desktop app (Tkinter GUI, no console window) that sorts photos and videos
out of a messy input folder into a dated structure. Same idea and layout as
the sibling [`video-organizer`](../video-organizer) project.

## Output structure

```
<OUTPUT>/
├── 2019/
│   ├── 03/<photos taken March 2019>
│   └── 07/<photos taken July 2019>
├── 2020/
│   └── 12/...
└── videos/
    ├── 2019/<videos from 2019>
    └── 2020/<videos from 2020>
```

Date comes from EXIF `DateTimeOriginal` when available, otherwise the
file's last-modified time. Duplicate content (by SHA-256) is skipped and
tracked in `<OUTPUT>/hashes.json`, so re-running the tool on the same input
never copies the same photo twice — even across separate runs.

---

## Do I need Python installed?

Pick one:

- **Simplest** — install Python once from https://www.python.org/downloads/
  (tick **"Add python.exe to PATH"** on Windows). Rename `run.py` to
  `run.pyw` and double-click it — no console window pops up. Or run
  `python run.py` / `python -m photo_organizer` from a terminal.
- **Standalone .exe on Windows** — run `build_windows.bat` once on any
  Windows PC with Python. Produces `dist\PhotoOrganizer.exe`, copy anywhere.
- **Standalone binary on macOS/Linux** — run `./build_unix.sh`. On Linux
  install `python3-tk` first (`sudo apt install python3-tk`).
- **Docker (reproducible builds)** — see the "Building with Docker" section
  below.
- **GitHub Actions (real Windows/macOS/Linux runners)** — the workflow at
  `.github/workflows/build.yml` builds all three from any repo commit and
  uploads binaries as artifacts. Tag a commit with `v*` (e.g. `v1.0`) to
  attach the binaries to a GitHub Release automatically.

Optional dependency for EXIF reading without the external `exiftool`
binary: `pip install -r requirements.txt` (installs `Pillow`).

`exiftool` (https://exiftool.org) is used automatically if it's on PATH or
installed at its default Windows location — it reads EXIF from more formats
than Pillow, including HEIC and videos. Its path is shown (and editable) in
the app's "Tools" section.

---

## Building with Docker

Reproducible builds without touching your host's Python. Requires Docker
Desktop (Windows/macOS) or Docker Engine + Compose (Linux). Your `input/`
and `output/` folders are excluded from the build context via
`.dockerignore` — they never leave your machine.

```bash
# Linux binary — reliable
docker compose run --rm build-linux
#   -> dist_docker/PhotoOrganizer-linux

# Windows .exe via Wine — experimental, may or may not work
docker compose run --rm build-windows
#   -> dist_docker/PhotoOrganizer.exe
```

**About the Windows Docker build:** cross-compiling a Tkinter GUI for
Windows from a Linux host uses Wine (image `tobix/pywine`). Tkinter under
Wine has been known to break between Wine versions. If it doesn't work,
use one of the alternatives — `build_windows.bat` on a real Windows PC is
the most straightforward, or the GitHub Actions workflow if you already
push code to GitHub.

---

## Using the app

1. Pick your **Input folder** (the messy pile of photos/videos).
2. Pick an **Output folder**.
3. Choose **Copy** or **Move**.
4. Keep **"Dry run"** ticked and press **Analyze / Plan**.
5. Read the log — every planned operation is listed, plus a summary
   (EXIF vs. mtime counts, duplicates, unrecognized files).
6. When happy, untick **"Dry run"**, click **Analyze** again, then **Apply**.

Nothing touches disk while "Dry run" is on — Apply refuses to run until you
untick it and re-analyze. There's a Cancel button, and log/plan can be
saved to a file from the button row.

---

## Development

No local Python install needed — everything below runs in a Docker
container (Python 3.11 + Tk + the project's deps, repo bind-mounted in).
Open the repo in VS Code and choose **"Reopen in Container"** to get the
same environment with editor support (`.devcontainer/devcontainer.json`
points at the same image), or drive it from the CLI:

```bash
make dev            # interactive shell in the dev container
make test           # run the test suite (pytest)
make coverage       # run tests with a coverage report (fails under 90%, gui.py excluded)
make lint            # ruff check
make typecheck      # mypy
make sec             # bandit security scan
make audit           # pip-audit — known CVEs in installed deps
make check          # lint + typecheck + sec + audit + coverage — same checks CI runs on every push/PR
make build-linux    # build dist_docker/PhotoOrganizer-linux
make build-windows  # build dist_docker/PhotoOrganizer.exe via Wine (experimental)
make clean          # remove local build/test artifacts
```

No `make`? Run the underlying `docker compose run --rm dev <command>` calls
directly — `make help` lists each target's exact command.

The core scan/hash/plan/apply logic lives in `photo_organizer/planner.py`
and has no Tkinter import, so it's tested headless (`tests/test_planner.py`)
through the same `ProgressReporter` protocol the GUI (`photo_organizer/gui.py`)
implements. `gui.py` and `__main__.py` are excluded from the coverage
requirement — they're presentation wiring, not logic.

Requirements: Python 3.11+ is the supported floor (matches every Dockerfile
and the CI workflow — see `pyproject.toml`'s `[tool.ruff]`/`[tool.mypy]`
`target-version`/`python_version`). App runtime deps are in
`requirements.txt`; dev/CI tooling (pytest, ruff, mypy, bandit, pip-audit)
is in `requirements-dev.txt`.

---

## Why this replaces `src/organize_photos.ps1` / `.sh`

Those scripts still work and are left in place for reference, but the
PowerShell version's WinForms window is prone to closing silently on some
setups (execution-policy or apartment-state issues) with no visible error.
A Python/Tkinter app avoids that class of problem entirely, and
`--windowed` PyInstaller builds give a real double-click `.exe` with no
flashing console.
