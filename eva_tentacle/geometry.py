"""Pure-numpy geometry for EVA foam tentacles.

Cross-section profile, sweep along the posed bone chain, seam fold angles,
splitting gores into mat-sized panels and flattening each panel to 2D.
No bpy imports, so everything here can be tested outside Blender.
"""

import math
from dataclasses import dataclass, field

import numpy as np


# ---------------------------------------------------------------- shape

@dataclass
class Shape:
    length: float = 1.3
    base_radius: float = 0.10
    tip_radius: float = 0.0125
    taper_power: float = 1.2      # 1 = straight cone, <1 fat then sudden, >1 whippy
    bulge: float = 0.1            # extra girth mid-length (fraction of radius)
    flare: float = 0.15           # extra girth right at the base
    flare_length: float = 0.08    # flare falloff, fraction of length
    height_ratio: float = 0.8     # top height / half width
    bottom_roundness: float = 0.25  # 0 = flat suction side, 1 = as round as the top
    top_gores: int = 4
    bottom_gores: int = 1
    top_columns: int = 3          # facets across each top gore
    bottom_columns: int = 4       # facets across each suction-side gore
    ring_spacing: float = 0.02
    adapt: float = 1.5            # extra rings in bends/twists (0 = evenly spaced)


def ring_count(shape):
    return max(int(math.ceil(shape.length / max(shape.ring_spacing, 1e-6))), 8) + 1


def taper_radii(shape, t):
    t = np.clip(np.asarray(t, float), 0.0, 1.0)
    p = max(shape.taper_power, 0.05)
    r = shape.tip_radius + (shape.base_radius - shape.tip_radius) * (1.0 - t) ** p
    r = r * (1.0 + shape.bulge * np.sin(np.pi * t))
    if shape.flare > 0 and shape.flare_length > 1e-6:
        r = r * (1.0 + shape.flare * np.exp(-t / shape.flare_length))
    return np.maximum(r, 1e-6)


# -------------------------------------------------------------- profile

@dataclass
class Profile:
    U: np.ndarray          # (M,2) unit section points (x, z); half width 1
    N: np.ndarray          # (M,2) mitred outward normals
    gore_start: list       # first vertex column of each gore
    gore_cols: list        # facet count of each gore
    labels: list
    is_bottom: list
    Nt: np.ndarray = None  # (M,2) true outward normals of the smooth section (corners averaged)

    @property
    def M(self):
        return len(self.U)

    def gore_columns(self, g):
        """Vertex column indices of gore g, both seams included."""
        return (self.gore_start[g] + np.arange(self.gore_cols[g] + 1)) % self.M


def _region(th0, th1, zscale, n, tangents=False):
    th = np.linspace(th0, th1, 4001)
    pts = np.stack([np.cos(th), zscale * np.sin(th)], 1)
    cum = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(pts, axis=0), axis=1))])
    tg = np.linspace(0.0, cum[-1], n + 1)
    out = np.stack([np.interp(tg, cum, pts[:, 0]), np.interp(tg, cum, pts[:, 1])], 1)
    if not tangents:
        return out[:-1]
    d = np.stack([-np.sin(th), zscale * np.cos(th)], 1)
    d = np.stack([np.interp(tg, cum, d[:, 0]), np.interp(tg, cum, d[:, 1])], 1)
    if np.linalg.norm(d[0]) < 1e-9:      # flat region: direction of travel
        d[:] = pts[-1] - pts[0]
    return out[:-1], _unit(d)


def gore_labels(shape):
    top = [chr(ord('A') + i) for i in range(shape.top_gores)]
    if shape.bottom_gores == 1:
        bot = ['S']
    else:
        bot = ['S%d' % (i + 1) for i in range(shape.bottom_gores)]
    return top + bot


def make_profile(shape):
    """Section runs CCW in (x, z): right side corner, over the top, left
    corner, then along the suction side back to the start."""
    h = shape.height_ratio
    b = shape.bottom_roundness
    nt = shape.top_gores * shape.top_columns
    nb = shape.bottom_gores * shape.bottom_columns
    U = np.vstack([_region(0.0, math.pi, h, nt),
                   _region(math.pi, 2 * math.pi, h * b, nb)])

    prev = np.roll(U, 1, axis=0)
    nxt = np.roll(U, -1, axis=0)

    def seg_normal(a, c):
        d = c - a
        n = np.stack([d[:, 1], -d[:, 0]], 1)
        return n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)

    n0 = seg_normal(prev, U)
    n1 = seg_normal(U, nxt)
    avg = n0 + n1
    avg /= np.maximum(np.linalg.norm(avg, axis=1, keepdims=True), 1e-12)
    N = avg / np.maximum((avg * n1).sum(1, keepdims=True), 0.6)

    # true normals: tangent of the smooth curve, averaged where regions meet
    _, ta = _region(0.0, math.pi, h, nt, True)
    _, tb = _region(math.pi, 2 * math.pi, h * b, nb, True)
    t_top = ta[:-1].copy()
    t_bot = tb[:-1].copy()
    t_top[0] = _unit(ta[0] + tb[-1])
    t_bot[0] = _unit(tb[0] + ta[-1])
    T2 = np.vstack([t_top, t_bot])
    Nt = np.stack([T2[:, 1], -T2[:, 0]], 1)

    starts = [i * shape.top_columns for i in range(shape.top_gores)]
    starts += [nt + i * shape.bottom_columns for i in range(shape.bottom_gores)]
    cols = [shape.top_columns] * shape.top_gores + [shape.bottom_columns] * shape.bottom_gores
    is_bot = [False] * shape.top_gores + [True] * shape.bottom_gores
    return Profile(U, N, starts, cols, gore_labels(shape), is_bot, Nt)


# ------------------------------------------------------------ centreline

def _catmull_rom(joints, per_seg=24):
    P = np.asarray(joints, float)
    n = len(P) - 1
    ext = np.vstack([2 * P[0] - P[1], P, 2 * P[-1] - P[-2]])
    u = np.linspace(0.0, 1.0, per_seg, endpoint=False)[:, None]
    pts, gs = [], []
    for i in range(n):
        p0, p1, p2, p3 = ext[i:i + 4]
        pts.append(0.5 * (2 * p1 + (-p0 + p2) * u + (2 * p0 - 5 * p1 + 4 * p2 - p3) * u ** 2
                          + (-p0 + 3 * p1 - 3 * p2 + p3) * u ** 3))
        gs.append(i + u[:, 0])
    pts.append(P[-1][None])
    gs.append(np.array([float(n)]))
    return np.vstack(pts), np.concatenate(gs)


def _unit(v):
    return v / np.maximum(np.linalg.norm(v, axis=-1, keepdims=True), 1e-12)


@dataclass
class Centreline:
    C: np.ndarray      # (R,3) positions
    T: np.ndarray      # tangents
    X: np.ndarray      # side axis
    Z: np.ndarray      # dorsal axis (suckers are on -Z)
    s: np.ndarray      # arc length at each ring
    total: float
    kappa: np.ndarray  # curvature at each ring


