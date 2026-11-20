"""C: ray-cast probes in a .blend (bpy). usage: python c_scene_probe.py <file.blend> <tag>
  * terrain mesh height at DEM5A pixel centres, PLATEAU TIN triangle centroids, GSI contour / ElevPt points
  * stair tread heights vs terrain at both ends
  * OSM highway centrelines (1 m spacing): inside-building test is done later; here: upward obstruction ray 0.05-1.9 m
  * cross-sections: horizontal clear width at 0.5 m and 1.2 m above the walkable surface
  * sightlines from Commons camera positions and from street sweeps to points on the pagoda axis
Output: out/probe_<tag>.pkl"""
import sys
import bpy  # noqa: F401
import json
import math
import os
import pickle
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from acommon import OUT, ROOT, osm_raw, osm_xy, gsi_fgd, T_OSM, OE, ON  # noqa: E402
from shapely.geometry import LineString, box  # noqa: E402

src, tag = sys.argv[-2], sys.argv[-1]
bpy.ops.wm.open_mainfile(filepath=src)
scene = bpy.context.scene
vl = bpy.context.view_layer


def set_exclude(names):
    def walk(lc):
        if lc.collection.name in names:
            lc.exclude = True
        for ch in lc.children:
            walk(ch)
    walk(vl.layer_collection)


set_exclude({"80_Atmosphere", "A_Asset_Library", "00_Source_Geography", "70_Lighting"})
dg = bpy.context.evaluated_depsgraph_get()
ter = bpy.data.objects["Terrain_GSI_DEM5A"]
tbvh = BVHTree.FromObject(ter, dg)
steps = [o for o in bpy.data.objects if o.name.startswith("Steps_osm") and o.type == "MESH"]
sbvh = {o.name: BVHTree.FromObject(o, dg) for o in steps}
sbb = {}
for o in steps:
    bb = np.array([list(o.matrix_world @ Vector(c)) for c in o.bound_box])
    sbb[o.name] = (bb.min(0), bb.max(0))


def tz(x, y):
    h = tbvh.ray_cast(Vector((x, y, 400.0)), Vector((0, 0, -1)))
    return h[0].z if h[0] is not None else float("nan")


def walkz(x, y):
    z = tz(x, y)
    for n, (a, b) in sbb.items():
        if a[0] - 0.05 < x < b[0] + 0.05 and a[1] - 0.05 < y < b[1] + 0.05:
            h = sbvh[n].ray_cast(Vector((x, y, 400.0)), Vector((0, 0, -1)))
            if h[0] is not None:
                z = max(z, h[0].z)
    return z


def ident(ob, mat):
    o = ob.original if hasattr(ob, "original") else ob
    cols = [c.name for c in o.users_collection]
    return dict(name=o.name, colls=cols, t=tuple(round(v, 2) for v in mat.translation),
                artistic=o.get("artistic"), detail_class=o.get("detail_class"))


def cast(origin, direction, dist):
    r = scene.ray_cast(dg, Vector(origin), Vector(direction).normalized(), distance=dist)
    if not r[0]:
        return None
    return dict(d=(r[1] - Vector(origin)).length, loc=tuple(r[1]), **ident(r[4], r[5]))


R = {}
# ---------------- terrain samples
ref = np.load(os.path.join(OUT, "dem_ref.npz"))
D = ref["dem5a"]; D = D[(np.abs(D[:, 0]) <= 198) & (np.abs(D[:, 1]) <= 198)]
R["dem5a"] = np.c_[D, [tz(x, y) for x, y in D[:, :2]]]
T = ref["tin"]
c = T.mean(1)
sel = (np.abs(c[:, 0]) <= 198) & (np.abs(c[:, 1]) <= 198)
c = c[sel]
rng = np.random.default_rng(9)
c = c[rng.choice(len(c), size=min(2500, len(c)), replace=False)]
R["tin"] = np.c_[c, [tz(x, y) for x, y in c[:, :2]]]
cn = []
for f in gsi_fgd("Cntr"):
    ln = LineString(f["xy"]).intersection(box(-198, -198, 198, 198))
    for g in getattr(ln, "geoms", [ln]):
        if g.is_empty or g.length < 1:
            continue
        for d in np.arange(0, g.length, 10.0):
            p = g.interpolate(d); cn.append((p.x, p.y, float(f["alti"]), tz(p.x, p.y)))
R["contours"] = np.array(cn)
R["elevpt"] = [(f["xy"][0][0], f["xy"][0][1], f["alti"], tz(f["xy"][0][0], f["xy"][0][1])) for f in gsi_fgd("ElevPt")]
# ---------------- stairs
SJ = {s["osm_id"]: s for s in json.load(open(os.path.join(ROOT, "data", "processed", "steps.json")))["steps"]}
st = []
for o in steps:
    oid = int(o["osm_id"])
    s = SJ[oid]
    cxy = np.array(s["coords"])
    if np.abs(cxy).max() > 200:
        continue
    ends = []
    for k, (p, q) in enumerate(((cxy[0], cxy[1]), (cxy[-1], cxy[-2]))):
        u = (p - q) / max(np.linalg.norm(p - q), 1e-6)
        inside = p - u * 0.25  # on the flight, 25 cm from its end
        outside = p + u * 0.6  # beyond the end, on the street
        h = sbvh[o.name].ray_cast(Vector((inside[0], inside[1], 400.0)), Vector((0, 0, -1)))
        tread = h[0].z if h[0] is not None else float("nan")
        ends.append(dict(end=k, tread_z=tread, terrain_beyond=tz(*outside), terrain_at_end=tz(*p)))
    st.append(dict(osm_id=oid, name=s["name"], n=s["n"], n_src=s["n_src"], riser=s["riser_m"], z_bottom=s["z_bottom"],
                   z_top=s["z_top"], asc=s["ascending_along_way"], ends=ends))
