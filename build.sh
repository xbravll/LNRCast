#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

case "${MSYSTEM:-}" in
  MINGW64|UCRT64|CLANG64) ;;
  *) echo "[!] Buka shell 'MSYS2 MINGW64' (bukan MSYS / MINGW32), lalu jalankan ulang."; exit 1 ;;
esac

PRE="${MINGW_PACKAGE_PREFIX}"
echo "[*] Memasang dependensi ($PRE-*) ..."
pacman -S --needed --noconfirm \
  "$PRE-python" "$PRE-python-pyqt6" "$PRE-python-pip"

echo "[*] Memasang PyInstaller via pip ..."
pip install pyinstaller --break-system-packages

MODE="${1:-onedir}"
FLAGS=(--noconfirm --clean --windowed --name LNRCast
       --icon "$(pwd)/assets/icon.ico" --paths src
       --distpath dist --workpath build/work --specpath build)
[ "$MODE" = "onefile" ] && FLAGS+=(--onefile) || FLAGS+=(--onedir)

echo "[*] Kompilasi ($MODE) ..."
python -m PyInstaller "${FLAGS[@]}" src/mirror_gui.py

if [ "$MODE" = "onefile" ]; then OUT="dist"; else OUT="dist/LNRCast"; fi
echo "[*] Menyalin tools/ dan assets/ ke $OUT ..."
rm -rf "$OUT/tools" "$OUT/assets"
cp -r tools  "$OUT/tools"
cp -r assets "$OUT/assets"

echo
echo "[+] Selesai. Portabel ada di: $OUT"
echo "    Jalankan LNRCast.exe (settings.json dibuat otomatis di sampingnya)."
