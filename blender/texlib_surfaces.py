"""Tileable surface materials built from physically scaled height fields (numpy).

Every material is generated as a real-scale height field (metres) + per-element colour/roughness, then
normal and AO are derived from the height (texlib_common.finish_height). All outputs wrap seamlessly.
Facade modules and kawara roofs are NOT here: they are modelled as real geometry in Blender
(texlib_facade.py / texlib_roof.py) and only use the timber/plaster/granite maps below as their base surfaces.
"""
import numpy as np

from texlib_common import (blur, blur_aniso, cells, fnoise, finish_height, hexc, lerp, smooth, warp, raster,
                           height_to_normal, ao_from_height, write_set, s2l, l2s)

R = 2048


# ============================================================================ building blocks
def bond_layout(w, h, row_h_px, len_px, seed, row_jitter=0.12, stagger=True, vertical=False, ydist=True):
    """Running-bond rectangular layout, periodic in both axes.

    Returns dict with id (int), dist (px to nearest joint), ex/ey (px from slab-local origin), sw/sh (slab size px).
    row heights vary by +-row_jitter; slab lengths drawn from len_px=(min,max)."""
    if vertical:
        o = bond_layout(h, w, row_h_px, len_px, seed, row_jitter, stagger, ydist=ydist)
        return {k: (v.T if isinstance(v, np.ndarray) else v) for k, v in o.items()}
    rng = np.random.default_rng(seed)
    nrows = max(1, int(round(h / row_h_px)))
    rh = rng.uniform(1 - row_jitter, 1 + row_jitter, nrows)
    rh = rh / rh.sum() * h
    y_edges = np.r_[0, np.cumsum(rh)]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    row = np.clip(np.searchsorted(y_edges, yy, side="right") - 1, 0, nrows - 1)
    ids = np.zeros((h, w), np.int32)
    dist = np.zeros((h, w), np.float32)
    ex = np.zeros((h, w), np.float32); ey = np.zeros((h, w), np.float32)
    sw = np.zeros((h, w), np.float32); sh = np.zeros((h, w), np.float32)
    nid = 0
    for r in range(nrows):
        lens = []
        while sum(lens) < w:
            lens.append(rng.uniform(*len_px))
        lens = np.array(lens)
        lens *= w / lens.sum()
        off = rng.uniform(0, w) if stagger else 0.0
        edges = np.r_[0, np.cumsum(lens)]
        m = row == r
        x = (xx[m] - off) % w
        k = np.clip(np.searchsorted(edges, x, side="right") - 1, 0, len(lens) - 1)
        x0 = edges[k]; x1 = edges[k + 1]
        y0, y1 = y_edges[r], y_edges[r + 1]
        y = yy[m]
        ids[m] = nid + k
        dx_ = np.minimum(x - x0, x1 - x)
        dist[m] = np.minimum(dx_, np.minimum(y - y0 + 0.5, y1 - y - 0.5)) if ydist else dx_
        ex[m] = x - x0; ey[m] = y - y0
        sw[m] = (x1 - x0); sh[m] = (y1 - y0)
        nid += len(lens)
    return {"id": ids, "dist": dist, "ex": ex, "ey": ey, "sw": sw, "sh": sh, "n": nid}


def per_id(ids, n, seed, lo=0.0, hi=1.0):
    v = np.random.default_rng(seed).uniform(lo, hi, n + 1).astype(np.float32)
    return v[ids]


def granite_grain(shape, seed, px_m, scale=1.0):
    """mm-scale granite mineral speckle: returns (rgb multiplier, height)"""
    h, w = shape
    rng = np.random.default_rng(seed)
    s = max(0.5, 0.0012 * scale / px_m)
    wn = blur(rng.standard_normal((h, w)).astype(np.float32), s)
    wn /= wn.std() + 1e-9
    wn2 = blur(rng.standard_normal((h, w)).astype(np.float32), s * 1.5)
    wn2 /= wn2.std() + 1e-9
    bio = smooth(1.45, 1.9, wn)            # dark biotite flecks
    fel = smooth(0.9, 1.4, wn2)            # pale feldspar
    pink = smooth(1.6, 2.1, -wn2) * 0.6    # a few pinkish K-feldspar grains
    mul = np.ones((h, w, 3), np.float32)
    mul = lerp(mul, np.array([0.38, 0.38, 0.40]), bio * 0.6)
    mul = lerp(mul, np.array([1.22, 1.20, 1.16]), fel * 0.6)
    mul = lerp(mul, np.array([1.12, 0.98, 0.92]), pink * 0.5)
    hgt = (wn * 0.25 + 0.35 * fel - 0.3 * bio) * 0.0004 * scale
    return mul, hgt


def wood_field(w, h, px_m, seed, ring_m=0.009, along="v", knot_density=0.6):
    """Wood grain: returns (grain 0..1 latewood mask, fibre noise, height) for grain running along v (rows)."""
    rng = np.random.default_rng(seed)
    # coordinate across the grain warped by long, smooth noise -> flowing figure
    warpn = fnoise((h, w), lo=1, hi=24, beta=3.0, seed=seed, aniso=(1.0, 0.12))
    xx = np.mgrid[0:h, 0:w][1].astype(np.float32)
    across = xx * px_m + warpn * 0.035
    # knots: local swirls
    kn = np.zeros((h, w), np.float32)
    for _ in range(int(knot_density * (w * h * px_m * px_m))):
        cx, cy = rng.uniform(0, w), rng.uniform(0, h)
        r = rng.uniform(0.006, 0.018) / px_m
        yy, xxg = np.ogrid[0:h, 0:w]
        dx = (xxg - cx + w / 2) % w - w / 2
        dy = (yy - cy + h / 2) % h - h / 2
        d = np.sqrt(dx * dx + (dy * 0.45) ** 2) / r
        kn += np.exp(-d * d) * rng.uniform(0.6, 1.2)
        across = across + np.exp(-d * d * 0.25) * r * px_m * 0.8 * np.sign(dx + 1e-3)
    rings = (across / ring_m + 0.6 * fnoise((h, w), lo=2, hi=40, beta=2, seed=seed + 1, aniso=(1, 0.1)))
    late = smooth(0.45, 0.98, 0.5 + 0.5 * np.sin(rings * 2 * np.pi)) ** 1.5
    fibre = fnoise((h, w), lo=8, hi=None, beta=0.6, seed=seed + 2, aniso=(1.0, 0.04))
    hgt = -late * 0.0005 + fibre * 0.00008 - kn * 0.0003
    if along == "u":
        return late.T, fibre.T, hgt.T, kn.T
    return late, fibre, hgt, kn


