import subprocess
import socket
import struct
import sys
import os
import time
import re
import argparse
import shutil
import threading
import collections
from pathlib import Path

APP_DIR = (Path(sys.executable).resolve().parent if getattr(sys, "frozen", False)
           else Path(__file__).resolve().parent)
# player: tanpa popup console (0x08000000) + prioritas ABOVE_NORMAL (0x8000) supaya tidak tersendat
_NOWIN  = {"creationflags": 0x08000000 | 0x00008000} if os.name == "nt" else {}


def _hidden_console():
    """adb tetap punya console (disembunyikan) -> handle stdin/stdout valid, tanpa popup."""
    if os.name != "nt":
        return {}
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 0                      # SW_HIDE
    return {"startupinfo": si}


_HIDE = _hidden_console()

ADB         = "adb"
LOCAL_PORT  = 27183
SERVER_DEST = "/data/local/tmp/scrcpy-server.jar"


# ══════════════════════════════════════════════════════════════════
#  ADB helpers
# ══════════════════════════════════════════════════════════════════

def adb(*args, serial=None, timeout=20):
    cmd = [ADB]
    if serial:
        cmd += ["-s", serial]
    cmd += list(args)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           errors="replace", timeout=timeout, **_HIDE)
        return r.stdout.strip(), r.stderr.strip(), r.returncode
    except FileNotFoundError:
        sys.exit("[!] 'adb' tidak ditemukan. Pastikan ADB ada di PATH.")
    except subprocess.TimeoutExpired:
        return "", "timeout", 1


def find_usb_devices():
    out, _, _ = adb("devices")
    devices = []
    for line in out.splitlines()[1:]:
        line = line.strip()
        if line.endswith("\tdevice") and ":" not in line:
            devices.append(line.split("\t")[0])
    return devices


def get_wifi_ip(serial):
    attempts = [
        ("shell", "ip", "route"),
        ("shell", "ip", "-4", "addr", "show", "wlan0"),
        ("shell", "ifconfig", "wlan0"),
        ("shell", "ip", "addr"),
    ]
    for cmd in attempts:
        out, _, _ = adb(*cmd, serial=serial)
        for m in re.finditer(r'(?:src |inet (?:addr:)?)(\d{1,3}(?:\.\d{1,3}){3})', out):
            ip = m.group(1)
            if not ip.startswith(("127.", "0.", "255.", "169.254.")):
                return ip
    return None


def setup_wireless(serial, adb_port=5555):
    ip = get_wifi_ip(serial)
    if not ip:
        print("  [!] Tidak bisa baca IP WiFi dari device")
        return None

    print(f"  [*] IP device  : {ip}")
    print(f"  [*] Switching ke TCP/IP port {adb_port}...")
    adb("tcpip", str(adb_port), serial=serial)
    time.sleep(2.5)

    target = f"{ip}:{adb_port}"
    out, _, code = adb("connect", target)
    if code or any(w in out.lower() for w in ("failed", "unable", "error", "refused")):
        print(f"  [!] Koneksi WiFi gagal: {out}")
        return None

    print(f"  [+] WiFi OK → {target}")
    return target


# ══════════════════════════════════════════════════════════════════
#  Cari scrcpy-server & player
# ══════════════════════════════════════════════════════════════════

def find_server_jar():
    here = APP_DIR
    candidates = [
        here / "scrcpy-server.jar",
        here / "scrcpy-server",
        here / "tools" / "scrcpy-server.jar",
        here / "tools" / "scrcpy-server",
        Path(r"C:\Program Files\scrcpy\scrcpy-server"),
        Path(r"C:\scrcpy\scrcpy-server"),
    ]
    for name in ("scrcpy-server", "scrcpy-server.jar"):
        for base in os.environ.get("PATH", "").split(os.pathsep):
            if base:
                candidates.append(Path(base) / name)
    for c in candidates:
        if c.is_file():
            return str(c)
    return None


def _which(name):
    """Cari exe di folder script dulu, baru di PATH."""
    for base in (APP_DIR, APP_DIR / "tools"):
        for cand in (base / f"{name}.exe", base / name):
            if cand.is_file():
                return str(cand)
    return shutil.which(name)


def find_player(prefer="auto"):
    """Return (nama, path). mpv diutamakan: dia bisa menampilkan frame TANPA timestamp."""
    order = ["mpv", "ffplay"] if prefer == "auto" else [prefer]
    for name in order:
        path = _which(name)
        if path:
            return name, path
    return None, None


