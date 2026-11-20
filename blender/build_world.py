"""Phase 4: geospatially aligned, untextured, traversable Blender blockout of Higashiyama.

Run:  /home/user/venv/bin/python blender/build_world.py [--no-render] [--no-glb]
Produces:
  blender/higashiyama_blockout.blend
  web/assets/world.glb          (shared with the web explorer; collision + visual base)
  renders/blockout_*.png        (quick Cycles checks)

Frame: 1 Blender unit = 1 m. +X east, +Y north, +Z = T.P. height (absolute, JGD2011 vertical).
Local origin = EPSG:6674 E -20160 / N -111160 (stored in scene custom properties).
Every object carries its source ids (plateau_id / osm_id) as custom properties.
"""
import json
import math
import os
import sys

import bpy  # noqa: I001  (bpy must be imported before bmesh)
import bmesh
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "pipeline"))
from terrain_sample import ground, H as TERR, X0, Y0, STEP, NX, NY  # noqa: E402

PROC = os.path.join(ROOT, "data", "processed")
ARGS = sys.argv[1:]
BND = json.load(open(os.path.join(PROC, "boundary.json")))
BLD = json.load(open(os.path.join(PROC, "buildings.json")))
L2 = np.load(os.path.join(PROC, "buildings_lod2.npz"))
STR = json.load(open(os.path.join(PROC, "streets.json")))
FEA = json.load(open(os.path.join(PROC, "features.json")))
STP = json.load(open(os.path.join(PROC, "steps.json")))

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.unit_settings.system = "METRIC"
scene.unit_settings.scale_length = 1.0
scene["crs"] = BND["crs"]
scene["origin_epsg6674_e"] = BND["origin_e"]
scene["origin_epsg6674_n"] = BND["origin_n"]
scene["boundary_local"] = [-200.0, -200.0, 200.0, 200.0]
scene["boundary_lonlat_corners"] = json.dumps(BND["corners_lonlat"])
scene["vertical_datum"] = "JGD2011 vertical, T.P. metres (absolute z)"


# ------------------------------------------------------------------ collections
def coll(name, parent=None):
    c = bpy.data.collections.new(name)
    (parent or scene.collection).children.link(c)
    return c


C_SRC = coll("00_Source_Geography")
C_TER = coll("10_Terrain")
C_STR = coll("20_Streets_Stairs")
C_BLD = coll("30_Buildings")
C_LM = coll("35_Landmarks")
C_WAL = coll("40_Walls_Barriers")
C_VEG = coll("50_Vegetation_Documented")
C_LGT = coll("70_Lighting")
C_BDP = coll("90_Backdrop_Outside_Boundary")
SECTIONS = {}
SECT_NAMES = {(0, 0): "SW_Kiyomizu-michi_West", (1, 0): "S_Parking_Gojo", (2, 0): "SE_Sannenzaka_Lower",
              (0, 1): "W_Higashioji_Yasaka-dori_Lower", (1, 1): "C_Koshindo_Central", (2, 1): "E_Sannenzaka_Upper",
              (0, 2): "NW_Shimokawara", (1, 2): "N_Yasaka_Pagoda_Precinct", (2, 2): "NE_Ninenzaka_Ichinenzaka"}
for k, nm in SECT_NAMES.items():
    SECTIONS[k] = coll("30_%s" % nm, C_BLD)


