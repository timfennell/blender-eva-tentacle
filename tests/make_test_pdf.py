"""Build a pattern PDF from the synthetic curl fixture (no Blender)."""
import sys, numpy as np
from curl_fixture import curled, G
from eva_tentacle import pattern_pdf

def meta_for(shape, prof, sw_outer, sw_mid, pat, st, mode='LETTER', mirror=False):
    return dict(code='T1', name='Tentacle', labels=prof.labels, is_bottom=prof.is_bottom,
                gore_start=prof.gore_start, tick_every=pat.tick_every, mirror=mirror, page_mode=mode,
                thickness=st.thickness, length=shape.length, base_d=2*shape.base_radius, tip_d=2*shape.tip_radius,
                height_ratio=shape.height_ratio, bottom_roundness=shape.bottom_roundness,
                top_gores=shape.top_gores, bottom_gores=shape.bottom_gores, mat_w=st.mat_w, mat_h=st.mat_h,
                margin=st.margin, max_bow=st.max_bow, seam_desc='auto (bevel creases > %.0f\xb0)' % st.crease_deg,
                bend_desc='ok', warnings=pat.warnings,
                section_outer=prof.U*np.array([shape.base_radius]*1), section_mid=prof.U*shape.base_radius*0.95)

if __name__ == '__main__':
    out = sys.argv[1]
    shape = G.Shape(length=1300, base_radius=100, tip_radius=12.5, ring_spacing=20, bottom_gores=2, bottom_columns=2)
    prof = G.make_profile(shape)
    j, u = curled(curl=330)
    sw = G.sweep(shape, prof, j, u, offset=5.0)
    st = G.Settings()
    pat = G.build_pattern(sw.V, prof, st)
    for p in pat.panels: G.finish_outlines(p, st.thickness)
    from eva_tentacle import pattern_pdf as PP
    doc, sheets = PP.write_pdf(out, pat, meta_for(shape, prof, sw, sw, pat, st, mode=sys.argv[2] if len(sys.argv) > 2 else 'LETTER'))
    print('pages', len(doc.pages), 'sheets', sheets)
    if len(sys.argv) > 3:   # split pages for previewing
        import os
        from eva_tentacle.pdfgen import Document
        for i in [int(x) for x in sys.argv[4].split(',')] if len(sys.argv) > 4 else range(len(doc.pages)):
            d = Document(); d.pages = [doc.pages[i]]; d.save(os.path.join(sys.argv[3], 'p%02d.pdf' % i))
    print(pat.warnings)