def _ups_at(ups, gr, T):
    nb = len(ups)
    f = np.clip(gr - 0.5, 0.0, nb - 1)
    i0 = np.floor(f).astype(int)
    i1 = np.minimum(i0 + 1, nb - 1)
    w = (f - i0)[:, None]
    up = ups[i0] * (1 - w) + ups[i1] * w
    return _unit(up - (up * T).sum(1, keepdims=True) * T)


def ring_weights(joints, ups, radius=None, adapt=1.5):
    """Dense samples along the centre line and how many rings each part
    deserves: 1 on straight stretches, up to 1 + 3*adapt where the surface
    turns fast (bend or twist, scaled by the local radius)."""
    D, g = _catmull_rom(joints)
    seg = np.linalg.norm(np.diff(D, axis=0), axis=1)
    cum = np.concatenate([[0.0], np.cumsum(np.maximum(seg, 1e-9))])
    w = np.ones(len(cum))
    if adapt > 0 and radius is not None:
        Td = _unit(np.gradient(D, cum, axis=0))
        Zd = _ups_at(np.asarray(ups, float), g, Td)
        turn = np.maximum(np.linalg.norm(np.gradient(Td, cum, axis=0), axis=1),
                          np.linalg.norm(np.gradient(Zd, cum, axis=0), axis=1))
        w = 1.0 + adapt * np.clip(turn * radius(cum / cum[-1]), 0.0, 3.0)
        k = max(len(w) // 40, 1)
        w = np.convolve(np.pad(w, k, mode='edge'), np.ones(2 * k + 1) / (2 * k + 1), mode='valid')
    return D, g, cum, w


def centreline(joints, ups, n_rings, radius=None, adapt=0.0):
    """joints: (N+1,3) bone heads plus last tail. ups: (N,3) bone Z axes.
    With adapt > 0, rings crowd into bends and twists (radius: callable of
    the length fraction, sets how much a turn matters)."""
    D, g, cum, w = ring_weights(joints, ups, radius, adapt)
    total = float(cum[-1])
    W = np.concatenate([[0.0], np.cumsum(0.5 * (w[1:] + w[:-1]) * np.diff(cum))])
    s = np.interp(np.linspace(0.0, W[-1], n_rings), W, cum)
    C = np.stack([np.interp(s, cum, D[:, k]) for k in range(3)], 1)
    gr = np.interp(s, cum, g)

    Td = _unit(np.gradient(D, cum, axis=0))
    kd = np.linalg.norm(np.gradient(Td, cum, axis=0), axis=1)
    T = _unit(np.stack([np.interp(s, cum, Td[:, k]) for k in range(3)], 1))
    kappa = np.interp(s, cum, kd)

    Z = _ups_at(np.asarray(ups, float), gr, T)
    X = np.cross(T, Z)
    return Centreline(C, T, X, Z, s, total, kappa)


@dataclass
class Sweep:
    V: np.ndarray       # (R,M,3)
    radii: np.ndarray   # (R,)
    line: Centreline
    base_bevel: np.ndarray = None   # (M,) blade tilt so the base sits flat on its mount
    V_ext: np.ndarray = None        # untrimmed grid extended back through the mount
    base_cut: np.ndarray = None     # (M,) fractional row in V_ext where each line meets the mount


def sweep(shape, profile, joints, ups, offset=0.0, trim=None):
    """Build the surface. offset > 0 moves it inward (e.g. half the foam
    thickness to get the foam's mid surface). trim: signed function of
    points, negative inside whatever the base is mounted on; the base edge
    is then cut to follow that surface."""
    radius = lambda t: taper_radii(shape, t) * max(shape.height_ratio, 1.0)
    R = ring_count(shape)
    if shape.adapt > 0:
        # add rings in proportion to how much bending there is, in steps of 4
        # so small pose changes don't keep changing the mesh
        _, _, cum, w = ring_weights(joints, ups, radius, shape.adapt)
        mean_w = float(np.trapezoid(w, cum) / cum[-1]) if hasattr(np, 'trapezoid') else float(np.trapz(w, cum) / cum[-1])
        R += 4 * int(round((R - 1) * (mean_w - 1) / 4))
    cl = centreline(joints, ups, R, radius, shape.adapt)
    r = taper_radii(shape, cl.s / max(cl.total, 1e-9))
    off = np.minimum(offset, 0.12 * r * min(1.0, shape.height_ratio))
    px = r[:, None] * profile.U[None, :, 0] - off[:, None] * profile.N[None, :, 0]
    pz = r[:, None] * profile.U[None, :, 1] - off[:, None] * profile.N[None, :, 1]
    V = cl.C[:, None, :] + cl.X[:, None, :] * px[..., None] + cl.Z[:, None, :] * pz[..., None]
    if trim is not None:
        Vt, P, cut = trim_base(V, trim)
        if cut is not None:
            # wall normals from the section's own (mitred) outward directions
            Nn = profile.Nt if profile.Nt is not None else profile.N
            W = _unit(cl.X[:, None, :] * Nn[None, :, :1] + cl.Z[:, None, :] * Nn[None, :, 1:])
            K = len(P) - len(V)
            W = np.concatenate([np.repeat(W[:1], K, 0), W], 0)
            return Sweep(Vt, r, cl, base_tilt(P, W, cut, trim), P, cut)
    return Sweep(V, r, cl)


def base_tilt(P, W, cut, f, eps=1e-4):
    """Blade tilt (degrees from square) along the base edge so the cut
    face lies flat on the mount surface. + = back face narrower.
    P: extended grid, W: its wall normals, cut: fractional row per line."""
    M = P.shape[1]
    a = np.minimum(np.floor(cut).astype(int), len(P) - 2)
    t = (cut - a)[:, None]
    cols = np.arange(M)
    p = P[a, cols] * (1 - t) + P[a + 1, cols] * t
    g = np.stack([(np.asarray(f(p + e)) - np.asarray(f(p - e))) / (2 * eps)
                  for e in np.eye(3) * eps], 1)
    nr = _unit(g)                                   # mount's outward normal
    d = _unit(P[a + 1, cols] - P[a, cols])          # wall running away from the mount
    nw = _unit(W[a, cols] * (1 - t) + W[a + 1, cols] * t)   # wall's outward normal
    tilt = np.degrees(np.arctan2((nr * nw).sum(1), (nr * d).sum(1)))
    return np.clip(tilt, -70.0, 70.0)


def trim_base(V, f, back=None, K=24):
    """Cut the base of a (R,M,3) sweep where it meets a surface (f < 0
    inside it). The base is extended straight back into the surface; each
    lengthwise line then starts at its crossing.
    Returns (trimmed grid for display, extended grid, cut row per column
    as a fractional row index into the extended grid) or (V, None, None)."""
    R, M, _ = V.shape
    T0 = _unit(V[1].mean(0) - V[0].mean(0))
    span = float(np.linalg.norm(V[0] - V[0].mean(0), axis=1).max())
    back = back or 4.0 * span
    steps = back * np.arange(K, 0, -1) / K
    P = np.concatenate([V[0][None] - T0[None, None, :] * steps[:, None, None], V], 0)
    fv = np.asarray(f(P.reshape(-1, 3))).reshape(K + R, M)
    out = fv > 0
    in_rows = np.nonzero(~out.all(1))[0]
    if len(in_rows) == 0:
        return V, None, None
    last = int(in_rows.max())
    if last >= K + R - 3:
        return V, None, None             # buried in the surface: leave it alone
    cut = np.full(M, float(K))
    for c in range(M):
        cross = np.nonzero(~out[:-1, c] & out[1:, c])[0]
        cross = cross[cross <= last]
        if len(cross):
            i = int(cross.max())
            cut[c] = i + fv[i, c] / (fv[i, c] - fv[i + 1, c])
    # display grid: each line starts at its cut, first rows re-spaced
    J0 = min(max(last - K + 2, 1), R - 1)
    Vt = V.copy()
    for c in range(M):
        col = P[:, c]
        cum = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(col, axis=0), axis=1))])
        i = min(int(cut[c]), K + R - 2)
        s0 = cum[i] + (cut[c] - i) * (cum[i + 1] - cum[i])
        s = np.linspace(s0, cum[K + J0], J0 + 1)
        Vt[:J0 + 1, c] = np.stack([np.interp(s, cum, col[:, k]) for k in range(3)], 1)
    return Vt, P, cut


