#!/usr/bin/env python3
import sys
import os
import re
import json
import shutil
import threading
import time

# ── skala otomatis supaya jendela (868 px) muat di layar kecil ─────────────
def _fit_scale():
    if os.environ.get("QT_SCALE_FACTOR"):
        return
    try:
        import ctypes
        from ctypes import wintypes
        rc = wintypes.RECT()
        if not ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rc), 0):
            return
        aw, ah = rc.right - rc.left, rc.bottom - rc.top
        s = min(1.0, 0.97 * aw / 1188.0, 0.97 * ah / 868.0)
        if s < 0.995:
            os.environ["QT_SCALE_FACTOR"] = f"{max(0.55, s):.3f}"
    except Exception:
        pass


_fit_scale()

from PyQt6.QtCore import (                                   # noqa: E402
    Qt, QRectF, QPointF, QPoint, QTimer, pyqtSignal, QEvent,
)
from PyQt6.QtGui import (                                    # noqa: E402
    QPainter, QColor, QPen, QBrush, QPainterPath, QIcon, QRadialGradient,
    QLinearGradient, QPixmap, QCursor,
)
from PyQt6.QtWidgets import (                                # noqa: E402
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QMenu,
)

import mirror                                                # noqa: E402
from mirror import MirrorSession, APP_DIR                    # noqa: E402
import ui_kit as K                                           # noqa: E402
from ui_kit import (                                         # noqa: E402
    C, font, text, text_width, elide, icon, soft_shadow, figma_linear,
    draw_wallpaper, Panel, Clickable, GlassButton, DeviceSelect, PrimaryButton,
    Seg, Switch, BitrateControl, SelectBox, FieldBox, digits_validator,
    INK, MUTED, SOFT, ACCENT, GOOD, GOOD_TXT, WARN, WARN_TXT, BAD,
    LEFT_VC, RIGHT_VC, CENTER, TOP_LEFT_WRAP, NOPEN, NOBRUSH,
)

SETTINGS_FILE = APP_DIR / "settings.json"
DEFAULTS = {
    "fps": 60, "bitrate": 20, "dec": "gpu", "codec": "h264", "size": 0,
    "audio": True, "serial": "", "pair_addr": "", "conn_addr": "",
}

DAYS = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
MONTHS = ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli",
          "Agustus", "September", "Oktober", "November", "Desember"]


# ══════════════════════════════════════════════════════════════════
#  Settings & tools (logika sama seperti GUI lama)
# ══════════════════════════════════════════════════════════════════

def load_settings():
    cfg = dict(DEFAULTS)
    try:
        cfg.update(json.loads(SETTINGS_FILE.read_text(encoding="utf-8")))
    except Exception:
        pass
    return cfg


def save_settings(cfg):
    try:
        SETTINGS_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    except Exception:
        pass


def setup_tools():
    """Taruh folder app + tools\\ di depan PATH supaya adb/mpv/ffplay ketemu."""
    tools = APP_DIR / "tools"
    os.environ["PATH"] = os.pathsep.join(
        [str(APP_DIR), str(tools), os.environ.get("PATH", "")])
    adb = shutil.which("adb")
    mirror.ADB = adb or "adb"
    return {
        "adb": adb,
        "player": mirror.find_player()[0],
        "server": mirror.find_server_jar(),
    }


def safe_adb(*args, **kw):
    """mirror.adb() memanggil sys.exit kalau adb tidak ada -> tangkap."""
    try:
        return mirror.adb(*args, **kw)
    except SystemExit as e:
        return "", str(e), 1


_MARK = re.compile(r"^\[(stat|[!+*i])\]\s*(.*)$")
_TAGS = {"!": "ERROR", "+": "SIAP", "*": "INFO", "i": "INFO", "stat": "STATS"}


def classify(line):
    """Baris print() engine -> (tag, pesan) untuk kartu Aktivitas. None = abaikan."""
    t = line.strip()
    if not t or not any(ch.isalnum() for ch in t):
        return None
    tag, msg = "SISTEM", t
    m = _MARK.match(t)
    if m:
        tag, msg = _TAGS[m.group(1)], m.group(2)
    msg = re.sub(r"^[^\w\[\(]+\s*", "", msg)
    low = msg.lower()
    if tag in ("INFO", "SIAP", "SISTEM") and any(
            k in low for k in ("wifi", "wi-fi", "tcp/ip", "ip device", "adb connect")):
        tag = "WI-FI"
    elif tag == "INFO" and "usb" in low:
        tag = "USB"
    if "mirroring aktif" in low:
        tag = "SIAP"
    return tag, msg


TAG_COLORS = {
    "SISTEM": MUTED, "USB": ACCENT, "WI-FI": ACCENT, "SIAP": "#268667",
    "INFO": ACCENT, "ERROR": BAD, "STATS": "#7a6bd0",
}


# ══════════════════════════════════════════════════════════════════
#  Cangkang jendela (frameless, kaca, wallpaper pastel)
# ══════════════════════════════════════════════════════════════════

