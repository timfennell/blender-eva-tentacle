import math
import random

import bpy
from bpy.props import EnumProperty, FloatProperty, IntProperty

from . import rig, ring


def _active_tentacle(context):
    return rig.find_tentacle(context.active_object)


def _targets(context):
    """Tentacles and mount rings to export."""
    ex = context.scene.eva_tentacle_export
    if ex.scope == 'ALL':
        return rig.all_tentacles(context.scene) + ring.all_rings(context.scene)
    obs = list(context.selected_objects) + [context.active_object]
    sel = {rig.find_tentacle(o) for o in obs} | {o for o in obs if ring.is_ring(o)}
    sel.discard(None)
    return sorted(sel, key=lambda o: (ring.is_ring(o), o.name))


def _pattern(ob, scene, settings=None):
    if ring.is_ring(ob):
        pat, prof, meta = ring.pattern_for(ob, scene, settings=settings)
        return pat, prof, meta, ring.pdf_path(ob, scene)
    pat, prof, meta = rig.pattern_for(ob, scene, settings=settings)
    return pat, prof, meta, rig.pdf_path(ob, scene)


class EVA_OT_add_tentacle(bpy.types.Operator):
    bl_idname = 'eva_tentacle.add'
    bl_label = 'Add Tentacle'
    bl_description = 'Add a tentacle rig with an IK target at the 3D cursor'
    bl_options = {'REGISTER', 'UNDO'}

    length: FloatProperty(name='Length', default=1.3, min=0.05, unit='LENGTH', subtype='DISTANCE')
    base_diameter: FloatProperty(name='Base width', default=0.20, min=0.005, unit='LENGTH',
                                 subtype='DISTANCE')
    bone_count: IntProperty(name='Bones', default=12, min=3, max=48)

    def execute(self, context):
        if context.object and context.object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        arm = rig.create_tentacle(context, 'Tentacle', tuple(context.scene.cursor.location), 0.0,
                                  length=self.length, base_diameter=self.base_diameter,
                                  bone_count=self.bone_count)
        for o in context.selected_objects:
            o.select_set(False)
        arm.select_set(True)
        context.view_layer.objects.active = arm
        return {'FINISHED'}


class EVA_OT_add_ring(bpy.types.Operator):
    bl_idname = 'eva_tentacle.add_ring'
    bl_label = 'Add Mount Ring'
    bl_description = 'Add a funnel-shaped EVA ring (sits on the hoop skirt) to glue tentacles onto'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        if context.object and context.object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        ob = ring.create_ring(context, tuple(context.scene.cursor.location))
        for o in context.selected_objects:
            o.select_set(False)
        ob.select_set(True)
        context.view_layer.objects.active = ob
        return {'FINISHED'}


def mount(arm, ring_ob, angle, height=None, emerge=None):
    p = arm.eva_tentacle
    p['mount_angle'] = angle
    if height is not None:
        p['mount_height'] = height
    if emerge is not None:
        p['emerge'] = emerge
    p.mount_ring = ring_ob          # update callback places it


