"""Phase 6 lighting & atmosphere, cameras, compositor grade, hero pagoda integration.

Mood: late-November late afternoon -> blue hour. Multiple-scattering sky (Blender 5.x enum
MULTIPLE_SCATTERING, sun disc off), separate low warm sun lamp, lavender-blue ambient lift, amber lanterns,
warm shop windows, thin height-fog volume, post-rain sheen (in the ground materials), AgX + compositor grade
(soft bloom, light anisotropic Kuwahara for the painterly read, warm/cool split, vignette).
Per-shot presets are applied by kit_render.py through apply_preset().
"""
import importlib
import math
import os
import sys

import bpy
import numpy as np

from kit_common import HERE, data, get_coll, gz, look_at_euler, street_index
from kit_materials import M, node, link, mix, mrange, math as mth, sep, comb

# ------------------------------------------------------------------ presets
PRESETS = {
    # sun elevation/azimuth in degrees (azimuth from north, clockwise); sky strength; sun strength;
    # lantern emission multiplier; fog density; exposure; mist (aerial perspective) amount
    "golden": dict(sun_el=6.5, sun_az=238.0, sky=0.28, sun=3.2, sun_k=3100, lamps=0.55, fog=0.0035, exposure=0.15, mist=0.22),
    "dusk": dict(sun_el=2.0, sun_az=242.0, sky=0.30, sun=2.0, sun_k=2600, lamps=0.9, fog=0.004, exposure=0.35, mist=0.25),
    "blue": dict(sun_el=-3.5, sun_az=246.0, sky=1.1, sun=0.0, sun_k=2400, lamps=1.6, fog=0.0045, exposure=0.9, mist=0.3),
}


def _sun_vec(el, az):
    el, az = math.radians(el), math.radians(az)
    return np.array([math.sin(az) * math.cos(el), math.cos(az) * math.cos(el), math.sin(el)])


def world_setup():
    w = bpy.data.worlds.get("ART_World") or bpy.data.worlds.new("ART_World")
    bpy.context.scene.world = w
    nt = w.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputWorld")
    sky = nt.nodes.new("ShaderNodeTexSky"); sky.name = "Sky"
    sky.sky_type = "MULTIPLE_SCATTERING"
    sky.sun_disc = False
    sky.altitude = 60.0
    sky.air_density = 1.0; sky.aerosol_density = 1.6; sky.ozone_density = 1.0
    lav = (0.30, 0.30, 0.52, 1)
    # lavender ambient lift: added mostly for diffuse (non-camera) rays so the sky in frame stays a sky
    lp = nt.nodes.new("ShaderNodeLightPath")
    amb = mix(nt, 0.0, (0, 0, 0), lav)
    amb.node.name = "AmbientMix"
    camray = lp.outputs["Is Camera Ray"]
    c = mix(nt, mth(nt, "SUBTRACT", 1.0, camray), sky.outputs[0], amb, blend="ADD")
    bg = nt.nodes.new("ShaderNodeBackground"); bg.name = "BG"
    link(nt, c, bg.inputs["Color"])
    link(nt, bg.outputs[0], out.inputs["Surface"])
    w.mist_settings.start = 25.0
    w.mist_settings.depth = 420.0
    w.mist_settings.falloff = "QUADRATIC"
    return w


def sun_setup():
    sun = bpy.data.objects.get("Sun")
    if sun is None:
        ld = bpy.data.lights.new("Sun", "SUN")
        sun = bpy.data.objects.new("Sun", ld)
        get_coll("70_Lighting").objects.link(sun)
    sun.data.angle = math.radians(0.8)
    return sun


