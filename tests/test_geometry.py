import time, numpy as np
from curl_fixture import curled, G

shape = G.Shape(length=1300, base_radius=100, tip_radius=12.5, ring_spacing=20)
prof = G.make_profile(shape)
for name, (j, u) in {'straight': curled(curl=0, twist=0), 'curled': curled()}.items():
    t = time.time()
    sw = G.sweep(shape, prof, j, u, offset=5.0)
    pat = G.build_pattern(sw.V, prof, G.Settings())
    print(name, 'R,M', sw.V.shape[:2], 'arc', round(sw.line.total), 'bend', G.tightest_bend(sw, shape),
          'time %.2fs' % (time.time() - t))
    for p in pat.panels:
        G.finish_outlines(p, 10.0)
        print('  %-5s rings %3d-%3d len %6.1f fit %s %4.0fx%4.0f strain %.2f%%  bevels %s' % (
            p.label, p.j0, p.j1, p.length, p.fits, p.w, p.h, p.strain * 100,
            ' '.join('%s:%s%.0f' % (s.name[0], 'B' if s.bevelled else 'sq', np.abs(s.bevel).max()) for s in p.sides)))
    print('  warnings', pat.warnings)
# straight panel length check: flattened mid column length vs 3D
p = pat.panels[0]
