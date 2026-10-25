"""Armature chain, IK target and the swept foam skin."""

import colorsys
import math
import os
import re
import time

import bpy
import numpy as np
from bpy.app.handlers import persistent
from mathutils import Matrix, Quaternion, Vector

from . import geometry as G

BONE = 'seg.%02d'
TOP_RGB = (0.28, 0.07, 0.36)
BOTTOM_RGB = (0.78, 0.55, 0.82)


# ------------------------------------------------------------- lookup

def is_tentacle(ob):
    return ob is not None and ob.type == 'ARMATURE' and ob.eva_tentacle.is_tentacle


def find_tentacle(ob):
    if ob is None:
        return None
    if is_tentacle(ob):
        return ob
    if ob.parent is not None and is_tentacle(ob.parent):
        return ob.parent
    return None


def all_tentacles(scene):
    return [o for o in scene.objects if is_tentacle(o)]


def chain(arm):
    names = [BONE % i for i in range(arm.eva_tentacle.bone_count)]
    return [arm.pose.bones[n] for n in names if n in arm.pose.bones]


def shape_of(props):
    return G.Shape(
        length=props.length, base_radius=props.base_diameter / 2, tip_radius=props.tip_diameter / 2,
        taper_power=props.taper_power, bulge=props.bulge, flare=props.flare,
        flare_length=props.flare_length, height_ratio=props.height_ratio,
        bottom_roundness=props.bottom_roundness, top_gores=props.top_gores,
        bottom_gores=props.bottom_gores, top_columns=props.top_columns,
        bottom_columns=props.bottom_columns, ring_spacing=props.ring_spacing,
        adapt=1.5 if props.adaptive_rings else 0.0)


def pose_arrays(arm, depsgraph=None):
    """Joint positions and bone Z axes in armature space. While IK is on,
    the IK handles' twist is added on top (IK itself only places bones)."""
    ob = arm.evaluated_get(depsgraph) if depsgraph is not None else arm
    pbs = [ob.pose.bones[pb.name] for pb in chain(arm)]
    joints = [tuple(pb.head) for pb in pbs] + [tuple(pbs[-1].tail)]
    ups = np.array([tuple(pb.matrix.col[2].xyz) for pb in pbs])
    if arm.eva_tentacle.use_ik:
        tw = bone_twists(arm, depsgraph)
        ys = np.array([tuple(pb.matrix.col[1].xyz) for pb in pbs])
        xs = np.cross(ys, ups)
        ups = ups * np.cos(tw)[:, None] + xs * np.sin(tw)[:, None]
    return np.array(joints), ups


_twist_prev = {}


def handle_twists(arm, depsgraph=None):
    """[(segment end bone, twist radians)] for each IK handle: how far the
    handle is rolled around the bone it pulls. Unwrapped against the last
    reading so several full turns keep counting."""
    dg = depsgraph or bpy.context.evaluated_depsgraph_get()
    ev = arm.evaluated_get(dg)
    inv = ev.matrix_world.to_3x3().inverted()
    targets = ik_targets(arm)
    ends = segment_ends(len(chain(arm)), len(targets) - 1)
    out = []
    for tgt, end in zip(targets, ends):
        if tgt is None:
            continue
        m = ev.pose.bones[BONE % end].matrix
        y = np.array(m.col[1].xyz)
        z = np.array(m.col[2].xyz)
        # swing-twist: turn the handle's Y onto the bone by the shortest arc,
        # then its Z vs the bone's Z is the pure twist (dragging doesn't add any)
        tm = inv @ tgt.evaluated_get(dg).matrix_world.to_3x3()
        hy, hz = tm.col[1].normalized(), tm.col[2].normalized()
        swing = hy.rotation_difference(Vector(y))
        e = np.array(swing @ hz)
        e = e - e.dot(y) * y
        if np.linalg.norm(e) < 1e-6:
            continue
        a = math.atan2(np.cross(z, e).dot(y), z.dot(e))
        key = tgt.session_uid
        prev = _twist_prev.get(key, 0.0)
        a += 2 * math.pi * round((prev - a) / (2 * math.pi))
        _twist_prev[key] = a
        out.append((end, a))
    return out


def bone_twists(arm, depsgraph=None):
    """Twist per bone, blended from the base (0) through each handle."""
    n = len(chain(arm))
    pts = handle_twists(arm, depsgraph)
    xs = [0.0] + [e + 1.0 for e, _ in pts]
    ts = [0.0] + [a for _, a in pts]
    return np.interp(np.arange(n) + 0.5, xs, ts)


# --------------------------------------------------------------- rig

class _ModeGuard:
    """Switch to object mode with `arm` active, restore afterwards."""

    def __init__(self, arm):
        self.arm = arm

    def __enter__(self):
        ctx = bpy.context
        self.vl = ctx.view_layer
        self.prev_active = self.vl.objects.active
        self.prev_mode = self.prev_active.mode if self.prev_active else 'OBJECT'
        if self.prev_active and self.prev_mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        self.vl.objects.active = self.arm
        return self

    def __exit__(self, *exc):
        if bpy.context.object and bpy.context.object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        self.vl.objects.active = self.prev_active
        if self.prev_active and self.prev_mode != 'OBJECT':
            try:
                bpy.ops.object.mode_set(mode=self.prev_mode)
            except RuntimeError:
                pass
        return False