def apply_preset(name, scene=None):
    scene = scene or bpy.context.scene
    p = PRESETS[name]
    w = scene.world
    sky = w.node_tree.nodes["Sky"]
    sky.sun_elevation = math.radians(p["sun_el"])
    sky.sun_rotation = math.radians((90 - p["sun_az"]) % 360)   # Blender sky: rotation CCW from +X
    w.node_tree.nodes["BG"].inputs["Strength"].default_value = p["sky"]
    amb = w.node_tree.nodes["AmbientMix"]
    amb.inputs[0].default_value = 0.35 if name != "blue" else 0.12
    sun = bpy.data.objects["Sun"]
    v = _sun_vec(p["sun_el"], p["sun_az"])
    # light points along -Z of the object: rotate -Z onto -v
    from mathutils import Vector
    sun.rotation_euler = Vector(v).to_track_quat("Z", "Y").to_euler()
    sun.data.energy = p["sun"]
    sun.hide_render = p["sun"] <= 0
    sun.data.color = _blackbody(p["sun_k"])
    for ob in bpy.data.objects:
        if ob.type == "LIGHT" and ob.get("lamp_base_energy") is not None:
            ob.data.energy = ob["lamp_base_energy"] * p["lamps"]
    for m in bpy.data.materials:
        if m.get("emit_base") is not None:
            for n in m.node_tree.nodes:
                if n.type == "EMISSION":
                    n.inputs["Strength"].default_value = m["emit_base"] * p["lamps"]
    fog = bpy.data.materials.get("ART_Fog")
    if fog:
        fog.node_tree.nodes["FogDensity"].outputs[0].default_value = p["fog"]
    scene.view_settings.exposure = p["exposure"]
    cn = scene.compositing_node_group
    if cn and "MistAmount" in cn.nodes:
        cn.nodes["MistAmount"].outputs[0].default_value = p["mist"]
        col = (0.55, 0.52, 0.62, 1) if name == "blue" else (0.78, 0.62, 0.52, 1)
        cn.nodes["MistColour"].outputs[0].default_value = col
    scene["preset"] = name


def _blackbody(k):
    # compact approximation (Tanner Helland) -> linear-ish
    t = k / 100.0
    r = 255 if t <= 66 else 329.7 * (t - 60) ** -0.1332
    g = 99.47 * math.log(t) - 161.1 if t <= 66 else 288.1 * (t - 60) ** -0.0755
    b = 255 if t >= 66 else (0 if t <= 19 else 138.5 * math.log(t - 10) - 305.0)
    return tuple(max(0.0, min(1.0, c / 255.0)) ** 2.2 for c in (r, g, b))


# ------------------------------------------------------------------ emission bookkeeping
def tag_emitters():
    for m in bpy.data.materials:
        for n in m.node_tree.nodes if m.node_tree else []:
            if n.type == "EMISSION" and m.get("emit_base") is None:
                m["emit_base"] = float(n.inputs["Strength"].default_value)


# ------------------------------------------------------------------ lanterns
def stone_lantern(name, x, y, coll, props, scale=1.0, light=True):
    """Kasuga-style stone toro with a fire box; documented position (OSM man_made=lamp)."""
    import bmesh
    z = gz(x, y)
    bm = bmesh.new()
    mats = []

    def mi(k):
        if k not in mats:
            mats.append(k)
        return mats.index(k)

    def cyl(r0, r1, z0, z1, n, key):
        res = bmesh.ops.create_cone(bm, cap_ends=True, segments=n, radius1=r0, radius2=r1, depth=z1 - z0)
        for v in res["verts"]:
            v.co.z += (z0 + z1) / 2
        for f in {f for v in res["verts"] for f in v.link_faces}:
            f.material_index = mi(key)
    s = scale
    cyl(0.32 * s, 0.30 * s, 0.0, 0.12 * s, 6, "stone_lantern")
    cyl(0.09 * s, 0.09 * s, 0.12 * s, 0.85 * s, 8, "stone_lantern")
    cyl(0.26 * s, 0.24 * s, 0.85 * s, 0.97 * s, 6, "stone_lantern")
    cyl(0.17 * s, 0.17 * s, 0.97 * s, 1.27 * s, 6, "lantern_fire")
    cyl(0.40 * s, 0.05 * s, 1.27 * s, 1.55 * s, 6, "stone_lantern")
    cyl(0.06 * s, 0.0, 1.55 * s, 1.68 * s, 6, "stone_lantern")
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me); bm.free()
    for k in mats:
        me.materials.append(M(k))
    ob = bpy.data.objects.new(name, me)
    ob.location = (x, y, z)
    coll.objects.link(ob)
    for k, v in props.items():
        ob[k] = v
    ob["collide"] = True
    if light:
        ld = bpy.data.lights.new(name + "_Light", "POINT")
        ld.energy = 25.0 * s; ld.color = (1.0, 0.55, 0.22); ld.shadow_soft_size = 0.12
        lo = bpy.data.objects.new(name + "_Light", ld)
        lo.location = (x, y, z + 1.12 * s)
        lo["lamp_base_energy"] = ld.energy
        for k, v in props.items():
            lo[k] = v
        coll.objects.link(lo)
    return ob


