"""Canby Court PNW texture library: real-scale procedural surfaces -> baked albedo / normal / ORM (numpy only).

Every generator models the physical object at real scale (shingle exposures, board widths, groove spacings,
aggregate sizes in metres), builds a height field in metres + an albedo, and derives tangent-space normals
(OpenGL) and AO from the height field (texcore.finish_height).

Colour convention: building-envelope materials (roof shingles, sidings, trim, garage/front doors, deck) are
baked NEUTRAL (light, near-white or grey) and tinted per house by the material colour factor from
data/facades.json (Blender: multiply node; glTF: baseColorFactor). Ground/vegetation sets are baked in colour.

Run:  /home/user/venv/bin/python blender/texlib_pnw.py [names...]
Writes blender/textures/<set>_{albedo,normal,orm}.{jpg,png} (Cycles, up to 2048) and
web/assets/tex/<set>_*.jpg (<= 1024, shared by both season GLBs) + library.json in both dirs.
"""
import math
import os
import sys
import time

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from texcore import (blur, blur_aniso, cells, fnoise, finish_height, height_to_normal, ao_from_height, hexc, lerp,
                     renorm, resize, smooth, warp, write_set, raster, to8, TEX_BL, TEX_WEB, _lib_update, LIB_JSON_BL,
                     LIB_JSON_WEB, save_img)

HI = 2048
MID = 1024
LO = 512


def uv_grid(res_w, res_h, size_m):
    """Pixel-centre coordinates in metres: u to the right, v UP (row 0 = top = v max)."""
    u = (np.arange(res_w) + 0.5) / res_w * size_m[0]
    v = (np.arange(res_h)[::-1] + 0.5) / res_h * size_m[1]
    return np.meshgrid(u, v)


def per_id(ids, n, seed, lo=0.0, hi=1.0):
    r = np.random.default_rng(seed).uniform(lo, hi, n + 1)
    return r[np.clip(ids, 0, n)]


def tint(base_hex, var, seed, shape, lo=1.0, hi=None):
    n = fnoise(shape, lo, hi, seed=seed)
    return hexc(base_hex)[None, None, :] * (1 + var * n)[..., None]


# ============================================================================ ROOF
def roof_arch_shingle(name="roof_arch_shingle", size=2.0, res=HI, seed=3):
    """Architectural (laminated) asphalt shingle: 14 courses x 0.1429 m exposure (5-5/8"), strips 1.0 m
    (39-3/8") with random-width tabs (dragon teeth) over a darker base layer; ceramic granule speckle;
    faint PNW algae streaks. Neutral grey; tinted per house."""
    rng = np.random.default_rng(seed)
    W = H = res
    px = size / res
    U, V = uv_grid(W, H, (size, size))
    ncourse = 14
    exp_m = size / ncourse
    course = np.floor(V / exp_m).astype(int)
    fv = V / exp_m - course                       # 0 at butt (bottom) .. 1 at top of exposure
    # per course: strip offset + tab boundaries
    hm = np.zeros((H, W), np.float32)
    lum = np.zeros((H, W), np.float32)
    tab_id = np.zeros((H, W), np.int32)
    is_tab = np.zeros((H, W), bool)
    for c in range(ncourse):
        m = course == c
        if not m.any():
            continue
        u = U[m]
        off = rng.uniform(0, size)
        # tab edges: random widths 0.10..0.32 m, periodic over `size`
        edges = [0.0]
        while edges[-1] < size:
            edges.append(edges[-1] + rng.uniform(0.10, 0.32))
        edges = np.array(edges) * size / edges[-1]
        uu = (u + off) % size
        k = np.searchsorted(edges, uu) - 1
        # every tab has a slightly different exposure (laminate depth) and some gaps ("dragon teeth")
        n_t = len(edges)
        tab_lum = rng.normal(0.0, 0.03, n_t)
        shadow = rng.random(n_t) < 0.55
        f = fv[m]
        # dragon-teeth gaps: narrow cut-outs that show the darker base layer
        gpos = rng.uniform(0.2, 0.8, n_t)
        gw = np.where(rng.random(n_t) < 0.45, rng.uniform(0.025, 0.07, n_t), 0.0)
        rel = uu - edges[k]
        thick = np.abs(rel - gpos[k] * (edges[k + 1] - edges[k])) > gw[k] / 2
        ein = np.minimum(uu - edges[k], edges[k + 1] - uu)
        thick &= ein > 0.003
        h = np.where(thick, 0.0032, 0.0) + 0.0035 * (1 - f)          # laminate + strip taper
        hm[m] = h
        sb = np.where(shadow[k] & (f < 0.3), -0.07 * (1 - f / 0.3), 0.0)
        lum[m] = np.where(thick, tab_lum[k] + sb, -0.14)
        tab_id[m] = c * 100 + k
        is_tab[m] = thick
        # strip end joints (every 1.0 m)
        sj = (u + off * 0.37) % 1.0
        joint = (sj < 0.003)
        hm[m] = np.where(joint, -0.002, hm[m])
    # butt edge step shadow: near f=0 of course above -> darker line
    butt = smooth(0.0, 0.05, fv)
    # granules: high-frequency speckle
    g1 = fnoise((H, W), lo=200, hi=None, beta=0.0, seed=seed + 1)
    g2 = fnoise((H, W), lo=60, hi=500, beta=1.0, seed=seed + 2)
    dark_gran = (fnoise((H, W), lo=300, beta=0.0, seed=seed + 3) > 2.0).astype(np.float32)
    light_gran = (fnoise((H, W), lo=300, beta=0.0, seed=seed + 4) > 2.2).astype(np.float32)
    streak = blur_aniso(fnoise((H, W), lo=2, hi=40, beta=1.5, seed=seed + 5, aniso=(1.0, 0.08)), 2, 6)
    algae = np.clip(streak - 1.2, 0, None) * 0.05
    L = 0.70 + lum + 0.045 * g1 + 0.03 * g2 - 0.25 * dark_gran + 0.15 * light_gran - algae
    L *= 0.82 + 0.18 * butt
    hue = fnoise((H, W), lo=3, hi=30, seed=seed + 6) * 0.015
    alb = np.stack([L * (1 + hue), L, L * (1 - hue)], -1)
    hm = hm + 0.00045 * g1 + 0.0003 * g2
    rough = np.clip(0.86 + 0.05 * g2 - 0.03 * light_gran, 0, 1)
    return finish_height(alb, hm.astype(np.float32), rough, (size, size), ao_radius_m=0.02, ao_strength=1.0,
                         nstrength=1.4, cavity_dark=0.2, name=name, category="roof",
                         tags=["asphalt", "shingle", "laminated", "composition", "neutral-tint"],
                         notes="14 courses x 142.9 mm exposure, 1.0 m strips, random 0.10-0.32 m tabs; neutral -> "
                               "tint with roof colour (facades.json)",
                         res_bl=(HI, HI), res_web=(MID, MID))


