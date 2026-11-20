"""Shared helpers for the art pass (blender/art_pass.py and kit_*.py).

Frame: 1 Blender unit = 1 m, +X east, +Y north, +Z = T.P. height (same as build_world.py).
"""
import json
import math
import os
import sys

import bpy  # noqa: F401  (bpy before bmesh)
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PROC = os.path.join(ROOT, "data", "processed")
DOCS = os.path.join(ROOT, "docs")
sys.path.insert(0, os.path.join(ROOT, "pipeline"))
from terrain_sample import ground  # noqa: E402

_cache = {}


def data(name):
    if name not in _cache:
        with open(os.path.join(PROC, name + ".json")) as f:
            _cache[name] = json.load(f)
    return _cache[name]


def gz(x, y):
    """Terrain height; scalar in -> float, arrays in -> ndarray."""
    r = ground(x, y)
    return float(r) if np.ndim(r) == 0 else np.asarray(r)


# Priority-2 streets (OSM way ids; names as mapped). Yasaka-dori includes its pedestrian continuation
# 710696944 (pagoda -> Sannenzaka junction).
P2_STREETS = {
    "Yasaka-dori": dict(ja="八坂通", ways=[24516359, 710696944]),
    "Ninenzaka": dict(ja="二寧坂", ways=[30913263, 30882783, 550360170, 1491152444, 1569088149]),
    "Sannenzaka": dict(ja="産寧坂", ways=[526198271, 1569088146, 1569088147, 179116810, 1251544286]),
    "Ichinenzaka": dict(ja="一念坂", ways=[157527438]),
}


def street_index():
    """{osm_id: street record} for all mapped streets."""
    if "_sidx" not in _cache:
        _cache["_sidx"] = {s["osm_id"]: s for s in data("streets")["streets"]}
    return _cache["_sidx"]


def p2_lines():
    """[(street_key, osm_id, shapely LineString, width_m, highway)]"""
    from shapely.geometry import LineString
    if "_p2" not in _cache:
        idx = street_index()
        out = []
        for key, d in P2_STREETS.items():
            for w in d["ways"]:
                s = idx[w]
                out.append((key, w, LineString(s["coords"]), float(s["width_m"] or 4.0), s["highway"]))
        _cache["_p2"] = out
    return _cache["_p2"]


def get_coll(name, parent=None):
    c = bpy.data.collections.get(name)
    if c is None:
        c = bpy.data.collections.new(name)
        (parent or bpy.context.scene.collection).children.link(c)
    return c


def exclude_coll(name, exclude=True):
    def walk(lc):
        if lc.collection.name == name:
            lc.exclude = exclude
            return True
        return any(walk(ch) for ch in lc.children)
    walk(bpy.context.view_layer.layer_collection)


def mesh_obj(name, verts, faces, coll=None, mats=(), face_mat=None, smooth=False):
    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(map(float, v)) for v in verts], [], [tuple(int(i) for i in f) for f in faces])
    me.validate(clean_customdata=False)
    for m in mats:
        me.materials.append(m)
    if face_mat is not None and len(me.polygons):
        me.polygons.foreach_set("material_index", np.asarray(face_mat, np.int32)[:len(me.polygons)])
    if smooth:
        me.shade_smooth()
    ob = bpy.data.objects.new(name, me)
    if coll is not None:
        coll.objects.link(ob)
    return ob


def rng_for(*keys):
    h = 2166136261
    for k in keys:
        for ch in str(k):
            h = ((h ^ ord(ch)) * 16777619) & 0xFFFFFFFF
    return np.random.default_rng(h)


def look_at_euler(loc, target):
    d = np.array(target, float) - np.array(loc, float)
    return (math.atan2(math.hypot(d[0], d[1]), -d[2]), 0.0, math.atan2(d[1], d[0]) - math.pi / 2)


# ---------------------------------------------------------------- evidence lookup
def evidence():
    """Load docs/evidence/building_evidence.json if the research agent has produced it (else {})."""
    if "_ev" not in _cache:
        p = os.path.join(DOCS, "evidence", "building_evidence.json")
        try:
            with open(p) as f:
                _cache["_ev"] = json.load(f)
        except Exception:
            _cache["_ev"] = {}
    return _cache["_ev"]