def ring_inside(rs):
    """Signed distance-like function for a mount ring (ring-local points):
    negative inside the funnel, zero on its outer skin."""
    v = np.linspace(0.0, 1.0, 801)
    r, z = ring_profile(rs, v)
    order = np.argsort(z)
    zs, rr = z[order], r[order]

    def f(q):
        q = np.asarray(q, float)
        rho = np.sqrt(q[:, 0] ** 2 + (q[:, 1] / rs.depth_ratio) ** 2)
        return rho - np.interp(q[:, 2], zs, rr)
    return f


def grid_faces(R, M):
    """Quads (j,c) (j+1,c) (j+1,c+1) (j,c+1); face index = j*M + c.
    Winding gives outward normals."""
    faces = []
    for j in range(R - 1):
        for c in range(M):
            c1 = (c + 1) % M
            faces.append((j * M + c, (j + 1) * M + c, (j + 1) * M + c1, j * M + c1))
    return faces


def fabric_coords(V, radii, profile):
    """Per face corner (in grid_faces order) for costume materials:
    fab = (distance around the section, distance along the tentacle, sucker
    cells along: length / (2 x local radius), so they shrink toward the tip);
    under = (1 on the suction side, position across the suction side 0..1, 0)."""
    R, M, _ = V.shape
    ring_step = np.linalg.norm(np.diff(V, axis=1, append=V[:, :1]), axis=2)      # (R,M): c -> c+1
    around = np.concatenate([np.zeros((R, 1)), np.cumsum(ring_step, axis=1)], 1)  # (R,M+1)
    along = np.concatenate([np.zeros((1, M)), np.cumsum(np.linalg.norm(np.diff(V, axis=0), axis=2), axis=0)], 0)
    ds = np.diff(along.mean(1))
    rr = 0.5 * (radii[1:] + radii[:-1])
    cells = np.concatenate([[0.0], np.cumsum(ds / np.maximum(2 * rr, 1e-9))])
    bottom = np.zeros(M, bool)
    for g in range(len(profile.gore_start)):
        if profile.is_bottom[g]:
            bottom[(profile.gore_start[g] + np.arange(profile.gore_cols[g])) % M] = True
    first = int(np.argmax(bottom))                  # first suction-side column
    width = np.maximum(around[:, M] - around[:, first], 1e-9)
    fab, under = [], []
    for j in range(R - 1):
        for c in range(M):
            for jj, cc in ((j, c), (j + 1, c), (j + 1, c + 1), (j, c + 1)):
                fab.append((around[jj, cc], along[jj, cc % M], cells[jj]))
                if bottom[c]:
                    under.append((1.0, (around[jj, cc] - around[jj, first]) / width[jj], 0.0))
                else:
                    under.append((0.0, -1.0, 0.0))
    return np.array(fab, np.float32), np.array(under, np.float32)


def tightest_bend(sw, shape):
    """Smallest (bend radius / section half-height) along the tentacle.
    Below 1 the inside of the curl folds through itself."""
    depth = sw.radii * max(shape.height_ratio, 1e-3)
    ratio = 1.0 / np.maximum(sw.line.kappa, 1e-9) / depth
    i = int(np.argmin(ratio))
    return float(ratio[i]), float(sw.line.s[i] / max(sw.line.total, 1e-9))


# ---------------------------------------------------------- fold angles

def fold_angles(V):
    """Signed fold (degrees, + = convex) at every vertex, across the
    lengthwise lines (LF) and across the rings (TF)."""
    R, M, _ = V.shape
    v0 = V[:-1]
    v1 = V[1:]
    v2 = np.roll(V[1:], -1, axis=1)
    v3 = np.roll(V[:-1], -1, axis=1)
    Fn = _unit(np.cross(v2 - v0, v3 - v1))          # (R-1,M,3)
    Fc = (v0 + v1 + v2 + v3) / 4.0

    def signed(na, nb, ca, cb):
        ang = np.degrees(np.arccos(np.clip((na * nb).sum(-1), -1.0, 1.0)))
        convex = ((cb - ca) * na).sum(-1) <= 0
        return np.where(convex, ang, -ang)

    # across lengthwise line c: faces c-1 and c in each face row
    rowfold = signed(np.roll(Fn, 1, axis=1), Fn, np.roll(Fc, 1, axis=1), Fc)   # (R-1,M)
    LF = np.zeros((R, M))
    LF[:-1] += rowfold
    LF[1:] += rowfold
    LF[1:-1] *= 0.5

    colfold = signed(Fn[:-1], Fn[1:], Fc[:-1], Fc[1:])                          # (R-2,M)
    TF = np.zeros((R, M))
    TF[1:-1] = 0.5 * (colfold + np.roll(colfold, 1, axis=1))
    return LF, TF


# ----------------------------------------------------------- flattening

def _apex(A, B, dA, dB, side):
    """Point at distances dA, dB from A, B; side=+1 puts it left of A->B."""
    u = B - A
    L = math.hypot(u[0], u[1])
    if L < 1e-9:
        return A + np.array([0.0, dA])
    u = u / L
    x = (dA * dA - dB * dB + L * L) / (2 * L)
    h = math.sqrt(max(dA * dA - x * x, 0.0))
    return A + x * u + side * h * np.array([-u[1], u[0]])