class TrafficLight(Clickable):
    def __init__(self, color, glyph, parent=None):
        super().__init__(12, 12, parent)
        self.color, self.glyph = color, glyph

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QBrush(C(self.color)))
        p.setPen(QPen(C("#000000", 0.12), 1))
        p.drawEllipse(QRectF(0.5, 0.5, 11, 11))
        if self._hover:
            p.setPen(QPen(C("#000000", 0.55), 1.3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            if self.glyph == "x":
                p.drawLine(QPointF(3.8, 3.8), QPointF(8.2, 8.2))
                p.drawLine(QPointF(8.2, 3.8), QPointF(3.8, 8.2))
            elif self.glyph == "-":
                p.drawLine(QPointF(3.4, 6), QPointF(8.6, 6))
            else:
                p.drawLine(QPointF(3.4, 6), QPointF(8.6, 6))
                p.drawLine(QPointF(6, 3.4), QPointF(6, 8.6))


class TitleBar(QWidget):
    H = 62

    def __init__(self, shell):
        super().__init__()
        self.shell = shell
        self.setFixedHeight(self.H)
        self.b_close = TrafficLight("#ff6059", "x", self)
        self.b_min = TrafficLight("#ffbd2e", "-", self)
        self.b_max = TrafficLight("#28c840", "+", self)
        self.b_close.move(24, 25)
        self.b_min.move(46, 25)
        self.b_max.move(68, 25)
        self.b_close.clicked.connect(shell.close)
        self.b_min.clicked.connect(shell.showMinimized)
        self.b_max.clicked.connect(shell.toggle_max)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        f = font(14, "semibold")
        tw = text_width("LNRCast", f)
        total = 18 + 9 + tw
        x0 = (w - total) / 2
        icon(p, "phone", QRectF(x0, 22, 18, 18), MUTED)
        text(p, x0 + 27, 0, tw + 6, self.H - 1, "LNRCast", f, INK)
        sf = font(11, "medium")
        s = "Low-latency screen mirror"
        text(p, w - 104 - text_width(s, sf) - 4, 0, text_width(s, sf) + 8, self.H - 1, s, sf, MUTED, RIGHT_VC)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            wh = self.shell.windowHandle()
            if wh is not None:
                wh.startSystemMove()

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.shell.toggle_max()


class Shell(QWidget):
    """Jendela utama: wallpaper + lapisan kaca putih 54% + bayangan, tanpa bingkai OS."""
    M = 18          # margin transparan tempat bayangan
    R = 28.0

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.page = QWidget(self)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(self.M, self.M, self.M, self.M)
        lay.setSpacing(0)
        lay.addWidget(self.page)
        self.overlay = None

    # ── geometri ─────────────────────────────────────────────────
    def _m(self):
        return 0 if self.isMaximized() else self.M

    def toggle_max(self):
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def changeEvent(self, e):
        if e.type() == QEvent.Type.WindowStateChange:
            m = self._m()
            self.layout().setContentsMargins(m, m, m, m)
            self.update()
        super().changeEvent(e)

    def resizeEvent(self, e):
        if self.overlay is not None:
            self.overlay.setGeometry(self.page.geometry())
        super().resizeEvent(e)

    def window_radius(self):
        return 0.0 if self.isMaximized() else self.R

    # ── resize dari tepi ─────────────────────────────────────────
    def _edges(self, pos):
        if self.isMaximized():
            return None
        g = 10
        x, y, w, h = pos.x(), pos.y(), self.width(), self.height()
        es = []
        if x < g:
            es.append(Qt.Edge.LeftEdge)
        elif x > w - g:
            es.append(Qt.Edge.RightEdge)
        if y < g:
            es.append(Qt.Edge.TopEdge)
        elif y > h - g:
            es.append(Qt.Edge.BottomEdge)
        if not es:
            return None
        r = es[0]
        for ed in es[1:]:
            r |= ed
        return r

    def mouseMoveEvent(self, e):
        ed = self._edges(e.position().toPoint())
        if ed is None:
            self.setCursor(Qt.CursorShape.ArrowCursor)
            return
        left_right = bool(ed & (Qt.Edge.LeftEdge | Qt.Edge.RightEdge))
        top_bottom = bool(ed & (Qt.Edge.TopEdge | Qt.Edge.BottomEdge))
        if left_right and top_bottom:
            diag = (bool(ed & Qt.Edge.LeftEdge) == bool(ed & Qt.Edge.TopEdge))
            self.setCursor(Qt.CursorShape.SizeFDiagCursor if diag else Qt.CursorShape.SizeBDiagCursor)
        elif left_right:
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        else:
            self.setCursor(Qt.CursorShape.SizeVerCursor)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            ed = self._edges(e.position().toPoint())
            wh = self.windowHandle()
            if ed is not None and wh is not None:
                wh.startSystemResize(ed)

    # ── gambar ───────────────────────────────────────────────────
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        m = self._m()
        r = QRectF(m, m, self.width() - 2 * m, self.height() - 2 * m)
        rad = self.window_radius()
        if m:
            soft_shadow(p, r, rad, blur=28, dy=10, color=QColor(46, 64, 128, 70))
        path = QPainterPath()
        path.addRoundedRect(r, rad, rad)
        p.setClipPath(path)
        draw_wallpaper(p, r)
        p.fillRect(r, C("#ffffff", 0.54))                                   # Jendela aplikasi
        p.fillRect(QRectF(r.x(), r.y(), r.width(), 62), C("#ffffff", 0.16))  # Bilah judul
        p.fillRect(QRectF(r.x(), r.y() + 61, r.width(), 1), C("#ffffff", 0.60))
        for w in self.findChildren(Panel):
            if w.has_shadow and w.isVisible():
                tl = w.mapTo(self, QPoint(0, 0))
                soft_shadow(p, QRectF(tl.x(), tl.y(), w.width(), w.height()), w.radius,
                            blur=24, dy=8, color=QColor(46, 64, 128, 36))
        p.setClipping(False)
        p.setBrush(NOBRUSH)
        p.setPen(QPen(C("#ffffff", 0.75), 1))
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), rad, rad)


# ══════════════════════════════════════════════════════════════════
#  Bagian-bagian halaman
# ══════════════════════════════════════════════════════════════════

class Hero(QWidget):
    H = 120

    def __init__(self):
        super().__init__()
        self.setFixedHeight(self.H)
        self.ok = True
        self.msg = "Semua sistem siap"

    def set_ready(self, ok, msg):
        self.ok, self.msg = ok, msg
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        text(p, 30, 26, 700, 35, "Layar kecil. Kemungkinan besar.", font(29, "semibold"), INK)
        text(p, 31, 70, 700, 17, "Hubungkan Android, atur kualitas, dan mulai mirroring.", font(14), MUTED)
        f = font(12, "medium")
        tw = text_width(self.msg, f)
        w = 14 + 8 + 10 + tw + 18
        x = self.width() - 31 - w
        y = 41
        p.setPen(NOPEN)
        p.setBrush(QBrush(C("#ffffff", 0.50)))
        p.drawRoundedRect(QRectF(x, y, w, 34), 17, 17)
        p.setBrush(QBrush(C(GOOD if self.ok else WARN)))
        p.drawEllipse(QRectF(x + 14, y + 13, 8, 8))
        text(p, x + 32, y, tw + 8, 34, self.msg, f, GOOD_TXT if self.ok else WARN_TXT)


