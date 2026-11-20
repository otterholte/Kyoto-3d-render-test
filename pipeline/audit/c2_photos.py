"""C2: Commons photo viewpoints. For each selected photo: geotag -> EPSG:6674, snap to the nearest OSM highway
centreline (geotags of street photos are typically 5-10 m off), pagoda visibility in blockout + art scenes
(blocker identified, instances resolved to their empty), and a low-res Cycles render of the blockout view.
usage: python c2_photos.py <blockout.blend> <art.blend> <render_dir>"""
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
from acommon import OUT, ROOT, osm_raw, osm_xy, T_OSM, OE, ON  # noqa: E402
from shapely.geometry import LineString, Point, box  # noqa: E402

blk, art, rdir = sys.argv[-3], sys.argv[-2], sys.argv[-1]
os.makedirs(rdir, exist_ok=True)
P = json.load(open(os.path.join(ROOT, "docs", "references", "commons_geotagged.json")))
# photo index: (snap?, lens mm (36 mm sensor), aim height above pagoda base, heading override)
SEL = {244: (True, 70, 22, None), 238: (True, 30, 18, None), 199: (True, 28, 18, None), 189: (True, 28, 18, None),
       6: (True, 30, 16, None), 268: (False, 45, 18, None), 243: (True, 28, 18, None), 190: (True, 26, 18, None),
       45: (True, 28, 18, None), 56: (True, 28, 18, None), 246: (True, 28, 18, None), 274: (True, 28, 18, None),
       197: (True, 28, 18, None), 44: (True, 28, 18, None), 18: (True, 24, 18, None), 269: (True, 30, 18, None)}
# street the photo was evidently taken on (read from the photo content), where the nearest centreline is a side lane
OVR = {238: 24516359, 199: 710696944, 189: 710696944, 18: 710696944, 6: 157527424, 246: 24516359, 269: 24516359,
       45: 710696944, 190: 710696944, 44: 710696944}
nodes, ways, rels = osm_raw()
BOX = box(-200, -200, 200, 200)
lines = []
for wid, (nds, t) in ways.items():
    if "highway" not in t or t["highway"] in ("construction", "proposed"):
        continue
    xy = osm_xy(nodes, nds)
    if len(xy) >= 2 and LineString(xy).intersects(BOX):
        lines.append((wid, t.get("name"), LineString(xy)))
PX, PY, PZ = 9.38, 83.34, 61.03
TGT = {"storey1": 3.0, "eave1": 8.3, "eave3": 16.1, "eave5": 23.9, "apex": 28.5, "tip": 38.0}
rows = {}
for i, cfg in SEL.items():
    p = P[i]
    e, n = T_OSM.transform(p["camera_latlon"][1], p["camera_latlon"][0])
    x, y = e - OE, n - ON
    sx, sy, sw, sd = x, y, None, 0.0
    if cfg[0]:
        cand = [l for l in lines if l[0] == OVR[i]] if i in OVR else lines
        best = min(cand, key=lambda l: l[2].distance(Point(x, y)))
        q = best[2].interpolate(best[2].project(Point(x, y)))
        sx, sy, sw, sd = q.x, q.y, best[0], best[2].distance(Point(x, y))
    along = []
    if sw is not None:
        ln = [l for l in lines if l[0] == sw][0][2]
        d0 = ln.project(Point(sx, sy))
        along = [ln.interpolate(d) for d in np.arange(max(0, d0 - 15), min(ln.length, d0 + 15.01), 1.0)]
    rows[i] = dict(i=i, title=p["title"], raw=(x, y), snapped=(sx, sy), snap_way=sw, snap_dist=sd, heading=p.get("heading_deg"),
                   along=[(q.x, q.y) for q in along],
                   lens=cfg[1], bearing_to_pagoda=(math.degrees(math.atan2(PX - sx, PY - sy)) + 360) % 360, vis={})


def setup(path):
    bpy.ops.wm.open_mainfile(filepath=path)
    vl = bpy.context.view_layer

    def walk(lc):
        if lc.collection.name in ("80_Atmosphere", "A_Asset_Library", "00_Source_Geography"):
            lc.exclude = True
        for ch in lc.children:
            walk(ch)
    walk(vl.layer_collection)
    for nm in ("LM_Yasaka_Pagoda_COLLIDER",):
        o = bpy.data.objects.get(nm)
        if o:
            o.hide_set(True); o.hide_render = True
    if bpy.data.objects.get("LM_Yasaka_Pagoda_HERO") and bpy.data.objects.get("LM_Yasaka_Pagoda_PLATEAU_LOD2"):
        bpy.data.objects["LM_Yasaka_Pagoda_PLATEAU_LOD2"].hide_set(True)
    for im in bpy.data.images:
        if "surface_mask" in im.filepath:
            im.filepath = os.path.join(ROOT, "data", "processed", "surface_mask.png")
    dg = bpy.context.evaluated_depsgraph_get()
    ter = BVHTree.FromObject(bpy.data.objects["Terrain_GSI_DEM5A"], dg)
    emp = {}
    for o in bpy.data.objects:
        if o.type == "EMPTY":
            emp[tuple(round(v, 1) for v in o.matrix_world.translation)] = o
    return dg, ter, emp