# ============================================================================ timber
WOOD_PALETTES = {
    # sRGB albedo: base, latewood, weathered-silver
    "dark": (hexc("#4e3a2b"), hexc("#2b1f17"), hexc("#8a8172")),      # sumi/kakishibu-stained machiya timber (obs. #5a3418 in sun)
    "bengara": (hexc("#4b2a20"), hexc("#301a14"), hexc("#6e5c56")),   # red-oxide (bengara) stain, weathered
    "honey": (hexc("#a0703f"), hexc("#73492a"), hexc("#a8998a")),     # renovated cedar/hinoki, oiled, observed on many shops
    "silver": (hexc("#6f655a"), hexc("#4b4239"), hexc("#a39d92")),    # long-weathered unpainted boards
}


def timber(name="timber_planks_weathered", palette="dark", size_m=(2.4, 2.4), board=(0.18, 0.27), seams=True, seed=11,
           res=R, battens=True, weather=0.5, write=True, grain_k=0.6, **kw):
    w = h = res
    px = size_m[0] / w
    base, late_c, silver = WOOD_PALETTES[palette]
    if seams:
        lay = bond_layout(w, h, h, (board[0] / px, board[1] / px), seed, row_jitter=0, stagger=False, ydist=False)
        # bond_layout(vertical=False) with one row of height h gives vertical boards across x
        bid = lay["id"]; dist = lay["dist"]; ex = lay["ex"]; bw = lay["sw"]
    else:
        bid = np.zeros((h, w), np.int32); dist = np.full((h, w), 1e3, np.float32)
        ex = np.mgrid[0:h, 0:w][1].astype(np.float32); bw = np.full((h, w), float(w))
    late, fibre, ghgt, kn = wood_field(w, h, px, seed)
    # per-board shifts so neighbouring boards don't share figure
    if seams:
        sh = per_id(bid, lay["n"], seed + 3, 0, h).astype(np.int32)
        yy = np.mgrid[0:h, 0:w][0]
        cols = np.mgrid[0:h, 0:w][1]
        late = late[(yy + sh) % h, cols]; fibre = fibre[(yy + sh) % h, cols]; ghgt = ghgt[(yy + sh) % h, cols]
        kn = kn[(yy + sh) % h, cols]
    tone = per_id(bid, 10000, seed + 4, -1, 1) if seams else np.zeros((h, w), np.float32)
    # weathering: silvering streaks running down the boards, stronger at the bottom of the repeat is avoided
    # (texture must tile) -> purely streak/patch based; module-level gradients are added on the facades.
    wst = fnoise((h, w), lo=1, hi=30, beta=2.2, seed=seed + 5, aniso=(1.0, 0.08))
    wpatch = fnoise((h, w), lo=1, hi=10, beta=2.0, seed=seed + 6)
    silv = np.clip(weather * (0.35 + 0.35 * wst + 0.25 * wpatch) + 0.25 * late * weather, 0, 1)
    silv = smooth(0.25, 0.9, silv) * weather
    col = lerp(np.broadcast_to(base, (h, w, 3)), late_c, late * grain_k)
    col = col * (1 + 0.10 * tone)[..., None] * (1 + 0.06 * fibre)[..., None]
    col = lerp(col, silver * (1 + 0.05 * fibre)[..., None], silv * 0.8)
    col = lerp(col, col * 0.55, smooth(0.3, 1.2, kn)[..., None])
    # dirt / water marks
    stains = smooth(0.8, 2.2, fnoise((h, w), lo=2, hi=40, beta=1.6, seed=seed + 7, aniso=(1, 0.3)))
    col = col * (1 - 0.25 * stains)[..., None]
    hgt = ghgt * (1 + weather) + silv * -0.0002
    rough = 0.72 + 0.12 * silv + 0.05 * fibre - 0.06 * (1 - weather)
    if seams:
        # cupping + seam gap 4 mm + slight board-to-board relief
        cup = ((ex / np.maximum(bw, 1)) - 0.5) ** 2 * 0.0025
        hgt = hgt + cup + per_id(bid, lay["n"], seed + 8, 0, 0.0015)
        gap = 1 - smooth(1.2, 3.0 + 0.002 / px, dist)
        hgt = hgt - gap * 0.008
        col = lerp(col, np.array([0.05, 0.04, 0.035]), gap * 0.85)
    col = np.clip(col, 0, 1)
    if not write:
        return col, hgt, rough
    return finish_height(col, hgt, rough, size_m, ao_radius_m=0.02, name=name, category="misc",
                         tags=["traditional", "timber"], **kw)


# ============================================================================ plaster
PLASTER = {
    "ochre": (hexc("#c4a274"), hexc("#a88456")),     # 聚楽-type earth plaster, observed #c8a878
    "cream": (hexc("#dccba2"), hexc("#c2ae84")),     # cream machiya plaster, observed #e6d6b0 (sunlit)
    "lime": (hexc("#e4e2da"), hexc("#c9c6bc")),      # shikkui white lime
    "earth": (hexc("#9c7b55"), hexc("#7d5f40")),     # bare clay wall (arakabe / nakanuri)
    "grey": (hexc("#a8a49b"), hexc("#8b877e")),      # grey mortar / ash plaster
}