class EVA_OT_add_set(bpy.types.Operator):
    bl_idname = 'eva_tentacle.add_set'
    bl_label = 'Add Ursula Set'
    bl_description = 'Add the set of tentacles (on a mount ring if wanted), each with its own curl'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        if context.object and context.object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        sp = context.scene.eva_tentacle_set
        rnd = random.Random(sp.seed)
        c = context.scene.cursor.location
        ring_ob = None
        if sp.on_ring:
            ring_ob = ring.find_ring(context.active_object) or next(iter(ring.all_rings(context.scene)), None)
            if ring_ob is None:
                ring_ob = ring.create_ring(context, tuple(c))
        n = sp.count
        made = []
        for i in range(n):
            a = math.pi / 2 - sp.spread / 2 + (i + 0.5) * sp.spread / n
            ln = sp.length * (1 + sp.variation * (rnd.random() * 2 - 1))
            if ring_ob is None:
                r = 0.25
                loc = (c.x + r * math.cos(a), c.y + r * math.sin(a), c.z)
                arm = rig.create_tentacle(context, 'Tentacle', loc, a - math.pi / 2, length=ln,
                                          controls=sp.controls)
            else:
                arm = rig.create_tentacle(context, 'Tentacle', (0, 0, 0), 0.0, length=ln, controls=sp.controls)
                mount(arm, ring_ob, a)
            context.view_layer.update()
            rig.apply_curl(arm, math.radians(rnd.uniform(160, 340)), rnd.uniform(1.5, 3.0), 0.3,
                           math.radians(rnd.uniform(-40, 40)), math.radians(rnd.uniform(-25, 25)),
                           math.radians(rnd.uniform(0, 5)), rnd.uniform(0.5, 1.5), rnd.uniform(0, 6))
            made.append(arm)
        context.view_layer.update()
        for arm in made:
            rig.snap_target(arm)
            rig.build_mesh(arm)
        return {'FINISHED'}


class EVA_OT_mount(bpy.types.Operator):
    bl_idname = 'eva_tentacle.mount'
    bl_label = 'Mount on Ring'
    bl_description = 'Stand this tentacle on the mount ring (the selected one, or the first in the scene)'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _active_tentacle(context) is not None

    def execute(self, context):
        arm = _active_tentacle(context)
        rings = [o for o in context.selected_objects if ring.is_ring(o)] or ring.all_rings(context.scene)
        if not rings:
            self.report({'ERROR'}, 'Add a mount ring first')
            return {'CANCELLED'}
        mount(arm, rings[0], arm.eva_tentacle.mount_angle)
        context.view_layer.update()
        rig.snap_target(arm)
        rig.build_mesh(arm)
        return {'FINISHED'}


class EVA_OT_curl(bpy.types.Operator):
    bl_idname = 'eva_tentacle.curl'
    bl_label = 'Curl Tentacle'
    bl_description = ('Set the bone rotations for a spiral curl; the IK handles move onto it. '
                      'Adjust in the redo panel, then drag the handles')
    bl_options = {'REGISTER', 'UNDO'}

    curl: FloatProperty(name='Curl', default=math.radians(270), soft_min=-math.radians(720),
                        soft_max=math.radians(720), subtype='ANGLE',
                        description='Total curl; positive rolls toward the suckers')
    power: FloatProperty(name='Tightening', default=2.0, min=0.0, max=6.0,
                         description='0 = even curl, higher = tighter toward the tip')
    start: FloatProperty(name='Start', default=0.2, min=0.0, max=0.95, subtype='FACTOR',
                         description='Where along the length the curl begins')
    twist: FloatProperty(name='Twist', default=0.0, soft_min=-math.pi * 2, soft_max=math.pi * 2,
                         subtype='ANGLE', description='Twist around the length (spirals the suckers)')
    side: FloatProperty(name='Side sweep', default=0.0, soft_min=-math.pi, soft_max=math.pi,
                        subtype='ANGLE', description='Even bend to the side')
    wave: FloatProperty(name='Wave', default=0.0, min=0.0, max=math.radians(30), subtype='ANGLE',
                        description='Side-to-side S-wave per bone')
    waves: FloatProperty(name='Wave count', default=1.0, min=0.0, max=6.0)
    phase: FloatProperty(name='Wave phase', default=0.0, subtype='ANGLE')

    @classmethod
    def poll(cls, context):
        return _active_tentacle(context) is not None

    def execute(self, context):
        arm = _active_tentacle(context)
        rig.apply_curl(arm, self.curl, self.power, self.start, self.twist, self.side,
                       self.wave, self.waves, self.phase)
        context.view_layer.update()
        rig.build_mesh(arm)
        return {'FINISHED'}