class DeviceCard(Panel):
    def __init__(self):
        super().__init__(fill=0.48, radius=20, shadow=True)
        self.setFixedSize(432, 126)
        self.select = DeviceSelect(self)
        self.select.move(16, 49)
        self.refresh = GlassButton(44, 58, "refresh", icon_px=20, parent=self)
        self.refresh.move(308, 49)
        self.pair = GlassButton(56, 58, "wifi", label="Pair", color=ACCENT, icon_px=18, parent=self)
        self.pair.move(360, 49)
        self.count = 0

    def set_count(self, n):
        self.count = n
        self.update()

    def paint_content(self, p):
        text(p, 20, 17, 200, 18, "Perangkat", font(15, "semibold"), INK)
        s = f"{self.count} tersedia" if self.count else "Tidak ada"
        text(p, 216, 19, 200, 13, s, font(11, "medium"), MUTED, RIGHT_VC)


class QualityCard(Panel):
    def __init__(self):
        super().__init__(fill=0.52, radius=20, shadow=True)
        self.setFixedSize(432, 344)
        self.fps = Seg([("30 fps", 30), ("60 fps", 60), ("120 fps", 120)], 392, 38, parent=self)
        self.fps.move(20, 81)
        self.br = BitrateControl(392, self)
        self.br.move(20, 133)
        self.dec = Seg([("GPU", "gpu"), ("CPU", "cpu")], 177, 38, parent=self)
        self.dec.move(235, 206)
        self.codec = SelectBox([("H.264", "h264"), ("H.265", "h265")], 189, 40, self)
        self.codec.move(20, 286)
        self.res = SelectBox([("Native", 0), ("1440", 1440), ("1080", 1080), ("720", 720)], 189, 40, self)
        self.res.move(223, 286)
        self.dec.setToolTip("GPU = pakai GPU yang tersedia (butuh mpv). CPU = software.")

    def paint_content(self, p):
        text(p, 20, 18, 250, 18, "Kualitas streaming", font(15, "semibold"), INK)
        text(p, 212, 20, 200, 12, "Tersimpan otomatis", font(10), MUTED, RIGHT_VC)
        lf = font(12, "medium")
        text(p, 20, 58, 200, 15, "Frame rate", lf, MUTED)
        text(p, 20, 217, 200, 15, "Pemrosesan di PC", lf, MUTED)
        text(p, 20, 263, 150, 15, "Codec", lf, MUTED)
        text(p, 223, 263, 150, 15, "Resolusi maks.", lf, MUTED)


class AudioRow(Panel):
    def __init__(self):
        super().__init__(fill=0.40, radius=15, shadow=False, stroke=False)
        self.setFixedSize(432, 52)
        self.sw = Switch(self)
        self.sw.move(368, 13)

    def paint_content(self, p):
        icon(p, "speaker", QRectF(18, 16, 20, 20), ACCENT)
        text(p, 49, 11, 260, 16, "Audio perangkat", font(13, "medium"), INK)
        text(p, 49, 30, 260, 12, "Ikut diputar di komputer", font(10), MUTED)


class Caption(QWidget):
    def __init__(self, s, h=12, fnt=None, color=MUTED, align=CENTER):
        super().__init__()
        self.s, self.fnt, self.color, self.align = s, fnt or font(10), color, align
        self.setFixedHeight(h)

    def set_text(self, s):
        self.s = s
        self.update()

    def __call__(self, tag, msg):
        self.set_text(f"[{tag}] {msg}")

    def paintEvent(self, _):
        p = QPainter(self)
        text(p, 0, 0, self.width(), self.height(), self.s, self.fnt, self.color, self.align)