def unfold(P):
    """Lay a (R,C,3) strip flat triangle by triangle. Each ring row is
    started at the middle column from the row below, then marched outward
    along the row, so every vertex keeps its distance to two placed
    neighbours. Rows advance along +y, columns along +x. Each new vertex is
    put on the side that keeps its row ahead of the row below (so cells
    can't flip); only when that is ambiguous does the 3D winding decide."""
    R, C, _ = P.shape
    Q = np.zeros((R, C, 2))
    Q[0, 1:, 0] = np.cumsum(np.linalg.norm(np.diff(P[0], axis=0), axis=1))
    # 2D (x=c, y=j) is seen from inside: 2D left turn == 3D turn against outward
    out = _unit(np.cross(np.gradient(P, axis=0), np.gradient(P, axis=1)))

    def ahead(j, c, pt):
        """How far pt lies on the advancing side of row j at column c."""
        a, b = Q[j, max(c - 1, 0)], Q[j, min(c + 1, C - 1)]
        d = b - a
        return d[0] * (pt[1] - Q[j, c][1]) - d[1] * (pt[0] - Q[j, c][0])

    def place(n, c, ia, ib):
        A3, B3, X3 = P[ia], P[ib], P[n, c]
        dA, dB = float(np.linalg.norm(X3 - A3)), float(np.linalg.norm(X3 - B3))
        c1 = _apex(Q[ia], Q[ib], dA, dB, 1.0)
        c2 = _apex(Q[ia], Q[ib], dA, dB, -1.0)
        a1, a2 = ahead(n - 1, c, c1), ahead(n - 1, c, c2)
        if (a1 > 0) != (a2 > 0):
            Q[n, c] = c1 if a1 > 0 else c2
        else:
            turn = np.dot(np.cross(B3 - A3, X3 - A3), out[n, c])
            Q[n, c] = c2 if turn > 0 else c1

    m = min(C // 2, C - 2)
    for j in range(R - 1):
        n = j + 1
        place(n, m, (j, m), (j, m + 1))
        for c in range(m + 1, C):
            place(n, c, (n, c - 1), (j, c))
        for c in range(m - 1, -1, -1):
            place(n, c, (n, c + 1), (j, c))
    return Q


def _grid_edges(R, C):
    idx = np.arange(R * C).reshape(R, C)
    e = [(idx[:, :-1], idx[:, 1:]), (idx[:-1, :], idx[1:, :]),
         (idx[:-1, :-1], idx[1:, 1:]), (idx[:-1, 1:], idx[1:, :-1])]
    a = np.concatenate([x[0].ravel() for x in e])
    b = np.concatenate([x[1].ravel() for x in e])
    return a, b


def _grid_triangles(R, C):
    """Both triangulations of every cell, as index triples."""
    idx = np.arange(R * C).reshape(R, C)
    v00, v10, v11, v01 = idx[:-1, :-1], idx[1:, :-1], idx[1:, 1:], idx[:-1, 1:]
    tris = [(v00, v10, v11), (v00, v11, v01), (v00, v10, v01), (v10, v11, v01)]
    return np.stack([np.concatenate([t[i].ravel() for t in tris]) for i in range(3)], 1)


def _signed_areas(q, T):
    a, b, c = q[T[:, 0]], q[T[:, 1]], q[T[:, 2]]
    return 0.5 * ((b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1]) - (b[:, 1] - a[:, 1]) * (c[:, 0] - a[:, 0]))


def folded_cells(Q):
    """Number of grid cells whose flat outline is turned inside out."""
    d1 = Q[1:, 1:] - Q[:-1, :-1]
    d2 = Q[1:, :-1] - Q[:-1, 1:]
    A = d1[..., 0] * d2[..., 1] - d1[..., 1] * d2[..., 0]
    return int((A * np.sign(np.median(A)) <= 0).sum())


def relax(Q, P, iters=300):
    """Spring relaxation of the unfolded grid toward the 3D edge lengths
    (rows, columns and both diagonals), plus a guard that pushes any
    squashed or flipped triangle back toward its 3D area so cells cannot
    fold over. Returns (Q, strain)."""
    R, C = Q.shape[:2]
    a, b = _grid_edges(R, C)
    P3 = P.reshape(-1, 3)
    rest = np.linalg.norm(P3[b] - P3[a], axis=1)
    T = _grid_triangles(R, C)
    A3 = 0.5 * np.linalg.norm(np.cross(P3[T[:, 1]] - P3[T[:, 0]], P3[T[:, 2]] - P3[T[:, 0]]), axis=1)
    q = Q.reshape(-1, 2).copy()
    sgn = np.sign(np.median(_signed_areas(q, T))) or 1.0
    deg = np.bincount(np.concatenate([a, b]), minlength=R * C).astype(float)[:, None]
    for _ in range(iters):
        d = q[b] - q[a]
        L = np.maximum(np.linalg.norm(d, axis=1), 1e-12)
        corr = ((L - rest) / L * 0.5)[:, None] * d
        disp = np.zeros_like(q)
        np.add.at(disp, a, corr)
        np.add.at(disp, b, -corr)
        q += disp / deg
        # area guard on triangles that are flipped or squashed below half size
        A2 = _signed_areas(q, T) * sgn
        bad = np.nonzero(A2 < 0.5 * A3)[0]
        if len(bad):
            t = T[bad]
            pa, pb, pc = q[t[:, 0]], q[t[:, 1]], q[t[:, 2]]
            ga = 0.5 * np.stack([pb[:, 1] - pc[:, 1], pc[:, 0] - pb[:, 0]], 1) * sgn
            gb = 0.5 * np.stack([pc[:, 1] - pa[:, 1], pa[:, 0] - pc[:, 0]], 1) * sgn
            gc = 0.5 * np.stack([pa[:, 1] - pb[:, 1], pb[:, 0] - pa[:, 0]], 1) * sgn
            g2 = (ga ** 2 + gb ** 2 + gc ** 2).sum(1)
            step = ((A3[bad] - A2[bad]) / np.maximum(g2, 1e-9))[:, None] * 0.5
            fix = np.zeros_like(q)
            cnt = np.zeros(len(q))
            for k, g in ((0, ga), (1, gb), (2, gc)):
                np.add.at(fix, t[:, k], step * g)
                np.add.at(cnt, t[:, k], 1.0)
            q += fix / np.maximum(cnt, 1.0)[:, None]
    L = np.linalg.norm(q[b] - q[a], axis=1)
    keep = rest > max(2.0, 0.1 * float(np.median(rest)))  # tiny tip edges are noise
    # 95th percentile: a few sliver edges at a tight tip should not dominate
    strain = float(np.percentile(np.abs(L[keep] / rest[keep] - 1.0), 95)) if keep.any() else 0.0
    return q.reshape(R, C, 2), strain


def fit_rotation(pts, W, H, step_deg=1.0, natural=False):
    """Rotation of pts for a W x H mat. Returns (fits, angle_rad, w, h).
    natural=False: any rotation that fits, smallest box first.
    natural=True: the panel must fit lying in its own smallest-box
    orientation (so long strips nest side by side instead of running
    corner to corner)."""
    pts = np.asarray(pts, float).reshape(-1, 2)
    ang = np.radians(np.arange(0.0, 180.0, step_deg))
    c, s = np.cos(ang), np.sin(ang)
    X = pts[:, :1] * c - pts[:, 1:] * s
    Y = pts[:, :1] * s + pts[:, 1:] * c
    w = X.max(0) - X.min(0)
    h = Y.max(0) - Y.min(0)
    area = w * h
    if natural:
        i = int(np.argmin(area))
        if w[i] < h[i]:            # lay it long side along the mat width
            i = (i + int(round(90 / step_deg))) % len(ang)
        ok = (w[i] <= W and h[i] <= H) or (h[i] <= W and w[i] <= H)
        return bool(ok), float(ang[i]), float(w[i]), float(h[i])
    ok = (w <= W) & (h <= H)
    if ok.any():
        i = int(np.argmin(np.where(ok, area, np.inf)))
        return True, float(ang[i]), float(w[i]), float(h[i])
    over = np.maximum(w / W, h / H)
    i = int(np.argmin(over))
    return False, float(ang[i]), float(w[i]), float(h[i])


