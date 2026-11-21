"""Cycles check renders of character_hires.blend.

    python render_checks.py                       # full set -> ../renders/character_*.png
    python render_checks.py --only summer_front --samples 32 --res 640x360 --out /tmp/x.png
"""
import argparse
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bpy  # noqa: E402
from mathutils import Vector  # noqa: E402

import sled as SLED  # noqa: E402

RENDERS = os.path.join(HERE, "..", "renders")

SHOTS = {
    # name: (outfit, clip, frame, camera azimuth deg (0 = front), cam height, target z, focal, dist)
    "summer_front": ("summer", None, 0, 0, 1.15, 0.92, 50, 4.4),
    "summer_34": ("summer", None, 0, 35, 1.2, 0.92, 50, 4.4),
    "summer_side": ("summer", None, 0, 90, 1.15, 0.92, 50, 4.4),
    "winter_front": ("winter", None, 0, 0, 1.15, 0.92, 50, 4.4),
    "winter_34": ("winter", None, 0, 35, 1.2, 0.92, 50, 4.4),
    "winter_side": ("winter", None, 0, 90, 1.15, 0.92, 50, 4.4),
    "summer_head": ("summer", "idle", 0, 25, 1.68, 1.64, 85, 1.25),
    "winter_head": ("winter", "idle", 0, 25, 1.68, 1.64, 85, 1.25),
    "walk": ("summer", "walk", 8, 70, 1.1, 0.9, 50, 4.6),
    "sled_sit": ("winter", "sled_sit", 10, 40, 1.1, 0.35, 50, 3.6),
    "superman": ("winter", "superman", 22, 60, 1.4, 0.35, 50, 4.2),
}


def setup_world(sc, winter):
    w = bpy.data.worlds.new("Sky")
    sc.world = w
    nt = w.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputWorld")
    # simple physically-plausible sky: zenith blue -> horizon haze, ground bounce below
    tc = nt.nodes.new("ShaderNodeTexCoord")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(tc.outputs["Generated"], sep.inputs[0])
    rp = nt.nodes.new("ShaderNodeValToRGB")
    nt.links.new(sep.outputs["Z"], rp.inputs[0])
    e = rp.color_ramp.elements
    e[0].position, e[0].color = 0.0, ((0.30, 0.31, 0.33, 1) if winter else (0.25, 0.24, 0.22, 1))
    e[1].position, e[1].color = 1.0, ((0.38, 0.52, 0.85, 1) if winter else (0.30, 0.50, 0.95, 1))
    mid = e.new(0.5)
    mid.color = (0.80, 0.84, 0.90, 1) if winter else (0.75, 0.80, 0.88, 1)
    bg = nt.nodes.new("ShaderNodeBackground")
    bg.inputs["Strength"].default_value = 0.9 if winter else 0.8
    nt.links.new(rp.outputs[0], bg.inputs[0])
    nt.links.new(bg.outputs[0], out.inputs[0])
    sun = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", "SUN"))
    sun.data.energy = 3.2 if not winter else 2.6
    sun.data.angle = math.radians(1.5)
    sun.data.color = (1.0, 0.95, 0.88)
    sun.rotation_euler = (math.radians(62), 0, math.radians(200 - 180 + 25))
    sc.collection.objects.link(sun)
    fill = bpy.data.objects.new("Fill", bpy.data.lights.new("Fill", "AREA"))
    fill.data.energy = 150
    fill.data.size = 3
    fill.data.color = (0.85, 0.9, 1.0)
    fill.location = (-3, -3, 2.5)
    fill.rotation_euler = (math.radians(60), 0, math.radians(-45))
    sc.collection.objects.link(fill)
    # ground
    me = bpy.data.meshes.new("Ground")
    s = 30
    me.from_pydata([(-s, -s, 0), (s, -s, 0), (s, s, 0), (-s, s, 0)], [], [(0, 1, 2, 3)])
    g = bpy.data.objects.new("Ground", me)
    sc.collection.objects.link(g)
    m = bpy.data.materials.new("Ground")
    nt = m.node_tree
    p = nt.nodes["Principled BSDF"]
    tc = nt.nodes.new("ShaderNodeTexCoord")
    nz = nt.nodes.new("ShaderNodeTexNoise")
    nz.inputs["Scale"].default_value = 6.0
    nz.inputs["Detail"].default_value = 10
    nt.links.new(tc.outputs["Object"], nz.inputs["Vector"])
    rp = nt.nodes.new("ShaderNodeValToRGB")
    nt.links.new(nz.outputs["Fac"], rp.inputs[0])
    if winter:
        rp.color_ramp.elements[0].color = (0.70, 0.74, 0.80, 1)
        rp.color_ramp.elements[1].color = (0.88, 0.90, 0.94, 1)
        p.inputs["Roughness"].default_value = 0.6
        p.inputs["Subsurface Weight"].default_value = 0.3
        p.inputs["Subsurface Radius"].default_value = (0.8, 0.9, 1.0)
        p.inputs["Subsurface Scale"].default_value = 0.05
        bmp = nt.nodes.new("ShaderNodeBump")
        bmp.inputs["Strength"].default_value = 0.4
        nt.links.new(nz.outputs["Fac"], bmp.inputs["Height"])
        nt.links.new(bmp.outputs[0], p.inputs["Normal"])
    else:
        rp.color_ramp.elements[0].color = (0.22, 0.22, 0.21, 1)
        rp.color_ramp.elements[1].color = (0.32, 0.31, 0.30, 1)
        p.inputs["Roughness"].default_value = 0.85
    nt.links.new(rp.outputs[0], p.inputs["Base Color"])
    g.data.materials.append(m)
    return g


