"""Ishidatami paving ribbons along the Priority-2 street centrelines (documented geometry: OSM centreline,
mapped width; surface=paving_stones/sett).  UVMap: u = metres along, v = metres across.
UVEdge.y = distance to the nearest street edge (m) -> gutter stones in the shader."""
import numpy as np

from kit_common import P2_STREETS, gz, mesh_obj, street_index


_BT = {}


def _extents(pts, nrm, w, reach=3.0):
    """Half-widths left/right: mapped width, extended up to `reach` m to the nearest building wall line."""
    from shapely.geometry import LineString, Polygon
    from shapely.strtree import STRtree
    from kit_common import data
    if "t" not in _BT:
        polys = []
        for b in data("buildings")["buildings"]:
            try:
                polys.append(Polygon(b["footprint"]).buffer(0))
            except Exception:
                pass
        _BT["p"] = polys; _BT["t"] = STRtree(polys)
    polys, tree = _BT["p"], _BT["t"]
    out = []
    for sgn in (-1, 1):
        hs = []
        for p, nv in zip(pts, nrm):
            a = p + nv * sgn * (w / 2 - 0.5)
            b = p + nv * sgn * (w / 2 + reach)
            ray = LineString([a, b])
            best = None
            for k in tree.query(ray):
                inter = polys[k].intersection(ray)
                if inter.is_empty:
                    continue
                dd = min(np.linalg.norm(np.array(c) - p) for g in getattr(inter, "geoms", [inter]) for c in g.coords)
                best = dd if best is None else min(best, dd)
            hs.append(w / 2 if best is None else float(np.clip(best + 0.6, w / 2, w / 2 + reach)))
        hs = np.array(hs)
        # smooth along the street so the edge does not zig-zag
        k = np.ones(5) / 5
        hs = np.convolve(np.pad(hs, 2, mode="edge"), k, mode="valid")
        out.append(hs)
    return out[0], out[1]


def ribbon(s, coll, mat, zoff=0.035):
    c = np.array(s["coords"], float)
    seg = np.diff(c, axis=0); sl = np.linalg.norm(seg, axis=1)
    keep = np.r_[True, sl > 0.05]
    c = c[keep]
    seg = np.diff(c, axis=0); sl = np.linalg.norm(seg, axis=1)
    cum = np.r_[0, np.cumsum(sl)]
    L = cum[-1]
    n = max(2, int(np.ceil(L / 0.5)) + 1)
    d = np.linspace(0, L, n)
    pts = np.c_[np.interp(d, cum, c[:, 0]), np.interp(d, cum, c[:, 1])]
    tg = np.gradient(pts, axis=0)
    tg /= np.maximum(np.linalg.norm(tg, axis=1, keepdims=True), 1e-9)
    # smooth tangents to avoid folds at sharp bends
    for _ in range(3):
        tg[1:-1] = (tg[:-2] + 2 * tg[1:-1] + tg[2:]) / 4
        tg /= np.maximum(np.linalg.norm(tg, axis=1, keepdims=True), 1e-9)
    nrm = np.c_[-tg[:, 1], tg[:, 0]]
    w = float(s["width_m"] or 4.0)
    hl, hr = _extents(pts, nrm, w)
    m = 7
    V, UV, UE = [], [], []
    for i in range(n):
        offs = np.r_[-hl[i], np.linspace(-hl[i] + 0.3, hr[i] - 0.3, m - 2), hr[i]]
        for o in offs:
            p = pts[i] + nrm[i] * o
            V.append((p[0], p[1], 0.0)); UV.append((d[i], o)); UE.append((o / (w / 2), min(hl[i] + o, hr[i] - o)))
    V = np.array(V)
    V[:, 2] = gz(V[:, 0], V[:, 1]) + zoff
    F = []
    for i in range(n - 1):
        for j in range(m - 1):
            a = i * m + j
            F.append((a, a + m, a + m + 1, a + 1))
    ob = mesh_obj("Paving_osm%d" % s["osm_id"], V, F, coll, [mat])
    me = ob.data
    vi = np.empty(len(me.loops), np.int32); me.loops.foreach_get("vertex_index", vi)
    for name, arr in (("UVMap", np.array(UV)), ("UVEdge", np.array(UE))):
        uv = me.uv_layers.new(name=name)
        uv.data.foreach_set("uv", arr[vi].ravel())
    me.uv_layers.active_index = 0
    for p in me.polygons:
        p.use_smooth = True
    ob["osm_id"] = str(s["osm_id"]); ob["name_ja"] = s["name"] or ""; ob["surface"] = s["surface"] or ""
    ob["width_m"] = w; ob["width_src"] = s["width_src"]; ob["walkable"] = True
    ob["detail_class"] = "inferred"          # centreline/surface documented; widening + slab pattern inferred/artistic
    ob["artistic"] = False
    ob["evidence_ref"] = ("osm:way/%d surface=%s width %.2f m (%s); paving extended to the building line where "
                          "buildings stand within 3 m of the mapped edge (inferred); slab pattern artistic") % (
        s["osm_id"], s["surface"], w, s["width_src"])
    return ob


