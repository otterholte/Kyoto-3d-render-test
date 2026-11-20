"""Phase 5 architecture pass: priority classification, eave-correct walls, roof thickness, ridges.

Priority 2 = buildings fronting Yasaka-dori / Ninenzaka / Sannenzaka / Ichinenzaka (P2_STREETS):
  * PLATEAU LOD2 walls stand on the roof edge (lod0RoofEdge). Outer walls are regenerated inset from the
    roof edge so that the surveyed roof edge becomes a real eave:
      - edge matched to a GSI 建築物の外周線 (BldL) line  -> inset = measured offset (detail "gsi")
      - otherwise                                       -> 0.5 m (validation median), flagged inferred
      - party walls (another footprint within 0.6 m)   -> no inset
  * roof surfaces kept exactly (shape + height), given 0.2 m thickness (vertical), ridge caps
    (munagawara) on convex roof edges, a nokigawara tile-end roll along horizontal eave edges.
Priority 3 = other buildings inside the box: geometry kept, roof thickness + ridge caps only.
Priority 4 = backdrop outside the box: untouched massing.
"""
import json
import math

import bpy
import bmesh
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from shapely.geometry import LineString, Point, Polygon
from shapely.strtree import STRtree

from kit_common import data, gz, p2_lines

ROOF_T = 0.2          # roof slab thickness (m)
P2_FRONT = 2.5        # footprint within (street half-width + this) of a P2 centreline -> priority 2
DEFAULT_INSET = 0.5


def _ring(fp):
    r = np.array(fp, float)
    if np.allclose(r[0], r[-1]):
        r = r[:-1]
    # drop near-duplicate consecutive points
    keep = [0]
    for i in range(1, len(r)):
        if np.linalg.norm(r[i] - r[keep[-1]]) > 0.05:
            keep.append(i)
    r = r[keep]
    if len(r) > 3 and np.linalg.norm(r[0] - r[-1]) < 0.05:
        r = r[:-1]
    # CCW
    a = 0.5 * np.sum(r[:, 0] * np.roll(r[:, 1], -1) - np.roll(r[:, 0], -1) * r[:, 1])
    if a < 0:
        r = r[::-1]
    return r


class Context:
    def __init__(self):
        B = data("buildings")["buildings"]
        self.rec = {b["id"]: b for b in B}
        self.polys = []
        self.pids = []
        for b in B:
            try:
                p = Polygon(b["footprint"])
                if not p.is_valid:
                    p = p.buffer(0)
                self.polys.append(p); self.pids.append(b["id"])
            except Exception:
                pass
        self.tree = STRtree(self.polys)
        segs, fids = [], []
        for g in data("streets")["gsi"]["BldL"]:
            c = g["coords"]
            for a, b2 in zip(c[:-1], c[1:]):
                if np.hypot(b2[0] - a[0], b2[1] - a[1]) > 0.2:
                    segs.append(LineString([a, b2])); fids.append(g["fid"])
        self.gsegs, self.gfids = segs, fids
        self.gtree = STRtree(segs)
        self.lines = p2_lines()

    def others_at(self, x, y, self_id):
        pt = Point(x, y)
        for i in self.tree.query(pt):
            if self.pids[i] != self_id and self.polys[i].contains(pt):
                return True
        return False

    def p2_front(self, poly):
        best = None
        for key, w, ls, width, hw in self.lines:
            d = ls.distance(poly)
            if d <= width / 2 + P2_FRONT and (best is None or d < best[0]):
                best = (d, key, w)
        return best