def ridge_cap(name="roof_ridge_cap", res=MID, seed=5):
    """Hip & ridge cap shingles: 0.30 m wide caps, 0.127 m exposure, along u."""
    size = (1.016, 0.30)
    W, H = res, int(res * size[1] / size[0])
    U, V = uv_grid(W, H, size)
    e = 0.127
    k = np.floor(U / e)
    f = U / e - k
    hm = 0.004 * (1 - f) + 0.01 * np.cos((V / size[1] - 0.5) * math.pi) ** 0.5
    g = fnoise((H, W), lo=100, beta=0.0, seed=seed)
    L = 0.68 + 0.04 * g + per_id(k.astype(int) % 8, 8, seed, -0.05, 0.05)
    L *= 0.8 + 0.2 * smooth(0, 0.08, f)
    alb = np.repeat(L[..., None], 3, -1)
    return finish_height(alb, hm.astype(np.float32), 0.86 + 0 * L, size, ao_radius_m=0.01, name=name,
                         category="roof", tags=["asphalt", "ridge", "neutral-tint"], res_bl=(W, H),
                         res_web=(W // 2, H // 2))


# ============================================================================ SIDING
def _board_courses(V, exp_m, rng, ncourse, size_u, U, joint_every=(1.2, 3.0)):
    course = np.floor(V / exp_m).astype(int)
    f = V / exp_m - course
    jmask = np.zeros_like(V, dtype=bool)
    board_id = course * 10
    for c in range(ncourse + 1):
        m = course == c
        if not m.any():
            continue
        js = []
        x = rng.uniform(0, size_u)
        js.append(x)
        jm = np.zeros(m.sum(), bool)
        u = U[m]
        for j in js:
            d = np.abs(((u - j + size_u / 2) % size_u) - size_u / 2)
            jm |= d < 0.0015
        jmask[m] = jm
        board_id[m] = c * 10 + (((u - x) % size_u) > size_u / 2).astype(int)
    return course, f, jmask, board_id


def siding_lap(name="siding_lap_wood", exp_in=7.0, ncourse=12, res=HI, seed=11, grain=1.0, fiber=False):
    """Horizontal lap siding: butt thickness 12 mm tapering to 4 mm, exposure exp_in inches, one butt joint per
    course in the repeat; embossed woodgrain (hardboard / fibre-cement 'cedarmill'). Neutral; tinted per house."""
    rng = np.random.default_rng(seed)
    exp_m = exp_in * 0.0254
    size = exp_m * ncourse
    W = H = res
    U, V = uv_grid(W, H, (size, size))
    course, f, jm, bid = _board_courses(V, exp_m, rng, ncourse, size, U)
    hm = 0.012 - 0.008 * f
    # drip/bevel at the butt edge
    hm -= 0.002 * (1 - smooth(0.0, 0.025, f))
    # woodgrain (long along u)
    gr = fnoise((H, W), lo=4, hi=400, beta=1.2, seed=seed + 1, aniso=(0.04, 1.0))
    gr2 = fnoise((H, W), lo=30, hi=900, beta=0.8, seed=seed + 2, aniso=(0.03, 1.0))
    hm += grain * (0.00035 * gr + 0.0002 * gr2)
    hm = np.where(jm, hm - 0.003, hm)
    paint = fnoise((H, W), lo=2, hi=30, seed=seed + 3)
    L = 0.86 + 0.012 * paint + 0.01 * gr * grain + per_id(bid % 997, 997, seed, -0.012, 0.012)
    # dirt under each butt (rain splash shadow), stronger near the bottom of the wall repeat
    dirt = (1 - smooth(0.0, 0.12, f)) * 0.03
    L = L - dirt
    L = np.where(jm, L - 0.12, L)
    alb = np.stack([L, L * 0.995, L * 0.985], -1)
    rough = 0.72 + 0.04 * paint if not fiber else 0.78 + 0.03 * paint
    return finish_height(alb, hm.astype(np.float32), rough, (size, size), ao_radius_m=0.02, ao_strength=1.3,
                         nstrength=1.0, name=name, category="siding",
                         tags=["lap", "siding", "neutral-tint"] + (["fibre-cement"] if fiber else ["wood/hardboard"]),
                         notes="%.0f in exposure (%.4f m), %d courses per repeat" % (exp_in, exp_m, ncourse),
                         res_bl=(res, res), res_web=(MID, MID))


def siding_t111(name="siding_t111", res=HI, seed=21):
    """T1-11 plywood: 4 x 8 ft panels, grooves 3/8" wide x 1/4" deep every 8" (0.2032 m), rough-sawn face,
    Z-flashing joint at 8 ft. Repeat = 2 panels wide x 1 high (2.4384 m)."""
    size = 2.4384
    W = H = res
    U, V = uv_grid(W, H, (size, size))
    g = 0.2032
    du = np.abs(((U + g / 2) % g) - g / 2)
    groove = 1 - smooth(0.0048 - 0.0015, 0.0048 + 0.0005, du)
    hm = -0.0063 * groove
    rs = fnoise((H, W), lo=10, hi=700, beta=1.0, seed=seed, aniso=(1.0, 0.06))
    hm += 0.0005 * rs
    zf = np.abs(V - 0.004) < 0.004
    hm = np.where(zf, hm - 0.004, hm)
    panel = np.floor(U / 1.2192).astype(int)
    L = 0.82 + 0.03 * rs + per_id(panel % 2, 2, seed, -0.015, 0.015)
    L = L - 0.18 * groove
    alb = np.stack([L, L * 0.99, L * 0.975], -1)
    return finish_height(alb, hm.astype(np.float32), 0.86 + 0.03 * rs, (size, size), ao_radius_m=0.012,
                         ao_strength=1.4, name=name, category="siding", tags=["T1-11", "plywood", "neutral-tint"],
                         res_bl=(res, res), res_web=(LO, LO))


def siding_shingle(name="siding_shingle_cedar", res=HI, seed=31, var=0.10):
    """Cedar shingle siding: 16 courses x 0.127 m (5") exposure, random widths 0.08-0.30 m, 3-6 mm keyways,
    butts 10 mm thick, vertical grain."""
    rng = np.random.default_rng(seed)
    exp_m = 0.127
    n = 16
    size = exp_m * n
    W = H = res
    U, V = uv_grid(W, H, (size, size))
    course = np.floor(V / exp_m).astype(int)
    f = V / exp_m - course
    hm = np.zeros((H, W), np.float32)
    sid = np.zeros((H, W), np.int32)
    gapm = np.zeros((H, W), bool)
    tilt = np.zeros((H, W), np.float32)
    for c in range(n):
        m = course == c
        e = [0.0]
        while e[-1] < size:
            e.append(e[-1] + rng.uniform(0.08, 0.30))
        e = np.array(e) * size / e[-1]
        off = rng.uniform(0, size)
        uu = (U[m] + off) % size
        k = np.searchsorted(e, uu) - 1
        ein = np.minimum(uu - e[k], e[k + 1] - uu)
        gw = rng.uniform(0.0015, 0.003, len(e))
        gapm[m] = ein < gw[k]
        sid[m] = c * 50 + k
        tl = rng.normal(0, 0.0015, len(e))
        tilt[m] = tl[k] * ((uu - e[k]) / np.maximum(1e-3, e[k + 1] - e[k]) - 0.5)
    hm = 0.010 * (1 - f) + tilt
    bf = np.where(f < 0.03, 1 - f / 0.03, 0) * 0.0015
    gr = fnoise((H, W), lo=10, hi=800, beta=1.0, seed=seed + 1, aniso=(1.0, 0.05))
    hm = hm - bf + 0.0004 * gr
    hm = np.where(gapm, -0.004, hm)
    L = 0.80 + per_id(sid % 9973, 9973, seed, -var, var) + 0.03 * gr
    L = L * (0.85 + 0.15 * smooth(0, 0.12, f))
    L = np.where(gapm, 0.25, L)
    alb = np.stack([L, L * 0.985, L * 0.965], -1)
    return finish_height(alb, hm.astype(np.float32), 0.85 + 0.04 * gr, (size, size), ao_radius_m=0.015,
                         ao_strength=1.2, name=name, category="siding", tags=["shingle", "cedar", "neutral-tint"],
                         res_bl=(res, res), res_web=(MID, MID))


def siding_board_batten(name="siding_board_batten", res=MID, seed=41):
    size = 2.4
    W = H = res
    U, V = uv_grid(W, H, (size, size))
    p = 0.3
    du = np.abs(((U + p / 2) % p) - p / 2)
    batt = 1 - smooth(0.028, 0.032, du)
    hm = 0.019 * batt
    gr = fnoise((H, W), lo=4, hi=300, beta=1.1, seed=seed, aniso=(1.0, 0.05))
    hm += 0.0003 * gr
    L = 0.85 + 0.02 * gr
    alb = np.repeat(L[..., None], 3, -1)
    return finish_height(alb, hm.astype(np.float32), 0.75 + 0 * L, (size, size), ao_radius_m=0.03, name=name,
                         category="siding", tags=["board-and-batten", "neutral-tint"], res_bl=(res, res),
                         res_web=(LO, LO))


def paint_trim(name="trim_paint", res=LO, seed=51):
    """Painted wood trim (1x4/1x6 boards): faint grain under paint."""
    size = 1.0
    gr = fnoise((res, res), lo=4, hi=200, beta=1.2, seed=seed, aniso=(0.04, 1.0))
    hm = 0.0002 * gr
    L = 0.9 + 0.008 * gr
    alb = np.repeat(L[..., None], 3, -1)
    return finish_height(alb, hm.astype(np.float32), 0.55 + 0.03 * gr, (size, size), name=name, category="trim",
                         tags=["paint", "neutral-tint"], res_bl=(res, res), res_web=(256, 256))


# ============================================================================ HARDSCAPE
def concrete(name, size, joints_u=True, joints_v=True, base="#b5b2aa", broom=True, res=MID, seed=61, stains=1.0,
             tooled_v=False):
    """Broom-finished Portland cement concrete; sawcut/tooled control joints along the texture borders."""
    W = H = res
    U, V = uv_grid(W, H, size)
    n1 = fnoise((H, W), lo=1, hi=20, seed=seed)
    n2 = fnoise((H, W), lo=20, hi=300, beta=1.0, seed=seed + 1)
    br = fnoise((H, W), lo=30, hi=600, beta=0.5, seed=seed + 2, aniso=(1.0, 0.03)) if broom else 0 * n1
    agg = (fnoise((H, W), lo=150, beta=0.0, seed=seed + 3) > 2.1).astype(np.float32)
    hm = 0.0004 * br + 0.0003 * n2 - 0.0006 * agg
    jw = 0.005
    jm = np.zeros((H, W), np.float32)
    if joints_u:
        d = np.minimum(U, size[0] - U)
        jm = np.maximum(jm, 1 - smooth(jw * 0.5, jw * 1.6, d))
    if joints_v:
        d = np.minimum(V, size[1] - V)
        jm = np.maximum(jm, 1 - smooth(jw * 0.5, jw * (6 if tooled_v else 1.6), d))
    hm -= 0.006 * jm
    stain = np.clip(fnoise((H, W), lo=1, hi=8, seed=seed + 4) - 1.0, 0, None) * 0.05 * stains
    c = hexc(base)[None, None] * (1 + 0.04 * n1 + 0.025 * n2 - stain)[..., None]
    c = c * (1 - 0.35 * jm)[..., None]
    c = c * (1 - 0.18 * agg)[..., None]
    rough = 0.9 - 0.04 * n1
    return finish_height(c, hm.astype(np.float32), rough, size, ao_radius_m=0.01, name=name, category="ground",
                         tags=["concrete", "PCC"], res_bl=(W, H), res_web=(LO, LO))


def asphalt(name="asphalt_street", size=6.0, res=HI, seed=71):
    """Aged residential ACP: 0-12 mm aggregate exposed by wear, oxidised binder, sealed cracks (tar snakes),
    a few oil drips. Grey."""
    W = H = res
    px = size / res
    rng = np.random.default_rng(seed)
    n1 = fnoise((H, W), lo=1, hi=12, seed=seed)
    n2 = fnoise((H, W), lo=12, hi=200, beta=1.0, seed=seed + 1)
    # aggregate (8-12 mm stones at ~3 mm/px) via band-limited noise
    agg = fnoise((H, W), lo=220, hi=700, beta=0.3, seed=seed + 2)
    stone = smooth(0.1, 1.0, agg)
    sl = fnoise((H, W), lo=150, hi=400, beta=0.0, seed=seed + 7) * 0.25
    worn = 0.5 + 0.5 * smooth(-1.0, 1.0, n1)
    fine = fnoise((H, W), lo=300, beta=0.0, seed=seed + 3)
    hm = 0.0015 * stone * worn + 0.0003 * fine + 0.002 * n2 * 0.2
    L = 0.32 + 0.02 * n1 + 0.035 * fine + worn * stone * sl * 0.35
    L = L - (1 - stone) * 0.05 * worn
    # sealed cracks: random walk polylines, dark glossy
    crack = Image.new("L", (W * 2, H * 2), 0)
    d = ImageDraw.Draw(crack)
    for i in range(4):
        x, y = rng.uniform(0, W * 2), rng.uniform(0, H * 2)
        ang = rng.uniform(0, 2 * math.pi)
        pts = [(x, y)]
        for k in range(rng.integers(30, 90)):
            ang += rng.normal(0, 0.12)
            x += math.cos(ang) * 14
            y += math.sin(ang) * 14
            pts.append((x, y))
        w = int(rng.uniform(8, 14))
        for dx in (-W * 2, 0, W * 2):
            for dy in (-H * 2, 0, H * 2):
                d.line([(p[0] + dx, p[1] + dy) for p in pts], fill=255, width=w, joint="curve")
    cr = np.asarray(crack.resize((W, H), Image.LANCZOS), np.float32) / 255
    cr = blur(cr, 1.0)
    L = L * (1 - 0.55 * cr)
    hm = hm + 0.001 * cr
    oil = np.clip(fnoise((H, W), lo=3, hi=40, seed=seed + 5) - 2.4, 0, None)
    L = L * (1 - 0.3 * np.clip(oil, 0, 1))
    alb = np.stack([L * 0.99, L, L * 1.02], -1)
    rough = np.clip(0.92 - 0.45 * cr - 0.15 * np.clip(oil, 0, 1) - 0.05 * stone * worn, 0.2, 1)
    return finish_height(alb, hm.astype(np.float32), rough, (size, size), ao_radius_m=0.008, ao_strength=1.0,
                         name=name, category="ground", tags=["asphalt", "ACP", "street"],
                         res_bl=(HI, HI), res_web=(MID, MID))


def gravel(name="gravel_drive", size=1.0, res=MID, seed=81):
    W = H = res
    f1, f21, cid = cells((H // 2, W // 2), 2400, seed=seed)
    f21 = resize(f21, (W, H)) * 2
    f1 = resize(f1, (W, H)) * 2
    cid = np.asarray(Image.fromarray(cid.astype(np.int32)).resize((W, H), Image.NEAREST))
    st = smooth(0.0, 6.0, f21)
    hm = 0.008 * np.sqrt(st)
    L = 0.42 + per_id(cid % 3001, 3001, seed, -0.15, 0.15)
    L = L * (0.5 + 0.5 * st)
    hue = per_id(cid % 3001, 3001, seed + 1, -0.04, 0.04)
    alb = np.stack([L * (1 + hue), L, L * (1 - hue)], -1)
    return finish_height(alb, hm.astype(np.float32), 0.85 + 0 * L, (size, size), ao_radius_m=0.01, name=name,
                         category="ground", tags=["gravel"], res_bl=(W, H), res_web=(LO, LO))


def brick(name="brick_red", res=MID, seed=91):
    """Modular brick 194x57 mm + 10 mm mortar (203 x 67.7 mm modules); running bond."""
    bw, bh = 0.2032, 0.0677
    size = (bw * 4, bh * 13)
    W = res
    H = int(res * size[1] / size[0])
    U, V = uv_grid(W, H, size)
    row = np.floor(V / bh).astype(int)
    uu = U + (row % 2) * bw / 2
    col = np.floor(uu / bw).astype(int)
    fu = uu / bw - col
    fv = V / bh - row
    mu = np.minimum(fu, 1 - fu) * bw
    mv = np.minimum(fv, 1 - fv) * bh
    mort = 1 - smooth(0.004, 0.0055, np.minimum(mu, mv))
    bid = (row * 7 + col) % 997
    n = fnoise((H, W), lo=20, hi=400, beta=1.0, seed=seed)
    hm = -0.006 * mort + 0.0005 * n
    base = hexc("#8a4b3a")
    col_b = base[None, None] * (1 + per_id(bid, 997, seed, -0.15, 0.12) + 0.06 * n)[..., None]
    mortar = hexc("#9c968c")[None, None] * (1 + 0.05 * n)[..., None]
    alb = lerp(col_b, mortar, mort)
    return finish_height(alb, hm.astype(np.float32), 0.88 + 0 * n, size, ao_radius_m=0.008, name=name,
                         category="masonry", tags=["brick"], res_bl=(W, H), res_web=(W // 2, H // 2))


def stone_veneer(name="stone_ledgestone", size=1.0, res=MID, seed=101):
    """Manufactured ledgestone veneer (Craftsman column bases): long thin stacked stones, grey-tan."""
    rng = np.random.default_rng(seed)
    W = H = res
    U, V = uv_grid(W, H, (size, size))
    hm = np.zeros((H, W), np.float32)
    sid = np.zeros((H, W), np.int32)
    y = 0.0
    r = 0
    while y < size:
        hgt = rng.uniform(0.03, 0.09)
        m = (V >= y) & (V < y + hgt)
        e = [0.0]
        while e[-1] < size:
            e.append(e[-1] + rng.uniform(0.12, 0.45))
        e = np.array(e) * size / e[-1]
        off = rng.uniform(0, size)
        uu = (U[m] + off) % size
        k = np.searchsorted(e, uu) - 1
        ein = np.minimum(uu - e[k], e[k + 1] - uu)
        vin = np.minimum(V[m] - y, y + hgt - V[m])
        d = np.minimum(ein, vin)
        hs = rng.uniform(0.005, 0.02, len(e))
        hm[m] = hs[k] * smooth(0.0, 0.006, d)
        sid[m] = r * 40 + k
        y += hgt
        r += 1
    n = fnoise((H, W), lo=10, hi=500, beta=1.0, seed=seed + 1)
    hm += 0.002 * n
    L = 0.55 + per_id(sid % 997, 997, seed, -0.15, 0.15) + 0.05 * n
    hue = per_id(sid % 997, 997, seed + 2, -0.05, 0.06)
    alb = np.stack([L * (1 + hue), L, L * (1 - hue * 1.3)], -1) * hexc("#b0a898")[None, None] / 0.6
    return finish_height(np.clip(alb, 0, 1), hm, 0.9 + 0 * n, (size, size), ao_radius_m=0.02, ao_strength=1.5,
                         name=name, category="masonry", tags=["stone", "veneer"], res_bl=(W, H), res_web=(LO, LO))


def wood_boards(name, size, board_w, gap, base_hex, res=MID, seed=111, var=0.08, along="u", weather=0.0,
                tags=("wood",)):
    """Deck boards / fence pickets: boards of board_w with gaps, grain along the board axis."""
    W = H = res
    U, V = uv_grid(W, H, size)
    a = V if along == "u" else U
    b = U if along == "u" else V
    p = board_w + gap
    k = np.floor(a / p).astype(int)
    f = (a - k * p)
    gapm = f > board_w
    an = (0.03, 1.0) if along == "u" else (1.0, 0.03)
    gr = fnoise((H, W), lo=6, hi=500, beta=1.1, seed=seed, aniso=an)
    knots = np.clip(fnoise((H, W), lo=4, hi=60, seed=seed + 1) - 2.2, 0, None)
    # board ends in deck repeat (one per board, random position)
    ends = np.zeros_like(gapm)
    rng = np.random.default_rng(seed + 2)
    offs = rng.uniform(0, size[0] if along == "u" else size[1], 200)
    L_b = size[0] if along == "u" else size[1]
    dd = np.abs(((b - offs[k % 200] + L_b / 2) % L_b) - L_b / 2)
    ends = (dd < 0.002) & (weather < 0.5)
    hm = np.where(gapm | ends, -0.01, 0.0) + 0.0006 * gr - 0.001 * knots
    edge = np.minimum(f, np.maximum(0, board_w - f))
    hm -= 0.0015 * (1 - smooth(0, 0.004, edge))
    L = 1 + per_id(k % 499, 499, seed, -var, var) + 0.08 * gr - 0.3 * np.clip(knots, 0, 1)
    c = hexc(base_hex)[None, None] * L[..., None]
    if weather > 0:
        grey = c.mean(-1, keepdims=True) * np.array([1.0, 1.0, 1.02])
        w = np.clip(weather + 0.2 * fnoise((H, W), lo=2, hi=40, seed=seed + 3), 0, 1)[..., None]
        c = lerp(c, grey * 1.1, w)
    c = np.where(gapm[..., None], c * 0.15, c)
    return finish_height(np.clip(c, 0, 1), hm.astype(np.float32), 0.8 + 0.05 * gr, size, ao_radius_m=0.01,
                         name=name, category="wood", tags=list(tags), res_bl=(W, H), res_web=(LO, LO))


# ============================================================================ SOFTSCAPE
def lawn(name="lawn_grass", size=1.0, res=MID, seed=121, palette="summer"):
    """Top-down cool-season lawn (perennial rye / fescue): ~25k blade strokes per m^2, mixed greens, a little
    thatch and clover. Baked in colour."""
    rng = np.random.default_rng(seed)
    W = H = res
    ss = 2
    img = Image.new("RGB", (W * ss, H * ss), (52, 60, 28))
    hgt = Image.new("L", (W * ss, H * ss), 0)
    d = ImageDraw.Draw(img)
    dh = ImageDraw.Draw(hgt)
    greens = [hexc(h) for h in ("#4d7a2c", "#5e8a33", "#3f6b26", "#6f9a3c", "#557f2e", "#7a9442", "#8a8f4a")]
    n = int(26000 * size * size)
    for i in range(n):
        x, y = rng.uniform(0, W * ss), rng.uniform(0, H * ss)
        L = rng.uniform(0.006, 0.02) / size * W * ss
        a = rng.uniform(0, 2 * math.pi)
        c = greens[rng.integers(len(greens))] * rng.uniform(0.75, 1.15)
        if rng.random() < 0.06:
            c = hexc("#9a8f5a") * rng.uniform(0.8, 1.1)       # dry blade / thatch
        col = tuple(int(255 * min(1, v)) for v in c)
        x2, y2 = x + math.cos(a) * L, y + math.sin(a) * L
        w = max(1, int(round(0.0025 / size * W * ss)))
        hv = int(rng.uniform(60, 255))
        for dx in (-W * ss, 0, W * ss):
            for dy in (-H * ss, 0, H * ss):
                if 0 <= x + dx < W * ss or 0 <= x2 + dx < W * ss:
                    if 0 <= y + dy < H * ss or 0 <= y2 + dy < H * ss:
                        d.line([(x + dx, y + dy), (x2 + dx, y2 + dy)], fill=col, width=w)
                        dh.line([(x + dx, y + dy), (x2 + dx, y2 + dy)], fill=hv, width=w)
    alb = np.asarray(img.resize((W, H), Image.LANCZOS), np.float32) / 255
    hm = np.asarray(hgt.resize((W, H), Image.LANCZOS), np.float32) / 255 * 0.008
    patch = fnoise((H, W), lo=1, hi=6, seed=seed + 1)
    alb = alb * (1 + 0.10 * patch)[..., None]
    return finish_height(np.clip(alb, 0, 1), hm, 0.9 + 0 * patch, (size, size), ao_radius_m=0.006, ao_strength=1.6,
                         name=name, category="ground", tags=["lawn", "grass", "summer"], res_bl=(W, H),
                         res_web=(LO, LO))


def scatter_chips(name, size, n, len_m, base_hexes, bg_hex, res=MID, seed=131, h_m=0.01, rough=0.9, tags=()):
    """Bark mulch / forest litter: random elongated polygons stacked."""
    rng = np.random.default_rng(seed)
    W = H = res
    ss = 2
    img = Image.new("RGB", (W * ss, H * ss), tuple(int(255 * v) for v in hexc(bg_hex)))
    hgt = Image.new("L", (W * ss, H * ss), 0)
    d = ImageDraw.Draw(img)
    dh = ImageDraw.Draw(hgt)
    cols = [hexc(h) for h in base_hexes]
    sc = W * ss / size
    for i in range(n):
        x, y = rng.uniform(0, W * ss), rng.uniform(0, H * ss)
        L = rng.uniform(*len_m) * sc
        wd = L * rng.uniform(0.25, 0.6)
        a = rng.uniform(0, math.pi)
        ca, sa = math.cos(a), math.sin(a)
        k = rng.integers(5, 8)
        pts = []
        for j in range(k):
            t = 2 * math.pi * j / k
            r = rng.uniform(0.7, 1.0)
            px_, py_ = math.cos(t) * L / 2 * r, math.sin(t) * wd / 2 * r
            pts.append((px_ * ca - py_ * sa, px_ * sa + py_ * ca))
        c = cols[rng.integers(len(cols))] * rng.uniform(0.7, 1.2)
        col = tuple(int(255 * min(1, v)) for v in c)
        hv = int(60 + 195 * i / n)
        for dx in (-W * ss, 0, W * ss):
            for dy in (-H * ss, 0, H * ss):
                P = [(x + dx + p[0], y + dy + p[1]) for p in pts]
                if max(p[0] for p in P) < 0 or min(p[0] for p in P) > W * ss or max(p[1] for p in P) < 0 or min(
                        p[1] for p in P) > H * ss:
                    continue
                d.polygon(P, fill=col)
                dh.polygon(P, fill=hv)
    alb = np.asarray(img.resize((W, H), Image.LANCZOS), np.float32) / 255
    hm = np.asarray(hgt.resize((W, H), Image.LANCZOS), np.float32) / 255 * h_m
    n2 = fnoise((H, W), lo=20, hi=400, seed=seed + 1)
    hm = hm + 0.0008 * n2
    return finish_height(np.clip(alb * (1 + 0.05 * n2)[..., None], 0, 1), hm, rough + 0 * n2, (size, size),
                         ao_radius_m=0.012, ao_strength=1.6, cavity_dark=0.3, name=name, category="ground",
                         tags=list(tags), res_bl=(W, H), res_web=(LO, LO))


def snow(name="snow_fresh", size=2.0, res=MID, seed=151, packed=False):
    """Fresh (or packed) snow: soft wind ripples + clumps; very bright, slightly blue in cavities; sparkle via
    roughness variation. Packed: compacted, greyer, with parallel sled/tyre grooves along u."""
    W = H = res
    U, V = uv_grid(W, H, (size, size))
    n1 = fnoise((H, W), lo=1, hi=8, beta=2.0, seed=seed)
    n2 = fnoise((H, W), lo=8, hi=80, beta=1.5, seed=seed + 1)
    rip = fnoise((H, W), lo=4, hi=30, beta=1.5, seed=seed + 2, aniso=(0.25, 1.0))
    sp = fnoise((H, W), lo=300, beta=0.0, seed=seed + 3)
    hm = 0.02 * n1 + 0.006 * n2 + 0.004 * rip
    L = 0.93 + 0.01 * n2
    rough = 0.62 - 0.25 * np.clip(sp - 1.8, 0, 1)
    if packed:
        rng = np.random.default_rng(seed)
        tr = np.zeros((H, W), np.float32)
        for i in range(14):
            v0 = rng.uniform(0, size)
            wv = rng.uniform(0.03, 0.12)
            dep = rng.uniform(0.004, 0.015)
            wob = 0.03 * np.sin(U / size * 2 * math.pi * rng.integers(1, 3) + rng.uniform(0, 6))
            dv = np.abs(((V - v0 - wob + size / 2) % size) - size / 2)
            tr -= dep * np.exp(-(dv / wv) ** 2 * 2)
        hm = 0.006 * n1 + 0.002 * n2 + tr
        L = 0.84 + 0.03 * n2 - 3.0 * np.clip(-tr, 0, 0.02) - 0.04 * np.clip(fnoise((H, W), lo=2, hi=30,
                                                                                     seed=seed + 5), 0, None)
        rough = 0.45 + 0.1 * n2
    alb = np.stack([L * 0.985, L * 0.995, L * 1.0], -1)
    return finish_height(np.clip(alb, 0, 1), hm.astype(np.float32), np.clip(rough, 0.1, 1), (size, size),
                         ao_radius_m=0.05, ao_strength=0.6, name=name, category="snow",
                         tags=["snow"] + (["packed", "sled-tracks"] if packed else ["fresh"]), res_bl=(W, H),
                         res_web=(LO, LO))


# ============================================================================ BARK
def bark(name, kind, size=1.0, res=MID, seed=161):
    """Tree bark, u = around the trunk (m), v = up (m)."""
    W = H = res
    U, V = uv_grid(W, H, (size, size))
    if kind == "fir":         # Douglas-fir: deep corky furrows, ridges 3-6 cm, red-brown inner furrows
        n = fnoise((H, W), lo=8, hi=60, beta=1.6, seed=seed, aniso=(1.0, 0.18))
        dx = fnoise((H, W), lo=2, hi=10, seed=seed + 1) * 10
        n = warp(n, dx, 0 * dx)
        ridge = smooth(-0.3, 0.9, n)
        cr = fnoise((H, W), lo=30, hi=200, beta=1.0, seed=seed + 2, aniso=(0.6, 1.0))
        hm = 0.035 * ridge + 0.004 * cr
        top = hexc("#6b625a")
        deep = hexc("#4a2e22")
        alb = lerp(deep[None, None], top[None, None], ridge) * (1 + 0.1 * cr)[..., None]
        lich = np.clip(fnoise((H, W), lo=4, hi=40, seed=seed + 3) - 1.2, 0, 1) * ridge
        alb = lerp(alb, hexc("#7d8a6a")[None, None], 0.5 * lich)
        rough = 0.92
        ao_r = 0.04
    elif kind == "cedar":     # western redcedar: long fibrous strips, red-brown to grey
        n = fnoise((H, W), lo=10, hi=200, beta=1.2, seed=seed, aniso=(1.0, 0.03))
        st = smooth(-0.5, 1.0, n)
        hm = 0.01 * st + 0.002 * fnoise((H, W), lo=50, hi=400, seed=seed + 1, aniso=(1.0, 0.05))
        alb = lerp(hexc("#5a3626")[None, None], hexc("#8a6f5c")[None, None], st)
        grey = np.clip(fnoise((H, W), lo=2, hi=20, seed=seed + 2), 0, 1)
        alb = lerp(alb, hexc("#8d8781")[None, None], 0.45 * grey)
        rough = 0.9
        ao_r = 0.015
    elif kind == "maple":     # bigleaf maple: grey-brown, shallow interlacing ridges, moss
        n = fnoise((H, W), lo=6, hi=60, beta=1.4, seed=seed, aniso=(1.0, 0.3))
        st = smooth(-0.6, 0.8, n)
        hm = 0.012 * st + 0.002 * fnoise((H, W), lo=40, hi=300, seed=seed + 1)
        alb = lerp(hexc("#4b4038")[None, None], hexc("#7d7468")[None, None], st)
        moss = np.clip(fnoise((H, W), lo=2, hi=20, seed=seed + 2) - 0.2, 0, 1)
        alb = lerp(alb, hexc("#5a6b2e")[None, None], 0.55 * moss)
        rough = 0.9
        ao_r = 0.02
    elif kind == "birch":     # paper birch: white with dark horizontal lenticels and dark fissure patches
        n = fnoise((H, W), lo=3, hi=40, seed=seed)
        len_ = fnoise((H, W), lo=20, hi=200, beta=0.8, seed=seed + 1, aniso=(0.05, 1.0))
        lent = np.clip(len_ - 1.7, 0, 1)
        patch = np.clip(fnoise((H, W), lo=3, hi=30, seed=seed + 2) - 1.3, 0, 1)
        hm = -0.002 * lent - 0.004 * patch + 0.0006 * n
        alb = hexc("#e4e0d6")[None, None] * (1 + 0.04 * n)[..., None]
        alb = lerp(alb, hexc("#2a2622")[None, None], np.clip(lent * 1.5 + patch, 0, 1))
        rough = 0.7
        ao_r = 0.01
    else:                     # cherry: glossy red-brown with horizontal lenticel bands
        len_ = fnoise((H, W), lo=20, hi=200, beta=0.8, seed=seed + 1, aniso=(0.04, 1.0))
        lent = np.clip(len_ - 1.4, 0, 1)
        n = fnoise((H, W), lo=3, hi=40, seed=seed)
        hm = 0.0015 * lent + 0.0008 * n
        alb = hexc("#5b3a33")[None, None] * (1 + 0.08 * n)[..., None]
        alb = lerp(alb, hexc("#8f7a6c")[None, None], 0.6 * lent)
        rough = 0.55
        ao_r = 0.01
    return finish_height(np.clip(alb, 0, 1), hm.astype(np.float32), rough + 0 * hm, (size, size), ao_radius_m=ao_r,
                         ao_strength=1.3, name=name, category="bark", tags=["bark", kind], res_bl=(W, H),
                         res_web=(LO // 2 if kind in ("cherry",) else LO, LO // 2 if kind in ("cherry",) else LO))


# ============================================================================ DOORS / WINDOWS / PANELS
def _panel_field(U, V, rects, bevel=0.025, raise_h=0.006):
    """Raised panels: rects (u0,v0,u1,v1) -> height with bevelled edges."""
    hm = np.zeros_like(U, dtype=np.float32)
    for (u0, v0, u1, v1) in rects:
        d = np.minimum.reduce([U - u0, u1 - U, V - v0, v1 - V])
        inside = d > 0
        hm = np.where(inside, np.maximum(hm, raise_h * smooth(0, bevel, d) - 0.003 * (d < 0.004)), hm)
    return hm


def garage_panel(name="garage_door_panel", res=MID, seed=171):
    """Steel sectional garage door, raised short panels: 4 sections x 4 panels per 2.438 m (8 ft) repeat;
    a 16x7 ft door uses u = 0..2 repeats, a 9x7 ft door 0..1.125. Woodgrain emboss. Neutral; tinted."""
    size = (2.4384, 2.1336)
    W = res
    H = int(res * size[1] / size[0])
    U, V = uv_grid(W, H, size)
    sec_h = size[1] / 4
    rects = []
    pw = size[0] / 4
    for r in range(4):
        for c in range(4):
            rects.append((c * pw + 0.06, r * sec_h + 0.09, (c + 1) * pw - 0.06, (r + 1) * sec_h - 0.09))
    hm = _panel_field(U, V, rects, bevel=0.03, raise_h=0.008)
    sv = (V % sec_h)
    seam = 1 - smooth(0.0, 0.006, np.minimum(sv, sec_h - sv))
    hm -= 0.006 * seam
    gr = fnoise((H, W), lo=6, hi=400, beta=1.1, seed=seed, aniso=(0.04, 1.0))
    hm += 0.0002 * gr
    L = 0.9 + 0.01 * gr - 0.3 * seam
    alb = np.repeat(L[..., None], 3, -1)
    return finish_height(alb, hm, 0.45 + 0 * L, size, ao_radius_m=0.02, name=name, category="door",
                         tags=["garage", "steel", "neutral-tint"], res_bl=(W, H), res_web=(LO, LO * H // W))


def door_front(name, style="6panel", res=LO, seed=181):
    """Front door 0.914 x 2.032 m (3'0" x 6'8"). 6panel: classic raised 6-panel. craftsman: 3 lites over
    2 vertical panels with a dentil shelf. Neutral body (tinted) - glass baked dark in albedo with low roughness."""
    size = (0.9144, 2.032)
    W = res
    H = res * 2
    U, V = uv_grid(W, H, size)
    st = 0.11
    glass = np.zeros_like(U, dtype=bool)
    if style == "6panel":
        rails = [(0.12, 0.80), (0.92, 1.40), (1.52, 1.92)]
        rects = []
        for (v0, v1) in rails:
            rects += [(st, v0, size[0] / 2 - 0.05, v1), (size[0] / 2 + 0.05, v0, size[0] - st, v1)]
        hm = -_panel_field(U, V, [(r[0], r[1], r[2], r[3]) for r in rects], bevel=0.035, raise_h=0.008) * 0
        for r in rects:
            d = np.minimum.reduce([U - r[0], r[2] - U, V - r[1], r[3] - V])
            hm = np.where(d > 0, -0.012 + 0.010 * smooth(0, 0.035, d), hm)
    else:
        rects = [(st, 0.15, size[0] / 2 - 0.04, 1.05), (size[0] / 2 + 0.04, 0.15, size[0] - st, 1.05)]
        hm = np.zeros_like(U, dtype=np.float32)
        for r in rects:
            d = np.minimum.reduce([U - r[0], r[2] - U, V - r[1], r[3] - V])
            hm = np.where(d > 0, -0.01, hm)
        shelf = (V > 1.12) & (V < 1.20)
        hm = np.where(shelf, 0.015, hm)
        dent = shelf & (V < 1.15) & ((U * 40) % 1 < 0.5)
        hm = np.where(dent, 0.008, hm)
        gl_w = (size[0] - 2 * st - 0.06) / 3
        for i in range(3):
            u0 = st + i * (gl_w + 0.03)
            m = (U > u0) & (U < u0 + gl_w) & (V > 1.30) & (V < 1.85)
            glass |= m
        hm = np.where(glass, -0.012, hm)
    gr = fnoise((H, W), lo=6, hi=300, beta=1.1, seed=seed, aniso=(1.0, 0.05))
    hm = hm + 0.0002 * gr
    L = 0.88 + 0.015 * gr
    alb = np.repeat(L[..., None], 3, -1)
    alb = np.where(glass[..., None], np.array([0.05, 0.055, 0.06]) * 0.4, alb)
    rough = np.where(glass, 0.05, 0.4)
    knob_u, knob_v = size[0] - 0.075, 0.95
    km = ((U - knob_u) ** 2 + (V - knob_v) ** 2) < 0.03 ** 2
    alb = np.where(km[..., None], np.array([0.55, 0.45, 0.25]), alb)
    metal = km.astype(np.float32)
    hm = np.where(km, 0.02, hm)
    return finish_height(alb, hm.astype(np.float32), rough, size, metal=metal, ao_radius_m=0.02, name=name,
                         category="door", tags=["door", style, "neutral-tint"], res_bl=(W, H),
                         res_web=(W // 2, H // 2), extra={"kind": "single"})


def window_interiors(name="window_interior", res=MID, seed=191):
    """Atlas 2x2 of what you see through a window (albedo seen through glass, emissive mask for lit rooms):
    [0] dim room, ceiling + furniture silhouettes; [1] white horizontal blinds 2/3 down; [2] beige curtains
    drawn to the sides; [3] sheer white curtain. Cells are stretched over each window glass."""
    rng = np.random.default_rng(seed)
    C = res // 2
    alb = np.zeros((res, res, 3), np.float32)
    emit = np.zeros((res, res), np.float32)
    yy, xx = np.mgrid[0:C, 0:C].astype(np.float32) / C
    for cell in range(4):
        r0, c0 = (cell // 2) * C, (cell % 2) * C
        room = 0.045 + 0.04 * (1 - yy) + 0.015 * fnoise((C, C), lo=2, hi=20, seed=seed + cell)
        col = np.stack([room * 1.1, room, room * 0.9], -1)
        e = 0.35 + 0.65 * (1 - yy) ** 1.5
        # furniture silhouettes / picture frame
        for k in range(3):
            x0, x1 = sorted(rng.uniform(0, 1, 2))
            y0 = rng.uniform(0.55, 0.85)
            m = (xx > x0) & (xx < x1) & (yy > y0)
            col[m] *= 0.55
        pf = (np.abs(xx - rng.uniform(0.3, 0.7)) < 0.12) & (np.abs(yy - 0.3) < 0.08)
        col[pf] = col[pf] * 0.3 + np.array([0.12, 0.1, 0.08])
        if cell == 1:
            blind = yy < 0.62
            slat = (np.sin(yy * C * 0.9) * 0.5 + 0.5)
            bc = np.stack([0.7 + 0.15 * slat] * 3, -1) * np.array([1, 0.99, 0.96])
            col = np.where(blind[..., None], bc, col)
            e = np.where(blind, 0.5 + 0.3 * slat, e)
        elif cell == 2:
            fold = 0.5 + 0.5 * np.sin(xx * 60 + 2 * np.sin(yy * 5))
            cur = (xx < 0.22) | (xx > 0.78)
            cc = np.stack([0.55 + 0.15 * fold, 0.48 + 0.13 * fold, 0.36 + 0.1 * fold], -1)
            col = np.where(cur[..., None], cc, col)
            e = np.where(cur, 0.6 * (0.6 + 0.4 * fold), e)
        elif cell == 3:
            fold = 0.5 + 0.5 * np.sin(xx * 90 + 3 * np.sin(yy * 4))
            sheer = 0.55 + 0.1 * fold
            col = col * 0.35 + np.stack([sheer, sheer, sheer * 0.97], -1) * 0.65
            e = 0.8 * (0.7 + 0.3 * fold)
        alb[r0:r0 + C, c0:c0 + C] = col
        emit[r0:r0 + C, c0:c0 + C] = e
    nrm = np.zeros((res, res, 3), np.float32)
    nrm[..., 2] = 1
    return write_set(name, np.clip(alb, 0, 1), nrm, np.ones((res, res), np.float32),
                     0.5 * np.ones((res, res), np.float32), emit=np.clip(emit, 0, 1), size_m=(1, 1), kind="atlas",
                     category="window", tags=["window", "interior", "atlas2x2"], res_bl=(res, res),
                     res_web=(res // 2, res // 2),
                     notes="2x2 atlas; cell 0 dim room, 1 blinds, 2 curtains, 3 sheer; emit = lit-room mask")


def solar_panel(name="solar_panel", res=LO, seed=201):
    """60-cell mono PV module 1.0 x 1.7 m: 6 x 10 cells, black, silver frame."""
    size = (1.0, 1.7)
    W = res
    H = int(res * 1.7)
    U, V = uv_grid(W, H, size)
    fr = 0.035
    inner = (U > fr) & (U < size[0] - fr) & (V > fr) & (V < size[1] - fr)
    cu = (U - fr) / ((size[0] - 2 * fr) / 6)
    cv = (V - fr) / ((size[1] - 2 * fr) / 10)
    gu = np.minimum(cu % 1, 1 - cu % 1)
    gv = np.minimum(cv % 1, 1 - cv % 1)
    gap = (gu < 0.02) | (gv < 0.012)
    corner = (gu < 0.1) & (gv < 0.06)
    bus = (np.abs((cu % 1) - 0.33) < 0.008) | (np.abs((cu % 1) - 0.66) < 0.008)
    alb = np.zeros((H, W, 3), np.float32) + np.array([0.03, 0.035, 0.05])
    alb[gap | corner] = [0.35, 0.36, 0.38]
    alb[bus & ~gap] = [0.2, 0.2, 0.22]
    alb[~inner] = [0.6, 0.61, 0.63]
    metal = np.where(~inner, 1.0, 0.0).astype(np.float32)
    rough = np.where(inner, 0.08, 0.35).astype(np.float32)
    hm = np.where(inner, 0.0, 0.006).astype(np.float32)
    return finish_height(alb, hm, rough, size, metal=metal, ao_radius_m=0.01, name=name, category="roof",
                         tags=["pv", "solar"], res_bl=(W, H), res_web=(W // 2, H // 2))


def foliage_dense(name, kind, size=1.0, res=MID, seed=211):
    """Tileable dense foliage surface for clipped hedges / columnar arborvitae / shrub cores."""
    rng = np.random.default_rng(seed)
    W = H = res
    ss = 2
    if kind == "laurel":
        cols = ["#2f4f1f", "#3b5e25", "#26421a", "#46692c"]
        n, Lm, wr = 900, (0.08, 0.14), 0.32
    elif kind == "arborvitae":
        cols = ["#3f6b2a", "#4f7d30", "#35592a", "#5b8a36"]
        n, Lm, wr = 2600, (0.03, 0.07), 0.45
    elif kind == "boxwood":
        cols = ["#3a5d25", "#4a6e2c", "#2f4d1f"]
        n, Lm, wr = 5000, (0.012, 0.022), 0.55
    else:  # rhodo
        cols = ["#2b4a22", "#365a28", "#24401c"]
        n, Lm, wr = 700, (0.08, 0.15), 0.3
    img = Image.new("RGB", (W * ss, H * ss), (20, 32, 14))
    hgt = Image.new("L", (W * ss, H * ss), 0)
    d = ImageDraw.Draw(img)
    dh = ImageDraw.Draw(hgt)
    sc = W * ss / size
    for i in range(n):
        x, y = rng.uniform(0, W * ss), rng.uniform(0, H * ss)
        L = rng.uniform(*Lm) * sc
        a = rng.uniform(0, 2 * math.pi)
        ca, sa = math.cos(a), math.sin(a)
        pts = []
        for t in np.linspace(0, 2 * math.pi, 14, endpoint=False):
            yl = -math.cos(t)
            w = wr * abs(math.sin(t)) ** 0.8
            if kind == "arborvitae":
                w *= 0.8 + 0.2 * math.cos(t * 7)
            px_, py_ = yl * L / 2, w * L / 2 * (1 if t < math.pi else -1)
            pts.append((px_ * ca - py_ * sa, px_ * sa + py_ * ca))
        depth = i / n
        c = hexc(cols[rng.integers(len(cols))]) * (0.55 + 0.6 * depth) * rng.uniform(0.85, 1.15)
        col = tuple(int(255 * min(1, v)) for v in c)
        hv = int(30 + 225 * depth)
        for dx in (-W * ss, 0, W * ss):
            for dy in (-H * ss, 0, H * ss):
                P = [(x + dx + p[0], y + dy + p[1]) for p in pts]
                if max(p[0] for p in P) < 0 or min(p[0] for p in P) > W * ss or max(p[1] for p in P) < 0 or min(
                        p[1] for p in P) > H * ss:
                    continue
                d.polygon(P, fill=col)
                dh.polygon(P, fill=hv)
    alb = np.asarray(img.resize((W, H), Image.LANCZOS), np.float32) / 255
    hm = np.asarray(hgt.resize((W, H), Image.LANCZOS), np.float32) / 255 * 0.05
    return finish_height(alb, hm, 0.6 + 0 * hm, (size, size), ao_radius_m=0.03, ao_strength=1.5, cavity_dark=0.4,
                         name=name, category="foliage", tags=["foliage", "dense", kind], res_bl=(W, H),
                         res_web=(LO, LO))


# ============================================================================ registry
def build_surfaces(only=None):
    jobs = {
        "roof_arch_shingle": lambda: roof_arch_shingle(),
        "roof_ridge_cap": lambda: ridge_cap(),
        "siding_lap_wood": lambda: siding_lap("siding_lap_wood", 7.0, 12, seed=11, grain=1.0),
        "siding_lap_fibercement": lambda: siding_lap("siding_lap_fibercement", 7.25, 12, seed=13, grain=1.6,
                                                     fiber=True),
        "siding_t111": lambda: siding_t111(),
        "siding_shingle_cedar": lambda: siding_shingle(),
        "siding_board_batten": lambda: siding_board_batten(),
        "trim_paint": lambda: paint_trim(),
        "concrete_drive": lambda: concrete("concrete_drive", (3.0, 3.0), base="#b9b6ae", seed=61),
        "concrete_sidewalk": lambda: concrete("concrete_sidewalk", (1.524, 1.524), base="#bdbab2", seed=63,
                                              tooled_v=True),
        "concrete_plain": lambda: concrete("concrete_plain", (2.0, 2.0), joints_u=False, joints_v=False,
                                           base="#aeaba3", broom=False, seed=65),
        "asphalt_street": lambda: asphalt(),
        "gravel_drive": lambda: gravel(),
        "brick_red": lambda: brick(),
        "stone_ledgestone": lambda: stone_veneer(),
        "wood_deck": lambda: wood_boards("wood_deck", (2.4, 2.4), 0.14, 0.006, "#8a6448", seed=111,
                                         tags=("wood", "deck", "neutral-ish")),
        "fence_cedar": lambda: wood_boards("fence_cedar", (2.24, 2.24), 0.134, 0.006, "#8c7058", along="v",
                                           weather=0.55, seed=113, tags=("wood", "fence", "cedar")),
        "lawn_grass": lambda: lawn(),
        "bark_mulch": lambda: scatter_chips("bark_mulch", 1.0, 9000, (0.012, 0.045),
                                            ["#5a3a26", "#6b442b", "#4a2f20", "#7a5134", "#3d281c"], "#2a1d15",
                                            seed=131, tags=("mulch", "bark")),
        "forest_floor": lambda: scatter_chips("forest_floor", 2.0, 14000, (0.01, 0.05),
                                              ["#4a3a28", "#5a4a30", "#3e3322", "#6b5a3a", "#45502a", "#3a4a22"],
                                              "#2a2418", seed=141, tags=("forest", "litter", "needles")),
        "snow_fresh": lambda: snow(),
        "snow_packed": lambda: snow("snow_packed", 4.0, packed=True, seed=157),
        "bark_fir": lambda: bark("bark_fir", "fir"),
        "bark_cedar": lambda: bark("bark_cedar", "cedar", seed=163),
        "bark_maple": lambda: bark("bark_maple", "maple", seed=165),
        "bark_birch": lambda: bark("bark_birch", "birch", seed=167),
        "bark_cherry": lambda: bark("bark_cherry", "cherry", seed=169),
        "garage_door_panel": lambda: garage_panel(),
        "door_6panel": lambda: door_front("door_6panel", "6panel"),
        "door_craftsman": lambda: door_front("door_craftsman", "craftsman"),
        "window_interior": lambda: window_interiors(),
        "solar_panel": lambda: solar_panel(),
        "foliage_laurel": lambda: foliage_dense("foliage_laurel", "laurel"),
        "foliage_arborvitae": lambda: foliage_dense("foliage_arborvitae", "arborvitae", seed=213),
        "foliage_boxwood": lambda: foliage_dense("foliage_boxwood", "boxwood", seed=215),
        "foliage_rhodo": lambda: foliage_dense("foliage_rhodo", "rhodo", seed=217),
    }
    for k, fn in jobs.items():
        if only and k not in only:
            continue
        t = time.time()
        fn()
        print("   %-26s %.1fs" % (k, time.time() - t), flush=True)


if __name__ == "__main__":
    only = sys.argv[1:] or None
    build_surfaces(only)
    if not only or "foliage_atlas" in only:
        import texlib_cards
        texlib_cards.build()
