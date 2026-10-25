"""EVA Tentacle Builder: pose foam tentacles with an IK chain and export
flattened EVA panel patterns (with seam bevel angles) as PDFs."""

bl_info = {
    'name': 'EVA Tentacle Builder',
    'author': 'Tim Fennell',
    'version': (0, 3, 13),
    'blender': (4, 2, 0),
    'location': 'View3D > Sidebar > Tentacle',
    'description': 'Pose foam tentacles and export flattened EVA panel patterns as PDFs',
    'category': 'Rigging',
}

try:
    import bpy  # noqa: F401
except ImportError:      # geometry / PDF modules are usable without Blender (tests)
    _modules = ()
else:
    from . import ops, props, rig, ring, ui  # noqa: F401
    _modules = (props, rig, ops, ui)


def register():
    for m in _modules:
        m.register()


def unregister():
    for m in reversed(_modules):
        m.unregister()