def edge_insets(ctx, ring, bid):
    """Per-edge inset distance + source string."""
    n = len(ring)
    out = []
    for i in range(n):
        a, b = ring[i], ring[(i + 1) % n]
        L = float(np.linalg.norm(b - a))
        if L < 0.25:
            out.append((0.0, "edge < 0.25 m (kept)", None)); continue
        u = (b - a) / L
        nin = np.array([-u[1], u[0]])
        party = 0
        for t in (0.2, 0.5, 0.8):
            p = a + (b - a) * t - nin * 0.6
            party += ctx.others_at(p[0], p[1], bid)
        if party >= 2:
            out.append((0.0, "party wall: adjacent footprint within 0.6 m (no inset)", None)); continue
        el = LineString([a, b])
        best = None
        for k in ctx.gtree.query(el.buffer(1.8)):
            s = ctx.gsegs[k]
            c0, c1 = np.array(s.coords[0]), np.array(s.coords[1])
            sv = c1 - c0; sl = np.linalg.norm(sv)
            if abs(np.dot(sv / sl, u)) < math.cos(math.radians(12)):
                continue
            t0, t1 = sorted([np.dot(c0 - a, u), np.dot(c1 - a, u)])
            ov = min(L, t1) - max(0.0, t0)
            if ov < 0.3 * min(L, sl):
                continue
            tm = 0.5 * (max(0.0, t0) + min(L, t1))
            # signed inward distance of the GSI line at the overlap midpoint
            sp = c0 + sv * ((tm - np.dot(c0 - a, u)) / np.dot(sv, u))
            dd = float(np.dot(sp - a, nin))
            if -0.3 < dd < 1.6 and (best is None or ov > best[0]):
                best = (ov, dd, ctx.gfids[k])
        if best and best[1] >= 0.3:
            dd = best[1]
            d = min(dd, 1.2)
            src = "gsi:BldL %s measured %.2f m%s" % (best[2], dd, "" if abs(d - dd) < 1e-6 else " (clamped to %.2f)" % d)
            out.append((d, src, best[2]))
        elif best:
            out.append((DEFAULT_INSET, "inferred: 0.5 m (GSI BldL %s traces the roof edge, %.2f m)" % (best[2], best[1]), None))
        else:
            out.append((DEFAULT_INSET, "inferred: 0.5 m (median GSI wall offset, validation_report)", None))
    return out


def inset_ring(ring, d):
    n = len(ring)
    Q = np.zeros_like(ring)
    for i in range(n):
        p = ring[i]
        a0, a1 = ring[i - 1], ring[i]
        b0, b1 = ring[i], ring[(i + 1) % n]
        u0 = (a1 - a0) / max(np.linalg.norm(a1 - a0), 1e-9)
        u1 = (b1 - b0) / max(np.linalg.norm(b1 - b0), 1e-9)
        n0 = np.array([-u0[1], u0[0]]); n1 = np.array([-u1[1], u1[0]])
        d0, d1 = d[i - 1], d[i]
        P0 = a1 + n0 * d0; P1 = b0 + n1 * d1
        cr = u0[0] * u1[1] - u0[1] * u1[0]
        if abs(cr) < 0.15:
            Q[i] = p + (n0 * d0 + n1 * d1) * 0.5
        else:
            t = ((P1[0] - P0[0]) * u1[1] - (P1[1] - P0[1]) * u1[0]) / cr
            q = P0 + u0 * t
            if np.linalg.norm(q - p) > 2.5 * max(d0, d1, 0.05):
                q = p + (n0 * d0 + n1 * d1) * 0.5
            Q[i] = q
    return Q


def _seg_dist(p, a, b):
    ab = b - a
    t = np.clip(np.dot(p - a, ab) / max(np.dot(ab, ab), 1e-12), 0, 1)
    return np.linalg.norm(p - (a + ab * t)), t


def _prism(bm, p0, p1, w, h_up, h_dn, col_layer, col, mat):
    """Box along p0->p1 (3D), width w (horizontal), extending h_up above and h_dn below the line."""
    p0 = Vector(p0); p1 = Vector(p1)
    ax = p1 - p0
    if ax.length < 0.05:
        return
    ax.normalize()
    side = ax.cross(Vector((0, 0, 1)))
    if side.length < 1e-3:
        return
    side.normalize()
    up = side.cross(ax).normalized()
    if up.z < 0:
        up = -up
    corners = []
    for p in (p0, p1):
        for s, v in ((-1, -h_dn), (1, -h_dn), (1, h_up), (-1, h_up)):
            corners.append(bm.verts.new(p + side * (s * w / 2) + up * v))
    q = corners
    faces = [(0, 1, 2, 3), (7, 6, 5, 4), (0, 4, 5, 1), (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 4, 0)]
    for f in faces:
        try:
            ff = bm.faces.new([q[i] for i in f]); ff.material_index = mat
            for lp in ff.loops:
                lp[col_layer] = col
        except ValueError:
            pass


