#!/bin/sh
# Adds hwp2x to the desktop application menu for the current user.
# Run from the unpacked hwp2x folder:  ./install.sh
set -e
here="$(cd "$(dirname "$0")" && pwd)"
apps="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
icons="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/512x512/apps"
mkdir -p "$apps" "$icons"
cp "$here/hwp2x-512.png" "$icons/hwp2x.png"
sed "s|^Exec=hwp2x-gui|Exec=\"$here/hwp2x-gui\"|" "$here/hwp2x.desktop" > "$apps/hwp2x.desktop"
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$apps" || true
echo "hwp2x 를 프로그램 메뉴에 추가했습니다."
