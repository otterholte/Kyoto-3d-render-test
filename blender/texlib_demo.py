"""Street-level check render of the texture library on real PLATEAU LOD2 buildings (Ninenzaka, looking south).

    /home/user/venv/bin/python blender/texlib_demo.py [--samples 96] [--radius 140] [--out renders/texlib_demo_ninenzaka.png]

Opens blender/higashiyama_blockout.blend read-only (never saved), applies the textured materials to the
buildings around the camera (facade atlas via assign_facades, kawara via apply_roof_uvs), adds simple 1F hisashi
pent roofs on street-facing traditional fronts (PLATEAU LOD2 omits them; evidence: hisashi at ~2.7-3.2 m) and
textured ground (ishidatami / asphalt / earth by the surface mask), then renders 1280x720 from local (153.6, 98).
"""
import json
import math
import os
import sys

import bpy
import bmesh
import numpy as np
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import materials_textured as MT  # noqa: E402

A = sys.argv[1:]


def arg(k, d):
    return type(d)(A[A.index(k) + 1]) if k in A else d


SAMPLES = arg("--samples", 96)
RADIUS = arg("--radius", 140.0)
OUT = arg("--out", os.path.join(ROOT, "renders", "texlib_demo_ninenzaka.png"))
CAM_XY = (153.6, 98.0)
NINENZAKA = (30913263, 30882783, 550360170)

bpy.ops.wm.open_mainfile(filepath=os.path.join(HERE, "higashiyama_blockout.blend"))
sc = bpy.context.scene
cam = bpy.data.objects["Cam_Ninenzaka_South"]
sc.camera = cam

# ----------------------------------------------------------------------------- evidence (structure codes)
EV = json.load(open(os.path.join(ROOT, "docs", "evidence", "building_evidence.json")))
ev_pts = []
for seg, recs in EV["buildings_by_street"].items():
    for r in recs:
        ev_pts.append((np.array(r["local_centroid_xy"]), r, seg))
BLD = {b["id"]: b for b in json.load(open(os.path.join(ROOT, "data", "processed", "buildings.json")))["buildings"]}


def evidence_for(pid):
    b = BLD.get(pid)
    if not b:
        return None
    c = np.array(b["centroid"])
    best = min(ev_pts, key=lambda e: np.linalg.norm(e[0] - c)) if ev_pts else None
    if best is not None and np.linalg.norm(best[0] - c) < 2.5:
        return best[1], best[2]
    return None


STRUCT_TXT = {"wooden": "601", "steel": "604", "reinforced": "603", "RC": "603"}

# ----------------------------------------------------------------------------- materials
fac = MT.make_facade_material(emit_strength=0.25)
roof = MT.make_roof_material()
plinth = MT.make_material("TX_Plinth_Granite", "kerb_granite")
hisashi_mat = MT.make_roof_material("TX_Hisashi_Kawara")
streets = MT.load_streets()
nin = [s for s in streets if s["osm_id"] in NINENZAKA]

