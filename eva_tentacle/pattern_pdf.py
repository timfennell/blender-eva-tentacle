"""Lay out one tentacle's EVA panels as a PDF: overview + assembly map,
mat layout, then every panel at 1:1, tiled onto printer paper with
overlapping registration targets (or one full-size page per panel)."""

import math
import time

import numpy as np

from . import geometry as G
from .pdfgen import Document, text_width

PAPER = {
    'LETTER': (215.9, 279.4),
    'A4': (210.0, 297.0),
    'TABLOID': (279.4, 431.8),
}
PRINT_MARGIN = 8.0     # unprintable border on home printers
OVERLAP = 18.0         # tiles overlap by this much; targets sit in the overlap
CANVAS_MARGIN = 14.0
HEADER = 34.0

RED = (0.82, 0.08, 0.08)
BLUE = (0.05, 0.3, 0.85)
GREY = (0.55, 0.55, 0.55)
LIGHT = (0.78, 0.78, 0.78)
BLACK = (0, 0, 0)
PURPLE = (0.5, 0.1, 0.65)

# Line styles carry the meaning so a greyscale printer loses nothing:
CUT_SQUARE = dict(rgb=BLACK, width=0.35)                                  # solid
CUT_BEVEL = dict(rgb=BLACK, width=0.75, dash=(0, 1.5), round_cap=True)    # heavy round dots
BACK_FACE = dict(rgb=GREY, width=0.25, dash=(5.0, 2.5))                   # grey long dashes
FORMING = dict(rgb=LIGHT, width=0.15, dash=(0, 2.6), round_cap=True)      # faint sparse dots
MOUNT_OUTLINE = dict(rgb=BLACK, width=0.45, dash=(6.0, 1.5, 0.8, 1.5))    # dash-dot
TICK = dict(rgb=BLACK, width=0.35)


def _foam(p, meta):
    return getattr(p, 'thickness', None) or meta['thickness']


def _sheet(p, meta):
    return getattr(p, 'mat', None) or (meta['mat_w'], meta['mat_h'])


def _groups(panels, owner, margin):
    """Nest panels per kind of foam (thickness + sheet size), thick first."""
    keyed = {}
    for p in panels:
        m = owner[id(p)]
        key = (round(_foam(p, m), 2), tuple(round(v, 1) for v in _sheet(p, m)))
        keyed.setdefault(key, []).append(p)
    out = []
    for gi, ((t, (w, h)), ps) in enumerate(sorted(keyed.items(), key=lambda kv: -kv[0][0])):
        out.append(dict(thickness=t, w=w, h=h, name='%g mm %s' % (t, 'mat' if gi == 0 else 'sheet'),
                        mats=_pack_mats(ps, w - 2 * margin, h - 2 * margin)))
    return out


def _rot(pts, a):
    c, s = math.cos(a), math.sin(a)
    pts = np.asarray(pts, float)
    return np.stack([pts[..., 0] * c - pts[..., 1] * s, pts[..., 0] * s + pts[..., 1] * c], -1)


def _readable(angle_deg):
    a = (angle_deg + 180.0) % 360.0 - 180.0
    if a > 90:
        a -= 180
    elif a <= -90:
        a += 180
    return a


def _seam_code(labels, a, b):
    return '%s/%s' % (labels[a], labels[b])


# Bevel angles are printed in whole steps (1 degree, or 2 / 5 when a file would
# otherwise need too many gauges). The same rounding is used for every number
# on the pieces and for the gauge page, so each printed angle has its gauge.
_BEVEL_STEP = [1]


def _q(v):
    st = _BEVEL_STEP[0]
    return int(st * round(abs(float(v)) / st))


def _mark_indices(s, tick_every, j0, j1):
    if s.kind == 'seam':
        return [i for i, r in enumerate(s.ids) if r % tick_every == 0 and r not in (j0, j1)]
    if s.kind == 'join':
        return [i for i, c in enumerate(s.ids) if 0 < c < len(s.ids) - 1]
    return []


