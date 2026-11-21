"""Short haircut, eyebrows and eyelashes.

Hi-res (Cycles): real hair curves (Principled Hair BSDF), bone-parented to the head.
Web: a hair 'cap' shell + brow cards + lash strips sharing one 1024 RGBA atlas.
The atlas is rasterised from the *same* strands that the hi-res curves use, so
both versions match.
"""
import math
import numpy as np
import bpy
from PIL import Image, ImageDraw, ImageFilter

import geo
from garments import Shell, smoothstep

HAIR_ROOT = np.array([0.045, 0.030, 0.018])     # linear albedo of the hair (dark ash brown)
HAIR_TIP = np.array([0.075, 0.050, 0.030])

# atlas rects (u0, v0, u1, v1)
R_CAP = (0.0, 0.5, 1.0, 1.0)
R_BROW = (0.0, 0.25, 0.5, 0.5)
R_LASH_UP = (0.5, 0.375, 1.0, 0.5)
R_LASH_LO = (0.5, 0.25, 1.0, 0.375)


class HeadFrame:
    def __init__(self, bd, eyes_ob, landmarks):
        self.E = (landmarks["eye_l"] + landmarks["eye_r"]) / 2
        self.C = self.E + np.array([0, 0.085, 0.015])   # approx skull centre
        self.crown = self.C + np.array([0, 0.045, 0.085])
        self.hd = landmarks["head"]

    def azim(self, p):
        """0 = front, +pi/2 = character's left, +-pi = back."""
        return np.arctan2(p[:, 0] - self.C[0], -(p[:, 1] - self.C[1]))

    def hairline(self, phi):
        a = np.abs(np.degrees(phi))
        E = self.E[2]
        pts = [(0, E + 0.074), (22, E + 0.078), (34, E + 0.084), (48, E + 0.050), (60, E + 0.022),
               (68, E - 0.028), (74, E - 0.024), (82, E + 0.030), (100, E + 0.038), (114, E + 0.012),
               (128, E - 0.045), (150, E - 0.078), (180, E - 0.086)]
        xs = np.array([p[0] for p in pts])
        ys = np.array([p[1] for p in pts])
        return np.interp(a, xs, ys)


def cap_v(p, hf):
    phi = hf.azim(p)
    hl = hf.hairline(phi) - 0.014
    hmax = (hf.crown[2] + 0.02) - hl
    return np.clip((p[:, 2] - hl) / hmax, 0, 1)


def scalp_mask(bd, hf, margin=0.0):
    headw = bd.w("head")
    phi = hf.azim(bd.co)
    return (headw > 0.5) & (bd.co[:, 2] > hf.hairline(phi) - margin)


