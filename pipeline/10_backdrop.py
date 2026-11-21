"""Phase 10: accurate distant backdrop (terrain rings, PLATEAU city massing, hill canopy, horizon ring).

  /home/user/venv/bin/python pipeline/backdrop_plateau.py luse 523536 523546
  /home/user/venv/bin/python pipeline/backdrop_plateau.py bldg 52353670 ... 52354614   (25 meshes, see MESHES)
  /home/user/venv/bin/python pipeline/10_backdrop.py [render] [web]   (GSI tiles fetched + cached on first run)

Inputs (fetched/cached by the helpers):
  * GSI DEM5A/5B z15 (+ DEM10B z14 fallback) for |x|,|y| <= 3.3 km, DEM10B z12 for the 15 km horizon ring
  * GSI seamlessphoto z16 (+ z12) orthophoto  -> ground / roof colours (measured, white-balanced, muted)
  * PLATEAU 2025 Kyoto bldg, 5 x 5 third-order meshes around 52353692 -> LOD1 prisms (+ LOD2 near / landmarks)
  * PLATEAU 2025 Kyoto luse 523536 + 523546 class 203 (山林) -> forest mask (orthophoto colour fallback outside)
  * data/processed/terrain.npz (inner 2 m terrain, +-300 m)  -> exact seam
Outputs:
  data/processed/backdrop_render.npz, backdrop_web.npz   (per object: V float32 local x/y/z, F int32, C uint8 sRGB)
  data/processed/backdrop_meta.json                       (sources, extents, counts, measured-vs-artistic)
Frame: local x east / y north / z T.P. m (EPSG:6674, origin E -20160 N -111160), like the rest of the project.
"""
import json
import os
import sys
import time
import zlib

import mapbox_earcut as earcut
import numpy as np
from PIL import Image, ImageDraw
from scipy.ndimage import distance_transform_edt, gaussian_filter, map_coordinates, median_filter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import PROC, RAW, load_boundary  # noqa: E402
import backdrop_gsi as gsi  # noqa: E402
from terrain_sample import ground as inner_ground, X0 as IX0, STEP as ISTEP, NX as INX  # noqa: E402

T0 = time.time()
BND = load_boundary()
INNER = 300.0                      # half-size of the existing 2 m terrain (terrain.npz)
R_EARTH, K_REFR = 6371000.0, 0.13  # curvature drop d^2/2R*(1-k), viewer at the box centre
CACHE = os.path.join(RAW, "plateau", "backdrop")
MESHES = [a + str(d) for a in ("5235367", "5235368", "5235369", "5235460", "5235461") for d in range(5)]

DETAIL = {
    # rings: (hole half-size a, outer half-size b, grid step s); a strip zips the previous ring's outer loop
    "render": dict(rings=[(INNER, 1008.0, 4.0), (1008.0, 3024.0, 12.0), (3024.0, 15120.0, 72.0)],
                   canopy="separate", lod2=True, sink=(0.4, 1.0)),
    "web": dict(rings=[(INNER, 1008.0, 12.0), (1008.0, 3024.0, 48.0), (3024.0, 15120.0, 252.0)],
                canopy="integrated", lod2="landmarks", sink=(0.8, 2.5)),
}
RING_NAMES = ["A", "B", "C"]


def log(*a):
    print("[%5.0fs]" % (time.time() - T0), *a, flush=True)


# =============================================================== rasters
log("fetching / loading GSI tiles")
DEM15, DEM15_SRC, dem15_info = gsi.fused_dem15(3300.0)
DEM12, dem12_info = gsi.mosaic("dem_png", 12, 15600.0)
DEM12.a = np.where(np.isnan(DEM12.a), np.nanmin(DEM12.a), DEM12.a)
ORT16, ort16_info = gsi.mosaic("seamlessphoto", 16, 3200.0, ext="jpg", kind="rgb")
ORT12, ort12_info = gsi.mosaic("seamlessphoto", 12, 15600.0, ext="jpg", kind="rgb")
PX_M = {12: 31.3, 14: 7.83, 15: 3.91, 16: 1.96}   # Web-Mercator pixel size at 35 N (m)

# white balance: grey-world over low-saturation (built-up) pixels of the 6 km orthophoto
o = ORT16.a.reshape(-1, 3)
sat = o.max(1) - o.min(1)
grey = o[(sat < 25) & (o.mean(1) > 60) & (o.mean(1) < 200)]
WB = grey.mean(0).mean() / grey.mean(0)
log("orthophoto white-balance gains", WB.round(3))
ORT16.a *= WB
ORT12.a *= WB

_blur_cache = {}