def _stations(marks, n):
    """Where bevel numbers go: halfway between match marks."""
    ticks = sorted(marks)
    if len(ticks) >= 2:
        st = [(u + v) // 2 for u, v in zip(ticks[:-1], ticks[1:])]
        st += [ticks[0] // 2, (ticks[-1] + n - 1) // 2]
    else:
        st = list(np.linspace(0, n - 1, min(n, 3)).astype(int))
    return sorted(set(min(max(i, 0), n - 1) for i in st))


def _diagram_wanted(panel, s):
    width = float(np.median(np.linalg.norm(panel.Q[:, 0] - panel.Q[:, -1], axis=1)))
    length = float(np.linalg.norm(np.diff(s.pts, axis=0), axis=1).sum())
    return s.bevelled and s.kind != 'tip' and width >= 48.0 and length >= 60.0


def _raw_bevels(panel, meta):
    """Every bevel angle a piece prints: edge stations, the label range and
    the diagram's angle."""
    out = []
    for s in panel.sides:
        if not s.bevelled:
            continue
        b = np.abs(s.bevel)
        marks = _mark_indices(s, meta['tick_every'], panel.j0, panel.j1)
        out += [b[i] for i in _stations(marks, len(b))]
        out += [b.min(), b.max()]
        if _diagram_wanted(panel, s):
            out.append(float(np.median(b)))
    return out


def set_bevel_step(panels, owner):
    """Choose the rounding for a document and return its gauge angles."""
    raw = [v for p in panels for v in _raw_bevels(p, owner[id(p)])]
    for step in (1, 2, 5):
        _BEVEL_STEP[0] = step
        vals = sorted({_q(v) for v in raw} - {0})
        if len(vals) <= 20:
            break
    return vals


def _fmt_bevel(side):
    if not side.bevelled:
        return 'SQUARE CUT 90\xb0'
    b = np.abs(side.bevel)
    lo, hi = _q(b.min()), _q(b.max())
    rng = ('%d\xb0' % hi) if lo == hi else ('%d–%d\xb0' % (lo, hi))
    sign = np.sign(side.bevel[np.argmax(b)])
    return 'BEVEL %s (%s)' % (rng, 'back face narrower' if sign >= 0 else 'back face WIDER')


def _inside(pt, poly):
    x, y = pt
    xs, ys = poly[:, 0], poly[:, 1]
    x2, y2 = np.roll(xs, -1), np.roll(ys, -1)
    cond = (ys > y) != (y2 > y)
    xi = xs + (y - ys) * (x2 - xs) / np.where(y2 - ys == 0, 1e-12, y2 - ys)
    return bool(np.sum(cond & (x < xi)) % 2)


class _Placed:
    """A panel rotated and moved into canvas coordinates."""

    def __init__(self, panel, labels, G_count, ox, oy, angle=None):
        """angle=None: turn for reading (tip right or up). Otherwise use the
        given turn and put the face outline's corner at ox, oy (mat nesting)."""
        a = panel.angle if angle is None else angle
        Q = _rot(panel.Q, a)
        tipdir = Q[-1].mean(0) - Q[0].mean(0)
        if angle is None and tipdir[0] + tipdir[1] < 0:     # tip toward the right or up
            a += math.pi
            Q = _rot(panel.Q, a)
        self.angle = a
        sides = []
        for s in panel.sides:
            sides.append({'s': s, 'face': _rot(s.face, a), 'back': _rot(s.back, a)})
        allp = np.vstack([d['face'] for d in sides] + [d['back'] for d in sides])
        lo = allp.min(0) if angle is None else np.vstack([d['face'][:-1] for d in sides]).min(0)
        shift = np.array([ox, oy]) - lo
        self.Q = Q + shift
        for d in sides:
            d['face'] = d['face'] + shift
            d['back'] = d['back'] + shift
        self.sides = sides
        self.marks = [(t, _rot(pts, a) + shift) for t, pts in panel.marks]
        self.size = allp.max(0) - lo
        self.poly = np.vstack([d['face'][:-1] for d in sides])
        self.ccw = G._signed_area(self.poly) > 0
        self.panel = panel
        g = panel.gore
        self.codes = {
            'right': _seam_code(labels, (g - 1) % G_count, g),
            'left': _seam_code(labels, g, (g + 1) % G_count),
            'bottom': '%s%d/%d' % (labels[g], panel.piece, panel.piece + 1),
            'top': '%s%d/%d' % (labels[g], panel.piece + 1, panel.piece + 2),
        }


def _draw_panel(pg, pl, meta):
    panel = pl.panel
    Q = pl.Q
    R, C = Q.shape[:2]
    tick_every = meta['tick_every']

    # where to heat-form: orange cells must stretch, blue cells must gather
    cut = panel.cut
    if panel.heat is not None:
        for j in range(R - 1):
            for c in range(C - 1):
                h = panel.heat[j, c]
                if abs(h) < 0.015 or (cut is not None and j + 1 <= max(cut[c], cut[c + 1])):
                    continue
                t = min((abs(h) - 0.015) / 0.05, 1.0)
                cell = [Q[j, c], Q[j, c + 1], Q[j + 1, c + 1], Q[j + 1, c]]
                if h > 0:             # stretch: plain shading, darker = more
                    g = 0.93 - 0.18 * t
                    pg.fill((1.0, g, g - 0.08))
                    pg.polyline(cell, close=True, fill=True, stroke=False)
                else:                 # gather: light shading plus hatching
                    pg.fill((0.9, 0.93, 1.0))
                    pg.polyline(cell, close=True, fill=True, stroke=False)
                    pg.stroke(GREY, 0.15 + 0.15 * t)
                    pg.line(*cell[0], *cell[2])
                    pg.line(*(0.5 * (cell[0] + cell[1])), *(0.5 * (cell[1] + cell[2])))
                    pg.line(*(0.5 * (cell[3] + cell[0])), *(0.5 * (cell[2] + cell[3])))

    # forming guides: facet lines along the length and the tick rings across
    pg.stroke(**FORMING)
    for c in range(1, C - 1):
        if cut is None:
            pg.polyline(G.smooth(Q[:, c]))
        else:
            a = int(np.floor(cut[c])) + 1
            pg.polyline(G.smooth(np.vstack([G._row_at(Q, cut[c], c)[None], Q[a:, c]])))
    for j in range(1, R - 1):
        if (panel.j0 + j) % tick_every == 0 and (cut is None or j > cut.max()):
            pg.polyline(G.smooth(Q[j]))

    # other-face line where a bevel moves it
    for d in pl.sides:
        if d['s'].bevelled:
            pg.stroke(**BACK_FACE)
            pg.polyline(G.smooth(d['back']))

    # cut line on the shown face
    for d in pl.sides:
        pg.stroke(**(CUT_BEVEL if d['s'].bevelled else CUT_SQUARE))
        pg.polyline(G.smooth(d['face']))      # corners between sides stay sharp

    for d in pl.sides:
        _annotate_side(pg, pl, d, meta)

    # outlines of parts glued on top (tentacle bases on the mount ring)
    for txt, pts in pl.marks:
        pg.stroke(**MOUNT_OUTLINE)
        pg.polyline(G.smooth(pts))
        c = pts.mean(0)
        pg.text(c[0], c[1] - 1.2, txt, size=3.2, bold=True, align='center')

    # centre label, written along the panel
    mid = R // 2
    centre = Q[mid].mean(0)
    width = float(np.linalg.norm(Q[mid, 0] - Q[mid, -1]))
    tipdir = Q[-1].mean(0) - Q[0].mean(0)
    ang = math.degrees(math.atan2(tipdir[1], tipdir[0]))
    along = _readable(ang)
    a = math.radians(along)
    up = np.array([-math.sin(a), math.cos(a)])
    thin = _foam(panel, meta) < meta['thickness'] - 1e-6
    label = meta.get('big_prefix', '') + panel.label
    line2 = '%s  %s  \u2022  piece %d of %d' % (meta['code'], meta['name'], panel.piece + 1, panel.pieces)
    line3 = '%s  \u2022  %g mm %s' % ('GOOD face up' if not meta['mirror'] else 'BACK face up', _foam(panel, meta),
                                     'SHEET FOAM' if thin else 'foam')
    # keep the block clear of the edge labels (about 11 mm in from each edge)
    avail = max(width - 22.0, 0.4 * width)
    big = min(22.0, max(3.0, avail * 0.6))
    small = float(np.clip(big * 0.3, 1.5, 3.2))
    height = big * 0.75 + small * 2.9
    if height > avail:
        k_ = avail / height
        big, small = big * k_, max(1.2, small * k_)
    along_room = max(panel.length * 0.5, 20.0)
    big = min(big, along_room / max(text_width(label, 1.0, True), 1e-6))
    small = min(small, along_room / max(text_width(line2, 1.0), text_width(line3, 1.0), 1e-6))
    height = big * 0.75 + small * 2.9
    base = centre + up * (height / 2 - big * 0.75)
    pg.text(*base, label, size=big, bold=True, angle=along, align='center')
    pg.text(*(base - up * small * 1.5), line2, size=small, angle=along, align='center')
    pg.text(*(base - up * small * 2.9), line3, size=small, bold=thin, angle=along, align='center')
    # arrow toward the tip
    t = tipdir / max(np.linalg.norm(tipdir), 1e-9)
    alen = float(np.clip(panel.length * 0.12, 12.0, 45.0))
    start = centre + t * (max(text_width(label, big, True), text_width(line2, small)) / 2 + 4)
    pg.stroke(BLACK, 0.35)
    pg.arrow(*start, *(start + t * alen), head=min(4.0, alen * 0.25))
    pg.text(*(start + t * (alen + 2.5)), meta.get('end_word', 'TIP'), size=small, bold=True, angle=along, align='center')


def _annotate_side(pg, pl, d, meta):
    s = d['s']
    face = d['face']
    n = len(face)
    nrm = G._outward_normals(face, pl.ccw)
    code = pl.codes[s.name]
    j0, j1 = pl.panel.j0, pl.panel.j1

    # match marks
    marks = []
    for i in _mark_indices(s, meta['tick_every'], j0, j1):
        if s.kind == 'seam':
            marks.append((i, '%s-%d' % (code, s.ids[i] // meta['tick_every'])))
        else:
            marks.append((i, '%s-%s' % (code, chr(ord('a') + int(s.ids[i]) - 1))))
    for i, txt in marks:
        p = face[i]
        o = nrm[i]
        pg.stroke(**TICK)
        pg.line(*(p - o * 3.0), *(p + o * 2.0))         # notch mark across the cut line
        d_ = face[min(i + 1, n - 1)] - face[max(i - 1, 0)]
        ang = _readable(math.degrees(math.atan2(d_[1], d_[0])))
        pg.text(*(p - o * 5.8), txt, size=2.0, angle=ang, align='center')   # inside the piece

    # bevel angles along the edge
    if s.bevelled:
        # halfway between match marks so the numbers don't sit on the tick labels
        for i in _stations([i for i, _ in marks], n):
            p = face[i] - nrm[i] * 5.8
            pg.text(*p, '%d\xb0' % _q(s.bevel[i]), size=2.4, bold=True, align='center')

    # edge label inside, along the edge
    if s.kind == 'seam':
        label = 'seam %s  –  joins %s  –  %s' % (code, ', '.join(s.neighbours), _fmt_bevel(s))
    elif s.kind == 'join':
        label = 'join %s  –  joins %s  –  %s' % (code, ', '.join(s.neighbours), _fmt_bevel(s))
    elif s.kind == 'base':
        label = meta.get('start_edge', 'BASE EDGE (open, attaches to costume)') + '  –  ' + _fmt_bevel(s)
    else:
        label = meta.get('end_edge', 'TIP END')
    seglen = np.linalg.norm(np.diff(face, axis=0), axis=1)
    total = float(seglen.sum())
    if total < 4:
        return
    narrow = float(np.median(np.linalg.norm(pl.Q[:, 0] - pl.Q[:, -1], axis=1))) < 32.0
    if narrow and s.kind in ('seam', 'join') and len(face) > 2:
        return          # no room: the match codes and bevel numbers carry it
    cum = np.concatenate([[0], np.cumsum(seglen)])
    # a quarter of the way along, at whichever end is further from the centre label
    centre = pl.Q[pl.Q.shape[0] // 2].mean(0)
    picks = []
    for f in ((0.25, 0.75) if total > 120 else (0.5,)):
        k = min(max(int(np.searchsorted(cum, total * f)), 1), n - 1)
        picks.append((float(np.linalg.norm(0.5 * (face[k] + face[k - 1]) - centre)), k))
    i = max(picks)[1]
    dvec = face[i] - face[i - 1]
    ang = _readable(math.degrees(math.atan2(dvec[1], dvec[0])))
    size = float(np.clip(0.85 * total / max(text_width(label, 1.0), 1e-6), 1.0, 2.6))
    p = 0.5 * (face[i] + face[i - 1]) - nrm[i] * 10.0
    pg.text(*p, label, size=size, angle=ang, align='center', bold=s.bevelled)

    # cross-section of the cut beside bevelled edges, where the piece is wide enough
    if _diagram_wanted(pl.panel, s):
        deg = _q(np.median(np.abs(s.bevel)))
        narrower = float(np.median(s.bevel)) >= 0
        inward = -nrm[i]
        edge_pt = 0.5 * (face[i] + face[i - 1]) + (dvec / max(np.linalg.norm(dvec), 1e-9)) * 18.0
        spot = edge_pt + inward * 22.0
        left = inward[0] >= 0
        _bevel_diagram(pg, spot[0], spot[1], deg, narrower, edge_on_left=left)
        corner = np.array([spot[0] + (-12.0 if left else 12.0), spot[1]])
        pg.stroke(BLACK, 0.2)
        pg.arrow(*corner, *(edge_pt + inward * 1.5), head=1.6)        # this diagram is for that edge


def _bevel_diagram(pg, x, y, deg, narrower, edge_on_left=True, scale=1.0):
    """Small cross-section of the foam at a bevelled edge: good face up, a
    dashed upright line, and the cut leaning from it by deg. The cut edge is
    drawn on the side facing the real edge."""
    m = 1.0 if edge_on_left else -1.0
    t = 6.0 * scale                                    # foam thickness as drawn
    lean = (1.0 if narrower else -1.0) * t * math.tan(math.radians(deg))
    P = lambda u, v: (x + m * u * scale, y + v * scale)
    x0 = -12.0
    pg.fill((0.88, 0.88, 0.88))
    pg.stroke(BLACK, 0.3)
    pg.polyline([P(x0, 0), P(x0 + 22, 0), P(x0 + 22, -6), P(x0 + lean / scale, -6)], close=True, fill=True)
    pg.stroke(BLACK, 0.2, (0.8, 0.8))
    pg.line(*P(x0, 1.5), *P(x0, -8.0))                # upright reference
    # angle arc from the upright line to the cut
    a_up = -90.0
    a_cut = math.degrees(math.atan2(-6.0, lean / scale))
    arc = [P(x0 + 4.5 * math.cos(math.radians(a)), 4.5 * math.sin(math.radians(a)))
           for a in np.linspace(a_up, a_cut, 12)]
    pg.stroke(BLACK, 0.3)
    pg.polyline(arc)
    lx, ly = P(x0 + (lean / scale) * 0.5 - 4.0 * (1 if lean >= 0 else -1) * 0.0, -10.5)
    pg.text(*P(x0 + 11, 1.2), 'GOOD face', size=1.8, align='center', rgb=GREY)
    pg.text(*P(x0 + 11, -8.4), 'back', size=1.8, align='center', rgb=GREY)
    pg.text(x, y - 13.0 * scale, '%d\xb0 from upright  (%d\xb0 to the face)' % (round(deg), 90 - round(deg)),
            size=2.2, bold=True, align='center')
    pg.text(x, y - 15.8 * scale, 'back face %s' % ('narrower' if narrower else 'WIDER'), size=1.9, align='center')


def _gauge_page(doc, angles, pw, ph, title):
    """Cut-out card gauges for setting the blade: stand the bottom edge on
    the foam's good face and tilt the blade to the slanted edge."""
    if not angles:
        return
    pg = doc.add_page(pw, ph)
    pg.text(12, ph - 16, '%s  \u2013  bevel gauges (print at 100%%, glue to card, cut out)' % title, size=5.5, bold=True)
    pg.text(12, ph - 22, 'Bevel numbers are measured FROM UPRIGHT: 0\xb0 is a straight-down cut. Stand a gauge on the '
            'foam\'s good face next to the line and tilt the blade until it lies along the slanted edge.',
            size=2.6)
    pg.text(12, ph - 26, 'One gauge for every bevel angle printed on the pieces in this file%s; 0\xb0 means cut '
            'straight down and needs none.' % ('' if _BEVEL_STEP[0] == 1 else
                                               ' (angles are printed in %d\xb0 steps)' % _BEVEL_STEP[0]),
            size=2.6, bold=True)
    _bevel_diagram(pg, 40, ph - 40, 30, True, True, 1.6)
    pg.text(75, ph - 36, 'Example: a 30\xb0 bevel. The blade leans 30\xb0 away from upright, so the cut face makes',
            size=2.6)
    pg.text(75, ph - 40, '60\xb0 with the good face. "Back face narrower" means the cut leans in under the piece.',
            size=2.6)
    Hmax, Wc = 50.0, 32.0
    x, y = 14.0, ph - 72 - Hmax
    for deg in angles:
        H = min(Hmax, 45.0 / max(math.tan(math.radians(deg)), 1e-6))   # steep gauges get shorter
        off = H * math.tan(math.radians(deg))
        if x + Wc + off > pw - 10:
            x = 14.0
            y -= Hmax + 22
            if y < 12:
                pg = doc.add_page(pw, ph)
                y = ph - 20 - Hmax
        shape = [(x, y), (x + Wc + off, y), (x + Wc + off, y + H), (x + off, y + H)]
        pg.stroke(BLACK, 0.35)
        pg.polyline(shape, close=True)
        pg.stroke(BLACK, 0.2, (0.8, 0.8))
        pg.line(x, y, x, y + H)                         # upright, for comparison
        cx = x + off + Wc / 2            # the solid part of the card, clear of the slant
        pg.text(cx, y + H * 0.5, '%d\xb0' % deg, size=min(7.0, H * 0.3), bold=True, align='center')
        pg.text(cx, y + H * 0.5 - min(7.0, H * 0.3) * 0.6, 'from upright', size=2.2, align='center')
        pg.text(cx, y + 2.5, 'stand on good face', size=2.0, align='center', rgb=GREY)
        x += Wc + off + 8


def _scale_check(pg, x, y):
    pg.stroke(BLACK, 0.3)
    pg.rect(x, y, 50, 10)
    pg.text(x + 25, y + 3.4, '50 mm  –  check at 100% scale', size=2.2, align='center')
    pg.line(x, y - 4, x + 25.4, y - 4)
    pg.line(x, y - 5.5, x, y - 2.5)
    pg.line(x + 25.4, y - 5.5, x + 25.4, y - 2.5)
    pg.text(x + 27.5, y - 4.8, '1 inch', size=2.2)


def _header(pg, pl, meta, x, ytop):
    p = pl.panel
    pg.text(x, ytop - 6, '%s %s  –  panel %s' % (meta['code'], meta['name'], p.label), size=5.2, bold=True)
    pg.text(x, ytop - 11.5, 'Gore %s (%s), piece %d of %d  •  rings %d–%d  •  %.0f mm long  •  '
            'needs %.0f \xd7 %.0f mm of mat  •  flatten stretch %.1f%%' % (
                p.gore_label, meta['gore_kind'][p.gore] if meta.get('gore_kind')
                else ('suction side' if meta['is_bottom'][p.gore] else 'top'),
                p.piece + 1, p.pieces, p.j0, p.j1, p.length, p.w, p.h, p.strain * 100), size=2.6)
    face = 'BACK face (mirrored for tracing on the back)' if meta['mirror'] else 'GOOD (outer) face'
    pg.text(x, ytop - 16.5, 'Shown: %s, EVA %g mm.  SOLID line = square cut (90\xb0).  HEAVY DOTTED line = bevel '
            'cut: tilt the blade from vertical by the bold number beside it.' % (face, _foam(p, meta)), size=2.4)
    pg.text(x, ytop - 20.5, 'Grey long dashes = where a bevel comes out on the other face.  Black ticks = match marks: '
            'glue so equal codes meet (e.g. A/B-3 to A/B-3).  Dash-dot = outline of a part glued on top.', size=2.4)
    pg.text(x, ytop - 24.5, 'Faint dots = forming lines and tick rings.  Shaded cells = heat and STRETCH the foam; '
            'hatched cells = heat and GATHER it (darker = more).', size=2.4, rgb=GREY)


def _panel_canvas(pl, meta):
    """Canvas ops (in mm) and size for one panel."""
    from .pdfgen import Page
    w = max(pl.size[0] + 2 * CANVAS_MARGIN, 190.0)
    h = pl.size[1] + 2 * CANVAS_MARGIN + HEADER
    cv = Page(w, h)
    _draw_panel(cv, pl, meta)
    _header(cv, pl, meta, CANVAS_MARGIN * 0.5, h - 2)
    _scale_check(cv, w - 62, h - 14)
    return cv, w, h


def _tiles(polys, cw, ch, pw, ph, header_w=190):
    aw, ah = pw - 2 * PRINT_MARGIN, ph - 2 * PRINT_MARGIN
    sx, sy = aw - OVERLAP, ah - OVERLAP
    nx = max(1, int(math.ceil((cw - OVERLAP) / sx)))
    ny = max(1, int(math.ceil((ch - OVERLAP) / sy)))
    allp = np.vstack(polys)
    keep = {}
    for iy in range(ny):
        for ix in range(nx):
            x0, y0 = ix * sx, ch - ah - iy * sy   # rows counted from the top
            inside = ((allp[:, 0] >= x0) & (allp[:, 0] <= x0 + aw) &
                      (allp[:, 1] >= y0) & (allp[:, 1] <= y0 + ah)).any()
            inside = inside or any(_inside((x0 + aw / 2, y0 + ah / 2), q) for q in polys)
            inside = inside or (iy == 0 and ix * sx < header_w)   # header
            keep[(iy, ix)] = (x0, y0, inside)
    return keep, nx, ny, aw, ah, sx, sy


def _registration_targets(nx, ny, aw, ah, sx, sy, ch):
    """Targets in the overlap strips, numbered; both pages print them."""
    t = []
    k = 1
    for iy in range(ny):
        for ix in range(nx - 1):
            x = (ix + 1) * sx + OVERLAP / 2
            y0 = ch - ah - iy * sy
            for f in (0.3, 0.7):
                t.append((x, y0 + ah * f, k))
                k += 1
    for iy in range(ny - 1):
        for ix in range(nx):
            y = ch - ah - iy * sy + OVERLAP / 2 - 0.0
            y = ch - (iy + 1) * sy - OVERLAP / 2
            x0 = ix * sx
            for f in (0.3, 0.7):
                t.append((x0 + aw * f, y, k))
                k += 1
    return t


def _draw_target(pg, x, y, k):
    pg.stroke(BLACK, 0.25)
    pg.circle(x, y, 4.0)
    pg.circle(x, y, 1.5)
    pg.line(x - 7, y, x + 7, y)
    pg.line(x, y - 7, x, y + 7)
    pg.text(x + 5, y + 4.2, 'R%d' % k, size=2.2, bold=True)


def _add_panel_pages(doc, pl, meta):
    cv, cw, ch = _panel_canvas(pl, meta)
    return _tile_canvas(doc, '\n'.join(cv.ops), cw, ch, [pl.poly], '%s %s' % (meta['code'], pl.panel.label), meta)


def _tile_canvas(doc, body, cw, ch, polys, tag, meta, header_w=190):
    """Print a canvas at 1:1: one page (FULL) or overlapping paper sheets
    with registration targets, skipping sheets with nothing on them."""
    mode = meta['page_mode']
    if mode == 'FULL':
        pg = doc.add_page(cw, ch)
        pg.raw(body)
        return 1, (1, 1)

    pw0, ph0 = PAPER[mode]
    best = None
    for pw, ph in ((pw0, ph0), (ph0, pw0)):
        tl = _tiles(polys, cw, ch, pw, ph, header_w)
        used = sum(1 for v in tl[0].values() if v[2])
        if best is None or used < best[0]:
            best = (used, pw, ph, tl)
    used, pw, ph, (keep, nx, ny, aw, ah, sx, sy) = best
    targets = _registration_targets(nx, ny, aw, ah, sx, sy, ch)
    rows = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
    for iy in range(ny):
        for ix in range(nx):
            x0, y0, inside = keep[(iy, ix)]
            if not inside:
                continue
            pg = doc.add_page(pw, ph)
            pg.push()
            pg.clip_rect(PRINT_MARGIN, PRINT_MARGIN, aw, ah)
            pg.push()
            pg.translate(PRINT_MARGIN - x0, PRINT_MARGIN - y0)
            pg.raw(body)
            for (tx, ty, k) in targets:
                if x0 - 8 <= tx <= x0 + aw + 8 and y0 - 8 <= ty <= y0 + ah + 8:
                    _draw_target(pg, tx, ty, k)
            pg.pop()
            pg.pop()
            # page furniture in the unprinted-content border
            pg.stroke(LIGHT, 0.2, (1, 1))
            pg.rect(PRINT_MARGIN, PRINT_MARGIN, aw, ah)
            pg.stroke(LIGHT, 0.2, (0.5, 1.5))
            if ix > 0:
                pg.line(PRINT_MARGIN + OVERLAP, PRINT_MARGIN, PRINT_MARGIN + OVERLAP, PRINT_MARGIN + ah)
            if iy > 0:
                pg.line(PRINT_MARGIN, PRINT_MARGIN + ah - OVERLAP, PRINT_MARGIN + aw, PRINT_MARGIN + ah - OVERLAP)
            name = '%s%d' % (rows[iy % 26], ix + 1)
            pg.text(PRINT_MARGIN, ph - PRINT_MARGIN + 2.5,
                    '%s  •  sheet %s  (row %s of %d, column %d of %d)  •  print at 100%% / actual size'
                    % (tag, name, rows[iy % 26], ny, ix + 1, nx), size=2.6, bold=True)
            pg.text(PRINT_MARGIN, 2.8, 'Overlap neighbouring sheets by %.0f mm so the numbered R targets sit '
                    'exactly on top of each other, then tape.' % OVERLAP, size=2.2, rgb=GREY)
            nb = []
            for (dy, dx, word) in ((-1, 0, 'above'), (1, 0, 'below'), (0, -1, 'left'), (0, 1, 'right')):
                k2 = (iy + dy, ix + dx)
                if k2 in keep and keep[k2][2]:
                    nb.append('%s%d %s' % (rows[k2[0] % 26], k2[1] + 1, word))
            if nb:
                pg.text(pw - PRINT_MARGIN, 2.8, 'neighbours: ' + ', '.join(nb), size=2.2, align='right', rgb=GREY)
            pg.stroke(BLACK, 0.3)
            pg.line(pw - PRINT_MARGIN - 25.4, ph - PRINT_MARGIN + 3.2, pw - PRINT_MARGIN, ph - PRINT_MARGIN + 3.2)
            pg.text(pw - PRINT_MARGIN - 27, ph - PRINT_MARGIN + 2.5, '1 in', size=2.2, align='right')
    return used, (ny, nx)


# ------------------------------------------------------------ overview

def _raster(poly, res):
    """Cells (rows=y, cols=x) covered by a polygon whose min corner is 0,0."""
    hi = poly.max(0)
    nx, ny = int(hi[0] // res) + 1, int(hi[1] // res) + 1
    xs = (np.arange(nx) + 0.5) * res
    ys = (np.arange(ny) + 0.5) * res
    X, Y = np.meshgrid(xs, ys)
    px, py = poly[:, 0], poly[:, 1]
    qx, qy = np.roll(px, -1), np.roll(py, -1)
    inside = np.zeros(X.shape, bool)
    for x1, y1, x2, y2 in zip(px, py, qx, qy):
        if y1 == y2:
            continue
        crosses = (y1 > Y) != (y2 > Y)
        xi = x1 + (Y - y1) * (x2 - x1) / (y2 - y1)
        inside ^= crosses & (X < xi)
    # cells the outline passes through (thin tips, edges)
    seg = np.linspace(0.0, 1.0, 8)[:, None]
    pts = (poly[None, :, :] * (1 - seg[..., None]) + np.roll(poly, -1, 0)[None] * seg[..., None]).reshape(-1, 2)
    ix = np.clip((pts[:, 0] // res).astype(int), 0, nx - 1)
    iy = np.clip((pts[:, 1] // res).astype(int), 0, ny - 1)
    inside[iy, ix] = True
    return inside


def _dilate(m, k):
    out = np.zeros((m.shape[0] + 2 * k, m.shape[1] + 2 * k), bool)
    for dy in range(2 * k + 1):
        for dx in range(2 * k + 1):
            out[dy:dy + m.shape[0], dx:dx + m.shape[1]] |= m
    return out


def _place(mat, opts, gw, gh, k):
    """Lowest, then leftmost, free spot on a mat for any of the options."""
    best = None
    free = mat['occ'].size - np.count_nonzero(mat['occ'])
    for a, m, Fm, cells in opts:
        if cells > free:
            continue
        kh, kw = m.shape
        corr = np.fft.irfft2(mat['F'] * Fm, s=mat['occ'].shape)
        valid = corr[:gh + 2 * k - kh + 1, :gw + 2 * k - kw + 1] < 0.5
        ys, xs = np.nonzero(valid)
        if len(ys) == 0:
            continue
        i = np.lexsort((xs, ys))[0]
        cand = (ys[i], xs[i], a, m)
        if cand[0] == 0 and cand[1] == 0:
            return cand
        if best is None or (cand[0], cand[1]) < (best[0], best[1]):
            best = cand
    return best


def _put(mat, spot, p, res, F):
    y, x, a, m = spot
    mat['occ'][y:y + m.shape[0], x:x + m.shape[1]] += m
    mat['F'] = F(mat['occ'])
    mat['items'].append((p, x * res, y * res, a))


def _shape_opts(p, turns, res, k, gw, gh, shape_fft):
    base = np.vstack([s.face[:-1] for s in p.sides])
    opts = []
    for q in range(turns):
        a = p.angle + q * 2 * math.pi / turns
        poly = _rot(base, a)
        poly = poly - poly.min(0)
        m = _dilate(_raster(poly, res), k)
        if m.shape[0] <= gh + 2 * k and m.shape[1] <= gw + 2 * k:
            Fm = np.conj(np.fft.rfft2(m.astype(float), s=shape_fft))
            opts.append((a, m, Fm, int(m.sum())))
    return opts


def _pack_once(shapes, gw, gh, k, res):
    mats = []
    F = lambda a: np.fft.rfft2(a, s=(gh + 2 * k, gw + 2 * k))
    for p, opts in shapes:
        if not opts:     # bigger than a mat: give it a mat of its own
            mats.append({'occ': None, 'F': None, 'items': [(p, 0.0, 0.0, p.angle)], 'fill': 1.0})
            continue
        spot = None
        for mat in mats:
            if mat['occ'] is None:
                continue
            spot = _place(mat, opts, gw, gh, k)
            if spot:
                break
        if spot is None:
            mat = {'occ': np.zeros((gh + 2 * k, gw + 2 * k)), 'items': []}
            mat['F'] = F(mat['occ'])
            mats.append(mat)
            spot = _place(mat, opts, gw, gh, k)
        _put(mat, spot, p, res, F)
    for m in mats:
        if m['occ'] is not None:
            m['fill'] = float((m['occ'] > 0).mean())
    return mats


def _pack_mats(panels, W, H, gap=3.0, res=2.0, turns=4, orders=2):
    """Bottom-left nesting of the real panel shapes (rasterised at `res` mm,
    kept `gap` mm apart), quarter turns allowed. A few placing orders are
    tried; then pieces on a nearly empty last mat are squeezed into the gaps
    of earlier mats (trying eighth turns too) so it can be dropped.
    Returns mats: [{'items': [(panel, x, y, angle)]}] with x, y in mm of the
    usable area (the panel's rotated outline starts at x, y)."""
    gw, gh = int(W // res), int(H // res)
    k = max(1, int(round(gap / 2 / res)))
    shape_fft = (gh + 2 * k, gw + 2 * k)
    F = lambda a: np.fft.rfft2(a, s=shape_fft)
    shapes = []
    for p in panels:
        base = np.vstack([s.face[:-1] for s in p.sides])
        bb = base.max(0) - base.min(0)
        shapes.append((abs(G._signed_area(base)), float(max(bb)), float(min(bb)), p,
                       _shape_opts(p, turns, res, k, gw, gh, shape_fft)))
    best = None
    for key in (lambda t: -t[0], lambda t: -t[1], lambda t: -t[2], lambda t: -t[1] * t[2])[:orders]:
        order = [(t[3], t[4]) for t in sorted(shapes, key=key)]
        mats = _pack_once(order, gw, gh, k, res)
        score = (len(mats), mats[-1]['fill'] if mats else 0)
        if best is None or score < best[0]:
            best = (score, mats)
    mats = best[1]

    # squeeze a nearly empty last mat into the others
    while len(mats) > 1 and mats[-1]['occ'] is not None and mats[-1]['fill'] < 0.35:
        last = mats[-1]
        trial = [{'occ': m['occ'].copy(), 'F': m['F'], 'items': list(m['items'])} for m in mats[:-1]
                 if m['occ'] is not None]
        moved = True
        for (p, *_r) in sorted(last['items'], key=lambda it: -abs(G._signed_area(
                np.vstack([s.face[:-1] for s in it[0].sides])))):
            opts = _shape_opts(p, 8, res, k, gw, gh, shape_fft)
            spot = None
            for m in trial:
                spot = _place(m, opts, gw, gh, k)
                if spot:
                    _put(m, spot, p, res, F)
                    break
            if spot is None:
                moved = False
                break
        if not moved:
            break
        keep = [m for m in mats[:-1] if m['occ'] is None]
        mats = keep + trial
        for m in mats:
            if m['occ'] is not None:
                m['fill'] = float((m['occ'] > 0).mean())
    return mats


def _panel_shape_on_mat(p, a):
    pts = _rot(np.vstack([s.face for s in p.sides]), a)
    return pts - pts.min(0)


def _overview(doc, pat, meta, labels, mats):
    pw, ph = PAPER['A4'][::-1] if meta['page_mode'] == 'A4' else PAPER['LETTER'][::-1]
    pg = doc.add_page(pw, ph)
    x = 12
    y = ph - 16
    pg.text(x, y, '%s  %s  –  %s' % (meta['code'], meta['name'], meta.get('kind_title', 'EVA foam tentacle pattern')),
            size=6.5, bold=True)
    y -= 6
    pg.text(x, y, 'Generated %s by the EVA Tentacle Builder Blender add-on. All dimensions in mm. Print every page '
            'at 100%% / actual size and check the 50 mm square.' % time.strftime('%Y-%m-%d'), size=2.6, rgb=GREY)

    # parameters
    y -= 10
    lines = meta.get('params') or [
        ('Length (along centre)', '%.0f mm' % meta['length']),
        ('Base \xd8 / tip \xd8', '%.0f / %.0f mm' % (meta['base_d'], meta['tip_d'])),
        ('Section height / width', '%.2f' % meta['height_ratio']),
        ('Suction-side roundness', '%.2f' % meta['bottom_roundness']),
        ('Gores', '%d top + %d suction side' % (meta['top_gores'], meta['bottom_gores'])),
        ('EVA thickness', '%.1f mm' % meta['thickness']),
        ('Mat size (margin)', '%.0f \xd7 %.0f mm (%.0f)' % (meta['mat_w'], meta['mat_h'], meta['margin'])),
        ('Max bow per piece', ('%.0f mm' % meta['max_bow']) if meta.get('max_bow') else 'off'),
        ('Seam style', meta['seam_desc']),
        ('Panels', '%d' % len(pat.panels)),
        ('Panel area', '%.2f m\xb2' % meta['area_m2']),
        ('Tightest bend', meta['bend_desc']),
    ]
    for r in (meta.get('runs') or [])[1:]:
        lines.append(('Steps to %g mm foam' % r['thickness'], 'at %.0f mm along (%.0f mm wide)'
                      % (r['from_mm'], r['width_mm'])))
    if meta.get('params'):
        lines = lines + [('Panels', '%d' % len(pat.panels)), ('Panel area', '%.2f m\xb2' % meta['area_m2'])]
    for k, v in lines:
        pg.text(x, y, k, size=2.8, rgb=GREY)
        pg.text(x + 40, y, v, size=2.8, bold=True)
        y -= 4.6

    # cross-section at the base
    _section(pg, meta, labels, x + 2, 16, 82, 70)

    # panel map: length along x, one row per gore
    mx0, mx1 = 112, pw - 12
    my = ph - 34
    pg.text(mx0, my + 4, 'Panel map  (%s; match marks every %d rings ~ %.0f mm)'
            % (meta.get('map_note', 'base on the left, tip on the right'), meta['tick_every'],
               meta['tick_every'] * pat.ring_spacing), size=2.8, bold=True)
    span = max(pat.R - 1, 1)
    rowh = min(7.0, 60.0 / max(len(labels), 1))
    for g, lab in enumerate(labels):
        yy = my - (g + 1) * rowh
        pg.text(mx0 - 2, yy + rowh * 0.3, lab, size=2.6, bold=True, align='right')
        for p in [q for q in pat.panels if q.gore == g]:
            xa = mx0 + (mx1 - mx0) * p.j0 / span
            xb = mx0 + (mx1 - mx0) * p.j1 / span
            if _foam(p, meta) < meta['thickness'] - 1e-6:   # thinner stock: darker the thinner
                g_ = 0.55 + 0.3 * _foam(p, meta) / meta['thickness']
                pg.fill((g_, g_, g_))
            else:
                pg.fill((0.93, 0.88, 0.97) if not meta['is_bottom'][g] else (0.98, 0.9, 0.93))
            pg.stroke(BLACK, 0.25)
            pg.rect(xa, yy, xb - xa, rowh * 0.85, fill=True)
            pg.text((xa + xb) / 2, yy + rowh * 0.28, p.label, size=min(2.6, rowh * 0.45), align='center',
                    bold=True)
    # table
    ty = my - (len(labels) + 1) * rowh - 6
    cols = [mx0, mx0 + 14, mx0 + 34, mx0 + 52, mx0 + 74, mx0 + 90]
    heads = ['Panel', 'Rings', 'Length', 'On mat', 'Stretch', 'Edges (right seam / left seam / joins)']
    for cx, hd in zip(cols, heads):
        pg.text(cx, ty, hd, size=2.4, bold=True)
    ty -= 3.8
    for p in pat.panels:
        if ty < 12:
            pg = doc.add_page(pw, ph)
            ty = ph - 16
        sd = {s.name: s for s in p.sides}
        edge = '%s / %s' % (_short_bevel(sd['right']), _short_bevel(sd['left']))
        joins = [s for s in (sd['bottom'], sd['top']) if s.kind == 'join']
        if joins:
            edge += ' / ' + ', '.join(_short_bevel(s) for s in joins)
        on_mat = meta['shared']['mat_of'][id(p)][2] if meta.get('shared') else '%.0f\xd7%.0f' % (p.w, p.h)
        if meta.get('shared'):     # round as the cutting file this piece is printed in does
            _BEVEL_STEP[0] = meta['shared']['steps'][meta['shared']['mat_of'][id(p)][0]]
        vals = [p.label, '%d–%d' % (p.j0, p.j1), '%.0f' % p.length, on_mat,
                '%.1f%%' % (p.strain * 100), edge]
        for cx, v in zip(cols, vals):
            pg.text(cx, ty, v, size=2.3, rgb=RED if (v.endswith('%') and p.strain > 0.03) else BLACK)
        ty -= 3.4

    _instructions(doc, pat, meta, labels, pw, ph, mats)


def _short_bevel(s):
    if not s.bevelled:
        return 'sq'
    return '%d\xb0' % _q(np.abs(s.bevel).max())


def _section(pg, meta, labels, x, y, w, h):
    outer = meta['section_outer']
    mid = meta['section_mid']
    lo = outer.min(0)
    hi = outer.max(0)
    # leave room around the outline for the gore letters and the captions
    sc = min((w - 20) / (hi[0] - lo[0]), (h - 30) / (hi[1] - lo[1]))
    cx = x + w / 2 - sc * (hi[0] + lo[0]) / 2
    cy = y + 12 + (h - 30) / 2 - sc * (hi[1] + lo[1]) / 2
    flip = -1.0 if meta.get('section_flip', True) else 1.0   # tentacles: looking from the tip back
    T = lambda p: (cx + flip * sc * p[0], cy + sc * p[1])
    pg.text(x, y + h + 1, meta.get('section_title', 'Section at the base (viewed from the tip), %.0f mm wide'
                                   % (hi[0] - lo[0])), size=2.6, bold=True)
    pg.stroke(GREY, 0.2, (1, 1))
    pg.polyline([T(p) for p in mid], close=True)
    pg.stroke(BLACK, 0.4)
    pg.polyline([T(p) for p in outer], close=True)
    starts = meta['gore_start']
    M = len(outer)
    centre = outer.mean(0)
    for g, lab in enumerate(labels):
        a = starts[g]
        b = starts[(g + 1) % len(starts)] if g + 1 < len(starts) else M
        pg.stroke(RED, 0.4)
        p = outer[a]
        d = (p - centre) / max(np.linalg.norm(p - centre), 1e-9)
        pg.line(*T(p), *T(p + d * 4 / sc))
        idx = np.arange(a, b + 1) % M
        mpt = outer[idx].mean(0) if len(idx) > 2 else outer[idx[len(idx) // 2]]
        mpt = outer[idx[len(idx) // 2]]
        d = (mpt - centre) / max(np.linalg.norm(mpt - centre), 1e-9)
        pg.text(*T(mpt + d * 7 / sc), lab, size=3.2, bold=True, align='center')
    pg.text(x + w / 2, y + 1, meta.get('section_note', 'suction side (suckers) down'), size=2.4, align='center',
            rgb=GREY)


def _instructions(doc, pat, meta, labels, pw, ph, mats):
    pg = doc.add_page(pw, ph)
    x = 12
    y = ph - 16
    pg.text(x, y, '%s  –  mat layout and assembly' % meta['code'], size=6, bold=True)
    y -= 9
    steps = [
        'Every panel is drawn at 1:1 on the following pages, split onto %s sheets that overlap by %.0f mm.' % (
            {'LETTER': 'US Letter', 'A4': 'A4', 'TABLOID': 'Tabloid', 'FULL': 'full-size'}[meta['page_mode']],
            OVERLAP),
        'Tape the sheets of one panel together with the numbered R targets exactly on top of each other.',
        'Trace onto the foam (%s), and transfer the blue match ticks as small nicks or pen marks.' % (
            'pattern is mirrored for the back face' if meta['mirror'] else 'pattern shows the good face'),
        'Heavy dotted edges get a bevel: tilt the blade from vertical by the bold number (the back face ends up narrower,'
        ' so the panels close into a crisp edge). Solid edges are cut straight down at 90\xb0 and glue into a'
        ' smooth curve.',
        'Heat-form each panel along its dotted facet lines before gluing so it already has the curve of the section.',
    ] + (meta.get('steps') or [
        'Join the pieces of each gore end to end first (A-1 + A-2 ...; join ticks a, b, c line up).',
        'Then glue the gores side by side, matching the seam ticks: A/B-3 meets A/B-3, B/C-5 meets B/C-5 ...',
        'Close the last seam (%s) last; the base edge stays open to attach to the costume.' % (
            _seam_code(labels, len(labels) - 1, 0)),
    ])
    for i, s in enumerate(steps):
        pg.text(x, y, '%d.' % (i + 1), size=2.8, bold=True)
        y = _wrap(pg, x + 6, y, s, pw - 2 * x - 6, 2.8)
        y -= 1.5
    if meta['warnings']:
        y -= 3
        pg.text(x, y, 'Warnings', size=3.2, bold=True, rgb=RED)
        y -= 4.5
        for wtxt in meta['warnings'][:14]:
            y = _wrap(pg, x, y, '• ' + wtxt, pw - 2 * x, 2.6, rgb=RED)

    if mats is None:              # pieces live on the shared mat templates
        sh = meta['shared']
        y -= 6
        pg.text(x, y, 'Cut from the shared cutting templates: %s' % ', '.join(sh['files']), size=3, bold=True)
        y -= 4.5
        by_mat = {}
        for p in pat.panels:
            by_mat.setdefault(sh['mat_of'][id(p)], []).append(p.label)
        for key in sorted(by_mat):
            y = _wrap(pg, x, y, '%s:  %s' % (key[2].capitalize(), ', '.join(by_mat[key])), pw - 2 * x, 2.8)
        return
    full = meta.get('print_layout', 'MATS') in ('MATS', 'BOTH')
    for g in mats:
        y -= 6
        pg.text(x, y, 'Layout on %g mm foam: %d \u00d7 %.0f \xd7 %.0f mm %s%s' % (
            g['thickness'], len(g['mats']), g['w'], g['h'], 'mats' if g['name'] == 'mat' else 'sheets',
            '  \u2013  printed full size on the following pages' if full else ''), size=3, bold=True)
        pg = _mat_thumbs(doc, pg, g['mats'], g['w'], g['h'], meta['margin'], x, y - 4, pw, ph, lambda p: p.label,
                         word=g['name'].rsplit(' ', 1)[-1])
        rows = (len(g['mats']) + max(int((pw - 2 * x) // 64), 1) - 1) // max(int((pw - 2 * x) // 64), 1)
        y = y - 4 - rows * 68 - 4
        if y < 40:
            pg = doc.add_page(pw, ph)
            y = ph - 16


def _mat_thumbs(doc, pg, mats, mat_w, mat_h, margin, x, y, pw, ph, name, word='mat'):
    box = 58.0
    sc = box / max(mat_w, mat_h)
    per_row = max(int((pw - 2 * x) // (box + 6)), 1)
    bx, by = x, y - box * mat_h / max(mat_w, mat_h)
    for i, m in enumerate(mats):
        if i and i % per_row == 0:
            bx = x
            by -= box + 10
            if by < 10:
                pg = doc.add_page(pw, ph)
                by = ph - 20 - box
        pg.stroke(GREY, 0.3)
        pg.rect(bx, by, mat_w * sc, mat_h * sc)
        pg.text(bx, by - 3.5, '%s %d  (%.0f%% used)' % (word, i + 1, 100 * _mat_use(m, mat_w, mat_h)), size=2.4, rgb=GREY)
        for (p, px, py, rot) in m['items']:
            shp = _panel_shape_on_mat(p, rot)
            ox = bx + (margin + px) * sc
            oy = by + (margin + py) * sc
            pg.stroke(BLACK, 0.2)
            pg.polyline([(ox + q[0] * sc, oy + q[1] * sc) for q in shp], close=True)
            c = shp.mean(0)
            pg.text(ox + c[0] * sc, oy + c[1] * sc - 0.8, name(p), size=1.8, bold=True, align='center')
        bx += box + 6
    return pg


def _mat_use(m, mat_w, mat_h):
    area = sum(abs(G._signed_area(np.vstack([s.face[:-1] for s in p.sides]))) for p, *_ in m['items'])
    return area / (mat_w * mat_h)


def _wrap(pg, x, y, s, width, size, rgb=BLACK):
    words = s.split(' ')
    line = ''
    for w in words:
        t = (line + ' ' + w).strip()
        if text_width(t, size) > width and line:
            pg.text(x, y, line, size=size, rgb=rgb)
            y -= size * 1.35
            line = w
        else:
            line = t
    if line:
        pg.text(x, y, line, size=size, rgb=rgb)
        y -= size * 1.35
    return y


# --------------------------------------------------------------- entry

def write_pdf(path, pat, meta, shared=None):
    """shared: {'file', 'n_mats', 'mat_of': {id(panel): mat number}} when the
    pieces are nested with other tentacles on a shared mat-templates PDF."""
    labels = meta['labels']
    doc = Document('%s %s EVA tentacle pattern' % (meta['code'], meta['name']))
    area = 0.0
    for p in pat.panels:
        poly = np.vstack([s.face[:-1] for s in p.sides])
        area += abs(G._signed_area(poly))
    meta['area_m2'] = area / 1e6
    margin = meta['margin']
    meta['shared'] = shared
    owner = {id(p): meta for p in pat.panels}
    groups = None if shared else _groups(pat.panels, owner, margin)
    gauges = set_bevel_step(pat.panels, owner)       # before any angle is printed
    if shared:
        _BEVEL_STEP[0] = max(shared.get('steps') or [1])
    _overview(doc, pat, meta, labels, groups)
    pw_, ph_ = PAPER['A4'][::-1] if meta['page_mode'] == 'A4' else PAPER['LETTER'][::-1]
    if not shared:          # with shared mats the pieces (and their gauges) are in the cutting files
        _gauge_page(doc, gauges, pw_, ph_, '%s %s' % (meta['code'], meta['name']))
    sheets = 0
    layout = meta.get('print_layout', 'MATS')
    if shared and layout == 'MATS':
        layout = 'NONE'          # the full mats are in the shared file
    if layout in ('MATS', 'BOTH') and not shared:
        for g in groups:
            sheets += _add_mat_pages(doc, g['mats'], owner, g['w'], g['h'], margin, meta['page_mode'],
                                     g['thickness'], prefix=meta['code'] + ' ', kind=g['name'])
    if layout in ('PANELS', 'BOTH'):
        for p in pat.panels:
            pl = _Placed(p, labels, len(labels), CANVAS_MARGIN, CANVAS_MARGIN)
            n, _ = _add_panel_pages(doc, pl, meta)
            sheets += n
    doc.save(path)
    return doc, sheets


# ------------------------------------------------------- mat templates

def write_mat_templates(folder, prefix, jobs, margin, page_mode):
    """Full-size cutting templates with every piece of all jobs nested
    together: one PDF per foam stock (e.g. 8 mm mats, 4 mm sheets), tiled
    onto paper. Returns ([(file name, group)], paper sheets, mat_of) where
    mat_of[id(panel)] = (group index, number, '8 mm mat 3 of 8')."""
    import os
    panels, owner = [], {}
    for pat, meta in jobs:
        for p in pat.panels:
            panels.append(p)
            owner[id(p)] = meta
    groups = _groups(panels, owner, margin)
    files = []
    sheets = 0
    mat_of = {}
    steps = []
    pw, ph = PAPER['A4'][::-1] if page_mode == 'A4' else PAPER['LETTER'][::-1]
    for gi, g in enumerate(groups):
        kind = 'mats' if g['name'].endswith('mat') else 'sheets'
        fname = '%s_%gmm_%s_%.0fx%.0f.pdf' % (prefix, g['thickness'], kind, g['w'], g['h'])
        doc = Document('EVA cutting templates %g mm' % g['thickness'])
        pg = doc.add_page(pw, ph)
        used = sum(_mat_use(m, g['w'], g['h']) for m in g['mats']) / max(len(g['mats']), 1)
        pg.text(12, ph - 16, 'Cut from %g mm EVA  \u2013  %d %s of %.0f \xd7 %.0f mm, %.0f%% used' % (
            g['thickness'], len(g['mats']), kind, g['w'], g['h'], 100 * used), size=6, bold=True)
        others = [x for x in groups if x is not g]
        pg.text(12, ph - 22, 'Each %s follows full size, tiled onto paper: tape its sheets together on the R targets, '
                'lay it on the foam with the solid frame on the foam edges, and cut every piece on it.'
                % kind[:-1], size=2.6, rgb=GREY)
        if others:
            pg.text(12, ph - 26.5, 'Other stock: ' + ', '.join('%g mm (%d %s)' % (
                x['thickness'], len(x['mats']), 'mats' if x['name'].endswith('mat') else 'sheets') for x in others)
                + ' \u2013 separate files.', size=2.6, rgb=GREY)
        _mat_thumbs(doc, pg, g['mats'], g['w'], g['h'], margin, 12, ph - 32, pw, ph,
                    lambda p: '%s %s' % (owner[id(p)]['code'], p.label), word=kind[:-1])
        _gauge_page(doc, set_bevel_step([p for m in g['mats'] for (p, *_r) in m['items']], owner), pw, ph,
                    'Cut from %g mm EVA' % g['thickness'])
        steps.append(_BEVEL_STEP[0])
        sheets += _add_mat_pages(doc, g['mats'], owner, g['w'], g['h'], margin, page_mode, g['thickness'],
                                 kind=g['name'])
        doc.save(os.path.join(folder, fname))
        files.append((fname, g))
        for i, m in enumerate(g['mats']):
            for (p, *_r) in m['items']:
                mat_of[id(p)] = (gi, i + 1, '%s %d of %d' % (g['name'], i + 1, len(g['mats'])))
    return files, sheets, mat_of, steps


def _add_mat_pages(doc, mats, owner, W_mat, H_mat, margin, page_mode, thickness, prefix='', kind='mat'):
    """Each mat at full size with its pieces drawn in place, tiled onto
    paper with registration targets: tape up one mat, lay it on the foam."""
    from .pdfgen import Page
    head = 40.0
    cm = CANVAS_MARGIN
    sheets = 0
    for i, m in enumerate(mats):
        cw, ch = W_mat + 2 * cm, H_mat + 2 * cm + head
        cv = Page(cw, ch)
        cv.stroke(BLACK, 0.5)
        cv.rect(cm, cm, W_mat, H_mat)                       # the mat itself
        cv.stroke(LIGHT, 0.25, (2, 2))
        cv.rect(cm + margin, cm + margin, W_mat - 2 * margin, H_mat - 2 * margin)
        polys = []
        names = []
        for (p, x, y, a) in m['items']:
            meta = dict(owner[id(p)])
            meta['big_prefix'] = meta['code'] + ' '
            pl = _Placed(p, meta['labels'], len(meta['labels']), cm + margin + x, cm + margin + y, angle=a)
            _draw_panel(cv, pl, meta)
            polys.append(pl.poly)
            names.append('%s %s' % (meta['code'], p.label))
        top = ch - 2
        cv.text(cm * 0.5, top - 6, '%s%s %d of %d  \u2013  %.0f \xd7 %.0f mm EVA, %g mm thick  \u2013  %d pieces' % (
            prefix, kind.upper(), i + 1, len(mats), W_mat, H_mat, thickness, len(m['items'])), size=5.2, bold=True)
        y = _wrap(cv, cm * 0.5, top - 12, 'Pieces: ' + ', '.join(sorted(names)), min(cw - 75, 420), 2.6)
        cv.text(cm * 0.5, y - 1, 'Tape this mat\'s sheets together on the R targets, lay it on the foam with the solid '
                'frame on the mat edges, and cut. Dashed frame = usable area.', size=2.4, rgb=GREY)
        _scale_check(cv, cw - 62, ch - 14)
        polys.append(np.array([[cm, cm], [cm + W_mat, cm], [cm + W_mat, cm + H_mat], [cm, cm + H_mat]], float))
        n, _ = _tile_canvas(doc, '\n'.join(cv.ops), cw, ch, polys, '%s%s %d' % (prefix, kind.upper(), i + 1),
                            {'page_mode': page_mode}, header_w=cw)
        sheets += n
    return sheets