class SummaryCard(Panel):
    """Ilustrasi PC + Android + chip status (kartu 'Ringkasan perangkat')."""

    def __init__(self):
        super().__init__(fill=0.28, radius=20, shadow=False)
        self.setMinimumHeight(382)
        self.state = "idle"          # idle | starting | running
        self.conn = None             # "USB" | "Wi-Fi" | None
        self.gpu = True
        self.dev_name = ""
        self._clock = QTimer(self)
        self._clock.timeout.connect(self.update)
        self._clock.start(20000)

    def set_state(self, state=None, conn="keep", gpu=None, dev_name=None):
        if state is not None:
            self.state = state
        if conn != "keep":
            self.conn = conn
        if gpu is not None:
            self.gpu = gpu
        if dev_name is not None:
            self.dev_name = dev_name
        self.update()

    def paint_content(self, p):
        W, H = self.width(), self.height()
        has_dev = self.conn is not None

        # ── baris atas (menempel ke tepi kartu) ─────────────────
        cap = "PERANGKAT TERHUBUNG" if has_dev else "BELUM ADA PERANGKAT"
        text(p, 23, 21, 300, 12, cap, font(10, "semibold", 0.7), MUTED)
        label, dot = {"idle": ("Idle", "#8994ad"), "starting": ("Menyambung", WARN),
                      "running": ("Mirroring", "#20a27b")}[self.state]
        pf = font(11, "medium")
        pw = 12 + 6 + 7 + text_width(label, pf) + 16
        px = W - 20 - pw
        p.setPen(NOPEN)
        p.setBrush(QBrush(C("#ffffff", 0.55)))
        p.drawRoundedRect(QRectF(px, 16, pw, 27), 13.5, 13.5)
        p.setBrush(QBrush(C(dot)))
        p.drawEllipse(QRectF(px + 12, 16 + 10.5, 6, 6))
        text(p, px + 25, 16, pw, 27, label, pf, MUTED)

        # ── ilustrasi (desain 644x382, dipusatkan) ──────────────
        p.save()
        p.translate(max(0, (W - 644) / 2), max(0, (H - 382) / 2))

        # pendar
        p.save()
        p.translate(141 + 185, 28 + 115)
        p.scale(185.0 / 115.0, 1.0)
        g = QRadialGradient(QPointF(0, 0), 115)
        g.setColorAt(0.0, C("#a8b9ff", 0.80))
        g.setColorAt(1.0, C("#cadbff", 0.0))
        p.setPen(NOPEN)
        p.setBrush(QBrush(g))
        p.drawEllipse(QPointF(0, 0), 115, 115)
        p.restore()

        # monitor
        mx, my = 159, 91
        p.setPen(QPen(C("#ffffff", 0.95), 1))
        p.setBrush(QBrush(C("#f9faff", 0.70)))
        p.drawRoundedRect(QRectF(mx + 0.5, my + 0.5, 281, 176), 15, 15)
        screen = QRectF(mx + 7, my + 7, 268, 152)
        sp = QPainterPath()
        sp.addRoundedRect(screen, 10, 10)
        p.save()
        p.setClipPath(sp)
        p.fillRect(screen, QBrush(figma_linear(screen, 0.7, 0.7, -0.1,
                                               [(0.0, "#3542a6"), (0.5, "#6a85ee"), (1.0, "#b4bef8")])))
        p.setPen(NOPEN)
        p.setBrush(QBrush(C("#afbdff", 0.40)))
        p.drawEllipse(QRectF(screen.x() + 71, screen.y() + 53, 275, 275))
        p.restore()
        p.setPen(NOPEN)
        p.setBrush(QBrush(C("#f4f6ff", 0.90)))
        p.drawRoundedRect(QRectF(mx + 117, my + 177, 48, 17), 2, 2)
        p.drawRoundedRect(QRectF(mx + 90, my + 193, 102, 5), 3, 3)

        # android
        p.save()
        p.setOpacity(1.0 if has_dev else 0.45)
        body = QRectF(370, 56, 110, 218)
        soft_shadow(p, body, 23, blur=24, dy=12, color=QColor(46, 56, 128, 50))
        p.setPen(QPen(C("#ffffff", 0.95), 1))
        p.setBrush(QBrush(C("#f7f9ff", 0.85)))
        p.drawRoundedRect(body.adjusted(0.5, 0.5, -0.5, -0.5), 23, 23)
        scr = QRectF(375, 61, 100, 208)
        pp = QPainterPath()
        pp.addRoundedRect(scr, 19, 19)
        p.save()
        p.setClipPath(pp)
        p.fillRect(scr, QBrush(figma_linear(scr, 0.7, 0.7, -0.1,
                                            [(0.0, "#3542a6"), (0.5, "#6a85ee"), (1.0, "#b4bef8")])))
        p.restore()
        p.setPen(NOPEN)
        p.setBrush(QBrush(C(INK, 0.85)))
        p.drawRoundedRect(QRectF(scr.x() + 43, scr.y() + 7, 14, 5), 2.5, 2.5)
        now = time.localtime()
        text(p, scr.x(), scr.y() + 40, scr.width(), 33, time.strftime("%H:%M", now),
             font(27, "medium"), "#ffffff", CENTER)
        date = f"{DAYS[now.tm_wday]}, {now.tm_mday} {MONTHS[now.tm_mon - 1]}"
        text(p, scr.x(), scr.y() + 74, scr.width(), 10, date, font(8), "#ffffff", CENTER)
        p.setPen(NOPEN)
        p.setBrush(QBrush(C("#ffffff", 0.80)))
        p.drawRoundedRect(QRectF(scr.x() + 33, scr.y() + 198, 34, 3), 1.5, 1.5)
        p.restore()

        # chip koneksi
        chip = QRectF(91, 200, 160, 42)
        self._chip(p, chip)
        p.setPen(NOPEN)
        p.setBrush(QBrush(C("#20a27b" if has_dev else "#a3adc4")))
        p.drawEllipse(QRectF(chip.x() + 17, chip.y() + 17, 8, 8))
        label = {"USB": "USB terhubung", "Wi-Fi": "Wi-Fi terhubung"}.get(self.conn, "Belum ada perangkat")
        text(p, chip.x() + 34, chip.y(), 124, 42, label, font(12, "medium"), INK)

        # chip GPU / CPU
        chip = QRectF(448, 131, 147, 42)
        self._chip(p, chip)
        text(p, chip.x() + 16, chip.y(), 40, 42, "GPU" if self.gpu else "CPU", font(12, "semibold"), ACCENT)
        text(p, chip.x() + 48, chip.y(), 96, 42, "Siap digunakan" if self.gpu else "Decode software",
             font(10, "medium"), MUTED)

        # judul + subjudul
        title, sub = {
            "idle": ("Siap saat kamu siap.", "Layar Android akan terbuka di jendela pemutar terpisah."),
            "starting": ("Menyambungkan…", "Menyiapkan server di perangkat dan jendela pemutar."),
            "running": ("Sedang mirroring.", "Tutup jendela pemutar atau tekan Hentikan untuk berhenti."),
        }[self.state]
        if self.state == "idle" and not has_dev:
            title, sub = "Hubungkan perangkat.", "Colok kabel USB atau pair lewat Wi-Fi untuk memulai."
        text(p, 0, 296, 644, 30, title, font(25, "semibold"), INK, CENTER)
        text(p, 0, 335, 644, 15, sub, font(12), MUTED, CENTER)
        p.restore()

    @staticmethod
    def _chip(p, r):
        soft_shadow(p, r, 21, blur=10, dy=3, color=QColor(46, 64, 128, 28))
        p.setPen(QPen(C("#ffffff", 0.9), 1))
        p.setBrush(QBrush(C("#ffffff", 0.66)))
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 21, 21)