# ----------------------------------------------------------------------------- buildings
cx, cy = CAM_XY
cam_dir = (cam.matrix_world.to_3x3() @ Vector((0, 0, -1)))
chosen, applied = [], 0
log = []
for ob in [o for o in bpy.data.objects if o.name.startswith("B_") and o.type == "MESH"]:
    pid = ob.get("plateau_id")
    b = BLD.get(pid)
    if not b:
        continue
    c = np.array(b["centroid"])
    d = np.hypot(c[0] - cx, c[1] - cy)
    if d > RADIUS:
        continue
    v = Vector((c[0] - cx, c[1] - cy, 0))
    if d > 25 and v.normalized().dot(Vector((cam_dir.x, cam_dir.y, 0)).normalized()) < 0.3:
        continue
    attrs = {"name": b.get("name"), "usage": b.get("usage"), "year": b.get("year"), "storeys": b.get("storeys"),
             "base_z": b.get("base_z"), "plateau_id": pid}
    ev = evidence_for(pid)
    if ev:
        st = ev[0].get("structure") or ""
        attrs["structure"] = next((code for k, code in STRUCT_TXT.items() if k in st), "")
        attrs["storeys"] = ev[0].get("storeys") or attrs["storeys"]
    infos = MT.assign_facades(ob, attrs, streets=streets)
    MT.apply_roof_uvs(ob)
    MT.ensure_slots(ob, fac, roof, plinth)
    applied += 1
    dn = min(MT._dist_to_streets(c, nin)[0], 99)
    street_facing = [i for i in infos if i["asg"].get("street_facing")]
    if dn < 12:
        chosen.append((dn, ob.name, pid, MT.classify(attrs), [(i["asg"]["gf"], i["asg"]["uf"]) for i in street_facing][:2]))
    # simple 1F hisashi on street-facing traditional fronts
    for i in street_facing:
        if i["asg"].get("kind") != "traditional" or i["length"] < 1.5:
            continue
        n = i["normal"]; t = Vector((0, 0, 1)).cross(n).normalized()
        me = ob.data; mw = ob.matrix_world
        g_pts = [mw @ me.vertices[vi].co for vi in range(len(me.vertices))]
        s_vals = [p.dot(t) for p in g_pts if abs((p - i["center"]).dot(n)) < 0.3]
        if not s_vals:
            continue
        s0, s1 = min(s_vals), max(s_vals)
        z0 = i["zmin"] + min(i["asg"]["gf_h"], 3.0) - 0.15
        if i["zmax"] - i["zmin"] < z0 - i["zmin"] + 1.0:
            continue
        base = i["center"] - t * (i["center"].dot(t)) + Vector((0, 0, 0))
        off = i["center"].dot(n)
        depth, drop = 0.95, 0.38
        bm = bmesh.new()

        def P(s, out, z):
            q = t * s + n * (off + out)
            return bm.verts.new((q.x, q.y, z))
        a0, a1 = P(s0 - 0.05, 0.0, z0 + drop), P(s1 + 0.05, 0.0, z0 + drop)
        b0, b1 = P(s1 + 0.05, depth, z0), P(s0 - 0.05, depth, z0)
        top = bm.faces.new([b1, b0, a1, a0])
        top.normal_update()
        if top.normal.z < 0:
            top.normal_flip()
        c0, c1 = P(s1 + 0.05, depth, z0 - 0.09), P(s0 - 0.05, depth, z0 - 0.09)
        fr = bm.faces.new([c1, c0, b0, b1])                       # fascia
        d0, d1 = P(s1 + 0.05, 0.0, z0 - 0.09 + drop * 0.1), P(s0 - 0.05, 0.0, z0 - 0.09 + drop * 0.1)
        so = bm.faces.new([d1, d0, c0, c1])                       # soffit
        for f in (fr, so):
            f.normal_update()
        hm = bpy.data.meshes.new("Hisashi_%s_%d" % (ob.name, i["index"]))
        bm.to_mesh(hm); bm.free()
        ho = bpy.data.objects.new(hm.name, hm)
        sc.collection.objects.link(ho)
        hm.materials.append(hisashi_mat)
        hm.materials.append(MT.make_material("TX_Timber_Dark", "timber_planks_weathered"))
        for p in hm.polygons:
            p.material_index = 0 if p.normal.z > 0.3 else 1
        uv = hm.uv_layers.new(name="UVMap")
        for p in hm.polygons:
            for li in p.loop_indices:
                q = hm.vertices[hm.loops[li].vertex_index].co
                uv.data[li].uv = (q.dot(t), q.z if p.normal.z < 0.3 else q.dot(n))
        MT.apply_roof_uvs(ho, roof_pred=lambda p, nn: nn.z > 0.3)
        rd = hm.attributes["roof_ridge_dist"].data
        for k in range(len(rd)):
            rd[k].value = 99.0