def set_rest_chain(arm):
    """Straight chain along local +Y, Z up (suckers on -Z). Keeps the pose
    of bones that survive a bone-count change."""
    p = arm.eva_tentacle
    if arm.mode == 'EDIT':
        return
    n = p.bone_count
    seg = p.length / n
    names = [BONE % i for i in range(n)]
    with _ModeGuard(arm):
        bpy.ops.object.mode_set(mode='EDIT')
        eb = arm.data.edit_bones
        for b in list(eb):
            if b.name not in names:
                eb.remove(b)
        prev = None
        for i, nm in enumerate(names):
            b = eb.get(nm) or eb.new(nm)
            b.head = (0.0, i * seg, 0.0)
            b.tail = (0.0, (i + 1) * seg, 0.0)
            b.roll = 0.0
            b.parent = prev
            b.use_connect = prev is not None
            prev = b
        bpy.ops.object.mode_set(mode='OBJECT')


def tip_world(arm):
    dg = bpy.context.evaluated_depsgraph_get()
    ev = arm.evaluated_get(dg)
    last = BONE % (arm.eva_tentacle.bone_count - 1)
    return ev.matrix_world @ ev.pose.bones[last].tail


def segment_ends(n, k):
    """Last bone of each IK segment: k mid-length controls, then the tip."""
    ends = sorted({max(0, min(n - 2, int(round(n * (i + 1) / (k + 1))) - 1)) for i in range(k)})
    return ends + [n - 1]


def ik_targets(arm):
    p = arm.eva_tentacle
    return [c.obj for c in p.controls] + [p.ik_target]


def ik_constraints(arm):
    return [c for pb in chain(arm) for c in pb.constraints if c.type == 'IK']


def ensure_ik(arm):
    """One IK segment per control point plus the tip, each pulling the end
    of its stretch of bones to its target."""
    p = arm.eva_tentacle
    pbs = chain(arm)
    for pb in pbs:
        for c in [c for c in pb.constraints if c.type == 'IK']:
            pb.constraints.remove(c)
    targets = ik_targets(arm)
    ends = segment_ends(len(pbs), len(targets) - 1)
    prev = -1
    for i, (end, tgt) in enumerate(zip(ends, targets)):
        con = pbs[end].constraints.new('IK')
        con.name = 'Tentacle IK' if i == len(ends) - 1 else 'Control %d IK' % (i + 1)
        con.target = tgt
        con.chain_count = end - prev
        con.use_tail = True
        con.mute = not p.use_ik
        if i == len(ends) - 1 and p.aim_tip:          # tip handle also sets the direction
            con.use_rotation = True
            con.orient_weight = max(p.aim_strength, 0.001)
            if tgt is not None:
                tgt.empty_display_type = 'CONE'
        prev = end


def capture_pose(arm, depsgraph=None):
    """World matrix of every bone, moved to its tail (where a handle sits)."""
    dg = depsgraph or bpy.context.evaluated_depsgraph_get()
    ev = arm.evaluated_get(dg)
    out = {}
    for pb in ev.pose.bones:
        m = ev.matrix_world @ pb.matrix
        m.translation = ev.matrix_world @ pb.tail
        out[pb.name] = m
    return out


def snap_target(arm, depsgraph=None, exclude=(), pose=None):
    """Move the tip target and every control onto the pose (the current one,
    or one captured earlier), lined up with their bones (zero twist)."""
    pose = pose or capture_pose(arm, depsgraph)
    targets = ik_targets(arm)
    ends = segment_ends(len(chain(arm)), len(targets) - 1)
    for tgt, end in zip(targets, ends):
        if tgt is not None and tgt not in exclude and BONE % end in pose:
            m = pose[BONE % end].copy()
            sc = tgt.matrix_world.to_scale()
            tgt.matrix_world = m.normalized() @ Matrix.Diagonal((*sc, 1.0))
            _twist_prev[tgt.session_uid] = 0.0


def sync_controls(arm):
    """Add or remove control empties to match control_count, keeping the
    pose the tentacle has now."""
    p = arm.eva_tentacle
    pose = capture_pose(arm)
    while len(p.controls) > p.control_count:
        ob = p.controls[-1].obj
        p.controls.remove(len(p.controls) - 1)
        if ob is not None:
            bpy.data.objects.remove(ob)
    coll = arm.users_collection[0] if arm.users_collection else bpy.context.collection
    while len(p.controls) < p.control_count:
        e = bpy.data.objects.new('%s_ctrl%d' % (arm.name, len(p.controls) + 1), None)
        coll.objects.link(e)
        e.empty_display_type = 'ARROWS'
        e.empty_display_size = max(p.base_diameter * 0.6, 0.02)
        e.parent = arm
        p.controls.add().obj = e
    snap_target(arm, pose=pose)      # handles first, so the new IK segments start satisfied
    ensure_ik(arm)


def set_ik(arm, on):
    if on:
        snap_target(arm)
    for con in ik_constraints(arm):
        con.mute = not on


