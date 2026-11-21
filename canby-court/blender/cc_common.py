"""Canby Court scene builder - shared helpers (data loading, DTM sampling, geometry, mesh/material utils).

Frame: local EPSG:6339 metres, origin E 539320 / N 5396840 (3905 address point), x east, y north,
z = NAVD88 metres (absolute). Blender: 1 unit = 1 m, +Z up. The web export converts to Y-up.
"""
import json
import math
import os
import zlib

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")
PROC = os.path.join(DATA, "processed")
RAW = os.path.join(DATA, "raw")
TEX_BL = os.path.join(HERE, "textures")
TEX_WEB = os.path.join(ROOT, "web", "assets", "tex")
WEB_ASSETS = os.path.join(ROOT, "web", "assets")
RENDERS = os.path.join(ROOT, "renders")
BLEND = os.path.join(HERE, "canby_court.blend")
for _d in (TEX_BL, TEX_WEB, RENDERS):
    os.makedirs(_d, exist_ok=True)

ORIGIN_E, ORIGIN_N = 539320.0, 5396840.0


def jload(*p):
    return json.load(open(os.path.join(*p)))


_cache = {}


def data(name):
    """houses / trees / boundary / sledding / terrain / context / jumps / facades."""
    if name in _cache:
        return _cache[name]
    paths = {
        "houses": (PROC, "houses.json"), "trees": (PROC, "trees.json"), "boundary": (PROC, "boundary.json"),
        "sledding": (PROC, "sledding.json"), "terrain": (PROC, "terrain.json"),
        "context": (PROC, "context_buildings.json"), "jumps": (DATA, "game", "jumps.json"),
        "facades": (DATA, "facades.json"),
    }
    _cache[name] = jload(*paths[name])
    return _cache[name]


def house(num):
    for h in data("houses")["houses"]:
        if h["number"] == num:
            return h
    raise KeyError(num)


def facade(num):
    for f in data("facades")["houses"]:
        if f["number"] == num:
            return f
    raise KeyError(num)


def fval(rec, key, default=None):
    """facades.json fields are {value, confidence, source}; return the value."""
    v = rec.get(key, default)
    if isinstance(v, dict) and "value" in v:
        return v["value"]
    return v


def seed_of(*parts):
    return zlib.crc32("|".join(str(p) for p in parts).encode()) & 0xFFFFFFFF


def rng_for(*parts):
    return np.random.default_rng(seed_of(*parts))


# ----------------------------------------------------------------------------- DTM
class DTM:
    """Bilinear sampler of the 0.5 m NAVD88 DTM in the local frame (+ editable overrides grid)."""

    def __init__(self):
        import rasterio
        r = rasterio.open(os.path.join(PROC, "terrain", "dtm_0p5m.tif"))
        self.z = r.read(1).astype(np.float64)
        t = r.transform
        self.res = t.a
        self.x0 = t.c - ORIGIN_E          # left edge (local)
        self.y0 = t.f - ORIGIN_N          # top edge (local)
        self.h, self.w = self.z.shape
        self.z_orig = self.z.copy()

    def sample(self, x, y):
        x = np.asarray(x, dtype=np.float64)
        y = np.asarray(y, dtype=np.float64)
        c = (x - self.x0) / self.res - 0.5
        r = (self.y0 - y) / self.res - 0.5
        c = np.clip(c, 0, self.w - 1.001)
        r = np.clip(r, 0, self.h - 1.001)
        c0 = np.floor(c).astype(int)
        r0 = np.floor(r).astype(int)
        fc = c - c0
        fr = r - r0
        z = self.z
        a = z[r0, c0] * (1 - fc) + z[r0, c0 + 1] * fc
        b = z[r0 + 1, c0] * (1 - fc) + z[r0 + 1, c0 + 1] * fc
        return a * (1 - fr) + b * fr

    def grid_xy(self):
        cols = self.x0 + (np.arange(self.w) + 0.5) * self.res
        rows = self.y0 - (np.arange(self.h) + 0.5) * self.res
        return cols, rows

    def flatten_polygon(self, poly, z, feather=1.5, mode="set"):
        """Grade the DTM to z inside poly (shapely), blending over `feather` metres outside."""
        from shapely import contains_xy
        cols, rows = self.grid_xy()
        minx, miny, maxx, maxy = poly.bounds
        ci = np.where((cols > minx - feather - 1) & (cols < maxx + feather + 1))[0]
        ri = np.where((rows > miny - feather - 1) & (rows < maxy + feather + 1))[0]
        if len(ci) == 0 or len(ri) == 0:
            return
        X, Y = np.meshgrid(cols[ci], rows[ri])
        inside = contains_xy(poly, X, Y)
        if feather > 0:
            from shapely import distance, points
            d = distance(poly, points(X.ravel(), Y.ravel())).reshape(X.shape)
            wgt = np.clip(1 - d / feather, 0, 1)
            wgt = wgt * wgt * (3 - 2 * wgt)
        else:
            wgt = inside.astype(float)
        sub = self.z[np.ix_(ri, ci)]
        zz = z if np.isscalar(z) else z(X, Y)
        if mode == "max":
            target = np.maximum(sub, zz)
        elif mode == "min":
            target = np.minimum(sub, zz)
        else:
            target = zz
        self.z[np.ix_(ri, ci)] = sub * (1 - wgt) + target * wgt


