"""Phase 6 vegetation.

Documented (50_Vegetation_Documented): every OSM natural=tree / tree_row sample keeps its exact position and its
height tag (default 7 m, flagged); species from tags (genus/species/species:ja) where present, otherwise an
inferred species mix (flagged species_src = "inferred").  Painterly clustered-leaf tree prototypes live in
A_Asset_Library (T_*) and are collection-instanced.

Artistic (55_Vegetation_Artistic, artistic=True): forest fill inside OSM landuse=forest / natural=scrub /
leisure=garden areas (area documented, trees inferred), bamboo clumps, shrubs along walls, weeds at facade
bases and in paving gutters, fallen maple leaves.

Season: late autumn (mid/late November, koyo peak in Higashiyama): maples crimson-orange, cherries bronze and
thinning, ginkgo yellow, pines and evergreens dark.
"""
import math

import bpy
import bmesh
import numpy as np
from mathutils import Matrix, Vector

from kit_common import data, get_coll, gz, rng_for, street_index, P2_STREETS
from kit_materials import M

LIB = "A_Asset_Library"


# ------------------------------------------------------------------ geometry helpers
# leaf material key -> foliage-atlas cards (blender/textures/foliage_atlas.json); late-autumn mixes
CARD_MAP = {
    "leaf_maple": [("maple_autumn", 1.0)],
    "leaf_cherry": [("cherry_leaf", 0.45), ("maple_autumn", 0.55)],
    "leaf_pine": [("pine_needles", 1.0)],
    "leaf_broad": [("cherry_leaf", 0.6), ("shrub_azalea", 0.4)],
    "leaf_bamboo": [("bamboo_leaves", 1.0)],
    "leaf_shrub": [("shrub_azalea", 0.5), ("shrub_box", 0.5)],
}
_FOL = {}


def _foliage():
    if "cards" not in _FOL:
        try:
            import json as _j
            import os as _o
            import materials_textured as MT
            _FOL["cards"] = _j.load(open(_o.path.join(MT.TEX, "foliage_atlas.json")))["cards"]
        except Exception:
            _FOL["cards"] = None
    return _FOL["cards"]