def build(coll, mat, mat_sett=None):
    idx = street_index()
    out = []
    k = 0
    for key, d in P2_STREETS.items():
        for wid in d["ways"]:
            s = idx[wid]
            if s["highway"] == "steps" or s["surface"] not in ("paving_stones", "sett", "stone", "cobblestone"):
                continue
            out.append(ribbon(s, coll, mat_sett if (s["surface"] == "sett" and mat_sett) else mat, 0.035 + 0.004 * (k % 4)))
            k += 1
    return out


def carve_terrain_under_steps(log=print):
    """The OSM stairs are built as straight flights between their surveyed end heights; the smooth DEM bulges
    above the middle of convex flights (Sannenzaka 46-step stair: terrain 79.4 m vs flight 78.8 m) and buried
    the treads.  Lower terrain vertices under each flight (+0.6 m margin) to 0.15 m below the flight line."""
    import bpy
    from shapely.geometry import LineString, Point
    S = __import__("kit_common").data("steps")["steps"]
    ter = bpy.data.objects.get("Terrain_GSI_DEM5A")
    if ter is None:
        return 0
    me = ter.data
    V = np.empty(len(me.vertices) * 3); me.vertices.foreach_get("co", V); V = V.reshape(-1, 3)
    n = 0
    for st in S:
        c = np.array(st["coords"], float)
        ls = LineString(c)
        if ls.length < 0.3:
            continue
        poly = ls.buffer(st["width_m"] / 2 + 0.6, cap_style=2)
        x0, y0, x1, y1 = poly.bounds
        sel = np.where((V[:, 0] >= x0) & (V[:, 0] <= x1) & (V[:, 1] >= y0) & (V[:, 1] <= y1))[0]
        zb, zt = st["z_bottom"], st["z_top"]
        for i in sel:
            p = Point(V[i, 0], V[i, 1])
            if not poly.contains(p):
                continue
            t = ls.project(p) / ls.length
            zl = zb + (zt - zb) * (t if st["ascending_along_way"] else 1 - t)
            if V[i, 2] > zl - 0.15:
                V[i, 2] = zl - 0.15; n += 1
    me.vertices.foreach_set("co", V.ravel())
    me.update()
    ter["carved_under_steps"] = "%d vertices lowered under OSM stairs (art_pass kit_ground.carve_terrain_under_steps)" % n
    log("terrain vertices carved under stairs", n)
    return n