def set_outfit(outfit):
    summer = outfit == "summer"
    for cname, vis in (("Outfit_Summer", summer), ("Outfit_Winter", not summer)):
        c = bpy.data.collections[cname]
        c.hide_render = not vis
        c.hide_viewport = not vis
    body = bpy.data.objects["Body"]
    body.modifiers["OutfitMask"].vertex_group = "vis_summer" if summer else "vis_winter"
    # winter: scalp curves hidden under the beanie (only nape strands would show; keep it simple)
    bpy.data.objects["Hair_Strands"].hide_render = not summer
    bpy.data.objects["Hair_Scalp_Hires"].hide_render = not summer
    # hi-res: strands give the volume; the web cap shell is hidden
    bpy.data.objects["Hair_Cap_Summer"].hide_render = True
    bpy.data.objects["Brows"].hide_render = True       # brow strands are used instead of the web cards


def set_clip(clip, frame):
    arm = bpy.data.objects["Armature"]
    ad = arm.animation_data
    for tr in ad.nla_tracks:
        tr.mute = True
    if clip:
        act = bpy.data.actions[clip]
        ad.action = act
        if act.slots:
            ad.action_slot = act.slots[0]
    else:
        ad.action = None
        for pb in arm.pose.bones:
            pb.location = (0, 0, 0)
            pb.rotation_quaternion = (1, 0, 0, 0)
    bpy.context.scene.frame_set(frame)


def render(name, out, samples, res):
    outfit, clip, frame, az, ch, tz, focal, dist = SHOTS[name]
    bpy.ops.wm.open_mainfile(filepath=os.path.join(HERE, "character_hires.blend"))
    sc = bpy.context.scene
    winter = outfit == "winter"
    setup_world(sc, winter)
    set_outfit(outfit)
    sled = bpy.data.objects["Sled"]
    if clip and (clip.startswith("sled") or clip in ("superman", "spread_eagle")):
        sled.location = Vector((0, 0, 0)) - Vector(SLED.SEAT) + Vector((0, 0, 0.0))
        sled.hide_render = False
    else:
        sled.hide_render = True
        for ch_ in sled.children:
            ch_.hide_render = True
    set_clip(clip, frame)
    cam = bpy.data.objects.new("Cam", bpy.data.cameras.new("Cam"))
    sc.collection.objects.link(cam)
    sc.camera = cam
    cam.data.lens = focal
    a = math.radians(az)
    tgt = Vector((0, 0, tz))
    cam.location = Vector((dist * math.sin(a), -dist * math.cos(a), ch))
    d = (tgt - cam.location)
    cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    cam.data.dof.use_dof = name.endswith("head")
    cam.data.dof.focus_distance = d.length
    cam.data.dof.aperture_fstop = 8.0
    sc.render.engine = "CYCLES"
    sc.cycles.device = "CPU"
    sc.cycles.samples = samples
    sc.cycles.use_denoising = True
    try:
        sc.cycles.denoiser = "OPENIMAGEDENOISE"
    except Exception:
        pass
    sc.cycles.max_bounces = 8
    sc.render.resolution_x, sc.render.resolution_y = res
    sc.render.resolution_percentage = 100
    sc.view_settings.view_transform = "AgX"
    try:
        sc.view_settings.look = "AgX - Medium High Contrast"
    except Exception:
        pass
    sc.view_settings.exposure = 0.0
    sc.render.film_transparent = False
    sc.render.filepath = out
    sc.render.image_settings.file_format = "PNG"
    bpy.ops.render.render(write_still=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=None)
    ap.add_argument("--samples", type=int, default=96)
    ap.add_argument("--res", default="1280x720")
    ap.add_argument("--out", default=None)
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    a = ap.parse_args(argv)
    res = tuple(int(x) for x in a.res.split("x"))
    os.makedirs(RENDERS, exist_ok=True)
    names = a.only.split(",") if a.only else list(SHOTS)
    for n in names:
        out = a.out or os.path.join(RENDERS, f"character_{n}.png")
        if a.out and len(names) > 1:
            out = a.out.replace(".png", f"_{n}.png")
        render(n, out, a.samples, res)
        print("rendered", out, flush=True)


if __name__ == "__main__":
    main()
