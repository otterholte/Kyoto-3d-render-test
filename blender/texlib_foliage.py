"""Alpha leaf cards (foliage atlas): Japanese maple (autumn + green), Japanese black pine needle clusters,
cherry blossom + cherry leaf, azalea, box, bamboo leaves.

Each card is a real-scale spray of leaves on twigs, drawn as polygons from botanical leaf outlines
(sizes in metres), with per-leaf tilt -> tangent-space normal (OpenGL), alpha coverage, and colour bleeding into
the transparent area (no dark halos when mip-mapped). Cards are generic botany (artistic), not per-tree evidence;
species follow the OSM/Commons-observed street trees of the area (maple, pine, cherry, bamboo, clipped shrubs).
"""
import json
import math
import os

import numpy as np
from PIL import Image, ImageDraw

from texlib_common import TEX_BL, TEX_WEB, blur, hexc, lerp, renorm, resize, save_img, to8, _lib_update, LIB_JSON_BL, LIB_JSON_WEB

CELL = 512         # Blender atlas cell (2048 x 1024 atlas = 4 x 2 cards); web = half
SS = 2             # supersampling for drawing


def maple_outline(n=7, serr=0.04):
    lobes = [(0.0, 1.0), (0.42, 0.92), (-0.42, 0.92), (0.86, 0.72), (-0.86, 0.72), (1.3, 0.45), (-1.3, 0.45)][:n]
    pts = []
    for t in np.linspace(-math.pi * 0.86, math.pi * 0.86, 220):
        r = 0.18 + max(L * math.exp(-((t - a) / 0.17) ** 2) for a, L in lobes)
        r *= 1 + serr * math.sin(t * 60)
        pts.append((r * math.sin(t), r * math.cos(t)))
    pts.append((0, -0.05))
    return pts


def ovate_outline(width=0.42, serr=0.02, tip=0.25):
    pts = []
    for t in np.linspace(0, 2 * math.pi, 160, endpoint=False):
        y = -math.cos(t)
        w = width * abs(math.sin(t)) ** 0.85 * (1 + 0.25 * math.cos(t)) * (1 - tip * max(0, y) ** 4)
        w *= 1 + serr * math.sin(t * 45)
        pts.append((w * (1 if t < math.pi else -1), y))
    return pts


def lance_outline(width=0.11):
    pts = []
    for t in np.linspace(0, 2 * math.pi, 80, endpoint=False):
        y = -math.cos(t)
        w = width * abs(math.sin(t)) ** 0.7 * (1 - 0.5 * max(0, y) ** 2)
        pts.append((w * (1 if t < math.pi else -1), y))
    return pts


def petal_flower(n=5):
    pts = []
    for t in np.linspace(0, 2 * math.pi, 200, endpoint=False):
        k = (t * n / (2 * math.pi)) % 1.0
        r = 0.55 + 0.45 * math.sin(math.pi * k) ** 0.6 - 0.12 * math.exp(-((k - 0.5) / 0.05) ** 2)
        pts.append((r * math.cos(t), r * math.sin(t)))
    return pts


def _tf(pts, cx, cy, size, ang, sx=1.0):
    c, s = math.cos(ang), math.sin(ang)
    return [(cx + (x * sx * c - y * s) * size, cy + (x * sx * s + y * c) * size) for x, y in pts]