print("textured buildings:", applied)
chosen.sort()
for c in chosen[:14]:
    print("  %5.1f m  %s  %s  %-11s %s" % c)

# ----------------------------------------------------------------------------- ground + walls
terr = next(o for o in bpy.data.objects if o.name.startswith("Terrain"))
gm = bpy.data.materials.new("TX_Ground_Mix")
T = MT._NT(gm)
tc = T.n("ShaderNodeTexCoord")
mask_img = next(n.image for n in terr.data.materials[0].node_tree.nodes if n.type == "TEX_IMAGE")
mt = T.n("ShaderNodeTexImage"); mt.image = mask_img; mask_img.colorspace_settings.name = "Non-Color"
T.l(tc.outputs["UV"], mt.inputs[0])
ms = T.n("ShaderNodeSeparateColor"); T.l(mt.outputs[0], ms.inputs[0])


def ground_set(set_name):
    L = MT.library()["sets"][set_name]
    mp = T.n("ShaderNodeMapping"); mp.inputs["Scale"].default_value = (1 / L["size_m"][0], 1 / L["size_m"][1], 1)
    T.l(tc.outputs["Object"], mp.inputs[0])
    f = L["files"]
    return [T.tex(mp.outputs[0], f["albedo"]).outputs[0], T.tex(mp.outputs[0], f["normal"], True).outputs[0],
            T.tex(mp.outputs[0], f["orm"], True).outputs[0]]


earth = ground_set("earth_moss"); gravel = ground_set("gravel"); asph = ground_set("asphalt_worn")
ishi = ground_set("ishidatami_granite")
layers = earth
for fac_s, st in ((ms.outputs[2], gravel), (ms.outputs[0], asph), (ms.outputs[1], ishi)):
    k = T.math("GREATER_THAN", fac_s, 0.5)
    layers = [T.mixc(k, a, b) for a, b in zip(layers, st)]
MT._surface(T, gm, layers[0], layers[1], layers[2], uv_map=terr.data.uv_layers[0].name if terr.data.uv_layers else "UVMap")
terr.data.materials[0] = gm


def box_mat(name, set_name, tint=None):
    m = bpy.data.materials.new(name)
    T = MT._NT(m)
    tc = T.n("ShaderNodeTexCoord")
    L = MT.library()["sets"][set_name]
    mp = T.n("ShaderNodeMapping"); mp.inputs["Scale"].default_value = (1 / L["size_m"][0],) * 3
    T.l(tc.outputs["Object"], mp.inputs[0])
    f = L["files"]
    ts = [T.tex(mp.outputs[0], f[k], k != "albedo") for k in ("albedo", "normal", "orm")]
    for t_ in ts:
        t_.projection = "BOX"; t_.projection_blend = 0.2
    bs = MT._surface(T, m, ts[0].outputs[0], ts[1].outputs[0], ts[2].outputs[0], tint=tint)
    bs.inputs["Normal"].default_value = (0, 0, 1)
    for l_ in list(m.node_tree.links):           # box projection: tangent-space normal not valid -> drop it
        if l_.to_socket == bs.inputs["Normal"]:
            m.node_tree.links.remove(l_)
    return m


stone = box_mat("TX_Ishigaki", "ishigaki_mossy")
steps = box_mat("TX_Steps", "ishidatami_granite")
fence = box_mat("TX_Fence_Timber", "timber_planks_weathered")
for o in bpy.data.objects:
    if o.type != "MESH" or not o.data.materials:
        continue
    nm = o.name
    if nm.startswith("Barrier_retaining_wall") or nm.startswith("Barrier_wall"):
        o.data.materials[0] = stone
    elif nm.startswith("Steps_"):
        o.data.materials[0] = steps
    elif nm.startswith("Barrier_fence"):
        o.data.materials[0] = fence