def _roof_details(bm, roof_faces, col_layer, ring, eaves=True):
    """Ridge caps on convex roof edges; nokigawara roll on horizontal outline eave edges."""
    avg = np.zeros(4); cnt = 0
    for f in roof_faces:
        for lp in f.loops:
            avg += np.array(lp[col_layer]); cnt += 1
    rc = tuple((avg / max(cnt, 1)) * np.array([0.8, 0.8, 0.82, 1.0]))
    rset = set(roof_faces)
    jobs = []
    for e in {e for f in roof_faces for e in f.edges}:
        lf = [f for f in e.link_faces if f in rset]
        v0, v1 = e.verts[0].co.copy(), e.verts[1].co.copy()
        L = (v1 - v0).length
        if L < 0.4:
            continue
        if len(lf) == 2:
            n0, n1 = lf[0].normal, lf[1].normal
            if n0.angle(n1, 0) < math.radians(12):
                continue
            c1 = lf[1].calc_center_median()
            if (c1 - v0).dot(n0) >= -0.02:     # concave (valley) or step
                continue
            horiz = abs(v1.z - v0.z) / L < 0.15
            jobs.append(("ridge", v0, v1, 0.34 if horiz else 0.24, 0.30 if horiz else 0.18))
        elif len(lf) == 1 and eaves:
            if abs(v1.z - v0.z) / L > 0.12:
                continue
            m = np.array([(v0.x + v1.x) / 2, (v0.y + v1.y) / 2])
            dmin = min(_seg_dist(m, ring[i], ring[(i + 1) % len(ring)])[0] for i in range(len(ring)))
            if dmin > 0.25:
                continue
            jobs.append(("eave", v0, v1, 0.16, 0.0))
    for kind, v0, v1, w, h in jobs:
        if kind == "ridge":
            _prism(bm, v0, v1, w, h, 0.08, col_layer, rc, 0)
        else:
            _prism(bm, v0 + Vector((0, 0, -0.02)), v1 + Vector((0, 0, -0.02)), w, 0.07, ROOF_T + 0.04, col_layer, rc, 0)
    return len(jobs)


def _thicken(bm, roof_faces, col_layer):
    res = bmesh.ops.extrude_face_region(bm, geom=roof_faces)
    nv = [g for g in res["geom"] if isinstance(g, bmesh.types.BMVert)]
    bmesh.ops.translate(bm, verts=nv, vec=(0, 0, -ROOF_T))
    newf = [g for g in res["geom"] if isinstance(g, bmesh.types.BMFace)]
    bmesh.ops.reverse_faces(bm, faces=newf)
    return newf


def _mesh_arrays(me):
    V = np.empty(len(me.vertices) * 3); me.vertices.foreach_get("co", V); V = V.reshape(-1, 3)
    mi = np.empty(len(me.polygons), np.int32); me.polygons.foreach_get("material_index", mi)
    ca = me.color_attributes.get("plateau_rgb")
    cols = None
    if ca is not None:
        cols = np.empty(len(ca.data) * 4); ca.data.foreach_get("color", cols); cols = cols.reshape(-1, 4)
    return V, mi, cols