def plaster(name="plaster_lime", kind="lime", size_m=(2.0, 2.0), seed=21, res=R, grime=0.5, write=True, **kw):
    w = h = res
    px = size_m[0] / w
    c0, c1 = PLASTER[kind]
    rng = np.random.default_rng(seed)
    # trowel undulation (very low), trowel strokes (arcs, anisotropic), sand grain
    und = fnoise((h, w), lo=1, hi=8, beta=3, seed=seed) * 0.0012
    strokes = fnoise((h, w), lo=6, hi=60, beta=1.5, seed=seed + 1, aniso=(0.35, 1.0), rot=0.5)
    strokes2 = fnoise((h, w), lo=6, hi=60, beta=1.5, seed=seed + 2, aniso=(0.35, 1.0), rot=-0.7)
    tr = np.maximum(strokes, strokes2)
    sandamt = {"lime": 0.15, "cream": 0.5, "ochre": 0.8, "earth": 1.0, "grey": 0.6}[kind]
    grain = blur(rng.standard_normal((h, w)).astype(np.float32), 0.6)
    grain /= grain.std()
    sand = smooth(1.0, 2.4, grain)                           # protruding sand grains
    straw = np.zeros((h, w), np.float32)
    if kind in ("earth", "ochre"):
        # chopped straw fibres (susa) visible in earth plaster
        for _ in range(int(40 * size_m[0] * size_m[1])):
            x0, y0 = rng.uniform(0, w), rng.uniform(0, h)
            ang = rng.uniform(0, np.pi); L = rng.uniform(0.006, 0.02) / px
            n = int(L) + 2
            xs = (x0 + np.cos(ang) * np.linspace(0, L, n)).astype(int) % w
            ys = (y0 + np.sin(ang) * np.linspace(0, L, n)).astype(int) % h
            straw[ys, xs] = 1
        straw = np.clip(blur(straw, 0.6) * 3, 0, 1)
    hgt = und + tr * 0.00025 + sand * 0.0005 * sandamt + straw * 0.0003
    mott = fnoise((h, w), lo=1, hi=40, beta=1.8, seed=seed + 3)
    col = lerp(np.broadcast_to(c0, (h, w, 3)), c1, np.clip(0.25 + 0.12 * mott, 0, 1))
    col = col * (1 + 0.05 * grain * sandamt)[..., None]
    col = lerp(col, c1 * 0.8, straw * 0.6)
    # grime: soot / water marks, vertical-ish streaks + patches; hairline cracks
    streak = fnoise((h, w), lo=1, hi=40, beta=1.8, seed=seed + 4, aniso=(1.0, 0.07))
    patch = fnoise((h, w), lo=1, hi=8, beta=2, seed=seed + 5)
    dirt = np.clip(grime * (smooth(0.6, 2.2, streak) * 0.5 + smooth(0.4, 1.8, patch) * 0.5), 0, 1)
    col = col * (1 - 0.12 * dirt)[..., None] * np.array([1.0, 0.98, 0.95])[None, None] ** dirt[..., None]
    crack_n = fnoise((h, w), lo=3, hi=50, beta=1.4, seed=seed + 6)
    crack = np.exp(-(crack_n / 0.03) ** 2) * smooth(0.2, 1.2, fnoise((h, w), lo=1, hi=6, beta=2, seed=seed + 7))
    crack *= 0.6 if kind in ("lime", "cream", "grey") else 0.35
    hgt = hgt - crack * 0.0006
    col = col * (1 - 0.45 * crack)[..., None]
    rough = 0.86 + 0.06 * sand * sandamt - 0.08 * (kind == "lime") + 0.03 * dirt
    if not write:
        return np.clip(col, 0, 1), hgt, rough
    return finish_height(col, hgt, rough, size_m, ao_radius_m=0.01, ao_strength=0.6, name=name, category="misc",
                         tags=["traditional", "plaster"], **kw)


# ============================================================================ ground
def granite_paving(name, size_m, row_m, len_m, base_hex, seed, joint_m=0.01, bevel_m=0.012, flamed=1.0, domed=0.0,
                   joint_col=(0.27, 0.25, 0.22), wear=0.5, res=R, category="ground", notes="", tags=("traditional",),
                   vertical=False, row_jitter=0.08, moss=0.0, write=True, **kw):
    w = h = res
    px = size_m[0] / w
    lay = bond_layout(w, h, row_m / px, (len_m[0] / px, len_m[1] / px), seed, row_jitter=row_jitter, vertical=vertical)
    sid, dist = lay["id"], lay["dist"]
    n = lay["n"]
    rng = np.random.default_rng(seed)
    base = hexc(base_hex)
    # joint width varies a bit per slab, edges irregular (warped distance)
    jw = (joint_m / 2) / px * per_id(sid, n, seed + 1, 0.7, 1.4)
    edge_noise = fnoise((h, w), lo=8, hi=80, beta=1.6, seed=seed + 2) * (0.0015 / px)
    d = dist + edge_noise
    inside = smooth(jw, jw + 1.5, d)
    bev = smooth(jw, jw + bevel_m / px, d)
    # slab surface: per-slab tilt + dome + flamed roughness
    tx = per_id(sid, n, seed + 3, -1, 1); ty = per_id(sid, n, seed + 4, -1, 1)
    exn = lay["ex"] / np.maximum(lay["sw"], 1) - 0.5
    eyn = lay["ey"] / np.maximum(lay["sh"], 1) - 0.5
    tilt = (tx * exn * lay["sw"] + ty * eyn * lay["sh"]) * px * 0.006
    dome = (1 - (2 * exn) ** 2) * (1 - (2 * eyn) ** 2) * domed
    flame = fnoise((h, w), lo=60, hi=None, beta=1.0, seed=seed + 5) * 0.0006 * flamed
    pits = smooth(1.8, 2.6, fnoise((h, w), lo=100, hi=None, beta=0.4, seed=seed + 6)) * 0.0008 * flamed
    gmul, ghgt = granite_grain((h, w), seed + 7, px)
    hgt = (tilt + dome + flame - pits + ghgt + per_id(sid, n, seed + 8, -0.002, 0.002)) * bev - (1 - inside) * 0.006
    hgt = hgt + (bev - 1) * 0.004
    # colour: per-slab hue/value shift, granite speckle, wear/grime
    v = per_id(sid, n, seed + 9, -1, 1)
    hue = per_id(sid, n, seed + 10, -1, 1)
    col = base[None, None] * (1 + 0.09 * v)[..., None] * (1 + 0.035 * hue[..., None] * np.array([1, 0, -1]))
    col = col * gmul
    mott = fnoise((h, w), lo=2, hi=60, beta=1.6, seed=seed + 11)
    col = col * (1 + 0.03 * mott)[..., None]
    grime = smooth(-0.5, 2.0, fnoise((h, w), lo=1, hi=6, beta=2.5, seed=seed + 12)) * wear
    edge_dirt = (1 - smooth(0, 0.03 / px, d - jw)) * 0.35
    col = col * (1 - 0.10 * grime - edge_dirt * 0.35)[..., None]
    # dark spots (old gum / oil / water)
    spots = smooth(2.3, 2.8, fnoise((h, w), lo=20, hi=200, beta=0.8, seed=seed + 13)) * wear
    col = col * (1 - 0.35 * spots)[..., None]
    jn = fnoise((h, w), lo=40, hi=None, beta=1, seed=seed + 14)
    jcol = np.array(joint_col)[None, None] * (1 + 0.25 * jn)[..., None]
    if moss:
        mm = smooth(0.2, 1.2, fnoise((h, w), lo=2, hi=30, beta=1.5, seed=seed + 15)) * moss
        jcol = lerp(jcol, np.array([0.16, 0.22, 0.08]) * (1 + 0.3 * jn)[..., None], mm)
    col = lerp(jcol, col, inside)
    rough = lerp(np.full((h, w), 0.9, np.float32), 0.62 + 0.18 * flamed - 0.18 * grime * wear + 0.05 * jn, inside)
    if not write:
        return np.clip(col, 0, 1), hgt, rough
    return finish_height(np.clip(col, 0, 1), hgt, rough, size_m, ao_radius_m=0.02, name=name, category=category,
                         tags=list(tags) + ["granite"], notes=notes, **kw)


