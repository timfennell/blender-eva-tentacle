"""Copy to Selected. Blender -b --factory-startup --python tests/test_copy.py"""
import os, sys, bpy
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import eva_tentacle
eva_tentacle.register()
from eva_tentacle import rig
ctx = bpy.context
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o)
sp = ctx.scene.eva_tentacle_set
sp.count = 4
bpy.ops.eva_tentacle.add_set()
ts = sorted(rig.all_tentacles(ctx.scene), key=lambda o: o.eva_tentacle.code)
src = ts[0]
tips_before = [np.array(rig.tip_world(t)) for t in ts[1:]]
p = src.eva_tentacle
p.base_diameter = 0.25
p.taper_power = 2.0
p.top_gores = 5
p.control_count = 2
p.emerge = 1.2
for o in ctx.selected_objects:
    o.select_set(False)
for t in ts[:3]:                      # leave the 4th unselected
    t.select_set(True)
ts[2].eva_tentacle.mesh_obj.select_set(True)   # a selected skin counts too
ctx.view_layer.objects.active = src
print(bpy.ops.eva_tentacle.copy_settings(groups={'SHAPE', 'PANELS', 'RIG'}))
ctx.view_layer.update()
for t in ts:
    q = t.eva_tentacle
    print(q.code, 'width %.2f taper %.1f gores %d controls %d lift %.2f verts %d' % (
        q.base_diameter, q.taper_power, q.top_gores, len(q.controls), q.emerge, len(q.mesh_obj.data.vertices)))
print('tips moved by copy (m):', [round(float(np.linalg.norm(np.array(rig.tip_world(t)) - b)), 4) for t, b in zip(ts[1:], tips_before)])

# Suggest Panels on the selected ones
print(bpy.ops.eva_tentacle.suggest_panels(target=3.0, together=True))
for t in ts[:3]:
    print('SUGGEST', t.eva_tentacle.code, t.eva_tentacle.layout_note)