def rebuild_p2(ob, ctx):
    rec = ctx.rec[ob["plateau_id"]]
    me = ob.data
    V, mi, cols = _mesh_arrays(me)
    ring = _ring(rec["footprint"])
    if len(ring) < 3:
        return None
    ins = edge_insets(ctx, ring, rec["id"])
    d = np.array([x[0] for x in ins])
    Q = inset_ring(ring, d)
    qp = Polygon(Q)
    area0 = Polygon(ring).area
    for scale in (0.6, 0.3):
        if qp.is_valid and qp.area >= 0.35 * area0:
            break
        Q = inset_ring(ring, d * scale); qp = Polygon(Q)
        if qp.is_valid and qp.area >= 0.35 * area0:
            d = d * scale
            ins = [(x[0] * scale, x[1] + " (scaled x%.1f to keep footprint valid)" % scale, x[2]) for x in ins]
    if not qp.is_valid or qp.area < 0.35 * area0:
        d = np.zeros(len(ring)); Q = ring.copy(); qp = Polygon(Q)
        ins = [(0.0, "inset rejected (degenerate footprint)", None)] * len(ring)
    n = len(ring)
    # ---- classify LOD2 faces
    polys = [(p.index, list(p.vertices), list(p.loop_indices), mi[p.index], np.array(p.normal)) for p in me.polygons]
    ringline = LineString(np.vstack([ring, ring[:1]]))
    on = np.array([ringline.distance(Point(v[0], v[1])) < 0.12 for v in V])
    roof = [p for p in polys if p[3] == 0]
    walls = [p for p in polys if p[3] == 1]
    if not roof:
        return None
    zmax = float(V[:, 2].max())
    rv = [V[i] for p in roof for i in p[1]]
    rverts = [Vector(V[i]) for i in range(len(V))]
    bvh = BVHTree.FromPolygons(rverts, [p[1] for p in roof])
    outer = [p for p in walls if all(on[i] for i in p[1]) and abs(p[4][2]) < 0.2]
    inner = [p for p in walls if p not in outer]
    # per-edge wall colour from original outer walls
    def col_of(plist):
        if cols is None or not plist:
            return None
        return np.mean([cols[li] for p in plist for li in p[2]], axis=0)
    wall_default = col_of(walls)
    if wall_default is None:
        wall_default = np.array([0.6, 0.55, 0.47, 1.0])
    edge_col = []
    for i in range(n):
        a, b = ring[i], ring[(i + 1) % n]
        near = [p for p in outer if _seg_dist(V[p[1]][:, :2].mean(0), a, b)[0] < 0.15]
        c = col_of(near)
        edge_col.append(c if c is not None else wall_default)

    bm = bmesh.new()
    cl = bm.loops.layers.color.new("plateau_rgb")
    vm = {}

    def vget(i, co=None):
        key = (i, None if co is None else tuple(np.round(co, 4)))
        if key not in vm:
            vm[key] = bm.verts.new(tuple(V[i]) if co is None else tuple(co))
        return vm[key]

    roof_faces = []
    for idx, vs, lis, m, nrm in roof:
        try:
            f = bm.faces.new([vget(i) for i in vs])
        except ValueError:
            continue
        f.material_index = 0
        for lp, li in zip(f.loops, lis):
            lp[cl] = tuple(cols[li]) if cols is not None else (0.3, 0.32, 0.35, 1)
        roof_faces.append(f)
    bmesh.ops.recalc_face_normals(bm, faces=roof_faces)
    for f in roof_faces:
        if f.normal.z < 0:
            f.normal_flip()
    nd = _roof_details(bm, roof_faces, cl, ring)
    _thicken(bm, roof_faces, cl)

    # interior walls: move outline vertices onto the inset line
    def move(p2):
        best = (1e9, 0, 0)
        for i in range(n):
            dd, t = _seg_dist(p2, ring[i], ring[(i + 1) % n])
            if dd < best[0]:
                best = (dd, i, t)
        _, i, t = best
        if t < 0.02:
            return Q[i]
        if t > 0.98:
            return Q[(i + 1) % n]
        a, b = ring[i], ring[(i + 1) % n]
        u = (b - a) / max(np.linalg.norm(b - a), 1e-9)
        return p2 + np.array([-u[1], u[0]]) * d[i]
    wm = {}
    for idx, vs, lis, m, nrm in inner:
        vv = []
        for i in vs:
            if i not in wm:
                co = V[i].copy()
                if on[i]:
                    co[:2] = move(co[:2])
                wm[i] = bm.verts.new(tuple(co))
            vv.append(wm[i])
        try:
            f = bm.faces.new(vv)
        except ValueError:
            continue
        f.material_index = 1
        for lp, li in zip(f.loops, lis):
            lp[cl] = tuple(cols[li]) if cols is not None else tuple(wall_default)

    # new outer walls along the inset ring
    fp_ground = gz(ring[:, 0], ring[:, 1])
    zb = float(np.min(fp_ground)) - 0.6
    segs = []
    for i in range(n):
        a, b = Q[i], Q[(i + 1) % n]
        L = float(np.linalg.norm(b - a))
        if L < 1e-3:
            continue
        k = max(1, int(math.ceil(L / 0.5)))
        pts = [a + (b - a) * (j / k) for j in range(k + 1)]
        tops = []
        for p in pts:
            hit = bvh.ray_cast(Vector((p[0], p[1], zmax + 5)), Vector((0, 0, -1)))
            if hit[0] is None:
                # nudge towards the polygon centre
                c = np.array(qp.centroid.coords[0]) if qp.is_valid else ring.mean(0)
                pp = p + (c - p) / max(np.linalg.norm(c - p), 1e-6) * 0.3
                hit = bvh.ray_cast(Vector((pp[0], pp[1], zmax + 5)), Vector((0, 0, -1)))
            tops.append(None if hit[0] is None else hit[0].z - 0.03)
        valid = [t for t in tops if t is not None]
        fill = min(valid) if valid else rec["top_z"]
        tops = [fill if t is None else t for t in tops]
        gzs = gz(np.array(pts)[:, 0], np.array(pts)[:, 1])
        c = tuple(edge_col[i])
        for j in range(k):
            p0, p1 = pts[j], pts[j + 1]
            zs0 = float(gzs[j]) + 0.35; zs1 = float(gzs[j + 1]) + 0.35
            for (z00, z01, z11, z10, m) in ((zb, zb, zs1, zs0, 2), (zs0, zs1, tops[j + 1], tops[j], 1)):
                vv = [bm.verts.new((p0[0], p0[1], z00)), bm.verts.new((p1[0], p1[1], z01)),
                      bm.verts.new((p1[0], p1[1], z11)), bm.verts.new((p0[0], p0[1], z10))]
                f = bm.faces.new(vv); f.material_index = m
                for lp in f.loops:
                    lp[cl] = c
        segs.append(dict(i=i, a=a.tolist(), b=b.tolist(), roof_a=ring[i].tolist(), roof_b=ring[(i + 1) % n].tolist(),
                         inset=float(d[i]), src=ins[i][1], top_min=float(min(tops)),
                         ground_min=float(np.min(gzs)), ground_max=float(np.max(gzs))))
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.004)
    new = bpy.data.meshes.new(me.name + "_art")
    bm.to_mesh(new); bm.free()
    for m in me.materials:
        new.materials.append(m)
    ob.data = new
    ob["priority"] = 2
    ob["wall_inset_m"] = json.dumps([round(float(x), 3) for x in d])
    ob["wall_inset_src"] = json.dumps([x[1] for x in ins], ensure_ascii=False)
    ob["inset_detail_class"] = "observed" if any(x[2] for x in ins) else "inferred"
    ob["roof_detail"] = "PLATEAU LOD2 roof kept; +%.2f m slab, %d ridge/eave tile rolls" % (ROOF_T, nd)
    return segs


