from __future__ import annotations

import math

from PyQt6.QtCore import (
    Qt, QRectF, QPointF, QPoint, QRegularExpression, pyqtSignal,
    QVariantAnimation, QEasingCurve, QEvent,
)
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QFont, QFontDatabase, QFontMetrics,
    QLinearGradient, QRadialGradient, QPainterPath, QPixmap, QPolygonF,
    QRegularExpressionValidator, QPalette,
)
from PyQt6.QtWidgets import QWidget, QMenu, QLineEdit

# ══════════════════════════════════════════════════════════════════
#  Token desain (dari Figma)
# ══════════════════════════════════════════════════════════════════

INK = "#1c2747"
MUTED = "#66718d"
SOFT = "#7b859d"
ACCENT = "#2764ea"
ACCENT_HI = "#3b74f0"
ACCENT_LO = "#1f55cf"
GOOD = "#219a75"
GOOD_TXT = "#377360"
WARN = "#d99a1d"
WARN_TXT = "#8a6410"
BAD = "#d4435a"
STOP = "#e5484d"
STOP_HI = "#ee5a5f"
STOP_LO = "#c93a3f"

A = Qt.AlignmentFlag
NOPEN = Qt.PenStyle.NoPen
NOBRUSH = Qt.BrushStyle.NoBrush


def C(color, alpha=None) -> QColor:
    """'#rrggbb' / QColor -> QColor, opsional dengan alpha 0..1."""
    c = QColor(color)
    if alpha is not None:
        c.setAlphaF(max(0.0, min(1.0, alpha)))
    return c


def flags(*fs) -> int:
    v = 0
    for f in fs:
        v |= f.value
    return v


LEFT_VC = flags(A.AlignLeft, A.AlignVCenter)
RIGHT_VC = flags(A.AlignRight, A.AlignVCenter)
CENTER = flags(A.AlignHCenter, A.AlignVCenter)
TOP_LEFT_WRAP = flags(A.AlignLeft, A.AlignTop, Qt.TextFlag.TextWordWrap)


# ══════════════════════════════════════════════════════════════════
#  Font (Inter dibundel di assets/fonts)
# ══════════════════════════════════════════════════════════════════

_FAM = {"regular": "Inter", "medium": "Inter", "semibold": "Inter"}
_WEIGHT = {
    "regular": QFont.Weight.Normal,
    "medium": QFont.Weight.Medium,
    "semibold": QFont.Weight.DemiBold,
}


def load_fonts(app_dir) -> bool:
    """Muat Inter dari <app>/assets/fonts. Kalau gagal pakai Segoe UI."""
    global _FAM
    files = {
        "regular": "Inter-Regular.otf",
        "medium": "Inter-Medium.otf",
        "semibold": "Inter-SemiBold.otf",
    }
    found = {}
    for d in (app_dir / "assets" / "fonts", app_dir / "fonts"):
        if not d.is_dir():
            continue
        for key, fn in files.items():
            f = d / fn
            if key in found or not f.is_file():
                continue
            fid = QFontDatabase.addApplicationFont(str(f))
            if fid >= 0:
                fams = QFontDatabase.applicationFontFamilies(fid)
                if fams:
                    found[key] = fams[0]
    if len(found) == 3:
        _FAM = found
        return True
    _FAM = {"regular": "Segoe UI", "medium": "Segoe UI", "semibold": "Segoe UI"}
    return False


def font(px: float, weight: str = "regular", spacing: float = 0.0) -> QFont:
    fam = _FAM[weight]
    f = QFont(fam)
    f.setPixelSize(int(round(px)))
    # Kalau tiap bobot terdaftar sebagai family sendiri ("Inter Medium"),
    # jangan minta bobot lagi (nanti disintesis jadi tebal palsu).
    same_family = (_FAM["regular"] == _FAM["medium"] == _FAM["semibold"])
    f.setWeight(_WEIGHT[weight] if same_family else QFont.Weight.Normal)
    if same_family and fam == "Segoe UI" and weight == "semibold":
        f.setFamily("Segoe UI Semibold")
        f.setWeight(QFont.Weight.Normal)
    if spacing:
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
    return f


def text(p: QPainter, x, y, w, h, s, fnt: QFont, color, align=LEFT_VC):
    p.setFont(fnt)
    p.setPen(QPen(C(color)))
    p.drawText(QRectF(x, y, w, h), align, s)