def build_player_cmd(player, exe, codec, fps, hwdec, title="LNRCast"):
    """
    Stream H.264 mentah TIDAK punya timestamp. Player yang menunggu timestamp
    akan menganggap 25 fps -> video jadi slow-motion + delay menumpuk.
      mpv    : --untimed = tampilkan frame secepat selesai di-decode (benar)
      ffplay : tidak punya mode itu, jadi dipaksa -framerate sebagai tambalan
    """
    fmt = "hevc" if codec == "h265" else "h264"

    if player == "ffplay":
        return [
            exe,
            "-fflags", "nobuffer",
            "-flags", "low_delay",
            "-framedrop",
            "-analyzeduration", "0",
            "-probesize", "32",
            "-avioflags", "direct",
            "-strict", "experimental",
            "-sync", "ext",
            "-window_title", title,
            "-f", fmt,
            "-framerate", str(fps),
            "-i", "pipe:0",
        ]
    return [
        exe,
        "--profile=low-latency",
        f"--hwdec={hwdec}",            # nvdec = dekode di GPU NVIDIA
        "--vo=gpu",
        "--no-cache",
        "--untimed",
        "--no-demuxer-thread",
        "--video-sync=desync",
        "--d3d11-sync-interval=0",      # jangan tunggu vsync: monitor 60Hz + stream 120fps = slow-mo
        "--swapchain-depth=1",
        "--framedrop=decoder+vo",
        f"--demuxer-lavf-format={fmt}",
        # --demuxer-lavf-o bertipe key/value list: kalau ditulis berkali-kali, yang TERAKHIR
        # menimpa semua sebelumnya (framerate & fflags dulu hilang). Jadi digabung 1 argumen.
        f"--demuxer-lavf-o=framerate={fps},fflags=+nobuffer",
        f"--container-fps-override={fps}",
        "--vd-lavc-o=flags=+low_delay",         # decoder langsung keluarkan frame, tanpa buffer reorder
        "--vd-lavc-fast",
        "--demuxer-lavf-analyzeduration=0",
        f"--title={title}",
        "--no-audio",
        "--input-terminal=no",
        "-",
    ]


def tune_process():
    """Windows: timer 1 ms (wake-up thread lebih presisi) + prioritas proses ABOVE_NORMAL."""
    if os.name != "nt":
        return
    try:
        import ctypes
        ctypes.windll.winmm.timeBeginPeriod(1)
        k = ctypes.windll.kernel32
        k.GetCurrentProcess.restype = ctypes.c_void_p
        k.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        k.SetPriorityClass(k.GetCurrentProcess(), 0x00008000)
    except Exception:
        pass


def display_refresh_hz():
    """Refresh rate monitor utama (Windows). None kalau tidak bisa dibaca."""
    if os.name != "nt":
        return None
    try:
        import ctypes
        u, g = ctypes.windll.user32, ctypes.windll.gdi32
        u.GetDC.restype = ctypes.c_void_p
        u.GetDC.argtypes = [ctypes.c_void_p]
        u.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        g.GetDeviceCaps.argtypes = [ctypes.c_void_p, ctypes.c_int]
        hdc = u.GetDC(None)
        hz = g.GetDeviceCaps(hdc, 116)          # VREFRESH
        u.ReleaseDC(None, hdc)
        return hz if hz > 1 else None
    except Exception:
        return None


def write_all(f, data):
    """write() ke pipe bisa parsial -> ulangi sampai semua byte terkirim."""
    mv = memoryview(data)
    while len(mv):
        n = f.write(mv)
        mv = mv[len(mv) if n is None else n:]


def extract_sps(payload, codec):
    """
    Ambil NAL SPS dari payload Annex-B (None kalau tidak ada / codec AV1).
    Yang dibandingkan hanya SPS-nya, bukan seluruh payload, karena sebagian
    encoder menempelkan SPS/PPS di depan setiap keyframe.
    """
    if codec not in ("h264", "h265"):
        return None
    want = 33 if codec == "h265" else 7
    i = payload.find(b"\x00\x00\x01")
    while i != -1 and i + 3 < len(payload):
        start = i + 3
        nxt = payload.find(b"\x00\x00\x01", start)
        b = payload[start]
        nal_type = (b >> 1) & 0x3F if codec == "h265" else b & 0x1F
        if nal_type == want:
            end = len(payload) if nxt == -1 else nxt
            return bytes(payload[start:end]).rstrip(b"\x00")
        i = nxt
    return None


def start_audio_player(player, exe):
    """
    Audio dari HP datang sebagai PCM mentah: 16-bit little-endian, 48000 Hz, stereo.
    Opsi ffplay untuk raw audio beda antar versi FFmpeg, jadi coba beberapa varian.
    """
    if player == "mpv":
        cmds = [[
            exe, "--no-video", "--force-window=no", "--really-quiet",
            "--profile=low-latency", "--cache=no",
            "--demuxer-readahead-secs=0", "--demuxer-max-bytes=64KiB",
            "--audio-buffer=0.03", "--audio-pitch-correction=no",
            "--demuxer=rawaudio", "--demuxer-rawaudio-format=s16le",
            "--demuxer-rawaudio-rate=48000", "--demuxer-rawaudio-channels=2",
            "--input-terminal=no", "-",
        ]]
    else:
        base = [exe, "-nodisp", "-fflags", "nobuffer", "-flags", "low_delay",
                "-probesize", "32", "-analyzeduration", "0", "-f", "s16le"]
        variants = [
            ["-sample_rate", "48000", "-ch_layout", "stereo"],
            ["-sample_rate", "48000", "-channels", "2"],
            ["-ar", "48000", "-ac", "2"],
        ]
        cmds = [base + v + ["-i", "pipe:0"] for v in variants]

    for cmd in cmds:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, bufsize=0, **_NOWIN)
        time.sleep(0.8)
        if proc.poll() is None:       # masih hidup = opsi diterima
            return proc
    return None


