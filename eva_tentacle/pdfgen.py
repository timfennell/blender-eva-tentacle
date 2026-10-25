"""Tiny vector PDF writer. Drawing units are millimetres, origin bottom-left.
Only what the pattern sheets need: lines, polygons, circles, Helvetica text."""

import math
import zlib

PT_PER_MM = 72.0 / 25.4

# Helvetica advance widths (1/1000 em) for printable ASCII 32..126
_HELV = [278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278,
         556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 278, 278, 584, 584, 584, 556,
         1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722, 778,
         667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556,
         333, 556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556,
         556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500, 334, 260, 334, 584]


def text_width(s, size, bold=False):
    w = 0
    for ch in s:
        o = ord(ch)
        w += _HELV[o - 32] if 32 <= o <= 126 else 556
    return w / 1000.0 * size * (1.06 if bold else 1.0)


def _esc(s):
    b = s.encode('cp1252', 'replace')
    b = b.replace(b'\\', b'\\\\').replace(b'(', b'\\(').replace(b')', b'\\)')
    return b.decode('latin-1')


def _n(v):
    return ('%.3f' % v).rstrip('0').rstrip('.') or '0'


class Page:
    def __init__(self, w, h):
        self.w, self.h = w, h
        self.ops = []

    def raw(self, s):
        self.ops.append(s)

    # state
    def push(self):
        self.raw('q')

    def pop(self):
        self.raw('Q')

    def stroke(self, rgb=(0, 0, 0), width=None, dash=None, round_cap=False):
        """round_cap with a dash of (0, gap) draws a line of round dots."""
        self.raw('%s %s %s RG' % tuple(_n(c) for c in rgb))
        if width is not None:
            self.raw('%s w' % _n(width))
        self.raw('[%s] 0 d %d J' % (' '.join(_n(d) for d in dash) if dash else '', 1 if round_cap else 0))

    def fill(self, rgb):
        self.raw('%s %s %s rg' % tuple(_n(c) for c in rgb))

    def translate(self, x, y):
        self.raw('1 0 0 1 %s %s cm' % (_n(x), _n(y)))

    def clip_rect(self, x, y, w, h):
        self.raw('%s %s %s %s re W n' % (_n(x), _n(y), _n(w), _n(h)))

    # shapes
    def polyline(self, pts, close=False, fill=False, stroke=True):
        pts = list(pts)
        if len(pts) < 2:
            return
        s = ['%s %s m' % (_n(pts[0][0]), _n(pts[0][1]))]
        s += ['%s %s l' % (_n(p[0]), _n(p[1])) for p in pts[1:]]
        if close:
            s.append('h')
        s.append({(True, True): 'B', (True, False): 'f', (False, True): 'S'}.get((fill, stroke), 'n'))
        self.raw(' '.join(s))

    def line(self, x1, y1, x2, y2):
        self.polyline([(x1, y1), (x2, y2)])

    def rect(self, x, y, w, h, fill=False, stroke=True):
        op = {(True, True): 'B', (True, False): 'f', (False, True): 'S'}[(fill, stroke)]
        self.raw('%s %s %s %s re %s' % (_n(x), _n(y), _n(w), _n(h), op))

    def circle(self, cx, cy, r, fill=False, stroke=True):
        k = 0.5523 * r
        s = '%s %s m ' % (_n(cx + r), _n(cy))
        for (x1, y1, x2, y2, x3, y3) in [(cx + r, cy + k, cx + k, cy + r, cx, cy + r),
                                         (cx - k, cy + r, cx - r, cy + k, cx - r, cy),
                                         (cx - r, cy - k, cx - k, cy - r, cx, cy - r),
                                         (cx + k, cy - r, cx + r, cy - k, cx + r, cy)]:
            s += '%s %s %s %s %s %s c ' % tuple(_n(v) for v in (x1, y1, x2, y2, x3, y3))
        s += {(True, True): 'B', (True, False): 'f', (False, True): 'S'}[(fill, stroke)]
        self.raw(s)

    def arrow(self, x1, y1, x2, y2, head=3.0):
        self.line(x1, y1, x2, y2)
        a = math.atan2(y2 - y1, x2 - x1)
        for da in (2.6, -2.6):
            self.line(x2, y2, x2 + head * math.cos(a + da), y2 + head * math.sin(a + da))

    def text(self, x, y, s, size=3.0, bold=False, angle=0.0, align='left', rgb=(0, 0, 0)):
        """size in mm (cap-to-descender em). angle in degrees."""
        w = text_width(s, size, bold)
        dx = {'left': 0.0, 'center': -w / 2, 'right': -w}[align]
        a = math.radians(angle)
        c, si = math.cos(a), math.sin(a)
        x += dx * c
        y += dx * si
        self.raw('BT %s %s %s rg /%s %s Tf %s %s %s %s %s %s Tm (%s) Tj ET' % (
            _n(rgb[0]), _n(rgb[1]), _n(rgb[2]), 'F2' if bold else 'F1', _n(size),
            _n(c), _n(si), _n(-si), _n(c), _n(x), _n(y), _esc(s)))
        return w


class Document:
    def __init__(self, title=''):
        self.title = title
        self.pages = []

    def add_page(self, w, h):
        p = Page(w, h)
        self.pages.append(p)
        return p

    def save(self, path):
        objs = {}
        fonts = {3: 'Helvetica', 4: 'Helvetica-Bold'}
        for k, name in fonts.items():
            objs[k] = ('<< /Type /Font /Subtype /Type1 /BaseFont /%s '
                       '/Encoding /WinAnsiEncoding >>' % name).encode()
        objs[5] = ('<< /Title (%s) /Producer (EVA Tentacle Builder) >>' % _esc(self.title)).encode('latin-1')
        kids = []
        num = 6
        for p in self.pages:
            content = ('%s 0 0 %s 0 0 cm\n' % (_n(PT_PER_MM), _n(PT_PER_MM)) + '\n'.join(p.ops)).encode('latin-1')
            z = zlib.compress(content, 6)
            objs[num + 1] = b'<< /Length %d /Filter /FlateDecode >>\nstream\n' % len(z) + z + b'\nendstream'
            objs[num] = ('<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %s %s] '
                         '/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents %d 0 R >>'
                         % (_n(p.w * PT_PER_MM), _n(p.h * PT_PER_MM), num + 1)).encode()
            kids.append(num)
            num += 2
        objs[1] = b'<< /Type /Catalog /Pages 2 0 R >>'
        objs[2] = ('<< /Type /Pages /Kids [%s] /Count %d >>'
                   % (' '.join('%d 0 R' % k for k in kids), len(kids))).encode()
        out = bytearray(b'%PDF-1.4\n%\xe2\xe3\xcf\xd3\n')
        offsets = {}
        for k in sorted(objs):
            offsets[k] = len(out)
            out += b'%d 0 obj\n' % k + objs[k] + b'\nendobj\n'
        xref = len(out)
        n = max(objs) + 1
        out += b'xref\n0 %d\n0000000000 65535 f \n' % n
        for k in range(1, n):
            out += b'%010d 00000 n \n' % offsets.get(k, 0)
        out += b'trailer\n<< /Size %d /Root 1 0 R /Info 5 0 R >>\nstartxref\n%d\n%%%%EOF\n' % (n, xref)
        with open(path, 'wb') as f:
            f.write(out)