def street_lamp(name, x, y, coll, props):
    import bmesh
    z = gz(x, y)
    bm = bmesh.new()
    res = bmesh.ops.create_cone(bm, cap_ends=True, segments=8, radius1=0.07, radius2=0.05, depth=4.6)
    for v in res["verts"]:
        v.co.z += 2.3
    res2 = bmesh.ops.create_cube(bm, size=0.3)
    for v in res2["verts"]:
        v.co.z += 4.6
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    me.materials.append(M("metal")); me.materials.append(M("andon"))
    for p in me.polygons:
        if p.center.z > 4.4:
            p.material_index = 1
    ob = bpy.data.objects.new(name, me); ob.location = (x, y, z); coll.objects.link(ob)
    ld = bpy.data.lights.new(name + "_Light", "POINT"); ld.energy = 60; ld.color = (1.0, 0.62, 0.32); ld.shadow_soft_size = 0.2
    lo = bpy.data.objects.new(name + "_Light", ld); lo.location = (x, y, z + 4.45); lo["lamp_base_energy"] = 60.0
    coll.objects.link(lo)
    for o in (ob, lo):
        for k, v in props.items():
            o[k] = v
    return ob


def lanterns():
    coll = get_coll("75_Lanterns_Lights")
    n_doc = 0
    for p in data("features")["pois"]:
        t = p["tags"]
        x, y = p["x"], p["y"]
        if abs(x) > 200 or abs(y) > 200:
            continue
        props = dict(osm_id=str(p["osm_id"]), detail_class="observed", artistic=False,
                     evidence_ref="osm:node/%s %s" % (p["osm_id"], " ".join("%s=%s" % kv for kv in t.items())))
        if t.get("man_made") == "lamp":
            stone_lantern("Lantern_osm%s" % p["osm_id"], x, y, coll, props, 1.15 if t.get("name") else 0.8,
                          light=True)
            n_doc += 1
        elif t.get("highway") == "street_lamp":
            street_lamp("StreetLamp_osm%s" % p["osm_id"], x, y, coll, props)
            n_doc += 1
    # kit chochin / andon get a small real light each (emission alone is too weak to model the pool of light)
    n_art = 0
    for e in bpy.data.objects:
        if e.type == "EMPTY" and e.get("kit_piece", "").startswith(("K_Chochin", "K_Andon")):
            mw = e.matrix_world
            from mathutils import Vector
            local = Vector((0.0, -0.55, 2.33)) if "Chochin" in e["kit_piece"] else Vector((0.0, -0.23, 0.88))
            ld = bpy.data.lights.new("KitLight", "POINT")
            ld.energy = 9.0 if "Chochin" in e["kit_piece"] else 6.0
            ld.color = (1.0, 0.45, 0.18) if "Red" in e["kit_piece"] else (1.0, 0.62, 0.32)
            ld.shadow_soft_size = 0.15
            lo = bpy.data.objects.new("KitLight_" + e.name, ld)
            lo.location = mw @ local
            lo["lamp_base_energy"] = ld.energy
            lo["detail_class"] = e.get("detail_class", "inferred"); lo["artistic"] = e.get("detail_class") == "artistic"
            lo["evidence_ref"] = "light for kit piece " + e.name
            coll.objects.link(lo)
            n_art += 1
    return n_doc, n_art


