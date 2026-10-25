import bpy
from bpy.props import (BoolProperty, EnumProperty, FloatProperty, IntProperty,
                       PointerProperty, StringProperty)


def _rebuild(self, context):
    from . import rig
    ob = self.id_data
    if self.is_tentacle:
        rig.build_mesh(ob)


def _rest(self, context):
    from . import rig
    ob = self.id_data
    if self.is_tentacle:
        rig.set_rest_chain(ob)
        rig.ensure_ik(ob)
        rig.build_mesh(ob)


def _controls(self, context):
    from . import rig
    if self.is_tentacle:
        rig.sync_controls(self.id_data)


def _mount(self, context):
    from . import rig
    if self.is_tentacle:
        rig.place_on_ring(self.id_data)


def _ring(self, context):
    from . import ring
    if self.is_ring:
        ring.rebuild(self.id_data)


def _ik(self, context):
    from . import rig
    if self.is_tentacle:
        rig.set_ik(self.id_data, self.use_ik)


class EVAStock(bpy.types.PropertyGroup):
    thickness: FloatProperty(name='Thickness', default=0.002, min=0.0005, unit='LENGTH', subtype='DISTANCE')
    width: FloatProperty(name='W', default=0.889, min=0.05, unit='LENGTH', subtype='DISTANCE')
    height: FloatProperty(name='H', default=1.499, min=0.05, unit='LENGTH', subtype='DISTANCE')


class EVAControl(bpy.types.PropertyGroup):
    obj: PointerProperty(type=bpy.types.Object)