class EVA_OT_bake_ik(bpy.types.Operator):
    bl_idname = 'eva_tentacle.bake_ik'
    bl_label = 'Keep IK Pose'
    bl_description = 'Store the current IK result as bone rotations and switch IK off, ready to hand-tweak'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _active_tentacle(context) is not None

    def execute(self, context):
        arm = _active_tentacle(context)
        rig.bake_ik(context, arm)
        rig.build_mesh(arm)
        return {'FINISHED'}


class EVA_OT_reset_pose(bpy.types.Operator):
    bl_idname = 'eva_tentacle.reset_pose'
    bl_label = 'Straighten'
    bl_description = 'Clear every bone rotation and move the IK target back to the tip'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _active_tentacle(context) is not None

    def execute(self, context):
        arm = _active_tentacle(context)
        rig.reset_pose(arm)
        rig.build_mesh(arm)
        return {'FINISHED'}


class EVA_OT_snap_target(bpy.types.Operator):
    bl_idname = 'eva_tentacle.snap_target'
    bl_label = 'Snap Target to Tip'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _active_tentacle(context) is not None

    def execute(self, context):
        rig.snap_target(_active_tentacle(context))
        return {'FINISHED'}


class EVA_OT_preview_panels(bpy.types.Operator):
    bl_idname = 'eva_tentacle.preview_panels'
    bl_label = 'Preview Panels'
    bl_description = 'Split into mat-sized panels and colour each one on the skin'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _active_tentacle(context) is not None or ring.is_ring(context.active_object)

    def execute(self, context):
        ob = context.active_object if ring.is_ring(context.active_object) else _active_tentacle(context)
        pat, prof, meta, _ = _pattern(ob, context.scene)
        rig.colour_panels(ob, pat, prof, getattr(pat, 'extra_rows', 0))
        arm = ob
        for area in context.screen.areas if context.screen else []:
            if area.type == 'VIEW_3D':
                sh = area.spaces.active.shading
                if sh.type == 'SOLID':
                    sh.color_type = 'VERTEX'
        msg = '%s: %d panels' % (meta['code'], len(pat.panels))
        if pat.warnings:
            msg += ' – %d warning(s): %s' % (len(pat.warnings), pat.warnings[0])
        self.report({'WARNING'} if pat.warnings else {'INFO'}, msg)
        return {'FINISHED'}


class EVA_OT_export_pdf(bpy.types.Operator):
    bl_idname = 'eva_tentacle.export_pdf'
    bl_label = 'Export Pattern PDFs'
    bl_description = 'Write one PDF of flattened EVA panels per tentacle'

    def execute(self, context):
        from . import pattern_pdf
        arms = _targets(context)
        if not arms:
            self.report({'ERROR'}, 'Select a tentacle or mount ring (or set Export to All)')
            return {'CANCELLED'}
        import os
        ex = context.scene.eva_tentacle_export
        done = []
        jobs = []
        for arm in arms:
            pat, prof, meta, path = _pattern(arm, context.scene)
            try:                            # only a preview: never let it stop an export
                rig.colour_panels(arm, pat, prof, getattr(pat, 'extra_rows', 0))
            except Exception as e:
                print('EVA tentacle: panel colours skipped for %s: %s' % (arm.name, e))
            jobs.append((pat, meta, path))
        shared = None
        mats_note = ''
        if ex.mat_sharing == 'SHARED':
            st = rig.export_settings(context.scene)
            codes = '_'.join(m['code'] for _, m, _ in jobs) if len(jobs) <= 4 else 'all_%d' % len(jobs)
            folder = os.path.dirname(jobs[0][2])
            files, n_sheets, mat_of, steps = pattern_pdf.write_mat_templates(
                folder, 'Cut_%s' % codes, [(p, m) for p, m, _ in jobs], st.margin, ex.page_mode)
            shared = {'files': [f for f, _ in files], 'mat_of': mat_of, 'steps': steps}
            counts = ', '.join('%d \xd7 %s' % (len(g['mats']), g['name']) for _, g in files)
            mats_note = ' + %d cutting file%s (%s, %d paper sheets)' % (len(files), '' if len(files) == 1 else 's',
                                                                       counts, n_sheets)
            for f, g in files:
                print('EVA tentacle: wrote %s (%d %s)' % (os.path.join(folder, f), len(g['mats']), g['name']))
        for pat, meta, path in jobs:
            doc, sheets = pattern_pdf.write_pdf(path, pat, meta, shared)
            done.append((path, len(pat.panels), sheets, len(pat.warnings)))
            print('EVA tentacle: wrote %s (%d panels, %d sheets)' % (path, len(pat.panels), sheets))
        warn = sum(d[3] for d in done)
        self.report({'WARNING'} if warn else {'INFO'},
                    'Wrote %d PDF%s%s to %s%s' % (len(done), '' if len(done) == 1 else 's', mats_note,
                                                 bpy.path.abspath(done[0][0]).rsplit('/', 1)[0],
                                                 (' – %d warning(s), see page 2' % warn) if warn else ''))
        context.window_manager['eva_last_export'] = done[0][0]
        return {'FINISHED'}


