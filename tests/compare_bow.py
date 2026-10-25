import numpy as np
from curl_fixture import curled, G
from eva_tentacle import pattern_pdf as PP
shape = G.Shape(length=1300, base_radius=100, tip_radius=12.5, ring_spacing=20, bottom_gores=2, bottom_columns=2)
prof = G.make_profile(shape)
for curl in (200, 330):
    j, u = curled(curl=curl)
    sw = G.sweep(shape, prof, j, u, offset=5.0)
    for bowmm in (0, 80, 50, 30):
        st = G.Settings(max_bow=bowmm)
        pat = G.build_pattern(sw.V, prof, st)
        for p in pat.panels: G.finish_outlines(p, 10)
        mats = PP._pack_mats(pat.panels, st.mat_w - 2*st.margin, st.mat_h - 2*st.margin)
        bows = [G.bow(p.Q) for p in pat.panels]
        area = sum(abs(G._signed_area(np.vstack([s.face[:-1] for s in p.sides]))) for p in pat.panels)
        print('curl %3d max_bow %3d: panels %2d  mats %d  worst bow %4.0f mm  fill %.0f%%' % (
            curl, bowmm, len(pat.panels), len(mats), max(bows), 100*area/(len(mats)*st.mat_w*st.mat_h)))