# ------------------------------------------------------------------ strands
def gen_strands(bd, hf, n=40000, k=7, seed=1, cap_only_heights=None):
    rng = np.random.default_rng(seed)
    m = scalp_mask(bd, hf)
    faces = [f for f in bd.faces if m[f].all()]
    tris = []
    for f in faces:
        for i in range(1, len(f) - 1):
            tris.append((f[0], f[i], f[i + 1]))
    tris = np.array(tris)
    P = bd.co
    a, b, c = P[tris[:, 0]], P[tris[:, 1]], P[tris[:, 2]]
    area = 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1)
    pick = rng.choice(len(tris), n, p=area / area.sum())
    r1, r2 = rng.random(n), rng.random(n)
    s = np.sqrt(r1)
    roots = a[pick] * (1 - s)[:, None] + b[pick] * (s * (1 - r2))[:, None] + c[pick] * (s * r2)[:, None]
    nrm = np.cross(b - a, c - a)[pick]
    nrm /= np.linalg.norm(nrm, axis=1, keepdims=True)
    phi = hf.azim(roots)
    hl = hf.hairline(phi)
    above = roots[:, 2] - hl
    keep = rng.random(n) < np.clip((above + 0.002) / 0.014, 0.12, 1.0)
    roots, nrm, phi, hl, above = roots[keep], nrm[keep], phi[keep], hl[keep], above[keep]
    n = len(roots)
    edge = np.clip(above / 0.035, 0, 1) ** 0.8               # thinner/shorter at the hairline
    top = smoothstep(hf.E[2] + 0.06, hf.E[2] + 0.12, roots[:, 2])
    side = np.clip((np.abs(np.degrees(phi)) - 35) / 25, 0, 1) * np.clip((150 - np.abs(np.degrees(phi))) / 30, 0, 1)
    L = (0.012 + 0.035 * top * (1 - 0.45 * side)) * (0.35 + 0.65 * edge) * rng.uniform(0.8, 1.2, n)
    # flow: away from the crown, tangential; front-top hair pushed forward and to the side (part)
    f = roots - hf.crown
    f -= nrm * np.sum(f * nrm, 1, keepdims=True)
    f /= np.maximum(np.linalg.norm(f, axis=1, keepdims=True), 1e-9)
    side_sweep = np.array([1.0, 0, 0]) * (0.35 * top)[:, None]
    f = f + side_sweep
    f -= nrm * np.sum(f * nrm, 1, keepdims=True)
    f /= np.maximum(np.linalg.norm(f, axis=1, keepdims=True), 1e-9)
    f += rng.normal(0, 0.18, f.shape)
    lift = (0.20 + 0.35 * top) * rng.uniform(0.6, 1.2, n)
    R0 = np.linalg.norm(roots - hf.C, axis=1)
    strands = np.zeros((n, k, 3))
    for j in range(k):
        t = j / (k - 1)
        h = L * (lift * np.sin(t * math.pi * 0.5) * 0.9 * (1 - 0.25 * t)) * 0.62
        p = roots + f * (L * t)[:, None]
        # keep on the skull: re-project radially to R0 + height
        d = p - hf.C
        dn = d / np.linalg.norm(d, axis=1, keepdims=True)
        p = hf.C + dn * (R0 + h + 0.0008)[:, None]
        # slight wave
        p += rng.normal(0, 0.0006, (n, 3)) * t
        strands[:, j] = p
    return dict(pts=strands, roots=roots, nrm=nrm, L=L, phi=phi, above=above)


def curves_object(name, strands, collection, r_root=0.00005, r_tip=0.00002):
    pts = strands["pts"]
    n, k, _ = pts.shape
    cu = bpy.data.hair_curves.new(name)
    cu.add_curves([k] * n)
    cu.position_data.foreach_set("vector", pts.reshape(-1).astype(np.float32))
    rad = cu.attributes.get("radius") or cu.attributes.new("radius", "FLOAT", "POINT")
    r = np.tile(np.linspace(r_root, r_tip, k), n).astype(np.float32)
    rad.data.foreach_set("value", r)
    ob = bpy.data.objects.new(name, cu)
    collection.objects.link(ob)
    return ob


def hair_bsdf_material(name="HairStrands", melanin=0.83, redness=0.3):
    from materials import new_material
    m, b = new_material(name)
    h = b.n("ShaderNodeBsdfHairPrincipled", loc=(900, 0), _parametrization="MELANIN")
    h.inputs["Melanin"].default_value = melanin
    h.inputs["Melanin Redness"].default_value = redness
    h.inputs["Roughness"].default_value = 0.32
    h.inputs["Radial Roughness"].default_value = 0.5
    info = b.n("ShaderNodeHairInfo")
    rnd = b.math("MULTIPLY", info.outputs["Random"], 0.25)
    b.set(h.inputs["Random Color"], 0.12)
    b.set(h.inputs["Random Roughness"], 0.15)
    b.link(h.outputs[0], b.out.inputs["Surface"])
    return m


