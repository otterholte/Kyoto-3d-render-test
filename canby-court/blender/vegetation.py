"""Vegetation: PNW tree / shrub / fern / grass prototypes (real branch skeletons + alpha cards from the foliage
atlas) instanced at the measured tree positions (trees.json), hedge rows, foundation planting, lawn grass.

Species mapping (trees.json `species_guess` + type):
  Douglas-fir / conifer  -> DFIR (3 size classes)       western redcedar        -> CEDAR
  columnar arborvitae    -> THUJA                         dwarf / globe conifer   -> GLOBE shrub
  bigleaf maple/alder/birch, deciduous -> MAPLE / ALDER / BIRCH (seeded mix)
  flowering cherry       -> CHERRY                        Japanese maple / red-leaf / ornamental -> JMAPLE
HEIGHTS: trees.json heights for tall conifers come from the Meta CHM (imagery-derived ~2016) which reads low
for tall firs/cedars; conifers with species Douglas-fir / redcedar / 'conifer' taller than 12 m are scaled up
x1.45 (capped at 36 m) and flagged `height_adjusted` (see docs/scene.md). Deciduous heights are used as given.
Winter: deciduous prototypes swap to a bare-twig mesh; conifer prototypes swap to snowy-spray UVs.
"""
import json
import math

import bpy
import numpy as np
import shapely
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union

import cc_common as C
import materials as MAT

ATLAS = None


def atlas():
    global ATLAS
    if ATLAS is None:
        ATLAS = json.load(open(C.TEX_BL + "/foliage_atlas.json"))["cells"]
    return ATLAS


def cell_uv(name):
    r = atlas()[name]["uv_rect"]
    return r  # u0, v0, u1, v1 (v0 = bottom)


def cell_shift(a, b):
    ra, rb = cell_uv(a), cell_uv(b)
    return rb[0] - ra[0], rb[1] - ra[1]


# ============================================================================ materials
def veg_materials():
    m = {}
    m["fol"] = MAT.tex_mat("FOL_atlas", "foliage_atlas", alpha=True, double_sided=True, translucency=0.28,
                           spec=0.35)
    m["fol_conifer"] = MAT.tex_mat("FOL_atlas_conifer", "foliage_atlas", alpha=True, double_sided=True,
                                   translucency=0.12, spec=0.3, tint="#e6eee0")
    for k in ("fir", "cedar", "maple", "birch", "cherry"):
        m["bark_" + k] = MAT.tex_mat("BARK_" + k, "bark_" + k)
    m["dense_laurel"] = MAT.tex_mat("FOLD_laurel", "foliage_laurel", rough_mul=0.8)
    m["dense_thuja"] = MAT.tex_mat("FOLD_arborvitae", "foliage_arborvitae", tint="#9aa88f", scale=(0.5, 0.5))
    m["dense_box"] = MAT.tex_mat("FOLD_boxwood", "foliage_boxwood")
    m["dense_rhodo"] = MAT.tex_mat("FOLD_rhodo", "foliage_rhodo")
    m["dense_fir"] = MAT.tex_mat("FOLD_fir", "foliage_arborvitae", tint="#5a6a58")
    m["snow"] = MAT.tex_mat("SNOW_fresh", "snow_fresh", rough_override=0.82, normal_strength=0.6)
    return m


# ============================================================================ card helper
def add_card(mb, mat, cell, base, up, side, w, h, cell_w=None):
    """Quad with its bottom-centre at base, extending along `up` by h, width w along `side`."""
    base = np.asarray(base, float)
    up = np.asarray(up, float)
    side = np.asarray(side, float)
    up /= np.linalg.norm(up) + 1e-9
    side /= np.linalg.norm(side) + 1e-9
    u0, v0, u1, v1 = cell_uv(cell)
    P = [base - side * w / 2, base + side * w / 2, base + side * w / 2 + up * h, base - side * w / 2 + up * h]
    mb.face(mb.add_verts(P), [(u0, v0), (u1, v0), (u1, v1), (u0, v1)], mat)


def _perp(v):
    v = np.asarray(v, float)
    a = np.array([0, 0, 1.0]) if abs(v[2]) < 0.9 else np.array([1.0, 0, 0])
    p = np.cross(v, a)
    return p / (np.linalg.norm(p) + 1e-9)


def _rot(v, axis, ang):
    axis = axis / (np.linalg.norm(axis) + 1e-9)
    return v * math.cos(ang) + np.cross(axis, v) * math.sin(ang) + axis * np.dot(axis, v) * (1 - math.cos(ang))


