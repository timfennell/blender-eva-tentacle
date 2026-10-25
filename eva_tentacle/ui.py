import bpy

from . import rig, ring


class _Base:
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Tentacle'


def _tentacle(context):
    return rig.find_tentacle(context.active_object)


class EVA_PT_main(_Base, bpy.types.Panel):
    bl_label = 'EVA Tentacles'

    def draw(self, context):
        layout = self.layout
        row = layout.row(align=True)
        row.operator('eva_tentacle.add', text='Tentacle', icon='BONE_DATA')
        row.operator('eva_tentacle.add_ring', text='Mount Ring', icon='MESH_CONE')

        sp = context.scene.eva_tentacle_set
        box = layout.box()
        box.label(text='Ursula set', icon='OUTLINER_OB_ARMATURE')
        col = box.column(align=True)
        col.prop(sp, 'count')
        col.prop(sp, 'length')
        col.prop(sp, 'variation')
        col.prop(sp, 'spread')
        col.prop(sp, 'controls')
        col.prop(sp, 'seed')
        box.prop(sp, 'on_ring')
        box.operator('eva_tentacle.add_set', text='Add %d Tentacles' % sp.count)

        arm = _tentacle(context)
        if arm is None:
            if not ring.is_ring(context.active_object):
                layout.label(text='Select a tentacle or the mount ring', icon='INFO')
            return
        p = arm.eva_tentacle
        box = layout.box()
        row = box.row()
        row.prop(p, 'code', text='')
        row.label(text=arm.name)
        box.operator('eva_tentacle.copy_settings', icon='DUPLICATE')
        if p.bend_ratio < 1.0:
            box.label(text='Curl too tight at %.0f%% – it folds into itself' % (p.bend_at * 100), icon='ERROR')
        elif p.bend_ratio < 1.6:
            box.label(text='Tight curl at %.0f%%' % (p.bend_at * 100), icon='INFO')


class EVA_PT_rig(_Base, bpy.types.Panel):
    bl_label = 'Pose'
    bl_parent_id = 'EVA_PT_main'

    @classmethod
    def poll(cls, context):
        return _tentacle(context) is not None

    def draw(self, context):
        arm = _tentacle(context)
        p = arm.eva_tentacle
        col = self.layout.column()
        col.prop(p, 'length')
        col.prop(p, 'bone_count')
        col.prop(p, 'control_count')
        row = col.row(align=True)
        row.prop(p, 'aim_tip')
        row.prop(p, 'aim_strength', text='Strength')
        row = col.row(align=True)
        row.prop(p, 'use_ik', toggle=True, icon='CON_KINEMATIC')
        row.operator('eva_tentacle.snap_target', text='', icon='PIVOT_CURSOR')
        row.operator('eva_tentacle.bake_ik', text='Keep pose')
        row = col.row(align=True)
        row.operator('eva_tentacle.curl', icon='MOD_SCREW')
        row.operator('eva_tentacle.reset_pose', icon='LOOP_BACK')
        col.prop(p, 'live_update')
        hint = col.column(align=True)
        hint.scale_y = 0.8
        hint.label(text='Move the tip / control handles to place it.', icon='INFO')
        hint.label(text='Spin a handle around the tentacle (R, Y, Y) to twist.')
        hint.label(text='Keep pose bakes it, then rotate bones by hand.')


class EVA_PT_mount(_Base, bpy.types.Panel):
    bl_label = 'Mount'
    bl_parent_id = 'EVA_PT_main'

    @classmethod
    def poll(cls, context):
        return _tentacle(context) is not None

    def draw(self, context):
        p = _tentacle(context).eva_tentacle
        col = self.layout.column()
        col.prop(p, 'mount_ring')
        if p.mount_ring is None:
            col.operator('eva_tentacle.mount', icon='MESH_CONE')
            return
        col.prop(p, 'mount_angle')
        col.prop(p, 'mount_height')
        col.prop(p, 'emerge')


class EVA_PT_shape(_Base, bpy.types.Panel):
    bl_label = 'Shape'
    bl_parent_id = 'EVA_PT_main'

    @classmethod
    def poll(cls, context):
        return _tentacle(context) is not None

    def draw(self, context):
        p = _tentacle(context).eva_tentacle
        col = self.layout.column()
        col.prop(p, 'base_diameter')
        col.prop(p, 'tip_diameter')
        col.prop(p, 'taper_power')
        col.prop(p, 'bulge')
        row = col.row(align=True)
        row.prop(p, 'flare')
        row.prop(p, 'flare_length', text='Reach')
        col.separator()
        col.prop(p, 'height_ratio')
        col.prop(p, 'bottom_roundness')
        col.operator('eva_tentacle.ursula_fabric', icon='MATERIAL')


