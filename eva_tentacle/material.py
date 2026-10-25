"""Ursula costume materials for the tentacle skins, with padded appliqué
suckers on the suction side:
LEATHER - shiny faux PU leather with a pebbled grain (lighter underneath);
VELVET - crushed velvet on top, satin underneath.

Reads the corner attributes the skins carry (rig._fabric_attributes):
eva_fabric = (distance around, distance along, sucker cells along) and
eva_under = (1 on the suction side, position across it 0..1, 0).
"""

import bpy

NAMES = {'LEATHER': 'Ursula Leather', 'VELVET': 'Ursula Velvet'}

VELVET = (0.032, 0.006, 0.042, 1.0)      # deep aubergine
SHEEN = (0.30, 0.07, 0.40, 1.0)          # purple-magenta glow at grazing angles
SATIN = (0.40, 0.20, 0.46, 1.0)          # mauve underside
SUCKER = (0.70, 0.44, 0.72, 1.0)         # pale lilac pads
SUCKER_CUP = (0.18, 0.05, 0.22, 1.0)     # dark centre
LEATHER = (0.024, 0.006, 0.032, 1.0)     # plum-black PU
LEATHER_HI = (0.05, 0.012, 0.062, 1.0)   # lighter patches where it's been stretched/worn
LEATHER_UNDER = (0.30, 0.13, 0.35, 1.0)  # mauve PU underneath


class _Tree:
    def __init__(self, mat):
        self.nt = mat.node_tree
        self.nt.nodes.clear()
        self.x = 0

    def node(self, kind, x, y, **props):
        n = self.nt.nodes.new(kind)
        n.location = (x, y)
        for k, v in props.items():
            setattr(n, k, v)
        return n

    def link(self, a, b):
        self.nt.links.new(a, b)

    def math(self, op, a, b=None, x=0, y=0, clamp=False):
        n = self.node('ShaderNodeMath', x, y, operation=op, use_clamp=clamp)
        for i, v in enumerate((a, b)):
            if v is None:
                continue
            if isinstance(v, (int, float)):
                n.inputs[i].default_value = v
            else:
                self.link(v, n.inputs[i])
        return n.outputs[0]

    def mix(self, kind, fac, a, b, x=0, y=0):
        n = self.node('ShaderNodeMix', x, y, data_type=kind)
        sock = {'RGBA': 'RGBA', 'FLOAT': 'VALUE'}[kind]
        ins = [s for s in n.inputs if s.type == sock and s.name in ('A', 'B')]
        outs = [s for s in n.outputs if s.type == sock][0]
        self.link(fac, n.inputs['Factor']) if not isinstance(fac, (int, float)) else \
            setattr(n.inputs['Factor'], 'default_value', fac)
        for s, v in zip(ins, (a, b)):
            if isinstance(v, (tuple, list, int, float)):
                s.default_value = v
            else:
                self.link(v, s)
        return outs

    def smooth(self, value, lo, hi, out_lo, out_hi, x=0, y=0):
        n = self.node('ShaderNodeMapRange', x, y, interpolation_type='SMOOTHSTEP', clamp=True)
        self.link(value, n.inputs['Value'])
        n.inputs['From Min'].default_value = lo
        n.inputs['From Max'].default_value = hi
        n.inputs['To Min'].default_value = out_lo
        n.inputs['To Max'].default_value = out_hi
        return n.outputs['Result']


