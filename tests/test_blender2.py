"""Ring, set of 8, control points and handle twist. Run headless:
Blender -b --factory-startup --python tests/test_blender2.py -- OUTDIR"""
import math, os, sys
import bpy
import numpy as np
from mathutils import Vector, Matrix
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import eva_tentacle
eva_tentacle.register()
from eva_tentacle import rig, ring

out = sys.argv[sys.argv.index('--') + 1]
os.makedirs(out, exist_ok=True)
ctx = bpy.context
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o)

# --- a single tentacle with 2 control points
bpy.ops.eva_tentacle.add()
arm = ctx.active_object
p = arm.eva_tentacle
p.control_count = 2
ctx.view_layer.update()
cons = rig.ik_constraints(arm)
print('controls', [c.obj.name for c in p.controls], 'IK segments', [(c.id_data.pose.bones.find(c.id_data.pose.bones[0].name), c.chain_count, c.target.name) for c in cons])
c1 = p.controls[0].obj
c1.location = Vector(c1.location) + Vector((0.12, -0.08, 0.1))
ctx.view_layer.update()
ev = arm.evaluated_get(ctx.evaluated_depsgraph_get())
end = rig.segment_ends(p.bone_count, 2)[0]
gap = (ev.matrix_world @ ev.pose.bones[rig.BONE % end].tail - c1.matrix_world.translation).length
print('control 1 reached: gap %.4f m' % gap)

# twist: spin control 2 about its own Y by 120 deg, tip by 300
c2 = p.controls[1].obj
for step in range(4):            # several steps so unwrapping sees the rotation
    c2.matrix_world = c2.matrix_world @ Matrix.Rotation(math.radians(30), 4, 'Y')
    ctx.view_layer.update()
tip = p.ik_target
for step in range(10):
    tip.matrix_world = tip.matrix_world @ Matrix.Rotation(math.radians(30), 4, 'Y')
    ctx.view_layer.update()
tw = np.degrees(rig.bone_twists(arm))
print('handle twists', [(e, round(math.degrees(a))) for e, a in rig.handle_twists(arm)])
print('bone twists', np.round(tw).astype(int).tolist())
verts_before = np.array([v.co[:] for v in p.mesh_obj.data.vertices])
bpy.ops.eva_tentacle.bake_ik()
ctx.view_layer.update()
rig.build_mesh(arm)
verts_after = np.array([v.co[:] for v in p.mesh_obj.data.vertices])
print('skin moved by Keep pose (twist baked): max %.4f m' % np.abs(verts_after - verts_before).max())

# --- ring + set of 8
bpy.ops.eva_tentacle.add_ring()
rob = ctx.active_object
rob.eva_ring.top_diameter = 0.38
rob.eva_ring.bottom_diameter = 0.9
rob.eva_ring.curve = -0.3
sp = ctx.scene.eva_tentacle_set
print('set default count', sp.count)
bpy.ops.eva_tentacle.add_set()
ts = [t for t in rig.all_tentacles(ctx.scene) if t.eva_tentacle.mount_ring == rob]
print('mounted', len(ts), [round(math.degrees(t.eva_tentacle.mount_angle)) for t in ts])
base = rig.base_outline_world(ts[0])
print('T base centre', np.round(base.mean(0), 3))
rob.eva_ring.bottom_height = 0.7          # ring change moves mounted tentacles
ctx.view_layer.update()
print('after ring edit', np.round(rig.base_outline_world(ts[0]).mean(0), 3))

ex = ctx.scene.eva_tentacle_export
ex.output_dir = out
ex.scope = 'ALL'
print(bpy.ops.eva_tentacle.export_pdf())
print(sorted(os.listdir(out)))
bpy.ops.wm.save_as_mainfile(filepath=os.path.join(out, 'ring_test.blend'))

# draw the sidebar once to catch UI errors
from eva_tentacle import ui
class _L:
    def __getattr__(self, k): return lambda *a, **kw: _L()
    scale_y = 1
for P in ui.classes:
    for ob in (arm, rob):
        ctx.view_layer.objects.active = ob
        if not hasattr(P, 'poll') or P.poll(ctx):
            fake = type('F', (), {'layout': _L()})()
            P.draw(fake, ctx)
print('ui draw ok')

# every mounted tentacle: bones start on the ring skin, base edge lies on it
from eva_tentacle import geometry as G
rs = ring.shape_of(rob.eva_ring)
f = G.ring_inside(rs)
inv = np.array(rob.matrix_world.inverted())
worst_root = worst_edge = 0.0
for t in ts:
    root = np.array(t.matrix_world.translation)
    worst_root = max(worst_root, abs(f((inv[:3, :3] @ root + inv[:3, 3])[None])[0]))
    edge = rig.base_outline_world(t)
    worst_edge = max(worst_edge, np.abs(f(edge @ inv[:3, :3].T + inv[:3, 3])).max())
print('root off ring %.2f mm, base edge off ring %.2f mm' % (worst_root * 1000, worst_edge * 1000))
