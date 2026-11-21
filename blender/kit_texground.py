"""Textured ground / stairs / walls using the image texture library (blender/materials_textured.py, blender/textures/).

* Terrain: asphalt_worn (mask R), setts_granite (G), gravel (B), earth_moss (unclassified) blended by the surveyed
  surface mask (data/processed/surface_mask.png), sampled at real scale through a world-metre UV layer "UVWorld".
* Steps_osm*: stone_steps_trim; Barrier walls: ishigaki_mossy; fences: bamboo_fence_kenninji -- per-face planar UVs
  in metres (u along the face's horizontal direction, v = height; horizontal faces: world x/y).
"""
import bpy
import numpy as np

import materials_textured as MT


def planar_uvs(me, name="UVMap"):
    """Per-face metre UVs (box-like projection)."""
    uv = me.uv_layers.get(name) or me.uv_layers.new(name=name)
    V = np.empty(len(me.vertices) * 3); me.vertices.foreach_get("co", V); V = V.reshape(-1, 3)
    out = np.zeros((len(me.loops), 2))
    for p in me.polygons:
        n = np.array(p.normal)
        idx = list(p.loop_indices)
        vs = V[[me.loops[i].vertex_index for i in idx]]
        if abs(n[2]) > 0.7:
            out[idx] = vs[:, :2]
        else:
            t = np.array([-n[1], n[0], 0.0]); t /= max(np.linalg.norm(t), 1e-9)
            out[idx, 0] = vs @ t
            out[idx, 1] = vs[:, 2]
    uv.data.foreach_set("uv", out.ravel())
    me.uv_layers.active = me.uv_layers[0]
    return uv


def terrain_material(ter, mask_img, name="TX_Terrain"):
    me = ter.data
    uvw = me.uv_layers.get("UVWorld") or me.uv_layers.new(name="UVWorld")
    vi = np.empty(len(me.loops), np.int32); me.loops.foreach_get("vertex_index", vi)
    V = np.empty(len(me.vertices) * 3); me.vertices.foreach_get("co", V); V = V.reshape(-1, 3)
    uvw.data.foreach_set("uv", V[vi, :2].ravel())
    lib = MT.library()["sets"]
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    T = MT._NT(mat)
    uvn = T.n("ShaderNodeUVMap", uv_map="UVMap")
    mt = T.n("ShaderNodeTexImage", interpolation="Cubic", extension="EXTEND"); mt.image = mask_img
    T.l(uvn.outputs[0], mt.inputs[0])
    sm = T.n("ShaderNodeSeparateColor"); T.l(mt.outputs[0], sm.inputs[0])
    uw = T.n("ShaderNodeUVMap", uv_map="UVWorld").outputs[0]
    # slight noise warp of the class borders so they do not read as pixel steps
    nz = T.n("ShaderNodeTexNoise"); nz.inputs["Scale"].default_value = 0.8
    T.l(uw, nz.inputs["Vector"])

    def mask(ch):
        a = T.math("MULTIPLY_ADD", nz.outputs["Fac"], 0.5, -0.25)
        b = T.math("ADD", sm.outputs[ch], a)
        mr = T.n("ShaderNodeMapRange"); mr.inputs[1].default_value = 0.4; mr.inputs[2].default_value = 0.6
        T.l(b, mr.inputs[0])
        return mr.outputs[0]

    def sset(set_name):
        s = lib[set_name]
        mp = T.n("ShaderNodeMapping"); mp.inputs["Scale"].default_value = (1 / s["size_m"][0], 1 / s["size_m"][1], 1)
        T.l(uw, mp.inputs[0])
        f = s["files"]
        return [T.tex(mp.outputs[0], f["albedo"]).outputs[0], T.tex(mp.outputs[0], f["normal"], True).outputs[0],
                T.tex(mp.outputs[0], f["orm"], True).outputs[0]]
    cur = sset("earth_moss")
    for set_name, ch in (("gravel", 2), ("asphalt_worn", 0), ("setts_granite", 1)):
        nxt = sset(set_name)
        m = mask(ch)
        cur = [T.mixc(m, a, b) for a, b in zip(cur, nxt)]
    MT._surface(T, mat, cur[0], cur[1], cur[2], uv_map="UVWorld")
    me.materials[0] = mat
    mat["texlib_set"] = "terrain blend: earth_moss/gravel/asphalt_worn/setts_granite by surface_mask"
    return mat


def run(log=print):
    n = dict(steps=0, walls=0, fences=0)
    m_steps = MT.make_material("TX_Stone_Steps", "stone_steps_trim")
    m_wall = MT.make_material("TX_Ishigaki", "ishigaki_mossy")
    m_fence = MT.make_material("TX_Bamboo_Fence", "bamboo_fence_kenninji")
    for ob in bpy.data.objects:
        if ob.type != "MESH":
            continue
        if ob.name.startswith("Steps_osm"):
            planar_uvs(ob.data); ob.data.materials[0] = m_steps; n["steps"] += 1
        elif ob.name.startswith("Barrier_"):
            planar_uvs(ob.data)
            if ob.get("barrier") in ("wall", "retaining_wall", "city_wall"):
                ob.data.materials[0] = m_wall; n["walls"] += 1
            else:
                ob.data.materials[0] = m_fence; n["fences"] += 1
    ter = bpy.data.objects.get("Terrain_GSI_DEM5A")
    img = next((im for im in bpy.data.images if "surface_mask" in im.name), None)
    if ter is not None and img is not None:
        terrain_material(ter, img)
    log("textured ground", n)
    return n
