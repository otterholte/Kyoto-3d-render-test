"""Ground: DTM -> constrained Delaunay terrain (0.5 m in the street core, 1 m to the core bbox, 2.5 m to the
context edge), with the City street pavement (asphalt), 15 cm curbs + 0.45 m concrete gutter pans (C&G),
5 ft PCC sidewalks, driveways graded from the street to each garage floor, front walks, and a splat-blended
softscape (lawn / bark mulch / forest floor / paved) from the ground-cover classes.

Measured: DTM, street polygons, sidewalk centrelines, building footprints, ground-cover classes (rough).
Inferred: curb/gutter dimensions (City 'C&G' type, standard sizes), driveway shapes (from garage-door positions,
checked against the orthos), front walks.
"""
import math

import bpy
import numpy as np
import shapely
from mathutils import Vector
from mathutils.geometry import delaunay_2d_cdt
from shapely.geometry import LineString, MultiPolygon, Point, Polygon, box, shape
from shapely.ops import unary_union, transform as sh_transform

import cc_common as C
import materials as MAT

CTX = (-210.0, -160.0, 110.0, 110.0)
INNER = (-135.0, -82.0, 36.0, 46.0)
CORE = (-163.0, -110.0, 56.0, 65.0)

CURB_W = 0.15
GUTTER_W = 0.45
CURB_H = 0.15

_geo = {}


def _to_local_geom(g):
    from pyproj import Transformer
    tr = Transformer.from_crs("EPSG:4326", "EPSG:6339", always_xy=True)

    def f(x, y, z=None):
        e, n = tr.transform(x, y)
        return e - C.ORIGIN_E, n - C.ORIGIN_N
    return sh_transform(f, g)


def street_poly():
    if "street" in _geo:
        return _geo["street"]
    gj = C.jload(C.RAW, "city", "street_pavement.geojson")
    parts = [_to_local_geom(shape(f["geometry"])) for f in gj["features"] if f["properties"].get("TYPE") == "STREET"]
    s = unary_union(parts).buffer(0)
    s = s.intersection(box(*CTX).buffer(-0.01))
    s = s.buffer(0.05).buffer(-0.05).simplify(0.05)
    _geo["street"] = s
    return s


def sidewalk_lines():
    if "swl" in _geo:
        return _geo["swl"]
    gj = C.jload(C.RAW, "city", "sidewalks.geojson")
    lines = []
    for f in gj["features"]:
        g = _to_local_geom(shape(f["geometry"]))
        g = g.intersection(box(*CTX).buffer(5))
        for ln in getattr(g, "geoms", [g]):
            if ln.length > 1:
                lines.append(ln)
    _geo["swl"] = lines
    return lines


def sidewalk_poly():
    if "sw" in _geo:
        return _geo["sw"]
    st = street_poly()
    sw = unary_union([ln.buffer(0.762, cap_style="flat", join_style="round") for ln in sidewalk_lines()])
    sw = sw.difference(st.buffer(CURB_W)).intersection(box(*CTX).buffer(-0.01))
    sw = sw.buffer(0.02).buffer(-0.02)
    _geo["sw"] = sw
    return sw


def buildings_poly(hbs=None):
    polys = [Polygon(h["footprint_local"]["value"]).buffer(0) for h in C.data("houses")["houses"]]
    for b in C.data("context")["buildings"]:
        p = Polygon(b["footprint_local"]).buffer(0)
        if p.intersects(box(*CTX)):
            polys.append(p)
    return unary_union(polys)


# ============================================================================ driveways & walks
EXTRA_PAVING = {
    # observed on the 2022/2024 orthos (analysis only): 3905 parking pad east of the garage
    3905: [[(14.6, 5.2), (20.8, 4.6), (20.4, -7.5), (14.0, -6.0), (14.2, -2.4)]],
}
# observed paved paths (local metres): 3905 path from the NE patio to the garden shed
PATHS = {
    3905: [[(11.5, 8.5), (12.2, 13.0), (13.2, 18.0), (14.0, 22.4)]],
}