def blurred(m, sigma, key):
    """Mosaic array pre-filtered for a grid step (anti-aliasing); cached."""
    if sigma < 0.6:
        return m.a
    k = (key, round(sigma, 1))
    if k not in _blur_cache:
        a = m.a
        _blur_cache[k] = (np.stack([gaussian_filter(a[..., c], sigma) for c in range(3)], -1) if a.ndim == 3
                          else gaussian_filter(a, sigma))
    return _blur_cache[k]


def curvature(x, y):
    d2 = np.asarray(x, float) ** 2 + np.asarray(y, float) ** 2
    return d2 / (2 * R_EARTH) * (1 - K_REFR)


def rinf(x, y):
    return np.maximum(np.abs(x), np.abs(y))


def ground_dem15(x, y, s):
    """Bare-earth height for the 6 km area, seam-corrected toward the inner 2 m terrain."""
    a = blurred(DEM15, 0.35 * s / PX_M[15], "dem15")
    h = DEM15.sample(x, y, a)
    r = rinf(x, y)
    w = np.clip(1 - (r - INNER) / 120.0, 0, 1)
    if np.any(w > 0):
        px = np.clip(x, -INNER, INNER); py = np.clip(y, -INNER, INNER)
        delta = inner_ground(px, py) - DEM15.sample(px, py)
        h = h + w * delta
    return h - curvature(x, y)


def ground_dem12(x, y, s):
    a = blurred(DEM12, 0.35 * s / PX_M[12], "dem12")
    return DEM12.sample(x, y, a) - curvature(x, y)


def ortho(x, y, s):
    """sRGB 0..255 ground colour at a grid of step s (pre-filtered)."""
    if rinf(np.atleast_1d(x), np.atleast_1d(y)).max() <= 3150:
        return ORT16.sample(x, y, blurred(ORT16, 0.5 * s / PX_M[16], "o16"))
    return ORT12.sample(x, y, blurred(ORT12, 0.5 * s / PX_M[12], "o12"))


# ---------------------------------------------------------------- forest mask
def luse_polys():
    out = []
    for m in ("523536", "523546"):
        d = np.load(os.path.join(CACHE, "luse_%s.npz" % m))
        codes = json.loads(str(d["meta"]))["codes"]
        xy, off, cl = d["ring_xy"], d["ring_off"], d["ring_cls"]
        for k in range(len(cl)):
            out.append((codes[cl[k]], xy[off[k]:off[k + 1]]))
    return out


LUSE = luse_polys()


def raster_masks(half, res):
    """forest (luse 203), luse coverage, at res m over +-half (row 0 = north)."""
    n = int(round(2 * half / res))
    f_im = Image.new("L", (n, n), 0); c_im = Image.new("L", (n, n), 0)
    fd, cd = ImageDraw.Draw(f_im), ImageDraw.Draw(c_im)
    for code, p in LUSE:
        if p[:, 0].max() < -half or p[:, 0].min() > half or p[:, 1].max() < -half or p[:, 1].min() > half:
            continue
        pts = list(zip((p[:, 0] + half) / res, (half - p[:, 1]) / res))
        if len(pts) < 3:
            continue
        cd.polygon(pts, fill=255)
        if code == "203":
            fd.polygon(pts, fill=255)
    return np.asarray(f_im) > 127, np.asarray(c_im) > 127


def ortho_forest(half, res):
    """Orthophoto-colour forest heuristic (only used where PLATEAU luse has no coverage)."""
    n = int(round(2 * half / res))
    c = (np.arange(n) + 0.5) * res - half
    GX, GY = np.meshgrid(c, -c)
    rgb = ortho(GX.ravel(), GY.ravel(), res).reshape(n, n, 3)
    R, G, B = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    lum = 0.3 * R + 0.59 * G + 0.11 * B
    exg = 2 * G - R - B
    f = (exg > 12) & (lum < 120) & (G >= R)
    return median_filter(f.astype(np.uint8), size=5) > 0


class ForestField:
    def __init__(self, half, res):
        self.half, self.res = half, res
        f, cov = raster_masks(half, res)
        heur = ortho_forest(half, res)
        self.src = np.where(cov, 1, 2).astype(np.uint8)          # 1 = PLATEAU luse, 2 = orthophoto heuristic
        f = np.where(cov, f, heur)
        self.mask = f
        # canopy taper (0 at the forest edge -> 1 at 25 m inside)
        dist = distance_transform_edt(f) * res
        self.taper = np.clip(dist / 25.0, 0, 1) ** 0.7
        log("forest raster %.0f m @%.0f m: forest %.1f %%, luse-covered %.1f %%" % (
            half, res, 100 * f.mean(), 100 * cov.mean()))

    def sample(self, x, y, arr=None):
        a = self.taper if arr is None else arr
        n = a.shape[0]
        fx = (np.asarray(x) + self.half) / self.res - 0.5
        fy = (self.half - np.asarray(y)) / self.res - 0.5
        inside = (fx >= 0) & (fx <= n - 1) & (fy >= 0) & (fy <= n - 1)
        v = map_coordinates(a.astype(np.float32), [np.clip(fy, 0, n - 1), np.clip(fx, 0, n - 1)], order=1)
        return np.where(inside, v, 0.0)