class LogCard(Panel):
    """Kartu 'Aktivitas' - baris waktu | tag | pesan, bisa di-scroll dengan roda mouse."""
    MAX = 400

    def __init__(self):
        super().__init__(fill=0.45, radius=20, shadow=False)
        self.setFixedHeight(170)
        self.events = []
        self.off = 0                       # jumlah baris digeser ke atas dari paling baru

    def add(self, tag, msg):
        self.events.append((time.strftime("%H:%M:%S"), tag, msg))
        if len(self.events) > self.MAX:
            del self.events[: len(self.events) - self.MAX]
        if self.off:
            self.off = min(self.off + 1, max(0, len(self.events) - self._rows()))
        self.update()

    def clear(self):
        self.events.clear()
        self.off = 0
        self.update()

    def _rows(self):
        return max(1, (self.height() - 61 - 8) // 30)

    def wheelEvent(self, e):
        rows = self._rows()
        mx = max(0, len(self.events) - rows)
        self.off = max(0, min(mx, self.off + (1 if e.angleDelta().y() > 0 else -1)))
        self.update()
        e.accept()

    def paint_content(self, p):
        W = self.width()
        text(p, 21, 17, 200, 17, "Aktivitas", font(14, "semibold"), INK)
        n = len(self.events)
        text(p, W - 20 - 160, 20, 160, 12, f"{n} peristiwa", font(10, "medium"), MUTED, RIGHT_VC)
        p.fillRect(QRectF(20, 46, W - 40, 1), C("#ffffff", 0.70))
        rows = self._rows()
        end = n - self.off
        start = max(0, end - rows)
        tf, cf, mf = font(11), font(9, "semibold"), font(11)
        for i, (t, tag, msg) in enumerate(self.events[start:end]):
            y = 61 + i * 30
            text(p, 21, y + 2, 66, 13, t, tf, SOFT)
            p.setPen(NOPEN)
            p.setBrush(QBrush(C("#ffffff", 0.50)))
            p.drawRoundedRect(QRectF(91, y, 57, 21), 6, 6)
            text(p, 91, y, 57, 21, tag, cf, TAG_COLORS.get(tag, MUTED), CENTER)
            text(p, 160, y + 2, W - 160 - 24, 13, elide(msg, mf, W - 160 - 24), mf, "#56617f")
        if n > rows:                                   # penanda scroll
            track = self.height() - 61 - 12
            th = max(18.0, track * rows / n)
            frac = 0.0 if n == rows else (start / (n - rows))
            ty = 58 + (track - th) * frac
            p.setPen(NOPEN)
            p.setBrush(QBrush(C("#8994ad", 0.35)))
            p.drawRoundedRect(QRectF(W - 12, ty, 3, th), 1.5, 1.5)


class DepsRow(QWidget):
    H = 43

    def __init__(self):
        super().__init__()
        self.setFixedHeight(self.H)
        self.items = [("ADB", False), ("Pemutar", False), ("Server", False)]

    def set_status(self, adb, player, server):
        self.items = [("ADB", bool(adb)), ("Pemutar", bool(player)), ("Server", bool(server))]
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        f = font(11, "medium")
        x = 10
        for name, ok in self.items:
            p.setPen(NOPEN)
            p.setBrush(QBrush(C("#269e79" if ok else BAD)))
            p.drawEllipse(QRectF(x, 17, 6, 6))
            label = f"{name} siap" if ok else f"{name} tidak ada"
            text(p, x + 14, 13, 130, 13, label, f, "#61718a")
            x += 145
        text(p, self.width() - 150, 13, 150, 12, "Tersimpan otomatis", font(10), "#75819c", RIGHT_VC)


# ══════════════════════════════════════════════════════════════════
#  Dialog pairing Wi-Fi (overlay modal di atas jendela)
# ══════════════════════════════════════════════════════════════════

class ArrowButton(Clickable):
    def __init__(self, label, w=464, h=46, parent=None):
        super().__init__(w, h, parent)
        self.label = label

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.isEnabled():
            base = "#a9b6d8"
        else:
            base = K.ACCENT_LO if self._down else (K.ACCENT_HI if self._hover else ACCENT)
        p.setPen(NOPEN)
        p.setBrush(QBrush(C(base)))
        p.drawRoundedRect(QRectF(self.rect()), 14, 14)
        text(p, 0, 0, self.width() - 56, self.height(), self.label, font(14, "semibold"), "#ffffff", CENTER)
        icon(p, "arrow", QRectF(self.width() - 47, 13, 20, 20), "#ffffff")


class LinkButton(Clickable):
    def __init__(self, label, icon_name, w=464, h=22, parent=None):
        super().__init__(w, h, parent)
        self.label, self.icon_name = label, icon_name

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setOpacity(self._alpha())
        f = font(12, "medium")
        col = ACCENT if self._hover else "#61718d"
        tw = text_width(self.label, f)
        x0 = (self.width() - (18 + 9 + tw)) / 2
        icon(p, self.icon_name, QRectF(x0, 2, 18, 18), col)
        text(p, x0 + 27, 0, tw + 6, self.height(), self.label, f, col)


class PairOverlay(QWidget):
    DW, DH = 520, 730
    connected = pyqtSignal(str)
    status = pyqtSignal(str)
    busy = pyqtSignal(bool)
    done = pyqtSignal(str)

    def __init__(self, shell, cfg):
        super().__init__(shell)
        self.shell, self.cfg = shell, cfg
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._bg = None
        self._msg = ""
        self._ox = self._oy = 0

        self.btn_close = GlassButton(34, 34, "close", radius=17, fill=0.60, color=MUTED,
                                     icon_px=16, base="#d9e0f1", circle=True, parent=self)
        self.f_pair = FieldBox("192.168.1.5:37123", parent=self)
        self.f_code = FieldBox("6 digit dari perangkat", tag="6 DIGIT", parent=self)
        self.f_code.edit.setValidator(digits_validator(self, 6))
        self.f_conn = FieldBox("192.168.1.5:41234", parent=self)
        self.btn_pair = ArrowButton("Pair & sambungkan", parent=self)
        self.btn_usb = LinkButton("USB → Wi-Fi otomatis", "usb", parent=self)

        self.btn_close.clicked.connect(self.close_overlay)
        self.btn_pair.clicked.connect(self.do_pair)
        self.btn_usb.clicked.connect(self.do_usb)
        self.status.connect(self._set_msg)
        self.busy.connect(self._set_busy)
        self.done.connect(self._ok)
        self.hide()

    # ── tata letak ───────────────────────────────────────────────
    def resizeEvent(self, e):
        self._ox = (self.width() - self.DW) // 2
        self._oy = max(0, (self.height() - self.DH) // 2)
        for w, (x, y) in ((self.btn_close, (456, 26)), (self.f_pair, (28, 367)),
                          (self.f_code, (28, 447)), (self.f_conn, (28, 573)),
                          (self.btn_pair, (28, 634)), (self.btn_usb, (28, 692))):
            w.move(self._ox + x, self._oy + y)
        super().resizeEvent(e)

    def _dlg_rect(self):
        return QRectF(self._ox, self._oy, self.DW, self.DH)

    # ── buka / tutup ─────────────────────────────────────────────
    def open_overlay(self):
        sh = self.shell
        base = sh.grab()                                        # tangkap jendela (overlay masih tersembunyi)
        w, h = sh.width(), sh.height()
        small = base.scaled(max(1, w // 12), max(1, h // 12),
                            Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
        self._bg = small.scaled(w, h, Qt.AspectRatioMode.IgnoreAspectRatio,
                                Qt.TransformationMode.SmoothTransformation)
        self.setGeometry(sh.page.geometry())
        self.f_pair.setText(self.cfg.get("pair_addr", ""))
        self.f_conn.setText(self.cfg.get("conn_addr", ""))
        self.f_code.setText("")
        self._msg = ""
        self.busy.emit(False)
        self.raise_()
        self.show()
        self.setFocus()
        (self.f_pair if not self.f_pair.text() else self.f_code).edit.setFocus()

    def close_overlay(self):
        self.hide()
        self._bg = None

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.close_overlay()
        elif e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.btn_pair.isEnabled():
            self.do_pair()
        else:
            super().keyPressEvent(e)

    def mousePressEvent(self, e):
        if not self._dlg_rect().contains(e.position()):
            self.close_overlay()

    # ── gambar ───────────────────────────────────────────────────
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        full = QRectF(self.rect())
        rad = self.shell.window_radius()
        wp = QPainterPath()
        wp.addRoundedRect(full, rad, rad)
        p.fillPath(wp, QBrush(C("#233258", 0.25)))                 # Latar modal

        r = self._dlg_rect()
        soft_shadow(p, r, 28, blur=64, dy=24, color=QColor(20, 36, 82, 80))
        dp = QPainterPath()
        dp.addRoundedRect(r, 28, 28)
        if self._bg is not None:
            p.save()
            p.setClipPath(dp)
            p.drawPixmap(QRectF(-self.x(), -self.y(), self._bg.width(), self._bg.height()),
                         self._bg, QRectF(self._bg.rect()))
            p.restore()
        p.fillPath(dp, QBrush(C("#f6f8ff", 0.84)))
        g = QLinearGradient(r.topLeft(), r.bottomRight())
        g.setColorAt(0.0, C("#ffffff", 0.95))
        g.setColorAt(1.0, C("#ffffff", 0.50))
        p.setBrush(NOBRUSH)
        p.setPen(QPen(QBrush(g), 1))
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 27.5, 27.5)

        p.save()
        p.translate(r.x(), r.y())
        # ikon wifi
        p.setPen(NOPEN)
        p.setBrush(QBrush(C("#ffffff", 0.80)))
        p.drawRoundedRect(QRectF(28, 28, 50, 50), 16, 16)
        icon(p, "wifi", QRectF(40, 40, 26, 26), ACCENT)
        # judul
        text(p, 28, 96, 464, 31, "Hubungkan tanpa kabel.", font(26, "semibold"), INK)
        text(p, 29, 135, 464, 16, "Pair Android melalui Wireless debugging.", font(13), MUTED)
        # kotak petunjuk
        p.setPen(NOPEN)
        p.setBrush(QBrush(C("#e1e9ff", 0.80)))
        p.drawRoundedRect(QRectF(28, 173, 464, 81), 14, 14)
        text(p, 43, 186, 300, 15, "Sebelum mulai", font(12, "semibold"), "#315998")
        p.setFont(font(12))
        p.setPen(QPen(C("#526888")))
        p.drawText(QRectF(43, 207, 432, 40), TOP_LEFT_WRAP,
                   "Gunakan Wi-Fi yang sama. Di Android, buka Opsi Developer → Wireless debugging.")
        # langkah 1
        self._step(p, 278, "1", "Pair perangkat")
        text(p, 28, 315, 464, 15, "Pilih “Pair device with pairing code” di Android.", font(12), MUTED)
        text(p, 28, 346, 300, 13, "IP:Port pairing", font(11, "medium"), MUTED)
        text(p, 28, 426, 300, 13, "Kode pairing", font(11, "medium"), MUTED)
        # langkah 2
        self._step(p, 510, "2", "Sambungkan")
        text(p, 28, 548, 464, 15, "IP:Port dari halaman utama Wireless debugging.", font(12), MUTED)
        # pesan status
        if self._msg:
            bad = any(k in self._msg.lower() for k in ("gagal", "isi ", "tidak"))
            text(p, 28, 618, 464, 15, elide(self._msg, font(11), 464), font(11), BAD if bad else ACCENT)
        p.restore()

    @staticmethod
    def _step(p, y, num, title):
        p.setPen(NOPEN)
        p.setBrush(QBrush(C(ACCENT, 0.10)))
        p.drawRoundedRect(QRectF(28, y, 25, 25), 8, 8)
        text(p, 28, y, 25, 25, num, font(12, "semibold"), ACCENT, CENTER)
        text(p, 64, y + 3, 300, 17, title, font(14, "semibold"), INK)

    # ── logika pairing (sama seperti GUI lama) ────────────────────
    def _set_msg(self, s):
        self._msg = s
        self.update()

    def _set_busy(self, b):
        self.btn_pair.setEnabled(not b)
        self.btn_usb.setEnabled(not b)
        if b:
            self._msg = "Bekerja…"
        self.update()

    def _ok(self, serial):
        self.busy.emit(False)
        self.cfg["pair_addr"] = self.f_pair.text()
        self.cfg["conn_addr"] = self.f_conn.text()
        self.close_overlay()
        self.connected.emit(serial)

    def do_pair(self):
        paddr, code, caddr = self.f_pair.text(), self.f_code.text(), self.f_conn.text()
        if not caddr and not (paddr and code):
            self.status.emit("Isi pairing (IP:port + kode) dan/atau IP:port koneksi.")
            return
        self.busy.emit(True)

        def job():
            if paddr and code:
                out, err, rc = safe_adb("pair", paddr, code, timeout=30)
                txt = (out + " " + err).strip()
                if "success" not in txt.lower():
                    self.busy.emit(False)
                    self.status.emit("Pair gagal: " + (txt or "tidak ada respon"))
                    return
            if caddr:
                out, err, rc = safe_adb("connect", caddr, timeout=20)
                txt = (out + " " + err).strip().lower()
                if rc or any(w in txt for w in ("failed", "unable", "error", "refused", "cannot")):
                    self.busy.emit(False)
                    self.status.emit("Connect gagal: " + (out or err))
                    return
                self.done.emit(caddr)
            else:
                self.busy.emit(False)
                self.status.emit("Pair OK. Isi IP:port koneksi lalu tekan lagi untuk connect.")

        threading.Thread(target=job, daemon=True).start()

    def do_usb(self):
        self.busy.emit(True)

        def job():
            devs = mirror.find_usb_devices() if mirror.ADB else []
            if not devs:
                self.busy.emit(False)
                self.status.emit("Tidak ada perangkat USB. Colok kabel & aktifkan USB debugging.")
                return
            target = mirror.setup_wireless(devs[0])
            if target:
                self.done.emit(target)
            else:
                self.busy.emit(False)
                self.status.emit("Setup Wi-Fi gagal — lihat log Aktivitas.")

        threading.Thread(target=job, daemon=True).start()


# ══════════════════════════════════════════════════════════════════
#  Jendela aplikasi
# ══════════════════════════════════════════════════════════════════

class LogStream:
    """Arahkan print() engine ke kartu Aktivitas (per baris utuh)."""

    def __init__(self, emit):
        self._emit = emit
        self._buf = ""

    def write(self, s):
        if not s:
            return 0
        self._buf += s
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            self._emit(line)
        if len(self._buf) > 4000:                       # jaga-jaga tanpa newline
            self._emit(self._buf)
            self._buf = ""
        return len(s)

    def flush(self):
        pass

    def isatty(self):
        return False


class Window(Shell):
    sig_log = pyqtSignal(str)
    sig_devices = pyqtSignal(list)
    sig_running = pyqtSignal(bool)
    sig_state = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("LNRCast")
        self.cfg = load_settings()
        self.sess = None
        self.state = "idle"
        self.devices = []
        self.selected = ""
        self._last_count = None
        self._warned_unauth = False

        # ── susun halaman ────────────────────────────────────────
        root = QVBoxLayout(self.page)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.titlebar = TitleBar(self)
        self.hero = Hero()
        root.addWidget(self.titlebar)
        root.addWidget(self.hero)

        body = QHBoxLayout()
        body.setContentsMargins(28, 0, 28, 11)
        body.setSpacing(20)
        root.addLayout(body, 1)

        left = QVBoxLayout()
        left.setSpacing(0)
        self.dev_card = DeviceCard()
        self.q = QualityCard()
        self.audio = AudioRow()
        self.go = PrimaryButton(432, 52)
        self.note = Caption("Pengaturan akan dikunci selama mirroring.")
        self.note.setFixedWidth(432)
        left.addWidget(self.dev_card)
        left.addSpacing(16)
        left.addWidget(self.q)
        left.addSpacing(14)
        left.addWidget(self.audio)
        left.addSpacing(14)
        left.addWidget(self.go)
        left.addSpacing(9)
        left.addWidget(self.note)
        left.addStretch(1)
        body.addLayout(left)

        right = QVBoxLayout()
        right.setSpacing(0)
        self.summary = SummaryCard()
        self.log = LogCard()
        self.deps = DepsRow()
        right.addWidget(self.summary, 1)
        right.addSpacing(16)
        right.addWidget(self.log)
        right.addSpacing(16)
        right.addWidget(self.deps)
        right.addSpacing(12)
        body.addLayout(right, 1)

        self.overlay = PairOverlay(self, self.cfg)

        # ── sinyal ───────────────────────────────────────────────
        self.sig_log.connect(self._on_line)
        self.sig_devices.connect(self._set_devices)
        self.sig_running.connect(self._set_running)
        self.sig_state.connect(self._set_state)
        self.dev_card.refresh.clicked.connect(lambda: self.refresh(True))
        self.dev_card.pair.clicked.connect(self.overlay.open_overlay)
        self.dev_card.select.clicked.connect(self._pick_device)
        self.overlay.connected.connect(self._after_connect)
        self.go.clicked.connect(self.toggle)

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(400)
        self._save_timer.timeout.connect(self._save_now)
        for sig in (self.q.fps.changed, self.q.dec.changed, self.q.codec.changed,
                    self.q.res.changed, self.q.br.valueChanged, self.audio.sw.toggled):
            sig.connect(self._changed)
        self.q.dec.changed.connect(lambda v: self.summary.set_state(gpu=(v == "gpu")))

        self.apply_cfg()
        self.tools = setup_tools()
        self._check_tools()
        self.refresh()
        self.resize(1152 + 2 * self.M, 832 + 2 * self.M)

    # ── konfigurasi ──────────────────────────────────────────────
    def apply_cfg(self):
        c = self.cfg
        self.q.fps.setValue(c["fps"])
        self.q.br.setValue(int(c["bitrate"]))
        self.q.dec.setValue(c["dec"])
        self.q.codec.setValue(c["codec"])
        self.q.res.setValue(c["size"])
        self.audio.sw.setChecked(bool(c["audio"]))
        self.selected = c.get("serial", "")
        self.summary.set_state(gpu=(c["dec"] == "gpu"))

    def collect(self):
        self.cfg.update(
            fps=self.q.fps.value(), bitrate=self.q.br.value(), dec=self.q.dec.value(),
            codec=self.q.codec.value(), size=self.q.res.value(),
            audio=self.audio.sw.isChecked(), serial=self.selected or "",
        )
        return self.cfg

    def _changed(self, *_):
        self._save_timer.start()

    def _save_now(self):
        save_settings(self.collect())

    # ── log ──────────────────────────────────────────────────────
    def _on_line(self, line):
        r = classify(line)
        if r is None:
            return
        tag, msg = r
        self.log.add(tag, msg)
        if "mirroring aktif" in msg.lower():
            self.sig_state.emit("running")

    def note(self, tag, msg):
        self.log.add(tag, msg)

    def _check_tools(self):
        t = self.tools
        self.deps.set_status(t["adb"], t["player"], t["server"])
        missing = [n for n, ok in (("adb", t["adb"]), ("mpv/ffplay", t["player"]),
                                   ("scrcpy-server", t["server"])) if not ok]
        if missing:
            self.hero.set_ready(False, "Perlu: " + ", ".join(missing))
            self.note("ERROR", "Tidak ketemu: " + ", ".join(missing) + " — taruh di folder tools\\")
        else:
            self.hero.set_ready(True, "Semua sistem siap")
            self.note("SISTEM", "ADB, pemutar, dan server siap.")

    # ── perangkat ────────────────────────────────────────────────
    def refresh(self, user=False):
        def job():
            out, _, _ = safe_adb("devices", "-l")
            devs, unauth = [], 0
            for line in out.splitlines()[1:]:
                parts = line.split()
                if len(parts) >= 2 and parts[1] == "device":
                    m = re.search(r"model:(\S+)", line)
                    devs.append((parts[0], (m.group(1) if m else "").replace("_", " ")))
                elif len(parts) >= 2 and parts[1] == "unauthorized":
                    unauth += 1
            if unauth and not self._warned_unauth:
                self._warned_unauth = True
                self.sig_log.emit("[!] Perangkat belum diizinkan — setujui 'Izinkan USB debugging' di HP.")
            self.sig_devices.emit(devs)

        threading.Thread(target=job, daemon=True).start()

    def _set_devices(self, devs):
        self.devices = devs
        serials = [s for s, _ in devs]
        if self.cfg.get("serial") in serials:
            self.selected = self.cfg["serial"]
        elif self.selected not in serials:
            self.selected = serials[0] if serials else ""
        self.dev_card.set_count(len(devs))
        self._show_selected()
        if self._last_count != len(devs):
            if devs:
                self.note("USB", f"{len(devs)} perangkat ditemukan.")
            elif self._last_count is not None:
                self.note("SISTEM", "Tidak ada perangkat terdeteksi.")
            self._last_count = len(devs)

    @staticmethod
    def _kind(serial):
        return "Wi-Fi" if (":" in serial or "_adb-tls" in serial) else "USB"

    def _show_selected(self):
        sel = next(((s, m) for s, m in self.devices if s == self.selected), None)
        if sel is None:
            self.dev_card.select.set_empty()
            self.summary.set_state(conn=None, dev_name="")
            return
        serial, model = sel
        kind = self._kind(serial)
        self.dev_card.select.set_device(model or "Android", f"{kind}  ·  {serial}")
        self.summary.set_state(conn=kind, dev_name=model)

    def _pick_device(self):
        if not self.devices:
            self.refresh(True)
            return
        m = QMenu(self)
        m.setWindowFlags(m.windowFlags() | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.NoDropShadowWindowHint)
        m.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        m.setMinimumWidth(self.dev_card.select.width())
        for serial, model in self.devices:
            act = m.addAction(f"{model or 'Android'}  ·  {self._kind(serial)}  ·  {serial}")
            act.setCheckable(True)
            act.setChecked(serial == self.selected)
            act.setData(serial)
        chosen = m.exec(self.dev_card.select.mapToGlobal(QPoint(0, self.dev_card.select.height() + 4)))
        if chosen is not None and chosen.data():
            self.selected = chosen.data()
            self.cfg["serial"] = self.selected
            self._show_selected()
            self._changed()

    def _after_connect(self, serial):
        self.cfg["serial"] = serial
        self.selected = serial
        save_settings(self.cfg)
        self.note("WI-FI", f"Tersambung: {serial}")
        self.refresh()

    # ── start / stop ─────────────────────────────────────────────
    def toggle(self):
        if self.state != "idle":
            if self.sess:
                threading.Thread(target=self.sess.stop, daemon=True).start()
            return
        cfg = self.collect()
        if not cfg["serial"]:
            self.note("ERROR", "Pilih perangkat dulu (colok USB atau Pair).")
            return
        save_settings(cfg)
        self.sess = MirrorSession(
            cfg["serial"], fps=cfg["fps"], bitrate_mbps=cfg["bitrate"],
            max_size=cfg["size"], codec=cfg["codec"],
            audio=cfg["audio"], hwdec="auto-safe" if cfg["dec"] == "gpu" else "no",
        )
        self.sig_state.emit("starting")
        self.note("SISTEM", f"Memulai: {cfg['fps']} fps · {cfg['bitrate']} Mbps · {cfg['codec'].upper()}")

        def job():
            try:
                self.sess.run()
            except SystemExit as e:
                print(f"[!] {e}")
            except Exception as e:
                print(f"[!] Error: {e}")
            finally:
                self.sig_state.emit("idle")

        threading.Thread(target=job, daemon=True).start()

    def _set_state(self, state):
        # "running" yang datang telat setelah sesi selesai diabaikan
        if state == "running" and self.state == "idle":
            return
        self.state = state
        busy = state != "idle"
        self.go.set_running(busy)
        self.go.setEnabled(True)
        for w in (self.q, self.audio, self.dev_card):
            w.setEnabled(not busy)
        self.summary.set_state(state=state)
        if state == "idle":
            self.sess = None
            self.note("SISTEM", "Sesi selesai.")

    def _set_running(self, running):
        self._set_state("starting" if running else "idle")

    def closeEvent(self, e):
        self._save_timer.stop()
        save_settings(self.collect())
        if self.sess:
            self.sess.stop()
        e.accept()


# ══════════════════════════════════════════════════════════════════
#  Main
# ══════════════════════════════════════════════════════════════════

QSS = f"""
QMenu {{
    background: #f6f8ff; border: 1px solid #ffffff; border-radius: 12px; padding: 6px;
}}
QMenu::item {{
    padding: 8px 14px; border-radius: 8px; color: {INK}; font-size: 12px;
}}
QMenu::item:selected {{ background: rgba(39,100,234,0.12); color: {ACCENT}; }}
QToolTip {{
    background: #f6f8ff; color: {INK}; border: 1px solid #c9d4f2; padding: 4px 8px;
}}
"""


def main():
    argv = sys.argv[1:]
    snap = None
    if "--snapshot" in argv:
        i = argv.index("--snapshot")
        snap = argv[i + 1] if i + 1 < len(argv) else "snapshot.png"
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    K.load_fonts(APP_DIR)
    app.setFont(font(13))
    app.setStyleSheet(QSS)
    for name in ("icon.ico", "icon.png"):
        ic = APP_DIR / "assets" / name
        if ic.is_file():
            app.setWindowIcon(QIcon(str(ic)))
            break

    w = Window()
    if snap is None:
        sys.stdout = sys.stderr = LogStream(w.sig_log.emit)
    scr = app.primaryScreen()
    if scr is not None:
        g = scr.availableGeometry()
        w.move(g.center() - QPoint(w.width() // 2, w.height() // 2))
    w.show()

    if snap is not None:
        def shot():
            if "--pair" in argv:
                w.overlay.open_overlay()
                app.processEvents()
            w.grab().save(snap)
            app.quit()
        QTimer.singleShot(700, shot)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()