class EVA_OT_open_folder(bpy.types.Operator):
    bl_idname = 'eva_tentacle.open_folder'
    bl_label = 'Open Folder'
    bl_description = 'Show the exported PDFs'

    def execute(self, context):
        import os
        path = context.window_manager.get('eva_last_export')
        folder = os.path.dirname(path) if path else None
        if not folder or not os.path.isdir(folder):
            self.report({'WARNING'}, 'Nothing exported yet')
            return {'CANCELLED'}
        bpy.ops.wm.path_open(filepath=folder)
        return {'FINISHED'}


COPY_GROUPS = {
    'SHAPE': ('base_diameter', 'tip_diameter', 'taper_power', 'bulge', 'flare', 'flare_length',
              'height_ratio', 'bottom_roundness'),
    'PANELS': ('top_gores', 'bottom_gores', 'top_columns', 'bottom_columns', 'ring_spacing'),
    'RIG': ('length', 'bone_count', 'control_count', 'aim_tip', 'aim_strength', 'live_update'),
    'MOUNT': ('mount_height', 'emerge'),
}


class EVA_OT_copy_settings(bpy.types.Operator):
    bl_idname = 'eva_tentacle.copy_settings'
    bl_label = 'Copy to Selected'
    bl_description = 'Copy this tentacle\'s settings to the other selected tentacles'
    bl_options = {'REGISTER', 'UNDO'}

    groups: EnumProperty(
        name='Copy', options={'ENUM_FLAG'}, default={'SHAPE', 'PANELS', 'RIG'},
        items=[('SHAPE', 'Shape', 'Widths, taper, bulge, flare, section'),
               ('PANELS', 'Panels', 'Gores, facets, ring spacing'),
               ('RIG', 'Rig', 'Length, bones, control points, tip aim'),
               ('MOUNT', 'Mount', 'Height down the ring and lift-off (not the angle around)')])

    @classmethod
    def poll(cls, context):
        src = _active_tentacle(context)
        return src is not None and any(rig.find_tentacle(o) not in (None, src) for o in context.selected_objects)

    def execute(self, context):
        src = _active_tentacle(context)
        targets = {rig.find_tentacle(o) for o in context.selected_objects} - {None, src}
        keys = [k for g in self.groups for k in COPY_GROUPS[g]]
        sp = src.eva_tentacle
        for arm in targets:
            p = arm.eva_tentacle
            for k in keys:
                p[k] = getattr(sp, k)          # raw write: one rebuild below, not one per setting
            if 'RIG' in self.groups:
                rig.set_rest_chain(arm)
                rig.sync_controls(arm)
            if 'MOUNT' in self.groups:
                rig.place_on_ring(arm)
            context.view_layer.update()
            rig.build_mesh(arm)
        self.report({'INFO'}, 'Copied %s from %s to %d tentacle%s' % (
            ', '.join(sorted(g.lower() for g in self.groups)), sp.code, len(targets),
            '' if len(targets) == 1 else 's'))
        return {'FINISHED'}