class EVATentacleProps(bpy.types.PropertyGroup):
    is_tentacle: BoolProperty(default=False, options={'HIDDEN'})
    code: StringProperty(name='Code', default='T1',
                         description='Short name printed on every panel (T1, T2 ...)')
    mesh_obj: PointerProperty(type=bpy.types.Object, options={'HIDDEN'})
    ik_target: PointerProperty(type=bpy.types.Object, options={'HIDDEN'})

    length: FloatProperty(name='Length', default=1.3, min=0.05, soft_max=4.0, unit='LENGTH',
                          subtype='DISTANCE', update=_rest,
                          description='Tentacle length along its centre line')
    bone_count: IntProperty(name='Bones', default=12, min=3, max=48, update=_rest,
                            description='Joints in the IK chain; more bones allow tighter curls')
    control_count: IntProperty(name='Control points', default=0, min=0, max=6, update=_controls,
                               description='Extra IK handles along the tentacle to place its middle')
    controls: bpy.props.CollectionProperty(type=EVAControl, options={'HIDDEN'})
    mount_ring: PointerProperty(name='Mount ring', type=bpy.types.Object, update=_mount,
                                poll=lambda self, ob: ob.type == 'MESH' and ob.eva_ring.is_ring,
                                description='Funnel ring the base of this tentacle is glued to')
    mount_angle: FloatProperty(name='Around', default=0.0, subtype='ANGLE', update=_mount,
                               description='Position around the ring (0 = side, 90 = back)')
    mount_height: FloatProperty(name='Down the ring', default=0.55, min=0.0, max=1.0, subtype='FACTOR',
                                update=_mount, description='0 = top edge of the ring, 1 = bottom edge')
    emerge: FloatProperty(name='Lift off', default=0.6, min=-0.5, max=1.57, subtype='ANGLE', update=_mount,
                          description='0 = base runs down the ring surface, 90 = sticks straight out')
    aim_tip: BoolProperty(name='Aim tip', default=True, update=_controls,
                          description='The tip points where the tip handle points (rotate the handle)')
    aim_strength: FloatProperty(name='Aim strength', default=1.0, min=0.0, max=1.0, subtype='FACTOR',
                                update=_controls)
    use_ik: BoolProperty(name='IK', default=True, update=_ik,
                         description='Pull the tip with the IK target. Off: pose bones by hand')
    live_update: BoolProperty(name='Live update', default=True,
                              description='Rebuild the foam skin while you pose')

    base_diameter: FloatProperty(name='Base width', default=0.20, min=0.005, unit='LENGTH',
                                 subtype='DISTANCE', update=_rebuild,
                                 description='Width of the tentacle at the base (side to side)')
    tip_diameter: FloatProperty(name='Tip width', default=0.025, min=0.001, unit='LENGTH',
                                subtype='DISTANCE', update=_rebuild)
    taper_power: FloatProperty(name='Taper curve', default=1.2, min=0.2, max=4.0, update=_rebuild,
                               description='1 = straight cone. Below 1 stays fat then narrows late; '
                                           'above 1 narrows quickly into a whip')
    bulge: FloatProperty(name='Mid bulge', default=0.10, min=-0.5, max=1.0, update=_rebuild,
                         description='Extra girth around mid-length')
    flare: FloatProperty(name='Base flare', default=0.15, min=0.0, max=2.0, update=_rebuild,
                         description='Extra girth right at the base where it meets the costume')
    flare_length: FloatProperty(name='Flare length', default=0.08, min=0.01, max=0.6,
                                subtype='FACTOR', update=_rebuild,
                                description='How far up the tentacle the flare reaches (fraction of length)')
    height_ratio: FloatProperty(name='Height / width', default=0.8, min=0.2, max=2.0, update=_rebuild,
                                description='Height of the rounded top relative to half the width')
    bottom_roundness: FloatProperty(name='Suction side roundness', default=0.25, min=0.0, max=1.0,
                                    subtype='FACTOR', update=_rebuild,
                                    description='0 = flat underside with crisp side corners, '
                                                '1 = as round as the top')

    top_gores: IntProperty(name='Top gores', default=4, min=1, max=16, update=_rebuild,
                           description='Lengthwise panels across the rounded top')
    bottom_gores: IntProperty(name='Suction gores', default=1, min=1, max=8, update=_rebuild,
                              description='Lengthwise panels across the suction side')
    top_columns: IntProperty(name='Top facets', default=3, min=1, max=12, update=_rebuild,
                             description='Facets across each top gore. 1 = flat panels with bevelled seams')
    bottom_columns: IntProperty(name='Suction facets', default=4, min=1, max=16, update=_rebuild)
    ring_spacing: FloatProperty(name='Ring spacing', default=0.02, min=0.004, max=0.2, unit='LENGTH',
                                subtype='DISTANCE', update=_rebuild,
                                description='Length resolution of the skin and the patterns')
    adaptive_rings: BoolProperty(name='Extra rings in bends', default=True, update=_rebuild,
                                 description='Add rings where the tentacle bends or twists sharply, '
                                             'so tight curls get smooth outlines')
    layout_note: StringProperty(default='', options={'HIDDEN'})
    thin_note: StringProperty(default='', options={'HIDDEN'})

    bend_ratio: FloatProperty(default=1e9, options={'HIDDEN'})
    bend_at: FloatProperty(default=0.0, options={'HIDDEN'})


class EVARingProps(bpy.types.PropertyGroup):
    is_ring: BoolProperty(default=False, options={'HIDDEN'})
    code: StringProperty(name='Code', default='RING')
    top_diameter: FloatProperty(name='Top width', default=0.40, min=0.01, unit='LENGTH', subtype='DISTANCE',
                                update=_ring, description='Width across the top (waist) edge')
    top_height: FloatProperty(name='Top height', default=1.00, unit='LENGTH', subtype='DISTANCE',
                              update=_ring, description='Height of the top edge above the floor')
    bottom_diameter: FloatProperty(name='Bottom width', default=0.80, min=0.01, unit='LENGTH',
                                   subtype='DISTANCE', update=_ring,
                                   description='Width across the bottom edge (sits on the hoop skirt)')
    bottom_height: FloatProperty(name='Bottom height', default=0.80, unit='LENGTH', subtype='DISTANCE',
                                 update=_ring, description='Height of the bottom edge above the floor')
    curve: FloatProperty(name='Profile curve', default=0.2, min=-1.5, max=1.5, update=_ring,
                         description='0 = straight cone, + bulges outward (dome), - dishes in (trumpet flare)')
    depth_ratio: FloatProperty(name='Front-back / side', default=1.0, min=0.3, max=2.0, update=_ring,
                               description='Below 1 makes the ring oval, shallower front to back')
    gores: IntProperty(name='Panels around', default=8, min=2, max=32, update=_ring)
    columns: IntProperty(name='Facets', default=3, min=1, max=12, update=_ring,
                         description='Facets across each ring panel')
    ring_spacing: FloatProperty(name='Ring spacing', default=0.02, min=0.004, unit='LENGTH',
                                subtype='DISTANCE', update=_ring)
    seam_angle: FloatProperty(name='First seam', default=1.5708, subtype='ANGLE', update=_ring,
                              description='Where the first seam goes (90 = centre back)')