def text_width(s: str, fnt: QFont) -> float:
    return float(QFontMetrics(fnt).horizontalAdvance(s))


def elide(s: str, fnt: QFont, w: float) -> str:
    return QFontMetrics(fnt).elidedText(s, Qt.TextElideMode.ElideRight, int(w))


# ══════════════════════════════════════════════════════════════════
#  Gambar dasar: gradien Figma, bayangan lembut, wallpaper
# ══════════════════════════════════════════════════════════════════

def figma_linear(rect: QRectF, a: float, b: float, c: float, stops) -> QLinearGradient:
    """Gradien linear Figma: t = a*u + b*v + c  (u,v = 0..1 di dalam node)."""
    gx, gy = a / rect.width(), b / rect.height()
    n2 = gx * gx + gy * gy
    p0 = QPointF(-c * gx / n2, -c * gy / n2) + rect.topLeft()
    p1 = QPointF((1 - c) * gx / n2, (1 - c) * gy / n2) + rect.topLeft()
    g = QLinearGradient(p0, p1)
    for pos, col in stops:
        g.setColorAt(pos, C(col))
    return g


def soft_shadow(p: QPainter, rect: QRectF, radius: float, blur: float = 24.0,
                dy: float = 8.0, color=None):
    """Bayangan jatuh lembut (aproksimasi blur) - bagian dalam kartu dikosongkan."""
    color = color or QColor(46, 64, 128, 44)
    rect = QRectF(rect)
    p.save()
    hole = QPainterPath()
    hole.addRoundedRect(rect, radius, radius)
    big = QPainterPath()
    big.addRect(rect.adjusted(-blur * 2, -blur * 2, blur * 2, blur * 2 + abs(dy)))
    p.setClipPath(big.subtracted(hole), Qt.ClipOperation.IntersectClip)
    n = 9
    each = color.alphaF() / n * 1.15
    p.setPen(NOPEN)
    for i in range(n):
        t = i / (n - 1)                 # 0 = terluar ... 1 = terdalam
        g = blur * 0.55 * (1 - t)
        c = QColor(color)
        c.setAlphaF(min(1.0, each))
        p.setBrush(QBrush(c))
        r = rect.adjusted(-g, -g + dy, g, g + dy)
        p.drawRoundedRect(r, radius + g, radius + g)
    p.restore()


def _blob(p: QPainter, x, y, w, h, color, alpha):
    """Elips 'cahaya' dengan tepi buram (aproksimasi foreground blur 90)."""
    cx, cy = x + w / 2, y + h / 2
    rx, ry = w / 2, h / 2
    p.save()
    p.translate(cx, cy)
    p.scale(rx / ry, 1.0)
    big_r = ry * 1.19
    g = QRadialGradient(QPointF(0, 0), big_r)
    for pos, k in ((0.0, 1.0), (0.66, 0.97), (0.76, 0.82), (0.84, 0.50),
                   (0.92, 0.18), (1.0, 0.0)):
        g.setColorAt(pos, C(color, alpha * k))
    p.setPen(NOPEN)
    p.setBrush(QBrush(g))
    p.drawEllipse(QPointF(0, 0), big_r, big_r)
    p.restore()


WALL_W, WALL_H = 1280, 960
WIN_W, WIN_H = 1152, 832           # ukuran jendela di desain
WIN_OX, WIN_OY = 64, 27            # posisi jendela di dalam wallpaper desain

_wall_cache = None


def wallpaper() -> QPixmap:
    """Wallpaper pastel 1280x960 (gradien + 3 cahaya) persis seperti frame 'Wallpaper'."""
    global _wall_cache
    if _wall_cache is not None:
        return _wall_cache
    pm = QPixmap(WALL_W, WALL_H)
    pm.fill(C("#c7d1f5"))
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    g = figma_linear(QRectF(0, 0, WALL_W, WALL_H), 0.8, 0.6, -0.1,
                     [(0.0, "#9daef3"), (0.48, "#d8ddf9"), (1.0, "#9ac9eb")])
    p.fillRect(pm.rect(), QBrush(g))
    _blob(p, -220, 270, 1030, 950, "#7967e4", 0.50)    # Cahaya lavender
    _blob(p, 610, -390, 1020, 1050, "#68aff2", 0.70)   # Cahaya biru
    _blob(p, 540, 590, 890, 600, "#f4ccea", 0.70)      # Cahaya peach
    p.end()
    _wall_cache = pm
    return pm


