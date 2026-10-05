"""blender_render: studio render of a printable mesh. Runs inside Blender.

    blender -b --factory-startup -P lib/blender_render.py -- MESH OUT.png [options]

`bin/cad render` builds that command line. The mesh is read in model units
(mm), scaled to metres, turned so --up points up, lit by a warm key, a cool
rim and a soft fill against a dark backdrop, and rendered with Cycles on the
GPU. --material clay gives a neutral grey (form only); --material color uses
the mesh's vertex colours (a GLB from a model script's preview).

Options: --material clay|color, --up x|y|z (the model axis that points up),
--azimuth / --elevation (camera, degrees; 0/0 looks at the +z face),
--focus X,Y,Z and --frame MM (centre and height of the framed region, in model
mm; default: the whole part), --size WxH, --samples N, --lens MM.
"""

import argparse
import math
import sys

import bpy  # type: ignore[import-not-found]  # provided by Blender
from mathutils import Matrix, Vector  # type: ignore[import-not-found]

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
ap = argparse.ArgumentParser(prog="blender_render")
ap.add_argument("mesh")
ap.add_argument("out")
ap.add_argument("--material", default="clay", choices=["clay", "color"])
ap.add_argument("--up", default="z", choices=["x", "y", "z"])
ap.add_argument("--azimuth", type=float, default=-30.0)
ap.add_argument("--elevation", type=float, default=10.0)
ap.add_argument("--focus")
ap.add_argument("--frame", type=float)
ap.add_argument("--size", default="1080x1620")
ap.add_argument("--samples", type=int, default=96)
ap.add_argument("--lens", type=float, default=70.0)
a = ap.parse_args(argv)

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene

# --- import, flatten to one object in model coordinates -------------------
before = set(bpy.data.objects)
ext = a.mesh.lower().rsplit(".", 1)[-1]
if ext == "stl":
    bpy.ops.wm.stl_import(filepath=a.mesh)
elif ext in ("glb", "gltf"):
    bpy.ops.import_scene.gltf(filepath=a.mesh)
elif ext == "obj":
    bpy.ops.wm.obj_import(filepath=a.mesh)
elif ext == "ply":
    bpy.ops.wm.ply_import(filepath=a.mesh)
else:
    raise SystemExit(f"blender_render: cannot read .{ext}")
meshes = [o for o in bpy.data.objects if o not in before and o.type == "MESH"]
if not meshes:
    raise SystemExit("blender_render: no mesh in the file")
for o in meshes:
    o.data.transform(o.matrix_world)
    o.parent = None
    o.matrix_world = Matrix.Identity(4)
for o in list(bpy.data.objects):
    if o.type != "MESH":
        bpy.data.objects.remove(o)
bpy.ops.object.select_all(action="DESELECT")
for o in meshes:
    o.select_set(True)
bpy.context.view_layer.objects.active = meshes[0]
if len(meshes) > 1:
    bpy.ops.object.join()
obj = bpy.context.view_layer.objects.active

# A glTF file is Y-up and Blender's importer turns it to Z-up, which is the
# model frame again; STL and OBJ arrive in the model frame directly.
up = {"z": Matrix.Identity(4),
      "y": Matrix.Rotation(math.radians(90), 4, "X"),     # model +y -> up, +z face -> camera
      "x": Matrix.Rotation(math.radians(-90), 4, "Y")}[a.up]
M = up @ Matrix.Scale(0.001, 4)
obj.data.transform(M)
try:
    bpy.ops.object.shade_auto_smooth(angle=math.radians(40))
except (AttributeError, RuntimeError):
    bpy.ops.object.shade_smooth()