class Card:
    def __init__(self, size_m, seed):
        self.N = CELL * SS
        self.size_m = size_m
        self.ppm = self.N / size_m
        self.rng = np.random.default_rng(seed)
        self.lab = Image.new("I", (self.N, self.N), 0)
        self.d = ImageDraw.Draw(self.lab)
        self.vein = Image.new("L", (self.N, self.N), 0)
        self.dv = ImageDraw.Draw(self.vein)
        self.props = [None]      # per label: (rgb, normal, kind)

    def add(self, pts, rgb, tilt=0.6, kind=0, vein=None):
        k = len(self.props)
        a = self.rng.uniform(0, 2 * math.pi); t = self.rng.uniform(0, tilt)
        n = (math.sin(t) * math.cos(a), math.sin(t) * math.sin(a), math.cos(t))
        self.props.append((np.asarray(rgb, np.float32), n, kind, pts))
        self.d.polygon(pts, fill=k)
        if vein:
            for seg in vein:
                self.dv.line(seg, fill=255, width=max(1, int(self.ppm * 0.0008)))
        return k

    def twig(self, p0, p1, w_m, rgb=(0.23, 0.17, 0.12), bend=0.1):
        pts = []
        for t in np.linspace(0, 1, 12):
            x = p0[0] + (p1[0] - p0[0]) * t + bend * math.sin(math.pi * t) * (p1[1] - p0[1])
            y = p0[1] + (p1[1] - p0[1]) * t - bend * math.sin(math.pi * t) * (p1[0] - p0[0])
            pts.append((x, y))
        k = len(self.props)
        self.props.append((np.asarray(rgb, np.float32), (0, 0, 1), 1, None))
        self.d.line(pts, fill=k, width=max(2, int(w_m * self.ppm)), joint="curve")
        return pts

    def finish(self):
        lab = np.asarray(self.lab, dtype=np.int64)
        n = len(self.props)
        cols = np.zeros((n, 3), np.float32); nrm = np.zeros((n, 3), np.float32); nrm[:, 2] = 1
        for i, p in enumerate(self.props[1:], 1):
            cols[i] = p[0]; nrm[i] = p[1]
        # depth cue: leaves drawn early are inner/lower in the spray -> darker; plus per-pixel mottling
        order = np.linspace(0.62, 1.0, n).astype(np.float32); order[0] = 1
        alb = cols[lab] * order[lab][..., None]
        from texlib_common import fnoise
        alb = alb * (1 + 0.10 * fnoise(lab.shape, lo=20, hi=400, beta=1.2, seed=n))[..., None]
        nm = nrm[lab]
        cover = (lab > 0).astype(np.float32)
        # per-leaf shading cues: midrib/veins lighter, slight cupping via blurred-label curvature
        v = np.asarray(self.vein, dtype=np.float32) / 255.0 * cover
        alb = lerp(alb, alb * 1.25 + 0.03, v * 0.6)
        edge = cover - blur(cover, 3 * SS)
        hgt = blur(cover, 4 * SS)
        gy, gx = np.gradient(hgt)
        nm = nm + np.stack([-gx * 6, gy * 6, np.zeros_like(gx)], -1)
        nm = renorm(nm)
        ao = np.clip(0.55 + 0.45 * np.clip(blur(cover, 6 * SS), 0, 1) ** 0.5, 0, 1)
        ao = 1 - (1 - ao) * cover
        # downsample
        f = SS
        cov = cover.reshape(CELL, f, CELL, f).mean((1, 3))
        al = (alb * cover[..., None]).reshape(CELL, f, CELL, f, 3).sum((1, 3)) / np.maximum(
            cover.reshape(CELL, f, CELL, f).sum((1, 3)), 1e-6)[..., None]
        nn = renorm((nm * cover[..., None]).reshape(CELL, f, CELL, f, 3).sum((1, 3)) + np.array([0, 0, 1e-3]))
        ao = ao.reshape(CELL, f, CELL, f).mean((1, 3))
        # bleed colour into transparent pixels
        filled = cov > 0.01
        acc = al * filled[..., None]; wsum = filled.astype(np.float32)
        for s in (2, 6, 16, 40):
            bw = blur(wsum, s); ba = blur(acc, s)
            m = wsum < 0.01
            acc[m] = (ba[m] / np.maximum(bw[m], 1e-6)[..., None]); wsum = np.where(m & (bw > 1e-4), 1.0, wsum)
        al = np.where(filled[..., None], al, acc)
        nn = np.where(filled[..., None], nn, np.array([0, 0, 1.0]))
        return np.clip(al, 0, 1), nn, ao, cov