def draw_wallpaper(p: QPainter, target: QRectF):
    """Gambar wallpaper memenuhi 'target', dipotong di sekitar posisi jendela desain."""
    pm = wallpaper()
    s = max(target.width() / WIN_W, target.height() / WIN_H)
    sw, sh = target.width() / s, target.height() / s
    cx, cy = WIN_OX + WIN_W / 2, WIN_OY + WIN_H / 2
    src = QRectF(cx - sw / 2, cy - sh / 2, sw, sh)
    p.drawPixmap(target, pm, src)


# ══════════════════════════════════════════════════════════════════
#  Ikon vektor (grid 24)
# ══════════════════════════════════════════════════════════════════

def _arrowhead(p: QPainter, theta_deg: float, cx: float, cy: float, r: float):
    th = math.radians(theta_deg)
    ex, ey = cx + r * math.cos(th), cy - r * math.sin(th)
    tx, ty = -math.sin(th), -math.cos(th)         # arah putar berlawanan jarum jam
    nx, ny = ty, -tx
    k1, k2 = 4.4, 3.3
    p.drawLine(QPointF(ex, ey), QPointF(ex - tx * k1 + nx * k2, ey - ty * k1 + ny * k2))
    p.drawLine(QPointF(ex, ey), QPointF(ex - tx * k1 - nx * k2, ey - ty * k1 - ny * k2))


def icon(p: QPainter, name: str, rect: QRectF, color, sw: float = 2.2):
    rect = QRectF(rect)
    p.save()
    p.translate(rect.x(), rect.y())
    s = rect.width() / 24.0
    p.scale(s, s)
    col = C(color)
    p.setPen(QPen(col, sw, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                  Qt.PenJoinStyle.RoundJoin))
    p.setBrush(NOBRUSH)

    if name == "phone":
        p.drawRoundedRect(QRectF(5.5, 2, 13, 20), 3, 3)
        p.drawLine(QPointF(10.2, 18), QPointF(13.8, 18))
    elif name == "chevron":
        p.drawPolyline(QPolygonF([QPointF(6, 9), QPointF(12, 15), QPointF(18, 9)]))
    elif name == "close":
        p.drawLine(QPointF(5.5, 5.5), QPointF(18.5, 18.5))
        p.drawLine(QPointF(18.5, 5.5), QPointF(5.5, 18.5))
    elif name == "arrow":
        p.drawLine(QPointF(4, 12), QPointF(20, 12))
        p.drawPolyline(QPolygonF([QPointF(14, 6), QPointF(20, 12), QPointF(14, 18)]))
    elif name == "play":
        p.setBrush(QBrush(col))
        p.drawPolygon(QPolygonF([QPointF(8, 4.5), QPointF(18, 12), QPointF(8, 19.5)]))
    elif name == "stop":
        p.setBrush(QBrush(col))
        p.drawRoundedRect(QRectF(6.5, 6.5, 11, 11), 2.5, 2.5)
    elif name == "wifi":
        p.setBrush(QBrush(col))
        p.drawEllipse(QPointF(12, 19), 1.3, 1.3)
        p.setBrush(NOBRUSH)
        for r in (6.0, 11.0, 16.0):
            p.drawArc(QRectF(12 - r, 19 - r, 2 * r, 2 * r), 45 * 16, 90 * 16)
    elif name == "speaker":
        p.drawPolygon(QPolygonF([QPointF(3, 9.5), QPointF(7, 9.5), QPointF(12, 5),
                                 QPointF(12, 19), QPointF(7, 14.5), QPointF(3, 14.5)]))
        p.drawArc(QRectF(12 - 5.5, 12 - 5.5, 11, 11), -45 * 16, 90 * 16)
        p.drawArc(QRectF(12 - 9.5, 12 - 9.5, 19, 19), -45 * 16, 90 * 16)
    elif name == "refresh":
        r = 8.0
        box = QRectF(12 - r, 12 - r, 2 * r, 2 * r)
        p.drawArc(box, 25 * 16, 130 * 16)
        p.drawArc(box, 205 * 16, 130 * 16)
        _arrowhead(p, 155, 12, 12, r)
        _arrowhead(p, 335, 12, 12, r)
    elif name == "usb":
        p.drawLine(QPointF(12, 4), QPointF(12, 19))
        p.setBrush(QBrush(col))
        p.drawEllipse(QPointF(12, 20), 1.8, 1.8)
        p.drawPolygon(QPolygonF([QPointF(12, 2.2), QPointF(9.8, 5.6), QPointF(14.2, 5.6)]))
        p.setBrush(NOBRUSH)
        p.drawPolyline(QPolygonF([QPointF(12, 14), QPointF(7, 11.5), QPointF(7, 9.5)]))
        p.drawPolyline(QPolygonF([QPointF(12, 11), QPointF(17, 8.5), QPointF(17, 7.5)]))
        p.setBrush(QBrush(col))
        p.drawEllipse(QPointF(7, 8.6), 1.6, 1.6)
        p.drawRect(QRectF(15.6, 5.4, 2.8, 2.8))
    p.restore()