# ------------------------------------------------------------------ fog
def fog_volume():
    coll = get_coll("80_Atmosphere")
    m = bpy.data.materials.get("ART_Fog") or bpy.data.materials.new("ART_Fog")
    nt = m.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    dens = nt.nodes.new("ShaderNodeValue"); dens.name = "FogDensity"; dens.outputs[0].default_value = 0.004
    # height falloff: denser in the lower 6-10 m (between buildings), fading out above the roofs.
    # Uses height above a tilted plane approximating the district slope (48 m west -> 75 m east).
    P = node(nt, "ShaderNodeNewGeometry").outputs["Position"]
    x, y, z = sep(nt, P)
    base = mth(nt, "MULTIPLY_ADD", x, 0.07, 58.0)
    base = mth(nt, "MULTIPLY_ADD", y, -0.05, base)
    hz = mth(nt, "SUBTRACT", z, base)
    fall = mrange(nt, hz, 4.0, 22.0, 1.0, 0.15)
    d = mth(nt, "MULTIPLY", dens.outputs[0], fall)
    vol = node(nt, "ShaderNodeVolumePrincipled", {"Color": (0.86, 0.82, 0.92, 1), "Anisotropy": 0.45})
    link(nt, d, vol.inputs["Density"])
    link(nt, vol.outputs[0], out.inputs["Volume"])
    import bmesh
    bm = bmesh.new(); bmesh.ops.create_cube(bm, size=1.0)
    me = bpy.data.meshes.new("FX_Fog_Volume"); bm.to_mesh(me); bm.free()
    me.materials.append(m)
    ob = bpy.data.objects.get("FX_Fog_Volume")
    if ob is None:
        ob = bpy.data.objects.new("FX_Fog_Volume", me); coll.objects.link(ob)
    ob.location = (20, 0, 75); ob.scale = (420, 420, 70)
    ob.visible_shadow = False
    ob["artistic"] = True
    ob["exclude_web"] = True
    return ob


# ------------------------------------------------------------------ cameras
def _snap(way, x, y):
    from shapely.geometry import LineString, Point
    s = street_index()[way]
    ls = LineString(s["coords"])
    p = ls.interpolate(ls.project(Point(x, y)))
    return p.x, p.y


def _walk_z(x, y):
    """Walkable surface height: terrain, or the top of an OSM step if one is under the point."""
    z = gz(x, y)
    from mathutils import Vector
    for ob in bpy.data.objects:
        if ob.name.startswith(("Steps_osm", "Paving_osm")) and ob.type == "MESH":
            bb = [ob.matrix_world @ Vector(c) for c in ob.bound_box]
            if min(v.x for v in bb) - 0.1 < x < max(v.x for v in bb) + 0.1 and min(v.y for v in bb) - 0.1 < y < max(v.y for v in bb) + 0.1:
                from mathutils.bvhtree import BVHTree
                dg = bpy.context.evaluated_depsgraph_get()
                bvh = BVHTree.FromObject(ob, dg)
                hit = bvh.ray_cast(Vector((x, y, z + 20)), Vector((0, 0, -1)))
                if hit[0] is not None:
                    z = max(z, hit[0].z)
    return z


SHOTS = {
    # name: way to snap to, approx xy, look-at (x, y, dz above ground at target or absolute z), lens, shift_y, preset
    "a_yasaka_dori_east": dict(way=24516359, xy=(-79.0, 88.2), look=(9.7, 83.5, None), lens=30, shift=0.24, preset="golden",
                               look_z=58.0),
    "b_ninenzaka_south": dict(way=30913263, xy=(153.6, 98.0), look=(155.5, 45.0, None), lens=28, shift=0.08, preset="dusk",
                              look_z_rel=1.2),
    "c_sannenzaka_stairs": dict(way=1569088146, xy=(166.5, -142.0), look=(151.0, -177.0, None), lens=26, shift=0.12,
                                preset="dusk", look_z_rel=3.6),
    "d_bluehour_roofs": dict(way=710696944, xy=(118.0, 30.0), look=(9.7, 83.5, None), lens=40, shift=0.0, preset="blue",
                             elev=14.0, look_z=78.0),
    "e_yasaka_dori_upper_west": dict(way=710696944, xy=(80.9, 39.8), look=(9.7, 83.5, None), lens=32, shift=0.2, preset="golden",
                                     look_z=70.0),
}