log("forest masks")
FOREST_NEAR = ForestField(3100.0, 4.0)
FOREST_FAR = ForestField(15200.0, 32.0)


def forest_w(x, y):
    r = rinf(x, y)
    w = np.where(r < 3050, FOREST_NEAR.sample(x, y), FOREST_FAR.sample(x, y))
    # no backdrop canopy inside / right at the documented inner area
    return w * np.clip((r - INNER - 10) / 50.0, 0, 1)


# value noise (deterministic) for canopy height + autumn colour patches
_rng = np.random.default_rng(20261120)
_LAT = [_rng.random((400, 400)).astype(np.float32) for _ in range(5)]


def _vraw(x, y, scale, k):
    lat = _LAT[k % 5]
    return map_coordinates(lat, [(np.asarray(y) / scale) % 399, (np.asarray(x) / scale) % 399],
                           order=3, mode="grid-wrap", prefilter=False)


_probe = _rng.uniform(0, 30000, (2, 200000))
_NSTAT = [(float(v.mean()), float(v.std())) for v in (_vraw(_probe[0], _probe[1], 1.0, k) for k in range(5))]


def vnoise(x, y, scale, k):
    """Smooth value noise, standardised to mean 0 / std 1 (approximately Gaussian)."""
    m, sd = _NSTAT[k % 5]
    return (_vraw(x, y, scale, k) - m) / sd


def canopy_height(x, y):
    zc = (0.5 * vnoise(x, y, 90.0, 0) + 0.32 * vnoise(x, y, 31.0, 1) + 0.18 * vnoise(x, y, 11.0, 2)) / 0.62
    n = np.clip(0.5 + 0.25 * zc, 0, 1)
    return 12.0 + 8.0 * n                                  # 12-20 m (artistic, not measured)


EVERGREEN = np.array([46, 60, 36], float)     # sRGB; cedar / hinoki / evergreen broadleaf
MAPLE = np.array([108, 46, 28], float)        # late-autumn momiji (deep red-brown at distance)
GINKGO = np.array([110, 90, 46], float)       # yellow-brown deciduous (konara, ginkgo, cherry)


def canopy_colour(x, y, base):
    """Late-autumn canopy (artistic palette) modulated by the measured orthophoto brightness pattern.
    Patch fractions ~7 % maple, ~7 % yellow-brown (tree-group speckle); the evergreen share follows Higashiyama's mixed forest."""
    lum = (0.3 * base[:, 0] + 0.59 * base[:, 1] + 0.11 * base[:, 2]) / 75.0
    mod = np.clip(lum, 0.7, 1.35)[:, None]
    c = EVERGREEN * mod
    # tree-group scale (14-18 m) patches whose density varies at stand scale (70-90 m)
    z1 = 0.92 * vnoise(x, y, 12.0, 3) + 0.4 * vnoise(x, y, 70.0, 1)
    z2 = 0.92 * vnoise(x, y, 16.0, 4) + 0.4 * vnoise(x, y, 90.0, 2)
    m1 = np.clip((z1 - 1.45) / 0.4, 0, 1)[:, None] * 0.7
    m2 = np.clip((z2 - 1.45) / 0.4, 0, 1)[:, None] * 0.55
    c = c * (1 - m2) + GINKGO * mod * m2
    c = c * (1 - m1) + MAPLE * mod * m1
    return np.clip(c, 0, 255)