# ══════════════════════════════════════════════════════════════════
#  Widget dasar
# ══════════════════════════════════════════════════════════════════

class Panel(QWidget):
    """Kartu kaca: isi putih transparan + garis putih 1px + (opsional) bayangan."""

    def __init__(self, fill=0.48, radius=20.0, shadow=True, stroke=True, parent=None):
        super().__init__(parent)
        self.fill, self.radius, self.has_shadow, self.has_stroke = fill, radius, shadow, stroke

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect())
        p.setPen(NOPEN)
        p.setBrush(QBrush(C("#ffffff", self.fill)))
        p.drawRoundedRect(r, self.radius, self.radius)
        if self.has_stroke:
            g = QLinearGradient(r.topLeft(), r.bottomRight())
            g.setColorAt(0.0, C("#ffffff", 0.95))
            g.setColorAt(1.0, C("#ffffff", 0.45))
            p.setBrush(NOBRUSH)
            p.setPen(QPen(QBrush(g), 1.0))
            p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), self.radius - 0.5, self.radius - 0.5)
        self.paint_content(p)

    def paint_content(self, p: QPainter):
        pass


class Clickable(QWidget):
    """Basis tombol kustom: hover / pressed / clicked."""
    clicked = pyqtSignal()

    def __init__(self, w, h, parent=None):
        super().__init__(parent)
        self.setFixedSize(int(w), int(h))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._hover = False
        self._down = False

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self._down = False
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self.isEnabled():
            self._down = True
            self.update()

    def mouseReleaseEvent(self, e):
        was = self._down
        self._down = False
        self.update()
        if was and e.button() == Qt.MouseButton.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit()

    def changeEvent(self, e):
        # hanya EnabledChange (setCursor sendiri memicu CursorChange -> rekursi tak berujung)
        if e.type() == QEvent.Type.EnabledChange:
            self.setCursor(Qt.CursorShape.PointingHandCursor if self.isEnabled()
                           else Qt.CursorShape.ArrowCursor)
            self.update()
        super().changeEvent(e)

    def _alpha(self):
        return 1.0 if self.isEnabled() else 0.5


class GlassButton(Clickable):
    """Tombol kaca kecil (Segarkan / Pair / Tutup dialog)."""

    def __init__(self, w, h, icon_name, label=None, radius=13.0, fill=0.56,
                 color=MUTED, icon_px=20, base="#ffffff", circle=False, parent=None):
        super().__init__(w, h, parent)
        self.icon_name, self.label, self.radius, self.fill = icon_name, label, radius, fill
        self.color, self.icon_px, self.base, self.circle = color, icon_px, base, circle

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setOpacity(self._alpha())
        a = self.fill + (0.14 if self._hover else 0) - (0.10 if self._down else 0)
        r = QRectF(self.rect())
        rad = min(r.width(), r.height()) / 2 if self.circle else self.radius
        p.setPen(NOPEN)
        p.setBrush(QBrush(C(self.base, a)))
        p.drawRoundedRect(r, rad, rad)
        s = self.icon_px
        if self.label:
            icon(p, self.icon_name, QRectF((r.width() - s) / 2, 9, s, s), self.color)
            text(p, 0, 31, r.width(), 16, self.label, font(11, "medium"), self.color, CENTER)
        else:
            icon(p, self.icon_name, QRectF((r.width() - s) / 2, (r.height() - s) / 2, s, s), self.color)