_dtm = None


def dtm():
    global _dtm
    if _dtm is None:
        _dtm = DTM()
    return _dtm


# ----------------------------------------------------------------------------- 2D geometry
def rot2(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, -s], [s, c]])


def poly_area(pts):
    p = np.asarray(pts)
    return 0.5 * np.sum(p[:, 0] * np.roll(p[:, 1], -1) - np.roll(p[:, 0], -1) * p[:, 1])


def ccw(pts):
    pts = [tuple(p) for p in pts]
    if pts[0] == pts[-1]:
        pts = pts[:-1]
    return pts if poly_area(pts) > 0 else pts[::-1]


def resample_line(pts, step):
    """Resample a polyline at ~step spacing; returns array (n,2) and cumulative distance."""
    p = np.asarray(pts, dtype=float)
    seg = np.linalg.norm(np.diff(p, axis=0), axis=1)
    d = np.concatenate([[0], np.cumsum(seg)])
    n = max(2, int(math.ceil(d[-1] / step)) + 1)
    s = np.linspace(0, d[-1], n)
    x = np.interp(s, d, p[:, 0])
    y = np.interp(s, d, p[:, 1])
    return np.stack([x, y], 1), s


def line_normals(p):
    t = np.gradient(p, axis=0)
    t /= np.maximum(1e-9, np.linalg.norm(t, axis=1, keepdims=True))
    return np.stack([-t[:, 1], t[:, 0]], 1), t


def heading_vec(deg):
    """jumps.json heading: math angle CCW from +x (east)."""
    a = math.radians(deg)
    return np.array([math.cos(a), math.sin(a)])


# ----------------------------------------------------------------------------- bpy helpers
def bpy_mod():
    import bpy
    return bpy


def get_coll(name, parent=None):
    bpy = bpy_mod()
    c = bpy.data.collections.get(name)
    if c is None:
        c = bpy.data.collections.new(name)
        (parent or bpy.context.scene.collection).children.link(c)
    return c