# --------------------------------------------------------------- panels

@dataclass
class Settings:
    mat_w: float = 610.0          # all mm
    mat_h: float = 610.0
    margin: float = 10.0
    max_len: float = 0.0          # 0 = no limit besides the mat
    max_bow: float = 50.0         # split pieces that curve further than this off straight; 0 = off
    max_strain: float = 0.0       # split pieces that would stretch more than this when formed; 0 = off
    min_piece: float = 100.0      # ...but never shorter than this (mm)
    align_breaks: bool = True
    relax_iters: int = 300
    seam_style: str = 'AUTO'      # AUTO, BEVEL, SQUARE
    crease_deg: float = 10.0      # AUTO: bevel seams whose crease exceeds this
    thickness: float = 10.0
    tick_spacing: float = 50.0


@dataclass
class Side:
    name: str                  # bottom, left, top, right (loop order)
    kind: str                  # seam, join, base, tip
    pts: np.ndarray            # (n,2) mid-surface line
    bevel: np.ndarray          # (n,) signed blade tilt, degrees
    bevelled: bool
    ids: np.ndarray            # ring index (seams) or vertex column (joins)
    neighbours: list           # panel labels on the other side
    face: np.ndarray = None    # line on the shown face
    back: np.ndarray = None    # line on the hidden face


@dataclass
class Panel:
    gore: int
    gore_label: str
    piece: int
    pieces: int
    j0: int
    j1: int
    cols: np.ndarray
    Q: np.ndarray              # (rows, C, 2)
    strain: float
    fits: bool
    angle: float
    w: float
    h: float
    length: float              # along the middle line
    sides: list = field(default_factory=list)
    marks: list = field(default_factory=list)   # [(text, (n,2) polyline in Q space)]
    cut: np.ndarray = None                      # per column: row where the base is cut off
    heat: np.ndarray = None                     # (rows-1, C-1): + needs stretching, - gathering

    @property
    def label(self):
        return '%s-%d' % (self.gore_label, self.piece + 1)


@dataclass
class Pattern:
    panels: list
    warnings: list
    ring_spacing: float
    tick_every: int
    R: int
    M: int
    row_offset: int = 0     # pattern row j is row j + row_offset of the grid passed in


def _mid_length(Pg):
    mid = Pg[:, Pg.shape[1] // 2]
    return np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(mid, axis=0), axis=1))])


def bow(Q, w=None, h=None):
    """How far a flattened piece curves off straight: the short side of its
    smallest box minus the piece's own widest width (mm)."""
    if w is None:
        _, _, w, h = fit_rotation(Q, 1e9, 1e9, natural=True)
    width = float(np.max(np.linalg.norm(Q[:, 0] - Q[:, -1], axis=1)))
    return max(0.0, min(w, h) - width)