class DeviceSelect(Clickable):
    """Kotak pilihan perangkat (284x58)."""

    def __init__(self, parent=None):
        super().__init__(284, 58, parent)
        self.name, self.sub, self.empty = "", "", True

    def set_device(self, name, sub):
        self.name, self.sub, self.empty = name, sub, False
        self.update()

    def set_empty(self, name="Tidak ada perangkat", sub="Colok USB atau tekan Pair"):
        self.name, self.sub, self.empty = name, sub, True
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setOpacity(self._alpha())
        a = 0.66 + (0.12 if self._hover else 0) - (0.08 if self._down else 0)
        p.setPen(NOPEN)
        p.setBrush(QBrush(C("#ffffff", a)))
        p.drawRoundedRect(QRectF(self.rect()), 13, 13)
        icol = MUTED if self.empty else ACCENT
        icon(p, "phone", QRectF(13, 17, 23, 23), icol)
        text(p, 48, 10, 190, 17, elide(self.name, font(14, "semibold"), 190), font(14, "semibold"), INK)
        text(p, 48, 32, 190, 13, elide(self.sub, font(11), 190), font(11), MUTED)
        icon(p, "chevron", QRectF(252, 19, 18, 18), MUTED)


class PrimaryButton(Clickable):
    """Tombol besar 'Mulai mirroring' (biru) / 'Hentikan' (merah)."""

    def __init__(self, w=432, h=52, parent=None):
        super().__init__(w, h, parent)
        self.running = False
        self.label_idle = "Mulai mirroring"
        self.label_run = "Hentikan mirroring"

    def set_running(self, running: bool):
        self.running = running
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.isEnabled():
            base = "#a9b6d8"
        elif self.running:
            base = STOP_LO if self._down else (STOP_HI if self._hover else STOP)
        else:
            base = ACCENT_LO if self._down else (ACCENT_HI if self._hover else ACCENT)
        p.setPen(NOPEN)
        p.setBrush(QBrush(C(base)))
        p.drawRoundedRect(QRectF(self.rect()), 16, 16)
        label = self.label_run if self.running else self.label_idle
        fnt = font(15, "semibold")
        tw = text_width(label, fnt)
        total = 20 + 10 + tw
        x0 = (self.width() - total) / 2
        icon(p, "stop" if self.running else "play", QRectF(x0, (self.height() - 20) / 2, 20, 20), "#ffffff")
        text(p, x0 + 30, 0, tw + 4, self.height(), label, fnt, "#ffffff")