def ground_colour(rgb, x=None, y=None, jitter=0.0):
    """Measured orthophoto colour, toned for use as albedo: aerial imagery of the built-up basin is bright
    and blue-lavender (atmosphere + sensor), which reads as water from street level. A gamma 1.25 curve,
    x0.92 gain, a further -25 % on non-green (built-up) pixels and a slight warm shift bring it to
    roof/asphalt albedo; saturation x0.8.
    Optional per-vertex luminance jitter (artistic, +-jitter) breaks up the blur of coarse grids."""
    c = 255.0 * (np.clip(rgb, 0, 255) / 255.0) ** 1.25 * 0.92
    exg = 2 * rgb[:, 1] - rgb[:, 0] - rgb[:, 2]
    c = c * (1 - 0.25 * np.clip((10 - exg) / 20, 0, 1))[:, None]    # built-up (non-green) -> urban albedo ~0.12
    lum = (0.3 * c[:, 0] + 0.59 * c[:, 1] + 0.11 * c[:, 2])[:, None]
    c = lum + (c - lum) * 0.8
    c = c * np.array([1.03, 1.0, 0.93])
    if jitter > 0 and x is not None:
        c = c * (1 + jitter * np.clip(vnoise(x, y, 1.0, 2) * 0.5 + vnoise(x, y, 7.0, 0) * 0.5, -2, 2))[:, None]
    return np.clip(c, 0, 255)


# =============================================================== terrain rings
def square_loop(h, s):
    """CCW loop of points on the square of half-size h, spacing s, starting at (-h, -h)."""
    n = int(round(2 * h / s))
    t = -h + np.arange(n) * s
    bot = np.c_[t, np.full(n, -h)]
    right = np.c_[np.full(n, h), t]
    top = np.c_[-t, np.full(n, h)]
    left = np.c_[np.full(n, -h), -t]
    return np.concatenate([bot, right, top, left])


def zipper(nP, nQ, offP, offQ):
    """Triangulate the strip between an inner loop P and outer loop Q (both CCW from the SW corner)."""
    F = []
    i = j = 0
    while i < nP or j < nQ:
        tp = (i + 1) / nP; tq = (j + 1) / nQ
        if (tp <= tq and i < nP) or j >= nQ:
            F.append((offP + i % nP, offQ + j % nQ, offP + (i + 1) % nP)); i += 1
        else:
            F.append((offP + i % nP, offQ + j % nQ, offQ + (j + 1) % nQ)); j += 1
    return np.array(F, np.int64)


def build_rings(cfg):
    """Returns list of ring dicts: x, y, zg, canopy, w, col_ground, col_canopy, faces, outer-loop indices."""
    rings = []
    # inner seam loop: exact heights of terrain.npz
    P = square_loop(INNER, ISTEP)
    prev = dict(x=P[:, 0], y=P[:, 1], zg=inner_ground(P[:, 0], P[:, 1]))
    prev["w"] = np.zeros(len(P)); prev["can"] = np.zeros(len(P))
    prev["cg"] = ground_colour(ortho(P[:, 0], P[:, 1], 4.0)); prev["cc"] = prev["cg"].copy()
    for k, (a, b, s) in enumerate(cfg["rings"]):
        a2 = (np.floor(a / s + 1e-9) + 1) * s
        n = int(round(2 * b / s)) + 1
        xs = -b + np.arange(n) * s
        GX, GY = np.meshgrid(xs, xs)
        R = rinf(GX, GY)
        used = R >= a2 - 1e-6
        vid = -np.ones((n, n), np.int64)
        vid[used] = np.arange(used.sum())
        x = GX[used]; y = GY[used]
        gfun = ground_dem15 if b <= 3100 else ground_dem12
        zg = gfun(x, y, s)
        cg_raw = ortho(x, y, s)
        w = forest_w(x, y)
        can = canopy_height(x, y)
        cg = ground_colour(cg_raw, x / s, y / s, 0.06 if b <= 1100 else 0.09 if b <= 3100 else 0.13)
        cc = canopy_colour(x, y, cg_raw)
        # grid faces (two triangles per cell outside the hole)
        i0 = vid[:-1, :-1]; i1 = vid[:-1, 1:]; i2 = vid[1:, 1:]; i3 = vid[1:, :-1]
        ok = (i0 >= 0) & (i1 >= 0) & (i2 >= 0) & (i3 >= 0)
        q = np.c_[i0[ok], i1[ok], i2[ok], i3[ok]]
        # split along the diagonal that best follows the surface
        zq = zg[q]
        d02 = np.abs(zq[:, 0] - zq[:, 2]); d13 = np.abs(zq[:, 1] - zq[:, 3])
        alt = d02 > d13
        F = np.where(alt[:, None, None],
                     np.stack([q[:, [0, 1, 3]], q[:, [1, 2, 3]]], 1),
                     np.stack([q[:, [0, 1, 2]], q[:, [0, 2, 3]]], 1)).reshape(-1, 3)
        # stitching strip: previous outer loop (copied) -> this ring's inner loop
        Q = square_loop(a2, s)
        qi = vid[np.round((Q[:, 1] + b) / s).astype(int), np.round((Q[:, 0] + b) / s).astype(int)]
        assert (qi >= 0).all()
        nV = len(x); nP = len(prev["x"])
        Pidx = np.arange(nV, nV + nP)
        strip = zipper(nP, len(Q), nV, 0)
        strip[strip < nV] = qi[strip[strip < nV]]
        x = np.r_[x, prev["x"]]; y = np.r_[y, prev["y"]]; zg = np.r_[zg, prev["zg"]]
        w = np.r_[w, prev["w"]]; can = np.r_[can, prev["can"]]
        cg = np.r_[cg, prev["cg"]]; cc = np.r_[cc, prev["cc"]]
        F = np.r_[F, strip]
        skirt = None
        if k == 0:
            skirt = Pidx                      # hang a 3 m skirt under the inner seam (hides any crack)
        O = square_loop(b, s)
        oi = vid[np.round((O[:, 1] + b) / s).astype(int), np.round((O[:, 0] + b) / s).astype(int)]
        ring = dict(name=RING_NAMES[k], a=a, b=b, s=s, x=x, y=y, zg=zg, w=w, can=can, cg=cg, cc=cc, F=F,
                    skirt=skirt, src="DEM15" if b <= 3100 else "DEM12")
        rings.append(ring)
        prev = dict(x=x[oi], y=y[oi], zg=zg[oi], w=w[oi], can=can[oi], cg=cg[oi], cc=cc[oi])
        log("ring %s: %d verts %d tris (step %.0f m, %.0f-%.0f m)" % (RING_NAMES[k], len(x), len(F), s, a, b))
    return rings