# ============================================================================ prototypes
def proto_conifer(name, H, R, kind, mats, seed, lite=False):
    """kind: 'fir' (Douglas-fir) or 'cedar' (western redcedar)."""
    rng = np.random.default_rng(seed)
    mb = C.MeshBuilder()
    bark = mats["bark_fir" if kind == "fir" else "bark_cedar"]
    fol = mats["fol_conifer"]
    cell = "fir_spray" if kind == "fir" else "cedar_spray"
    r0 = 0.014 * H + 0.06
    lean = rng.normal(0, 0.01, 2)
    trunk = [(lean[0] * z, lean[1] * z, z) for z in np.linspace(-0.3, H, 9)]
    mb.tube(trunk, r0, bark, sides=10, r_end=0.03, cap=True)
    if kind == "cedar":  # buttress flare
        mb.tube([(0, 0, -0.3), (0, 0, 0.6)], r0 * 1.5, bark, sides=10, r_end=r0, cap=False)
    hb = H * (rng.uniform(0.22, 0.35) if kind == "fir" else rng.uniform(0.04, 0.1))
    # opaque inner crown (stops the see-through look of card-only conifers)
    core = mats["dense_fir"]
    nseg, nr = 8, 10
    rings = []
    for j in range(nr + 1):
        zz = hb + 0.3 + (H - 0.6 - hb - 0.3) * j / nr
        f = (H - zz) / (H - hb)
        rr = max(0.05, 0.42 * R * f ** 0.85)
        ring = [(rr * math.cos(2 * math.pi * k / nseg + j), rr * math.sin(2 * math.pi * k / nseg + j), zz)
                for k in range(nseg)]
        rings.append(mb.add_verts(ring))
    for j in range(nr):
        for k in range(nseg):
            a_, b_ = rings[j][k], rings[j][(k + 1) % nseg]
            c_, d_ = rings[j + 1][(k + 1) % nseg], rings[j + 1][k]
            mb.face([a_, b_, c_, d_], [(k, j), (k + 1, j), (k + 1, j + 1), (k, j + 1)], core, True)
    step = 0.42 if kind == "fir" else 0.5
    if lite:
        step *= 1.6
    z = hb
    cards = 0
    while z < H - 0.3:
        f = (H - z) / (H - hb)
        nb = rng.integers(4, 7) if kind == "fir" else rng.integers(3, 6)
        az0 = rng.uniform(0, 2 * math.pi)
        for k in range(nb):
            az = az0 + 2 * math.pi * k / nb + rng.normal(0, 0.3)
            Lb = R * (f ** 0.85) * rng.uniform(0.75, 1.1) + 0.25
            Lb = min(Lb, R * 1.05)
            dirh = np.array([math.cos(az), math.sin(az), 0.0])
            if kind == "fir":
                pitch = math.radians(-18 + 45 * (1 - f) + rng.normal(0, 6))
            else:
                pitch = math.radians(-35 + 50 * (1 - f) + rng.normal(0, 6))
            base = np.array([lean[0] * z, lean[1] * z, z])
            pts = [base]
            seg = 4
            for s in range(1, seg + 1):
                t = s / seg
                if kind == "cedar":  # J-shaped: droop then upturned tip
                    pz = math.sin(pitch) * t - 0.25 * math.sin(math.pi * t) * Lb / 3 + (0.35 * t ** 3) * (Lb / 3)
                else:
                    pz = math.sin(pitch) * t - 0.08 * t * t
                pts.append(base + dirh * Lb * t * math.cos(pitch) + np.array([0, 0, pz * Lb]))
            if not lite or Lb > 1.2:
                mb.tube(pts, max(0.015, 0.03 * Lb ** 0.6), bark, sides=4, r_end=0.008, cap=False, smooth=True)
            # sprays along the branch
            P = np.array(pts)
            segL = np.linalg.norm(np.diff(P, axis=0), axis=1)
            cum = np.concatenate([[0], np.cumsum(segL)])
            s = Lb * (0.25 if kind == "fir" else 0.15)
            spacing = (0.24 if kind == "fir" else 0.3) * (1.7 if lite else 1.0)
            while s < cum[-1]:
                q = np.array([np.interp(s, cum, P[:, i]) for i in range(3)])
                kk = min(len(P) - 2, np.searchsorted(cum, s, side="right") - 1)
                bd = P[kk + 1] - P[kk]
                bd /= np.linalg.norm(bd)
                for side_s in ((-1, 1) if not lite else (rng.choice([-1, 1]),)):
                    outv = _rot(bd, np.array([0, 0, 1.0]), side_s * rng.uniform(0.35, 1.0))
                    if kind == "cedar":
                        outv = outv + np.array([0, 0, -rng.uniform(0.3, 0.9)])
                    else:
                        outv = outv + np.array([0, 0, rng.uniform(-0.15, 0.25)])
                    sc = rng.uniform(0.85, 1.3) * (0.8 + 0.4 * min(1.0, Lb / 2))
                    sd = np.cross(outv, np.array([0, 0, 1.0]))
                    sd = _rot(sd / (np.linalg.norm(sd) + 1e-9), outv / np.linalg.norm(outv), rng.uniform(-1.3, 1.3))
                    cw, ch = atlas()[cell]["size_m"]
                    add_card(mb, fol, cell, q, outv, sd, cw * sc, ch * sc)
                    cards += 1
                s += spacing * rng.uniform(0.8, 1.2)
            # tip card along the branch direction
            add_card(mb, fol, cell, P[-2], P[-1] - P[-2] + np.array([0, 0, 0.1]), _perp(P[-1] - P[-2]),
                     0.6, 0.8)
        z += step * rng.uniform(0.8, 1.25)
    # leader
    add_card(mb, fol, cell, (lean[0] * H, lean[1] * H, H - 1.0), (0, 0, 1), (1, 0, 0), 0.5, 1.2)
    add_card(mb, fol, cell, (lean[0] * H, lean[1] * H, H - 1.0), (0, 0, 1), (0, 1, 0), 0.5, 1.2)
    ob = mb.emit(name, None)
    ob["proto"] = name
    ob["cards"] = cards
    return ob