class TB:
    def __init__(self, name):
        self.name = name
        self.bm = bmesh.new()
        self.uv = self.bm.loops.layers.uv.new("UVMap")
        self.mats = []

    def mi(self, k):
        if k not in self.mats:
            self.mats.append(k)
        return self.mats.index(k)

    def tube(self, pts, radii, key, n=6):
        pts = [Vector(p) for p in pts]
        rings = []
        for i, p in enumerate(pts):
            t = (pts[min(i + 1, len(pts) - 1)] - pts[max(i - 1, 0)]).normalized()
            a = t.orthogonal().normalized()
            b = t.cross(a).normalized()
            rings.append([self.bm.verts.new(p + (a * math.cos(2 * math.pi * k / n) + b * math.sin(2 * math.pi * k / n)) * radii[i])
                          for k in range(n)])
        m = self.mi(key)
        for r0, r1 in zip(rings[:-1], rings[1:]):
            for k in range(n):
                f = self.bm.faces.new([r0[k], r0[(k + 1) % n], r1[(k + 1) % n], r1[k]]); f.material_index = m

    def leaves(self, center, radii, count, size, key, rng, shape="leaf", up_bias=0.3, shell=0.75):
        cards = _foliage()
        if cards and key in CARD_MAP:
            return self.cards(center, radii, max(4, count // 6), CARD_MAP[key], rng, cards, shell)
        m = self.mi(key)
        c = Vector(center)
        for _ in range(count):
            d = Vector(rng.normal(size=3)).normalized()
            r = rng.uniform(shell, 1.0) ** 0.5
            p = c + Vector((d.x * radii[0], d.y * radii[1], d.z * radii[2])) * r
            nrm = (Vector(rng.normal(size=3)) * 0.6 + d * 0.6 + Vector((0, 0, up_bias))).normalized()
            a = nrm.orthogonal().normalized(); b = nrm.cross(a)
            s = size * rng.uniform(0.7, 1.3)
            if shape == "needle":
                L = s * 2.2
                vs = [p - a * 0.012, p + a * 0.012, p + a * 0.012 + b * L, p - a * 0.012 + b * L]
            elif shape == "blade":
                vs = [p - a * s * 0.06, p + a * s * 0.06, p + b * s * 1.5 + a * s * 0.02, p + b * s * 1.5 - a * s * 0.02]
            else:
                vs = [p - a * s * 0.5, p - b * s * 0.15, p + a * s * 0.5, p + b * s * 0.9]
            f = self.bm.faces.new([self.bm.verts.new(v) for v in vs]); f.material_index = m

    def cards(self, center, radii, n, names_w, rng, cards, shell=0.6):
        """Alpha leaf cards from the texture library's foliage atlas (oriented outward, pivot at the twig base)."""
        m = self.mi("foliage")
        names = [c for c, _ in names_w]; w = np.array([x for _, x in names_w], float); w /= w.sum()
        c0 = Vector(center)
        for _ in range(n):
            d = Vector(rng.normal(size=3)).normalized()
            r = rng.uniform(shell, 1.0) ** 0.5
            p = c0 + Vector((d.x * radii[0], d.y * radii[1], d.z * radii[2])) * r * 0.85
            cn = names[rng.choice(len(names), p=w)]
            rect = cards[cn]["uv_rect"]; sz = cards[cn]["size_m"][0] * rng.uniform(0.85, 1.35)
            out = Vector((d.x, d.y, 0.0))
            out = out.normalized() if out.length > 1e-3 else Vector((1, 0, 0))
            b_ = rng.uniform(-0.5, 0.9)
            up = Vector((0, 0, 1)) * np.cos(b_) + out * np.sin(b_)
            side = up.cross(out).normalized()
            up = out.cross(side).normalized()
            if up.z < 0:
                up = -up
            base = p - up * sz * 0.35
            q = [base - side * sz / 2, base + side * sz / 2, base + side * sz / 2 + up * sz, base - side * sz / 2 + up * sz]
            f = self.bm.faces.new([self.bm.verts.new(v) for v in q]); f.material_index = m
            for lp, uv in zip(f.loops, ((rect[0], rect[1]), (rect[2], rect[1]), (rect[2], rect[3]), (rect[0], rect[3]))):
                lp[self.uv].uv = uv

    def finish(self, coll):
        me = bpy.data.meshes.new(self.name)
        self.bm.to_mesh(me); self.bm.free()
        for k in self.mats:
            me.materials.append(M(k))
        ob = bpy.data.objects.new(self.name, me)
        coll.objects.link(ob)
        return ob


def _branch(rng, start, direction, length, segs, wander):
    pts = [Vector(start)]
    d = Vector(direction).normalized()
    for i in range(segs):
        d = (d + Vector(rng.normal(size=3)) * wander).normalized()
        pts.append(pts[-1] + d * (length / segs))
    return pts


# ------------------------------------------------------------------ prototypes (height ~ nominal H)
def proto_maple(name, seed):
    rng = np.random.default_rng(seed)
    tb = TB(name)
    H = 6.0
    trunk_h = rng.uniform(1.4, 2.0)
    tr = _branch(rng, (0, 0, -0.3), (rng.normal() * 0.15, rng.normal() * 0.15, 1), trunk_h + 0.3, 4, 0.12)
    tb.tube(tr, np.linspace(0.2, 0.15, len(tr)), "bark")
    tops = []
    nb = rng.integers(4, 7)
    for k in range(nb):
        az = 2 * math.pi * k / nb + rng.uniform(-0.4, 0.4)
        d = (math.cos(az) * 0.8, math.sin(az) * 0.8, rng.uniform(0.6, 1.1))
        br = _branch(rng, tr[-1], d, rng.uniform(2.3, 3.3), 5, 0.25)
        tb.tube(br, np.linspace(0.12, 0.03, len(br)), "bark", n=5)
        tops += br[2:]
    # layered, horizontally spread crown of clusters (Acer palmatum habit)
    for p in tops[::1]:
        for _ in range(2):
            c = p + Vector((rng.normal() * 0.5, rng.normal() * 0.5, rng.uniform(-0.1, 0.5)))
            r = rng.uniform(0.7, 1.15)
            tb.leaves(c, (r * 1.25, r * 1.25, r * 0.55), int(170 * r), 0.16, "leaf_maple", rng)
    return tb, H


def proto_cherry(name, seed):
    rng = np.random.default_rng(seed)
    tb = TB(name)
    H = 7.0
    tr = _branch(rng, (0, 0, -0.3), (0.1, 0, 1), 2.4, 4, 0.1)
    tb.tube(tr, np.linspace(0.28, 0.2, len(tr)), "bark_cherry", n=7)
    nb = rng.integers(4, 6)
    for k in range(nb):
        az = 2 * math.pi * k / nb + rng.uniform(-0.3, 0.3)
        d = (math.cos(az), math.sin(az), rng.uniform(0.35, 0.7))
        br = _branch(rng, tr[-1], d, rng.uniform(3.2, 4.4), 6, 0.18)
        tb.tube(br, np.linspace(0.16, 0.035, len(br)), "bark_cherry", n=5)
        for p in br[2:]:
            for _ in range(2):
                sb = _branch(rng, p, (rng.normal(), rng.normal(), 0.5), rng.uniform(0.8, 1.4), 3, 0.3)
                tb.tube(sb, np.linspace(0.03, 0.01, len(sb)), "bark_cherry", n=4)
                # thinning autumn foliage: sparse clusters
                if rng.random() < 0.7:
                    tb.leaves(sb[-1], (0.8, 0.8, 0.5), 70, 0.17, "leaf_cherry", rng)
    return tb, H


def proto_pine(name, seed):
    rng = np.random.default_rng(seed)
    tb = TB(name)
    H = 6.5
    lean = Vector((rng.normal() * 0.35, rng.normal() * 0.35, 1))
    tr = _branch(rng, (0, 0, -0.3), lean, 6.0, 7, 0.15)
    tb.tube(tr, np.linspace(0.24, 0.07, len(tr)), "bark", n=6)
    # niwaki cloud pads on horizontal branches
    for i in range(2, len(tr)):
        if rng.random() < 0.85:
            az = rng.uniform(0, 2 * math.pi)
            L = rng.uniform(1.0, 2.2) * (1.2 - i / len(tr))
            br = _branch(rng, tr[i], (math.cos(az), math.sin(az), rng.uniform(-0.05, 0.25)), L, 3, 0.1)
            tb.tube(br, np.linspace(0.07, 0.03, len(br)), "bark", n=4)
            r = rng.uniform(0.7, 1.1)
            tb.leaves(br[-1] + Vector((0, 0, 0.15)), (r * 1.2, r * 1.2, r * 0.35), int(260 * r), 0.11, "leaf_pine", rng,
                      shape="needle", up_bias=1.2, shell=0.5)
    tb.leaves(tr[-1], (0.9, 0.9, 0.4), 220, 0.11, "leaf_pine", rng, shape="needle", up_bias=1.2, shell=0.5)
    return tb, H


def proto_broad(name, seed, key="leaf_broad"):
    rng = np.random.default_rng(seed)
    tb = TB(name)
    H = 8.0
    tr = _branch(rng, (0, 0, -0.3), (0, 0, 1), 3.0, 4, 0.08)
    tb.tube(tr, np.linspace(0.3, 0.2, len(tr)), "bark", n=7)
    for k in range(5):
        az = 2 * math.pi * k / 5 + rng.uniform(-0.3, 0.3)
        br = _branch(rng, tr[-1], (math.cos(az) * 0.6, math.sin(az) * 0.6, 1), rng.uniform(2.0, 3.2), 4, 0.15)
        tb.tube(br, np.linspace(0.14, 0.04, len(br)), "bark", n=5)
    for _ in range(26):
        d = Vector(rng.normal(size=3)); d.z = abs(d.z) * 0.8; d.normalize()
        c = Vector((0, 0, 5.2)) + Vector((d.x * 2.4, d.y * 2.4, d.z * 2.2))
        r = rng.uniform(0.9, 1.4)
        tb.leaves(c, (r, r, r * 0.8), int(150 * r), 0.2, key, rng)
    return tb, H


def proto_bamboo(name, seed):
    rng = np.random.default_rng(seed)
    tb = TB(name)
    H = 9.0
    for k in range(int(rng.integers(14, 22))):
        x, y = rng.normal(size=2) * 0.9
        h = rng.uniform(6.5, 10.0)
        lean = Vector((x * 0.04 + rng.normal() * 0.04, y * 0.04 + rng.normal() * 0.04, 1)).normalized()
        pts = [Vector((x, y, -0.2)) + lean * (h * t / 5) + Vector((0, 0, 0)) for t in range(6)]
        pts[-1] += Vector((rng.normal() * 0.3, rng.normal() * 0.3, -0.3))
        tb.tube(pts, np.linspace(0.05, 0.02, len(pts)), "bamboo_green", n=5)
        for t in (0.55, 0.7, 0.85, 1.0):
            p = pts[0].lerp(pts[-1], t)
            tb.leaves(p, (0.8, 0.8, 0.5), 45, 0.18, "leaf_bamboo", rng, shape="blade", up_bias=-0.3)
    return tb, H


def proto_shrub(name, seed, key="leaf_shrub"):
    rng = np.random.default_rng(seed)
    tb = TB(name)
    for _ in range(3):
        c = Vector((rng.normal() * 0.35, rng.normal() * 0.35, rng.uniform(0.35, 0.55)))
        r = rng.uniform(0.45, 0.65)
        tb.leaves(c, (r, r, r * 0.75), int(260 * r), 0.09, key, rng, shell=0.6)
    return tb, 1.0


def proto_weeds(name, seed):
    rng = np.random.default_rng(seed)
    tb = TB(name)
    for _ in range(4):
        c = Vector((rng.normal() * 0.08, rng.normal() * 0.08, 0.06))
        tb.leaves(c, (0.08, 0.08, 0.03), 18, 0.12, "grass", rng, shape="blade", up_bias=2.5, shell=0.0)
    return tb, 0.2


PROTOS = {
    "T_Maple_1": (proto_maple, 11), "T_Maple_2": (proto_maple, 12), "T_Maple_3": (proto_maple, 13),
    "T_Cherry_1": (proto_cherry, 21), "T_Cherry_2": (proto_cherry, 22),
    "T_Pine_1": (proto_pine, 31), "T_Pine_2": (proto_pine, 32),
    "T_Broad_1": (proto_broad, 41), "T_Broad_2": (proto_broad, 42),
    "T_Ginkgo_1": (lambda n, s: proto_broad(n, s, "leaf_ginkgo"), 51),
    "T_Bamboo_1": (proto_bamboo, 61), "T_Bamboo_2": (proto_bamboo, 62),
    "T_Shrub_1": (proto_shrub, 71), "T_Shrub_2": (lambda n, s: proto_shrub(n, s, "leaf_maple"), 72),
    "T_Weeds_1": (proto_weeds, 81),
}
NOMINAL = {}


def build_protos():
    lib = get_coll(LIB)
    out = {}
    for name, (fn, seed) in PROTOS.items():
        c = bpy.data.collections.get(name)
        if c is None:
            c = bpy.data.collections.new(name)
            lib.children.link(c)
            tb, H = fn(name, seed)
            tb.finish(c)
            NOMINAL[name] = H
        else:
            NOMINAL[name] = {"Maple": 6.0, "Cherry": 7.0, "Pine": 6.5, "Broad": 8.0, "Ginkgo": 8.0, "Bamboo": 9.0}.get(name.split("_")[1], 1.0)
        out[name] = c
    return out


def _inst(lib, proto, coll, name, loc, rotz, s, props):
    e = bpy.data.objects.new(name, None)
    e.instance_type = "COLLECTION"; e.instance_collection = lib[proto]
    e.location = loc; e.rotation_euler = (0, 0, rotz); e.scale = (s, s, s)
    coll.objects.link(e)
    for k, v in props.items():
        e[k] = v
    e["proto"] = proto
    return e


# ------------------------------------------------------------------ documented trees
def species_of(tags, key):
    g = (tags.get("genus") or "") + " " + (tags.get("species") or "") + " " + (tags.get("species:ja") or "") + " " + (tags.get("taxon") or "")
    g = g.lower()
    if any(k in g for k in ("acer", "もみじ", "モミジ".lower(), "かえで", "カエデ".lower())):
        return "maple", "osm:species"
    if any(k in g for k in ("cerasus", "prunus", "サクラ".lower(), "ザクラ".lower(), "さくら", "桜")):
        return "cherry", "osm:species"
    if any(k in g for k in ("pinus", "マツ".lower(), "松")):
        return "pine", "osm:species"
    if "ginkgo" in g or "イチョウ" in g:
        return "ginkgo", "osm:species"
    rng = rng_for("species", key)
    r = rng.random()
    lt = tags.get("leaf_type")
    if lt == "needleleaved":
        return "pine", "osm:leaf_type (species inferred)"
    sp = "maple" if r < 0.34 else "broad" if r < 0.68 else "cherry" if r < 0.82 else "pine" if r < 0.94 else "ginkgo"
    if lt == "broadleaved" and sp == "pine":
        sp = "broad"
    return sp, "inferred (untagged OSM tree; late-autumn Higashiyama species mix)"


PROTO_OF = {"maple": ["T_Maple_1", "T_Maple_2", "T_Maple_3"], "cherry": ["T_Cherry_1", "T_Cherry_2"],
            "pine": ["T_Pine_1", "T_Pine_2"], "broad": ["T_Broad_1", "T_Broad_2"], "ginkgo": ["T_Ginkgo_1"]}


PAGODA_XY = (9.4, 83.3)


def pagoda_corridors():
    """Sight corridors (5 m buffer) from every geotagged Commons photo of the pagoda and from the hero cameras to the
    pagoda: artistic trees are kept out of them; documented default-height crowns inside are drawn smaller
    (accuracy audit F9)."""
    import json as _json
    import os as _os
    from shapely.geometry import LineString
    from shapely.ops import unary_union
    from kit_common import DOCS
    pts = []
    try:
        for c in _json.load(open(_os.path.join(DOCS, "references", "commons_geotagged.json"))):
            xy = c.get("local_xy_m")
            txt = (c.get("title", "") + " " + " ".join(c.get("categories") or [])).lower()
            if xy and max(abs(xy[0]), abs(xy[1])) < 320 and any(k in txt for k in ("yasaka no t", "pagoda", "hokan", "gojunoto", "八坂の塔", "法観寺", "yasakanoto", "yasaka tower")):
                pts.append(tuple(xy))
    except Exception:
        pass
    pts += [(-79.0, 88.2), (118.0, 30.0), (91.8, 44.7), (80.9, 39.8), (55.9, 48.4)]
    lines = [LineString([p, PAGODA_XY]).buffer(5.0) for p in set(pts) if (p[0] - PAGODA_XY[0]) ** 2 + (p[1] - PAGODA_XY[1]) ** 2 > 400]
    return unary_union(lines) if lines else None


def documented_trees(lib, log):
    coll = get_coll("50_Vegetation_Documented")
    for o in list(coll.objects):
        if o.name.startswith(("Tree_osm", "TreeCrown_osm")):
            bpy.data.objects.remove(o, do_unlink=True)
    pts = []
    for t in data("features")["trees"]:
        if t["kind"] == "tree":
            pts.append((t["x"], t["y"], t.get("osm_id"), t["tags"], "natural=tree"))
        else:
            c = np.array(t["coords"]); ln = np.r_[0, np.cumsum(np.linalg.norm(np.diff(c, axis=0), axis=1))]
            for d in np.arange(0, ln[-1], 5.0):
                i = min(len(c) - 2, int(np.searchsorted(ln, d, side="right") - 1))
                p = c[i] + (c[i + 1] - c[i]) * (d - ln[i]) / max(ln[i + 1] - ln[i], 1e-6)
                pts.append((p[0], p[1], t["osm_id"], t["tags"], "natural=tree_row sampled every 5 m"))
    stats = {}
    from shapely.geometry import Point as _Pt
    corr = pagoda_corridors()
    for k, (x, y, oid, tags, kind) in enumerate(pts):
        sp, src = species_of(tags, "%s_%d" % (oid, k))
        rng = rng_for("tree", oid, k)
        protos = PROTO_OF[sp]
        proto = protos[int(rng.integers(0, len(protos)))]
        try:
            h = float(tags.get("height", "").replace("m", "")) if tags.get("height") else 7.0
            hsrc = "osm:height" if tags.get("height") else "default 7 m (inferred)"
        except ValueError:
            h, hsrc = 7.0, "default 7 m (inferred)"
        s = float(np.clip(h / NOMINAL[proto] * rng.uniform(0.9, 1.1), 0.55, 1.8))
        props = dict(osm_id=str(oid or ""), documented=True, artistic=False, species=sp, species_src=src,
                     species_tag=tags.get("species") or tags.get("species:ja") or tags.get("genus") or "",
                     height_m=h, height_src=hsrc, osm_kind=kind, collide=True,
                     detail_class="observed" if src == "osm:species" else "inferred")
        if corr is not None and corr.contains(_Pt(x, y)) and not tags.get("height"):
            s *= 0.8
            props["crown_note"] = "default-height crown drawn 20 % smaller inside a documented pagoda sightline (audit F9)"
        _inst(lib, proto, coll, "Tree_osm%s_%d" % (oid, k), (x, y, gz(x, y)), rng.uniform(0, 2 * math.pi), s, props)
        stats[sp] = stats.get(sp, 0) + 1
    log("documented trees", len(pts), stats)
    return len(pts)


# ------------------------------------------------------------------ artistic vegetation
def _inside(poly, x, y):
    from shapely.geometry import Point
    return poly.contains(Point(x, y))


def artistic(lib, log):
    from shapely.geometry import Polygon, Point, LineString
    from shapely.strtree import STRtree
    coll = get_coll("55_Vegetation_Artistic")
    B = data("buildings")["buildings"]
    bpolys = [Polygon(b["footprint"]).buffer(0.8) for b in B]
    btree = STRtree(bpolys)
    streets = [LineString(s["coords"]).buffer(max(2.0, (s["width_m"] or 3) / 2 + 0.6)) for s in data("streets")["streets"]]
    stree = STRtree(streets)

    def free(x, y):
        p = Point(x, y)
        return not any(bpolys[i].contains(p) for i in btree.query(p)) and not any(streets[i].contains(p) for i in stree.query(p))

    n = dict(forest=0, bamboo=0, shrub=0, weeds=0, skipped_in_sightline=0)
    corr = pagoda_corridors()
    # forest / scrub / garden fill (documented areas, inferred individual trees)
    for a in data("features")["areas"]:
        t = a["tags"]
        kind = t.get("landuse") if t.get("landuse") == "forest" else t.get("natural") if t.get("natural") in ("scrub", "wood") else \
            t.get("leisure") if t.get("leisure") in ("garden", "park") else None
        if not kind:
            continue
        try:
            poly = Polygon(a["coords"]).buffer(0)
        except Exception:
            continue
        cx, cy = poly.centroid.x, poly.centroid.y
        if abs(cx) > 300 or abs(cy) > 300:
            continue
        rng = rng_for("area", a["osm_id"])
        spacing = {"forest": 6.5, "wood": 6.5, "scrub": 4.0, "garden": 9.0, "park": 10.0}[kind]
        x0, y0, x1, y1 = poly.bounds
        xs = np.arange(x0 + spacing / 2, x1, spacing); ys = np.arange(y0 + spacing / 2, y1, spacing)
        ref = "osm:way/%s %s (area documented; individual plants inferred)" % (a["osm_id"], kind)
        for x in xs:
            for y in ys:
                px, py = x + rng.uniform(-0.45, 0.45) * spacing, y + rng.uniform(-0.45, 0.45) * spacing
                if not poly.contains(Point(px, py)) or not free(px, py):
                    continue
                if corr is not None and corr.contains(Point(px, py)):
                    n["skipped_in_sightline"] += 1
                    continue
                r = rng.random()
                if kind == "scrub":
                    proto = "T_Shrub_1" if r < 0.6 else "T_Bamboo_1" if r < 0.8 else "T_Maple_2"
                elif kind in ("garden", "park"):
                    proto = "T_Maple_1" if r < 0.35 else "T_Pine_1" if r < 0.55 else "T_Shrub_1" if r < 0.8 else "T_Cherry_2"
                else:
                    proto = "T_Broad_1" if r < 0.3 else "T_Broad_2" if r < 0.5 else "T_Maple_3" if r < 0.68 else \
                        "T_Bamboo_2" if r < 0.8 else "T_Pine_2" if r < 0.92 else "T_Ginkgo_1"
                s = rng.uniform(0.85, 1.3)
                _inst(lib, proto, coll, "TreeArt_%s_%d" % (a["osm_id"], n["forest"]), (px, py, gz(px, py) - 0.1),
                      rng.uniform(0, 6.28), s, dict(artistic=True, detail_class="artistic", documented=False, evidence_ref=ref, collide=False))
                n["forest"] += 1
    # shrubs along stone walls (garden side and street side alternately), very sparse
    for bar in data("features")["barriers"]:
        if bar.get("point") or bar["barrier"] not in ("wall", "retaining_wall", "hedge", "fence"):
            continue
        c = np.array(bar["coords"])
        if np.abs(c).max() > 260:
            continue
        rng = rng_for("bar", bar["osm_id"])
        ln = np.r_[0, np.cumsum(np.linalg.norm(np.diff(c, axis=0), axis=1))]
        for d in np.arange(1.5, ln[-1], 7.0):
            if rng.random() > 0.45:
                continue
            i = min(len(c) - 2, int(np.searchsorted(ln, d, side="right") - 1))
            p = c[i] + (c[i + 1] - c[i]) * (d - ln[i]) / max(ln[i + 1] - ln[i], 1e-6)
            u = (c[i + 1] - c[i]) / max(np.linalg.norm(c[i + 1] - c[i]), 1e-6)
            side = 1 if rng.random() < 0.5 else -1
            q = p + np.array([-u[1], u[0]]) * 0.7 * side
            if not free(q[0], q[1]):
                continue
            proto = "T_Shrub_1" if rng.random() < 0.7 else "T_Shrub_2"
            _inst(lib, proto, coll, "Shrub_art_%d" % n["shrub"], (q[0], q[1], gz(q[0], q[1])), rng.uniform(0, 6.28),
                  rng.uniform(0.7, 1.2), dict(artistic=True, detail_class="artistic", evidence_ref="artistic: shrub at OSM barrier %s" % bar["osm_id"], collide=False))
            n["shrub"] += 1
    # weeds along P2 facade bases (between paving and walls)
    for e in [o for o in bpy.data.objects if o.type == "EMPTY" and o.get("kit_piece") in ("K_Koshi", "K_Koshi_Lit", "K_Door", "K_Inuyarai")]:
        rng = rng_for("weed", e.name)
        if rng.random() < 0.55:
            continue
        loc = e.matrix_world @ Vector((rng.uniform(0.1, 1.7), -0.25 if e["kit_piece"] != "K_Inuyarai" else -0.5, 0))
        loc.z = gz(loc.x, loc.y)
        _inst(lib, "T_Weeds_1", coll, "Weeds_art_%d" % n["weeds"], loc, rng.uniform(0, 6.28), rng.uniform(0.7, 1.3),
              dict(artistic=True, detail_class="artistic", evidence_ref="artistic: weeds at facade base", collide=False))
        n["weeds"] += 1
    log("artistic vegetation", n)
    fallen_leaves(coll, log)
    return n


def fallen_leaves(coll, log):
    """Flat fallen maple leaves on the P2 paving (denser near gutters and near maples)."""
    maples = np.array([o.location[:2] for o in bpy.data.objects if o.get("species") == "maple" or "Maple" in o.get("proto", "")] or [[1e6, 1e6]])
    total = 0
    for ob in [o for o in bpy.data.objects if o.name.startswith("Paving_osm")]:
        me = ob.data
        V = np.array([v.co[:] for v in me.vertices])
        uve = me.uv_layers.get("UVEdge")
        rng = rng_for("leaves", ob.name)
        bm = bmesh.new()
        polys = list(me.polygons)
        for p in polys:
            c = np.array(p.center)
            dm = np.min(np.hypot(maples[:, 0] - c[0], maples[:, 1] - c[1]))
            # loops -> UVEdge.y (distance to edge)
            ed = min(uve.data[li].uv[1] for li in p.loop_indices) if uve else 1.0
            dens = 1.2 + (6.0 if ed < 0.4 else 0.0) + (10.0 * math.exp(-dm / 12.0))
            k = rng.poisson(dens * p.area * 0.6)
            vs = [V[i] for i in p.vertices]
            for _ in range(k):
                w = rng.dirichlet([1, 1, 1, 1])
                q = sum(wi * vi for wi, vi in zip(w, vs))
                a = rng.uniform(0, 2 * math.pi); s = rng.uniform(0.04, 0.07)
                ca, sa = math.cos(a) * s, math.sin(a) * s
                z = q[2] + 0.006 + rng.uniform(0, 0.004)
                pts = [(q[0] - ca, q[1] - sa, z), (q[0] - sa * 0.6, q[1] + ca * 0.6, z + 0.004),
                       (q[0] + ca, q[1] + sa, z), (q[0] + sa * 0.6, q[1] - ca * 0.6, z + 0.004)]
                bm.faces.new([bm.verts.new(pp) for pp in pts])
                total += 1
        mm = bpy.data.meshes.new("Veg_FallenLeaves_" + ob.name)
        bm.to_mesh(mm); bm.free()
        mm.materials.append(M("fallen_leaf"))
        lo = bpy.data.objects.new("Veg_FallenLeaves_" + ob.name[7:], mm)
        lo["artistic"] = True; lo["detail_class"] = "artistic"; lo["evidence_ref"] = "artistic: late-autumn fallen leaves"; lo["exclude_web"] = True
        coll.objects.link(lo)
    log("fallen leaves", total)


def run(log=print):
    lib = build_protos()
    lib.update({k: bpy.data.collections[k] for k in PROTOS})
    nd = documented_trees(lib, log)
    na = artistic(lib, log)
    bpy.context.scene["vegetation"] = "documented %d, artistic %s, season late autumn" % (nd, na)
