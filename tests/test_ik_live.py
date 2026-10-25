"""IK handles stay live after curls; grabbing a handle wakes IK.
Blender -b --factory-startup --python tests/test_ik_live.py"""
import math, os, sys
import bpy
import numpy as np
from mathutils import Vector
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import eva_tentacle
eva_tentacle.register()
from eva_tentacle import rig, ring
ctx = bpy.context
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o)

def joints(arm):
    ev = arm.evaluated_get(ctx.evaluated_depsgraph_get())
    return np.array([tuple(ev.matrix_world @ pb.tail) for pb in ev.pose.bones])

sp = ctx.scene.eva_tentacle_set
sp.count = 3
bpy.ops.eva_tentacle.add_set()
ctx.view_layer.update()
arm = rig.all_tentacles(ctx.scene)[0]
p = arm.eva_tentacle
print('after set: use_ik', p.use_ik, 'muted', [c.mute for c in rig.ik_constraints(arm)])
# handles sit on the curled pose: IK on must not change it
J0 = joints(arm)
ctx.view_layer.update()
print('curl kept with IK on: max joint shift %.4f m' % np.abs(joints(arm) - J0).max())

# drag the tip handle: tentacle follows
tip = p.ik_target
tip.location = Vector(tip.location) + Vector((0.0, 0.0, 0.15))
ctx.view_layer.update()
print('tip handle drag: tip moved %.3f m, gap to handle %.4f m' % (
    np.linalg.norm(joints(arm)[-1] - J0[-1]), np.linalg.norm(joints(arm)[-1] - np.array(tip.matrix_world.translation))))

# IK off (e.g. after Keep pose), then grab the control: IK wakes up
bpy.ops.object.select_all(action='DESELECT')
ctx.view_layer.objects.active = arm
bpy.ops.eva_tentacle.bake_ik()
ctx.view_layer.update()
J1 = joints(arm)
c1 = p.controls[0].obj
c1.location = Vector(c1.location) + Vector((0.08, 0.0, 0.05))
ctx.view_layer.update()
ctx.view_layer.update()
end = rig.segment_ends(p.bone_count, 1)[0]
print('after grab with IK off: use_ik', p.use_ik, 'control gap %.4f m, tip moved %.4f m' % (
    np.linalg.norm(joints(arm)[end] - np.array(c1.matrix_world.translation)), np.linalg.norm(joints(arm)[-1] - J1[-1])))

# ring change must not wake IK on a tentacle that has it off
arm2 = rig.all_tentacles(ctx.scene)[1]
ctx.view_layer.objects.active = arm2
bpy.ops.eva_tentacle.bake_ik()
ctx.view_layer.update()
r = arm2.eva_tentacle.mount_ring
r.eva_ring.bottom_height -= 0.05
ctx.view_layer.update()
print('ring edit leaves IK off:', not arm2.eva_tentacle.use_ik)
# live colouring path (timers do not run headless; call directly)
rig.colour_live(arm)
rig.colour_live(r)
print('live colour ok')

# stale handles (IK off, handle left far away) get parked on the pose
arm3 = rig.all_tentacles(ctx.scene)[2]
ctx.view_layer.objects.active = arm3
bpy.ops.eva_tentacle.bake_ik()
for c in rig.ik_constraints(arm3):
    c.mute = True
arm3.eva_tentacle['use_ik'] = False
arm3.eva_tentacle.ik_target.location = (3, 3, 3)
rig._seen.clear()            # as if the file had just been opened with the handle already adrift
ctx.view_layer.update()
ctx.view_layer.update()
gap = np.linalg.norm(joints(arm3)[-1] - np.array(arm3.eva_tentacle.ik_target.matrix_world.translation))
print('stale handle parked: gap %.4f m, IK still off: %s' % (gap, not arm3.eva_tentacle.use_ik))