def plan_driveways(hbs):
    st = street_poly()
    stb = st.boundary
    drives = []
    for n, hb in hbs.items():
        gs = [p for p in hb.plan if p["kind"] == "garage"]
        if not gs:
            continue
        cen = np.mean([g["center"] for g in gs], 0)
        nrm = np.array(gs[0]["normal"])
        span = sum(g["width"] for g in gs) + 0.45 * (len(gs) - 1)
        wd = span + 1.0
        p0 = cen + nrm * 0.02
        p1 = cen + nrm * 6.0
        tp = stb.interpolate(stb.project(Point(*p1)))
        t = np.array([tp.x, tp.y])
        v = t - p1
        dist = np.linalg.norm(v)
        if dist > 0.5:
            pend = t + v / dist * 0.8
            line = LineString([tuple(p0), tuple(p1), tuple(pend)])
        else:
            line = LineString([tuple(p0), tuple(p1 + nrm * 0.8)])
        poly = line.buffer(wd / 2, cap_style="flat", join_style="round")
        # flared curb cut where it meets the street
        poly = poly.union(Point(*t).buffer(wd / 2 + 1.2).intersection(st.buffer(CURB_W + 1.6)))
        for e in EXTRA_PAVING.get(n, []):
            poly = poly.union(Polygon(e))
        fpp = Polygon(hb.fp).buffer(0.02)
        poly = poly.difference(fpp).difference(st)
        z_door = min(g["z"] for g in gs)
        drives.append(dict(house=n, poly=poly, line=line, z_door=z_door, t_street=t, width=wd))
    return drives


def grade(drives):
    """Grade the DTM along each driveway: linear from the curb to the garage floor."""
    dtm = C.dtm()
    for d in drives:
        line = d["line"]
        z_st = float(dtm.sample(*d["t_street"])) - 0.0
        z_dr = d["z_door"]
        L = line.length

        def zf(X, Y, line=line, z_st=z_st, z_dr=z_dr, L=L):
            s = shapely.line_locate_point(line, shapely.points(X.ravel(), Y.ravel())).reshape(X.shape)
            f = np.clip(s / max(L, 1e-6), 0, 1)
            return z_dr + (z_st - z_dr) * f
        dtm.flatten_polygon(d["poly"].buffer(0.3), zf, feather=1.2)


def plan_walks(hbs, drives):
    sw = sidewalk_poly()
    allp = unary_union([d["poly"] for d in drives] + [sw])
    walks = []
    for n, hb in hbs.items():
        se = getattr(hb, "stoop_end", None)
        if se is None:
            continue
        target = sw if n == 3905 else allp
        tp = target.boundary.interpolate(target.boundary.project(Point(*se)))
        if n == 3905:
            mid = (np.array(se) + np.array([tp.x, tp.y])) / 2 + np.array([-1.5, 0.5])
            line = LineString([tuple(se), tuple(mid), (tp.x, tp.y)])
        else:
            line = LineString([tuple(se), (tp.x, tp.y)])
        if line.length < 0.3:
            continue
        w = line.buffer(0.6, cap_style="round", join_style="round").difference(Polygon(hb.fp).buffer(0.02))
        walks.append(w)
        for pth in PATHS.get(n, []):
            walks.append(LineString(pth).buffer(0.55, cap_style="round"))
    return unary_union(walks) if walks else Polygon()


# ============================================================================ ground-cover splat
class Splat:
    """Blurred class masks (lawn, mulch/bed, forest floor, paved) from data/processed/groundcover."""

    def __init__(self):
        import rasterio
        from scipy.ndimage import gaussian_filter, distance_transform_edt
        r = rasterio.open(C.PROC + "/groundcover/classes_0p3m.tif")
        cl = r.read(1)
        t = r.transform
        self.res = t.a
        self.x0 = t.c - C.ORIGIN_E
        self.y0 = t.f - C.ORIGIN_N
        bld = cl == 1
        dist = distance_transform_edt(~bld) * self.res
        lawn = (cl == 6).astype(np.float32)
        bed = np.isin(cl, [7, 8, 9]).astype(np.float32)
        paved = np.isin(cl, [3, 4, 5]).astype(np.float32)
        forest = bed * (dist > 16)
        mulch = bed * (dist <= 16)
        # greenbelt south of the houses is forest regardless
        rows = self.y0 - (np.arange(cl.shape[0]) + 0.5) * self.res
        south = (rows < -78)[:, None] & np.ones_like(bld)
        forest = np.maximum(forest, mulch * south)
        mulch = mulch * (~south)
        sig = 0.45 / self.res
        self.maps = [gaussian_filter(m, sig) for m in (lawn, mulch, forest, paved)]
        tot = sum(self.maps) + 1e-4
        self.maps = [m / tot for m in self.maps]

    def sample(self, x, y):
        c = np.clip(((np.asarray(x) - self.x0) / self.res).astype(int), 0, self.maps[0].shape[1] - 1)
        r = np.clip(((self.y0 - np.asarray(y)) / self.res).astype(int), 0, self.maps[0].shape[0] - 1)
        return np.stack([m[r, c] for m in self.maps], -1)


