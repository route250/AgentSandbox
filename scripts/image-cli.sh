#!/usr/bin/env bash
set -euo pipefail
#
# bwrapをつかったsandboxでプロセスを起動するツール

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")"/.. && pwd)"
SBOX_ROOT="$PROJECT_DIR/images"
SBOX_BASE="$PROJECT_DIR/base"
SBOX_PROF="opencode"
SBOX_ID=""
SBOX_PORT=""
CREATE=0

# ------------------
# help message
# ------------------
usage() {
  echo "Usage: $0 --id IMAGE_ID --port PORT [--create]" >&2
  exit 2
}

# ------------------
# command line options
# ------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --id) SBOX_ID="${2:-}"; shift 2 ;;
    --port) SBOX_PORT="${2:-}"; shift 2 ;;
    --create) CREATE=1; shift ;;
    *) usage ;;
  esac
done

[[ "$SBOX_ID" =~ ^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$ ]] || usage
[[ "$SBOX_PORT" =~ ^[0-9]{1,5}$ ]] && (( SBOX_PORT >= 1024 && SBOX_PORT <= 65535 )) || usage

SBOX_IMG="$SBOX_ROOT/$SBOX_ID"
if [[ ! -d "$SBOX_IMG" && "$CREATE" -ne 1 ]]; then
  echo "Image does not exist: $SBOX_ID" >&2
  exit 1
fi

# ------------------
# check profile
# ------------------
PROF_DIR="$PROJECT_DIR/profile/$SBOX_PROF"
[[ -d "$PROF_DIR" ]] || { echo "Profile not found: $SBOX_PROF" >&2; exit 1; }

# ------------------
# create image dir
# ------------------
mkdir -p "$SBOX_ROOT" "$SBOX_IMG"
SBOX_FS="$SBOX_IMG/fs"
mkdir -p "$SBOX_FS/.sbox"


# ------------------
# copy shell rcfiles
# ------------------
for src in /etc/skel/.*; do
  [[ -f "$src" ]] || continue
  name="$(basename "$src")"
  dst="$SBOX_FS/$name"
  cp -f "$src" "$dst"
  extra="${SBOX_BASE}/skel/_${name#.}"
  [[ -f "$extra" ]] && cat "$extra" >> "$dst"
done

# ------------------
# mount system dirs
# ------------------
BWRAP_OPT=(--tmpfs / --dev /dev --proc /proc --ro-bind /sys /sys --tmpfs /run --tmpfs /tmp --share-net)
for d in /bin /sbin /etc /usr /lib /lib64 /var /run/systemd/resolve /run/dbus; do
  [[ -d "$d" ]] && BWRAP_OPT+=(--ro-bind "$d" "$d")
done
BWRAP_OPT+=(--bind "$SBOX_FS" "$HOME" --ro-bind "$SBOX_BASE/_sbox" "$HOME/.sbox")

# ------------------
# mount profiles
# ------------------
if [[ -x "$PROF_DIR/boot.sh" ]]; then
    chmod +x "$PROF_DIR/boot.sh"
    BWRAP_OPT+=(--ro-bind "$PROF_DIR/boot.sh" "$HOME/.boot.sh")
fi

while read -r mode share_path src_path; do
  [[ -n "$mode" ]] || continue
  [[ -n "$src_path" ]] || src_path="$PROF_DIR/$share_path"
  [[ -e "$src_path" ]] || { echo "Profile path not found: $share_path $src_path" >&2; exit 1; }
  dst="$SBOX_FS/$share_path"
  mkdir -p "$(dirname "$dst")"
  case "$mode" in
    ro) BWRAP_OPT+=(--ro-bind "$src_path" "$HOME/$share_path") ;;
    rw) BWRAP_OPT+=(--bind "$src_path" "$HOME/$share_path") ;;
    init) [[ -e "$dst" ]] || cp -a "$src_path" "$dst" ;;
    *) echo "Unknown profile mode: $mode" >&2; exit 1 ;;
  esac
done < <(sed 's/#.*$//' "$PROF_DIR/mount.cfg")

# ------------------
# environment
# ------------------
BWRAP_OPT+=(--setenv SBOX_ID "$SBOX_ID" --setenv SBOX_PORT "$SBOX_PORT")

# ------------------
# boot
# ------------------
command=(bwrap "${BWRAP_OPT[@]}" --chdir "$HOME" /bin/bash --login "$HOME/.sbox/boot.sh")
exec "${command[@]}"
