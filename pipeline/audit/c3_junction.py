"""C3: pagoda visibility across the width of upper Yasaka-dori (way 710696944) near the Ninenzaka/Sannenzaka
junction: grid of points (along x lateral) at eye height 1.6 m; art + blockout. usage: python c3_junction.py <blend> <tag>"""
import sys
import bpy  # noqa: F401
import os
import pickle
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from acommon import OUT, osm_raw, osm_xy  # noqa: E402
from shapely.geometry import LineString  # noqa: E402

src, tag = sys.argv[-2], sys.argv[-1]
bpy.ops.wm.open_mainfile(filepath=src)


def walk(lc):
    if lc.collection.name in ("80_Atmosphere", "A_Asset_Library", "00_Source_Geography"):
        lc.exclude = True
    for ch in lc.children:
        walk(ch)


walk(bpy.context.view_layer.layer_collection)
for nm in ("LM_Yasaka_Pagoda_COLLIDER",) + (("LM_Yasaka_Pagoda_PLATEAU_LOD2",) if bpy.data.objects.get("LM_Yasaka_Pagoda_HERO") else ()):
    o = bpy.data.objects.get(nm)
    if o:
        o.hide_set(True)
dg = bpy.context.evaluated_depsgraph_get()
ter = BVHTree.FromObject(bpy.data.objects["Terrain_GSI_DEM5A"], dg)
nodes, ways, _ = osm_raw()
ln = LineString(osm_xy(nodes, ways[710696944][0]))
PX, PY, PZ = 9.38, 83.34, 61.03
res = []
L = ln.length
for d in np.arange(L - 45, L + 0.01, 1.0):
    p = ln.interpolate(d); q = ln.interpolate(min(d + 0.5, L)); q0 = ln.interpolate(max(d - 0.5, 0))
    t = np.array([q.x - q0.x, q.y - q0.y]); t /= np.linalg.norm(t); nrm = np.array([-t[1], t[0]])
    for off in np.arange(-2.5, 2.51, 0.5):
        x, y = p.x + nrm[0] * off, p.y + nrm[1] * off
        h = ter.ray_cast(Vector((x, y, 400)), Vector((0, 0, -1)))
        eye = Vector((x, y, h[0].z + 1.6))
        n = 0
        for hh in (16.1, 23.9, 28.5, 38.0):
            tgt = Vector((PX, PY, PZ + hh)); dv = tgt - eye
            r = bpy.context.scene.ray_cast(dg, eye, dv.normalized(), distance=dv.length + 0.5)
            nm = (r[4].original.name if r[0] and hasattr(r[4], "original") else (r[4].name if r[0] else ""))
            if not r[0] or nm.startswith(("Yasaka_", "LM_Yasaka")) or (r[1] - eye).length > dv.length - 1:
                n += 1
        res.append((round(p.x, 1), round(p.y, 1), off, n))
pickle.dump(res, open(os.path.join(OUT, "c3_junction_%s.pkl" % tag), "wb"))
import collections
by = collections.defaultdict(list)
for x, y, off, n in res:
    by[(x, y)].append(n)
for k, v in by.items():
    print(k, "".join(str(a) for a in v))