# ============================================================================ terrain CDT
def _grid(spacing):
    pts = []
    zones = [(INNER, spacing), (CORE, spacing * 2), (CTX, spacing * 5)]
    prev = None
    for (bx, sp) in zones:
        xs = np.arange(bx[0], bx[2] + 1e-6, sp)
        ys = np.arange(bx[1], bx[3] + 1e-6, sp)
        X, Y = np.meshgrid(xs, ys)
        X, Y = X.ravel(), Y.ravel()
        if prev is not None:
            keep = ~((X > prev[0] - 1e-6) & (X < prev[2] + 1e-6) & (Y > prev[1] - 1e-6) & (Y < prev[3] + 1e-6))
            X, Y = X[keep], Y[keep]
        pts.append(np.stack([X, Y], 1))
        prev = bx
    return np.concatenate(pts)


def _rings(g):
    out = []
    for p in getattr(g, "geoms", [g]):
        if p.is_empty or p.geom_type != "Polygon":
            continue
        out.append(np.asarray(p.exterior.coords))
        for i in p.interiors:
            out.append(np.asarray(i.coords))
    return out


def _densify(ring, step):
    out = []
    for a, b in zip(ring[:-1], ring[1:]):
        L = np.linalg.norm(b - a)
        n = max(1, int(math.ceil(L / step)))
        for k in range(n):
            out.append(a + (b - a) * k / n)
    return np.array(out)


def build_cdt(constraint_geoms, spacing):
    """Returns (verts2d (n,2), tris (m,3))."""
    grid = _grid(spacing)
    # rasterise boundaries to drop grid points that would make slivers
    from PIL import Image, ImageDraw
    from scipy.ndimage import binary_dilation
    R = 0.25
    W = int((CTX[2] - CTX[0]) / R) + 1
    H = int((CTX[3] - CTX[1]) / R) + 1
    im = Image.new("L", (W, H), 0)
    dr = ImageDraw.Draw(im)
    cverts, cedges = [], []
    for g in constraint_geoms:
        for ring in _rings(g):
            dd = _densify(ring, spacing * 0.9)
            if len(dd) < 3:
                continue
            i0 = len(cverts)
            cverts.extend(dd.tolist())
            m = len(dd)
            cedges.extend([(i0 + k, i0 + (k + 1) % m) for k in range(m)])
            pix = [((p[0] - CTX[0]) / R, (CTX[3] - p[1]) / R) for p in dd] + [((dd[0][0] - CTX[0]) / R,
                                                                                (CTX[3] - dd[0][1]) / R)]
            dr.line(pix, fill=255, width=1)
    mask = np.asarray(im) > 0
    mask = binary_dilation(mask, iterations=max(1, int(spacing * 0.55 / R)))
    gi = np.clip(((grid[:, 0] - CTX[0]) / R).astype(int), 0, W - 1)
    gj = np.clip(((CTX[3] - grid[:, 1]) / R).astype(int), 0, H - 1)
    inner = (grid[:, 0] > INNER[0]) & (grid[:, 0] < INNER[2]) & (grid[:, 1] > INNER[1]) & (grid[:, 1] < INNER[3])
    keep = ~mask[gj, gi] | ~inner
    # coarse zones: drop points too close to constraints using a wider radius
    if True:
        m2 = binary_dilation(mask, iterations=int(spacing * 2.0 / R))
        keep &= ~(m2[gj, gi] & ~inner)
    grid = grid[keep]
    allv = np.concatenate([grid, np.array(cverts)]) if cverts else grid
    ng = len(grid)
    edges = [(a + ng, b + ng) for a, b in cedges]
    vs = [Vector((float(x), float(y))) for x, y in allv]
    res = delaunay_2d_cdt(vs, edges, [], 0, 1e-4)
    V = np.array([(v.x, v.y) for v in res[0]])
    F = [f for f in res[2] if len(f) == 3]
    return V, np.array(F, dtype=np.int64)


