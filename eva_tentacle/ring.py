"""Funnel-shaped EVA mount ring that the tentacle bases are glued to."""

import os
import re

import bpy
import numpy as np

from . import geometry as G
from . import rig

RING_RGB = (0.42, 0.33, 0.48)


def is_ring(ob):
    return ob is not None and ob.type == 'MESH' and ob.eva_ring.is_ring


def find_ring(ob):
    if is_ring(ob):
        return ob
    t = rig.find_tentacle(ob)
    if t is not None and is_ring(t.eva_tentacle.mount_ring):
        return t.eva_tentacle.mount_ring
    return None


def all_rings(scene):
    return [o for o in scene.objects if is_ring(o)]


def shape_of(p):
    return G.RingShape(top_diameter=p.top_diameter, top_height=p.top_height,
                       bottom_diameter=p.bottom_diameter, bottom_height=p.bottom_height,
                       curve=p.curve, depth_ratio=p.depth_ratio, gores=p.gores, columns=p.columns,
                       ring_spacing=p.ring_spacing, seam_angle=p.seam_angle)


def mounted(ring_ob, scene=None):
    scene = scene or bpy.context.scene
    return [t for t in rig.all_tentacles(scene) if t.eva_tentacle.mount_ring == ring_ob]


def build_mesh(ring_ob):
    rs = shape_of(ring_ob.eva_ring)
    V, _ = G.ring_surface(rs)
    R, M = V.shape[:2]
    me = ring_ob.data
    me.clear_geometry()
    me.from_pydata(V.reshape(-1, 3).tolist(), [], G.grid_faces(R, M))
    me.polygons.foreach_set('use_smooth', np.ones(len(me.polygons), bool))
    rig._colour_faces(me, np.tile(RING_RGB, ((R - 1) * M, 1)))
    me.update()
    rig.schedule_panels(ring_ob)


def rebuild(ring_ob):
    build_mesh(ring_ob)
    for t in mounted(ring_ob):
        rig.place_on_ring(t)


def create_ring(context, location=(0, 0, 0)):
    me = bpy.data.meshes.new('Mount Ring')
    ob = bpy.data.objects.new('Mount Ring', me)
    context.collection.objects.link(ob)
    ob.location = (location[0], location[1], 0.0)
    me.materials.append(rig._material())
    ob.eva_ring.is_ring = True
    build_mesh(ob)
    return ob


def pattern_for(ring_ob, scene, settings=None):
    ex = scene.eva_tentacle_export
    rp = ring_ob.eva_ring
    to_mm = scene.unit_settings.scale_length * 1000.0
    rs = shape_of(rp)
    scale = float(np.mean(ring_ob.matrix_world.to_scale()))
    off = ex.thickness / 2 / max(scale, 1e-9) if ex.model_surface == 'OUTER' else 0.0
    V, _ = G.ring_surface(rs, offset=off)
    mw = np.array(ring_ob.matrix_world)
    Vw = (V.reshape(-1, 3) @ mw[:3, :3].T + mw[:3, 3]).reshape(V.shape) * to_mm
    prof, th = G.ring_profile_object(rs)
    st = rig.export_settings(scene)
    for k, v in (settings or {}).items():
        setattr(st, k, v)
    pat = G.build_pattern(Vw, prof, st)

    # where each tentacle's base sits, traced onto the ring panels
    dg = bpy.context.evaluated_depsgraph_get()
    placed = []
    for t in mounted(ring_ob, scene):
        base = rig.base_outline_world(t, dg) * to_mm
        G.add_marks(pat, prof, Vw, '%s base' % t.eva_tentacle.code, base)
        placed.append(t.eva_tentacle.code)
    for pn in pat.panels:
        G.finish_outlines(pn, st.thickness, ex.mirror)

    k = scale * to_mm
    top = np.stack([np.cos(th), rs.depth_ratio * np.sin(th)], 1)
    rt, rb = rs.top_diameter / 2 * k, rs.bottom_diameter / 2 * k
    slant = float(np.linalg.norm(Vw[-1] - Vw[0], axis=1).mean())
    meta = dict(
        code=rp.code, name=ring_ob.name, labels=prof.labels, is_bottom=prof.is_bottom,
        gore_start=prof.gore_start, tick_every=pat.tick_every, mirror=ex.mirror, page_mode=ex.page_mode,
        print_layout=ex.print_layout,
        thickness=st.thickness, mat_w=st.mat_w, mat_h=st.mat_h, margin=st.margin, max_bow=st.max_bow,
        warnings=pat.warnings,
        kind_title='EVA foam mount ring pattern',
        params=[
            ('Top width / height', '%.0f mm at %.0f mm' % (rs.top_diameter * k, rs.top_height * k)),
            ('Bottom width / height', '%.0f mm at %.0f mm' % (rs.bottom_diameter * k, rs.bottom_height * k)),
            ('Profile curve', '%+.2f' % rs.curve),
            ('Front-back / side', '%.2f' % rs.depth_ratio),
            ('Slant length', '%.0f mm' % slant),
            ('Panels around', '%d' % rs.gores),
            ('EVA thickness', '%.1f mm' % st.thickness),
            ('Mat size (margin)', '%.0f \xd7 %.0f mm (%.0f)' % (st.mat_w, st.mat_h, st.margin)),
            ('Tentacles marked', ', '.join(placed) or 'none'),
        ],
        section_title='Top view: bottom edge (solid), top edge (dashed); front is down',
        section_note='front of the costume',
        section_outer=top * rb, section_mid=top * rt, section_flip=False,
        gore_kind=['ring'] * rs.gores,
        start_edge='TOP EDGE (waist)', end_edge='BOTTOM EDGE (rests on the hoop skirt)',
        end_word='DOWN',
        map_note='top edge on the left, bottom edge on the right',
        steps=[
            'Join the pieces of each ring panel top to bottom first (join ticks a, b, c line up).',
            'Glue the panels side by side into a funnel, matching seam ticks: M1/M2-3 meets M1/M2-3 ...',
            'Dash-dot outlines show where each tentacle base is glued; transfer them to the foam.',
        ])
    return pat, prof, meta


def pdf_path(ring_ob, scene):
    path = rig.pdf_path(ring_ob, scene, ring_ob.eva_ring.code)
    return path