# ------------------------------------------------------------------ cap (web + under-layer in hi-res)
def cap_mesh(bd, hf, collection, strands, scale=1.0, name="Hair_Cap"):
    m = scalp_mask(bd, hf, margin=0.012)
    # grow the region by one ring so the cap edge sits under the fading hairline
    sh = Shell(bd, m, name)
    sh.smooth(4)
    phi = hf.azim(sh.co)
    top = smoothstep(hf.E[2] + 0.06, hf.E[2] + 0.12, sh.co[:, 2])
    above = sh.co[:, 2] - hf.hairline(phi)
    off = 0.0006 + (0.002 + 0.009 * top) * np.clip(above / 0.02, 0.0, 1) * scale
    sh.offset(off)
    sh.smooth(2)
    ob = sh.to_object(collection)
    # atlas UV: u = azimuth, v = height above hairline (normalised, 0 hairline .. 1 crown)
    me = ob.data
    co, faces, _ = geo.mesh_arrays(ob)
    phi = hf.azim(co)
    v = cap_v(co, hf)
    u = (phi + np.pi) / (2 * np.pi)
    lu = []
    for f in faces:
        us = u[f].copy()
        if us.max() - us.min() > 0.5:      # seam at the back
            us[us < 0.5] += 1.0
        for i, vi in enumerate(f):
            lu.append((us[i], v[vi]))
    lu = np.array(lu)
    x0, y0, x1, y1 = R_CAP
    # wrap u>1 back by duplicating texture horizontally (texture is periodic)
    lu[:, 0] = x0 + (lu[:, 0] % 1.0000001) * (x1 - x0) * 0.999
    # fix wrap for faces that straddled: keep them contiguous by allowing u>1 (sampler repeats) ->
    # we use clamp-safe approach: faces crossing the seam take the duplicated column at u in [1,1.02]
    uvl = me.uv_layers.new(name="UVMap")
    uvl.data.foreach_set("uv", (lu * [1, 1]).astype(np.float32).ravel())
    k = 0
    data = []
    for f in faces:
        us = u[f].copy()
        straddle = us.max() - us.min() > 0.5
        for i, vi in enumerate(f):
            uu = us[i]
            if straddle and uu < 0.5:
                uu += 1.0
            data.append((x0 + uu * (x1 - x0) * 0.98, y0 + v[vi] * (y1 - y0)))
    uvl.data.foreach_set("uv", np.array(data, dtype=np.float32).ravel())
    me.uv_layers.active = uvl
    return ob