def ring_objects(rings, cfg):
    objs = []
    for r in rings:
        x, y, zg, w = r["x"], r["y"], r["zg"], r["w"]
        if cfg["canopy"] == "integrated":
            z = zg + r["can"] * w
            col = r["cg"] * (1 - w[:, None]) + r["cc"] * w[:, None]
        else:
            z = zg; col = r["cg"]
        V = np.c_[x, y, z]; F = r["F"]; C = col
        if r["skirt"] is not None:
            sk = r["skirt"]; n = len(V); m = len(sk)
            V = np.r_[V, V[sk] - [0, 0, 3.0]]; C = np.r_[C, C[sk]]
            a0 = sk; a1 = np.roll(sk, -1); b0 = n + np.arange(m); b1 = np.roll(b0, -1)
            F = np.r_[F, np.c_[a0, b0, a1], np.c_[a1, b0, b1]]   # faces toward the box centre
        objs.append(dict(name="Backdrop_Terrain_%s_%gm" % (r["name"], r["s"]), V=V, F=F, C=C,
                         kind="terrain", artistic=cfg["canopy"] == "integrated",
                         source=("GSI DEM5A z15 (DEM10B z14 fill)" if r["src"] == "DEM15" else "GSI DEM10B z12")
                         + " bare earth; colour GSI seamlessphoto z%d (white-balanced, muted)" % (16 if r["src"] == "DEM15" else 12)
                         + ("; forest cells raised by the artistic canopy (12-20 m)" if cfg["canopy"] == "integrated" else ""),
                         step_m=r["s"], extent_m=[r["a"], r["b"]]))
        if cfg["canopy"] == "separate":
            Fr = r["F"]
            keep = (w[Fr] > 0).any(1)
            Fc = Fr[keep]
            used = np.unique(Fc)
            remap = -np.ones(len(x), np.int64); remap[used] = np.arange(len(used))
            zc = zg[used] - 0.8 + (r["can"][used] + 0.8) * w[used]
            objs.append(dict(name="Backdrop_Canopy_%s" % r["name"], V=np.c_[x[used], y[used], zc], F=remap[Fc],
                             C=r["cc"][used], kind="canopy", artistic=True,
                             source="forest extent: PLATEAU luse class 203 山林 (orthophoto-colour heuristic outside luse coverage); "
                                    "canopy height 12-20 m value noise and late-autumn palette are ARTISTIC",
                             step_m=r["s"], extent_m=[r["a"], r["b"]]))
    return objs


# =============================================================== buildings
def load_buildings():
    inner_ids = {b["id"] for b in json.load(open(os.path.join(PROC, "buildings.json")))["buildings"]}
    out = []
    for m in MESHES:
        p = os.path.join(CACHE, "bldg_%s.npz" % m)
        if not os.path.exists(p):
            log("missing cache", p); continue
        d = np.load(p)
        if "absent" in d:
            continue
        meta = json.loads(str(d["meta"]))["buildings"]
        out.append((m, d, meta, inner_ids))
    return out