def build(style='LEATHER', mat=None):
    name = NAMES[style]
    mat = mat or bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    t = _Tree(mat)

    fab = t.node('ShaderNodeAttribute', -1800, 200, attribute_name='eva_fabric', attribute_type='GEOMETRY')
    und = t.node('ShaderNodeAttribute', -1800, -300, attribute_name='eva_under', attribute_type='GEOMETRY')
    sf = t.node('ShaderNodeSeparateXYZ', -1600, 200)
    su = t.node('ShaderNodeSeparateXYZ', -1600, -300)
    t.link(fab.outputs['Vector'], sf.inputs[0])
    t.link(und.outputs['Vector'], su.inputs[0])
    around, along, cells = sf.outputs['X'], sf.outputs['Y'], sf.outputs['Z']
    under, across = su.outputs['X'], su.outputs['Y']

    # fabric-space coordinates (metres around, metres along)
    uv = t.node('ShaderNodeCombineXYZ', -1400, 400)
    t.link(around, uv.inputs['X'])
    t.link(along, uv.inputs['Y'])

    # crushed velvet: soft irregular patches of nap catching the light differently
    crush = t.node('ShaderNodeTexNoise', -1150, 600, noise_dimensions='3D')
    crush.inputs['Scale'].default_value = 14.0
    crush.inputs['Detail'].default_value = 6.0
    crush.inputs['Roughness'].default_value = 0.62
    crush.inputs['Distortion'].default_value = 2.2
    t.link(uv.outputs['Vector'], crush.inputs['Vector'])
    crush_v = t.smooth(crush.outputs['Fac'], 0.35, 0.68, 0.0, 1.0, -950, 600)

    # fine weave (about a 1 mm thread pitch)
    weave_a = t.node('ShaderNodeTexWave', -1150, 300, wave_type='BANDS', bands_direction='X')
    weave_b = t.node('ShaderNodeTexWave', -1150, 120, wave_type='BANDS', bands_direction='Y')
    for w in (weave_a, weave_b):
        w.inputs['Scale'].default_value = 900.0
        w.inputs['Distortion'].default_value = 0.0
        t.link(uv.outputs['Vector'], w.inputs['Vector'])
    weave = t.math('MULTIPLY', weave_a.outputs['Fac'], weave_b.outputs['Fac'], -950, 220)

    # appliqué suckers: two staggered rows across the suction side, square-ish
    # cells one local radius on a side, so they shrink with the tentacle
    rowf = t.math('MULTIPLY', across, 2.0, -1400, -500)
    row = t.math('FLOOR', rowf, None, -1250, -600)
    cx = t.math('SUBTRACT', t.math('FRACT', rowf, None, -1250, -480), 0.5, -1100, -480)
    ay = t.math('ADD', t.math('MULTIPLY', cells, 2.0, -1400, -700), t.math('MULTIPLY', row, 0.5, -1100, -620),
                -950, -650)
    cy = t.math('SUBTRACT', t.math('FRACT', ay, None, -800, -650), 0.5, -650, -650)
    d = t.math('SQRT', t.math('ADD', t.math('POWER', cx, 2.0, -800, -480), t.math('POWER', cy, 2.0, -500, -700),
                              -500, -520), None, -350, -520)
    disc = t.smooth(d, 0.31, 0.335, 1.0, 0.0, -150, -450)
    cup = t.smooth(d, 0.10, 0.135, 1.0, 0.0, -150, -650)
    on_under = t.math('MULTIPLY', disc, under, 50, -450)
    dome = t.smooth(d, 0.0, 0.335, 1.0, 0.0, -150, -850)

    suck_h = t.math('SUBTRACT', t.math('MULTIPLY', dome, on_under, 100, -800),
                    t.math('MULTIPLY', t.math('MULTIPLY', cup, on_under, 100, -950), 0.7, 250, -950), 400, -850)
    sucker_col = t.mix('RGBA', cup, SUCKER, SUCKER_CUP, 100, -250)
    bsdf = t.node('ShaderNodeBsdfPrincipled', 1200, 200)
    bump = t.node('ShaderNodeBump', 950, -300)

    if style == 'VELVET':
        velvet = t.mix('RGBA', crush_v, VELVET, (0.075, 0.015, 0.09, 1.0), -700, 700)
        under_col = t.mix('RGBA', on_under, SATIN, sucker_col, 300, -150)
        base = t.mix('RGBA', under, velvet, under_col, 550, 300)
        rough_top = t.mix('FLOAT', crush_v, 0.82, 0.66, -700, 450)
        rough = t.mix('FLOAT', under, rough_top, t.mix('FLOAT', on_under, 0.30, 0.45, 300, 0), 550, 100)
        sheen = t.mix('FLOAT', under, 0.8, 0.3, 550, -50)
        t.link(sheen, bsdf.inputs['Sheen Weight'])
        bsdf.inputs['Sheen Roughness'].default_value = 0.35
        bsdf.inputs['Sheen Tint'].default_value = SHEEN
        bsdf.inputs['Specular IOR Level'].default_value = 0.3
        # weave and nap on top; padded suckers (cups pressed in) underneath
        top_h = t.math('ADD', t.math('MULTIPLY', weave, 0.25, -750, 200),
                       t.math('MULTIPLY', crush_v, 0.6, -750, 500), -550, 350)
        under_h = t.math('ADD', suck_h, t.math('MULTIPLY', weave, 0.08, 250, -650), 550, -700)
        bump.inputs['Strength'].default_value = 0.6
        bump.inputs['Distance'].default_value = 0.004
        mat.diffuse_color = (0.2, 0.05, 0.25, 1.0)
    else:
        # pebbled PU grain: small cells with soft crevices between them
        grain = t.node('ShaderNodeTexVoronoi', -1150, 900, feature='DISTANCE_TO_EDGE')
        grain.inputs['Scale'].default_value = 950.0
        grain.inputs['Randomness'].default_value = 0.9
        t.link(uv.outputs['Vector'], grain.inputs['Vector'])
        pebble = t.smooth(grain.outputs['Distance'], 0.0, 0.14, 0.0, 1.0, -950, 900)
        # soft wear: where the coating stretched over the padding it lightens a touch
        top = t.mix('RGBA', crush_v, LEATHER, LEATHER_HI, -700, 700)
        under_col = t.mix('RGBA', on_under, LEATHER_UNDER, sucker_col, 300, -150)
        base = t.mix('RGBA', under, top, under_col, 550, 300)
        rough_grain = t.mix('FLOAT', pebble, 0.55, 0.26, -700, 450)          # crevices duller
        rough = t.mix('FLOAT', on_under, rough_grain, 0.22, 550, 100)
        bsdf.inputs['Coat Weight'].default_value = 0.6                       # the glossy finish
        bsdf.inputs['Coat Roughness'].default_value = 0.12
        bsdf.inputs['Specular IOR Level'].default_value = 0.55
        top_h = t.math('ADD', t.math('MULTIPLY', pebble, 0.22, -750, 900),
                       t.math('MULTIPLY', crush_v, 0.25, -750, 500), -550, 350)
        under_h = t.math('ADD', suck_h, t.math('MULTIPLY', pebble, 0.2, 250, -650), 550, -700)
        bump.inputs['Strength'].default_value = 0.5
        bump.inputs['Distance'].default_value = 0.002
        mat.diffuse_color = (0.12, 0.03, 0.15, 1.0)

    height = t.mix('FLOAT', under, top_h, under_h, 750, -300)
    t.link(height, bump.inputs['Height'])
    t.link(base, bsdf.inputs['Base Color'])
    t.link(rough, bsdf.inputs['Roughness'])
    t.link(bump.outputs['Normal'], bsdf.inputs['Normal'])
    out = t.node('ShaderNodeOutputMaterial', 1500, 200)
    t.link(bsdf.outputs['BSDF'], out.inputs['Surface'])
    return mat


def apply(objects, style='LEATHER'):
    """Put the costume material on these skins (first slot)."""
    mat = build(style)
    for ob in objects:
        if ob is None or ob.type != 'MESH':
            continue
        if ob.data.materials:
            ob.data.materials[0] = mat
        else:
            ob.data.materials.append(mat)
    return mat