def cameras():
    coll = get_coll("70_Lighting")
    out = {}
    for name, sh in SHOTS.items():
        x, y = _snap(sh["way"], *sh["xy"])
        z = _walk_z(x, y) + 1.6 + sh.get("elev", 0.0)
        tx, ty, _ = sh["look"]
        if "look_z" in sh:
            tz = sh["look_z"]
        else:
            tz = _walk_z(tx, ty) + sh.get("look_z_rel", 1.6)
        # level the camera: pitch toward target but use lens shift for the rest (architectural verticals)
        cname = "Cam_" + name
        cd = bpy.data.cameras.get(cname) or bpy.data.cameras.new(cname)
        cd.lens = sh["lens"]; cd.clip_start = 0.1; cd.clip_end = 3000
        cd.shift_y = sh["shift"]
        cd.sensor_width = 36
        co = bpy.data.objects.get(cname) or bpy.data.objects.new(cname, cd)
        if co.name not in coll.objects:
            coll.objects.link(co)
        co.location = (x, y, z)
        e = look_at_euler((x, y, z), (tx, ty, tz))
        # compensate the shift so the target stays where look-at would put it: reduce pitch
        fov_v = 2 * math.atan(24 * 9 / 16 / 2 / sh["lens"]) if False else 2 * math.atan((36 * 9 / 16) / 2 / sh["lens"])
        pitch = e[0] - sh["shift"] * fov_v
        co.rotation_euler = (pitch, 0, e[2])
        co["walkable_position"] = "osm:way/%d (snapped from %s), z = walkable surface + %.1f m" % (sh["way"], sh["xy"], 1.6 + sh.get("elev", 0.0))
        co["preset"] = sh["preset"]
        out[name] = co
    return out


# ------------------------------------------------------------------ compositor + render settings
def compositor():
    scene = bpy.context.scene
    vl = scene.view_layers[0]
    vl.use_pass_mist = True
    ng = bpy.data.node_groups.get("ART_Grade")
    if ng:
        bpy.data.node_groups.remove(ng)
    ng = bpy.data.node_groups.new("ART_Grade", "CompositorNodeTree")
    ng.interface.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")
    scene.compositing_node_group = ng
    N = ng.nodes
    rl = N.new("CompositorNodeRLayers")
    go = N.new("NodeGroupOutput")
    # aerial perspective from the mist pass
    amt = N.new("ShaderNodeValue"); amt.name = "MistAmount"; amt.outputs[0].default_value = 0.22
    mcol = N.new("CompositorNodeRGB"); mcol.name = "MistColour"; mcol.outputs[0].default_value = (0.78, 0.62, 0.52, 1)
    mf = N.new("ShaderNodeMath"); mf.operation = "MULTIPLY"
    ng.links.new(rl.outputs["Mist"], mf.inputs[0]); ng.links.new(amt.outputs[0], mf.inputs[1])
    mm = N.new("ShaderNodeMix"); mm.data_type = "RGBA"; mm.blend_type = "MIX"
    ng.links.new(mf.outputs[0], mm.inputs[0]); ng.links.new(rl.outputs["Image"], mm.inputs[6]); ng.links.new(mcol.outputs[0], mm.inputs[7])
    img = mm.outputs[2]
    # soft bloom
    gl = N.new("CompositorNodeGlare")
    gl.inputs["Type"].default_value = "Bloom"
    gl.inputs["Quality"].default_value = "High"
    gl.inputs["Threshold"].default_value = 0.9
    gl.inputs["Strength"].default_value = 0.35
    gl.inputs["Size"].default_value = 0.65
    ng.links.new(img, gl.inputs["Image"])
    img = gl.outputs[0]
    # painterly: anisotropic Kuwahara, blended at 55 %
    kw = N.new("CompositorNodeKuwahara"); kw.name = "Kuwahara"
    kw.inputs["Size"].default_value = 5
    kw.inputs["Type"].default_value = "Anisotropic"
    kw.inputs["Sharpness"].default_value = 0.6
    kw.inputs["Eccentricity"].default_value = 1.2
    kw.inputs["High Precision"].default_value = True
    ng.links.new(img, kw.inputs["Image"])
    km = N.new("ShaderNodeMix"); km.data_type = "RGBA"; km.name = "KuwaharaMix"
    km.inputs[0].default_value = 0.55
    ng.links.new(img, km.inputs[6]); ng.links.new(kw.outputs[0], km.inputs[7])
    img = km.outputs[2]
    # grade: cool lift, warm gain
    cb = N.new("CompositorNodeColorBalance")
    cb.inputs["Color Lift"].default_value = (0.97, 0.97, 1.05, 1)
    cb.inputs["Color Gamma"].default_value = (1.0, 0.99, 1.0, 1)
    cb.inputs["Color Gain"].default_value = (1.05, 1.0, 0.94, 1)
    ng.links.new(img, cb.inputs["Image"])
    img = cb.outputs[0]
    hs = N.new("CompositorNodeHueSat")
    hs.inputs["Saturation"].default_value = 0.94
    ng.links.new(img, hs.inputs["Image"])
    img = hs.outputs[0]
    # vignette
    em = N.new("CompositorNodeEllipseMask")
    em.inputs["Size"].default_value = (0.92, 0.82)
    bl = N.new("CompositorNodeBlur"); bl.name = "VignetteBlur"
    bl.inputs["Size"].default_value = (300, 300)
    ng.links.new(em.outputs[0], bl.inputs["Image"])
    vm = N.new("ShaderNodeMix"); vm.data_type = "RGBA"; vm.blend_type = "MULTIPLY"
    inv = N.new("ShaderNodeMath"); inv.operation = "MULTIPLY_ADD"
    ng.links.new(bl.outputs[0], inv.inputs[0]); inv.inputs[1].default_value = -0.28; inv.inputs[2].default_value = 0.28
    ng.links.new(inv.outputs[0], vm.inputs[0])
    ng.links.new(img, vm.inputs[6]); vm.inputs[7].default_value = (0.25, 0.22, 0.3, 1)
    img = vm.outputs[2]
    ng.links.new(img, go.inputs[0])
    return ng


