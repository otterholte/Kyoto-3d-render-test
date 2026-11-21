"""World / sun / camera / render settings for the two seasons.

Summer: late-afternoon July light at 48.72 N (sun az ~280 deg, el ~24 deg), clear PNW sky with haze.
Winter: low golden December sun through thin overcast (az ~222 deg, el ~9 deg), cool sky fill; porch & some
window lights on.
"""
import math

import bpy
import numpy as np
from mathutils import Vector

import cc_common as C

PRESETS = {
    "summer": dict(sun_az=281.0, sun_el=24.0, sun_strength=4.2, sun_color=(1.0, 0.9, 0.78), sun_angle=0.6,
                   sky_strength=0.9, air=1.0, aerosol=2.2, ozone=1.0, exposure=0.0, lights_on=False,
                   mist=0.0012, bg_tint=(1.0, 1.0, 1.0)),
    "winter": dict(sun_az=232.0, sun_el=8.0, sun_strength=3.6, sun_color=(1.0, 0.72, 0.48), sun_angle=2.5,
                   sky_strength=0.75, air=1.4, aerosol=5.0, ozone=1.0, exposure=-0.2, lights_on=True,
                   mist=0.0025, bg_tint=(0.92, 0.95, 1.0)),
}


def sun_vec(az, el):
    """az: compass bearing (deg, clockwise from north) the sun is IN; returns direction toward the sun."""
    a, e = math.radians(az), math.radians(el)
    return Vector((math.sin(a) * math.cos(e), math.cos(a) * math.cos(e), math.sin(e)))


def world_setup(preset):
    P = PRESETS[preset]
    sc = bpy.context.scene
    w = bpy.data.worlds.get("World_" + preset) or bpy.data.worlds.new("World_" + preset)
    sc.world = w
    nt = w.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputWorld")
    bg = nt.nodes.new("ShaderNodeBackground")
    sky = nt.nodes.new("ShaderNodeTexSky")
    try:
        sky.sky_type = "MULTIPLE_SCATTERING"
    except Exception:
        sky.sky_type = "SINGLE_SCATTERING"
    sky.sun_disc = False
    sky.sun_elevation = math.radians(P["sun_el"])
    sky.sun_rotation = math.radians(P["sun_az"])      # calibrated: sky sun_rotation == compass bearing
    sky.altitude = 140
    sky.air_density = P["air"]
    try:
        sky.aerosol_density = P["aerosol"]
    except Exception:
        pass
    sky.ozone_density = P["ozone"]
    mix = nt.nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    mix.blend_type = "MULTIPLY"
    mix.inputs[0].default_value = 1.0
    mix.inputs[7].default_value = (*P["bg_tint"], 1)
    nt.links.new(sky.outputs[0], mix.inputs[6])
    nt.links.new(mix.outputs[2], bg.inputs["Color"])
    bg.inputs["Strength"].default_value = P["sky_strength"]
    nt.links.new(bg.outputs[0], out.inputs["Surface"])
    if preset == "winter":
        # thin overcast: blend the clear sky toward a soft grey dome
        gr = nt.nodes.new("ShaderNodeRGB")
        gr.outputs[0].default_value = (0.42, 0.45, 0.52, 1)
        mx2 = nt.nodes.new("ShaderNodeMix")
        mx2.data_type = "RGBA"
        mx2.inputs[0].default_value = 0.35
        nt.links.new(mix.outputs[2], mx2.inputs[6])
        nt.links.new(gr.outputs[0], mx2.inputs[7])
        nt.links.new(mx2.outputs[2], bg.inputs["Color"])
    # sun lamp
    sun = bpy.data.objects.get("Sun")
    if sun is None:
        sun = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", "SUN"))
        sc.collection.objects.link(sun)
    sun.data.energy = P["sun_strength"]
    sun.data.color = P["sun_color"]
    sun.data.angle = math.radians(P["sun_angle"])
    v = sun_vec(P["sun_az"], P["sun_el"])
    sun.rotation_euler = (-v).to_track_quat("-Z", "Y").to_euler()
    sc.view_settings.exposure = P["exposure"]
    try:
        sc.view_settings.view_transform = "AgX"
        sc.view_settings.look = "AgX - Base Contrast"
    except Exception:
        pass
    sc["preset"] = preset
    return sun