def asphalt(name="asphalt_worn", size_m=(4.0, 4.0), seed=41, res=R, **kw):
    w = h = res
    px = size_m[0] / w
    rng = np.random.default_rng(seed)
    # aggregate: blurred white noise thresholded at two scales
    a1 = blur(rng.standard_normal((h, w)).astype(np.float32), 0.004 / px); a1 /= a1.std()
    a2 = blur(rng.standard_normal((h, w)).astype(np.float32), 0.0015 / px); a2 /= a2.std()
    stones = np.maximum(smooth(0.6, 1.3, a1), smooth(1.0, 1.6, a2) * 0.8)
    binder = 1 - stones
    stone_col = lerp(np.broadcast_to(hexc("#8f8b84"), (h, w, 3)), hexc("#5d5a56"),
                     np.clip(0.5 + 0.5 * fnoise((h, w), lo=80, beta=0.3, seed=seed + 1), 0, 1))
    bind_col = np.broadcast_to(hexc("#3a3a3a"), (h, w, 3))
    col = lerp(bind_col, stone_col, stones * 0.85)
    hgt = stones * 0.0012 - binder * 0.0006
    # patches: rectangular newer asphalt with seams
    patch = np.zeros((h, w), np.float32)
    yy, xx = np.mgrid[0:h, 0:w]
    for _ in range(5):
        cx, cy = rng.uniform(0, w), rng.uniform(0, h)
        pw, ph = rng.uniform(0.4, 1.6) / px, rng.uniform(0.3, 1.2) / px
        dx = np.abs((xx - cx + w / 2) % w - w / 2); dy = np.abs((yy - cy + h / 2) % h - h / 2)
        patch = np.maximum(patch, (dx < pw / 2) & (dy < ph / 2))
    patch = blur(patch.astype(np.float32), 2.5)
    seam = np.clip(np.abs(np.gradient(patch)[0]) + np.abs(np.gradient(patch)[1]), 0, 1) * 4
    col = lerp(col, col * 0.80, patch * 0.85)
    hgt = hgt + patch * 0.002
    # weathering (oxidised lighter grey), oil stains, cracks sealed with tar
    ox = smooth(-1.0, 1.5, fnoise((h, w), lo=1, hi=10, beta=2, seed=seed + 2))
    col = lerp(col, col * 1.25 + 0.04, (ox * (1 - patch) * 0.6)[..., None])
    oil = smooth(1.2, 2.4, fnoise((h, w), lo=2, hi=30, beta=1.6, seed=seed + 3))
    col = col * (1 - 0.35 * oil)[..., None]
    cr = fnoise((h, w), lo=2, hi=40, beta=1.6, seed=seed + 4)
    crack = np.exp(-(cr / 0.025) ** 2) * smooth(0.3, 1.0, fnoise((h, w), lo=1, hi=5, beta=2, seed=seed + 5))
    tar = np.exp(-(cr / 0.06) ** 2) * smooth(0.6, 1.2, fnoise((h, w), lo=1, hi=5, beta=2, seed=seed + 6))
    col = lerp(col, np.array([0.03, 0.03, 0.03]), np.clip(crack * 0.9 + tar * 0.7, 0, 1))
    hgt = hgt - crack * 0.003 + tar * 0.0008
    # white edge line remnant: 0.15 m wide, at u = 0.30..0.45 m, worn through (only fragments)
    u = xx * px
    line = smooth(0.30, 0.305, u) * (1 - smooth(0.445, 0.45, u))
    wearl = smooth(-0.3, 0.6, fnoise((h, w), lo=2, hi=60, beta=1.4, seed=seed + 7)) * smooth(0.2, 0.8, stones + 0.3)
    paint = line * wearl * (1 - patch)
    col = lerp(col, hexc("#dedbd2") * (1 - 0.15 * oil)[..., None], paint * 0.92)
    hgt = hgt + paint * 0.0007
    rough = 0.9 - 0.15 * paint - 0.25 * oil - 0.05 * stones
    return finish_height(np.clip(col, 0, 1), hgt, rough, size_m, ao_radius_m=0.01, name=name, category="ground",
                         tags=["modern"], notes="white edge-line remnant at u = 0.30-0.45 m (put u=0 at the road edge)",
                         **kw)


def stamp_stones(w, h, px, n, r_m, seed, elong=(1.0, 1.6), height_k=0.6, hmap=None, idmap=None):
    """Stamp n rounded stones (radius range r_m metres) into a wrap-around height map (max blend)."""
    rng = np.random.default_rng(seed)
    hm = np.full((h, w), -1.0, np.float32) if hmap is None else hmap
    ids = np.full((h, w), -1, np.int32) if idmap is None else idmap
    for k in range(n):
        r = rng.uniform(*r_m) / px
        e = rng.uniform(*elong)
        a = rng.uniform(0, np.pi)
        cx, cy = rng.uniform(0, w), rng.uniform(0, h)
        R_ = int(r * e) + 2
        ys = (np.arange(int(cy) - R_, int(cy) + R_ + 1)) % h
        xs = (np.arange(int(cx) - R_, int(cx) + R_ + 1)) % w
        oy = np.arange(int(cy) - R_, int(cy) + R_ + 1) - cy
        ox = np.arange(int(cx) - R_, int(cx) + R_ + 1) - cx
        X, Y = np.meshgrid(ox, oy)
        xr = (X * np.cos(a) + Y * np.sin(a)) / (r * e)
        yr = (-X * np.sin(a) + Y * np.cos(a)) / r
        d2 = xr * xr + yr * yr
        z = np.sqrt(np.clip(1 - d2, 0, 1)) * r * px * height_k + rng.uniform(-0.2, 0.2) * r * px
        z = np.where(d2 < 1, z, -1)
        sub = hm[np.ix_(ys, xs)]
        better = z > sub
        sub = np.where(better, z, sub)
        hm[np.ix_(ys, xs)] = sub
        sid = ids[np.ix_(ys, xs)]
        ids[np.ix_(ys, xs)] = np.where(better, k, sid)
    return hm, ids