class EVA_OT_suggest_panels(bpy.types.Operator):
    bl_idname = 'eva_tentacle.suggest_panels'
    bl_label = 'Suggest Panels'
    bl_description = ('Try different gore counts on the posed tentacle(s) and pick the fewest seams '
                      'whose panels can be made flat (stretch under the target)')
    bl_options = {'REGISTER', 'UNDO'}

    target: FloatProperty(name='Max stretch', default=3.0, min=0.5, max=20.0, subtype='PERCENTAGE',
                          description='How much a flat foam panel may have to stretch to take its shape. '
                                      'About 3% is easy to heat-form; more needs real stretching')
    together: bpy.props.BoolProperty(name='Same for all selected', default=True,
                                     description='One layout for every selected tentacle (matching pieces), '
                                                 'otherwise the best for each')

    @classmethod
    def poll(cls, context):
        return _active_tentacle(context) is not None

    def execute(self, context):
        arms = {rig.find_tentacle(o) for o in context.selected_objects} | {_active_tentacle(context)}
        arms = sorted(arms - {None}, key=lambda a: a.eva_tentacle.code)
        wm = context.window_manager
        wm.progress_begin(0, len(arms) * len(rig.layout_candidates()))
        try:
            res = rig.suggest_layout(arms, context.scene, self.target / 100.0, self.together,
                                     progress=wm.progress_update)
        finally:
            wm.progress_end()
        for arm, (top, bot, st, n, tried) in res.items():
            p = arm.eva_tentacle
            p['top_gores'] = top
            p['bottom_gores'] = bot
            ok = st <= self.target / 100.0
            p.layout_note = '%d top + %d suction gores: %d panels, max stretch %.1f%%%s' % (
                top, bot, n, st * 100, '' if ok else ' (target not reachable)')
            rig.build_mesh(arm)
            print('EVA suggest %s: %s; tried %s' % (p.code, p.layout_note,
                  ', '.join('%d+%d:%.1f%%' % (t[0], t[1], w * 100) for t, w in tried)))
        first = res[arms[0]]
        self.report({'INFO'} if first[2] <= self.target / 100.0 else {'WARNING'},
                    '%s%s' % (arms[0].eva_tentacle.layout_note,
                              ' (all %d tentacles)' % len(arms) if self.together and len(arms) > 1 else ''))
        return {'FINISHED'}


class EVA_OT_optimise_mats(bpy.types.Operator):
    bl_idname = 'eva_tentacle.optimise_mats'
    bl_label = 'Optimise Pieces for Mats'
    bl_description = ('Try shorter maximum piece lengths for the tentacles and rings being exported, nest '
                      'everything on your mats, and keep the length that needs the fewest mats (then fewest pieces)')
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        from . import pattern_pdf
        obs = _targets(context)
        if not obs:
            self.report({'ERROR'}, 'Select tentacles / the ring, or set Export to All')
            return {'CANCELLED'}
        sc = context.scene
        ex = sc.eva_tentacle_export
        to_mm = sc.unit_settings.scale_length * 1000.0
        st = rig.export_settings(sc)
        W, H = st.mat_w - 2 * st.margin, st.mat_h - 2 * st.margin
        lengths = [0.0, 0.75 * max(W, H), 0.5 * max(W, H)]
        wm = context.window_manager
        wm.progress_begin(0, len(lengths) * len(obs))
        results = []
        try:
            for i, L in enumerate(lengths):
                panels = []
                for j, ob in enumerate(obs):
                    pat = _pattern(ob, sc, {'max_len': L, 'relax_iters': 200})[0]
                    panels += pat.panels
                    wm.progress_update(i * len(obs) + j + 1)
                owner = {id(p): {'thickness': st.thickness, 'mat_w': st.mat_w, 'mat_h': st.mat_h} for p in panels}
                groups = pattern_pdf._groups(panels, owner, st.margin)
                results.append((sum(len(g['mats']) for g in groups), len(panels), L))
        finally:
            wm.progress_end()
        best = min(results)
        ex.max_panel_length = best[2] / to_mm
        for n, k, L in results:
            print('EVA optimise: max piece %s -> %d mats, %d pieces' % ('%.0f mm' % L if L else 'mat size', n, k))
        self.report({'INFO'}, 'Max piece length %s: %d mats, %d pieces (tried %s)' % (
            '%.0f mm' % best[2] if best[2] else 'mat size', best[0], best[1],
            ', '.join('%s=%d mats' % ('%.0f' % L if L else 'mat', n) for n, k, L in results)))
        return {'FINISHED'}