class _Splitter:
    def __init__(self, grids, st):
        self.grids = grids
        self.st = st
        self.W = st.mat_w - 2 * st.margin
        self.H = st.mat_h - 2 * st.margin
        self.cache = {}

    def relaxed(self, g, j0, j1):
        key = (g, j0, j1)
        if key not in self.cache:
            P = self.grids[g][j0:j1 + 1]
            self.cache[key] = relax(unfold(P), P, self.st.relax_iters)
        return self.cache[key]

    def ok(self, Q):
        fits, _, w, h = fit_rotation(Q, self.W, self.H, natural=True)
        if fits and self.st.max_bow > 0 and len(Q) > 2:
            fits = bow(Q, w, h) <= self.st.max_bow
        return fits

    def fits(self, g, j0, j1):
        Q, strain = self.relaxed(g, j0, j1)
        if not self.ok(Q):
            return False
        if self.st.max_strain > 0 and strain > self.st.max_strain:
            return j1 - j0 <= self.min_rows(g, j0)     # as short as allowed: accept, warn later
        return True

    def min_rows(self, g, j0):
        L = _mid_length(self.grids[g][j0:])
        return max(1, int(np.searchsorted(L, self.st.min_piece)))

    def guess_end(self, g, j0):
        """Furthest ring the unrelaxed unfold still fits (binary search)."""
        P = self.grids[g][j0:]
        Q = unfold(P)
        L = _mid_length(P)
        n = len(P) - 1
        lo, hi = 1, n
        if not fit_rotation(Q[:2], self.W, self.H, natural=True)[0]:
            return j0 + 1
        while lo < hi:
            k = (lo + hi + 1) // 2
            ok = k == 1 or self.ok(Q[:k + 1])
            if self.st.max_len > 0 and L[k] > self.st.max_len:
                ok = False
            if ok:
                lo = k
            else:
                hi = k - 1
        return j0 + lo

    def confirm(self, gores, j0, end):
        while end > j0 + 1 and not all(self.fits(g, j0, end) for g in gores):
            end -= max(1, (end - j0) // 12)
        return end

    def split(self, gores, first_min=1):
        R = self.grids[gores[0]].shape[0]
        breaks = [0]
        j0 = 0
        while j0 < R - 1:
            end = min(self.guess_end(g, j0) for g in gores)
            end = self.confirm(gores, j0, end)
            if j0 == 0:
                end = min(max(end, first_min), R - 1)   # first piece holds the whole base cut
            # don't leave a stub at the tip: take it in, or share what is left
            left = R - 1 - end
            if 0 < left < min(self.min_rows(g, end) for g in gores):
                if all(self.fits(g, j0, R - 1) for g in gores):
                    end = R - 1
                elif end - j0 > left:
                    end = j0 + (R - 1 - j0) // 2
            breaks.append(end)
            j0 = end
        # try the same number of pieces at equal lengths
        n = len(breaks) - 1
        if n > 1:
            even = [int(round(i * (R - 1) / n)) for i in range(n + 1)]
            ok = even[1] >= first_min and all(self.fits(g, even[i], even[i + 1])
                                               for g in gores for i in range(n))
            if ok and self.st.max_len > 0:
                ok = all(_mid_length(self.grids[g][even[i]:even[i + 1] + 1])[-1] <= self.st.max_len
                         for g in gores for i in range(n))
            if ok:
                breaks = even
        return breaks


def area_stretch(P, Q):
    """Per grid cell: how much bigger the 3D surface is than the flat
    panel (+ = heat and stretch the foam there, - = heat and gather it)."""
    def area(A, dim3):
        d1 = A[1:, 1:] - A[:-1, :-1]
        d2 = A[1:, :-1] - A[:-1, 1:]
        if dim3:
            return 0.5 * np.linalg.norm(np.cross(d1, d2), axis=-1)
        return 0.5 * np.abs(d1[..., 0] * d2[..., 1] - d1[..., 1] * d2[..., 0])
    a2, a3 = area(Q, False), area(P, True)
    ok = a3 > 0.05 * float(np.median(a3))          # skip squashed slivers at the very tip
    return np.clip(np.where(ok, a3 / np.maximum(a2, 1e-9) - 1.0, 0.0), -0.5, 0.5)


def _row_at(Q, r, c):
    a = min(int(np.floor(r)), Q.shape[0] - 2)
    t = r - a
    return Q[a, c] * (1 - t) + Q[a + 1, c] * t


def _cut_side(side, Q, r, c, j0, reverse=False):
    """Shorten a lengthwise side so it starts at the base cut (row r)."""
    pts, bev, ids = side.pts, side.bevel, side.ids
    if reverse:
        pts, bev, ids = pts[::-1], bev[::-1], ids[::-1]
    a = int(np.floor(r)) + 1
    pts = np.vstack([_row_at(Q, r, c)[None], pts[a:]])
    bev = np.concatenate([[bev[min(a - 1, len(bev) - 1)]], bev[a:]])
    ids = np.concatenate([[-1], ids[a:]])
    if reverse:
        pts, bev, ids = pts[::-1], bev[::-1], ids[::-1]
    side.pts, side.bevel, side.ids = pts, bev, ids
    return side


def _crease(fold, inner_a, inner_b):
    """Crease left after each panel takes up its own curvature."""
    return fold - 0.5 * (inner_a + inner_b)


def build_pattern(V, profile, st, base_bevel=None, base_cut=None):
    """V: (R,M,3) mid-surface in mm. Returns a Pattern. base_cut: per
    lengthwise line, the fractional row where the base is cut off (V is
    then the grid extended back through the mount)."""
    first_min = 1
    base_cut_in = base_cut
    if base_cut is not None:
        j_start = int(np.floor(base_cut.min()))
        V = V[j_start:]
        base_cut = np.asarray(base_cut, float) - j_start
        first_min = int(np.ceil(base_cut.max())) + 1
    R, M, _ = V.shape
    G = len(profile.gore_start)
    LF, TF = fold_angles(V)
    gcols = [profile.gore_columns(g) for g in range(G)]
    grids = [V[:, c] for c in gcols]
    warnings = []

    sp = _Splitter(grids, st)
    if st.align_breaks:
        b = sp.split(list(range(G)), first_min)
        breaks = [b] * G
    else:
        breaks = [sp.split([g], first_min) for g in range(G)]

    # crease per lengthwise seam: subtract the panels' own curvature
    def seam_crease(g, side):
        c = gcols[g][0] if side == 'right' else gcols[g][-1]
        fold = LF[:, c]
        if side == 'right':
            mine = LF[:, gcols[g][1]] if profile.gore_cols[g] > 1 else 0.0
            ng = (g - 1) % G
            theirs = LF[:, gcols[ng][-2]] if profile.gore_cols[ng] > 1 else 0.0
        else:
            mine = LF[:, gcols[g][-2]] if profile.gore_cols[g] > 1 else 0.0
            ng = (g + 1) % G
            theirs = LF[:, gcols[ng][1]] if profile.gore_cols[ng] > 1 else 0.0
        return _crease(fold, mine, theirs), ng

    TFc = np.zeros_like(TF)
    TFc[2:-2] = _crease(TF[2:-2], TF[1:-3], TF[3:-1])

    def decide(crease):
        if st.seam_style == 'SQUARE':
            return False
        if st.seam_style == 'BEVEL':
            return True
        return float(np.max(np.abs(crease))) >= st.crease_deg

    def neighbours_on(g, j0, j1):
        out = []
        for k in range(len(breaks[g]) - 1):
            a, b = breaks[g][k], breaks[g][k + 1]
            if a < j1 and b > j0:
                out.append('%s-%d' % (profile.labels[g], k + 1))
        return out

    tick_every = max(1, int(round(st.tick_spacing / max(np.linalg.norm(V[1] - V[0], axis=1).mean(), 1e-6))))
    rings = np.arange(R)

    panels = []
    for g in range(G):
        cols = gcols[g]
        n = len(breaks[g]) - 1
        for k in range(n):
            j0, j1 = breaks[g][k], breaks[g][k + 1]
            Q, strain = sp.relaxed(g, j0, j1)
            Q = Q.copy()
            Q[..., 0] *= -1.0     # view from outside: column 0 on the right, tip up
            fits, ang, w, h = fit_rotation(Q, sp.W, sp.H, natural=True)
            if not fits:
                warnings.append('%s-%d does not fit the mat (%.0f x %.0f mm needed)'
                                % (profile.labels[g], k + 1, w, h))
            if strain > 0.03:
                warnings.append('%s-%d has to stretch ~%.1f%% to take its 3D shape (tight curl on a wide, '
                                'curved gore). Heat-form it, or use more gores to make panels narrower.'
                                % (profile.labels[g], k + 1, strain * 100))
            p = Panel(g, profile.labels[g], k, n, j0, j1, cols, Q, strain, fits, ang, w, h,
                      float(_mid_length(grids[g][j0:j1 + 1])[-1]))
            p.heat = area_stretch(grids[g][j0:j1 + 1], Q)
            if folded_cells(Q):
                warnings.append('%s-%d folds over itself when laid flat (%d cells) - do not cut that spot; '
                                'try more gores or ring spacing' % (profile.labels[g], k + 1, folded_cells(Q)))

            cr_r, ng_r = seam_crease(g, 'right')
            cr_l, ng_l = seam_crease(g, 'left')
            rr = slice(j0, j1 + 1)

            # bottom (towards base), loop order: right -> left along row j0
            rcut = None
            if j0 == 0 and base_cut is not None:
                rcut = np.minimum(base_cut[cols], Q.shape[0] - 1.001)
            if j0 == 0:
                bb = np.zeros(len(cols)) if base_bevel is None else np.asarray(base_bevel)[cols]
                pts = Q[0] if rcut is None else np.array([_row_at(Q, rcut[i], i) for i in range(len(cols))])
                bt = Side('bottom', 'base', pts, bb, bool(np.abs(bb).max() > 1.0),
                          np.arange(len(cols)), [])
            else:
                c = TFc[j0, cols]
                bt = Side('bottom', 'join', Q[0], c / 2, decide(c), np.arange(len(cols)),
                          ['%s-%d' % (profile.labels[g], k)])
            c = cr_l[rr]
            lf = Side('left', 'seam', Q[:, -1], c / 2, decide(c), rings[rr],
                      neighbours_on(ng_l, j0, j1))
            if rcut is not None:
                lf = _cut_side(lf, Q, rcut[-1], len(cols) - 1, j0)
            if j1 == R - 1:
                tp = Side('top', 'tip', Q[-1, ::-1], np.zeros(len(cols)), False,
                          np.arange(len(cols))[::-1], [])
            else:
                c = TFc[j1, cols][::-1]
                tp = Side('top', 'join', Q[-1, ::-1], c / 2, decide(c), np.arange(len(cols))[::-1],
                          ['%s-%d' % (profile.labels[g], k + 2)])
            c = cr_r[rr][::-1]
            rt = Side('right', 'seam', Q[::-1, 0], c / 2, decide(c), rings[rr][::-1],
                      neighbours_on(ng_r, j0, j1))
            if rcut is not None:
                rt = _cut_side(rt, Q, rcut[0], 0, j0, reverse=True)
            p.cut = rcut
            for s in (bt, lf, tp, rt):
                if not s.bevelled:
                    s.bevel = np.zeros_like(s.bevel)
                elif len(s.bevel) >= 5:
                    k5 = np.ones(5) / 5.0
                    s.bevel = np.convolve(np.pad(s.bevel, 2, mode='edge'), k5, mode='valid')
            p.sides = [bt, lf, tp, rt]
            panels.append(p)

    seg = float(np.linalg.norm(V[1:] - V[:-1], axis=2).mean())
    return Pattern(panels, warnings, seg, tick_every, R, M,
                   int(np.floor(base_cut_in.min())) if base_cut_in is not None else 0)


# ----------------------------------------------------- outline offsets

def fair(pts, max_shift=0.75, iters=30):
    """Take out point-to-point noise along an edge (Taubin smoothing, which
    doesn't shrink the curve), ends fixed, no point moved more than
    max_shift mm. Real bends are far larger than that and survive."""
    P0 = np.asarray(pts, float)
    if len(P0) < 4:
        return P0
    P = P0.copy()
    for _ in range(iters):
        for f in (0.5, -0.53):
            lap = 0.5 * (P[:-2] + P[2:]) - P[1:-1]
            P[1:-1] += f * lap
        d = P - P0
        n = np.linalg.norm(d, axis=1, keepdims=True)
        P = P0 + d * np.minimum(1.0, max_shift / np.maximum(n, 1e-12))
    return P


def smooth(pts, step=1.5):
    """Centripetal Catmull-Rom through pts, resampled about every `step`
    mm. Passes through every input point and never loops on sharp turns."""
    P = np.asarray(pts, float)
    if len(P) < 3:
        return P
    keep = np.concatenate([[True], np.linalg.norm(np.diff(P, axis=0), axis=1) > 1e-6])
    P = P[keep]
    if len(P) < 3:
        return P
    ext = np.vstack([2 * P[0] - P[1], P, 2 * P[-1] - P[-2]])
    out = [P[:1]]
    for i in range(len(P) - 1):
        p0, p1, p2, p3 = ext[i:i + 4]
        t0 = 0.0
        t1 = t0 + max(np.linalg.norm(p1 - p0), 1e-9) ** 0.5
        t2 = t1 + max(np.linalg.norm(p2 - p1), 1e-9) ** 0.5
        t3 = t2 + max(np.linalg.norm(p3 - p2), 1e-9) ** 0.5
        n = max(int(np.linalg.norm(p2 - p1) / step), 1)
        t = np.linspace(t1, t2, n + 1)[1:, None]
        a1 = (t1 - t) / (t1 - t0) * p0 + (t - t0) / (t1 - t0) * p1
        a2 = (t2 - t) / (t2 - t1) * p1 + (t - t1) / (t2 - t1) * p2
        a3 = (t3 - t) / (t3 - t2) * p2 + (t - t2) / (t3 - t2) * p3
        b1 = (t2 - t) / (t2 - t0) * a1 + (t - t0) / (t2 - t0) * a2
        b2 = (t3 - t) / (t3 - t1) * a2 + (t - t1) / (t3 - t1) * a3
        out.append((t2 - t) / (t2 - t1) * b1 + (t - t1) / (t2 - t1) * b2)
    return np.vstack(out)


def _signed_area(loop):
    x, y = loop[:, 0], loop[:, 1]
    return 0.5 * float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))