def _decid_skeleton(rng, H, R, fork, levels=3, nscaff=(3, 5), spread=0.6):
    """Returns list of branch polylines with radii, and terminal (point, dir) list."""
    branches = []
    terms = []
    r0 = 0.018 * H + 0.05
    trunk_top = np.array([rng.normal(0, 0.1), rng.normal(0, 0.1), fork])
    trunk = [np.array([0, 0, -0.3]), np.array([0, 0, fork * 0.5]), trunk_top]
    branches.append((trunk, r0, r0 * 0.75))

    def grow(p, d, L, r, lev):
        pts = [p]
        q = p.copy()
        dd = d.copy()
        n = 4
        for i in range(n):
            dd = dd + rng.normal(0, 0.12, 3)
            dd[2] += 0.04 if lev < 2 else -0.03
            dd /= np.linalg.norm(dd)
            q = q + dd * L / n
            pts.append(q.copy())
        branches.append((pts, r, r * 0.55))
        if lev >= levels - 1:
            terms.append((pts[-1], dd))
            terms.append((pts[-2], dd))
        if lev >= levels:
            terms.append((pts[-3], dd))
            return
        nk = rng.integers(2, 4)
        for k in range(nk):
            j = rng.integers(2, len(pts))
            ax = _perp(dd)
            ax = _rot(ax, dd, rng.uniform(0, 2 * math.pi))
            nd = _rot(dd, ax, rng.uniform(0.35, 0.8))
            grow(pts[j], nd, L * rng.uniform(0.5, 0.7), r * 0.55, lev + 1)

    ns = rng.integers(*nscaff)
    az0 = rng.uniform(0, 2 * math.pi)
    for k in range(ns):
        az = az0 + 2 * math.pi * k / ns + rng.normal(0, 0.3)
        el = rng.uniform(0.9, 1.25) * (1 - spread * 0.5)
        d = np.array([math.cos(az) * math.cos(el), math.sin(az) * math.cos(el), math.sin(el)])
        grow(trunk_top, d, (H - fork) * 0.55, r0 * 0.6, 1)
    # rescale crown to fit R and H
    allp = np.concatenate([np.array(b[0]) for b in branches])
    zmax = allp[:, 2].max()
    rmax = np.max(np.hypot(allp[:, 0], allp[:, 1]))
    sz = (H * 0.93 - fork) / max(0.1, zmax - fork)
    sr = R * 0.85 / max(0.1, rmax)
    def tf(p):
        p = np.array(p, float)
        return np.array([p[0] * sr, p[1] * sr, fork + (p[2] - fork) * sz if p[2] > fork else p[2]])
    branches = [([tf(p) for p in pts], r_a, r_b) for (pts, r_a, r_b) in branches]
    terms = [(tf(p), d) for (p, d) in terms]
    return branches, terms