def wall_palette():
    """Measured PLATEAU texture wall colours of the inner mesh, bucketed by storeys (<=2, >=3)."""
    L2 = np.load(os.path.join(PROC, "buildings_lod2.npz"))
    blds = json.load(open(os.path.join(PROC, "buildings.json")))["buildings"]
    K, C, BI = L2["kind"], L2["colour"], L2["building"]
    sel = (K == 1) & (C[:, 0] >= 0)
    low, high = [], []
    for bi in np.unique(BI[sel]):
        c = C[sel & (BI == bi)].mean(0)
        (low if blds[bi]["storeys"] <= 2 else high).append(c)
    return np.array(low), np.array(high)


def stable_hash(s):
    return zlib.crc32(s.encode())


def roof_colour(xy):
    cx, cy = xy.mean(0)
    c0 = np.array([cx, cy])
    pts = np.r_[xy * 0.5 + c0 * 0.5, c0[None], xy * 0.25 + c0 * 0.75]
    c = np.median(ORT16.sample(pts[:, 0], pts[:, 1]), axis=0)
    lum = 0.3 * c[0] + 0.59 * c[1] + 0.11 * c[2]
    c = lum + (c - lum) * 0.55                       # roofs: muted (kawara greys, sheet metal, concrete)
    lum2 = np.clip(lum * 0.8, 40, 140)                  # orthophoto roofs read brighter than kawara albedo
    return np.clip(c * (lum2 / max(lum, 1)) * np.array([1.02, 1.0, 0.96]), 0, 255)


def prism(xy, z0, z1, croof, cwall):
    """LOD1 prism: roof (n verts) + wall top ring + wall bottom ring. Returns V, F, C (local indices)."""
    n = len(xy)
    idx = earcut.triangulate_float64(xy.astype(np.float64), np.array([n], np.uint32))
    rt = np.asarray(idx, np.int64).reshape(-1, 3)
    V = np.r_[np.c_[xy, np.full(n, z1)], np.c_[xy, np.full(n, z1)], np.c_[xy, np.full(n, z0)]]
    i = np.arange(n); j = (i + 1) % n
    walls = np.r_[np.c_[2 * n + i, 2 * n + j, n + j], np.c_[2 * n + i, n + j, n + i]]
    F = np.r_[rt, walls]
    C = np.r_[np.tile(croof, (n, 1)), np.tile(cwall, (n, 1)), np.tile(cwall * 0.92, (n, 1))]
    return V, F, C


def simplify_ring(xy, tol, maxv=12):
    from shapely.geometry import Polygon
    p = Polygon(xy)
    if not p.is_valid:
        p = p.buffer(0)
        if p.geom_type != "Polygon":
            return None
    q = p.simplify(tol, preserve_topology=True)
    if q.is_empty or q.geom_type != "Polygon" or q.area < 0.5 * p.area or len(q.exterior.coords) - 1 > maxv:
        q = p.minimum_rotated_rectangle
    c = np.array(q.exterior.coords)[:-1]
    return c if len(c) >= 3 else None