class EVA_OT_stock_add(bpy.types.Operator):
    bl_idname = 'eva_tentacle.stock_add'
    bl_label = 'Add Stock'
    bl_description = 'Add another, thinner foam stock (thickness and sheet size)'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        ex = context.scene.eva_tentacle_export
        thinnest = min([ex.thin_thickness] + [s.thickness for s in ex.stocks])
        new = ex.stocks.add()
        new.thickness = max(math.floor(thinnest * 1000 / 2) / 1000, 0.001)   # whole mm, e.g. 5 -> 2: edit to suit
        new.width, new.height = ex.thin_mat_width, ex.thin_mat_height
        return {'FINISHED'}


class EVA_OT_stock_remove(bpy.types.Operator):
    bl_idname = 'eva_tentacle.stock_remove'
    bl_label = 'Remove Stock'
    bl_options = {'REGISTER', 'UNDO'}
    index: IntProperty()

    def execute(self, context):
        context.scene.eva_tentacle_export.stocks.remove(self.index)
        return {'FINISHED'}


class EVA_OT_ursula_fabric(bpy.types.Operator):
    bl_idname = 'eva_tentacle.ursula_fabric'
    bl_label = 'Apply Ursula Fabric'
    bl_description = ('Costume material on the tentacle skins, with appliqué suckers underneath: shiny '
                      'faux PU leather or crushed velvet (selected tentacles, or all if none are selected)')
    bl_options = {'REGISTER', 'UNDO'}

    style: EnumProperty(name='Style', default='LEATHER',
                        items=[('LEATHER', 'Faux PU leather', 'Shiny plum-black leather with a pebbled grain'),
                               ('VELVET', 'Crushed velvet', 'Velvet on top, satin underneath')])

    def execute(self, context):
        from . import material
        arms = {rig.find_tentacle(o) for o in context.selected_objects} - {None}
        arms = arms or set(rig.all_tentacles(context.scene))
        for arm in arms:
            rig.build_mesh(arm)            # make sure the skin carries the fabric coordinates
        material.apply([a.eva_tentacle.mesh_obj for a in arms], self.style)
        self.report({'INFO'}, 'Ursula fabric on %d tentacle%s' % (len(arms), '' if len(arms) == 1 else 's'))
        return {'FINISHED'}


classes = (EVA_OT_ursula_fabric, EVA_OT_stock_add, EVA_OT_stock_remove, EVA_OT_add_tentacle, EVA_OT_copy_settings, EVA_OT_suggest_panels, EVA_OT_optimise_mats, EVA_OT_add_ring, EVA_OT_add_set, EVA_OT_mount, EVA_OT_curl, EVA_OT_bake_ik, EVA_OT_reset_pose,
           EVA_OT_snap_target, EVA_OT_preview_panels, EVA_OT_export_pdf, EVA_OT_open_folder)


def register():
    for c in classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
