"""Entry point. Implementation lives in the photo_organizer/ package.

Double-click this (rename to run.pyw on Windows for no console window), or
run `python run.py` / `python -m photo_organizer`. This is also what the
build scripts (build_windows.bat, build_unix.sh, Dockerfiles, CI) point
PyInstaller at.
"""
from photo_organizer.gui import main

if __name__ == '__main__':
    main()