def _outward_normals(pts, ccw):
    d = np.gradient(pts, axis=0) if len(pts) > 2 else np.repeat(pts[1:2] - pts[0:1], len(pts), 0)
    d = _unit(d)
    if ccw:
        return np.stack([d[:, 1], -d[:, 0]], 1)
    return np.stack([-d[:, 1], d[:, 0]], 1)


def _intersect(p1, p2, p3, p4):
    d1 = p2 - p1
    d2 = p4 - p3
    den = d1[0] * d2[1] - d1[1] * d2[0]
    if abs(den) < 1e-9:
        return 0.5 * (p2 + p3)
    t = ((p3[0] - p1[0]) * d2[1] - (p3[1] - p1[1]) * d2[0]) / den
    return p1 + t * d1


def finish_outlines(panel, thickness, mirror=False):
    """Fill side.face / side.back: where the cut meets the shown face and the
    hidden face. Bevels pivot about the mid surface, so each face line moves
    by half the thickness times tan(bevel). mirror=True shows the back."""
    if mirror:
        flip = np.array([-1.0, 1.0])
        for s in panel.sides:
            s.pts = s.pts * flip
        panel.Q = panel.Q * flip
        panel.marks = [(t, pts * flip) for t, pts in panel.marks]
    loop = np.vstack([s.pts[:-1] for s in panel.sides])
    ccw = _signed_area(loop) > 0
    half = thickness / 2.0
    for s in panel.sides:          # remove flattening noise before offsetting
        s.pts = fair(s.pts)
    # local panel width at each ring, to keep bevel offsets from crossing
    Q = panel.Q
    width = np.linalg.norm(Q[:, 0] - Q[:, -1], axis=1)
    for s in panel.sides:
        n = _outward_normals(s.pts, ccw)
        o = half * np.tan(np.radians(s.bevel))
        if s.name in ('left', 'right'):
            if len(width) == len(o):
                lim = 0.2 * (width if s.name == 'left' else width[::-1])
            else:                     # shortened by a base cut
                lim = 0.2 * float(np.median(width))
            o = np.clip(o, -lim, lim)
        o = o[:, None]
        outer = s.pts + n * o
        inner = s.pts - n * o
        s.face, s.back = (inner, outer) if mirror else (outer, inner)
        s.offset = np.abs(o[:, 0])
    # join neighbouring offset lines at the corners, but only where the
    # meeting point is about as far as the offsets themselves (nearly parallel
    # edges would otherwise send it far along the edge)
    for attr in ('face', 'back'):
        k = len(panel.sides)
        for i in range(k):
            sa, sb = panel.sides[i], panel.sides[(i + 1) % k]
            a, b = getattr(sa, attr), getattr(sb, attr)
            if len(a) >= 2 and len(b) >= 2:
                x = _intersect(a[-2], a[-1], b[0], b[1])
                tol = 2.5 * max(sa.offset[-1], sb.offset[0]) + 0.3
                if np.linalg.norm(x - a[-1]) < tol and np.linalg.norm(x - b[0]) < tol:
                    a[-1] = x
                    b[0] = x


# ----------------------------------------------------------- mount ring