def section_of(x, y):
    i = min(2, max(0, int((x + 200) // (400 / 3))))
    j = min(2, max(0, int((y + 200) // (400 / 3))))
    return SECTIONS[(i, j)]


# ------------------------------------------------------------------ materials (blockout = flat clay tones)
def mat(name, rgb, rough=0.8, vcol=None):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (*rgb, 1)
    bsdf.inputs["Roughness"].default_value = rough
    if vcol:
        a = nt.nodes.new("ShaderNodeVertexColor"); a.layer_name = vcol
        mix = nt.nodes.new("ShaderNodeMix"); mix.data_type = "RGBA"; mix.blend_type = "MULTIPLY"
        mix.inputs["Factor"].default_value = 0.85
        mix.inputs["A"].default_value = (*rgb, 1)
        nt.links.new(a.outputs["Color"], mix.inputs["B"])
        nt.links.new(mix.outputs["Result"], bsdf.inputs["Base Color"])
    return m


M_ROOF = mat("BO_Roof", (0.35, 0.36, 0.38), 0.7, vcol="plateau_rgb")
M_WALL = mat("BO_Wall", (0.85, 0.80, 0.70), 0.9, vcol="plateau_rgb")
M_GROUND = mat("BO_Plinth", (0.45, 0.42, 0.38), 0.9)
M_STEP = mat("BO_StoneSteps", (0.55, 0.53, 0.50), 0.85)
M_WALLB = mat("BO_BarrierWall", (0.70, 0.66, 0.58), 0.9)
M_TRUNK = mat("BO_Trunk", (0.25, 0.18, 0.12), 0.9)
M_LEAF = mat("BO_Leaf", (0.22, 0.38, 0.18), 0.8)

# Terrain material: surface mask (R asphalt, G stone, B gravel) blended over soil
M_TER = bpy.data.materials.new("BO_Terrain_SurfaceMask")
M_TER.use_nodes = True
nt = M_TER.node_tree
bsdf = nt.nodes.get("Principled BSDF")
img = bpy.data.images.load(os.path.join(PROC, "surface_mask.png"))
img.colorspace_settings.name = "Non-Color"
tex = nt.nodes.new("ShaderNodeTexImage"); tex.image = img; tex.interpolation = "Linear"
sep = nt.nodes.new("ShaderNodeSeparateColor")
nt.links.new(tex.outputs["Color"], sep.inputs["Color"])


def mixc(fac_socket, a_rgb_or_socket, b_rgb):
    mx = nt.nodes.new("ShaderNodeMix"); mx.data_type = "RGBA"
    nt.links.new(fac_socket, mx.inputs["Factor"])
    if isinstance(a_rgb_or_socket, tuple):
        mx.inputs["A"].default_value = (*a_rgb_or_socket, 1)
    else:
        nt.links.new(a_rgb_or_socket, mx.inputs["A"])
    mx.inputs["B"].default_value = (*b_rgb, 1)
    return mx.outputs["Result"]


c1 = mixc(sep.outputs["Blue"], (0.36, 0.33, 0.24), (0.55, 0.50, 0.42))   # soil -> gravel
c2 = mixc(sep.outputs["Red"], c1, (0.30, 0.30, 0.31))                     # -> asphalt
c3 = mixc(sep.outputs["Green"], c2, (0.62, 0.60, 0.56))                   # -> granite paving
nt.links.new(c3, bsdf.inputs["Base Color"])
bsdf.inputs["Roughness"].default_value = 0.85


def link(obj, c):
    c.objects.link(obj)
    return obj


def mesh_obj(name, verts, faces, c, mats=(), face_mat=None):
    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(map(float, v)) for v in verts], [], [tuple(map(int, f)) for f in faces])
    me.validate(clean_customdata=False)
    for m in mats:
        me.materials.append(m)
    if face_mat is not None:
        me.polygons.foreach_set("material_index", np.asarray(face_mat, np.int32))
    ob = bpy.data.objects.new(name, me)
    link(ob, c)
    return ob


# ------------------------------------------------------------------ terrain
xs = X0 + np.arange(NX) * STEP; ys = Y0 + np.arange(NY) * STEP
GX, GY = np.meshgrid(xs, ys)
verts = np.c_[GX.ravel(), GY.ravel(), TERR.ravel()]
idx = np.arange(NX * NY).reshape(NY, NX)
faces = np.c_[idx[:-1, :-1].ravel(), idx[:-1, 1:].ravel(), idx[1:, 1:].ravel(), idx[1:, :-1].ravel()]
ter = mesh_obj("Terrain_GSI_DEM5A", verts, faces, C_TER, [M_TER])
me = ter.data
uv = me.uv_layers.new(name="UVMap")
mext = STP["extent"]  # x0, x1, y0, y1 of mask
lu = np.empty(len(me.loops) * 2)
vi = np.empty(len(me.loops), np.int32); me.loops.foreach_get("vertex_index", vi)
lu[0::2] = (verts[vi, 0] - mext[0]) / (mext[1] - mext[0])
lu[1::2] = (verts[vi, 1] - mext[2]) / (mext[3] - mext[2])
uv.data.foreach_set("uv", lu)
for p in me.polygons:
    p.use_smooth = True
ter["source"] = "GSI DEM5A 5 m laser DEM resampled to 2 m (bare earth)"
ter["walkable"] = True

# ------------------------------------------------------------------ buildings (PLATEAU LOD2)
P = L2["positions"]; T = L2["triangles"]; K = L2["kind"]; COL = L2["colour"]; BI = L2["building"]
order = np.argsort(BI, kind="stable")
bounds = np.searchsorted(BI[order], np.arange(len(BLD["buildings"]) + 1))
pag_id = "bldg_2b477621-2b5c-480b-a960-d2b3972db237"
nb = 0
for bi, rec in enumerate(BLD["buildings"]):
    tri_idx = order[bounds[bi]:bounds[bi + 1]]
    cx, cy = rec["centroid"]
    target = section_of(cx, cy) if rec["in_box"] else C_BDP
    if rec["id"] == pag_id:
        target = C_LM
    fp = np.array(rec["footprint"])
    tmin = float(np.min(ground(fp[:, 0], fp[:, 1])))
    bm = bmesh.new()
    col_layer = bm.loops.layers.color.new("plateau_rgb")
    if len(tri_idx):
        vmap = {}
        ground_faces = []
        for t in tri_idx:
            vs = []
            for vid in T[t]:
                if vid not in vmap:
                    vmap[vid] = bm.verts.new(tuple(map(float, P[vid])))
                vs.append(vmap[vid])
            if len({v.index for v in vs}) < 3 and len(set(vs)) < 3:
                continue
            try:
                f = bm.faces.new(vs)
            except ValueError:
                continue
            f.material_index = int(K[t])
            c = COL[t]
            rgb = (c / 255.0) if c[0] >= 0 else np.array([0.8, 0.78, 0.72])
            for lp in f.loops:
                lp[col_layer] = (*[float(v) ** 2.2 for v in rgb], 1.0)
            if K[t] == 2:
                ground_faces.append(f)
        # plinth: push ground surface down to below the lowest terrain under the footprint
        drop = max(0.0, rec["base_z"] - tmin) + 0.4
        if ground_faces:
            res = bmesh.ops.extrude_face_region(bm, geom=ground_faces)
            nv = [g for g in res["geom"] if isinstance(g, bmesh.types.BMVert)]
            bmesh.ops.translate(bm, verts=nv, vec=(0, 0, -drop))
            for g in res["geom"]:
                if isinstance(g, bmesh.types.BMFace):
                    g.material_index = 2
            bmesh.ops.delete(bm, geom=ground_faces, context="FACES_ONLY")
    else:
        # LOD1 fallback: extrude roof-edge footprint (flagged)
        ring = fp[:-1] if np.allclose(fp[0], fp[-1]) else fp
        bot = [bm.verts.new((x, y, tmin - 0.4)) for x, y in ring]
        top = [bm.verts.new((x, y, rec["top_z"])) for x, y in ring]
        try:
            ft = bm.faces.new(top); ft.material_index = 0
            for i in range(len(ring)):
                j = (i + 1) % len(ring)
                f = bm.faces.new([bot[i], bot[j], top[j], top[i]]); f.material_index = 1
        except ValueError:
            pass
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.01)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me = bpy.data.meshes.new(rec["id"])
    bm.to_mesh(me); bm.free()
    for m in (M_ROOF, M_WALL, M_GROUND):
        me.materials.append(m)
    name = ("LM_Yasaka_Pagoda_PLATEAU_LOD2" if rec["id"] == pag_id else
            "B_%s" % rec["id"][5:13]) if True else rec["id"]
    ob = bpy.data.objects.new(name, me)
    target.objects.link(ob)
    ob["plateau_id"] = rec["id"]
    ob["source"] = "PLATEAU 2025 Kyoto LOD2" if len(tri_idx) else "PLATEAU 2025 Kyoto LOD1 (extruded roof edge)"
    for k in ("name", "usage", "usage_ja", "year", "height", "storeys", "structure", "base_z", "top_z"):
        if rec.get(k) is not None:
            ob[k] = rec[k]
    ob["in_boundary"] = rec["in_box"]
    ob["collide"] = True
    nb += 1
print("buildings", nb)
pag = bpy.data.objects["LM_Yasaka_Pagoda_PLATEAU_LOD2"]
pag["hero_replacement"] = "custom high-detail model (blender/hero_pagoda.py), total 38.8 m measured/derived (PLATEAU roof apex 28.7 m + photo-derived sorin); popular ~46 m figure disputed"

# ------------------------------------------------------------------ stairs (OSM highway=steps)
for s in STP["steps"]:
    c = np.array(s["coords"])
    seg = np.diff(c, axis=0); sl = np.linalg.norm(seg, axis=1)
    cum = np.r_[0, np.cumsum(sl)]; L = cum[-1]
    if L < 0.3:
        continue
    n, w = s["n"], s["width_m"]
    r = (s["z_top"] - s["z_bottom"]) / n
    vs, fs = [], []

    def at(d):
        i = min(len(sl) - 1, int(np.searchsorted(cum, d, side="right") - 1))
        t = (d - cum[i]) / max(sl[i], 1e-6)
        p = c[i] + seg[i] * t
        dvec = seg[i] / max(sl[i], 1e-6)
        return p, dvec

    for k in range(n):
        d0, d1 = k * L / n, (k + 1) * L / n
        # step index counted from the bottom end
        level = (k + 1) if s["ascending_along_way"] else (n - k)
        ztop = s["z_bottom"] + level * r
        p0, dv0 = at(d0); p1, dv1 = at(d1)
        nrm0 = np.array([-dv0[1], dv0[0]]) * w / 2; nrm1 = np.array([-dv1[1], dv1[0]]) * w / 2
        quad = [p0 - nrm0, p1 - nrm1, p1 + nrm1, p0 + nrm0]
        zb = s["z_bottom"] - 0.8
        base = len(vs)
        for q in quad:
            vs.append((q[0], q[1], zb))
        for q in quad:
            vs.append((q[0], q[1], ztop))
        fs += [(base + 4, base + 5, base + 6, base + 7), (base + 0, base + 3, base + 2, base + 1),
               (base + 0, base + 1, base + 5, base + 4), (base + 1, base + 2, base + 6, base + 5),
               (base + 2, base + 3, base + 7, base + 6), (base + 3, base + 0, base + 4, base + 7)]
    ob = mesh_obj("Steps_osm%d" % s["osm_id"], vs, fs, C_STR, [M_STEP])
    ob["osm_id"] = str(s["osm_id"]); ob["name_ja"] = s["name"] or ""; ob["n_steps"] = n
    ob["n_src"] = s["n_src"]; ob["riser_m"] = s["riser_m"]; ob["tread_m"] = s["tread_m"]
    ob["width_m"] = w; ob["width_src"] = s["width_src"]; ob["walkable"] = True

# ------------------------------------------------------------------ walls / fences (OSM barrier=*)
DEF_H = dict(wall=1.8, fence=1.2, retaining_wall=1.0, hedge=1.4, city_wall=2.5, guard_rail=0.8, bollard=0.9,
             handrail=1.0, kerb=0.15, gate=2.0)
for bar in FEA["barriers"]:
    if bar.get("point") or bar["barrier"] in ("kerb", "gate", "lift_gate", "bollard"):
        continue
    c = np.array(bar["coords"])
    try:
        h = float((bar.get("height") or "").replace("m", "")) if bar.get("height") else DEF_H.get(bar["barrier"], 1.5)
    except ValueError:
        h = DEF_H.get(bar["barrier"], 1.5)
    # densify to 1 m so the wall follows terrain
    pts = [c[0]]
    for a, b2 in zip(c[:-1], c[1:]):
        k = max(1, int(np.linalg.norm(b2 - a)))
        for t in range(1, k + 1):
            pts.append(a + (b2 - a) * t / k)
    pts = np.array(pts)
    if len(pts) < 2:
        continue
    th = 0.35 if bar["barrier"] in ("wall", "retaining_wall", "city_wall") else 0.12
    zg = ground(pts[:, 0], pts[:, 1])
    vs, fs = [], []
    for i in range(len(pts)):
        dv = pts[min(i + 1, len(pts) - 1)] - pts[max(i - 1, 0)]
        dv = dv / max(np.linalg.norm(dv), 1e-6)
        nv = np.array([-dv[1], dv[0]]) * th / 2
        for sgn in (-1, 1):
            q = pts[i] + sgn * nv
            vs += [(q[0], q[1], zg[i] - 0.3), (q[0], q[1], zg[i] + h)]
    for i in range(len(pts) - 1):
        a, b2 = 4 * i, 4 * (i + 1)
        fs += [(a, b2, b2 + 1, a + 1), (a + 2, a + 3, b2 + 3, b2 + 2), (a + 1, b2 + 1, b2 + 3, a + 3)]
    ob = mesh_obj("Barrier_%s_osm%d" % (bar["barrier"], bar["osm_id"]), vs, fs, C_WAL, [M_WALLB])
    ob["osm_id"] = str(bar["osm_id"]); ob["barrier"] = bar["barrier"]; ob["height_m"] = h
    ob["height_src"] = "osm:height" if bar.get("height") else "default (inferred)"; ob["collide"] = True

# ------------------------------------------------------------------ documented trees (OSM natural=tree / tree_row)
bpy.ops.mesh.primitive_cylinder_add(vertices=8, radius=0.18, depth=1.0, location=(0, 0, 0.5))
trunk_proto = bpy.context.active_object; trunk_proto.data.materials.append(M_TRUNK)
bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2, radius=1.0, location=(0, 0, 0))
crown_proto = bpy.context.active_object; crown_proto.data.materials.append(M_LEAF)
for o in (trunk_proto, crown_proto):
    for cc in o.users_collection:
        cc.objects.unlink(o)
tree_pts = []
for t in FEA["trees"]:
    if t["kind"] == "tree":
        tree_pts.append((t["x"], t["y"], t.get("osm_id"), t["tags"]))
    else:
        c = np.array(t["coords"]); ln = np.r_[0, np.cumsum(np.linalg.norm(np.diff(c, axis=0), axis=1))]
        for d in np.arange(0, ln[-1], 5.0):
            i = min(len(c) - 2, int(np.searchsorted(ln, d, side="right") - 1))
            p = c[i] + (c[i + 1] - c[i]) * (d - ln[i]) / max(ln[i + 1] - ln[i], 1e-6)
            tree_pts.append((p[0], p[1], t["osm_id"], t["tags"]))
for k, (x, y, oid, tags) in enumerate(tree_pts):
    z = float(ground(x, y))
    try:
        h = float(tags.get("height", "").replace("m", "")) if tags.get("height") else 7.0
    except ValueError:
        h = 7.0
    tr = bpy.data.objects.new("Tree_osm%s_%d" % (oid, k), trunk_proto.data); C_VEG.objects.link(tr)
    tr.location = (x, y, z); tr.scale = (1, 1, h * 0.45)
    cr = bpy.data.objects.new("TreeCrown_osm%s_%d" % (oid, k), crown_proto.data); C_VEG.objects.link(cr)
    cr.location = (x, y, z + h * 0.62); cr.scale = (h * 0.32, h * 0.32, h * 0.28)
    for o in (tr, cr):
        o["osm_id"] = str(oid or ""); o["species"] = tags.get("species", tags.get("species:ja", "")); o["documented"] = True
        o["height_src"] = "osm:height" if tags.get("height") else "default 7 m (inferred)"

# ------------------------------------------------------------------ source geography overlays
bnd = mesh_obj("Boundary_400m_EPSG6674", [(-200, -200, 45), (200, -200, 45), (200, 200, 45), (-200, 200, 45)], [], C_SRC)
bnd.data.edges.add(0)
me = bnd.data; me.edges.add(4); me.edges.foreach_set("vertices", [0, 1, 1, 2, 2, 3, 3, 0])
bnd.hide_render = True
for s in STR["streets"]:
    if not s["in_box"]:
        continue
    c = s["coords"]; z = s["z"]
    me = bpy.data.meshes.new("osm%d" % s["osm_id"])
    me.from_pydata([(x, y, zz + 0.05) for (x, y), zz in zip(c, z)], [(i, i + 1) for i in range(len(c) - 1)], [])
    ob = bpy.data.objects.new("OSM_%s_%d" % (s["highway"], s["osm_id"]), me); C_SRC.objects.link(ob)
    ob["osm_id"] = str(s["osm_id"]); ob["highway"] = s["highway"]; ob["name_ja"] = s["name"] or ""
    ob["width_m"] = s["width_m"]; ob["width_src"] = s["width_src"]; ob["surface"] = s["surface"] or ""
    ob.hide_render = True
C_SRC.hide_render = True

# ------------------------------------------------------------------ light + camera for checks
sun = bpy.data.lights.new("Sun", "SUN"); sun.energy = 3.5; sun.angle = math.radians(1.5)
so = bpy.data.objects.new("Sun", sun); C_LGT.objects.link(so)
so.rotation_euler = (math.radians(62), 0, math.radians(-115))  # late afternoon, from the WSW
world = bpy.data.worlds.new("World"); scene.world = world; world.use_nodes = True
bg = world.node_tree.nodes.get("Background"); bg.inputs["Color"].default_value = (0.55, 0.62, 0.8, 1); bg.inputs["Strength"].default_value = 0.8


def add_cam(name, loc, target, lens=28):
    cd = bpy.data.cameras.new(name); cd.lens = lens; cd.clip_end = 2000
    co = bpy.data.objects.new(name, cd); C_LGT.objects.link(co)
    co.location = loc
    d = np.array(target) - np.array(loc)
    co.rotation_euler = (math.atan2(math.hypot(d[0], d[1]), -d[2]), 0, math.atan2(d[1], d[0]) - math.pi / 2)
    return co


px, py = BND["pagoda"]["local_x"], BND["pagoda"]["local_y"]
gz = lambda x, y: float(ground(x, y))
cams = {
    # camera positions snapped onto OSM centrelines (way 24516359 Yasaka-dori, 179116810 Sannenzaka steps, 30913263 Ninenzaka)
    "Cam_YasakaDori_East": add_cam("Cam_YasakaDori_East", (-79.0, 88.2, gz(-79, 88.2) + 1.6), (px, py, gz(px, py) + 16), 35),
    "Cam_Aerial_SW": add_cam("Cam_Aerial_SW", (-330, -330, 330), (0, 0, 60), 35),
    "Cam_Sannenzaka_Stairs": add_cam("Cam_Sannenzaka_Stairs", (166.5, -142.0, gz(166.5, -142) + 1.6), (151, -177, gz(151, -177) + 2.0), 28),
    "Cam_Ninenzaka_South": add_cam("Cam_Ninenzaka_South", (153.6, 98.0, gz(153.6, 98) + 1.6), (155.5, 45, gz(155.5, 45) + 2.5), 28),
}
scene.camera = cams["Cam_YasakaDori_East"]

out_blend = os.path.join(HERE, "higashiyama_blockout.blend")
bpy.ops.wm.save_as_mainfile(filepath=out_blend, compress=True)
print("saved", out_blend)

if "--no-glb" not in ARGS:
    os.makedirs(os.path.join(ROOT, "web", "assets"), exist_ok=True)
    for o in scene.objects:
        o.select_set(o.type == "MESH" and not o.name.startswith("OSM_") and not o.name.startswith("Boundary"))
    bpy.ops.export_scene.gltf(filepath=os.path.join(ROOT, "web", "assets", "world.glb"), export_format="GLB",
                              use_selection=True, export_extras=True, export_apply=True,
                              export_yup=True, export_image_format="AUTO")
    print("glb exported")

if "--no-render" not in ARGS:
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"; scene.cycles.samples = 24; scene.cycles.use_denoising = True
    scene.render.resolution_x, scene.render.resolution_y = 1280, 720
    os.makedirs(os.path.join(ROOT, "renders"), exist_ok=True)
    for nm, cam in cams.items():
        if "--only-street" in ARGS and nm == "Cam_Aerial_SW":
            continue
        scene.camera = cam
        scene.render.filepath = os.path.join(ROOT, "renders", "blockout_%s.png" % nm)
        bpy.ops.render.render(write_still=True)
        print("rendered", nm)
