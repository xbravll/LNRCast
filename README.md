
## Build
1. Pasang MSYS2 (https://www.msys2.org), default `C:\msys64`.
2. Dobel-klik **build.bat**  — atau buka shell **MSYS2 MINGW64** lalu:
   ```
   ./build.sh            # folder portabel  -> dist/LNRCast/LNRCast.exe
   ./build.sh onefile    # satu exe          -> dist/LNRCast.exe
   ```
   Script memasang `python`, `python-pyqt6`, `python-pyinstaller` via pacman, mengompilasi,
   lalu menyalin `tools/` (adb, mpv, scrcpy-server) dan `assets/` (font Inter, ikon) ke hasil build.
3. Salin folder hasil build ke mana saja — portabel. `settings.json` dibuat otomatis di sampingnya.

Jika `pacman` tidak menemukan paket, cek namanya: `pacman -Ss pyqt6` / `pacman -Ss pyinstaller`.

## Isi
- `src/mirror.py` — engine mirroring (tidak diubah dari punyamu).
- `src/mirror_gui.py`, `src/ui_kit.py` — UI baru sesuai Figma (jendela utama + dialog Pairing Wi-Fi).
- `tools/` — adb.exe + DLL, mpv.exe, scrcpy-server (dari zip LNR MIRROR).
- `assets/` — Inter Regular/Medium/SemiBold (lisensi OFL), ikon.

## Debug tampilan
`LNRCast.exe --snapshot out.png` (tambah `--pair` untuk dialog) merender jendela ke PNG lalu keluar.

## Catatan UI
- Jendela tanpa bingkai OS: tombol merah/kuning/hijau = tutup/minimize/maximize, bilah judul bisa di-drag, tepi bisa di-resize.
- Layar kecil: UI otomatis diskalakan agar muat (set `QT_SCALE_FACTOR` untuk menimpa).
- Pengaturan tersimpan otomatis; dikunci saat mirroring.