def utility_poles(coll, log=print):
    """Concrete utility poles + overhead wires along Yasaka-dori west (OSM 24516359).
    Type observed (building_evidence.json yasaka_dori_west street_character: 'overhead utility poles');
    positions inferred: every ~28 m along the north street edge, skipping points inside building footprints."""
    import bpy
    import bmesh
    from shapely.geometry import LineString, Point, Polygon
    from kit_common import data, street_index
    from kit_materials import M
    s = street_index()[24516359]
    ls = LineString(s["coords"])
    w = float(s["width_m"] or 4.3)
    polys = [Polygon(b["footprint"]).buffer(0.15) for b in data("buildings")["buildings"] if abs(b["centroid"][0]) < 250]
    tops = []
    d = 6.0
    k = 0
    while d < ls.length - 3:
        p = np.array(ls.interpolate(d).coords[0]); q = np.array(ls.interpolate(d + 0.5).coords[0])
        t = (q - p) / max(np.linalg.norm(q - p), 1e-6)
        nrm = np.array([-t[1], t[0]])
        side = 1 if nrm[1] > 0 else -1          # north side
        pos = p + nrm * side * (w / 2 - 0.3)
        # keep the hero sightline (shot a, documented Commons viewpoint area) to the pagoda clear
        sight = LineString([(-79.0, 88.2), (9.4, 83.3)]).buffer(2.5)
        if any(pp.contains(Point(*pos)) for pp in polys) or sight.contains(Point(*pos)):
            d += 3.0
            continue
        z = gz(pos[0], pos[1])
        bm = bmesh.new()
        r = bmesh.ops.create_cone(bm, cap_ends=True, segments=10, radius1=0.17, radius2=0.10, depth=10.5)
        for v in r["verts"]:
            v.co.z += 10.5 / 2 - 0.5
        r2 = bmesh.ops.create_cube(bm, size=1.0)
        for v in r2["verts"]:
            v.co.x *= 0.09; v.co.y *= 1.6; v.co.z *= 0.09; v.co.z += 9.3
        if k % 3 == 1:   # pole transformer
            r3 = bmesh.ops.create_cone(bm, cap_ends=True, segments=10, radius1=0.25, radius2=0.25, depth=0.9)
            for v in r3["verts"]:
                v.co.x += 0.32; v.co.z += 7.4
        me = bpy.data.meshes.new("UtilityPole_%d" % k); bm.to_mesh(me); bm.free()
        me.materials.append(M("concrete"))
        ob = bpy.data.objects.new("UtilityPole_%d" % k, me)
        ob.location = (pos[0], pos[1], z)
        ob.rotation_euler = (0, 0, float(np.arctan2(t[1], t[0])))
        ob["detail_class"] = "inferred"; ob["artistic"] = False; ob["collide"] = True
        ob["evidence_ref"] = "type observed: building_evidence.json#yasaka_dori_west/street_character (overhead utility poles); positions inferred"
        coll.objects.link(ob)
        arm = np.array([-t[1], t[0]])
        tops.append([np.array([pos[0], pos[1], z + 9.3]) + np.r_[arm * o, 0] for o in (-1.4, -0.5, 0.5, 1.4)])
        k += 1
        d += 28.0
    # wires with sag
    bm = bmesh.new()
    for a, b in zip(tops[:-1], tops[1:]):
        for pa, pb_ in zip(a, b):
            n = 12
            pts = [pa + (pb_ - pa) * (i / n) - np.array([0, 0, 0.55 * 4 * (i / n) * (1 - i / n)]) for i in range(n + 1)]
            for p0, p1 in zip(pts[:-1], pts[1:]):
                dv = p1 - p0
                side = np.cross(dv, [0, 0, 1]); side = side / max(np.linalg.norm(side), 1e-9) * 0.009
                vs = [bm.verts.new(v) for v in (p0 - side, p1 - side, p1 + side, p0 + side)]
                bm.faces.new(vs)
                vs = [bm.verts.new(v) for v in (p0 + [0, 0, -0.009], p1 + [0, 0, -0.009], p1 + [0, 0, 0.009], p0 + [0, 0, 0.009])]
                bm.faces.new(vs)
    me = bpy.data.meshes.new("UtilityWires"); bm.to_mesh(me); bm.free()
    me.materials.append(M("metal"))
    ob = bpy.data.objects.new("UtilityWires_osm24516359", me); coll.objects.link(ob)
    ob["detail_class"] = "inferred"; ob["artistic"] = False; ob["collide"] = False
    ob["evidence_ref"] = "overhead wires observed on Yasaka-dori west (building_evidence.json); spans inferred"
    log("utility poles", k)
    return k