# ══════════════════════════════════════════════════════════════════
#  Mirror session
# ══════════════════════════════════════════════════════════════════

class MirrorSession:
    _CODEC_MAP = {
        0x68323634: "h264",
        0x68323635: "h265",
        0x00617631: "av1",
    }

    def __init__(self, serial, *, fps=120, bitrate_mbps=20, max_size=0,
                 codec="h264", encoder="", iframe_interval=1, scrcpy_ver="auto",
                 audio=True, audio_dup=False, hwdec="nvdec", player_pref="auto",
                 audio_max_ms=0, max_lag_ms=150, lowlat=True, cbr="auto", stats_sec=5):
        self.audio           = audio
        self.audio_dup       = audio_dup
        # 0 = auto: USB jitter kecil -> buffer ketat; WiFi butuh ruang lebih
        wifi = ":" in serial or "_adb-tls" in serial
        self.audio_max_ms    = audio_max_ms or (120 if wifi else 50)
        self.max_lag_ms      = max_lag_ms        # 0 = matikan pemangkasan lag video
        self.lowlat          = lowlat            # opsi encoder low-latency (auto-fallback kalau gagal)
        self._stopping       = False
        self._stop_req       = False
        self._got_frame      = False
        self._launched       = False
        self.vstats          = {"snaps": 0, "dropped": 0}
        # CBR = ukuran frame stabil -> tidak ada lonjakan data di WiFi (auto: WiFi on, USB off)
        self.cbr             = wifi if cbr == "auto" else (cbr in (True, "on"))
        self.stats_sec       = stats_sec
        self._vwin           = {"frames": 0, "bytes": 0, "lag": 0.0, "gap": 0.0, "last": 0.0}
        self._awin           = {"maxb": 0, "drops": 0}
        self._sock = self._asock = self._server = None
        self.hwdec           = hwdec
        self.player_pref     = player_pref
        self._aplayer        = None
        self._player         = None
        self.serial          = serial
        self.fps             = fps
        self.bitrate         = bitrate_mbps * 1_000_000
        self.max_size        = max_size
        self.codec           = codec
        self.encoder         = encoder
        self.iframe_interval = iframe_interval
        self.scrcpy_ver      = scrcpy_ver
        self.server_log      = []

    def _push_jar(self, jar_path):
        _, err, code = adb("push", str(jar_path), SERVER_DEST,
                           serial=self.serial, timeout=30)
        if code:
            raise RuntimeError(f"Push JAR gagal: {err}")
        print("  [+] Server ter-push ke device")

    def _detect_version(self):
        """
        Versi di argumen pertama HARUS sama persis dengan versi file server,
        kalau tidak server langsung exit. Jadi kita pancing dengan versi palsu,
        lalu baca versi asli dari pesan errornya.
        """
        if self.scrcpy_ver != "auto":
            return self.scrcpy_ver

        out, err, _ = adb(
            "shell", f"CLASSPATH={SERVER_DEST}", "app_process", "/",
            "com.genymobile.scrcpy.Server", "0.0", "log_level=info",
            serial=self.serial, timeout=15,
        )
        m = re.search(r"server version \(([^)]+)\)", out + "\n" + err)
        if m:
            return m.group(1)

        try:
            r = subprocess.run(["scrcpy", "--version"], capture_output=True,
                               text=True, timeout=10, **_NOWIN)
            m = re.search(r"scrcpy\s+(\d+(?:\.\d+)+)", r.stdout)
            if m:
                return m.group(1)
        except Exception:
            pass

        raise RuntimeError(
            "Gagal deteksi versi scrcpy-server.\n"
            f"      Output: {(out + err)[:300]!r}\n"
            "      Coba manual: python mirror.py --scrcpy-ver <versi>  (lihat: scrcpy --version)"
        )

    def _forward_port(self):
        _, err, code = adb("forward", f"tcp:{LOCAL_PORT}", "localabstract:scrcpy",
                           serial=self.serial)
        if code:
            raise RuntimeError(f"Port forward gagal: {err}")
        print(f"  [+] Port forwarded: 127.0.0.1:{LOCAL_PORT}")

    def _codec_opts(self):
        opts = [f"i-frame-interval={self.iframe_interval}"]
        if self.cbr:
            opts.append("bitrate-mode=2")      # 2 = CBR (1 = VBR)
        if self.lowlat:
            # latency=0 : mode low-latency MediaCodec (Android 11+)
            # priority=0: encoder realtime, bukan best-effort
            # max-bframes=0: tanpa B-frame -> tidak ada reorder delay (Android 13+)
            # key yang tidak dikenal encoder diabaikan MediaCodec
            opts += ["latency=0", "priority=0", "max-bframes=0"]
        return opts

    def _launch_server(self):
        kv = {
            "log_level":           "info",
            "video":               "true",
            "audio":               "true" if self.audio else "false",
            "control":             "false",
            "tunnel_forward":      "true",
            "max_size":            str(self.max_size),
            "max_fps":             str(self.fps),
            "video_bit_rate":      str(self.bitrate),
            "video_codec":         self.codec,
            "video_codec_options": ",".join(self._codec_opts()),
        }
        if self.encoder:
            kv["video_encoder"] = self.encoder
        if self.audio:
            kv["audio_codec"] = "raw"          # PCM mentah, tanpa perlu decoder
            if self.audio_dup:
                kv["audio_dup"] = "true"       # suara tetap bunyi di HP (Android 13+)

        cmd = [
            ADB, "-s", self.serial, "shell",
            f"CLASSPATH={SERVER_DEST}",
            "app_process", "/",
            "com.genymobile.scrcpy.Server",
            self.scrcpy_ver,
            *[f"{k}={v}" for k, v in kv.items()],
        ]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT,
                                text=True, errors="replace", **_HIDE)

        def reader():
            for line in proc.stdout:
                self.server_log.append(line.rstrip())

        threading.Thread(target=reader, daemon=True).start()
        return proc

    def _connect_socket(self, server, retries=40):
        """
        adb forward SELALU menerima koneksi walau server di HP belum jalan,
        jadi 'connect berhasil' tidak cukup. Server baru dianggap siap kalau
        dia mengirim dummy byte pertama.
        """
        print("  [*] Menunggu server ", end="", flush=True)
        for _ in range(retries):
            if server.poll() is not None or self._stopping:
                break
            try:
                s = socket.create_connection(("127.0.0.1", LOCAL_PORT), timeout=3)
                s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                if s.recv(1):                 # dummy byte
                    s.settimeout(None)
                    print(" OK")
                    return s
                s.close()
            except OSError:
                pass
            print(".", end="", flush=True)
            time.sleep(0.5)

        print()
        if self._stopping:
            raise RuntimeError("Dibatalkan")
        time.sleep(0.5)
        log = "\n".join("        " + l for l in self.server_log) or "        (server tidak mengeluarkan output)"
        raise RuntimeError("Server di device gagal start. Output server:\n" + log)

    @staticmethod
    def _recv(sock, n):
        buf = bytearray(n)
        view = memoryview(buf)
        got = 0
        while got < n:
            r = sock.recv_into(view[got:], n - got)
            if not r:
                raise EOFError("Koneksi ditutup device")
            got += r
        return buf

    def _read_handshake(self, sock):
        """
        scrcpy 2.x/3.x setelah dummy byte:
          64 byte nama device | 4 byte codec id | 4 byte width | 4 byte height
        """
        name = self._recv(sock, 64).split(b"\x00")[0].decode("utf-8", "replace")
        codec_id, w, h = struct.unpack(">III", self._recv(sock, 12))
        codec = self._CODEC_MAP.get(codec_id, self.codec)
        print(f"  [+] Device: {name}  |  codec={codec}  |  {w}×{h}")
        return codec, w, h

    # tipe paket di antrean video
    _P_FRAME, _P_KEY, _P_CFG = 0, 1, 2

    @classmethod
    def _snap(cls, q):
        """
        Lag menumpuk -> lompat ke 'sekarang'. P-frame tidak boleh dibuang sembarangan
        (referensi frame sebelumnya = gambar rusak), jadi pangkas semua frame SEBELUM
        keyframe terbaru di antrean. Paket config (SPS/PPS) terakhir tetap dipertahankan.
        Return jumlah frame yang dibuang (0 = belum ada keyframe untuk dilompati).
        """
        items = list(q)
        k = -1
        for i in range(len(items) - 1, 0, -1):
            if items[i][1] == cls._P_KEY:
                k = i
                break
        if k <= 0:
            return 0
        head = items[:k]
        cfg = next((p for p in reversed(head) if p[1] == cls._P_CFG), None)
        dropped = sum(1 for p in head if p[1] != cls._P_CFG)
        q.clear()
        if cfg is not None:
            q.append(cfg)
        q.extend(items[k:])
        return dropped

    def _pump(self, sock, spawn, codec):
        """
        Setiap packet punya header 12 byte. Dua jenis:
          media   : [flags+PTS 8 byte][size 4 byte] + payload  -> kirim payload ke player
          session : (scrcpy baru) bit7 byte pertama = 1, byte 4-7 = lebar, 8-11 = tinggi,
                    TANPA payload. Dikirim saat HP berputar -> jangan dibaca sebagai size!
        flags: bit63 = config (SPS/PPS), bit62 = keyframe.

        Anti slow-mo / fast-forward:
          Thread ini HANYA menguras socket (tidak pernah menunggu player). Kalau player
          tersendat, paket menumpuk di antrean -> delay naik (slow-mo), lalu terburu-buru
          menyusul (fast). Kalau paket tertua di antrean sudah > max_lag_ms, antrean
          dilompatkan ke keyframe terbaru, jadi delay tidak bisa menumpuk.

        Rotasi = encoder di HP restart dengan SPS baru. Player tidak mengubah ukuran
        window sendiri, jadi saat SPS berubah writer me-restart player.
        """
        cv = threading.Condition()
        q = collections.deque()
        st = {"done": False}
        lag_s = self.max_lag_ms / 1000.0
        writer = threading.Thread(target=self._video_writer,
                                  args=(cv, q, st, spawn, codec), daemon=True)
        writer.start()
        try:
            while True:
                hdr = self._recv(sock, 12)

                if hdr[0] & 0x80 and hdr[4:8] != b"\x00\x00\x00\x00":
                    sw, sh = struct.unpack(">II", hdr[4:12])
                    if 0 < sw <= 16384 and 0 < sh <= 16384:
                        continue          # session packet: tidak ada payload

                size = struct.unpack(">I", hdr[8:12])[0]
                if not size:
                    continue
                payload = self._recv(sock, size)
                self._got_frame = True

                if hdr[0] & 0x80:
                    kind = self._P_CFG
                elif hdr[0] & 0x40:
                    kind = self._P_KEY
                else:
                    kind = self._P_FRAME

                now = time.monotonic()
                w = self._vwin
                w["frames"] += 1
                w["bytes"] += size
                if w["last"]:
                    w["gap"] = max(w["gap"], now - w["last"])
                w["last"] = now
                with cv:
                    q.append((now, kind, payload))
                    w["lag"] = max(w["lag"], now - q[0][0])
                    if lag_s and now - q[0][0] > lag_s:
                        d = self._snap(q)
                        if d:
                            self.vstats["snaps"] += 1
                            self.vstats["dropped"] += d
                    cv.notify()
        except (BrokenPipeError, OSError):
            pass
        except EOFError:
            if not self._stopping:
                print("\n  [!] Stream terputus dari device")
                if self.server_log:
                    print("      Log server:")
                    for l in self.server_log[-10:]:
                        print("        " + l)
        finally:
            with cv:
                st["done"] = True
                cv.notify_all()

    def _video_writer(self, cv, q, st, spawn, codec):
        """Satu-satunya thread yang menulis ke stdin player; boleh block tanpa menahan socket."""
        last_sps = None
        try:
            while True:
                with cv:
                    while not q and not st["done"]:
                        cv.wait()
                    if not q:
                        break
                    _, kind, payload = q.popleft()

                if kind != self._P_FRAME:
                    sps = extract_sps(payload, codec)
                    if sps is not None:
                        if last_sps is not None and sps != last_sps:
                            print("  [*] Orientasi/resolusi berubah — restart window player")
                            self._stop_player(self._player)
                            self._player = spawn()
                        last_sps = sps

                write_all(self._player.stdin, payload)
        except (BrokenPipeError, OSError, ValueError):
            pass
        finally:
            self.stop()                   # player mati / stream selesai -> akhiri sesi

    @staticmethod
    def _stop_player(proc):
        for closer in (lambda: proc.stdin.close(), lambda: proc.terminate()):
            try:
                closer()
            except Exception:
                pass

    def _connect_audio(self):
        """
        Socket kedua = audio. Harus connect SETELAH socket video dan SEBELUM
        membaca handshake video, karena server menunggu semua socket tersambung.
        """
        s = socket.create_connection(("127.0.0.1", LOCAL_PORT), timeout=5)
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        return s

    def _audio_loop(self, sock, player_name, exe):
        """
        Anti-delay audio:
          - Socket audio SELALU dikuras (thread ini), tidak pernah menunggu player.
          - Data disimpan di antrean kecil; kalau backlog > audio_max_ms, paket
            terlama dibuang (loncat ke 'sekarang') -> delay tidak bisa menumpuk.
          - Audio yang datang selama player masih booting dibuang.
        """
        BPS      = 48000 * 2 * 2                       # s16le stereo 48kHz
        max_b    = int(BPS * self.audio_max_ms / 1000)
        keep_b   = max_b // 2
        cv       = threading.Condition()
        buf      = collections.deque()
        st       = {"bytes": 0, "ready": False, "done": False}

        def writer():
            ap = start_audio_player(player_name, exe)
            if not ap:
                print("  [!] Player audio gagal start. Lanjut tanpa suara.")
                st["done"] = True
                return
            self._aplayer = ap
            with cv:
                buf.clear()
                st["bytes"] = 0
                st["ready"] = True
            print("  [+] Audio aktif")
            try:
                while True:
                    with cv:
                        while not buf and not st["done"]:
                            cv.wait()
                        if not buf:
                            break
                        chunk = buf.popleft()
                        st["bytes"] -= len(chunk)
                    write_all(ap.stdin, chunk)
            except (OSError, ValueError):
                pass
            finally:
                st["done"] = True
                try:
                    ap.stdin.close()
                except Exception:
                    pass

        try:
            sock.settimeout(15)
            codec_id = struct.unpack(">I", self._recv(sock, 4))[0]
            if codec_id in (0, 1):
                print("  [!] Audio tidak tersedia di device ini (butuh Android 11+). Lanjut tanpa suara.")
                return
            sock.settimeout(None)

            threading.Thread(target=writer, daemon=True).start()

            while not st["done"]:
                hdr  = self._recv(sock, 12)
                size = struct.unpack(">I", hdr[8:12])[0]
                if not size:
                    continue
                data = self._recv(sock, size)
                if not st["ready"]:
                    continue                           # player belum siap -> buang
                with cv:
                    buf.append(data)
                    st["bytes"] += len(data)
                    self._awin["maxb"] = max(self._awin["maxb"], st["bytes"])
                    if st["bytes"] > max_b:            # backlog -> buang yang lama
                        self._awin["drops"] += 1
                        while len(buf) > 1 and st["bytes"] > keep_b:
                            st["bytes"] -= len(buf.popleft())
                    cv.notify()
        except (OSError, EOFError, struct.error):
            pass
        finally:
            with cv:
                st["done"] = True
                cv.notify_all()
            try:
                sock.close()
            except Exception:
                pass

    def _dump_logcat(self):
        """Tampilkan baris logcat yang relevan supaya penyebab 'Aborted' kelihatan."""
        out, _, _ = adb("logcat", "-d", "-t", "400", serial=self.serial, timeout=15)
        keys = ("scrcpy", "MediaCodec", "CCodec", "Codec2", "C2", "qti", "DEBUG",
                "FATAL", "bort", "tombstone", "AndroidRuntime")
        lines = [l for l in out.splitlines() if any(k in l for k in keys)][-15:]
        if lines:
            print("  Logcat HP:")
            for l in lines:
                print("    " + l[:200])

    def _stats_loop(self):
        """Satu baris ringkas tiap stats_sec detik: lihat dari mana lonjakan/lag berasal."""
        BPMS = 48000 * 4 / 1000.0
        last_t = time.monotonic()
        last_snaps = 0
        while not self._stopping:
            time.sleep(0.25)
            now = time.monotonic()
            if now - last_t < self.stats_sec:
                continue
            dt = now - last_t
            last_t = now
            w, a = self._vwin, self._awin
            snaps = self.vstats["snaps"] - last_snaps
            last_snaps = self.vstats["snaps"]
            line = (f"  [stat] {w['frames'] / dt:5.1f}fps {w['bytes'] * 8 / dt / 1e6:5.1f}Mbps"
                    f" | video: lag maks {w['lag'] * 1000:3.0f}ms, jeda maks {w['gap'] * 1000:3.0f}ms, snap {snaps}")
            if self.audio:
                line += f" | audio: buf maks {a['maxb'] / BPMS:3.0f}/{self.audio_max_ms}ms, buang {a['drops']}"
            print(line)
            w.update(frames=0, bytes=0, lag=0.0, gap=0.0)
            a.update(maxb=0, drops=0)

    def _watch_player(self):
        """Window player ditutup user -> hentikan sesi (walau layar HP statis/tanpa frame)."""
        last = None
        while not self._stopping:
            time.sleep(0.5)
            p = self._player
            if p is not None and p.poll() is not None:
                if last is p:             # mati 2x cek berturut = bukan restart rotasi
                    self.stop()
                    return
                last = p
            else:
                last = None

    def stop(self):
        """Dipanggil dari thread lain (GUI) untuk menghentikan run()."""
        self._stop_req = True
        if self._stopping:
            return
        self._stopping = True
        for closer in (
            lambda: self._sock.shutdown(socket.SHUT_RDWR),
            lambda: self._sock.close(),
            lambda: self._asock.shutdown(socket.SHUT_RDWR),
            lambda: self._asock.close(),
            lambda: self._player.stdin.close(),
            lambda: self._player.terminate(),
            lambda: self._aplayer.terminate(),
            lambda: self._server.terminate(),
        ):
            try:
                closer()
            except Exception:
                pass

    def _cleanup(self):
        adb("forward", "--remove", f"tcp:{LOCAL_PORT}", serial=self.serial)

    def run(self):
        jar = find_server_jar()
        if not jar:
            print(
                "\n  [!] scrcpy-server tidak ditemukan!"
                "\n      Taruh file 'scrcpy-server' di folder yang sama dengan mirror.py"
                f"\n      ({APP_DIR})\n"
            )
            return False

        player_name, player_exe = find_player(self.player_pref)
        if not player_name:
            print("\n  [!] mpv / ffplay tidak ditemukan!"
                  "\n      Disarankan mpv (https://mpv.io): taruh mpv.exe di PATH atau di folder mirror.py\n")
            return False

        if player_name == "ffplay" and (self.max_size == 0 or self.max_size > 1080 or self.fps > 60):
            self.max_size = 1080 if (self.max_size == 0 or self.max_size > 1080) else self.max_size
            self.fps = min(self.fps, 60)
            print("  [!] ffplay decode di CPU: dibatasi 60fps & max 1080px biar tidak slow-motion/delay")
            print("      (pasang mpv.exe untuk native/120fps)")
        print(f"  [*] Player: {player_name}" +
              (f"  (hwdec={self.hwdec})" if player_name == "mpv" else
               "  (ffplay tidak bisa lepas timestamp & tanpa GPU decode — pakai mpv untuk hasil terbaik)"))
        print(f"  [*] Server: {jar}")

        tune_process()
        hz = display_refresh_hz()
        if hz and self.fps > hz:
            print(f"  [i] Monitor {hz}Hz < {self.fps}fps: frame ekstra tidak akan tampil "
                  f"(pakai --fps {hz} biar lebih ringan & stabil)")
        print(f"  [*] Buffer audio maks: {self.audio_max_ms}ms  |  pangkas lag video: "
              + (f"{self.max_lag_ms}ms" if self.max_lag_ms else "off")
              + f"  |  bitrate: {'CBR' if self.cbr else 'VBR'}")

        attempts = [True, False] if self.lowlat else [False]
        ok = False
        for n, ll in enumerate(attempts):
            self.lowlat = ll
            if not ll:
                self.cbr = False
            ok, early = self._run_once(jar, player_name, player_exe)
            if ok or self._stop_req or not early or n == len(attempts) - 1:
                break
            print("\n  [!] Gagal start dengan opsi encoder low-latency — ulang tanpa opsi itu\n")
            adb("shell", "pkill", "-f", "com.genymobile.scrcpy.Server", serial=self.serial)
            self._reset_state()
            time.sleep(1.0)
        if self.vstats["snaps"]:
            print(f"  [i] Lag video dipangkas {self.vstats['snaps']}x "
                  f"({self.vstats['dropped']} frame dilompati) — kalau sering, turunkan fps/bitrate/resolusi")
        return ok

    def _reset_state(self):
        self._stopping = False
        self._got_frame = False
        self._launched = False
        self._sock = self._asock = self._server = None
        self._player = self._aplayer = None
        self.server_log = []

    def _run_once(self, jar, player_name, player_exe):
        """Return (ok, early_fail). early_fail = server sudah jalan tapi belum ada frame sama sekali."""
        server = sock = asock = None
        try:
            self._push_jar(jar)
            self.scrcpy_ver = self._detect_version()
            print(f"  [+] Versi server: {self.scrcpy_ver}")
            self._forward_port()

            server = self._launch_server()
            self._server = server
            self._launched = True
            time.sleep(0.8)

            try:
                sock = self._connect_socket(server)
            except RuntimeError:
                if not self._stopping:
                    self._dump_logcat()
                raise
            self._sock = sock
            if self.audio:
                asock = self._connect_audio()
                self._asock = asock
            codec, w, h = self._read_handshake(sock)

            title = f"LNRCast — {self.fps}fps  {self.bitrate // 1_000_000}Mbps"

            def spawn():
                return subprocess.Popen(
                    build_player_cmd(player_name, player_exe, codec, self.fps, self.hwdec, title),
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    bufsize=0,                # tanpa buffer Python ke player
                    **_NOWIN,
                )

            self._player = spawn()
            threading.Thread(target=self._watch_player, daemon=True).start()
            if self.stats_sec:
                threading.Thread(target=self._stats_loop, daemon=True).start()

            print(f"\n  ✓ Mirroring aktif!  ({self.fps}fps, {self.bitrate // 1_000_000}Mbps, {codec})")
            print("  → Ctrl+C atau tutup jendela player untuk berhenti.\n")

            if asock:
                threading.Thread(target=self._audio_loop,
                                 args=(asock, player_name, player_exe),
                                 daemon=True).start()

            self._pump(sock, spawn, codec)
            early = self._launched and not self._got_frame and not self._stop_req
            return (not early), early

        except KeyboardInterrupt:
            self._stop_req = True
            print("\n  [*] Dihentikan oleh pengguna")
            return True, False
        except Exception as exc:
            print(f"\n  [!] Error: {exc}")
            early = self._launched and not self._got_frame and not self._stop_req
            return False, early
        finally:
            self._stopping = True
            for closer in (
                lambda: sock.close(),
                lambda: asock.close(),
                lambda: self._player.stdin.close(),
                lambda: self._player.terminate(),
                lambda: self._aplayer.terminate(),
                lambda: server.terminate(),
            ):
                try:
                    closer()
                except Exception:
                    pass
            self._cleanup()
            print("  [*] Selesai.")