R["steps"] = st
# ---------------- centreline obstruction (all OSM highway ways in the box)
nodes, ways, rels = osm_raw()
BOX = box(-200, -200, 200, 200)
cl = []
for wid, (nds, t) in ways.items():
    if "highway" not in t or t["highway"] in ("construction", "proposed", "platform", "bus_stop"):
        continue
    xy = osm_xy(nodes, nds)
    if len(xy) < 2:
        continue
    li = LineString(xy).intersection(BOX)
    for g in getattr(li, "geoms", [li]):
        if g.is_empty or g.geom_type != "LineString":
            continue
        for d in np.arange(0, g.length, 1.0):
            p = g.interpolate(d)
            z = walkz(p.x, p.y)
            h = cast((p.x, p.y, z + 0.05), (0, 0, 1), 1.85)
            cl.append(dict(osm_id=wid, highway=t["highway"], name=t.get("name"), x=p.x, y=p.y, z=z, terr=tz(p.x, p.y), hit=h))
R["centreline"] = cl
# ---------------- cross-sections
X = json.load(open(os.path.join(OUT, "xsections.json")))
for x in X:
    z = walkz(x["x"], x["y"])
    x["walk_z"] = z
    for hz in (0.5, 1.2):
        for sgn, side in ((1, "R"), (-1, "L")):
            reach = 25 if x["street"] == "Higashioji" else 15
            x["hit_%s_%.1f" % (side, hz)] = cast((x["x"], x["y"], z + hz), (sgn * x["nx"], sgn * x["ny"], 0), reach)
R["xsections"] = X
# ---------------- sightlines
hero = bpy.data.objects.get("LM_Yasaka_Pagoda_HERO")
for nm in ("LM_Yasaka_Pagoda_COLLIDER",):
    o = bpy.data.objects.get(nm)
    if o:
        o.hide_set(True)
if hero is not None:
    pl = bpy.data.objects.get("LM_Yasaka_Pagoda_PLATEAU_LOD2")
    if pl:
        pl.hide_set(True)
dg = bpy.context.evaluated_depsgraph_get()
PX, PY, PZ = 9.38, 83.34, 61.03
TGT = {"storey1": 3.0, "eave1": 8.3, "eave3": 16.1, "eave5": 23.9, "apex": 28.5, "sorin_mid": 33.0, "tip": 38.0}
PAGNAMES = ("Yasaka_", "LM_Yasaka")


def vis(eye):
    out = {}
    for k, h in TGT.items():
        tgt = np.array([PX, PY, PZ + h])
        dvec = tgt - np.array(eye)
        L = float(np.linalg.norm(dvec))
        r = cast(eye, dvec, L + 0.5)
        if r is None:
            out[k] = (True, None)
        else:
            ok = r["name"].startswith(PAGNAMES) or r["d"] > L - 1.0
            out[k] = (bool(ok), None if ok else (r["name"], r["colls"][:1], round(r["d"], 1)))
    return out


photos = json.load(open(os.path.join(ROOT, "docs", "references", "commons_geotagged.json")))
ph = []
for i, p in enumerate(photos):
    if not p.get("camera_latlon"):
        continue
    e, n = T_OSM.transform(p["camera_latlon"][1], p["camera_latlon"][0])
    x, y = e - OE, n - ON
    if abs(x) > 200 or abs(y) > 200:
        continue
    z = walkz(x, y)
    ph.append(dict(i=i, title=p["title"], x=x, y=y, z=z, heading=p.get("heading_deg"), note=p.get("geotag_note"),
                   vis=vis((x, y, z + 1.6))))
R["photo_sightlines"] = ph
sweep = []
for name, wids in {"Yasaka-dori": [24516359, 710696944], "Ninenzaka": [30913263, 30882783, 550360170, 1491152444, 1569088149],
                   "Sannenzaka": [526198271, 1569088146, 1569088147, 179116810, 1251544286]}.items():
    for wid in wids:
        xy = osm_xy(nodes, ways[wid][0])
        ln = LineString(xy).intersection(BOX)
        for g in getattr(ln, "geoms", [ln]):
            if g.is_empty:
                continue
            for d in np.arange(0, g.length, 4.0):
                p = g.interpolate(d)
                z = walkz(p.x, p.y)
                sweep.append(dict(street=name, osm_id=wid, x=p.x, y=p.y, z=z, vis=vis((p.x, p.y, z + 1.6))))
R["sweep"] = sweep
pickle.dump(R, open(os.path.join(OUT, "probe_%s.pkl" % tag), "wb"))
print("done", {k: len(v) for k, v in R.items()})