# --- material ---------------------------------------------------------------
mat = bpy.data.materials.new("studio")
mat.use_nodes = True
nt = mat.node_tree
bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
attrs = obj.data.color_attributes
if a.material == "color" and len(attrs):
    ca = nt.nodes.new("ShaderNodeVertexColor")
    ca.layer_name = attrs.active_color.name if attrs.active_color else attrs[0].name
    nt.links.new(ca.outputs["Color"], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = 0.45
    if "Coat Weight" in bsdf.inputs:
        bsdf.inputs["Coat Weight"].default_value = 0.15
else:
    bsdf.inputs["Base Color"].default_value = (0.30, 0.30, 0.31, 1.0)   # linear: a mid clay grey
    bsdf.inputs["Roughness"].default_value = 0.5
obj.data.materials.clear()
obj.data.materials.append(mat)

# --- framing ------------------------------------------------------------------
corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
lo = Vector([min(c[i] for c in corners) for i in range(3)])
hi = Vector([max(c[i] for c in corners) for i in range(3)])
if a.focus:
    target = M @ Vector([float(v) for v in a.focus.split(",")])
else:
    target = (lo + hi) / 2
frame = (a.frame / 1000.0) if a.frame else max(hi.z - lo.z, (hi - lo).length * 0.6)
w, h = (int(v) for v in a.size.lower().split("x"))
cam_data = bpy.data.cameras.new("cam")
cam_data.lens = a.lens
cam_data.clip_start = 0.005
cam_data.clip_end = 20.0
half_fov = math.atan(18.0 / a.lens)                  # 36 mm sensor across the longer side
if w > h:
    half_fov = math.atan(math.tan(half_fov) * h / w)  # fit the frame height in a landscape shot
dist = 0.5 * frame * 1.08 / math.tan(half_fov)
az, el = math.radians(a.azimuth), math.radians(a.elevation)
view = Vector((math.cos(el) * math.sin(az), -math.cos(el) * math.cos(az), math.sin(el)))
cam = bpy.data.objects.new("cam", cam_data)
cam.location = target + view * dist
cam.rotation_euler = (target - cam.location).to_track_quat("-Z", "Y").to_euler()
scene.collection.objects.link(cam)
scene.camera = cam


def area_light(name, power, size, color, direction, distance):
    ld = bpy.data.lights.new(name, "AREA")
    ld.energy = power
    ld.size = size
    ld.color = color
    lo_ = bpy.data.objects.new(name, ld)
    d = Vector(direction).normalized()
    lo_.location = target + d * distance
    lo_.rotation_euler = (target - lo_.location).to_track_quat("-Z", "Y").to_euler()
    scene.collection.objects.link(lo_)


# lights scale with the framed size so a close-up is lit like the full view
s = frame / 0.2
area_light("key", 8 * s * s, 0.25 * s, (1.0, 0.93, 0.85), (-0.7 + view.x * 0.3, -0.8, 0.9), 0.55 * s)
area_light("rim", 12 * s * s, 0.18 * s, (0.75, 0.85, 1.0), (0.9, 0.9, 0.5), 0.5 * s)
area_light("fill", 1.0 * s * s, 0.6 * s, (0.95, 0.97, 1.0), (0.9, -0.7, -0.1), 0.6 * s)

world = bpy.data.worlds.new("studio")
world.use_nodes = True
bg = next(n for n in world.node_tree.nodes if n.type == "BACKGROUND")
bg.inputs["Color"].default_value = (0.018, 0.02, 0.025, 1.0)
bg.inputs["Strength"].default_value = 0.35
scene.world = world

# --- render -----------------------------------------------------------------
scene.render.engine = "CYCLES"
prefs = bpy.context.preferences.addons["cycles"].preferences
try:
    prefs.compute_device_type = "METAL"
    prefs.get_devices()
    for dev in prefs.devices:
        dev.use = True
    scene.cycles.device = "GPU"
except (TypeError, AttributeError):
    scene.cycles.device = "CPU"
scene.cycles.samples = a.samples
scene.cycles.use_denoising = True
scene.render.resolution_x = w
scene.render.resolution_y = h
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"
scene.render.filepath = a.out
try:
    scene.view_settings.view_transform = "AgX"
    looks = [i.identifier for i in scene.view_settings.bl_rna.properties["look"].enum_items]
    for want in ("AgX - Medium High Contrast", "Medium High Contrast"):
        if want in looks:
            scene.view_settings.look = want
            break
except TypeError:
    pass
bpy.ops.render.render(write_still=True)
print(f"blender_render: wrote {a.out}")
