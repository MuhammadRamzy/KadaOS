#!/usr/bin/env bash
# Build a copy of a GNOME Shell theme gresource with extra CSS appended to its gdm.css (no root needed).
#   bash config/brand/gdm-theme.sh SOURCE.gresource EXTRA.css   → prints the path of the new gresource
set -euo pipefail
src="$1"; css="$2"; d="$(mktemp -d)"; mkdir "$d/r"
trap 'rm -rf "${d:?}"' EXIT                            # on failure, clean up; on success the caller removes it
{ echo '<?xml version="1.0" encoding="UTF-8"?><gresources><gresource prefix="/">'
  while read -r p; do
    mkdir -p "$d/r$(dirname "$p")"; gresource extract "$src" "$p" > "$d/r$p"; echo "<file>${p#/}</file>"
  done < <(gresource list "$src")
  echo '</gresource></gresources>'; } > "$d/r/theme.xml"
f="$d/r/org/gnome/shell/theme/gdm.css"; [ -f "$f" ] || { echo "no gdm.css in $src" >&2; exit 1; }
cat "$css" >> "$f"
glib-compile-resources --sourcedir="$d/r" --target="$d/gnome-shell-theme.gresource" "$d/r/theme.xml"
trap - EXIT; echo "$d/gnome-shell-theme.gresource"