def render_settings(scene=None):
    scene = scene or bpy.context.scene
    scene.render.engine = "CYCLES"
    c = scene.cycles
    c.device = "CPU"
    c.use_adaptive_sampling = True
    c.adaptive_threshold = 0.02
    c.adaptive_min_samples = 16
    c.samples = 128
    c.use_denoising = True
    c.denoiser = "OPENIMAGEDENOISE"
    c.denoising_input_passes = "RGB_ALBEDO_NORMAL"
    c.denoising_prefilter = "ACCURATE"
    c.max_bounces = 6; c.diffuse_bounces = 3; c.glossy_bounces = 2; c.transmission_bounces = 4
    c.volume_bounces = 0; c.transparent_max_bounces = 6
    c.volume_step_rate = 4.0
    c.volume_max_steps = 256
    c.sample_clamp_indirect = 6.0
    c.sample_clamp_direct = 0.0
    c.light_sampling_threshold = 0.01
    c.use_light_tree = True
    c.caustics_reflective = False; c.caustics_refractive = False
    c.blur_glossy = 1.0
    scene.render.use_persistent_data = True
    scene.render.compositor_device = "CPU"
    scene.render.compositor_precision = "FULL"
    scene.render.use_compositing = True
    scene.render.film_transparent = False
    scene.view_settings.view_transform = "AgX"
    try:
        scene.view_settings.look = "AgX - Medium High Contrast"
    except TypeError:
        pass
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_depth = "8"


# ------------------------------------------------------------------ run
def run(log=print):
    world_setup()
    sun_setup()
    nd, na = lanterns()
    log("lanterns: documented", nd, "kit lights", na)
    fog_volume()
    tag_emitters()
    cams = cameras()
    log("cameras", list(cams))
    compositor()
    render_settings()
    apply_preset("golden")
    bpy.context.scene.camera = cams["a_yasaka_dori_east"]


# ------------------------------------------------------------------ hero pagoda
def pagoda(log=print):
    path = os.path.join(HERE, "hero_pagoda.py")
    old = bpy.data.objects.get("LM_Yasaka_Pagoda_PLATEAU_LOD2")
    if not os.path.exists(path):
        log("hero_pagoda.py not found -> keeping PLATEAU placeholder")
        bpy.context.scene["pagoda"] = "placeholder (PLATEAU LOD2)"
        return None
    try:
        if HERE not in sys.path:
            sys.path.insert(0, HERE)
        hp = importlib.import_module("hero_pagoda")
        importlib.reload(hp)
        coll = get_coll("35_Landmarks")
        hero_c = get_coll("36_Hero_Pagoda", coll)
        ob = hp.build_pagoda(hero_c, "render")
    except Exception as ex:  # keep the placeholder if the other workstream's module is mid-edit
        import traceback
        traceback.print_exc()
        log("hero pagoda build failed (%s) -> keeping placeholder" % ex)
        bpy.context.scene["pagoda"] = "placeholder (hero build failed: %s)" % ex
        return None
    if old is not None:
        old.hide_render = True
        old.hide_set(True)
        old["replaced_by_hero"] = True
    bpy.context.scene["pagoda"] = "hero (blender/hero_pagoda.py build_pagoda)"
    log("hero pagoda built:", ob.name if ob else None)
    return ob