def build_city(cfg, detail, ground_fn):
    lowp, highp = wall_palette()
    acc = {"lod1": ([], [], []), "lod2": ([], [], [])}
    nv = {"lod1": 0, "lod2": 0}
    stats = dict(buildings=0, lod1=0, lod2=0, skipped_inner=0, skipped_web=0, landmarks=[])
    web = detail == "web"
    for mesh, d, meta, inner_ids in load_buildings():
        xy_all, off, rb = d["ring_xy"], d["ring_off"], d["ring_bld"]
        zmin, zmax = d["ring_zmin"], d["ring_zmax"]
        l2t, l2k, l2b = d["lod2_tri"], d["lod2_kind"], d["lod2_bld"]
        order = np.argsort(l2b, kind="stable"); l2b_sorted = l2b[order]
        parts_of = {}
        for k in range(len(rb)):
            parts_of.setdefault(int(rb[k]), []).append(k)
        for bi, rec in enumerate(meta):
            if rec["id"] in inner_ids:
                stats["skipped_inner"] += 1; continue
            ks = parts_of.get(bi, [])
            if not ks:
                continue
            rings = []
            for k in ks:
                xy = xy_all[off[k]:off[k + 1]].astype(np.float64)
                if len(xy) > 3 and np.allclose(xy[0], xy[-1]):
                    xy = xy[:-1]
                keep = np.r_[True, np.any(np.abs(np.diff(xy, axis=0)) > 1e-3, axis=1)]
                xy = xy[keep]
                if len(xy) < 3:
                    continue
                area = 0.5 * np.sum(xy[:, 0] * np.roll(xy[:, 1], -1) - np.roll(xy[:, 0], -1) * xy[:, 1])
                if area < 0:
                    xy = xy[::-1]
                rings.append((xy, abs(area), float(zmin[k]), float(zmax[k])))
            if not rings:
                continue
            allxy = np.concatenate([r[0] for r in rings])
            cx, cy = allxy.mean(0)
            r_inf = max(abs(cx), abs(cy)); dist = float(np.hypot(cx, cy))
            if r_inf > 3020:
                continue
            area = sum(r[1] for r in rings)
            bz0 = min(r[2] for r in rings)
            h = max(r[3] for r in rings) - bz0
            height = rec["height"] if np.isfinite(rec["height"]) else h
                    # web budget (<= 4 MB GLB): everything within 600 m, beyond only massing that rises above the
            # low-rise roofscape (>= 12 m and >= 150 m2), very large footprints, and landmarks (> 45 m)
            if web and not (dist < 600 or (height >= 12 and area >= 150) or area >= 1500 or height > 45):
                stats["skipped_web"] += 1; continue
            g = ground_fn(np.r_[allxy[:, 0], cx], np.r_[allxy[:, 1], cy])
            sink = cfg["sink"][0] if r_inf < 1008 else cfg["sink"][1]
            base = float(np.min(g)) - sink
            croof = roof_colour(allxy)
            pal = lowp if rec["storeys"] <= 2 else highp
            cwall = pal[stable_hash(rec["id"]) % len(pal)].astype(float)
            cwall = np.clip(0.85 * cwall + 0.15 * 150, 0, 255)
            lo, hi = np.searchsorted(l2b_sorted, bi), np.searchsorted(l2b_sorted, bi, side="right")
            use_l2 = hi > lo and (cfg["lod2"] is True or (cfg["lod2"] == "landmarks" and height > 45))
            if use_l2:
                T = l2t[order[lo:hi]].astype(np.float64)
                kinds = l2k[order[lo:hi]]
                T[:, :, 2] += (base + sink) - bz0          # PLATEAU ground -> terrain minimum under the footprint
                V = T.reshape(-1, 3)
                Cc = np.where(np.repeat(kinds, 3)[:, None] == 0, croof, cwall)
                key = np.round(V, 2)
                uq, inv = np.unique(np.c_[key, np.repeat(kinds, 3)], axis=0, return_inverse=True)
                inv = inv.ravel()
                Vu = np.zeros((len(uq), 3)); Vu[inv] = V
                Cu = np.zeros((len(uq), 3)); Cu[inv] = Cc
                Fu = inv.reshape(-1, 3)
                # LOD2 floor: extend walls down to the sunk base so slopes never show a gap
                Vu[:, 2] = np.where(Vu[:, 2] < base + sink + 0.05, base, Vu[:, 2])
                bucket = "lod2"; Vb, Fb, Cb = Vu, Fu, Cu
                stats["lod2"] += 1
            else:
                Vs, Fs, Cs = [], [], []
                o2 = 0
                for xy, ar, z0, z1 in rings:
                    if web:
                        xy = simplify_ring(xy, 0.8 if dist < 600 else 2.0, maxv=12 if dist < 600 else 6)
                        if xy is None:
                            continue
                        a2 = 0.5 * np.sum(xy[:, 0] * np.roll(xy[:, 1], -1) - np.roll(xy[:, 0], -1) * xy[:, 1])
                        if a2 < 0:
                            xy = xy[::-1]
                    top = base + sink + max(z1 - bz0, 2.5)
                    V, F, C = prism(xy, base, top, croof, cwall)
                    Vs.append(V); Fs.append(F + o2); Cs.append(C); o2 += len(V)
                if not Vs:
                    continue
                Vb, Fb, Cb = np.concatenate(Vs), np.concatenate(Fs), np.concatenate(Cs)
                bucket = "lod1"; stats["lod1"] += 1
            A = acc[bucket]
            A[0].append(Vb); A[1].append(Fb + nv[bucket]); A[2].append(Cb); nv[bucket] += len(Vb)
            stats["buildings"] += 1
            if height > 45 or (rec.get("name") and height > 25):
                stats["landmarks"].append(dict(id=rec["id"], name=rec.get("name"), height=height, mesh=mesh,
                                               xy=[round(cx, 1), round(cy, 1)], lod2=bool(use_l2)))
    objs = []
    for bucket, nm in (("lod2", "Backdrop_City_LOD2"), ("lod1", "Backdrop_City_LOD1")):
        V, F, C = acc[bucket]
        if not V:
            continue
        objs.append(dict(name=nm, V=np.concatenate(V), F=np.concatenate(F), C=np.concatenate(C), kind="city",
                         artistic=False,
                         source="PLATEAU 2025 Kyoto City CityGML (%s), 3rd-order meshes %s..%s; heights as surveyed, "
                                "placed on GSI DEM; roof colour = GSI seamlessphoto z16 median in footprint (muted); "
                                "wall colour drawn from measured PLATEAU texture means of mesh 52353692 by storey class"
                                % ("LOD2 Roof/Wall" if bucket == "lod2" else "LOD1 solids", MESHES[0], MESHES[-1])))
    log("city %s: %s" % (detail, {k: v for k, v in stats.items() if k != "landmarks"}))
    return objs, stats