def gravel(name="gravel", size_m=(1.0, 1.0), seed=51, res=R, **kw):
    w = h = res
    px = size_m[0] / w
    base = fnoise((h, w), lo=2, hi=60, beta=1.5, seed=seed) * 0.002 - 0.004
    hm, ids = stamp_stones(w, h, px, 2600, (0.004, 0.011), seed, elong=(1.0, 1.7), height_k=0.55)
    hm, ids = stamp_stones(w, h, px, 900, (0.006, 0.016), seed + 1, elong=(1.0, 1.5), height_k=0.6, hmap=hm, idmap=ids)
    is_st = ids >= 0
    hm = np.where(is_st, hm, base)
    hm = np.maximum(hm, base)
    rng = np.random.default_rng(seed + 2)
    pal = np.array([hexc(c) for c in ("#9b968c", "#b1aa9c", "#7f7a72", "#c1b8a7", "#6e6b66", "#a08f7b", "#8e8d88")])
    sc = pal[rng.integers(0, len(pal), 4000)] * rng.uniform(0.85, 1.15, (4000, 1))
    col = np.where(is_st[..., None], sc[np.maximum(ids, 0) % 4000], hexc("#4f4a42"))
    gm, gh = granite_grain((h, w), seed + 3, px, 0.6)
    col = col * lerp(np.ones_like(gm), gm, 0.5)
    hm = hm + gh
    rough = np.where(is_st, 0.7, 0.95).astype(np.float32)
    return finish_height(np.clip(col, 0, 1), hm, rough, size_m, ao_radius_m=0.015, ao_strength=1.3, name=name,
                         category="ground", tags=["temple", "generic"], cavity_dark=0.3, **kw)


def earth_moss(name="earth_moss", size_m=(2.0, 2.0), seed=61, res=R, **kw):
    w = h = res
    px = size_m[0] / w
    big = fnoise((h, w), lo=1, hi=12, beta=2.5, seed=seed)
    hm = big * 0.006 + fnoise((h, w), lo=20, hi=None, beta=1.3, seed=seed + 1) * 0.0012
    pb, pid = stamp_stones(w, h, px, 900, (0.002, 0.008), seed + 2, height_k=0.4)
    hm = np.maximum(hm, pb - 0.004)
    stone = (pid >= 0) & (pb - 0.004 >= hm - 1e-6)
    col = lerp(np.broadcast_to(hexc("#7a6448"), (h, w, 3)), hexc("#5a4632"),
               np.clip(0.5 + 0.4 * fnoise((h, w), lo=2, hi=40, beta=1.8, seed=seed + 3), 0, 1))
    col = np.where(stone[..., None], hexc("#9a9184") * (0.85 + 0.3 * np.random.default_rng(seed).random((h, w, 1))), col)
    # moss in the lower, damp areas: fluffy height, two greens
    mm = smooth(-0.1, 0.9, -big * 0.9 + 0.6 * fnoise((h, w), lo=4, hi=50, beta=1.4, seed=seed + 4))
    fluff = fnoise((h, w), lo=150, hi=None, beta=0.5, seed=seed + 5)
    mcol = lerp(np.broadcast_to(hexc("#3d4720"), (h, w, 3)), hexc("#56602c"), np.clip(0.5 + 0.5 * fluff, 0, 1))
    mcol = lerp(mcol, hexc("#2f3a17"), smooth(0.5, 1.5, -fnoise((h, w), lo=10, hi=80, beta=1, seed=seed + 6)))
    col = lerp(col, mcol, mm)
    hm = hm + mm * (0.003 + fluff * 0.0006)
    leaf = smooth(2.2, 2.7, fnoise((h, w), lo=30, hi=200, beta=0.6, seed=seed + 7))
    col = lerp(col, hexc("#6b4a2a"), leaf * 0.7)
    rough = 0.95 - 0.05 * mm
    return finish_height(np.clip(col, 0, 1), hm, rough, size_m, ao_radius_m=0.02, name=name, category="ground",
                         tags=["traditional", "temple"], **kw)


def kerb(name="kerb_granite", size_m=(2.4, 0.6), seed=71, **kw):
    w, h = 2048, 512
    px = size_m[0] / w
    col, hm, rough = granite_paving("tmp", (size_m[0], size_m[0]), row_m=size_m[1] * 4, len_m=(0.6, 1.0),
                                    base_hex="#a7a197", seed=seed, joint_m=0.008, bevel_m=0.006, flamed=0.7,
                                    res=w, write=False, row_jitter=0)
    col, hm, rough = col[:h], hm[:h], rough[:h]
    # kerb arris: worn rounded line at v=0.33 (top face / front face break)
    yy = np.mgrid[0:h, 0:w][0] * px
    ar = np.exp(-((yy - 0.6 * 0.66) / 0.006) ** 2)
    hm = hm + ar * 0.002
    col = col * (1 + 0.1 * ar)[..., None]
    nrm = height_to_normal(hm, px, wrap=False)
    ao = ao_from_height(hm, px, 0.02, wrap=False)
    return write_set(name, col, nrm, ao, rough, size_m=size_m, category="ground", tags=["traditional", "granite"],
                     notes="tiles in u only; v 0-0.4 m = top face, 0.4-0.6 m = street face", res_bl=(2048, 512),
                     res_web=(1024, 256), **kw)


