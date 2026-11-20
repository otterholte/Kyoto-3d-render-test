"""B: dump scene geometry needed by the audit from a .blend (run with the venv python; bpy imported first).
usage: python b_dump_scene.py <file.blend> <out.pkl>
Per building (objects with plateau_id): collections, matrix, roof outline (union of projected roof faces),
wall cross-section segments at base_z + 1.5 m and + 4.5 m, z-range, custom props.
Also: instance empties (kit / vegetation), steps, barriers, lanterns, hero pagoda bbox, cameras."""
import sys
import bpy  # noqa: F401  (bpy before bmesh)
import pickle
import numpy as np
from shapely.geometry import Polygon, LineString
from shapely.ops import unary_union

src, dst = sys.argv[-2], sys.argv[-1]
bpy.ops.wm.open_mainfile(filepath=src)


def colls(ob):
    return [c.name for c in ob.users_collection]


def mesh_arrays(ob):
    me = ob.data
    V = np.empty(len(me.vertices) * 3); me.vertices.foreach_get("co", V); V = V.reshape(-1, 3)
    M = np.array(ob.matrix_world)
    V = V @ M[:3, :3].T + M[:3, 3]
    mi = np.empty(len(me.polygons), np.int32); me.polygons.foreach_get("material_index", mi)
    polys = [list(p.vertices) for p in me.polygons]
    return V, mi, polys


def cut(V, polys, mi, z, mats=(1, 2)):
    segs = []
    for p, m in zip(polys, mi):
        if m not in mats:
            continue
        P = V[p]
        d = P[:, 2] - z
        pts = []
        for i in range(len(p)):
            a, b = P[i], P[(i + 1) % len(p)]
            da, db = d[i], d[(i + 1) % len(p)]
            if (da < 0) != (db < 0):
                t = da / (da - db)
                pts.append(a[:2] + (b[:2] - a[:2]) * t)
        if len(pts) >= 2:
            segs.append(np.array(pts[:2]))
    return segs


def outline(segs):
    if not segs:
        return None
    u = unary_union([LineString(s) for s in segs if np.linalg.norm(s[1] - s[0]) > 1e-4]).buffer(0.05)
    holes = []
    for g in getattr(u, "geoms", [u]):
        for h in g.interiors:
            holes.append(Polygon(h))
    if not holes:
        return None
    return max(holes, key=lambda h: h.area).buffer(0.05)


out = dict(buildings={}, empties=[], steps={}, barriers={}, lanterns=[], hero=None, cams={}, other_meshes=[])
for ob in bpy.data.objects:
    if ob.type == "MESH" and "plateau_id" in ob:
        V, mi, polys = mesh_arrays(ob)
        roof = []
        for p, m in zip(polys, mi):
            if m == 0 and len(p) >= 3:
                pg = Polygon(V[p][:, :2])
                if pg.is_valid and pg.area > 1e-4:
                    roof.append(pg)
                elif pg.area > 1e-4:
                    roof.append(pg.buffer(0))
        ro = unary_union(roof) if roof else None
        bz = float(ob.get("base_z", V[:, 2].min()))
        s15 = cut(V, polys, mi, bz + 1.5)
        s45 = cut(V, polys, mi, bz + 4.5)
        props = {k: (ob[k] if isinstance(ob[k], (int, float, str)) else str(ob[k])) for k in ob.keys()}
        out["buildings"].setdefault(ob["plateau_id"], []).append(dict(
            name=ob.name, colls=colls(ob), matrix=np.array(ob.matrix_world), roof=ro, segs15=s15, segs45=s45,
            wall15=outline(s15), zmin=float(V[:, 2].min()), zmax=float(V[:, 2].max()), props=props,
            hide_render=ob.hide_render, nverts=len(V)))
    elif ob.type == "EMPTY":
        d = dict(name=ob.name, colls=colls(ob), loc=tuple(ob.matrix_world.translation),
                 rotz=float(ob.matrix_world.to_euler()[2]), scale=tuple(ob.matrix_world.to_scale()),
                 inst=ob.instance_collection.name if ob.instance_collection else None,
                 props={k: (ob[k] if isinstance(ob[k], (int, float, str)) else str(ob[k])) for k in ob.keys()})
        out["empties"].append(d)
    elif ob.type == "MESH" and ob.name.startswith("Steps_osm"):
        V, mi, polys = mesh_arrays(ob)
        out["steps"][ob.name] = dict(V=V, polys=polys, props={k: (ob[k] if isinstance(ob[k], (int, float, str)) else str(ob[k])) for k in ob.keys()})
    elif ob.type == "MESH" and ob.name.startswith("Barrier_"):
        V, mi, polys = mesh_arrays(ob)
        out["barriers"][ob.name] = dict(V=V[::1], props={k: (ob[k] if isinstance(ob[k], (int, float, str)) else str(ob[k])) for k in ob.keys()})
    elif ob.type == "CAMERA":
        out["cams"][ob.name] = dict(loc=tuple(ob.location), rot=tuple(ob.rotation_euler), lens=ob.data.lens)
    elif ob.type == "MESH":
        props = {k: (ob[k] if isinstance(ob[k], (int, float, str)) else str(ob[k])) for k in ob.keys()}
        bb = np.array([ob.matrix_world @ __import__("mathutils").Vector(c) for c in ob.bound_box])
        out["other_meshes"].append(dict(name=ob.name, colls=colls(ob), bbmin=bb.min(0), bbmax=bb.max(0), props=props,
                                        hide_render=ob.hide_render, loc=tuple(ob.matrix_world.translation)))
hc = bpy.data.collections.get("Yasaka_Pagoda_HERO")
if hc:
    allv = []
    for ob in hc.all_objects:
        if ob.type == "MESH":
            V, mi, polys = mesh_arrays(ob)
            allv.append(V)
    root = [o for o in hc.all_objects if o.type == "EMPTY"]
    allv = np.concatenate(allv)
    zb = allv[:, 2].min()
    # horizontal slices for footprint / eave analysis
    sl = {}
    for dz in np.arange(0.0, 40.0, 0.5):
        m = (allv[:, 2] >= zb + dz) & (allv[:, 2] < zb + dz + 0.5)
        if m.sum() > 3:
            sl[round(float(dz), 1)] = allv[m][:, :2]
    out["hero"] = dict(bbmin=allv.min(0), bbmax=allv.max(0),
                       root=[dict(name=o.name, loc=tuple(o.matrix_world.translation), rot=tuple(o.matrix_world.to_euler()),
                                  props={k: str(o[k])[:400] for k in o.keys()}) for o in root],
                       slices=sl, objs=[(o.name, o.type, o.hide_render) for o in hc.all_objects])
pickle.dump(out, open(dst, "wb"))
print("buildings", len(out["buildings"]), "empties", len(out["empties"]), "steps", len(out["steps"]))