class Ground:
    def __init__(self, hbs, drives, walks):
        self.hbs = hbs
        self.drives = drives
        self.st = street_poly()
        self.curb_outer = self.st.buffer(CURB_W, join_style="mitre")
        self.gut_inner = self.st.buffer(-GUTTER_W)
        self.sw = sidewalk_poly()
        self.dr = unary_union([d["poly"] for d in drives]) if drives else Polygon()
        self.walk = walks.difference(self.st.buffer(CURB_W)).difference(self.dr) if not walks.is_empty else walks
        self.bld = buildings_poly()
        self.splat = Splat()

    def constraints(self):
        return [self.st, self.curb_outer, self.gut_inner, self.sw, self.dr, self.walk,
                self.bld.buffer(-0.3)]

    def classify(self, V, F):
        cen = V[F].mean(1)
        x, y = cen[:, 0], cen[:, 1]
        cls = np.full(len(F), "soft", dtype=object)
        cp = shapely.contains_xy
        in_b = cp(self.bld.buffer(-0.3), x, y)
        in_st = cp(self.st, x, y)
        in_gi = cp(self.gut_inner, x, y)
        in_co = cp(self.curb_outer, x, y)
        in_sw = cp(self.sw, x, y)
        in_dr = cp(self.dr, x, y) if not self.dr.is_empty else np.zeros(len(F), bool)
        in_wk = cp(self.walk, x, y) if not self.walk.is_empty else np.zeros(len(F), bool)
        cls[in_wk] = "walk"
        cls[in_dr] = "drive"
        cls[in_sw] = "sidewalk"
        cls[in_co & ~in_st] = "curb"
        cls[in_co & ~in_st & in_dr] = "apron"
        cls[in_st] = "gutter"
        cls[in_st & in_gi] = "street"
        cls[in_b] = "building"
        return cls

    def offset(self, cls, P):
        n = len(P)
        if cls in ("street", "gutter"):
            return np.full(n, -CURB_H)
        if cls == "apron":
            d = shapely.distance(self.st, shapely.points(P[:, 0], P[:, 1]))
            return -CURB_H + np.clip(d / CURB_W, 0, 1) * CURB_H
        if cls == "soft":
            return np.full(n, -0.01)
        return np.zeros(n)

    def uv(self, cls, P):
        if cls == "sidewalk":
            lines = sidewalk_lines()
            pts = shapely.points(P[:, 0], P[:, 1])
            dists = np.stack([shapely.distance(l, pts) for l in lines], 1)
            k = dists.argmin(1)
            u = np.zeros(len(P))
            v = np.zeros(len(P))
            for li, l in enumerate(lines):
                m = k == li
                if not m.any():
                    continue
                u[m] = shapely.line_locate_point(l, pts[m])
                # signed offset across
                s = u[m]
                q0 = shapely.line_interpolate_point(l, s)
                q1 = shapely.line_interpolate_point(l, s + 0.05)
                x0, y0 = shapely.get_x(q0), shapely.get_y(q0)
                tx, ty = shapely.get_x(q1) - x0, shapely.get_y(q1) - y0
                cr = tx * (P[m, 1] - y0) - ty * (P[m, 0] - x0)
                v[m] = np.sign(cr) * dists[m, li] / 1.0 + 0.762
            return np.stack([u, v], 1)
        if cls in ("drive", "apron"):
            out = P[:, :2].copy()
            pts = shapely.points(P[:, 0], P[:, 1])
            for d in self.drives:
                m = shapely.contains_xy(d["poly"].buffer(0.5), P[:, 0], P[:, 1])
                if not m.any():
                    continue
                L = d["line"]
                c = np.array(L.coords)
                a = math.atan2(c[1][1] - c[0][1], c[1][0] - c[0][0])
                ca, sa = math.cos(a), math.sin(a)
                rel = P[m, :2] - c[0]
                out[m, 0] = rel[:, 0] * ca + rel[:, 1] * sa
                out[m, 1] = -rel[:, 0] * sa + rel[:, 1] * ca + d["width"] / 2
            return out
        return P[:, :2].copy()

    def build(self, coll, spacing=0.5, suffix="", mats=None):
        V, F = build_cdt(self.constraints(), spacing)
        cls = self.classify(V, F)
        dtm = C.dtm()
        Z = dtm.sample(V[:, 0], V[:, 1])
        objs = {}
        offs_cache = {}
        groups = ["street", "gutter", "curb", "apron", "sidewalk", "drive", "walk", "soft"]
        vert_off = {}
        for g in groups:
            fm = cls == g
            if not fm.any():
                continue
            tri = F[fm]
            ids, inv = np.unique(tri.ravel(), return_inverse=True)
            P = np.column_stack([V[ids], Z[ids]])
            off = self.offset(g, P)
            vert_off[g] = dict(zip(ids.tolist(), off.tolist()))
            P[:, 2] += off
            faces = inv.reshape(-1, 3)
            uv = self.uv(g, P)
            loops_uv = uv[faces.ravel()]
            name = "Ground_%s%s" % (g.capitalize(), suffix)
            if g == "soft":
                sp = self.splat.sample(P[:, 0], P[:, 1])
                dom = sp[faces].mean(1).argmax(1)
                ob = C.mesh_from_data(name, P, faces.tolist(), coll=coll, uvs=loops_uv, mat_idx=dom)
                at = ob.data.color_attributes.new("splat", "FLOAT_COLOR", "POINT")
                at.data.foreach_set("color", np.column_stack([sp[:, 0], sp[:, 1], sp[:, 2], sp[:, 3]]).astype(
                    np.float32).ravel())
                for m in mats["soft"]:
                    ob.data.materials.append(m)
                ob["web_materials"] = ["GROUND_lawn", "GROUND_mulch", "GROUND_forest", "GROUND_paved"]
            else:
                ob = C.mesh_from_data(name, P, faces.tolist(), coll=coll, uvs=loops_uv)
                ob.data.materials.append(mats[g])
            ob.data.polygons.foreach_set("use_smooth", np.ones(len(faces), bool))
            C.set_extras(ob, kind="ground", surface=g, walkable=True, collide=False)
            objs[g] = ob
        # vertical faces where neighbouring classes have different offsets (curb faces, apron lips)
        from collections import defaultdict
        emap = defaultdict(list)
        for ti, (a, b, c_) in enumerate(F):
            for e in ((a, b), (b, c_), (c_, a)):
                emap[(min(e), max(e))].append(ti)
        mb = C.MeshBuilder()
        cm = mats["curb"]
        for (a, b), tl in emap.items():
            if len(tl) != 2:
                continue
            g1, g2 = cls[tl[0]], cls[tl[1]]
            if g1 == g2 or "building" in (g1, g2):
                continue
            o1a, o1b = vert_off[g1][a], vert_off[g1][b]
            o2a, o2b = vert_off[g2][a], vert_off[g2][b]
            if abs(o1a - o2a) < 0.01 and abs(o1b - o2b) < 0.01:
                continue
            lo_a, hi_a = sorted((o1a, o2a))
            lo_b, hi_b = sorted((o1b, o2b))
            pa, pb = V[a], V[b]
            q = [(pa[0], pa[1], Z[a] + lo_a), (pb[0], pb[1], Z[b] + lo_b), (pb[0], pb[1], Z[b] + hi_b),
                 (pa[0], pa[1], Z[a] + hi_a)]
            mb.poly(q, cm, uv_mode="wall")
            mb.poly(q[::-1], cm, uv_mode="wall")
        if len(mb):
            ob = mb.emit("Ground_CurbFaces%s" % suffix, coll)
            C.set_extras(ob, kind="curb", walkable=False, collide=False)
            objs["curbfaces"] = ob
        self.V, self.F, self.cls, self.Z = V, F, cls, Z
        return objs

    def build_snow(self, coll, mats, spacing=0.5, suffix=""):
        """Winter snow surface: one continuous mesh draped over everything (soft curb steps, drifts)."""
        if not hasattr(self, "V") or suffix:
            V, F = build_cdt(self.constraints(), spacing)
            cls = self.classify(V, F)
            Z = C.dtm().sample(V[:, 0], V[:, 1])
        else:
            V, F, cls, Z = self.V, self.F, self.cls, self.Z
        keep = cls != "building"
        F = F[keep]
        cls = cls[keep]
        depth = {"street": -CURB_H + 0.07, "gutter": -CURB_H + 0.08, "curb": 0.12, "apron": -0.04,
                 "sidewalk": 0.12, "drive": 0.05, "walk": 0.08, "soft": 0.22}
        tgt = np.zeros(len(V))
        cnt = np.zeros(len(V))
        for g, d in depth.items():
            m = cls == g
            ids = F[m].ravel()
            np.add.at(tgt, ids, d)
            np.add.at(cnt, ids, 1)
        used = cnt > 0
        tgt[used] /= cnt[used]
        # Laplacian smoothing of the offset over the mesh graph (soft curbs, rounded edges)
        from scipy.sparse import coo_matrix
        rows = np.concatenate([F[:, 0], F[:, 1], F[:, 2], F[:, 1], F[:, 2], F[:, 0]])
        cols = np.concatenate([F[:, 1], F[:, 2], F[:, 0], F[:, 0], F[:, 1], F[:, 2]])
        A = coo_matrix((np.ones(len(rows)), (rows, cols)), shape=(len(V), len(V))).tocsr()
        A.data[:] = 1
        deg = np.asarray(A.sum(1)).ravel() + 1e-9
        off = tgt.copy()
        for _ in range(4):
            off = 0.5 * off + 0.5 * (A @ off) / deg
        # drifts: low-frequency noise + build-up against buildings
        rng = np.random.default_rng(7)
        ph = rng.uniform(0, 6.28, 6)
        nz = (np.sin(V[:, 0] * 0.21 + ph[0]) * np.sin(V[:, 1] * 0.17 + ph[1]) * 0.03 +
              np.sin(V[:, 0] * 0.53 + V[:, 1] * 0.31 + ph[2]) * 0.015)
        softish = np.zeros(len(V))
        np.add.at(softish, F[cls == "soft"].ravel(), 1)
        softish = np.clip(softish, 0, 1)
        d_b = shapely.distance(self.bld, shapely.points(V[:, 0], V[:, 1]))
        drift = np.exp(-np.clip(d_b - 0.3, 0, None) / 0.8) * 0.12
        off = off + (nz + drift) * softish
        Pz = Z + off
        ids, inv = np.unique(F.ravel(), return_inverse=True)
        P = np.column_stack([V[ids], Pz[ids]])
        faces = inv.reshape(-1, 3)
        packed = np.isin(cls, ["street", "gutter", "drive", "apron", "walk"]).astype(int)
        ob = C.mesh_from_data("Snow_Ground%s" % suffix, P, faces.tolist(), coll=coll,
                              uvs=P[faces.ravel(), :2], mat_idx=packed)
        ob.data.materials.append(mats["fresh"])
        ob.data.materials.append(mats["packed"])
        ob.data.polygons.foreach_set("use_smooth", np.ones(len(faces), bool))
        C.set_extras(ob, kind="terrain", surface="snow", season="winter", walkable=True, collide=False)
        self.snow_P = P
        return ob