def stone_steps(name="stone_steps_trim", size_m=(2.4, 1.2), seed=81, **kw):
    """Trim sheet: v (from bottom of texture) 0.00-0.20 riser, 0.20-0.24 nosing arris, 0.24-0.66 tread A,
    0.66-0.86 riser B (mossy), 0.86-1.20 tread B (older, mossy joints). Tiles in u."""
    w, h = 2048, 1024
    px = size_m[0] / w
    out_c = np.zeros((h, w, 3), np.float32); out_h = np.zeros((h, w), np.float32); out_r = np.zeros((h, w), np.float32)
    rows = h  # image rows top->bottom; v = 1 - row/h
    vv = (1 - (np.mgrid[0:h, 0:w][0] + 0.5) / h) * size_m[1]
    bands = [(0.0, 0.24, "riser", 0.0, seed), (0.24, 0.66, "tread", 0.0, seed + 1),
             (0.66, 0.86, "riser", 0.6, seed + 2), (0.86, 1.2, "tread", 0.8, seed + 3)]
    for v0, v1, kind, moss, sd in bands:
        c, hh, r = granite_paving("tmp", (size_m[0], size_m[0]), row_m=4.0, len_m=(0.7, 1.3), base_hex="#a39d93",
                                  seed=sd, joint_m=0.008, bevel_m=0.01, flamed=1.0 if kind == "tread" else 0.6,
                                  res=w, write=False, row_jitter=0, moss=moss, wear=0.8)
        m = (vv >= v0) & (vv < v1)
        out_c[m] = c[:h][m]; out_h[m] = hh[:h][m]; out_r[m] = r[:h][m]
        # worn, rounded front arris at the top of each riser band, darker underside shadow
        if kind == "riser":
            t = (vv - v0) / (v1 - v0)
            ar = np.exp(-((t - 0.92) / 0.05) ** 2) * m
            out_h += ar * 0.004
            out_c *= (1 - 0.25 * np.exp(-((t - 0.05) / 0.08) ** 2) * m)[..., None]
        if moss:
            mm = smooth(0.4, 1.4, fnoise((h, w), lo=2, hi=40, beta=1.6, seed=sd + 9)) * moss * m
            # moss creeps from the joint with the riser below
            edge = np.exp(-((vv - v0) / 0.05) ** 2) * m
            mm = np.clip(mm * 0.5 + edge * moss * smooth(-0.5, 0.8, fnoise((h, w), lo=8, hi=80, seed=sd + 10)), 0, 1)
            out_c = lerp(out_c, hexc("#4e5b26") * (0.8 + 0.4 * np.random.default_rng(sd).random((h, w, 1))), mm * 0.85)
            out_h += mm * 0.002
            out_r = lerp(out_r, 0.95, mm)
    nrm = height_to_normal(out_h, px, wrap=False)
    ao = ao_from_height(out_h, px, 0.02, wrap=False)
    return write_set(name, np.clip(out_c, 0, 1), nrm, ao, out_r, size_m=size_m, category="ground", kind="trim",
                     tags=["traditional", "granite"],
                     notes="trim sheet, tiles in u. v bands (m from bottom): riser 0-0.20, nosing 0.20-0.24, "
                           "tread 0.24-0.66, mossy riser 0.66-0.86, mossy tread 0.86-1.20",
                     extra={"bands_m": {"riser": [0.0, 0.24], "tread": [0.24, 0.66], "riser_mossy": [0.66, 0.86],
                                        "tread_mossy": [0.86, 1.2]}},
                     res_bl=(2048, 1024), res_web=(1024, 512), **kw)


# ============================================================================ misc
def ishigaki(name="ishigaki_mossy", size_m=(3.0, 3.0), seed=91, res=R, **kw):
    """Nozura-zumi (rough boulder) retaining wall with mossy joints."""
    w = h = res
    px = size_m[0] / w
    f1, f21, cid = cells((h, w), 44, seed, jitter=0.85)
    n = cid.max() + 1
    # stones: rounded by distance to the cell border (F2-F1), irregular
    rough_e = fnoise((h, w), lo=6, hi=120, beta=1.2, seed=seed + 1)
    d = f21 * px + rough_e * 0.012
    gap = 1 - smooth(0.006, 0.03, d)
    bulge = np.sqrt(np.clip(d / 0.18, 0, 1)) * 0.10
    facet = fnoise((h, w), lo=8, hi=60, beta=2.4, seed=seed + 2) * 0.012
    hm = bulge + facet * (1 - gap) - gap * 0.06
    gm, gh = granite_grain((h, w), seed + 3, px, 1.3)
    hm += gh * 2
    tone = per_id(cid, n, seed + 4, -1, 1)
    hue = per_id(cid, n, seed + 5, -1, 1)
    base = hexc("#8f8a82")
    col = base[None, None] * (1 + 0.15 * tone)[..., None] * (1 + 0.06 * hue[..., None] * np.array([1, 0, -1]))
    col = col * lerp(np.ones_like(gm), gm, 0.6)
    lich = smooth(0.8, 1.8, fnoise((h, w), lo=6, hi=80, beta=1.3, seed=seed + 6))
    col = lerp(col, hexc("#b9b6a2"), lich * 0.5)
    stain = smooth(-0.2, 1.4, fnoise((h, w), lo=1, hi=20, beta=2, seed=seed + 7, aniso=(1, 0.2)))
    col = col * (1 - 0.3 * stain)[..., None]
    mm = np.clip(gap * 1.2 + smooth(0.6, 1.6, fnoise((h, w), lo=4, hi=60, beta=1.5, seed=seed + 8)) * (1 - smooth(0.03, 0.12, d)), 0, 1)
    fl = fnoise((h, w), lo=150, beta=0.5, seed=seed + 9)
    mcol = lerp(np.broadcast_to(hexc("#3e4d1c"), (h, w, 3)), hexc("#68782a"), np.clip(0.5 + 0.5 * fl, 0, 1))
    col = lerp(col, mcol, mm * 0.9)
    col = lerp(col, np.array([0.05, 0.05, 0.04]), gap * (1 - mm) * 0.8)
    hm += mm * 0.006 * (1 + 0.3 * fl)
    rough = 0.85 + 0.1 * mm
    return finish_height(np.clip(col, 0, 1), hm, rough, size_m, ao_radius_m=0.08, ao_strength=1.2, name=name,
                         category="misc", tags=["traditional", "stone"], **kw)