def mesh_from_data(name, verts, faces, coll=None, mats=None, mat_idx=None, uvs=None, uv_name="UVMap",
                   smooth=False, extras=None, uv2=None):
    """Create a mesh object. uvs: per-loop list/array (n_loops, 2) in face-corner order, or None."""
    bpy = bpy_mod()
    me = bpy.data.meshes.new(name)
    verts = np.asarray(verts, dtype=np.float64).reshape(-1, 3)
    me.vertices.add(len(verts))
    me.vertices.foreach_set("co", verts.astype(np.float32).ravel())
    nl = [len(f) for f in faces]
    me.loops.add(sum(nl))
    me.polygons.add(len(faces))
    li = np.concatenate([np.asarray(f, dtype=np.int32) for f in faces]) if faces else np.zeros(0, np.int32)
    me.loops.foreach_set("vertex_index", li)
    ls = np.concatenate([[0], np.cumsum(nl)[:-1]]).astype(np.int32) if faces else np.zeros(0, np.int32)
    me.polygons.foreach_set("loop_start", ls)
    if mat_idx is not None:
        me.polygons.foreach_set("material_index", np.asarray(mat_idx, dtype=np.int32))
    if uvs is not None:
        uvl = me.uv_layers.new(name=uv_name)
        uvl.data.foreach_set("uv", np.asarray(uvs, dtype=np.float32).ravel())
    if uv2 is not None:
        uvl = me.uv_layers.new(name="UV2")
        uvl.data.foreach_set("uv", np.asarray(uv2, dtype=np.float32).ravel())
    me.update(calc_edges=True)
    me.validate(clean_customdata=False)
    if smooth:
        me.polygons.foreach_set("use_smooth", np.ones(len(me.polygons), dtype=bool))
    ob = bpy.data.objects.new(name, me)
    (coll or bpy.context.scene.collection).objects.link(ob)
    for m in (mats or []):
        me.materials.append(m)
    if extras:
        for k, v in extras.items():
            ob[k] = v
    return ob


class MeshBuilder:
    """Accumulate quads/tris with per-loop UVs and material slots, then emit one object."""

    def __init__(self):
        self.v = []
        self.f = []
        self.uv = []
        self.mi = []
        self.mats = []
        self.smooth = []

    def mat(self, m):
        if m not in self.mats:
            self.mats.append(m)
        return self.mats.index(m)

    def add_verts(self, pts):
        i0 = len(self.v)
        self.v.extend([tuple(map(float, p)) for p in pts])
        return list(range(i0, i0 + len(pts)))

    def face(self, idx, uvs, mat, smooth=False):
        self.f.append(list(idx))
        self.uv.extend([tuple(map(float, u)) for u in uvs])
        self.mi.append(self.mat(mat))
        self.smooth.append(smooth)

    def poly(self, pts, mat, uvs=None, uv_mode="wall", smooth=False, uv_scale=1.0):
        """Add one polygon from 3D points (new verts). uv_mode: 'wall' (u along first edge, v = z),
        'xy' (world x,y), 'plane' (u along first edge, v in plane), or explicit uvs."""
        pts = np.asarray(pts, dtype=float)
        idx = self.add_verts(pts)
        if uvs is None:
            uvs = auto_uv(pts, uv_mode) * uv_scale
        self.face(idx, uvs, mat, smooth)
        return idx

    def box(self, center, size, mat, rotz=0.0, uv_mode="box", skip=()):
        cx, cy, cz = center
        sx, sy, sz = [s / 2 for s in size]
        c, s = math.cos(rotz), math.sin(rotz)
        corners = []
        for dz in (-sz, sz):
            for dx, dy in ((-sx, -sy), (sx, -sy), (sx, sy), (-sx, sy)):
                corners.append((cx + c * dx - s * dy, cy + s * dx + c * dy, cz + dz))
        P = np.array(corners)
        quads = {"bottom": [3, 2, 1, 0], "top": [4, 5, 6, 7], "s": [0, 1, 5, 4], "e": [1, 2, 6, 5],
                 "n": [2, 3, 7, 6], "w": [3, 0, 4, 7]}
        for k, q in quads.items():
            if k in skip:
                continue
            self.poly(P[q], mat, uv_mode="plane")

    def prism(self, base_pts, z0, z1, mat, cap_top=True, cap_bottom=False, smooth=False):
        """Vertical extrusion of a CCW polygon."""
        base = [tuple(p) for p in base_pts]
        n = len(base)
        for i in range(n):
            a, b = base[i], base[(i + 1) % n]
            self.poly([(a[0], a[1], z0), (b[0], b[1], z0), (b[0], b[1], z1), (a[0], a[1], z1)], mat, uv_mode="wall",
                      smooth=smooth)
        if cap_top:
            self.poly([(p[0], p[1], z1) for p in base], mat, uv_mode="xy")
        if cap_bottom:
            self.poly([(p[0], p[1], z0) for p in base[::-1]], mat, uv_mode="xy")

    def tube(self, path, radius, mat, sides=6, cap=True, smooth=True, r_end=None, uv_len=1.0):
        """Tube along a 3D polyline (path: (n,3)); radius may taper to r_end."""
        P = np.asarray(path, dtype=float)
        n = len(P)
        r_end = radius if r_end is None else r_end
        rings = []
        acc = 0.0
        prev_side = None
        for i in range(n):
            t = P[min(i + 1, n - 1)] - P[max(i - 1, 0)]
            t /= np.linalg.norm(t) + 1e-12
            if prev_side is None:
                up = np.array([0, 0, 1.0]) if abs(t[2]) < 0.9 else np.array([1.0, 0, 0])
                side = np.cross(t, up)
            else:
                side = prev_side - t * np.dot(prev_side, t)
            side /= np.linalg.norm(side) + 1e-12
            prev_side = side
            up2 = np.cross(side, t)
            r = radius + (r_end - radius) * (i / max(1, n - 1))
            if i > 0:
                acc += np.linalg.norm(P[i] - P[i - 1])
            ring = [P[i] + r * (math.cos(a) * side + math.sin(a) * up2) for a in np.linspace(0, 2 * math.pi, sides + 1)]
            rings.append((self.add_verts(ring), acc))
        circ = 2 * math.pi * max(radius, 1e-3)
        for i in range(n - 1):
            (ra, va), (rb, vb) = rings[i], rings[i + 1]
            for k in range(sides):
                u0, u1 = k / sides * circ, (k + 1) / sides * circ
                self.face([ra[k], ra[k + 1], rb[k + 1], rb[k]],
                          [(u0, va * uv_len), (u1, va * uv_len), (u1, vb * uv_len), (u0, vb * uv_len)], mat, smooth)
        if cap:
            r0 = rings[-1][0][:sides]
            self.face(r0, [(0, 0)] * sides, mat, smooth)

    def emit(self, name, coll=None, extras=None, smooth_all=None):
        ob = mesh_from_data(name, self.v, self.f, coll=coll, mats=self.mats, mat_idx=self.mi, uvs=self.uv,
                            extras=extras)
        sm = self.smooth if smooth_all is None else [smooth_all] * len(self.f)
        ob.data.polygons.foreach_set("use_smooth", np.asarray(sm, dtype=bool))
        return ob

    def __len__(self):
        return len(self.f)


