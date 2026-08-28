#!/usr/bin/env bash
# organize_photos.sh
# Usage: ./organize_photos.sh SRC_DIR DST_DIR [--move] [--dry-run]

set -euo pipefail

SRC="${1:-}"
DST="${2:-}"
ACTION="${3:---copy}" # --copy (default), --move
DRYRUN="${4:-}"       # optional: --dry-run

[[ -z "$SRC" || -z "$DST" ]] && {
  echo "Usage: $0 SRC_DIR DST_DIR [--move|--copy] [--dry-run]"
  exit 1
}

HASH_DB="$DST/.photo_hashes.txt"
mkdir -p "$DST"
touch "$HASH_DB"

# Counters for summary
TOTAL=0
EXIF_USED_COUNT=0
MTIME_USED_COUNT=0
VIDEO_COUNT=0

log() { echo "[*] $*"; }
hash_file() { sha256sum "$1" | awk '{print $1}'; }

# Extract YYYY and MM from EXIF or fallback mtime
get_date_parts() {
  local f="$1" dt
  local exif_used=0

  if command -v exiftool >/dev/null 2>&1; then
    dt=$(exiftool -s3 -DateTimeOriginal -d "%Y-%m" "$f" 2>/dev/null || true)
    if [[ -n "$dt" ]]; then
      exif_used=1
      echo "$dt|$exif_used"
      return
    fi
  fi

  # fallback to file mtime
  dt=$(date -r "$f" "+%Y-%m")
  echo "$dt|$exif_used"
}

copy_or_move() {
  local src="$1" dst="$2"
  if [[ "$DRYRUN" == "--dry-run" ]]; then
    log "Would $ACTION: $src -> $dst"
    return
  fi
  if [[ "$ACTION" == "--move" ]]; then
    mv -n "$src" "$dst"
  else
    cp -n "$src" "$dst"
  fi
}

process_file() {
  local f="$1" hash year month subdir dest base ext
  ((TOTAL++))
  hash=$(hash_file "$f")

  # skip duplicates
  if grep -q "^$hash " "$HASH_DB"; then
    log "Duplicate: $f"
    return
  fi

  ext="${f##*.}"
  ext="${ext,,}" # lowercase

  if [[ "$ext" =~ ^(mp4|mov|avi|mkv|flv|wmv)$ ]]; then
    subdir="$DST/videos"
    ((VIDEO_COUNT++))
  else
    read -r date exif_flag <<<"$(get_date_parts "$f" | tr '|' ' ')"
    year="${date%-*}"
    month="${date#*-}"

    if [[ "${exif_flag}" -eq 1 ]]; then
        ((EXIF_USED_COUNT++))
        log "EXIF used for $f -> $DST/$year/$month"
    else
        ((MTIME_USED_COUNT++))
        log "File mtime used for $f -> $DST/$year/$month"
    fi
  fi

  mkdir -p "$subdir"

  # resolve filename conflicts
  base=$(basename "$f")
  dest="$subdir/$base"
  while [[ -e "$dest" ]]; do
    dest="${subdir}/${base%.*}_$RANDOM.${base##*.}"
  done

  copy_or_move "$f" "$dest"

  [[ "$DRYRUN" != "--dry-run" ]] && echo "$hash $dest" >>"$HASH_DB"
}

export -f log hash_file get_date_parts copy_or_move process_file
export SRC DST HASH_DB ACTION DRYRUN

# File extensions to process
find "$SRC" -type f \
  \( -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.png' -o -iname '*.heic' \
     -o -iname '*.gif' -o -iname '*.tiff' -o -iname '*.mp4' -o -iname '*.mov' \
     -o -iname '*.avi' -o -iname '*.mkv' -o -iname '*.flv' -o -iname '*.wmv' \) \
  -print0 | xargs -0 -n1 -P4 bash -c 'process_file "$@"' _

# ✅ Print summary
echo
echo "===== Summary ====="
echo "Total files processed : $TOTAL"
echo "Photos using EXIF    : $EXIF_USED_COUNT"
echo "Photos using mtime   : $MTIME_USED_COUNT"
echo "Videos               : $VIDEO_COUNT"
echo "===================="