def takegaki(name="bamboo_fence_kenninji", size_m=(1.8, 1.8), seed=101, res=R, **kw):
    """Kenninji-gaki: vertical split bamboo (~6 cm), horizontal split-bamboo press bars (oshibuchi) at 0.3/0.9/1.5 m,
    tied with black shuro rope."""
    w = h = res
    px = size_m[0] / w
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    lay = bond_layout(w, h, h, (0.05 / px, 0.075 / px), seed, row_jitter=0, stagger=False, ydist=False)
    sid = lay["id"]; ex = lay["ex"]; sw = lay["sw"]
    t = ex / np.maximum(sw, 1)
    prof = np.sqrt(np.clip(1 - (2 * t - 1) ** 2, 0, 1)) * 0.012
    # nodes (fushi) every ~0.3 m per culm, offset per strip
    off = per_id(sid, lay["n"], seed + 1, 0, 0.3)
    node_v = ((yy * px + off) % 0.31) / 0.31
    node = np.exp(-((node_v - 0.5) / 0.012) ** 2)
    hm = prof + node * 0.0015
    fib = fnoise((h, w), lo=10, beta=0.6, seed=seed + 2, aniso=(1, 0.03))
    age = per_id(sid, lay["n"], seed + 3, 0, 1)
    c_new = hexc("#b39a64"); c_old = hexc("#7d6e55")
    col = lerp(np.broadcast_to(c_new, (h, w, 3)), c_old, np.clip(age * 0.7 + 0.2 * fib, 0, 1)[..., None])
    col = col * (1 + 0.08 * fib)[..., None] * (1 - 0.25 * node)[..., None]
    col = lerp(col, np.array([0.05, 0.045, 0.04]), (1 - smooth(0.02, 0.09, t * (1 - t) * 4))[..., None] * 0.9)
    stain = smooth(0.0, 1.5, fnoise((h, w), lo=1, hi=15, beta=2, seed=seed + 4, aniso=(1, 0.2)))
    col = col * (1 - 0.25 * stain)[..., None]
    # oshibuchi bars
    for yb in (0.3, 0.9, 1.5):
        yc = (size_m[1] - yb) / px
        bar_t = (yy - yc) / (0.035 / px)
        m = np.abs(bar_t) < 1
        bp = np.sqrt(np.clip(1 - bar_t ** 2, 0, 1)) * 0.022 + 0.014
        hm = np.where(m, np.maximum(hm, bp), hm)
        bcol = c_old * (1 + 0.1 * fnoise((h, w), lo=10, beta=0.6, seed=seed + 5, aniso=(0.03, 1)))[..., None]
        col = np.where(m[..., None], bcol, col)
        # rope ties every ~0.3 m
        for xc in np.arange(0.15, size_m[0], 0.3) / px:
            dx = np.abs((xx - xc + w / 2) % w - w / 2)
            rope = (dx < 0.012 / px) & (np.abs(yy - yc) < 0.05 / px)
            twist = 0.5 + 0.5 * np.sin((yy - yc) * px / 0.006 * np.pi + dx * px / 0.004)
            hm = np.where(rope, np.maximum(hm, 0.04 + 0.002 * twist), hm)
            col = np.where(rope[..., None], np.array([0.06, 0.05, 0.045]) * (0.7 + 0.6 * twist)[..., None], col)
    rough = 0.55 + 0.25 * age + 0.1 * stain
    return finish_height(np.clip(col, 0, 1), hm, rough, size_m, ao_radius_m=0.04, name=name, category="misc",
                         tags=["traditional"], **kw)


def bark(name="bark_pine", size_m=(1.0, 1.0), seed=111, res=R, **kw):
    """Japanese black pine (kuromatsu) bark: thick polygonal plates with deep fissures."""
    w = h = res
    px = size_m[0] / w
    f1, f21, cid = cells((h, w), 160, seed, jitter=0.9)
    # stretch plates vertically
    d = f21 * px
    plate = smooth(0.002, 0.02, d + fnoise((h, w), lo=10, hi=150, beta=1.2, seed=seed + 1) * 0.004)
    flake = fnoise((h, w), lo=20, hi=200, beta=1.2, seed=seed + 2, aniso=(1, 0.5))
    hm = plate * (0.012 + 0.004 * flake) + (1 - plate) * -0.01
    layers = np.floor(np.clip(0.5 + 0.5 * fnoise((h, w), lo=10, hi=60, beta=1.5, seed=seed + 3), 0, 0.999) * 3) / 3
    hm += layers * 0.003 * plate
    n = cid.max() + 1
    tone = per_id(cid, n, seed + 4, -1, 1)
    col = lerp(np.broadcast_to(hexc("#4a3a30"), (h, w, 3)), hexc("#6d5646"), np.clip(0.5 + 0.3 * tone + 0.2 * flake, 0, 1))
    col = lerp(col, hexc("#7b5a3f"), (smooth(0.4, 0.8, layers) * plate * 0.5)[..., None])
    col = lerp(col, np.array([0.06, 0.05, 0.04]), (1 - plate) * 0.85)
    lich = smooth(1.2, 2.0, fnoise((h, w), lo=6, hi=60, beta=1.3, seed=seed + 5))
    col = lerp(col, hexc("#8d9478"), lich * plate * 0.5)
    rough = 0.9 + 0.05 * flake
    return finish_height(np.clip(col, 0, 1), hm, rough, size_m, ao_radius_m=0.03, ao_strength=1.2, name=name,
                         category="misc", tags=["vegetation"], **kw)


# ============================================================================ roofs (non-kawara)
def copper_roof(name="roof_copper_patina", size_m=(1.8, 1.8), seed=121, res=R, **kw):
    """Hira-buki copper roofing: small staggered plates (~0.30 x 0.18 m working size) with folded seams,
    verdigris patina (rokushō) with darker run-off streaks."""
    w = h = res
    px = size_m[0] / w
    lay = bond_layout(w, h, 0.18 / px, (0.30 / px, 0.30 / px), seed, row_jitter=0.0)
    d = lay["dist"]
    seam = np.exp(-(d / (0.004 / px)) ** 2)
    eyn = lay["ey"] / np.maximum(lay["sh"], 1)
    hm = seam * 0.003 + (1 - eyn) * 0.002 + fnoise((h, w), lo=10, hi=80, beta=2, seed=seed) * 0.0006
    pat = fnoise((h, w), lo=1, hi=40, beta=1.6, seed=seed + 1)
    streak = fnoise((h, w), lo=2, hi=80, beta=1.5, seed=seed + 2, aniso=(1, 0.06))
    green = lerp(np.broadcast_to(hexc("#6b9285"), (h, w, 3)), hexc("#4a6a60"), np.clip(0.5 + 0.35 * pat, 0, 1))
    brown = hexc("#5a4030")
    col = lerp(green, brown, smooth(0.8, 2.0, -pat + 0.5 * streak) * 0.7)
    col = col * (1 - 0.25 * smooth(0.3, 1.8, streak))[..., None]
    col = lerp(col, hexc("#9bb8aa"), smooth(1.6, 2.4, fnoise((h, w), lo=40, beta=0.6, seed=seed + 3)) * 0.3)
    col = col * (1 - 0.3 * seam)[..., None]
    rough = 0.75 + 0.1 * pat
    metal = 0.15 + 0.2 * smooth(0.8, 2.0, -pat)
    return finish_height(np.clip(col, 0, 1), hm, rough, size_m, metal=metal, ao_radius_m=0.01, name=name,
                         category="roof", tags=["temple"], **kw)