class EVA_PT_panels(_Base, bpy.types.Panel):
    bl_label = 'Panels'
    bl_parent_id = 'EVA_PT_main'

    @classmethod
    def poll(cls, context):
        return _tentacle(context) is not None

    def draw(self, context):
        p = _tentacle(context).eva_tentacle
        col = self.layout.column()
        row = col.row(align=True)
        row.prop(p, 'top_gores')
        row.prop(p, 'top_columns', text='Facets')
        row = col.row(align=True)
        row.prop(p, 'bottom_gores')
        row.prop(p, 'bottom_columns', text='Facets')
        col.prop(p, 'ring_spacing')
        col.prop(p, 'adaptive_rings')
        col.operator('eva_tentacle.suggest_panels', icon='LIGHT')
        if p.layout_note:
            col.label(text=p.layout_note, icon='INFO')
        if p.thin_note:
            col.label(text=p.thin_note, icon='MOD_THICKNESS')
        row = col.row(align=True)
        row.prop(context.scene.eva_tentacle_export, 'live_panels', text='Live preview')
        row.operator('eva_tentacle.preview_panels', text='Update', icon='MOD_UVPROJECT')


class EVA_PT_ring(_Base, bpy.types.Panel):
    bl_label = 'Mount Ring'
    bl_parent_id = 'EVA_PT_main'

    @classmethod
    def poll(cls, context):
        return ring.is_ring(context.active_object)

    def draw(self, context):
        ob = context.active_object
        rp = ob.eva_ring
        col = self.layout.column()
        col.prop(rp, 'code')
        sub = col.column(align=True)
        sub.prop(rp, 'top_diameter')
        sub.prop(rp, 'top_height')
        sub = col.column(align=True)
        sub.prop(rp, 'bottom_diameter')
        sub.prop(rp, 'bottom_height')
        col.prop(rp, 'curve')
        col.prop(rp, 'depth_ratio')
        col.separator()
        row = col.row(align=True)
        row.prop(rp, 'gores')
        row.prop(rp, 'columns')
        col.prop(rp, 'ring_spacing')
        col.prop(rp, 'seam_angle')
        n = len(ring.mounted(ob, context.scene))
        col.label(text='%d tentacle%s mounted' % (n, '' if n == 1 else 's'), icon='OUTLINER_OB_ARMATURE')
        col.operator('eva_tentacle.preview_panels', icon='MOD_UVPROJECT')


class EVA_PT_export(_Base, bpy.types.Panel):
    bl_label = 'Foam & PDF'
    bl_parent_id = 'EVA_PT_main'

    def draw(self, context):
        ex = context.scene.eva_tentacle_export
        col = self.layout.column()
        col.prop(ex, 'live_panels')
        col.prop(ex, 'thickness')
        col.prop(ex, 'model_surface')
        row = col.row(align=True)
        row.prop(ex, 'mat_width', text='Mat W')
        row.prop(ex, 'mat_height', text='H')
        col.prop(ex, 'mat_margin')
        col.prop(ex, 'thin_tips')
        if ex.thin_tips:
            box = col.box()
            box.label(text='Thinner stock (main mats above)', icon='MOD_THICKNESS')
            row = box.row(align=True)
            row.prop(ex, 'thin_thickness', text='')
            row.prop(ex, 'thin_mat_width', text='W')
            row.prop(ex, 'thin_mat_height', text='H')
            row.label(text='', icon='BLANK1')
            for i, stk in enumerate(ex.stocks):
                row = box.row(align=True)
                row.prop(stk, 'thickness', text='')
                row.prop(stk, 'width', text='W')
                row.prop(stk, 'height', text='H')
                row.operator('eva_tentacle.stock_remove', text='', icon='X').index = i
            box.operator('eva_tentacle.stock_add', icon='ADD')
            box.prop(ex, 'thin_ratio')
        col.prop(ex, 'max_panel_length')
        col.prop(ex, 'max_bow')
        col.prop(ex, 'max_stretch')
        col.prop(ex, 'align_breaks')
        col.separator()
        col.prop(ex, 'seam_style')
        if ex.seam_style == 'AUTO':
            col.prop(ex, 'crease_angle')
        col.prop(ex, 'tick_spacing')
        col.separator()
        col.prop(ex, 'page_mode')
        col.prop(ex, 'print_layout')
        col.prop(ex, 'mat_sharing')
        col.prop(ex, 'mirror')
        col.prop(ex, 'output_dir')
        row = col.row(align=True)
        row.prop(ex, 'scope', expand=True)
        col.operator('eva_tentacle.optimise_mats', icon='MOD_ARRAY')
        col.operator('eva_tentacle.export_pdf', icon='EXPORT')
        col.operator('eva_tentacle.open_folder', icon='FILE_FOLDER')


classes = (EVA_PT_main, EVA_PT_rig, EVA_PT_mount, EVA_PT_shape, EVA_PT_panels, EVA_PT_ring, EVA_PT_export)


def register():
    for c in classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