def ground_materials():
    m = {}
    m["street"] = MAT.tex_mat("GROUND_asphalt", "asphalt_street")
    m["gutter"] = MAT.tex_mat("GROUND_gutter", "concrete_plain", tint="#c9c6bf")
    m["curb"] = MAT.tex_mat("GROUND_curb", "concrete_plain", tint="#d2cfc8")
    m["apron"] = MAT.tex_mat("GROUND_drive", "concrete_drive")
    m["drive"] = m["apron"]
    m["sidewalk"] = MAT.tex_mat("GROUND_sidewalk", "concrete_sidewalk")
    m["walk"] = MAT.tex_mat("GROUND_walk", "concrete_sidewalk", scale=(1.0, 1.2))
    sp = splat_material()
    m["soft"] = [sp, sp, sp, sp]
    # web stand-ins (swapped in by export_web.py)
    MAT.tex_mat("GROUND_lawn", "lawn_grass")
    MAT.tex_mat("GROUND_mulch", "bark_mulch")
    MAT.tex_mat("GROUND_forest", "forest_floor")
    MAT.tex_mat("GROUND_paved", "concrete_plain")
    return m


def splat_material(name="GROUND_soft_splat"):
    m = bpy.data.materials.get(name)
    if m:
        return m
    m = bpy.data.materials.new(name)
    nt = m.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bs = nt.nodes.new("ShaderNodeBsdfPrincipled")
    nt.links.new(bs.outputs[0], out.inputs["Surface"])
    ca = nt.nodes.new("ShaderNodeVertexColor")
    ca.layer_name = "splat"
    sepw = nt.nodes.new("ShaderNodeSeparateColor")
    nt.links.new(ca.outputs["Color"], sepw.inputs[0])
    tc = nt.nodes.new("ShaderNodeTexCoord")
    # macro variation noise (breaks tiling)
    noi = nt.nodes.new("ShaderNodeTexNoise")
    noi.inputs["Scale"].default_value = 0.08
    noi.inputs["Detail"].default_value = 4
    nt.links.new(tc.outputs["Object"], noi.inputs["Vector"])
    noi2 = nt.nodes.new("ShaderNodeTexNoise")
    noi2.inputs["Scale"].default_value = 1.2
    noi2.inputs["Detail"].default_value = 3
    nt.links.new(tc.outputs["Object"], noi2.inputs["Vector"])
    sets = [("lawn_grass", 1.0), ("bark_mulch", 1.0), ("forest_floor", 2.0), ("concrete_plain", 2.0)]
    lib = MAT.lib()
    cols, rghs, nrms = [], [], []
    uvn = nt.nodes.new("ShaderNodeUVMap")
    uvn.uv_map = "UVMap"
    for s, size in sets:
        f = lib[s]["files"]
        mp = nt.nodes.new("ShaderNodeMapping")
        mp.inputs["Scale"].default_value = (1 / lib[s]["size_m"][0], 1 / lib[s]["size_m"][1], 1)
        nt.links.new(uvn.outputs[0], mp.inputs[0])
        ta = nt.nodes.new("ShaderNodeTexImage")
        ta.image = MAT.img(f["albedo"])
        nt.links.new(mp.outputs[0], ta.inputs[0])
        to = nt.nodes.new("ShaderNodeTexImage")
        to.image = MAT.img(f["orm"], True)
        nt.links.new(mp.outputs[0], to.inputs[0])
        tn = nt.nodes.new("ShaderNodeTexImage")
        tn.image = MAT.img(f["normal"], True)
        nt.links.new(mp.outputs[0], tn.inputs[0])
        so = nt.nodes.new("ShaderNodeSeparateColor")
        nt.links.new(to.outputs["Color"], so.inputs[0])
        cols.append(ta.outputs["Color"])
        rghs.append(so.outputs[1])
        nrms.append(tn.outputs["Color"])
    # weights: lawn edge breakup with noise
    def mix(a, b, fac_sock, kind="RGBA"):
        mx = nt.nodes.new("ShaderNodeMix")
        mx.data_type = kind
        nt.links.new(fac_sock, mx.inputs[0])
        if kind == "RGBA":
            nt.links.new(a, mx.inputs[6])
            nt.links.new(b, mx.inputs[7])
            return mx.outputs[2]
        nt.links.new(a, mx.inputs[2])
        nt.links.new(b, mx.inputs[3])
        return mx.outputs[0]

    def ramp_w(sock, lo=0.35, hi=0.65):
        mr = nt.nodes.new("ShaderNodeMapRange")
        mr.inputs["From Min"].default_value = lo
        mr.inputs["From Max"].default_value = hi
        nt.links.new(sock, mr.inputs["Value"])
        return mr.outputs[0]

    # sequential blend: forest -> mulch -> paved -> lawn
    def add(a_sock, b_sock):
        ad = nt.nodes.new("ShaderNodeMath")
        ad.operation = "ADD"
        nt.links.new(a_sock, ad.inputs[0])
        nt.links.new(b_sock, ad.inputs[1])
        return ad.outputs[0]

    def noisy(w_sock, amt=0.25):
        sub = nt.nodes.new("ShaderNodeMath")
        sub.operation = "SUBTRACT"
        nt.links.new(noi2.outputs["Fac"], sub.inputs[0])
        sub.inputs[1].default_value = 0.5
        mul = nt.nodes.new("ShaderNodeMath")
        mul.operation = "MULTIPLY"
        nt.links.new(sub.outputs[0], mul.inputs[0])
        mul.inputs[1].default_value = amt
        return add(w_sock, mul.outputs[0])

    w_mulch = ramp_w(noisy(sepw.outputs[1]))
    # alpha channel = paved weight
    cattr = nt.nodes.new("ShaderNodeAttribute")
    cattr.attribute_name = "splat"
    w_paved = ramp_w(noisy(cattr.outputs["Alpha"], 0.15), 0.4, 0.6)
    w_lawn = ramp_w(noisy(sepw.outputs[0], 0.3), 0.35, 0.6)
    col = mix(cols[2], cols[1], w_mulch)
    col = mix(col, cols[3], w_paved)
    col = mix(col, cols[0], w_lawn)
    rg = mix(rghs[2], rghs[1], w_mulch, "FLOAT")
    rg = mix(rg, rghs[3], w_paved, "FLOAT")
    rg = mix(rg, rghs[0], w_lawn, "FLOAT")
    nm = mix(nrms[2], nrms[1], w_mulch)
    nm = mix(nm, nrms[3], w_paved)
    nm = mix(nm, nrms[0], w_lawn)
    # macro tint for the lawn (dry / lush patches)
    hsv = nt.nodes.new("ShaderNodeHueSaturation")
    mr = nt.nodes.new("ShaderNodeMapRange")
    mr.inputs["To Min"].default_value = 0.8
    mr.inputs["To Max"].default_value = 1.15
    nt.links.new(noi.outputs["Fac"], mr.inputs["Value"])
    nt.links.new(mr.outputs[0], hsv.inputs["Value"])
    mr2 = nt.nodes.new("ShaderNodeMapRange")
    mr2.inputs["To Min"].default_value = 0.47
    mr2.inputs["To Max"].default_value = 0.53
    nt.links.new(noi.outputs["Fac"], mr2.inputs["Value"])
    nt.links.new(mr2.outputs[0], hsv.inputs["Hue"])
    nt.links.new(col, hsv.inputs["Color"])
    nt.links.new(hsv.outputs[0], bs.inputs["Base Color"])
    nt.links.new(rg, bs.inputs["Roughness"])
    nmap = nt.nodes.new("ShaderNodeNormalMap")
    nt.links.new(nm, nmap.inputs["Color"])
    nt.links.new(nmap.outputs[0], bs.inputs["Normal"])
    m["splat"] = True
    return m