# =============================================================== main
def ring_ground_fn(rings):
    """Height of the (bare) terrain surface used for placing buildings: DEM function with the ring's own step."""
    def f(x, y):
        x = np.asarray(x); y = np.asarray(y)
        r = rinf(x, y)
        out = np.empty(len(x))
        inner = r <= INNER
        out[inner] = inner_ground(x[inner], y[inner])
        for rg in rings:
            m = (r > rg["a"] if rg["a"] > INNER else r > INNER) & (r <= rg["b"])
            m &= ~inner
            if m.any():
                fn = ground_dem15 if rg["b"] <= 3100 else ground_dem12
                out[m] = fn(x[m], y[m], rg["s"])
        return out
    return f


def save(detail, objs):
    arrs = {}
    names = []
    for k, o in enumerate(objs):
        names.append(o["name"])
        arrs["V%d" % k] = o["V"].astype(np.float32)
        nmax = len(o["V"])
        arrs["F%d" % k] = o["F"].astype(np.uint32 if nmax > 65535 else np.uint16)
        arrs["C%d" % k] = np.clip(np.round(o["C"]), 0, 255).astype(np.uint8)
    info = [dict({k: v for k, v in o.items() if k not in ("V", "F", "C")}, verts=int(len(o["V"])), tris=int(len(o["F"])))
            for o in objs]
    arrs["objects"] = np.array(json.dumps(info, ensure_ascii=False))
    p = os.path.join(PROC, "backdrop_%s.npz" % detail)
    np.savez_compressed(p, **arrs)
    log("wrote", p, "%.1f MB" % (os.path.getsize(p) / 1e6), "tris", sum(i["tris"] for i in info))
    return info


def main():
    meta = dict(
        crs=BND["crs"], origin=[BND["origin_e"], BND["origin_n"]], frame="local x east, y north, z T.P. m (absolute)",
        inner_terrain="data/processed/terrain.npz, |x|,|y| <= 300 m (2 m grid) - left as a hole; ring A zips onto its boundary vertices exactly",
        earth_curvature="z -= d^2/(2R)*(1-0.13), d = horizontal distance from the box centre (viewer-centred)",
        sources=dict(
            dem15=dem15_info, dem15_pixel_sources={"dem5a": int((DEM15_SRC == 1).sum()), "dem10b_z14_fill": int((DEM15_SRC == 3).sum())},
            dem12=dem12_info, ortho16=ort16_info, ortho12=ort12_info, ortho_white_balance=WB.round(4).tolist(),
            plateau="https://assets.cms.plateau.reearth.io/.../26100_kyoto-shi_city_2025_citygml_1_op.zip (bldg %s; luse 523536, 523546)" % ",".join(MESHES),
            attribution="出典: 国土地理院 (GSI tiles); PLATEAU 2025 Kyoto City (国土交通省 Project PLATEAU)"),
        details={})
    mp = os.path.join(PROC, "backdrop_meta.json")
    if os.path.exists(mp):
        meta["details"] = json.load(open(mp)).get("details", {})
    want = [a for a in sys.argv[1:] if a in DETAIL] or list(DETAIL)
    for detail, cfg in DETAIL.items():
        if detail not in want:
            continue
        log("=== detail", detail)
        rings = build_rings(cfg)
        objs = ring_objects(rings, cfg)
        city, stats = build_city(cfg, detail, ring_ground_fn(rings))
        info = save(detail, objs + city)
        meta["details"][detail] = dict(rings=[dict(name=RING_NAMES[k], hole=a, outer=b, step=s)
                                              for k, (a, b, s) in enumerate(cfg["rings"])],
                                       canopy=cfg["canopy"], objects=info,
                                       city={k: v for k, v in stats.items() if k != "landmarks"},
                                       landmarks=stats["landmarks"] if detail == "render" else None)
    meta["forest"] = dict(near_res_m=4.0, far_res_m=32.0,
                          rule="PLATEAU luse class 203 (山林（樹林地）) where any luse polygon covers the cell; "
                               "elsewhere orthophoto colour heuristic (2G-R-B>12, luminance<120, G>=R, 5-px median)")
    with open(mp, "w") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    log("done")


if __name__ == "__main__":
    main()