def auto_uv(pts, mode):
    pts = np.asarray(pts, dtype=float)
    if mode == "xy":
        return pts[:, :2].copy()
    e = pts[1] - pts[0]
    if mode == "wall":
        h = np.array([e[0], e[1], 0.0])
        if np.linalg.norm(h) < 1e-6:
            h = np.array([1.0, 0, 0])
        h /= np.linalg.norm(h)
        return np.stack([(pts - pts[0]) @ h, pts[:, 2]], 1)
    # plane / box: u along the first edge, v perpendicular in-plane (choose v pointing "up" if possible)
    n = np.cross(pts[1] - pts[0], pts[2] - pts[0]) if len(pts) >= 3 else np.array([0, 0, 1.0])
    nn = np.linalg.norm(n)
    n = n / nn if nn > 1e-9 else np.array([0, 0, 1.0])
    if abs(n[2]) > 0.9:          # horizontal face -> world xy
        return pts[:, :2].copy()
    u = np.cross(np.array([0, 0, 1.0]), n)
    u /= np.linalg.norm(u)
    v = np.cross(n, u)
    return np.stack([(pts - pts[0]) @ u, (pts - pts[0]) @ v + pts[0][2]], 1)


def set_extras(ob, **kw):
    for k, v in kw.items():
        if v is None:
            continue
        ob[k] = v


def srgb2lin(c):
    c = np.asarray(c, dtype=float)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def hex2lin(h, a=1.0):
    h = h.lstrip("#")
    c = srgb2lin([int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)])
    return (float(c[0]), float(c[1]), float(c[2]), a)


def hex2srgb(h):
    h = h.lstrip("#")
    return np.array([int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)])