class EVASetProps(bpy.types.PropertyGroup):
    count: IntProperty(name='Tentacles', default=8, min=1, max=16)
    length: FloatProperty(name='Length', default=1.3, min=0.05, unit='LENGTH', subtype='DISTANCE')
    variation: FloatProperty(name='Length variation', default=0.15, min=0.0, max=0.6, subtype='FACTOR')
    spread: FloatProperty(name='Spread', default=6.2832, min=0.0, max=6.2832, subtype='ANGLE',
                          description='How far around the ring the tentacles go (360 = all the way)')
    controls: IntProperty(name='Control points', default=1, min=0, max=6)
    on_ring: BoolProperty(name='On a mount ring', default=True,
                          description='Make (or reuse) a funnel mount ring and stand the tentacles on it')
    seed: IntProperty(name='Curl seed', default=7)


class EVAExportProps(bpy.types.PropertyGroup):
    live_panels: BoolProperty(name='Live panel preview', default=True,
                              description='Colour each mat-sized panel on the skin, updated a moment '
                                          'after you stop posing or editing')
    thickness: FloatProperty(name='Foam thickness', default=0.010, min=0.0005, unit='LENGTH',
                             subtype='DISTANCE')
    model_surface: EnumProperty(
        name='Skin is', default='OUTER',
        items=[('OUTER', 'Outside of foam', 'The tentacle skin is the outside of the finished foam'),
               ('MID', 'Middle of foam', 'The tentacle skin is the middle of the foam thickness')])
    mat_width: FloatProperty(name='Mat width', default=0.56, min=0.05, unit='LENGTH', subtype='DISTANCE',
                             description='Main stock: 56 x 56 cm, 1 cm thick floor mats')
    mat_height: FloatProperty(name='Mat height', default=0.56, min=0.05, unit='LENGTH', subtype='DISTANCE')
    mat_margin: FloatProperty(name='Mat margin', default=0.01, min=0.0, unit='LENGTH', subtype='DISTANCE',
                              description='Unusable border of each mat (interlocking teeth etc.)')
    max_panel_length: FloatProperty(name='Max panel length', default=0.0, min=0.0, unit='LENGTH',
                                    subtype='DISTANCE', description='0 = only limited by the mat')
    max_bow: FloatProperty(name='Max bow', default=0.05, min=0.0, unit='LENGTH', subtype='DISTANCE',
                           description='Split long curved pieces once they bend further than this off a '
                                       'straight line, so straighter strips nest more per mat. 0 = off')
    thin_tips: BoolProperty(name='Step down to thinner stock', default=True,
                            description='Where a tentacle bends tighter than the main foam allows (narrow section '
                                        'or tight curl), switch to the thickest thinner stock that can take it')
    stocks: bpy.props.CollectionProperty(type=EVAStock)
    thin_thickness: FloatProperty(name='Thin foam', default=0.005, min=0.0005, unit='LENGTH', subtype='DISTANCE',
                                  description='First thinner stock for tight parts. Add Stock lists more '
                                              '(only listed stocks are used)')
    thin_ratio: FloatProperty(name='Bend limit', default=4.0, min=1.0, max=20.0,
                              description='Bend radius must be at least this many times the foam thickness '
                                          '(4 = foam no thicker than a quarter of the radius); tighter parts '
                                          'use the thin foam')
    thin_mat_width: FloatProperty(name='Thin sheet W', default=0.889, min=0.05, unit='LENGTH', subtype='DISTANCE',
                                  description='5 mm EVA sheets, 35 x 59 in (889 x 1499 mm)')
    thin_mat_height: FloatProperty(name='Thin sheet H', default=1.499, min=0.05, unit='LENGTH', subtype='DISTANCE')
    max_stretch: FloatProperty(name='Max stretch', default=3.0, min=0.0, max=20.0, subtype='PERCENTAGE',
                               description='Cut pieces shorter where a flat panel would have to stretch more '
                                           'than this to take its shape (heat-forming limit). 0 = off')
    align_breaks: BoolProperty(name='Align piece breaks', default=True,
                               description='Break every gore at the same rings (neat rings) '
                                           'instead of staggering the joins')
    seam_style: EnumProperty(
        name='Seams', default='AUTO',
        items=[('AUTO', 'Auto', 'Bevel only seams with a real crease; cut the rest square for smooth curves'),
               ('BEVEL', 'Bevel all', 'Bevel every seam by its crease angle'),
               ('SQUARE', 'Square all', 'Cut every edge at 90 degrees (smooth, rounded joins)')])
    crease_angle: FloatProperty(name='Crease above', default=10.0, min=0.0, max=90.0,
                                description='Auto: seams that fold more than this many degrees get a bevel')
    page_mode: EnumProperty(
        name='Paper', default='LETTER',
        items=[('LETTER', 'US Letter tiles', '8.5 x 11 in sheets with overlapping registration targets'),
               ('A4', 'A4 tiles', 'A4 sheets with overlapping registration targets'),
               ('TABLOID', 'Tabloid tiles', '11 x 17 in sheets'),
               ('FULL', 'Full size', 'One page per panel at full size (plotter / print shop)')])
    print_layout: EnumProperty(
        name='Print', default='MATS',
        items=[('MATS', 'Full mats', 'Each mat full size with its pieces nested on it, tiled onto paper: '
                                     'tape up, lay on the foam, cut'),
               ('PANELS', 'One panel at a time', 'Each panel on its own set of sheets'),
               ('BOTH', 'Both', 'Full mats, then every panel on its own')])
    mat_sharing: EnumProperty(
        name='Mats', default='SHARED',
        items=[('SHARED', 'Shared (least waste)', 'Nest the pieces of every exported tentacle and the ring together '
                                                 'in one mat-templates PDF: fewest mats, pieces labelled by tentacle'),
               ('SEPARATE', 'Per tentacle', 'Each tentacle / ring PDF nests and prints its own mats')])
    mirror: BoolProperty(name='Mirror for back face', default=False,
                         description='Flip the patterns for tracing on the back of the foam')
    tick_spacing: FloatProperty(name='Match mark spacing', default=0.05, min=0.01, unit='LENGTH',
                                subtype='DISTANCE')
    output_dir: StringProperty(name='Folder', default='//', subtype='DIR_PATH',
                               description='Where the PDFs go (// = next to the .blend)')
    scope: EnumProperty(name='Export', default='SELECTED',
                        items=[('SELECTED', 'Selected', 'Selected tentacles (or the active one)'),
                               ('ALL', 'All', 'Every tentacle in the scene')])


classes = (EVAStock, EVAControl, EVATentacleProps, EVARingProps, EVASetProps, EVAExportProps)


def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.Object.eva_tentacle = PointerProperty(type=EVATentacleProps)
    bpy.types.Object.eva_ring = PointerProperty(type=EVARingProps)
    bpy.types.Scene.eva_tentacle_export = PointerProperty(type=EVAExportProps)
    bpy.types.Scene.eva_tentacle_set = PointerProperty(type=EVASetProps)


def unregister():
    del bpy.types.Scene.eva_tentacle_set
    del bpy.types.Scene.eva_tentacle_export
    del bpy.types.Object.eva_ring
    del bpy.types.Object.eva_tentacle
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