@dataclass
class RingShape:
    """Funnel-shaped mounting ring, a surface of revolution (optionally oval).
    Lengths in any one unit; heights are z of the top and bottom edges."""
    top_diameter: float = 0.40
    top_height: float = 1.00
    bottom_diameter: float = 0.80
    bottom_height: float = 0.80
    curve: float = 0.2            # + bulges outward, - dishes in (trumpet)
    depth_ratio: float = 1.0      # front-to-back / side-to-side
    gores: int = 8
    columns: int = 3
    ring_spacing: float = 0.02
    seam_angle: float = math.pi / 2   # first seam at the back (+Y)


def ring_profile(rs, v):
    """(radius, z) at v in [0,1], top edge to bottom edge."""
    v = np.asarray(v, float)
    rt, rb = rs.top_diameter / 2, rs.bottom_diameter / 2
    dr, dz = rb - rt, rs.bottom_height - rs.top_height
    L = math.hypot(dr, dz) or 1e-9
    nr, nz = -dz / L, dr / L          # away from the axis
    bow = rs.curve * 0.25 * L * np.sin(np.pi * v)
    return rt + v * dr + bow * nr, rs.top_height + v * dz + bow * nz


def _ellipse_angles(depth, n, start):
    """n angles around an ellipse (1, depth) at equal arc length."""
    th = np.linspace(0.0, 2 * np.pi, 4001)
    pts = np.stack([np.cos(th + start), depth * np.sin(th + start)], 1)
    cum = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(pts, axis=0), axis=1))])
    return start + np.interp(np.linspace(0, cum[-1], n + 1)[:-1], cum, th)


def ring_profile_object(rs):
    """Profile stand-in so build_pattern can split the ring into gores."""
    M = rs.gores * rs.columns
    th = _ellipse_angles(rs.depth_ratio, M, rs.seam_angle)
    U = np.stack([np.cos(th), rs.depth_ratio * np.sin(th)], 1)
    labels = ['M%d' % (i + 1) for i in range(rs.gores)]
    return Profile(U, U.copy(), [i * rs.columns for i in range(rs.gores)], [rs.columns] * rs.gores,
                   labels, [False] * rs.gores), th


def ring_surface(rs, offset=0.0):
    """(R,M,3) grid: rows run down the profile, columns around (CCW from
    above, so outward normals match the tentacle grids). offset > 0 moves
    the surface inward along its normals."""
    vv = np.linspace(0.0, 1.0, 2001)
    r, z = ring_profile(rs, vv)
    cum = np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(r), np.diff(z)))])
    R = max(int(math.ceil(cum[-1] / max(rs.ring_spacing, 1e-6))), 4) + 1
    v = np.interp(np.linspace(0.0, cum[-1], R), cum, vv)
    r, z = ring_profile(rs, v)
    _, th = ring_profile_object(rs)
    V = np.stack([r[:, None] * np.cos(th)[None], r[:, None] * rs.depth_ratio * np.sin(th)[None],
                  np.repeat(z[:, None], len(th), 1)], -1)
    if offset:
        V = V - grid_normals(V) * offset
    return V, v


def grid_normals(V):
    """Outward vertex normals of a (R,M,3) grid that wraps around in M."""
    dj = np.gradient(V, axis=0)
    dc = (np.roll(V, -1, axis=1) - np.roll(V, 1, axis=1)) / 2
    return _unit(np.cross(dj, dc))


def ring_frame(rs, theta, v, eps=1e-4):
    """Point, down-the-profile tangent and outward normal at (theta, v)."""
    def S(t, w):
        r, z = ring_profile(rs, w)
        return np.array([float(r) * math.cos(t), float(r) * rs.depth_ratio * math.sin(t), float(z)])
    p = S(theta, v)
    tv = _unit(S(theta, min(v + eps, 1)) - S(theta, max(v - eps, 0)))
    tt = _unit(S(theta + eps, v) - S(theta - eps, v))
    n = _unit(np.cross(tv, tt))
    return p, tv, n


# ------------------------------------------------ points onto panels

def _bilinear(c00, c10, c01, c11, s, t):
    return c00 * (1 - s) * (1 - t) + c10 * s * (1 - t) + c01 * (1 - s) * t + c11 * s * t


def locate_on_grid(V, P):
    """For each point, (j, c, s, t): the grid quad (rows j..j+1, columns
    c..c+1 wrapping) and bilinear coordinates of its closest point."""
    R, M, _ = V.shape
    flat = V.reshape(-1, 3)
    out = []
    for p in np.asarray(P, float):
        k = int(np.argmin(((flat - p) ** 2).sum(1)))
        j0, c0 = divmod(k, M)
        best = None
        for j in (j0 - 1, j0):
            if j < 0 or j > R - 2:
                continue
            for c in (c0 - 1, c0):
                c %= M
                c1 = (c + 1) % M
                q = (V[j, c], V[j, c1], V[j + 1, c], V[j + 1, c1])
                s = t = 0.5
                for _ in range(8):
                    B = _bilinear(*q, s, t)
                    ds = (q[1] - q[0]) * (1 - t) + (q[3] - q[2]) * t
                    dt = (q[2] - q[0]) * (1 - s) + (q[3] - q[1]) * s
                    Jm = np.stack([ds, dt], 1)
                    step, *_ = np.linalg.lstsq(Jm, p - B, rcond=None)
                    s, t = s + step[0], t + step[1]
                s, t = float(np.clip(s, 0, 1)), float(np.clip(t, 0, 1))
                err = float(np.linalg.norm(_bilinear(*q, s, t) - p))
                if best is None or err < best[0]:
                    best = (err, j, c, s, t)
        out.append(best[1:])
    return out


def add_marks(pattern, profile, V, label, P):
    """Draw a closed 3D outline (e.g. a tentacle base on the mount ring)
    onto whichever panels it falls on."""
    M = V.shape[1]
    loc = locate_on_grid(V, P)
    owner = []
    for (j, c, s, t) in loc:
        hit = None
        for pn in pattern.panels:
            cols = list(pn.cols)
            if pn.j0 <= j < pn.j1 and c in cols[:-1]:
                ci = cols.index(c)
                Q = pn.Q
                jr = j - pn.j0
                hit = (pn, _bilinear(Q[jr, ci], Q[jr, ci + 1], Q[jr + 1, ci], Q[jr + 1, ci + 1], s, t))
                break
        owner.append(hit)
    # split the closed loop into runs that stay on one panel
    n = len(owner)
    start = next((i for i in range(n) if owner[i] is None or owner[i][0] is not owner[i - 1][0]), 0)
    runs, cur, cur_p = [], [], None
    for k in range(n + 1):
        h = owner[(start + k) % n]
        pn = h[0] if h else None
        if pn is not cur_p and cur:
            runs.append((cur_p, cur))
            cur = []
        cur_p = pn
        if h:
            cur.append(h[1])
    if cur:
        runs.append((cur_p, cur))
    if len(runs) == 1 and len(runs[0][1]) == n:          # wholly on one panel: close it
        runs[0][1].append(runs[0][1][0])
    for pn, pts in runs:
        if pn is not None and len(pts) >= 2:
            pn.marks.append((label, np.array(pts)))
