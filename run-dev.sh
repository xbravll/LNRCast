#!/usr/bin/env bash
# Jalankan langsung dari source (tanpa build) di shell MSYS2 MINGW64
cd "$(dirname "$0")" && PATH="$PWD/tools:$PATH" python src/mirror_gui.py "$@"