def jitter(rgb, rng, v=0.12, h=0.05):
    c = np.asarray(rgb) * (1 + rng.normal(0, v)) + rng.normal(0, h, 3) * np.array([1, 0.5, 0.2])
    return np.clip(c, 0, 1)


def spray(card, leaf_fn, n_twigs, leaves_per, leaf_m, palette, twig_w=0.004, spread=1.0, tilt=0.6, vein=True,
          tip_cluster=False):
    N = card.N; rng = card.rng
    base = (N * 0.5, N * 0.98)
    for t in range(n_twigs):
        ang = -math.pi / 2 + rng.uniform(-0.75, 0.75) * spread
        L = rng.uniform(0.6, 0.95) * N * 0.78
        tip = (base[0] + math.cos(ang) * L + rng.uniform(-0.1, 0.1) * N, base[1] + math.sin(ang) * L)
        pts = card.twig(base, tip, twig_w, bend=rng.uniform(-0.15, 0.15))
        for k in range(leaves_per):
            u = rng.uniform(0.25, 1.0) if not tip_cluster else rng.uniform(0.8, 1.0)
            i = min(len(pts) - 1, int(u * (len(pts) - 1)))
            px, py = pts[i]
            a = rng.uniform(-math.pi, math.pi)
            off = rng.uniform(0.2, 0.9) * leaf_m * card.ppm
            cx, cy = px + math.cos(a) * off, py + math.sin(a) * off
            size = leaf_m * card.ppm * rng.uniform(0.75, 1.15) / 2
            col = jitter(palette[rng.integers(len(palette))], rng)
            outline = leaf_fn()
            p = _tf(outline, cx, cy, size, a + math.pi / 2 + rng.uniform(-0.4, 0.4), sx=rng.uniform(0.75, 1.0))
            veins = None
            if vein:
                c_, s_ = math.cos(a + math.pi / 2), math.sin(a + math.pi / 2)
                veins = [[(cx, cy), (cx - s_ * size * 0.9 * -1, cy + c_ * size * 0.9 * -1)]]
            card.add(p, col, tilt=tilt, vein=veins)
            card.d.line([(px, py), (cx, cy)], fill=len(card.props) - 1, width=max(1, int(0.0012 * card.ppm)))


