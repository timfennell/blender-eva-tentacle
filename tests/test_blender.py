"""Run: Blender -b --factory-startup --python tests/test_blender.py -- OUTDIR"""
import math, os, sys
import bpy
from mathutils import Vector
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import eva_tentacle
eva_tentacle.register()
from eva_tentacle import rig

out = sys.argv[sys.argv.index('--') + 1]
os.makedirs(out, exist_ok=True)
ctx = bpy.context
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o)

bpy.ops.eva_tentacle.add()
arm = ctx.active_object
p = arm.eva_tentacle
print('created', arm.name, p.code, 'bones', len(arm.pose.bones), 'skin verts', len(p.mesh_obj.data.vertices))
pb = arm.pose.bones[0]
print('bone0 axes Y', tuple(round(v, 3) for v in pb.matrix.col[1].xyz), 'Z', tuple(round(v, 3) for v in pb.matrix.col[2].xyz))

# IK: pull the target and check the skin follows via the depsgraph handler
v0 = p.mesh_obj.data.vertices[-1].co.copy()
p.ik_target.location = (0.5, 0.8, 0.3)
ctx.view_layer.update()
v1 = p.mesh_obj.data.vertices[-1].co.copy()
print('IK moved tip vertex by', round((v1 - v0).length, 3), 'tip now', tuple(round(x, 3) for x in rig.tip_world(arm)))
bpy.ops.eva_tentacle.bake_ik()
print('after bake: ik muted', all(c.mute for c in rig.ik_constraints(arm)), 'use_ik', p.use_ik)

# length / bone count change keeps working
p.length = 1.5
p.bone_count = 16
ctx.view_layer.update()
print('length 1.5 / 16 bones -> bones', len(arm.pose.bones), 'skin verts', len(p.mesh_obj.data.vertices))

bpy.ops.eva_tentacle.curl(curl=math.radians(250), twist=math.radians(30), side=math.radians(20))
ctx.view_layer.update()
print('bend ratio', round(p.bend_ratio, 2), 'at', round(p.bend_at, 2))
p.bottom_gores = 2
p.bottom_roundness = 0.2

ex = ctx.scene.eva_tentacle_export
ex.output_dir = out
bpy.ops.eva_tentacle.preview_panels()
bpy.ops.eva_tentacle.export_pdf()

# a full Ursula set exported in one go, A4 and full-size modes
ctx.scene.eva_tentacle_set.count = 6
ctx.scene.eva_tentacle_set.on_ring = False
bpy.ops.eva_tentacle.add_set()
ex.scope = 'ALL'
ex.page_mode = 'FULL'
r = bpy.ops.eva_tentacle.export_pdf()
print('set export', r, sorted(os.listdir(out)))
bpy.ops.wm.save_as_mainfile(filepath=os.path.join(out, 'tentacle_test.blend'))