# ══════════════════════════════════════════════════════════════════
#  CLI
# ══════════════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser(description="LNRCast — Low-Latency Screen Mirror")
    ap.add_argument("--wireless", "-w", action="store_true",
                    help="Auto-setup WiFi dari USB, lalu mirror via WiFi")
    ap.add_argument("--ip", metavar="ADDR", help="Langsung pakai IP (atau IP:PORT)")
    ap.add_argument("--adb-port", type=int, default=5555)
    ap.add_argument("--fps", type=int, default=120)
    ap.add_argument("--bitrate", type=int, default=20, help="Mbps")
    ap.add_argument("--size", type=int, default=0, help="Max sisi panjang px (0=native)")
    ap.add_argument("--codec", choices=["h264", "h265", "av1"], default="h264")
    ap.add_argument("--encoder", default="",
                    help="Paksa encoder, mis. OMX.qcom.video.encoder.avc")
    ap.add_argument("--iframe", type=int, default=1, metavar="S",
                    help="I-frame interval detik (0 = tiap frame)")
    ap.add_argument("--scrcpy-ver", default="auto", metavar="VER",
                    help="Versi scrcpy-server (default: auto-detect)")
    ap.add_argument("--player", choices=["auto", "mpv", "ffplay"], default="auto",
                    help="Player video (auto = mpv dulu, fallback ffplay)")
    ap.add_argument("--hwdec", default="nvdec",
                    help="Dekode GPU di mpv: nvdec (NVIDIA), d3d11va, auto-safe, no")
    ap.add_argument("--no-audio", action="store_true", help="Matikan audio")
    ap.add_argument("--audio-dup", action="store_true",
                    help="Suara tetap bunyi di HP juga (Android 13+)")
    ap.add_argument("--audio-max-ms", type=int, default=0, metavar="MS",
                    help="Backlog audio maksimal sebelum dibuang (0 = auto: USB 50ms, WiFi 120ms; makin kecil = makin low-latency)")
    ap.add_argument("--max-lag-ms", type=int, default=150, metavar="MS",
                    help="Video menumpuk lebih dari ini -> lompat ke keyframe terbaru (0 = off)")
    ap.add_argument("--cbr", choices=["auto", "on", "off"], default="auto",
                    help="Bitrate konstan: frame stabil, tanpa lonjakan (auto = on di WiFi, off di USB)")
    ap.add_argument("--stats", type=int, default=5, metavar="SEC",
                    help="Cetak statistik lag/bitrate tiap SEC detik (0 = off)")
    ap.add_argument("--no-lowlat", action="store_true",
                    help="Matikan opsi encoder low-latency (latency/priority/max-bframes)")
    args = ap.parse_args()

    print()
    print("  ╔══════════════════════════════════════════════╗")
    print("  ║   LNRCast — Low-Latency Screen Mirror  ║")
    print("  ╚══════════════════════════════════════════════╝")
    print()

    print("[*] Restart ADB server...")
    adb("kill-server")
    adb("start-server")
    time.sleep(0.8)

    serial = None

    if args.ip:
        target = args.ip if ":" in args.ip else f"{args.ip}:{args.adb_port}"
        print(f"\n[*] Menghubungkan ke {target}...")
        out, _, code = adb("connect", target)
        if code or any(w in out.lower() for w in ("failed", "unable", "error", "refused")):
            sys.exit(f"[!] Gagal konek ke {target}: {out}")
        serial = target
        print(f"[+] Terhubung ke {target}")
    else:
        print()
        input("[?] Hubungkan kabel USB & aktifkan USB Debugging, lalu tekan Enter... ")
        print()

        usb_devs = find_usb_devices()
        if not usb_devs:
            sys.exit(
                "[!] Tidak ada USB device terdeteksi.\n"
                "    Pastikan kabel terhubung, USB Debugging aktif, dan driver ADB ter-install."
            )

        if len(usb_devs) == 1:
            serial = usb_devs[0]
            print(f"[+] Device: {serial}")
        else:
            for i, d in enumerate(usb_devs, 1):
                print(f"    {i}. {d}")
            try:
                serial = usb_devs[int(input("  Pilih nomor: ")) - 1]
            except (ValueError, IndexError):
                sys.exit("[!] Pilihan tidak valid")

        if args.wireless:
            print("\n[*] Setup wireless ADB...")
            wifi_serial = setup_wireless(serial, args.adb_port)
            if wifi_serial:
                print("[*] Kamu bisa lepas kabel USB sekarang")
                time.sleep(2)
                serial = wifi_serial
            else:
                print("[!] Wireless setup gagal, lanjut pakai USB")

    print()
    print(f"[*] Config: {args.fps}fps | {args.bitrate}Mbps | {args.codec.upper()} | "
          f"i-frame={args.iframe}s | size={'native' if args.size == 0 else args.size}px")
    print()

    MirrorSession(
        serial=serial,
        fps=args.fps,
        bitrate_mbps=args.bitrate,
        max_size=args.size,
        codec=args.codec,
        encoder=args.encoder,
        iframe_interval=args.iframe,
        scrcpy_ver=args.scrcpy_ver,
        audio=not args.no_audio,
        audio_dup=args.audio_dup,
        hwdec=args.hwdec,
        player_pref=args.player,
        audio_max_ms=args.audio_max_ms,
        max_lag_ms=args.max_lag_ms,
        lowlat=not args.no_lowlat,
        cbr=args.cbr,
        stats_sec=args.stats,
    ).run()


if __name__ == "__main__":
    main()