def vis(dg, emp, eye):
    sc = bpy.context.scene
    out = {}
    for k, h in TGT.items():
        tgt = Vector((PX, PY, PZ + h)); d = tgt - Vector(eye); L = d.length
        r = sc.ray_cast(dg, Vector(eye), d.normalized(), distance=L + 0.5)
        if not r[0]:
            out[k] = "visible"; continue
        nm = r[4].original.name if hasattr(r[4], "original") else r[4].name
        if nm.startswith(("Yasaka_", "LM_Yasaka")) or (r[1] - Vector(eye)).length > L - 1.0:
            out[k] = "visible"; continue
        e = emp.get(tuple(round(v, 1) for v in r[5].translation))
        who = nm
        if e is not None and e.instance_collection is not None:
            who = "%s [%s, artistic=%s, %s]" % (e.name, e.users_collection[0].name, e.get("artistic"), e.get("osm_id", ""))
        out[k] = "blocked by %s at %.1f m" % (who, (r[1] - Vector(eye)).length)
    return out


for tag, path in (("blockout", blk), ("art", art)):
    dg, ter, emp = setup(path)
    for i, r in rows.items():
        for which in ("raw", "snapped"):
            x, y = r[which]
            h = ter.ray_cast(Vector((x, y, 400)), Vector((0, 0, -1)))
            z = h[0].z if h[0] else 70.0
            r.setdefault("ground", {})[which] = z
            r["vis"]["%s_%s" % (tag, which)] = vis(dg, emp, (x, y, z + 1.6))
        al = []
        for (x, y) in r["along"]:
            h = ter.ray_cast(Vector((x, y, 400)), Vector((0, 0, -1)))
            v = vis(dg, emp, (x, y, (h[0].z if h[0] else 70.0) + 1.6))
            al.append(sum(v[k] == "visible" for k in ("eave3", "eave5", "apex", "tip")))
        r["along_%s" % tag] = al
    if tag == "blockout":
        sc = bpy.context.scene
        sc.render.engine = "CYCLES"; sc.cycles.device = "CPU"; sc.cycles.samples = 8; sc.cycles.use_denoising = False
        sc.render.threads_mode = "FIXED"; sc.render.threads = 2
        sc.render.resolution_x, sc.render.resolution_y = 480, 360
        sc.render.image_settings.file_format = "PNG"
        cd = bpy.data.cameras.new("AuditCam"); cam = bpy.data.objects.new("AuditCam", cd)
        sc.collection.objects.link(cam); sc.camera = cam; cd.sensor_width = 36; cd.clip_end = 3000
        for i, r in rows.items():
            x, y = r["snapped"]; z = r["ground"]["snapped"] + 1.6
            if i == 268:
                z += 6.0  # elevated viewpoint (photo shows roofs from above)
                r["render_eye_note"] = "eye raised +6 m (photo taken from an elevated position)"
            cd.lens = r["lens"]
            yaw = math.radians(r["bearing_to_pagoda"])
            dist = math.hypot(PX - x, PY - y)
            pitch = math.atan2(PZ + SEL[i][2] - z, dist)
            cam.location = (x, y, z)
            cam.rotation_euler = (math.pi / 2 + pitch, 0, -yaw)
            sc.render.filepath = os.path.join(rdir, "blk_%03d.png" % i)
            if not os.path.exists(sc.render.filepath):
                bpy.ops.render.render(write_still=True)
            r["render"] = sc.render.filepath
            r["render_cam"] = dict(xyz=(x, y, z), yaw_deg=r["bearing_to_pagoda"], pitch_deg=math.degrees(pitch), lens=r["lens"])
pickle.dump(rows, open(os.path.join(OUT, "c2_photos.pkl"), "wb"))
for i, r in rows.items():
    print(i, r["title"][5:45], "snap %.1f m to way %s" % (r["snap_dist"], r["snap_way"]), "along+-15m (n tiers>=eave3 visible) blk", r.get("along_blockout"), "art", r.get("along_art"))
    for k, v in r["vis"].items():
        print("   ", k, {a: (b if b == "visible" else b[:70]) for a, b in v.items()})
