"""Base trimming against a mount ring, without Blender."""
import math, numpy as np
from curl_fixture import curled, G

rs = G.RingShape(top_diameter=400, top_height=1000, bottom_diameter=820, bottom_height=780, curve=0.38,
                 depth_ratio=0.82, ring_spacing=20)
f = G.ring_inside(rs)
shape = G.Shape(length=1200, base_radius=100, tip_radius=12.5, ring_spacing=20)
prof = G.make_profile(shape)
j, u = curled(n=12, length=1200, curl=200)
for emerge_deg in (20, 35, 60):
    pt, tv, n = G.ring_frame(rs, 0.4, 0.55)
    e = math.radians(emerge_deg)
    Y = math.cos(e) * tv + math.sin(e) * n
    Z = -math.sin(e) * tv + math.cos(e) * n
    X = np.cross(Y, Z)
    Rm = np.stack([X, Y, Z], 1)                        # tentacle local -> ring local
    to_ring = lambda q: q @ Rm.T + pt
    trim = lambda q: f(to_ring(q))
    sw = G.sweep(shape, prof, j, u, trim=trim)
    base = to_ring(sw.V[0])
    on = np.abs(f(base))
    rest = f(to_ring(sw.V[3:].reshape(-1, 3)))
    pat = G.build_pattern(sw.V_ext, prof, G.Settings(), base_bevel=sw.base_bevel, base_cut=sw.base_cut)
    # the flattened base edge must be as long as the 3D cut line, per gore
    for p in pat.panels:
        if p.j0 == 0:
            G.finish_outlines(p, 10)
            L2 = np.linalg.norm(np.diff(p.sides[0].pts, axis=0), axis=1).sum()
            L3 = np.linalg.norm(np.diff(sw.V[0][p.cols], axis=0), axis=1).sum()
            assert abs(L2 / L3 - 1) < 0.03, (p.label, L2, L3)
    bev = [ (p.label, round(float(np.abs(p.sides[0].bevel).max()))) for p in pat.panels if p.j0 == 0]
    print('lift %2d deg: base edge off the ring max %.2f mm; skin inside ring after row 3: %d pts; '
          'base bevels %s; worst stretch %.1f%%' % (emerge_deg, on.max(), (rest < -1).sum(), bev,
          100 * max(p.strain for p in pat.panels)))