def lighten_p3(ob):
    me = ob.data
    bm = bmesh.new(); bm.from_mesh(me)
    cl = bm.loops.layers.color.get("plateau_rgb")
    if cl is None:
        cl = bm.loops.layers.color.new("plateau_rgb")
    roof_faces = [f for f in bm.faces if f.material_index == 0 and f.normal.z > 0.05]
    if roof_faces:
        rec_fp = None
        try:
            rec_fp = _ring(ob.get("_fp"))
        except Exception:
            pass
        _roof_details(bm, roof_faces, cl, rec_fp if rec_fp is not None else np.zeros((3, 2)), eaves=False)
        # thin fascia: extrude roof down (walls stay on the roof edge)
        res = bmesh.ops.extrude_face_region(bm, geom=roof_faces)
        nv = [g for g in res["geom"] if isinstance(g, bmesh.types.BMVert)]
        bmesh.ops.translate(bm, verts=nv, vec=(0, 0, -0.15))
        bmesh.ops.reverse_faces(bm, faces=[g for g in res["geom"] if isinstance(g, bmesh.types.BMFace)])
    bm.to_mesh(me); bm.free()
    ob["priority"] = 3


def run(only=None, log=print):
    """Classify every B_* building, rebuild P2, lighten P3. Returns facade segments for the kit."""
    ctx = Context()
    facades = []
    stats = dict(p2=0, p3=0, p4=0, edges_gsi=0, edges_inferred=0, edges_party=0)
    for ob in list(bpy.data.objects):
        if ob.type != "MESH" or not ob.name.startswith("B_") or "plateau_id" not in ob:
            continue
        rec = ctx.rec.get(ob["plateau_id"])
        if rec is None:
            continue
        if not rec["in_box"]:
            ob["priority"] = 4; stats["p4"] += 1
            continue
        poly = Polygon(rec["footprint"])
        fr = ctx.p2_front(poly)
        if only is not None and ob.name not in only:
            continue
        if fr and rec.get("has_lod2"):
            segs = rebuild_p2(ob, ctx)
            if segs is None:
                lighten_p3(ob); stats["p3"] += 1
                continue
            ob["street_front"] = fr[1]; ob["street_front_osm"] = str(fr[2])
            stats["p2"] += 1
            for s in segs:
                s.update(obj=ob.name, plateau_id=rec["id"], storeys=rec.get("storeys") or 0,
                         height=rec.get("height") or 0, usage=rec.get("usage") or "", year=rec.get("year") or "")
                if s["src"].startswith("gsi"):
                    stats["edges_gsi"] += 1
                elif s["src"].startswith("inferred"):
                    stats["edges_inferred"] += 1
                elif s["src"].startswith("party"):
                    stats["edges_party"] += 1
                facades.append(s)
        else:
            lighten_p3(ob); stats["p3"] += 1
    log("arch stats", stats)
    return facades, stats