def metal_seam_roof(name="roof_metal_seam", size_m=(1.82, 1.82), seed=131, res=R, **kw):
    """Galvalume standing-seam roof (modern): seams every 0.455 m (quarter ken), dark grey."""
    w = h = res
    px = size_m[0] / w
    xx = np.mgrid[0:h, 0:w][1] * px
    t = (xx % 0.455) / 0.455
    seam = np.exp(-((t - 0.5) / (0.012 / 0.455)) ** 2)
    rib = np.exp(-((t % 0.25 - 0.125) / 0.01) ** 2) * 0.3
    hm = seam * 0.025 + rib * 0.001 + fnoise((h, w), lo=1, hi=10, beta=2, seed=seed) * 0.0008
    streak = fnoise((h, w), lo=1, hi=60, beta=1.6, seed=seed + 1, aniso=(1, 0.05))
    col = np.broadcast_to(hexc("#4d5152"), (h, w, 3)) * (1 + 0.05 * streak)[..., None]
    col = col * (1 - 0.2 * smooth(1.0, 2.2, -streak))[..., None]
    dust = smooth(0.5, 2.0, fnoise((h, w), lo=1, hi=20, beta=2, seed=seed + 2))
    col = lerp(col, hexc("#7d776c"), dust * 0.3)
    rough = 0.45 + 0.25 * dust
    metal = 0.75 - 0.4 * dust
    return finish_height(np.clip(col, 0, 1), hm, rough, size_m, metal=metal, ao_radius_m=0.03, name=name,
                         category="roof", tags=["modern"], **kw)


def cement_slate_roof(name="roof_cement_slate", size_m=(1.82, 1.82), seed=141, res=R, **kw):
    """Colonial/cement slate (modern houses): 0.91 x 0.182 m working rows... 4 slates per 0.91 m, row 0.182 m."""
    w = h = res
    px = size_m[0] / w
    lay = bond_layout(w, h, 0.182 / px, (0.2275 / px, 0.2275 / px), seed, row_jitter=0.0)
    eyn = lay["ey"] / np.maximum(lay["sh"], 1)
    d = lay["dist"]
    gap = 1 - smooth(1.0, 2.5, d)
    sid = lay["id"]
    hm = (1 - eyn) * 0.006 + fnoise((h, w), lo=30, beta=1.2, seed=seed) * 0.0004 - gap * 0.004
    # vertical slits between slates are grooves only (rows overlap): emphasise bottom edge shadow
    edge = np.exp(-((1 - eyn) * lay["sh"] / (0.003 / px)) ** 2)
    tone = per_id(sid, lay["n"], seed + 1, -1, 1)
    col = np.broadcast_to(hexc("#575a5c"), (h, w, 3)) * (1 + 0.06 * tone)[..., None]
    lich = smooth(1.3, 2.2, fnoise((h, w), lo=10, hi=100, beta=1.2, seed=seed + 2))
    col = lerp(col, hexc("#9a9c8a"), lich * 0.5)
    fade = smooth(-0.5, 1.5, fnoise((h, w), lo=1, hi=12, beta=2, seed=seed + 3))
    col = lerp(col, hexc("#8a8a86"), fade * 0.35)
    col = col * (1 - 0.5 * edge - 0.6 * gap)[..., None]
    rough = 0.8 + 0.1 * lich
    return finish_height(np.clip(col, 0, 1), hm, rough, size_m, ao_radius_m=0.01, name=name, category="roof",
                         tags=["modern"], **kw)


# ============================================================================ catalogue
def build_all(only=None):
    jobs = [
        ("timber_planks_weathered", lambda: timber()),
        ("timber_planks_bengara", lambda: timber("timber_planks_bengara", palette="bengara", seed=12, weather=0.4)),
        ("plaster_lime", lambda: plaster("plaster_lime", "lime", seed=21)),
        ("plaster_ochre", lambda: plaster("plaster_ochre", "ochre", seed=22)),
        ("plaster_cream", lambda: plaster("plaster_cream", "cream", seed=23)),
        ("plaster_earth", lambda: plaster("plaster_earth", "earth", seed=24)),
        ("ishidatami_granite", lambda: granite_paving(
            "ishidatami_granite", (2.4, 2.4), row_m=0.30, len_m=(0.45, 0.85), base_hex="#a9a39a", seed=31,
            joint_m=0.010, bevel_m=0.012, flamed=1.0, wear=0.6, tags=("traditional",),
            notes="Ninenzaka/Sannenzaka/Yasaka-dori east granite slabs ~0.30 x 0.45-0.85 m, running bond "
                  "(evidence: observed ~0.3 x 0.6 m). Rows run along u: put u across the street.")),
        ("setts_granite", lambda: granite_paving(
            "setts_granite", (1.6, 1.6), row_m=0.10, len_m=(0.16, 0.24), base_hex="#8a857a", seed=32,
            joint_m=0.011, bevel_m=0.01, flamed=1.2, domed=0.004, wear=0.7, joint_col=(0.24, 0.22, 0.19),
            notes="Yasaka-dori west small rough-flamed granite setts ~0.10 x 0.16-0.24 m, running bond "
                  "(OSM surface=sett; size inferred)")),
        ("asphalt_worn", lambda: asphalt()),
        ("gravel", lambda: gravel()),
        ("earth_moss", lambda: earth_moss()),
        ("kerb_granite", lambda: kerb()),
        ("stone_steps_trim", lambda: stone_steps()),
        ("ishigaki_mossy", lambda: ishigaki()),
        ("bamboo_fence_kenninji", lambda: takegaki()),
        ("bark_pine", lambda: bark()),
        ("roof_copper_patina", lambda: copper_roof()),
        ("roof_metal_seam", lambda: metal_seam_roof()),
        ("roof_cement_slate", lambda: cement_slate_roof()),
    ]
    for nm, fn in jobs:
        if only and not any(o in nm for o in only):
            continue
        print("surface", nm)
        fn()