def _material():
    mat = bpy.data.materials.get('EVA Tentacle')
    if mat is None:
        mat = bpy.data.materials.new('EVA Tentacle')
        mat.use_nodes = True
        nt = mat.node_tree
        bsdf = next(n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED')
        attr = nt.nodes.new('ShaderNodeVertexColor')
        attr.layer_name = 'Panels'
        attr.location = (-300, 200)
        nt.links.new(attr.outputs['Color'], bsdf.inputs['Base Color'])
        bsdf.inputs['Roughness'].default_value = 0.65
        mat.diffuse_color = (*TOP_RGB, 1.0)
    return mat


def next_code(scene):
    used = {o.eva_tentacle.code for o in all_tentacles(scene)}
    i = 1
    while 'T%d' % i in used:
        i += 1
    return 'T%d' % i


def create_tentacle(context, name='Tentacle', location=(0, 0, 0), angle_z=0.0, controls=0, **shape):
    scene = context.scene
    data = bpy.data.armatures.new(name + '_bones')
    data.display_type = 'OCTAHEDRAL'
    arm = bpy.data.objects.new(name, data)
    context.collection.objects.link(arm)
    arm.location = location
    arm.rotation_euler = (0.0, 0.0, angle_z)
    arm.show_in_front = True
    p = arm.eva_tentacle
    p.code = next_code(scene)
    for k, v in shape.items():
        setattr(p, k, v)
    p.is_tentacle = True

    set_rest_chain(arm)

    me = bpy.data.meshes.new(name + '_skin')
    skin = bpy.data.objects.new(name + '_skin', me)
    context.collection.objects.link(skin)
    skin.parent = arm
    skin.data.materials.append(_material())
    p.mesh_obj = skin

    tgt = bpy.data.objects.new(name + '_IK', None)
    context.collection.objects.link(tgt)
    tgt.empty_display_type = 'SPHERE'
    tgt.empty_display_size = max(p.base_diameter * 0.35, 0.01)
    tgt.parent = arm
    tgt.location = (0.0, p.length, 0.0)
    p.ik_target = tgt

    p.control_count = controls
    sync_controls(arm)
    build_mesh(arm)
    return arm


def place_on_ring(arm):
    """Stand the tentacle's base on its mount ring: running down the funnel,
    tilted out by the emerge angle, suction side toward the ring."""
    from . import ring as RG
    p = arm.eva_tentacle
    ring_ob = p.mount_ring
    if ring_ob is None or not RG.is_ring(ring_ob):
        return
    rs = RG.shape_of(ring_ob.eva_ring)
    pt, tv, n = G.ring_frame(rs, p.mount_angle, p.mount_height)
    e = p.emerge
    Y = math.cos(e) * tv + math.sin(e) * n
    Z = -math.sin(e) * tv + math.cos(e) * n
    X = np.cross(Y, Z)
    m = Matrix.Identity(4)
    for i in range(3):
        m[i][0], m[i][1], m[i][2], m[i][3] = X[i], Y[i], Z[i], pt[i]   # root on the ring skin
    if arm.parent is not ring_ob:
        arm.parent = ring_ob
    arm.matrix_parent_inverse = Matrix.Identity(4)
    arm.matrix_basis = m
    build_mesh(arm)


def ring_trim(arm):
    """Trim function in the tentacle's own space for the ring it is
    mounted on, or None."""
    from . import ring as RG
    ring_ob = arm.eva_tentacle.mount_ring
    if ring_ob is None or not RG.is_ring(ring_ob):
        return None
    f = G.ring_inside(RG.shape_of(ring_ob.eva_ring))
    m = np.array(ring_ob.matrix_world.inverted() @ arm.matrix_world)
    return lambda pts: f(pts @ m[:3, :3].T + m[:3, 3])


# -------------------------------------------------------------- skin

def _colour_faces(me, rgb_per_face):
    """One colour per quad face. Returns False (and leaves the mesh alone) when the
    mesh doesn't have that many quads, e.g. a skin not yet rebuilt for new settings."""
    if len(me.polygons) != len(rgb_per_face) or len(me.loops) != 4 * len(rgb_per_face):
        return False
    if 'Panels' not in me.color_attributes:
        me.color_attributes.new('Panels', 'BYTE_COLOR', 'CORNER')
    attr = me.color_attributes['Panels']
    me.color_attributes.active_color = attr
    rgba = np.concatenate([np.asarray(rgb_per_face, float), np.ones((len(rgb_per_face), 1))], 1)
    corner = np.repeat(rgba, 4, axis=0)
    attr.data.foreach_set('color', corner.ravel().astype(np.float32))
    return True


def default_colours(prof, R):
    M = prof.M
    col_bottom = np.zeros(M, bool)
    for g in range(len(prof.gore_start)):
        if prof.is_bottom[g]:
            col_bottom[(prof.gore_start[g] + np.arange(prof.gore_cols[g])) % M] = True
    rgb = np.where(col_bottom[:, None], BOTTOM_RGB, TOP_RGB)
    return np.tile(rgb, (R - 1, 1))


def _fabric_attributes(me, sw, prof):
    """Corner attributes the Ursula fabric material reads (see material.py)."""
    fab, under = G.fabric_coords(sw.V, sw.radii, prof)
    for name, data in (('eva_fabric', fab), ('eva_under', under)):
        a = me.attributes.get(name)
        if a is None or a.domain != 'CORNER' or len(a.data) != len(data):
            if a is not None:
                me.attributes.remove(a)
            a = me.attributes.new(name, 'FLOAT_VECTOR', 'CORNER')
        a.data.foreach_set('vector', data.ravel())


def build_mesh(arm, depsgraph=None):
    p = arm.eva_tentacle
    skin = p.mesh_obj
    if skin is None or len(chain(arm)) < 2 or rendering():
        return
    shape = shape_of(p)
    prof = G.make_profile(shape)
    joints, ups = pose_arrays(arm, depsgraph)
    sw = G.sweep(shape, prof, joints, ups, trim=ring_trim(arm))
    R, M = sw.V.shape[:2]
    me = skin.data
    flat = sw.V.reshape(-1, 3).astype(np.float32).ravel()
    if len(me.vertices) != R * M or me.get('eva_M') != M:
        me.clear_geometry()
        me.from_pydata(sw.V.reshape(-1, 3).tolist(), [], G.grid_faces(R, M))
        me.polygons.foreach_set('use_smooth', np.ones(len(me.polygons), bool))
        me['eva_M'] = M
        _colour_faces(me, default_colours(prof, R))
    else:
        me.vertices.foreach_set('co', flat)
    _fabric_attributes(me, sw, prof)
    me.update()
    ratio, at = G.tightest_bend(sw, shape)
    if abs(ratio - p.bend_ratio) > 1e-3 * max(abs(ratio), 1.0):
        p.bend_ratio = min(ratio, 1e9)
        p.bend_at = at
    schedule_panels(arm)


# ------------------------------------------------- live panel preview

_panel_queue = {}
_panel_time = [0.0]
_shading_set = [False]


def schedule_panels(ob):
    """Re-colour ob's panels shortly after editing stops (a full split and
    flatten is too slow to run on every drag)."""
    scene = bpy.context.scene
    if bpy.app.background or not getattr(scene, 'eva_tentacle_export', None) \
            or not scene.eva_tentacle_export.live_panels:
        return
    _panel_queue[ob.name] = True
    _panel_time[0] = time.time()
    if not bpy.app.timers.is_registered(_panel_timer):
        bpy.app.timers.register(_panel_timer, first_interval=0.6)


def rendering():
    """True while Blender renders: the render engine (Cycles inside Spirula too)
    is reading the meshes, so nothing here may touch them."""
    # Ask Blender itself: a flag set by render handlers can stay stuck if a render dies
    # without its complete/cancel handler running, and then nothing would ever rebuild.
    return bpy.app.is_job_running('RENDER')


def _panel_timer():
    if rendering():
        return 1.0                      # try again once the render is done
    if time.time() - _panel_time[0] < 0.5:
        return 0.25
    if not _panel_queue:
        return None
    name = next(iter(_panel_queue))
    _panel_queue.pop(name)
    ob = bpy.data.objects.get(name)
    try:
        if ob is not None:
            colour_live(ob)
    except Exception as e:          # never let a bad pose kill the timer
        print('EVA live panels:', e)
    return 0.05 if _panel_queue else None


def colour_live(ob):
    from . import ring as RG
    if rendering():
        return
    scene = bpy.context.scene
    if RG.is_ring(ob):
        pat, prof, _ = RG.pattern_for(ob, scene)
    elif is_tentacle(ob):
        pat, prof, _ = pattern_for(ob, scene)
    else:
        return
    colour_panels(ob, pat, prof, getattr(pat, 'extra_rows', 0))
    show_panel_colours()


def show_panel_colours():
    """Once per session, switch solid views to attribute colours so the
    panel colours show."""
    if _shading_set[0]:
        return
    _shading_set[0] = True
    for win in bpy.context.window_manager.windows:
        for area in win.screen.areas:
            if area.type == 'VIEW_3D':
                sh = area.spaces.active.shading
                if sh.type == 'SOLID':
                    sh.color_type = 'VERTEX'


def colour_panels(ob, pattern, prof, extra_rows=0):
    """ob: a tentacle armature or a mount ring mesh. extra_rows: rows the
    pattern grid had in front of the mesh (base extended through the ring)."""
    me = ob.data if ob.type == 'MESH' else ob.eva_tentacle.mesh_obj.data
    M = prof.M
    if len(me.vertices) % M or me.get('eva_M', M) != M:
        # the skin was built for other settings (e.g. a different gore count): rebuild it
        if ob.type == 'MESH':
            from . import ring as RG
            RG.build_mesh(ob)
        else:
            build_mesh(ob)
        me = ob.data if ob.type == 'MESH' else ob.eva_tentacle.mesh_obj.data
        if len(me.vertices) % M:
            return
    R = len(me.vertices) // M
    rgb = (default_colours(prof, R) if ob.type != 'MESH'
           else np.tile((0.42, 0.33, 0.48), ((R - 1) * M, 1))).reshape(R - 1, M, 3).copy()
    G_ = len(prof.gore_start)
    for p in pattern.panels:
        hue = (p.gore / max(G_, 1) * 0.83 + 0.6) % 1.0
        val = 0.85 if p.piece % 2 == 0 else 0.55
        c = colorsys.hsv_to_rgb(hue, 0.55, val)
        cols = (prof.gore_start[p.gore] + np.arange(prof.gore_cols[p.gore])) % M
        shift = pattern.row_offset - extra_rows
        for j in range(max(p.j0 + shift, 0), min(p.j1 + shift, R - 1)):
            rgb[j, cols] = c
    _colour_faces(me, rgb.reshape(-1, 3))
    me.update()


# --------------------------------------------------------- posing

def apply_curl(arm, curl, power, start, twist, side, wave, waves, phase):
    """Curl > 0 rolls toward the suckers, most of it near the tip."""
    pbs = chain(arm)
    n = len(pbs)
    w = np.array([((i + 1) / n) ** power if (i + 1) / n > start else 0.0 for i in range(n)])
    if w.sum() > 0:
        w *= curl / w.sum()
    for i, pb in enumerate(pbs):
        pb.rotation_mode = 'QUATERNION'
        sway = side / n + wave * math.sin(2 * math.pi * waves * i / n + phase)
        q = (Quaternion((1, 0, 0), -w[i]) @ Quaternion((0, 1, 0), twist / n)
             @ Quaternion((0, 0, 1), sway))
        pb.rotation_quaternion = q
        pb.location = (0, 0, 0)
        pb.scale = (1, 1, 1)
    keep_pose_with_ik(arm)


def keep_pose_with_ik(arm):
    """After setting bone rotations by hand: evaluate them without IK, move
    the handles onto that pose, and switch IK back on if it was on, so the
    handles stay live without the pose jumping."""
    cons = ik_constraints(arm)
    on = arm.eva_tentacle.use_ik
    for con in cons:
        con.mute = True
    bpy.context.view_layer.update()
    snap_target(arm)
    for con in cons:
        con.mute = not on


def bake_ik(context, arm):
    """Keep the IK result as plain bone rotations, then switch IK off."""
    pbs = chain(arm)
    dg = context.evaluated_depsgraph_get()
    ev = arm.evaluated_get(dg)
    mats = [ev.pose.bones[pb.name].matrix.copy() for pb in pbs]
    twists = bone_twists(arm, dg) if arm.eva_tentacle.use_ik else np.zeros(len(pbs))
    for con in ik_constraints(arm):
        con.mute = True
    for pb, m, tw in zip(pbs, mats, twists):
        pb.rotation_mode = 'QUATERNION'
        pb.matrix = m @ Matrix.Rotation(float(tw), 4, 'Y')
        context.view_layer.update()
    arm.eva_tentacle['use_ik'] = False


def reset_pose(arm):
    for pb in chain(arm):
        pb.rotation_mode = 'QUATERNION'
        pb.rotation_quaternion = (1, 0, 0, 0)
        pb.location = (0, 0, 0)
        pb.scale = (1, 1, 1)
    keep_pose_with_ik(arm)


# ------------------------------------------------------- pattern

def layout_candidates(max_top=8, max_bottom=3):
    """(top, suction) gore counts, fewest seams first."""
    c = [(t, b) for t in range(3, max_top + 1) for b in range(1, max_bottom + 1)]
    return sorted(c, key=lambda tb: (tb[0] + tb[1], tb[1]))


def suggest_layout(arms, scene, target=0.03, together=True, progress=None):
    """Fewest gores whose panels all stretch less than `target` when made
    flat. together=True finds one layout that works for every tentacle.
    Returns {arm: (top, bottom, worst stretch, panels, tried)}."""
    cands = layout_candidates()
    groups = [list(arms)] if together else [[a] for a in arms]
    out = {}
    step = [0]

    def evaluate(arm, tb):
        pat, _, _ = pattern_for(arm, scene, {'top_gores': tb[0], 'bottom_gores': tb[1]}, quick=True)
        step[0] += 1
        if progress:
            progress(step[0])
        return max(pn.strain for pn in pat.panels), len(pat.panels)

    for group in groups:
        best = None          # (worst, tb, results) if nothing meets the target
        chosen = None
        tried = []
        for tb in cands:
            results = {}
            worst = 0.0
            for arm in group:
                st, n = evaluate(arm, tb)
                results[arm] = (st, n)
                worst = max(worst, st)
                if st > target:
                    break
            tried.append((tb, worst))
            if worst <= target and len(results) == len(group):
                chosen = (tb, results)
                break
            if best is None or worst < best[0]:
                best = (worst, tb, results)
        if chosen is None:              # nothing met the target: least stretch found
            tb = best[1]
            chosen = (tb, {a: evaluate(a, tb) for a in group})
        tb, results = chosen
        for arm in group:
            st, n = results[arm]
            out[arm] = (tb[0], tb[1], st, n, tried)
    return out


def export_settings(scene):
    ex = scene.eva_tentacle_export
    to_mm = scene.unit_settings.scale_length * 1000.0
    return G.Settings(
        mat_w=ex.mat_width * to_mm, mat_h=ex.mat_height * to_mm, margin=ex.mat_margin * to_mm,
        max_len=ex.max_panel_length * to_mm, max_bow=ex.max_bow * to_mm, align_breaks=ex.align_breaks,
        max_strain=ex.max_stretch / 100.0,
        seam_style=ex.seam_style, crease_deg=ex.crease_angle, thickness=ex.thickness * to_mm,
        tick_spacing=ex.tick_spacing * to_mm)


def base_outline_world(arm, depsgraph=None):
    """Outer skin's first ring (the base outline) in world units."""
    p = arm.eva_tentacle
    shape = shape_of(p)
    prof = G.make_profile(shape)
    joints, ups = pose_arrays(arm, depsgraph)
    sw = G.sweep(shape, prof, joints, ups, trim=ring_trim(arm))
    mw = np.array(arm.matrix_world)
    return sw.V[0] @ mw[:3, :3].T + mw[:3, 3]


def pattern_for(arm, scene, overrides=None, quick=False, settings=None):
    """Flatten one tentacle. Returns (pattern, profile, meta).
    overrides: Shape fields to try instead of the tentacle's own (e.g. gore
    counts). quick: fewer relax steps and no outlines/meta (for searching)."""
    p = arm.eva_tentacle
    ex = scene.eva_tentacle_export
    to_mm = scene.unit_settings.scale_length * 1000.0
    scale = float(np.mean(arm.matrix_world.to_scale()))
    k = scale * to_mm
    shape = shape_of(p)
    for key, v in (overrides or {}).items():
        setattr(shape, key, v)
    prof = G.make_profile(shape)
    joints, ups = pose_arrays(arm, bpy.context.evaluated_depsgraph_get())
    half = ex.thickness / 2 / max(scale, 1e-9)
    off = half if ex.model_surface == 'OUTER' else 0.0
    sw = G.sweep(shape, prof, joints, ups, offset=off, trim=ring_trim(arm))
    mw = np.array(arm.matrix_world)
    Vs = sw.V if sw.base_cut is None else sw.V_ext      # cut at the ring after flattening
    V = Vs.reshape(-1, 3) @ mw[:3, :3].T + mw[:3, 3]
    V = V.reshape(Vs.shape) * to_mm

    st = export_settings(scene)
    for key, v in (settings or {}).items():
        setattr(st, key, v)
    if quick:
        st.relax_iters = 150
        st.max_strain = 0.0     # judge the gore layout itself, not one rescued by short pieces
    Kx = 0 if sw.V_ext is None else len(sw.V_ext) - len(sw.V)

    # each stretch goes on the thickest stock that can bend that tight
    stocks = stock_list(scene, st) if (ex.thin_tips and not quick) else [(st.thickness, st.mat_w, st.mat_h)]
    runs = stock_runs(sw, shape, k, stocks, ex.thin_ratio)
    min_first = 0 if sw.base_cut is None else int(np.ceil(sw.base_cut.max())) - Kx + 3
    if len(runs) > 1 and runs[1][1] < min_first:          # keep the base cut in one stock
        runs = [r for r in runs if r[1] >= min_first or r is runs[0]]
        runs[1:] = [(i, max(j, min_first)) for i, j in runs[1:]]
        runs = [runs[0]] + [r for r in runs[1:] if r[1] < len(sw.line.s) - 3]
    ends = [r[1] for r in runs[1:]] + [len(sw.line.s) - 1]
    pat = G.build_pattern(V[:Kx + ends[0] + 1], prof, st, base_bevel=sw.base_bevel, base_cut=sw.base_cut)
    pat.extra_rows = Kx
    for pn in pat.panels:
        pn.thickness = st.thickness
        pn.mat = (st.mat_w, st.mat_h)
    for (si, j0), j1 in zip(runs[1:], ends[1:]):
        t_mm, w_mm, h_mm = stocks[si]
        st_s = export_settings(scene)
        for key, v in (settings or {}).items():
            setattr(st_s, key, v)
        st_s.thickness, st_s.mat_w, st_s.mat_h = t_mm, w_mm, h_mm
        off_s = t_mm / to_mm / 2 / max(scale, 1e-9) if ex.model_surface == 'OUTER' else 0.0
        sw_s = G.sweep(shape, prof, joints, ups, offset=off_s, trim=ring_trim(arm))
        Vs_ = sw_s.V if sw_s.base_cut is None else sw_s.V_ext
        Vs_ = (Vs_.reshape(-1, 3) @ mw[:3, :3].T + mw[:3, 3]).reshape(Vs_.shape) * to_mm
        seg = G.build_pattern(Vs_[Kx + j0:Kx + j1 + 1], prof, st_s)
        _append_segment(pat, seg, prof, Kx + j0 - pat.row_offset, st_s)
    totals = {}
    for q in pat.panels:
        totals[q.gore] = totals.get(q.gore, 0) + 1
    for q in pat.panels:
        q.pieces = totals[q.gore]
    pat.runs = [dict(thickness=stocks[si][0], from_mm=float(sw.line.s[j0] * k), width_mm=float(2 * sw.radii[j0] * k))
                for si, j0 in runs]
    # the thinnest stock used must obey the rule too
    rmin = np.minimum(sw.radii * min(1.0, shape.height_ratio) * k, k / np.maximum(sw.line.kappa, 1e-9))
    t_last = stocks[runs[-1][0]][0]
    bad = np.nonzero(rmin[runs[-1][1]:] < ex.thin_ratio * t_last)[0]
    if ex.thin_tips and len(bad):
        pat.warnings.append('Even %g mm foam is too thick from %.0f mm along (bend radius %.0f mm, needs at '
                            'least %.0f mm): add a thinner stock or ease the curl.'
                            % (t_last, float(sw.line.s[runs[-1][1] + bad[0]] * k), float(rmin[runs[-1][1]:][bad].min()),
                               ex.thin_ratio * t_last))
    if quick:
        return pat, prof, None
    for pn in pat.panels:
        G.finish_outlines(pn, pn.thickness, ex.mirror)

    r0 = sw.radii[0] * k
    half_mm = st.thickness / 2
    if off:
        outer = prof.U * r0
        mid = prof.U * r0 - prof.N * min(half_mm, 0.12 * r0 * min(1.0, shape.height_ratio))
    else:
        outer = prof.U * r0 + prof.N * half_mm
        mid = prof.U * r0

    ratio, at = G.tightest_bend(sw, shape)
    if ratio < 1.0:
        bend = 'TOO TIGHT at %.0f%% of the length: the inside folds through itself' % (at * 100)
        pat.warnings.insert(0, 'Curl is too tight at %.0f%% of the length (bend radius %.2f x the section '
                               'height); the inside of the curl would fold through itself.' % (at * 100, ratio))
    elif ratio < 1.6:
        bend = 'tight (%.1f x section height at %.0f%%)' % (ratio, at * 100)
    else:
        bend = 'ok (%.1f x section height)' % ratio
    seam_desc = {'AUTO': 'auto: bevel creases over %.0f\xb0, others square' % ex.crease_angle,
                 'BEVEL': 'bevel every seam', 'SQUARE': 'all square (90\xb0)'}[ex.seam_style]
    if p.mount_ring is not None:
        extra = dict(start_edge='BASE EDGE: sits on the mount ring over the dash-dot %s outline' % p.code)
    else:
        extra = {}
    runs = getattr(pat, 'runs', [])
    p.thin_note = ('Foam: ' + ' \u2192 '.join('%g mm%s' % (r['thickness'], (' at %.0f mm' % r['from_mm'])
                                                             if r['from_mm'] > 0 else '') for r in runs)) \
        if len(runs) > 1 else ''
    meta = dict(
        **extra, runs=runs,
        code=p.code, name=arm.name, labels=prof.labels, is_bottom=prof.is_bottom,
        gore_start=prof.gore_start, tick_every=pat.tick_every, mirror=ex.mirror,
        page_mode=ex.page_mode, print_layout=ex.print_layout, thickness=st.thickness, length=sw.line.total * k,
        base_d=p.base_diameter * k, tip_d=p.tip_diameter * k, height_ratio=p.height_ratio,
        bottom_roundness=p.bottom_roundness, top_gores=p.top_gores, bottom_gores=p.bottom_gores,
        mat_w=st.mat_w, mat_h=st.mat_h, margin=st.margin, max_bow=st.max_bow, seam_desc=seam_desc, bend_desc=bend,
        warnings=pat.warnings, section_outer=outer, section_mid=mid)
    return pat, prof, meta


def stock_list(scene, st):
    """[(thickness, sheet W, sheet H)] in mm: the main mats, then thinner
    stocks from thickest to thinnest."""
    ex = scene.eva_tentacle_export
    to_mm = scene.unit_settings.scale_length * 1000.0
    # exactly the stocks listed in the panel: the first thinner stock, then any added rows
    extra = [(ex.thin_thickness, ex.thin_mat_width, ex.thin_mat_height)] + \
        [(s.thickness, s.width, s.height) for s in ex.stocks]
    extra = sorted({(round(t * to_mm, 3), w * to_mm, h * to_mm) for t, w, h in extra}, key=lambda x: -x[0])
    return [(st.thickness, st.mat_w, st.mat_h)] + [x for x in extra if x[0] < st.thickness - 1e-6]


def stock_runs(sw, shape, k, stocks, ratio, min_rows=3):
    """[(stock index, first ring)]: from the base, each stretch takes the
    thickest stock whose thickness is at most bend radius / ratio, never
    going back to thicker toward the tip. Very short stretches are folded
    into the thinner stretch that follows."""
    R = len(sw.line.s)
    if len(stocks) == 1:
        return [(0, 0)]
    rmin = np.minimum(sw.radii * min(1.0, shape.height_ratio) * k, k / np.maximum(sw.line.kappa, 1e-9))
    th = np.array([s[0] for s in stocks])
    choice = np.array([int(np.argmax(th <= r / ratio)) if (th <= r / ratio).any() else len(th) - 1
                       for r in rmin])
    choice = np.maximum.accumulate(choice)
    runs = [(int(choice[0]), 0)]
    for j in range(1, R):
        if choice[j] != runs[-1][0]:
            runs.append((int(choice[j]), j))
    # fold short stretches into the next (thinner, so still safe)
    out = [runs[0]]
    for i, (si, j0) in enumerate(runs[1:], 1):
        end = runs[i + 1][1] if i + 1 < len(runs) else R - 1
        if end - j0 < min_rows and i + 1 < len(runs):
            continue
        out.append((si, j0))
    if len(out) > 1 and (R - 1) - out[-1][1] < min_rows:
        out[-1] = (out[-1][0], max(R - 1 - min_rows, out[-2][1] + min_rows))
    if len(out) > 1 and out[1][1] < min_rows:
        out = [(out[1][0], 0)] + out[2:]
    return out


def _append_segment(pat, seg, prof, shift, st_s):
    """Append a thinner-stock stretch to the pattern: continue the piece
    numbers, line up ring numbers, and turn the meeting ends into joins."""
    G_ = len(prof.labels)
    n_prev = {g: sum(1 for q in pat.panels if q.gore == g) for g in range(G_)}
    idx = {lab: g for g, lab in enumerate(prof.labels)}

    def renum(label):
        lab, num = label.rsplit('-', 1)
        return '%s-%d' % (lab, int(num) + n_prev[idx[lab]])
    for q in pat.panels:
        if q.piece == n_prev[q.gore] - 1:            # its tip end now meets the next stock
            top = q.sides[2]
            top.kind = 'join'
            top.neighbours = ['%s-%d' % (q.gore_label, q.piece + 2)]
    for q in seg.panels:
        q.thickness = st_s.thickness
        q.mat = (st_s.mat_w, st_s.mat_h)
        q.piece += n_prev[q.gore]
        q.j0 += shift
        q.j1 += shift
        for s in q.sides:
            if s.kind == 'seam':
                s.ids = s.ids + shift
            s.neighbours = [renum(x) for x in s.neighbours]
        if q.piece == n_prev[q.gore]:                 # its base end meets the thicker stock
            bt = q.sides[0]
            bt.kind = 'join'
            bt.neighbours = ['%s-%d' % (q.gore_label, q.piece)]
            bt.bevel = np.zeros_like(bt.bevel)
            bt.bevelled = False
    pat.panels = sorted(pat.panels + seg.panels, key=lambda q: (q.gore, q.piece))
    pat.warnings += seg.warnings


def pdf_path(arm, scene, code=None):
    ex = scene.eva_tentacle_export
    d = ex.output_dir or '//'
    if d.startswith('//') and not bpy.data.filepath:
        folder = os.path.join(os.path.expanduser('~'), 'Documents', 'EVA tentacle patterns')
    else:
        folder = bpy.path.abspath(d)
    os.makedirs(folder, exist_ok=True)
    safe = re.sub(r'[^A-Za-z0-9_.-]+', '_', '%s_%s' % (code or arm.eva_tentacle.code, arm.name)).strip('_')
    return os.path.join(folder, safe + '_EVA_pattern.pdf')


# ------------------------------------------------------- handlers

_last = {}
_seen = {}
_busy = False
_render_busy = [False]


@persistent
def on_render_start(*_):
    _render_busy[0] = True


@persistent
def on_render_end(*_):
    _render_busy[0] = False


def _handle_key(t):
    return np.round(np.array(t.matrix_basis).ravel(), 6).tobytes()


def _handles_adrift(ob, depsgraph):
    ev = ob.evaluated_get(depsgraph)
    targets = ik_targets(ob)
    ends = segment_ends(len(chain(ob)), len(targets) - 1)
    for t, end in zip(targets, ends):
        if t is not None:
            want = ev.matrix_world @ ev.pose.bones[BONE % end].tail
            if (t.matrix_world.translation - want).length > 1e-4:
                return True
    return False


def _wake_ik(ob, depsgraph):
    """IK is off but a handle was just moved or spun: line the other
    handles up with the pose and switch IK on, so the grab takes effect."""
    targets = [t for t in ik_targets(ob) if t is not None]
    moved = [t for t in targets if _seen.get(t.session_uid) not in (None, _handle_key(t))]
    if moved and not ob.eva_tentacle.use_ik:
        snap_target(ob, depsgraph, exclude=set(moved))
        for con in ik_constraints(ob):
            con.mute = False
        ob.eva_tentacle['use_ik'] = True
    elif not ob.eva_tentacle.use_ik and _handles_adrift(ob, depsgraph):
        snap_target(ob, depsgraph)       # park unused handles on the pose
    for t in targets:
        _seen[t.session_uid] = _handle_key(t)


@persistent
def on_depsgraph(scene, depsgraph):
    global _busy
    if _busy or rendering():
        return
    _busy = True
    try:
        for ob in all_tentacles(scene):
            if not ob.eva_tentacle.live_update or ob.eva_tentacle.mesh_obj is None:
                continue
            _wake_ik(ob, depsgraph)
            ev = ob.evaluated_get(depsgraph)
            mats = [list(pb.matrix) for pb in ev.pose.bones]
            mats += [list(t.evaluated_get(depsgraph).matrix_world) for t in ik_targets(ob) if t is not None]
            sig = np.round(np.array(mats).ravel(), 6).tobytes()
            key = ob.session_uid
            if _last.get(key) != sig:
                _last[key] = sig
                build_mesh(ob, depsgraph)
    finally:
        _busy = False


@persistent
def on_load(_):
    _last.clear()
    _seen.clear()
    _panel_queue.clear()


def register():
    bpy.app.handlers.depsgraph_update_post.append(on_depsgraph)
    bpy.app.handlers.load_post.append(on_load)
    bpy.app.handlers.render_init.append(on_render_start)
    bpy.app.handlers.render_complete.append(on_render_end)
    bpy.app.handlers.render_cancel.append(on_render_end)


def unregister():
    for lst, fn in ((bpy.app.handlers.depsgraph_update_post, on_depsgraph),
                    (bpy.app.handlers.load_post, on_load),
                    (bpy.app.handlers.render_init, on_render_start),
                    (bpy.app.handlers.render_complete, on_render_end),
                    (bpy.app.handlers.render_cancel, on_render_end)):
        if fn in lst:
            lst.remove(fn)