def street_details(coll, hbs):
    """Asphalt patches, catch-basin grates, hydrant, street lights, mailboxes."""
    st = street_poly()
    dtm = C.dtm()
    rng = C.rng_for("street")
    mb = C.MeshBuilder()
    patch = MAT.tex_mat("GROUND_asphalt_patch", "asphalt_street", tint="#8c8c90", rough_mul=0.95)
    # patches (utility cuts) along Canby Ct
    cl = LineString(C.data("boundary")["canby_ct_centerline_local"]["coordinates"])
    for k in range(9):
        s = rng.uniform(5, cl.length - 5)
        p = cl.interpolate(s)
        q = cl.interpolate(min(cl.length, s + 0.5))
        a = math.atan2(q.y - p.y, q.x - p.x)
        off = rng.uniform(-3.5, 3.5)
        cx, cy = p.x - math.sin(a) * off, p.y + math.cos(a) * off
        w, h = rng.uniform(1.2, 3.0), rng.uniform(0.9, 2.2)
        rect = [(cx + math.cos(a) * dx - math.sin(a) * dy, cy + math.sin(a) * dx + math.cos(a) * dy)
                for dx, dy in ((-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2))]
        poly = Polygon(rect).intersection(st.buffer(-GUTTER_W - 0.05))
        if poly.is_empty or poly.geom_type != "Polygon":
            continue
        pts = np.asarray(poly.exterior.coords)[:-1]
        z = dtm.sample(pts[:, 0], pts[:, 1]) - CURB_H + 0.006
        mb.poly(np.column_stack([pts, z]), patch, uv_mode="xy")
    # catch basins
    grate = MAT.M("GRATE", lambda: MAT.flat_mat("METAL_grate", "#3a3836", rough=0.6, metal=0.8))
    for f in C.jload(C.RAW, "city", "catch_basins.geojson")["features"]:
        g = _to_local_geom(shape(f["geometry"]))
        if not box(*CTX).contains(g):
            continue
        z = float(dtm.sample(g.x, g.y)) - CURB_H + 0.005
        bp = st.boundary.interpolate(st.boundary.project(g))
        a = math.atan2(bp.y - g.y, bp.x - g.x)
        mb.box((g.x, g.y, z), (0.6, 0.45, 0.01), grate, rotz=a)
    ob = mb.emit("Street_Details", coll)
    C.set_extras(ob, kind="street_detail", collide=False)
    return ob