# ----------------------------------------------------------------------------- trees: leaf cards instead of blobs
bark = box_mat("TX_Bark", "bark_pine")
nt_ = 0
for o in [o for o in bpy.data.objects if o.name.startswith("TreeCrown_")]:
    v = Vector((o.location.x - cx, o.location.y - cy, 0))
    if v.length > 160 or (v.length > 15 and v.normalized().dot(Vector((cam_dir.x, cam_dir.y, 0)).normalized()) < 0.5):
        continue
    sp = (o.get("species") or "") + o.name
    cards = [("maple_green", 3), ("cherry_leaf", 1)] if nt_ % 3 else [("pine_needles", 3), ("maple_green", 1)]
    if nt_ % 5 == 4:
        cards = [("maple_autumn", 3), ("maple_green", 1)]
    d = o.dimensions
    MT.foliage_cards("Leaves_" + o.name, tuple(o.location), (d.x / 2, d.y / 2, d.z / 2), cards,
                     n=int(90 * d.x * d.y * d.z / 30) + 60, seed=nt_, card_scale=1.4)
    o.hide_render = True
    nt_ += 1
for o in bpy.data.objects:
    if o.name.startswith("Tree_") and o.type == "MESH":
        o.data.materials[0] = bark
print("leaf-card crowns:", nt_)
sc.cycles.transparent_max_bounces = 24

# ----------------------------------------------------------------------------- light + render
for o in [o for o in bpy.data.objects if o.type == "LIGHT"]:
    bpy.data.objects.remove(o)
w = sc.world or bpy.data.worlds.new("W"); sc.world = w
wt = w.node_tree; wt.nodes.clear()
sky = wt.nodes.new("ShaderNodeTexSky")
try:
    sky.sky_type = "MULTIPLE_SCATTERING"
except Exception:
    pass
sun_el, sun_az = math.radians(34), math.radians(232)     # mid-afternoon, from the south-west
for attr, val in (("sun_elevation", sun_el), ("sun_rotation", sun_az), ("altitude", 60.0), ("air_density", 1.2),
                  ("aerosol_density", 1.6)):
    try:
        setattr(sky, attr, val)
    except Exception:
        pass
bg = wt.nodes.new("ShaderNodeBackground"); bg.inputs["Strength"].default_value = 0.35
wo = wt.nodes.new("ShaderNodeOutputWorld")
wt.links.new(sky.outputs[0], bg.inputs[0]); wt.links.new(bg.outputs[0], wo.inputs[0])
sd = bpy.data.lights.new("Sun", "SUN"); sd.energy = 3.2; sd.angle = math.radians(0.6)
sd.color = (1.0, 0.93, 0.84)
so = bpy.data.objects.new("Sun", sd); sc.collection.objects.link(so)
so.rotation_euler = (math.pi / 2 - sun_el, 0, sun_az + math.pi / 2)
sc.render.engine = "CYCLES"
sc.cycles.device = "CPU"
sc.cycles.samples = SAMPLES
sc.cycles.use_adaptive_sampling = True
sc.cycles.adaptive_threshold = 0.03
sc.cycles.max_bounces = 4; sc.cycles.diffuse_bounces = 2; sc.cycles.glossy_bounces = 2
sc.cycles.use_denoising = True
try:
    sc.cycles.denoiser = "OPENIMAGEDENOISE"
except Exception:
    pass
sc.render.threads_mode = "FIXED"; sc.render.threads = int(os.environ.get("TEXLIB_THREADS", "3"))
sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage = 1280, 720, 100
sc.render.compositor_device = "CPU"
sc.compositing_node_group = None
sc.view_settings.view_transform = "AgX"
try:
    sc.view_settings.look = "AgX - Medium High Contrast"
except Exception:
    pass
sc.view_settings.exposure = 0.0
sc.render.image_settings.file_format = "PNG"
sc.render.filepath = OUT
bpy.ops.render.render(write_still=True)
print("saved", OUT)