def make_cards():
    cards = {}
    # Japanese maple (Acer palmatum): leaf 5-7 cm across, card 0.5 m
    for nm, pal in (("maple_autumn", ["#b3261e", "#c8401c", "#d8641e", "#a51d24", "#e08a2a", "#8f1c1c"]),
                    ("maple_green", ["#4f7a2a", "#5f8c30", "#3f6a24", "#6f9a3a", "#557f2c"])):
        c = Card(0.5, len(nm))
        spray(c, lambda: maple_outline(), 9, 26, 0.06, [hexc(p) for p in pal], twig_w=0.003, tilt=0.7)
        cards[nm] = (c, 0.5, "Acer palmatum spray, leaves 5-7 cm")
    # Japanese black pine (Pinus thunbergii): paired needles 8-15 cm in dense tufts at shoot tips
    c = Card(0.6, 3)
    rng = c.rng
    N = c.N
    for t in range(9):
        base = (N * 0.5, N * 0.98)
        ang = -math.pi / 2 + rng.uniform(-0.8, 0.8)
        L = rng.uniform(0.35, 0.6) * N
        tip = (base[0] + math.cos(ang) * L, base[1] + math.sin(ang) * L)
        c.twig(base, tip, 0.012, rgb=(0.25, 0.19, 0.14), bend=rng.uniform(-0.1, 0.1))
        for k in range(150):
            a = ang + rng.normal(0, 0.9)
            ln = rng.uniform(0.07, 0.13) * c.ppm
            s0 = rng.uniform(0.0, 0.05) * c.ppm
            p0 = (tip[0] + math.cos(a) * s0 - math.cos(ang) * rng.uniform(0, 0.08) * c.ppm,
                  tip[1] + math.sin(a) * s0 - math.sin(ang) * rng.uniform(0, 0.08) * c.ppm)
            p1 = (p0[0] + math.cos(a) * ln, p0[1] + math.sin(a) * ln)
            col = jitter(hexc(["#2f4a26", "#3c5a2c", "#273f22", "#4a6534"][rng.integers(4)]), rng, 0.15)
            k_ = c.add([p0, p1, (p1[0] + 1, p1[1] + 1)], col, tilt=0.9)
            c.d.line([p0, p1], fill=k_, width=max(2, int(0.0018 * c.ppm)))
    cards["pine_needles"] = (c, 0.6, "Pinus thunbergii shoot tufts, paired needles 7-13 cm")
    # cherry (Prunus x yedoensis / weeping cherry): blossoms 3 cm in clusters, leaves 8-12 cm
    c = Card(0.5, 5)
    rng = c.rng; N = c.N
    for t in range(10):
        base = (N * 0.5, N * 0.98)
        ang = -math.pi / 2 + rng.uniform(-1.0, 1.0)
        L = rng.uniform(0.5, 0.9) * N * 0.55
        tip = (base[0] + math.cos(ang) * L, base[1] + math.sin(ang) * L)
        pts = c.twig(base, tip, 0.005, rgb=(0.22, 0.16, 0.14), bend=rng.uniform(-0.15, 0.15))
        for k in range(10):
            i = rng.integers(3, len(pts)); px, py = pts[i]
            for f in range(rng.integers(3, 6)):
                a = rng.uniform(0, 2 * math.pi); off = rng.uniform(0.005, 0.03) * c.ppm
                cx, cy = px + math.cos(a) * off, py + math.sin(a) * off
                col = jitter(hexc(["#f3d6dc", "#f6e4e6", "#eec3cc", "#fbeff0"][rng.integers(4)]), rng, 0.04, 0.01)
                c.add(_tf(petal_flower(), cx, cy, 0.015 * c.ppm * rng.uniform(0.85, 1.15), rng.uniform(0, 6.28)),
                      col, tilt=0.8)
                cc = c.props[-1]
                c.d.ellipse([cx - 2, cy - 2, cx + 2, cy + 2], fill=len(c.props) - 1)
    cards["cherry_blossom"] = (c, 0.5, "Prunus (Somei-yoshino type) blossom clusters, flowers ~3 cm")
    c = Card(0.6, 6)
    spray(c, lambda: ovate_outline(0.4, 0.03), 8, 16, 0.10, [hexc(p) for p in ("#4d7a2e", "#5a8636", "#41692a", "#6b9440")],
          twig_w=0.004, tilt=0.6)
    cards["cherry_leaf"] = (c, 0.6, "Prunus leaves, ovate serrate 8-12 cm")
    # azalea (tsutsuji, clipped): small elliptic leaves 2-4 cm, a few magenta flowers
    c = Card(0.4, 7)
    spray(c, lambda: ovate_outline(0.38, 0.0, 0.1), 14, 30, 0.03, [hexc(p) for p in ("#2f4f22", "#3b5c28", "#47692f", "#2a451e")],
          twig_w=0.002, tilt=0.8, spread=1.3)
    rng = c.rng
    leaf_pts = [p[3] for p in c.props[1:] if p is not None and p[3] is not None and len(p[3]) > 10]
    for k in range(14):
        lp = leaf_pts[rng.integers(len(leaf_pts) // 2, len(leaf_pts))]
        cx, cy = np.mean(lp, axis=0)
        c.add(_tf(petal_flower(5), cx, cy, 0.02 * c.ppm, rng.uniform(0, 6)), jitter(hexc("#c2407a"), rng, 0.08), tilt=0.5)
    cards["shrub_azalea"] = (c, 0.4, "Rhododendron (tsutsuji) clipped shrub, leaves 2-4 cm")
    # box / inu-tsuge: dense tiny leaves 1-1.5 cm
    c = Card(0.3, 8)
    spray(c, lambda: ovate_outline(0.5, 0.0, 0.0), 18, 45, 0.013, [hexc(p) for p in ("#2c4a1f", "#36572a", "#41632f", "#24401b", "#4c6e34")],
          twig_w=0.0015, tilt=0.9, spread=1.5, vein=False)
    cards["shrub_box"] = (c, 0.3, "Ilex crenata / box-type clipped hedge, leaves 1-1.5 cm")
    # bamboo (Phyllostachys): lanceolate leaves 10-20 cm in fans
    c = Card(0.8, 9)
    spray(c, lambda: lance_outline(0.12), 7, 22, 0.16, [hexc(p) for p in ("#5f8a32", "#6f9a3a", "#4e7a2a", "#86a548", "#7a9440")],
          twig_w=0.003, tilt=0.6, tip_cluster=True)
    cards["bamboo_leaves"] = (c, 0.8, "Phyllostachys leaf fans, lanceolate 10-20 cm")
    return cards


def build_all():
    cards = make_cards()
    names = list(cards)
    cols, rows = 4, 2
    W, H = cols * CELL, rows * CELL
    A = np.zeros((H, W, 3), np.float32); Nn = np.zeros((H, W, 3), np.float32); Nn[..., 2] = 1
    AO = np.ones((H, W), np.float32); AL = np.zeros((H, W), np.float32)
    desc = {"schema": "foliage_atlas v1", "atlas_px": [W, H], "grid": [cols, rows],
            "normal": "OpenGL tangent space", "alpha": "albedo PNG alpha = coverage (use alpha clip ~0.4 or hashed)",
            "orm": "R=AO G=roughness(0.55 leaves / 0.8 twigs) B=0", "cards": {}}
    for i, nm in enumerate(names):
        c, size_m, note = cards[nm]
        al, nn, ao, cov = c.finish()
        x, y = (i % cols) * CELL, (i // cols) * CELL
        A[y:y + CELL, x:x + CELL] = al; Nn[y:y + CELL, x:x + CELL] = nn; AO[y:y + CELL, x:x + CELL] = ao
        AL[y:y + CELL, x:x + CELL] = cov
        desc["cards"][nm] = {"uv_rect": [x / W, 1 - (y + CELL) / H, (x + CELL) / W, 1 - y / H],
                             "size_m": [size_m, size_m], "pivot": "bottom-centre (twig base)", "note": note}
    rough = np.where(AL > 0.5, 0.55, 0.8).astype(np.float32)
    orm = np.stack([AO, rough, np.zeros_like(AO)], -1)
    for d, f, lib in ((TEX_BL, 1, LIB_JSON_BL), (TEX_WEB, 2, LIB_JSON_WEB)):
        w2, h2 = W // f, H // f
        a = resize(A, (w2, h2)); al = resize(AL, (w2, h2)); nn = renorm(resize(Nn, (w2, h2))); o = resize(orm, (w2, h2))
        Image.fromarray(to8(np.concatenate([a, al[..., None]], -1)), "RGBA").save(os.path.join(d, "foliage_atlas_albedo.png"), optimize=True)
        save_img(os.path.join(d, "foliage_atlas_normal.jpg"), nn * 0.5 + 0.5, 92 if f == 1 else 80)
        save_img(os.path.join(d, "foliage_atlas_orm.jpg"), o, 90 if f == 1 else 80)
        dd = dict(desc); dd["atlas_px"] = [w2, h2]
        dd["files"] = {"albedo": "foliage_atlas_albedo.png", "normal": "foliage_atlas_normal.jpg", "orm": "foliage_atlas_orm.jpg"}
        json.dump(dd, open(os.path.join(d, "foliage_atlas.json"), "w"), indent=1)
        _lib_update(lib, "foliage_atlas", {"kind": "alpha_atlas", "category": "foliage", "files": dd["files"],
                                           "resolution": [w2, h2], "descriptor": "foliage_atlas.json",
                                           "tags": ["vegetation"], "size_m": None,
                                           "notes": "alpha leaf cards; see foliage_atlas.json for per-card rects"})
    print("  foliage atlas", W, H, names)


if __name__ == "__main__":
    build_all()