class Seg(QWidget):
    """Kontrol segmen (30/60/120 fps, GPU/CPU) dengan pil putih yang bergeser."""
    changed = pyqtSignal(object)

    def __init__(self, items, w, h=38, pad=4, parent=None):
        super().__init__(parent)
        self.items = list(items)
        self.setFixedSize(int(w), int(h))
        self.pad = pad
        self._idx = 0
        self._pos = 0.0
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(170)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._on_anim)

    def _on_anim(self, v):
        self._pos = float(v)
        self.update()

    def value(self):
        return self.items[self._idx][1]

    def setValue(self, value, animate=False):
        for i, (_, v) in enumerate(self.items):
            if v == value:
                self._set_index(i, animate)
                return
        self._set_index(0, animate)

    def _set_index(self, i, animate):
        self._idx = i
        if animate:
            self._anim.stop()
            self._anim.setStartValue(self._pos)
            self._anim.setEndValue(float(i))
            self._anim.start()
        else:
            self._pos = float(i)
            self.update()

    def _seg_w(self):
        return (self.width() - 2 * self.pad) / len(self.items)

    def mousePressEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton or not self.isEnabled():
            return
        i = int((e.position().x() - self.pad) // self._seg_w())
        i = max(0, min(len(self.items) - 1, i))
        if i != self._idx:
            self._set_index(i, True)
            self.changed.emit(self.value())

    def keyPressEvent(self, e):
        k = e.key()
        if k in (Qt.Key.Key_Left, Qt.Key.Key_Right) and self.isEnabled():
            i = max(0, min(len(self.items) - 1, self._idx + (1 if k == Qt.Key.Key_Right else -1)))
            if i != self._idx:
                self._set_index(i, True)
                self.changed.emit(self.value())
        else:
            super().keyPressEvent(e)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setOpacity(1.0 if self.isEnabled() else 0.55)
        r = QRectF(self.rect())
        p.setPen(NOPEN)
        p.setBrush(QBrush(C("#b7c3df", 0.25)))
        p.drawRoundedRect(r, 11, 11)
        sw = self._seg_w()
        pill = QRectF(self.pad + self._pos * sw, self.pad, sw, r.height() - 2 * self.pad)
        soft_shadow(p, pill, 8, blur=6, dy=2, color=QColor(51, 77, 128, 30))
        p.setPen(NOPEN)
        p.setBrush(QBrush(C("#ffffff", 0.96)))
        p.drawRoundedRect(pill, 8, 8)
        for i, (label, _) in enumerate(self.items):
            sel = abs(i - self._pos) < 0.5
            text(p, self.pad + i * sw, 0, sw, r.height(), label,
                 font(12, "semibold" if sel else "medium"), ACCENT if sel else MUTED, CENTER)


class Switch(QWidget):
    toggled = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(44, 26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._on = True
        self._t = 1.0
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(150)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._tick)

    def _tick(self, v):
        self._t = float(v)
        self.update()

    def isChecked(self):
        return self._on

    def setChecked(self, on, animate=False):
        self._on = bool(on)
        if animate:
            self._anim.stop()
            self._anim.setStartValue(self._t)
            self._anim.setEndValue(1.0 if self._on else 0.0)
            self._anim.start()
        else:
            self._t = 1.0 if self._on else 0.0
            self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self.isEnabled() \
                and self.rect().contains(e.position().toPoint()):
            self.setChecked(not self._on, True)
            self.toggled.emit(self._on)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setOpacity(1.0 if self.isEnabled() else 0.55)
        t = self._t
        off, on = C("#b8c5e0", 0.75), C(ACCENT)
        col = QColor(int(off.red() + (on.red() - off.red()) * t),
                     int(off.green() + (on.green() - off.green()) * t),
                     int(off.blue() + (on.blue() - off.blue()) * t),
                     int(off.alpha() + (on.alpha() - off.alpha()) * t))
        p.setPen(NOPEN)
        p.setBrush(QBrush(col))
        p.drawRoundedRect(QRectF(self.rect()), 13, 13)
        x = 3 + 18 * t
        thumb = QRectF(x, 3, 20, 20)
        soft_shadow(p, thumb, 10, blur=4, dy=1, color=QColor(30, 50, 100, 40))
        p.setBrush(QBrush(C("#ffffff")))
        p.drawEllipse(thumb)


class BitrateControl(QWidget):
    """Label 'Bitrate' + nilai + track/thumb + skala 1..100 Mbps (392x66)."""
    valueChanged = pyqtSignal(int)
    LO, HI = 1, 100

    def __init__(self, w=392, parent=None):
        super().__init__(parent)
        self.setFixedSize(int(w), 66)
        self._v = 20
        self._drag = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def value(self):
        return self._v

    def setValue(self, v, emit=False):
        v = max(self.LO, min(self.HI, int(v)))
        if v != self._v:
            self._v = v
            self.update()
            if emit:
                self.valueChanged.emit(v)

    def _from_x(self, x):
        self.setValue(round(x / self.width() * 100), emit=True)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self.isEnabled() and e.position().y() > 18:
            self._drag = True
            self._from_x(e.position().x())

    def mouseMoveEvent(self, e):
        if self._drag:
            self._from_x(e.position().x())

    def mouseReleaseEvent(self, e):
        self._drag = False

    def wheelEvent(self, e):
        if self.isEnabled():
            step = 1 if e.angleDelta().y() > 0 else -1
            self.setValue(self._v + step, emit=True)
            e.accept()

    def keyPressEvent(self, e):
        k = e.key()
        if k in (Qt.Key.Key_Left, Qt.Key.Key_Down):
            self.setValue(self._v - 1, emit=True)
        elif k in (Qt.Key.Key_Right, Qt.Key.Key_Up):
            self.setValue(self._v + 1, emit=True)
        else:
            super().keyPressEvent(e)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setOpacity(1.0 if self.isEnabled() else 0.55)
        w = self.width()
        text(p, 0, 2, 120, 15, "Bitrate", font(12, "medium"), MUTED)
        text(p, w - 140, 0, 140, 17, f"{self._v} Mbps", font(14, "semibold"), ACCENT, RIGHT_VC)
        ty = 35.0
        p.setPen(NOPEN)
        p.setBrush(QBrush(C("#b8c5e0", 0.60)))
        p.drawRoundedRect(QRectF(0, ty, w, 5), 3, 3)
        cx = max(9.5, min(w - 9.5, w * self._v / 100.0))
        p.setBrush(QBrush(C(ACCENT)))
        p.drawRoundedRect(QRectF(0, ty, cx, 5), 3, 3)
        thumb = QRectF(cx - 9.5, ty + 2.5 - 9.5, 19, 19)
        soft_shadow(p, thumb, 9.5, blur=5, dy=2, color=QColor(26, 51, 102, 50))
        p.setBrush(QBrush(C("#ffffff")))
        p.drawEllipse(thumb)
        text(p, 0, 51, 80, 12, "1 Mbps", font(10), MUTED)
        text(p, w - 80, 51, 80, 12, "100 Mbps", font(10), MUTED, RIGHT_VC)


class SelectBox(Clickable):
    """Dropdown kaca (Codec / Resolusi maks.)."""
    changed = pyqtSignal(object)

    def __init__(self, items, w=189, h=40, parent=None):
        super().__init__(w, h, parent)
        self.items = list(items)
        self._idx = 0
        self.clicked.connect(self._open)

    def value(self):
        return self.items[self._idx][1]

    def setValue(self, value):
        for i, (_, v) in enumerate(self.items):
            if v == value:
                self._idx = i
                break
        else:
            self._idx = 0
        self.update()

    def _open(self):
        m = QMenu(self)
        m.setWindowFlags(m.windowFlags() | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.NoDropShadowWindowHint)
        m.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        m.setMinimumWidth(self.width())
        for i, (label, _) in enumerate(self.items):
            act = m.addAction(label)
            act.setCheckable(True)
            act.setChecked(i == self._idx)
            act.setData(i)
        chosen = m.exec(self.mapToGlobal(QPoint(0, self.height() + 4)))
        if chosen is not None:
            i = chosen.data()
            if i is not None and i != self._idx:
                self._idx = int(i)
                self.update()
                self.changed.emit(self.value())

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setOpacity(self._alpha())
        a = 0.65 + (0.12 if self._hover else 0) - (0.06 if self._down else 0)
        p.setPen(NOPEN)
        p.setBrush(QBrush(C("#ffffff", a)))
        p.drawRoundedRect(QRectF(self.rect()), 10, 10)
        text(p, 12, 0, self.width() - 40, self.height(), self.items[self._idx][0],
             font(12, "medium"), INK)
        icon(p, "chevron", QRectF(self.width() - 29, (self.height() - 17) / 2, 17, 17), MUTED)


class FieldBox(QWidget):
    """Input teks kaca (464x43) untuk dialog pairing."""

    def __init__(self, placeholder, tag=None, w=464, h=43, parent=None):
        super().__init__(parent)
        self.setFixedSize(int(w), int(h))
        self.tag = tag
        self.edit = QLineEdit(self)
        self.edit.setPlaceholderText(placeholder)
        self.edit.setFont(font(13))
        self.edit.setFrame(False)
        self.edit.setStyleSheet(f"QLineEdit {{ background: transparent; border: none; color: {INK};"
                                f" selection-background-color: {ACCENT}; selection-color: white; }}")
        pal = self.edit.palette()
        pal.setColor(QPalette.ColorRole.PlaceholderText, C("#8490a8"))
        self.edit.setPalette(pal)
        right = 14 + (60 if tag else 0)
        self.edit.setGeometry(14, 0, int(w) - 14 - right, int(h))
        self.edit.textChanged.connect(lambda _t: self.update())
        self.edit.installEventFilter(self)

    def eventFilter(self, obj, ev):
        if obj is self.edit and ev.type() in (QEvent.Type.FocusIn, QEvent.Type.FocusOut):
            self.update()
        return False

    def text(self):
        return self.edit.text().strip()

    def setText(self, s):
        self.edit.setText(s)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect())
        focus = self.edit.hasFocus()
        p.setPen(NOPEN)
        p.setBrush(QBrush(C("#ffffff", 0.92 if focus else 0.80)))
        p.drawRoundedRect(r, 11, 11)
        if focus:
            p.setBrush(NOBRUSH)
            p.setPen(QPen(C(ACCENT, 0.85), 1.5))
            p.drawRoundedRect(r.adjusted(0.75, 0.75, -0.75, -0.75), 10.5, 10.5)
        if self.tag:
            text(p, r.width() - 14 - 56, 0, 56, r.height(), self.tag, font(9, "semibold", 0.4),
                 "#8793ab", RIGHT_VC)


def digits_validator(parent, max_len=6):
    return QRegularExpressionValidator(QRegularExpression(rf"^\d{{0,{max_len}}}$"), parent)