def rasterize_cap(strands, hf, size=1024, ss=2):
    """Draw strands into the cap region (u=azimuth, v=height above hairline)."""
    W, H = size * ss, int(size * (R_CAP[3] - R_CAP[1])) * ss
    col = Image.new("RGB", (W, H), tuple(int(255 * c ** (1 / 2.2)) for c in HAIR_ROOT * 0.8))
    alpha = Image.new("L", (W, H), 0)
    hgt = Image.new("L", (W, H), 0)
    dc, da, dh = ImageDraw.Draw(col), ImageDraw.Draw(alpha), ImageDraw.Draw(hgt)
    pts = strands["pts"]
    n, k, _ = pts.shape
    rng = np.random.default_rng(7)
    P = pts.reshape(-1, 3)
    phi = hf.azim(P)
    v = cap_v(P, hf).reshape(n, k)
    u = ((phi + np.pi) / (2 * np.pi)).reshape(n, k)
    order = np.argsort(rng.random(n))
    for i in order:
        uu = u[i] * W * 0.98 / 0.98
        if uu.max() - uu.min() > W / 2:
            continue
        vv = (1 - v[i]) * H
        shade = rng.uniform(0.75, 1.35)
        c = np.clip((HAIR_ROOT * shade) ** (1 / 2.2) * 255, 0, 255)
        ct = np.clip((HAIR_TIP * shade) ** (1 / 2.2) * 255, 0, 255)
        for j in range(k - 1):
            t = j / (k - 2)
            cc = tuple(int(x) for x in c * (1 - t) + ct * t)
            seg = [(uu[j] * 0.98, vv[j]), (uu[j + 1] * 0.98, vv[j + 1])]
            dc.line(seg, fill=cc, width=ss)
            da.line(seg, fill=255, width=ss)
            dh.line(seg, fill=int(120 + 120 * rng.random()), width=ss)
    alpha = alpha.filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.GaussianBlur(ss))
    col = col.resize((W // ss, H // ss), Image.LANCZOS)
    alpha = alpha.resize((W // ss, H // ss), Image.LANCZOS)
    hgt = hgt.filter(ImageFilter.GaussianBlur(ss * 0.7)).resize((W // ss, H // ss), Image.LANCZOS)
    return col, alpha, hgt


# ------------------------------------------------------------------ brows
def brow_curve(hf, sx):
    """Points along the brow (inner -> tail) on the brow ridge, left (sx=1) / right (-1)."""
    E = hf.E
    eye_x = abs(hf_eye_x(hf))
    xs = np.array([0.011, 0.020, 0.032, 0.044, 0.054, 0.062])
    zs = E[2] + np.array([0.021, 0.0245, 0.0265, 0.0265, 0.0245, 0.019])
    widths = np.array([0.009, 0.0095, 0.0085, 0.007, 0.005, 0.003])
    return np.stack([sx * xs, np.zeros_like(xs), zs], 1), widths


def hf_eye_x(hf):
    return hf.eye_x if hasattr(hf, "eye_x") else 0.032


def project_to_surface(pts, bd, maxd=0.2):
    """Project points along -Y (front) onto the body surface: nearest vertex in xz with min y."""
    from scipy.spatial import cKDTree
    head = bd.w("head") > 0.5
    front = head & (bd.co[:, 1] < bd.co[head][:, 1].min() + 0.06)
    P = bd.co[front]
    t = cKDTree(P[:, [0, 2]])
    d, idx = t.query(pts[:, [0, 2]], k=6)
    w = 1 / (d + 1e-5)
    y = np.sum(P[idx][:, :, 1] * w, 1) / w.sum(1)
    out = pts.copy()
    out[:, 1] = y
    return out


def brow_strands(bd, hf, n_per=1000, seed=3):
    rng = np.random.default_rng(seed)
    all_pts = []
    meta = []
    for sx in (1, -1):
        cpts, widths = brow_curve(hf, sx)
        for i in range(n_per):
            t = rng.random() ** 0.9
            idx = t * (len(cpts) - 1)
            i0 = min(int(idx), len(cpts) - 2)
            fr = idx - i0
            c = cpts[i0] * (1 - fr) + cpts[i0 + 1] * fr
            w = widths[i0] * (1 - fr) + widths[i0 + 1] * fr
            off = np.clip(rng.normal(0, 0.28), -0.5, 0.5) * w
            root = c + np.array([0, 0, off])
            # direction: inner hairs point up, then sweep outward and slightly down at the tail
            ang = np.radians(80 - 75 * t ** 0.6 + rng.normal(0, 8) - 10 * max(t - 0.7, 0) / 0.3)
            d = np.array([sx * math.cos(ang), 0, math.sin(ang)])
            L = 0.0055 + 0.003 * rng.random()
            seg = [root + d * L * s + np.array([0, 0, -0.0012 * s * s * (1 if t > 0.3 else 0)]) for s in np.linspace(0, 1, 4)]
            all_pts.append(seg)
            meta.append((sx, t))
    pts = np.array(all_pts)
    flat = pts.reshape(-1, 3)
    proj = project_to_surface(flat, bd)
    proj[:, 1] -= 0.0007
    pts = proj.reshape(pts.shape)
    # lift the tips a hair off the skin
    pts[:, 1:, 1] -= np.linspace(0.0, 0.0008, pts.shape[1] - 1)[None, :]
    return dict(pts=pts, meta=meta)


def brow_cards(bd, hf, collection):
    """Two quad strips following the brow, slightly in front of the skin; UVs into R_BROW."""
    verts, faces, uvs = [], [], []
    for sx in (1, -1):
        cpts, widths = brow_curve(hf, sx)
        # extend a little beyond the hair area
        nseg = 12
        tt = np.linspace(-0.04, 1.04, nseg + 1)
        base = len(verts)
        for j, t in enumerate(tt):
            idx = np.clip(t, 0, 1) * (len(cpts) - 1)
            i0 = min(int(idx), len(cpts) - 2)
            fr = idx - i0
            c = cpts[i0] * (1 - fr) + cpts[i0 + 1] * fr
            c = c + (cpts[-1] - cpts[0]) * (t - np.clip(t, 0, 1))
            for side in (-1, 1):
                p = c + np.array([0, 0, side * 0.011])
                verts.append(p)
        vv = np.array(verts[base:])
        vv = project_to_surface(vv, bd)
        vv[:, 1] -= 0.0012
        verts[base:] = list(vv)
        for j in range(nseg):
            a = base + j * 2
            if sx > 0:
                faces.append([a, a + 2, a + 3, a + 1])
            else:
                faces.append([a, a + 1, a + 3, a + 2])
            for (jj, s) in ([(j, 0), (j + 1, 0), (j + 1, 1), (j, 1)] if sx > 0 else [(j, 0), (j, 1), (j + 1, 1), (j + 1, 0)]):
                u = (tt[jj] + 0.04) / 1.08
                uvs.append((R_BROW[0] + u * (R_BROW[2] - R_BROW[0]), R_BROW[1] + s * (R_BROW[3] - R_BROW[1])))
    ob = geo.make_object("Brows", np.array(verts), faces, collection, uv_loops=np.array(uvs))
    return ob


def rasterize_brows(bs, hf, size=1024, ss=3):
    W = int(size * (R_BROW[2] - R_BROW[0])) * ss
    H = int(size * (R_BROW[3] - R_BROW[1])) * ss
    col = Image.new("RGB", (W, H), (40, 30, 22))
    al = Image.new("L", (W, H), 0)
    dc, da = ImageDraw.Draw(col), ImageDraw.Draw(al)
    rng = np.random.default_rng(11)
    cpts, _ = brow_curve(hf, 1)
    for strand, (sx, t) in zip(bs["pts"], bs["meta"]):
        if sx < 0:
            continue
        # card param: along = projection on brow polyline t, across = z offset relative to curve
        uvp = []
        for p in strand:
            q = p.copy()
            # nearest param along polyline
            best = None
            for i in range(len(cpts) - 1):
                a, b = cpts[i], cpts[i + 1]
                ab = (b - a)[[0, 2]]
                ap = (q - a)[[0, 2]]
                s = np.clip(ap @ ab / (ab @ ab), 0, 1)
                d = np.linalg.norm(ap - s * ab)
                if best is None or d < best[0]:
                    sign = np.sign(ab[0] * ap[1] - ab[1] * ap[0])
                    best = (d, (i + s) / (len(cpts) - 1), sign * d)
            u = (best[1] + 0.04) / 1.08
            v = 0.5 + best[2] / 0.022
            uvp.append((u * W, (1 - v) * H))
        shade = rng.uniform(0.7, 1.3)
        c = tuple(int(x) for x in np.clip((HAIR_ROOT * 0.8 * shade) ** (1 / 2.2) * 255, 0, 255))
        dc.line(uvp, fill=c, width=max(1, ss - 1))
        da.line(uvp, fill=230, width=max(1, ss - 1))
    col = col.resize((W // ss, H // ss), Image.LANCZOS)
    al = al.filter(ImageFilter.GaussianBlur(0.6)).resize((W // ss, H // ss), Image.LANCZOS)
    return col, al


# ------------------------------------------------------------------ lashes
def lash_mesh(d, collection):
    """Eyelash strips from the MakeHuman eyelash helper geometry (upper = *-2, lower = *-1)."""
    import mh_base as mh
    co = d["co"]
    verts, faces, uvs = [], [], []
    vmap = {}
    for (f, g) in d["lash_faces"]:
        upper = g.endswith("-2")
        rect = R_LASH_UP if upper else R_LASH_LO
        fidx = []
        for vi in f:
            key = (vi, upper)
            if key not in vmap:
                vmap[key] = len(verts)
                verts.append(co[vi])
            fidx.append(vmap[key])
        faces.append((fidx, upper, g))
    verts = np.array(verts)
    # UV: u = x across the eye (per side), v = distance from the lid (lowest-z ring = 0)
    out_f, out_uv = [], []
    groups = {}
    for fidx, upper, g in faces:
        groups.setdefault(g, []).append(fidx)
    for g, fl in groups.items():
        upper = g.endswith("-2")
        rect = R_LASH_UP if upper else R_LASH_LO
        vs = sorted(set(i for f in fl for i in f))
        P = verts[vs]
        xs = P[:, 0]
        x0, x1 = xs.min(), xs.max()
        # attachment edge: for each vertex, v by height relative to the strip centre line
        cz = P[:, 2].mean()
        zr = P[:, 2].max() - P[:, 2].min()
        for f in fl:
            out_f.append(f)
            for i in f:
                u = (verts[i, 0] - x0) / max(x1 - x0, 1e-6)
                if verts[i, 0] < 0:
                    u = 1 - u
                rel = (verts[i, 2] - P[:, 2].min()) / max(zr, 1e-6)
                v = rel if upper else 1 - rel
                out_uv.append((rect[0] + u * (rect[2] - rect[0]), rect[1] + v * (rect[3] - rect[1])))
    ob = geo.make_object("Lashes", verts, out_f, collection, uv_loops=np.array(out_uv))
    return ob


def rasterize_lashes(size=1024, ss=3, upper=True):
    W = int(size * 0.5) * ss
    H = int(size * 0.125) * ss
    col = Image.new("RGB", (W, H), (18, 14, 12))
    al = Image.new("L", (W, H), 0)
    da = ImageDraw.Draw(al)
    rng = np.random.default_rng(5 if upper else 6)
    n = 110 if upper else 60
    for i in range(n):
        u = rng.uniform(0.04, 0.96)
        dens = 1 - abs(u - 0.55) * 0.8
        if rng.random() > dens:
            continue
        L = (0.75 if upper else 0.45) * (0.6 + 0.4 * math.sin(math.pi * u)) * rng.uniform(0.8, 1.1)
        lean = (u - 0.5) * 0.25 + rng.normal(0, 0.03)
        pts = []
        for s in np.linspace(0, 1, 6):
            x = (u + lean * s * s) * W
            y = H - s * L * H
            pts.append((x, y))
        da.line(pts, fill=255, width=ss)
    al = al.filter(ImageFilter.GaussianBlur(0.8)).resize((W // ss, H // ss), Image.LANCZOS)
    return col.resize((W // ss, H // ss)), al


def build_atlas(cap, brows, lash_up, lash_lo, size=1024):
    col = Image.new("RGB", (size, size), tuple(int(255 * c ** (1 / 2.2)) for c in HAIR_ROOT))
    al = Image.new("L", (size, size), 0)
    hgt = Image.new("L", (size, size), 0)

    def paste(img, a, rect, h=None):
        x0, y0, x1, y1 = rect
        box = (int(x0 * size), int((1 - y1) * size))
        img = img.resize((int((x1 - x0) * size), int((y1 - y0) * size)))
        a = a.resize(img.size)
        col.paste(img, box)
        al.paste(a, box)
        if h is not None:
            hgt.paste(h.resize(img.size), box)
    paste(cap[0], cap[1], R_CAP, cap[2])
    paste(brows[0], brows[1], R_BROW)
    paste(lash_up[0], lash_up[1], R_LASH_UP)
    paste(lash_lo[0], lash_lo[1], R_LASH_LO)
    rgba = col.copy()
    rgba.putalpha(al)
    # normal map from height (strand relief)
    h = np.asarray(hgt, dtype=np.float32) / 255.0
    gx = np.roll(h, -1, 1) - np.roll(h, 1, 1)
    gy = np.roll(h, -1, 0) - np.roll(h, 1, 0)
    nz = np.ones_like(h)
    n = np.stack([-gx * 2.0, gy * 2.0, nz], -1)
    n /= np.linalg.norm(n, axis=-1, keepdims=True)
    nimg = Image.fromarray(((n * 0.5 + 0.5) * 255).astype(np.uint8))
    return rgba, nimg


def card_material(name, rgba_path, normal_path=None, rough=0.45, clip=0.35, sheen=0.0):
    from materials import new_material
    m, b = new_material(name)
    t = b.n("ShaderNodeTexImage")
    t.image = bpy.data.images.load(rgba_path, check_existing=True)
    b.set(t.inputs["Vector"], b.uv("UVMap"))
    kw = {"Base Color": t.outputs["Color"], "Alpha": t.outputs["Alpha"], "Roughness": rough,
          "Sheen Weight": sheen, "Specular IOR Level": 0.35}
    if normal_path:
        nt = b.n("ShaderNodeTexImage")
        nt.image = bpy.data.images.load(normal_path, check_existing=True)
        nt.image.colorspace_settings.name = "Non-Color"
        b.set(nt.inputs["Vector"], b.uv("UVMap"))
        nm = b.n("ShaderNodeNormalMap")
        b.set(nm.inputs["Color"], nt.outputs["Color"])
        nm.inputs["Strength"].default_value = 0.6
        kw["Normal"] = nm.outputs[0]
    b.principled(**kw)
    m.blend_method = "CLIP" if hasattr(m, "blend_method") else None
    try:
        m.surface_render_method = "DITHERED"
    except Exception:
        pass
    m["gltf_alpha_cutoff"] = clip
    return m