def set_lights(on):
    """Porch / coach lights + lit windows on (winter dusk) or off (summer)."""
    for m in bpy.data.materials:
        nt = m.node_tree
        if nt is None:
            continue
        bs = next((n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"), None)
        if bs is None:
            continue
        if m.name == "LIGHT_porch":
            bs.inputs["Emission Strength"].default_value = 25.0 if on else 0.0
        elif m.get("lit"):
            bs.inputs["Emission Strength"].default_value = 2.5 if on else 0.0
    for ob in bpy.data.objects:
        if ob.type == "LIGHT" and ob.get("porch_light"):
            ob.hide_render = not on


def porch_lamps(hbs, coll):
    for n, hb in hbs.items():
        for i, p in enumerate(getattr(hb, "light_points", [])):
            ld = bpy.data.lights.new("PL_%d_%d" % (n, i), "POINT")
            ld.energy = 25
            ld.color = (1.0, 0.72, 0.42)
            ld.shadow_soft_size = 0.08
            ob = bpy.data.objects.new("PorchLamp_%d_%d" % (n, i), ld)
            ob.location = p
            ob["porch_light"] = True
            coll.objects.link(ob)


def camera(name, loc, target, lens=28.0, coll=None, shift_y=0.0):
    cd = bpy.data.cameras.get(name) or bpy.data.cameras.new(name)
    ob = bpy.data.objects.get(name)
    if ob is None:
        ob = bpy.data.objects.new(name, cd)
        (coll or bpy.context.scene.collection).objects.link(ob)
    cd.lens = lens
    cd.clip_start = 0.1
    cd.clip_end = 2000
    cd.shift_y = shift_y
    ob.location = loc
    ob.rotation_euler = (Vector(target) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
    return ob


def cameras(coll):
    d = C.dtm()
    z = lambda x, y: float(d.sample(x, y))
    cams = {}
    # (a) eye level from the bulb looking at 3905 (front: WSW + SSE faces, garage wing)
    p = (-9.5, -25.5)
    cams["a"] = camera("Cam_a_bulb_3905", (p[0], p[1], z(*p) + 1.62), (0.5, 0.0, z(0.5, 0.0) + 3.6), 24, coll)
    # (b) top of the sled run looking down Canby Ct (winter)
    p = (-12.0, -30.1)
    cams["b"] = camera("Cam_b_sledrun_top", (p[0], p[1], z(*p) + 2.0), (-62.0, -29.0, z(-62, -29.0) - 1.2), 30,
                       coll)
    # (c) 3905 back yard from the NW lawn
    p = (6.0, 23.5)
    cams["c"] = camera("Cam_c_3905_backyard", (p[0], p[1], z(*p) + 1.62), (-2.5, 7.0, z(-2.5, 7) + 3.0), 24, coll)
    # overview (checks only)
    cams["o"] = camera("Cam_o_overview", (-95, -95, 200), (-35, -15, 140), 30, coll)
    return cams


def render_settings(samples=64, res=(960, 540), threads=3):
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.device = "CPU"
    sc.cycles.samples = samples
    sc.cycles.use_adaptive_sampling = True
    sc.cycles.adaptive_threshold = 0.02
    sc.cycles.use_denoising = True
    try:
        sc.cycles.denoiser = "OPENIMAGEDENOISE"
    except Exception:
        pass
    sc.cycles.max_bounces = 5
    sc.cycles.diffuse_bounces = 2
    sc.cycles.glossy_bounces = 2
    sc.cycles.transmission_bounces = 3
    sc.cycles.transparent_max_bounces = 24
    sc.cycles.adaptive_threshold = 0.03
    sc.cycles.caustics_reflective = False
    sc.cycles.caustics_refractive = False
    sc.cycles.blur_glossy = 1.0
    sc.render.resolution_x, sc.render.resolution_y = res
    sc.render.resolution_percentage = 100
    sc.render.threads_mode = "FIXED"
    sc.render.threads = threads
    sc.render.image_settings.file_format = "PNG"
    sc.render.film_transparent = False
    try:
        sc.cycles.texture_limit_render = "2048"
    except Exception:
        pass