def proto_decid(name, H, R, kind, mats, seed, lite=False):
    """kind: maple / alder / birch / cherry / jmaple."""
    rng = np.random.default_rng(seed)
    conf = {
        "maple": dict(fork=0.28, cell="maple_cluster", bark="bark_maple", scale=1.5, per=9, levels=4),
        "alder": dict(fork=0.35, cell="birch_cluster", bark="bark_maple", scale=1.7, per=10, levels=4),
        "birch": dict(fork=0.4, cell="birch_cluster", bark="bark_birch", scale=1.5, per=10, levels=4),
        "cherry": dict(fork=0.3, cell="cherry_cluster", bark="bark_cherry", scale=1.3, per=10, levels=4),
        "jmaple": dict(fork=0.18, cell="jmaple_cluster", bark="bark_cherry", scale=1.1, per=9, levels=4),
    }[kind]
    br, terms = _decid_skeleton(rng, H, R, H * conf["fork"], levels=conf["levels"])
    bark = mats[conf["bark"]]
    fol = mats["fol"]
    leaf = C.MeshBuilder()
    wood = C.MeshBuilder()
    for (pts, ra, rb) in br:
        if lite and ra < 0.02:
            continue
        wood.tube(pts, max(0.01, ra), bark, sides=7 if ra > 0.08 else 4, r_end=max(0.006, rb), cap=False)
    # summer: leaf clusters at terminals; winter: twig cards at the same places
    twig = C.MeshBuilder()
    cw, ch = atlas()[conf["cell"]]["size_m"]
    per = conf["per"] if not lite else max(2, conf["per"] // 2)
    for (p, d) in terms:
        for k in range(per):
            dd = d + rng.normal(0, 0.6, 3)
            dd[2] += 0.25
            dd /= np.linalg.norm(dd)
            sd = _rot(_perp(dd), dd, rng.uniform(0, 2 * math.pi))
            sc = conf["scale"] * rng.uniform(0.8, 1.2)
            q = p + rng.normal(0, 0.35, 3) * (R / 5)
            add_card(leaf, fol, conf["cell"], q, dd, sd, cw * sc, ch * sc)
        for k in range(2):
            dd = d + rng.normal(0, 0.3, 3)
            dd /= np.linalg.norm(dd)
            sd = _rot(_perp(dd), dd, rng.uniform(0, 2 * math.pi))
            add_card(twig, fol, "bare_twigs", p - dd * 0.2, dd, sd, 1.1, 1.1)
    # merge wood into both versions
    sm = merge([wood, leaf], name)
    wi = merge([wood, twig], name + "_bare")
    sm["proto"] = name
    wi["proto"] = name + "_bare"
    return sm, wi


def merge(builders, name):
    mb = C.MeshBuilder()
    for b in builders:
        off = len(mb.v)
        mb.v.extend(b.v)
        for f, mi in zip(b.f, b.mi):
            mb.f.append([i + off for i in f])
            mb.mi.append(mb.mat(b.mats[mi]))
        mb.uv.extend(b.uv)
        mb.smooth.extend(b.smooth)
    return mb.emit(name, None)


def proto_blob(name, R, H, core_mat, cards, mats, seed, ncards=60, shape="ellipsoid", cell_scale=1.0):
    """Shrub / columnar conifer: displaced core + alpha cards on its surface."""
    rng = np.random.default_rng(seed)
    mb = C.MeshBuilder()
    nu, nv = 14, 10
    rings = []
    for j in range(nv + 1):
        t = j / nv
        z = t * H
        if shape == "column":
            r = R * min(1.0, 0.75 + t * 2) * max(0.0, 1 - t) ** 0.75 + 0.02
        else:
            r = 0.72 * R * math.sqrt(max(0.0, 1 - (2 * t - 1) ** 2)) * (1.0 if t > 0.1 else 0.85) + 0.01
        ring = []
        for i in range(nu):
            a = 2 * math.pi * i / nu
            rr = r * (1 + rng.normal(0, 0.08))
            ring.append((rr * math.cos(a), rr * math.sin(a), z + rng.normal(0, 0.02) * H))
        rings.append(mb.add_verts(ring))
    for j in range(nv):
        for i in range(nu):
            a, b = rings[j][i], rings[j][(i + 1) % nu]
            c, d = rings[j + 1][(i + 1) % nu], rings[j + 1][i]
            u0, u1 = i / nu * 2 * math.pi * R, (i + 1) / nu * 2 * math.pi * R
            mb.face([a, b, c, d], [(u0, j / nv * H), (u1, j / nv * H), (u1, (j + 1) / nv * H), (u0, (j + 1) / nv * H)],
                    core_mat, True)
    top = mb.add_verts([(0, 0, H)])[0]
    for i in range(nu):
        mb.face([rings[-1][i], rings[-1][(i + 1) % nu], top], [(0, 0), (1, 0), (0.5, 1)], core_mat, True)
    fol = mats["fol"]
    for k in range(ncards):
        t = rng.uniform(0.05, 0.97)
        a = rng.uniform(0, 2 * math.pi)
        z = t * H
        if shape == "column":
            r = R * min(1.0, 0.75 + t * 2) * max(0.0, 1 - t) ** 0.75
        else:
            r = R * math.sqrt(max(0.0, 1 - (2 * t - 1) ** 2))
        p = np.array([r * rng.uniform(0.55, 0.95) * math.cos(a), r * rng.uniform(0.55, 0.95) * math.sin(a), z])
        outv = np.array([math.cos(a), math.sin(a), rng.uniform(0.2, 1.0)])
        cell = cards[rng.integers(len(cards))]
        cw, ch = atlas()[cell]["size_m"]
        sc = rng.uniform(0.7, 1.1) * cell_scale
        add_card(mb, fol, cell, p, outv, _rot(_perp(outv), outv / np.linalg.norm(outv), rng.uniform(0, 6.3)),
                 cw * sc, ch * sc)
    ob = mb.emit(name, None)
    ob["proto"] = name
    return ob


def proto_fern(name, mats, seed, R=0.7):
    rng = np.random.default_rng(seed)
    mb = C.MeshBuilder()
    fol = mats["fol"]
    for k in range(18):
        a = rng.uniform(0, 2 * math.pi)
        el = rng.uniform(0.5, 1.2)
        d = np.array([math.cos(a) * math.cos(el), math.sin(a) * math.cos(el), math.sin(el)])
        side = np.array([-math.sin(a), math.cos(a), 0])
        # two segments to fake the arch
        cw, ch = atlas()["fern_frond"]["size_m"]
        s = rng.uniform(0.7, 1.0) * R / 0.7
        u0, v0, u1, v1 = cell_uv("fern_frond")
        vm = v0 + (v1 - v0) * 0.5
        p0 = np.zeros(3)
        p1 = p0 + d * ch * s * 0.5
        d2 = d.copy()
        d2[2] -= 0.6
        d2 /= np.linalg.norm(d2)
        p2 = p1 + d2 * ch * s * 0.5
        w = cw * s
        P = [p0 - side * w / 2, p0 + side * w / 2, p1 + side * w / 2, p1 - side * w / 2]
        mb.face(mb.add_verts(P), [(u0, v0), (u1, v0), (u1, vm), (u0, vm)], fol)
        P = [p1 - side * w / 2, p1 + side * w / 2, p2 + side * w / 2, p2 - side * w / 2]
        mb.face(mb.add_verts(P), [(u0, vm), (u1, vm), (u1, v1), (u0, v1)], fol)
    ob = mb.emit(name, None)
    ob["proto"] = name
    return ob


def proto_grass_clump(name, mats, seed, n=14, h=0.09):
    rng = np.random.default_rng(seed)
    mb = C.MeshBuilder()
    g = MAT.M("GRASSBLADE", lambda: grass_blade_mat())
    for k in range(n):
        a = rng.uniform(0, 2 * math.pi)
        r = rng.uniform(0, 0.03)
        base = np.array([r * math.cos(a), r * math.sin(a), 0])
        lean = rng.uniform(0.1, 0.6)
        d = np.array([math.cos(a) * lean, math.sin(a) * lean, 1.0])
        d /= np.linalg.norm(d)
        hh = h * rng.uniform(0.6, 1.3)
        side = np.array([-math.sin(a), math.cos(a), 0]) * 0.0022
        mid = base + d * hh * 0.55
        tip = base + d * hh + np.array([math.cos(a), math.sin(a), 0]) * hh * lean * 0.4
        v = mb.add_verts([base - side, base + side, mid + side * 0.8, mid - side * 0.8, tip])
        shade = rng.uniform(0, 1)
        mb.face([v[0], v[1], v[2], v[3]], [(shade, 0), (shade, 0), (shade, 0.55), (shade, 0.55)], g)
        mb.face([v[3], v[2], v[4]], [(shade, 0.55), (shade, 0.55), (shade, 1)], g)
    ob = mb.emit(name, None)
    ob["proto"] = name
    return ob


def grass_blade_mat():
    m = bpy.data.materials.new("GRASS_blade")
    nt = m.node_tree
    bs = nt.nodes["Principled BSDF"]
    uv = nt.nodes.new("ShaderNodeUVMap")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(uv.outputs[0], sep.inputs[0])
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    nt.links.new(sep.outputs[0], ramp.inputs[0])
    ramp.color_ramp.elements[0].color = C.hex2lin("#3f6a24")
    ramp.color_ramp.elements[1].color = C.hex2lin("#7f9a3e")
    e = ramp.color_ramp.elements.new(0.85)
    e.color = C.hex2lin("#9a9a52")
    grad = nt.nodes.new("ShaderNodeMix")
    grad.data_type = "RGBA"
    grad.blend_type = "MULTIPLY"
    nt.links.new(sep.outputs[1], grad.inputs[0])
    grad.inputs[6].default_value = (0.45, 0.5, 0.4, 1)
    nt.links.new(ramp.outputs[0], grad.inputs[7])
    mr = nt.nodes.new("ShaderNodeMix")
    mr.data_type = "RGBA"
    nt.links.new(sep.outputs[1], mr.inputs[0])
    nt.links.new(ramp.outputs[0], mr.inputs[7])
    c6 = nt.nodes.new("ShaderNodeMix")
    c6.data_type = "RGBA"
    c6.blend_type = "MULTIPLY"
    c6.inputs[0].default_value = 1.0
    nt.links.new(ramp.outputs[0], c6.inputs[6])
    c6.inputs[7].default_value = (0.5, 0.5, 0.5, 1)
    nt.links.new(c6.outputs[2], mr.inputs[6])
    nt.links.new(mr.outputs[2], bs.inputs["Base Color"])
    bs.inputs["Roughness"].default_value = 0.55
    try:
        bs.inputs["Subsurface Weight"].default_value = 0.0
        bs.inputs["Transmission Weight"].default_value = 0.0
    except Exception:
        pass
    return m


# ============================================================================ library + instancing
class Library:
    def __init__(self, coll, mats, lite=False, sfx=""):
        self.sfx = sfx
        self.coll = coll
        self.mats = mats
        self.summer = {}
        self.winter = {}
        L = lite
        mk = lambda ob: self._keep(ob)
        for key, H, R, sd in (("DFIR_L", 32, 4.8, 11), ("DFIR_M", 20, 3.8, 12), ("DFIR_S", 10, 2.6, 13)):
            ob = mk(proto_conifer(key + sfx, H, R, "fir", mats, sd, L))
            self.summer[key] = ob
            self.winter[key] = mk(self._snowy(ob, "fir_spray", "fir_spray_snow"))
        for key, H, R, sd in (("CEDAR_L", 26, 4.8, 21), ("CEDAR_S", 12, 3.0, 22)):
            ob = mk(proto_conifer(key + sfx, H, R, "cedar", mats, sd, L))
            self.summer[key] = ob
            self.winter[key] = mk(self._snowy(ob, "cedar_spray", "cedar_spray_snow"))
        for key, kind, H, R, sd in (("MAPLE_L", "maple", 17, 6.5, 31), ("MAPLE_S", "maple", 10, 4.2, 32),
                                    ("ALDER", "alder", 14, 4.0, 33), ("BIRCH", "birch", 12, 3.2, 34),
                                    ("CHERRY", "cherry", 6.5, 3.0, 35), ("JMAPLE", "jmaple", 4.0, 1.8, 36)):
            s, w = proto_decid(key + sfx, H, R, kind, mats, sd, L)
            self.summer[key] = mk(s)
            self.winter[key] = mk(w)
        thuja = mk(proto_blob("THUJA" + sfx, 0.6, 4.5, mats["dense_thuja"], ["arborvitae_spray"], mats, 41,
                              ncards=70 if L else 320, shape="column", cell_scale=0.8 if not L else 1.1))
        self.summer["THUJA"] = thuja
        self.winter["THUJA"] = thuja
        for key, R, H, core, cards, n, sd in (
                ("RHODO", 0.9, 1.7, "dense_rhodo", ["rhodo_cluster"], 230, 51),
                ("AZALEA", 0.55, 0.8, "dense_box", ["azalea_cluster"], 70, 52),
                ("BOXBALL", 0.45, 0.8, "dense_box", ["azalea_cluster"], 40, 53),
                ("LAURELSH", 1.0, 1.9, "dense_laurel", ["laurel_cluster"], 220, 54),
                ("GLOBE", 1.2, 2.2, "dense_thuja", ["arborvitae_spray"], 220, 55)):
            ob = mk(proto_blob(key + sfx, R, H, mats[core], cards, mats, sd, ncards=n // (3 if L else 1)))
            self.summer[key] = ob
            self.winter[key] = ob
        f = mk(proto_fern("FERN" + sfx, mats, 61))
        self.summer["FERN"] = f
        self.winter["FERN"] = f

    def _keep(self, ob):
        for c in list(ob.users_collection):
            c.objects.unlink(ob)
        self.coll.objects.link(ob)
        ob.hide_render = True
        ob.hide_viewport = True
        return ob

    def _snowy(self, ob, a, b):
        me = ob.data.copy()
        me.name = ob.data.name + "_snow"
        du, dv = cell_shift(a, b)
        uvl = me.uv_layers[0]
        uv = np.zeros(len(uvl.data) * 2, np.float32)
        uvl.data.foreach_get("uv", uv)
        uv = uv.reshape(-1, 2)
        ra = cell_uv(a)
        inside = (uv[:, 0] >= ra[0] - 1e-4) & (uv[:, 0] <= ra[2] + 1e-4) & (uv[:, 1] >= ra[1] - 1e-4) & (
            uv[:, 1] <= ra[3] + 1e-4)
        # only card faces use atlas coordinates in [0,1]; bark UVs are metres (often > 1)
        mats = [m.name for m in me.materials]
        loop_mat = np.zeros(len(uv), int)
        mi = np.zeros(len(me.polygons), int)
        me.polygons.foreach_get("material_index", mi)
        ls = np.zeros(len(me.polygons), int)
        me.polygons.foreach_get("loop_start", ls)
        lt = np.zeros(len(me.polygons), int)
        me.polygons.foreach_get("loop_total", lt)
        for p in range(len(mi)):
            loop_mat[ls[p]:ls[p] + lt[p]] = mi[p]
        fol_idx = [i for i, n in enumerate(mats) if n.startswith("FOL_")]
        sel = inside & np.isin(loop_mat, fol_idx)
        uv[sel, 0] += du
        uv[sel, 1] += dv
        uvl.data.foreach_set("uv", uv.ravel())
        nob = bpy.data.objects.new(ob.name + "_snow", me)
        nob["proto"] = ob.name + "_snow"
        return nob


def species_proto(t):
    sg = (t.get("species_guess") or "").lower()
    ty = t["type"]
    H = t["height_m"]
    rng = C.rng_for("sp", t["id"])
    if "arborvitae" in sg or "columnar" in sg:
        return "THUJA"
    if "globe" in sg or "dwarf" in sg or "rounded" in sg:
        return "GLOBE"
    if ty == "conifer":
        if "redcedar" in sg and "douglas" not in sg:
            return "CEDAR_L" if H > 14 else "CEDAR_S"
        if "spruce" in sg:
            return "DFIR_S"
        if "redcedar" in sg and rng.random() < 0.35:
            return "CEDAR_L" if H > 14 else "CEDAR_S"
        return "DFIR_L" if H > 22 else ("DFIR_M" if H > 13 else "DFIR_S")
    if "cherry" in sg:
        return "CHERRY"
    if "japanese maple" in sg or "red-leaf" in sg:
        return "JMAPLE"
    if ty == "ornamental":
        return "JMAPLE" if rng.random() < 0.4 else ("CHERRY" if H > 4 else "RHODO")
    if "shrub" in sg:
        return "LAURELSH"
    r = rng.random()
    if "maple" in sg and "alder" not in sg and "birch" not in sg:
        return "MAPLE_L" if H > 12 else "MAPLE_S"
    if r < 0.5:
        return "MAPLE_L" if H > 13 else "MAPLE_S"
    if r < 0.8:
        return "ALDER"
    return "BIRCH"


PROTO_HR = {"DFIR_L": (32, 4.8), "DFIR_M": (20, 3.8), "DFIR_S": (10, 2.6), "CEDAR_L": (26, 4.8),
            "CEDAR_S": (12, 3.0), "MAPLE_L": (17, 6.5), "MAPLE_S": (10, 4.2), "ALDER": (14, 4.0),
            "BIRCH": (12, 3.2), "CHERRY": (6.5, 3.0), "JMAPLE": (4.0, 1.8), "THUJA": (4.5, 0.6),
            "GLOBE": (2.2, 1.2), "RHODO": (1.7, 0.9), "AZALEA": (0.8, 0.55), "BOXBALL": (0.8, 0.45),
            "LAURELSH": (1.9, 1.0), "FERN": (0.8, 0.7)}
TRUNK_R = {"DFIR_L": 0.5, "DFIR_M": 0.34, "DFIR_S": 0.2, "CEDAR_L": 0.5, "CEDAR_S": 0.24, "MAPLE_L": 0.36,
           "MAPLE_S": 0.24, "ALDER": 0.26, "BIRCH": 0.2, "CHERRY": 0.15, "JMAPLE": 0.08, "THUJA": 0.3,
           "GLOBE": 0.5}


def instance(lib, key, x, y, H, R, coll, name, extras, rot=None, rng=None, z=None):
    ob0 = lib.summer[key]
    ob = bpy.data.objects.new(name, ob0.data)
    coll.objects.link(ob)
    zz = float(C.dtm().sample(x, y)) if z is None else z
    ob.location = (x, y, zz)
    rng = rng or np.random.default_rng()
    ob.rotation_euler = (0, 0, rot if rot is not None else rng.uniform(0, 2 * math.pi))
    h0, r0 = PROTO_HR[key]
    sz = H / h0
    sr = np.clip(R / r0, 0.6 * sz, 1.6 * sz)
    ob.scale = (sr, sr, sz)
    ob["proto"] = key
    ob["proto_winter"] = lib.winter[key].data.name
    ob["proto_summer"] = ob0.data.name
    for k, v in extras.items():
        if v is not None:
            ob[k] = v
    return ob


def plant_trees(lib, coll):
    T = C.data("trees")["trees"]
    houses = unary_union([Polygon(h["footprint_local"]["value"]) for h in C.data("houses")["houses"]])
    out = []
    for t in T:
        key = species_proto(t)
        H = float(t["height_m"])
        adj = False
        sg = (t.get("species_guess") or "").lower()
        if key.startswith(("DFIR", "CEDAR")) and H > 12 and ("douglas" in sg or "cedar" in sg or sg == "conifer"):
            H = min(36.0, H * 1.45)
            adj = True
            key = "DFIR_L" if (key.startswith("DFIR") and H > 22) else key
            key = "CEDAR_L" if (key.startswith("CEDAR") and H > 14) else key
        R = float(t["crown_radius_m"])
        if key == "THUJA":
            R = 0.6
        caps = {"GLOBE": 2.6, "RHODO": 2.6, "LAURELSH": 3.2, "JMAPLE": 4.5}
        if key in caps and H > caps[key]:
            H = caps[key]
            adj = True
        if key in ("GLOBE", "RHODO", "LAURELSH"):
            R = min(R, 1.6)
        rng = C.rng_for("tree", t["id"])
        x, y = t["x"], t["y"]
        # keep trunks off walls
        if houses.distance(Point(x, y)) < 0.8 and houses.contains(Point(x, y)):
            continue
        ob = instance(lib, key, x, y, H, R, coll, "Tree_%s_%s" % (t["id"], key),
                      dict(kind="tree", species=key, tree_id=t["id"], collide=True,
                           collide_radius=round(TRUNK_R.get(key, 0.2) * H / PROTO_HR[key][0], 2),
                           height_m=round(H, 1), height_adjusted=adj, height_source=t["height_source"],
                           evergreen=key.startswith(("DFIR", "CEDAR", "THUJA", "GLOBE"))), rng=rng)
        out.append(ob)
    return out


def hedges(lib, coll, mats):
    out = []
    for h in C.data("trees")["hedges"]:
        kind = h["kind"].lower()
        line = LineString(h["points"])
        H = float(h["height_m_est"])
        W = float(h["width_m"])
        if "arborvitae" in kind or "columnar" in kind:
            n = max(2, int(line.length / 0.95))
            for i in range(n + 1):
                p = line.interpolate(i / n, normalized=True)
                rng = C.rng_for("thuja", h["id"], i)
                hh = H * rng.uniform(0.88, 1.08)
                ob = instance(lib, "THUJA", p.x + rng.normal(0, 0.05), p.y + rng.normal(0, 0.05), hh, 0.6, coll,
                              "Hedge_%s_%02d" % (h["id"], i),
                              dict(kind="hedge", hedge_id=h["id"], collide=True, collide_radius=0.45), rng=rng)
                out.append(ob)
            continue
        # continuous clipped hedge: displaced extrusion + cards
        mat = mats["dense_laurel"] if ("laurel" in kind or "privet" in kind or "dense" in kind) else mats["dense_box"]
        cell = "laurel_cluster" if mat is mats["dense_laurel"] else "azalea_cluster"
        if "rounded shrubs" in kind or "mixed" in kind:
            mat, cell = mats["dense_rhodo"], "rhodo_cluster"
        mb = C.MeshBuilder()
        rng = C.rng_for("hedge", h["id"])
        pts, s = C.resample_line(h["points"], 0.5)
        nrm, tan = C.line_normals(pts)
        prof = [(-0.5, 0.0), (-0.5, 0.75), (-0.38, 0.95), (0.0, 1.0), (0.38, 0.95), (0.5, 0.75), (0.5, 0.0)]
        rows = []
        dtm = C.dtm()
        for i, p in enumerate(pts):
            g = float(dtm.sample(*p))
            ring = []
            for (a, b) in prof:
                jit = rng.normal(0, 0.05)
                q = p + nrm[i] * a * W * (1 + jit)
                ring.append((q[0], q[1], g - 0.1 + b * H * (1 + rng.normal(0, 0.03))))
            rows.append(mb.add_verts(ring))
        for i in range(len(pts) - 1):
            for k in range(len(prof) - 1):
                a, b = rows[i][k], rows[i][k + 1]
                c, d = rows[i + 1][k + 1], rows[i + 1][k]
                mb.face([a, d, c, b], [(s[i], k * 0.4), (s[i + 1], k * 0.4), (s[i + 1], (k + 1) * 0.4),
                                       (s[i], (k + 1) * 0.4)], mat, True)
        for end in (0, len(pts) - 1):
            ring = rows[end] if end else rows[0][::-1]
            mb.face(ring if end else ring, [(0, 0)] * len(ring), mat, True)
        # cards over the surface
        fol = mats["fol"]
        cw, ch = atlas()[cell]["size_m"]
        ncard = int(line.length * (H + W) * 3.0)
        for k in range(ncard):
            i = rng.uniform(0, len(pts) - 1)
            j = int(i)
            f = i - j
            p = pts[j] * (1 - f) + pts[min(j + 1, len(pts) - 1)] * f
            nn = nrm[j]
            side = rng.choice([-1, 1])
            zf = rng.uniform(0.1, 1.0)
            g = float(dtm.sample(*p))
            base = np.array([p[0] + nn[0] * side * W * 0.45, p[1] + nn[1] * side * W * 0.45, g + zf * H * 0.97])
            outv = np.array([nn[0] * side, nn[1] * side, rng.uniform(-0.2, 1.0) + (1.5 if zf > 0.92 else 0)])
            sc = rng.uniform(0.7, 1.1)
            add_card(mb, fol, cell, base, outv, _rot(_perp(outv), outv / np.linalg.norm(outv), rng.uniform(0, 6.3)),
                     cw * sc, ch * sc)
        ob = mb.emit("Hedge_%s" % h["id"], coll)
        C.set_extras(ob, kind="hedge", hedge_id=h["id"], collide=True, height_m=H, note=h["kind"])
        out.append(ob)
    return out


def shrubs(lib, coll, ground, avoid_polys, n_max=900):
    """Foundation planting / beds: rhododendron, azalea, boxwood, laurel, ferns where the ground-cover
    splat says mulch near the Canby Ct houses; sword ferns in the greenbelt edge."""
    rng = C.rng_for("shrubs")
    sp = ground.splat
    houses = [Polygon(h["footprint_local"]["value"]) for h in C.data("houses")["houses"]]
    H = unary_union(houses)
    trees = [(t["x"], t["y"]) for t in C.data("trees")["trees"]]
    avoid = unary_union(avoid_polys)
    xs = np.arange(-125, 30, 1.25)
    ys = np.arange(-95, 40, 1.25)
    X, Y = np.meshgrid(xs, ys)
    X = X.ravel() + rng.uniform(-0.5, 0.5, X.size)
    Y = Y.ravel() + rng.uniform(-0.5, 0.5, Y.size)
    w = sp.sample(X, Y)
    pts = shapely.points(X, Y)
    dH = shapely.distance(H, pts)
    inav = shapely.contains_xy(avoid.buffer(0.6), X, Y)
    TT = np.array(trees)
    dT = np.min(np.hypot(X[:, None] - TT[None, :, 0], Y[:, None] - TT[None, :, 1]), 1)
    out = []
    cnt = 0
    for i in np.argsort(rng.random(X.size)):
        if cnt >= n_max:
            break
        x, y = X[i], Y[i]
        if inav[i] or dT[i] < 1.2:
            continue
        mulch, forest = w[i, 1], w[i, 2]
        if dH[i] < 0.9:
            continue
        if mulch > 0.55 and dH[i] < 9:
            r = rng.random()
            key = "RHODO" if r < 0.32 else "AZALEA" if r < 0.58 else "BOXBALL" if r < 0.72 else \
                "LAURELSH" if r < 0.82 else "FERN"
        elif forest > 0.6 and rng.random() < 0.35:
            key = "FERN" if rng.random() < 0.7 else "LAURELSH"
        else:
            continue
        h0, r0 = PROTO_HR[key]
        s = rng.uniform(0.75, 1.25)
        ob = instance(lib, key, x, y, h0 * s, r0 * s, coll, "Shrub_%04d_%s" % (cnt, key),
                      dict(kind="shrub", species=key, collide=False), rng=rng)
        out.append(ob)
        cnt += 1
    return out


def grass_zone(ground_obj, cams, coll, lib_coll, mats, radius=34.0, density=700):
    """Cycles only: particle-instanced grass clumps on lawn triangles near the hero cameras."""
    me = ground_obj.data
    n = len(me.polygons)
    cen = np.zeros(n * 3, np.float32)
    me.polygons.foreach_get("center", cen)
    cen = cen.reshape(-1, 3)
    mi = np.zeros(n, int)
    me.polygons.foreach_get("material_index", mi)
    near = np.zeros(n, bool)
    for c in cams:
        near |= np.hypot(cen[:, 0] - c[0], cen[:, 1] - c[1]) < radius
    sel = near & (mi == 0)
    idx = np.where(sel)[0]
    if len(idx) == 0:
        return None
    verts = np.zeros(len(me.vertices) * 3, np.float32)
    me.vertices.foreach_get("co", verts)
    verts = verts.reshape(-1, 3)
    faces = [list(me.polygons[i].vertices) for i in idx]
    used = sorted(set(v for f in faces for v in f))
    remap = {v: k for k, v in enumerate(used)}
    V = verts[used]
    F = [[remap[v] for v in f] for f in faces]
    # lawn weight per vertex for density
    col = me.color_attributes.get("splat")
    lw = np.zeros(len(me.vertices) * 4, np.float32)
    col.data.foreach_get("color", lw)
    lw = lw.reshape(-1, 4)[used, 0]
    ob = C.mesh_from_data("Grass_Zone", V + np.array([0, 0, -0.005]), F, coll=coll)
    vg = ob.vertex_groups.new(name="lawn")
    for k, wv in enumerate(lw):
        vg.add([k], float(np.clip((wv - 0.35) / 0.4, 0, 1)), "REPLACE")
    clumps = bpy.data.collections.get("GrassClumps") or bpy.data.collections.new("GrassClumps")
    if "GrassClumps" not in [c.name for c in lib_coll.children]:
        lib_coll.children.link(clumps)
    for k in range(6):
        g = proto_grass_clump("GrassClump_%d" % k, mats, 70 + k, n=16, h=[0.07, 0.09, 0.11, 0.08, 0.13, 0.1][k])
        for c in list(g.users_collection):
            c.objects.unlink(g)
        clumps.objects.link(g)
    area = sum(me.polygons[i].area for i in idx)
    ps = ob.modifiers.new("grass", "PARTICLE_SYSTEM").particle_system
    st = ps.settings
    st.type = "HAIR"
    st.use_advanced_hair = True
    st.count = int(area * density)
    st.hair_length = 1.0
    st.emit_from = "FACE"
    st.distribution = "RAND"
    st.render_type = "COLLECTION"
    st.instance_collection = clumps
    st.use_collection_pick_random = True
    st.particle_size = 1.0
    st.size_random = 0.45
    st.use_rotations = True
    st.rotation_mode = "GLOB_Z"
    st.phase_factor_random = 2.0
    ps.vertex_group_density = "lawn"
    ps.seed = 3
    ob["render_only"] = True
    ob["web_export"] = False
    print("   grass instances", st.count, "area %.0f m2" % area)
    return ob
