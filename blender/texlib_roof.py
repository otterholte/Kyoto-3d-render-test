"""Kawara roof textures from real-scale tile geometry (Blender) -> orthographic data-pass bake, tileable.

Frame: X along the eave, Y up-slope, Z = roof-plane normal. The orthographic camera looks down -Z, so the
normal pass is the tangent-space normal (u = along eave, v = up-slope, OpenGL).

Tile sizes
* sangawara (桟瓦, J-type "53A"): working width 265 mm x working length 235 mm (≈16 tiles/m²) - industry standard
  size used on Kyoto machiya (documented: JIS A 5208 / manufacturers' 53A spec; size class is generic, not per-building).
  Repeat = 8 x 9 tiles = 2.120 x 2.115 m.
* hongawara (本瓦, temples): 0.30 m column pitch (hiragawara channel + marugawara cover), marugawara course 0.27 m,
  hiragawara steps every 0.09 m (generic/inferred proportions). Repeat = 7 x 8 = 2.10 x 2.16 m.
Tileability: the tile array extends one repeat beyond the frame on all sides and per-tile colours are indexed
modulo the repeat, so AO, overlaps and colours wrap exactly.
"""
import math
import os
import sys
import time

import bpy  # noqa: F401
import bmesh
import numpy as np
from mathutils import Matrix

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from texlib_common import (blur, fnoise, hexc, height_to_normal, l2s, lerp, renorm, s2l, smooth, write_set)
import texlib_facade as F

SANG_W, SANG_L, SANG_FULL = 0.265, 0.235, 0.315
HON_COL, HON_ROW, HON_HIRA = 0.30, 0.27, 0.09


def kawara_palette(n, seed):
    """Weathered blue-grey ibushi kawara: per-tile sRGB colours (a few replaced darker/silvery tiles)."""
    rng = np.random.default_rng(seed)
    base = hexc("#6e7175")
    v = rng.normal(0, 0.025, n)
    hue = rng.normal(0, 0.004, n)
    cols = base[None] * (1 + v)[:, None] + hue[:, None] * np.array([-1, 0, 1.2])
    repl = rng.random(n) < 0.04
    cols[repl] = hexc("#5c6064") * rng.uniform(0.95, 1.05, (repl.sum(), 1))
    brown = rng.random(n) < 0.03
    cols[brown] = hexc("#6d6a66") * rng.uniform(0.95, 1.05, (brown.sum(), 1))
    return np.clip(cols, 0, 1)


def _grid(fb, x0, y0, nx, ny, w, L, zfun, key, col, rnd):
    bm = fb.bm
    vs = {}
    for i in range(nx + 1):
        for j in range(ny + 1):
            s, t = i / nx, j / ny
            vs[(i, j)] = bm.verts.new((x0 + s * w, y0 + t * L, zfun(s, t)))
    faces = []
    for i in range(nx):
        for j in range(ny):
            f = bm.faces.new([vs[(i, j)], vs[(i + 1, j)], vs[(i + 1, j + 1)], vs[(i, j + 1)]])
            f.normal_update(); faces.append(f)
    # front lip (vertical face under the lower edge)
    for i in range(nx):
        a, b = vs[(i, 0)], vs[(i + 1, 0)]
        c = bm.verts.new((b.co.x, b.co.y, b.co.z - 0.018)); d = bm.verts.new((a.co.x, a.co.y, a.co.z - 0.018))
        f = bm.faces.new([d, c, b, a]); f.normal_update(); faces.append(f)
    fb._finish_faces(faces, key, "y", rnd=rnd, col=col)


def sang_prof(s):
    if s < 0.62:
        return -0.030 * math.sin(math.pi * s / 0.62)
    return 0.017 * math.sin(math.pi * (s - 0.62) / 0.38)


def build_sangawara(fb, NI, NK, rows_extra=2, seed=1, cols=None, k_range=None):
    rng = np.random.default_rng(seed)
    pal = kawara_palette(NI * NK, seed) if cols is None else cols
    lip = 0.022
    k0, k1 = k_range or (-rows_extra, NK + rows_extra)
    for k in range(k0, k1):
        for i in range(-2, NI + 2):
            ii, kk = i % NI, k % NK
            r = np.random.default_rng(1000 + ii * 31 + kk * 977)
            dx, dy = r.uniform(-0.002, 0.002), r.uniform(-0.003, 0.003)
            tw = r.uniform(-0.006, 0.006)    # twist (mm-scale irregular laying)
            c = tuple(s2l(pal[(ii + kk * NI) % len(pal)]))

            def zf(s, t, tw=tw):
                return sang_prof(s) + lip * (1 - t) + tw * (s - 0.5) * (1 - t)
            _grid(fb, i * SANG_W + dx + 0.0015, k * SANG_L + dy, 16, 6, SANG_W - 0.003, SANG_FULL, zf, "kawara_tile",
                  c, rnd=r.random())


def build_hongawara(fb, NI, NK, seed=2, k_range=None):
    pal = kawara_palette(NI * NK * 2, seed)
    k0, k1 = k_range or (-2, NK + 2)
    for k in range(k0, k1):
        for i in range(-2, NI + 2):
            ii, kk = i % NI, k % NK
            r = np.random.default_rng(5000 + ii * 31 + kk * 977)
            # three hiragawara steps per marugawara course (concave channel 0.24 wide under the covers)
            for h in range(3):
                c = tuple(s2l(pal[(ii + kk * NI) * 2 % len(pal)] * r.uniform(0.95, 1.05)))
                y0 = k * HON_ROW + h * HON_HIRA

                def zh(s, t):
                    return -0.02 * math.sin(math.pi * s) + 0.015 * (1 - t)
                _grid(fb, i * HON_COL + 0.03, y0, 10, 3, HON_COL - 0.06, HON_HIRA + 0.06, zh, "kawara_tile", c,
                      rnd=r.random())
            # marugawara (half cylinder r = 0.075) over the joint, with a tamabuchi step at its upper end
            c = tuple(s2l(pal[((ii + kk * NI) * 2 + 1) % len(pal)]))
            xc = i * HON_COL
            R = 0.075

            def zm(s, t):
                a = math.pi * s
                return 0.01 + R * math.sin(a) * 0.95 + 0.012 * (1 - t)
            bm = fb.bm
            n_a, n_t = 14, 6
            vs = {}
            for a in range(n_a + 1):
                for j in range(n_t + 1):
                    ang = math.pi * a / n_a
                    vs[(a, j)] = bm.verts.new((xc - R * math.cos(ang), k * HON_ROW + HON_ROW * j / n_t * 1.12,
                                               zm(a / n_a, j / n_t)))
            faces = []
            for a in range(n_a):
                for j in range(n_t):
                    f = bm.faces.new([vs[(a, j)], vs[(a + 1, j)], vs[(a + 1, j + 1)], vs[(a, j + 1)]])
                    f.normal_update()
                    if f.normal.z < 0:
                        f.normal_flip()
                    faces.append(f)
            fb._finish_faces(faces, "kawara_tile", "y", rnd=r.random(), col=c)


def build_ridge(fb, W, y_ridge, pitch_deg=24.0, layers=5, seed=3):
    """Noshi-gawara stack + kanmuri (round cap) along X at the top of the face, built in world-up then
    rotated into the roof-plane frame."""
    th = math.radians(pitch_deg)
    bm = fb.bm
    before = set(bm.verts)
    rng = np.random.default_rng(seed)
    for k in range(layers):
        # each noshi layer: flat strips 0.03 thick stepping inwards by 0.015, joints every ~0.27 m
        y_out = 0.17 - k * 0.018
        x = -0.1
        while x < W + 0.1:
            L = 0.27
            c = tuple(s2l(hexc("#5f6266") * rng.uniform(0.9, 1.08)))
            fb.box(x + 0.002, x + L - 0.002, -y_out, 0.0, k * 0.032, k * 0.032 + 0.03, "kawara_tile", grain="x",
                   col=c, bevel=0.004)
            x += L
    c = tuple(s2l(hexc("#55585c")))
    zc = layers * 0.032 + 0.02
    fb.cyl(W / 2, 0.0, zc, 0.085, W + 0.4, "x", "kawara_tile", seg=20, col=c)
    new = [v for v in bm.verts if v not in before]
    # world-up frame (y = horizontal towards ridge... here: y<0 = down-slope side) -> roof frame
    M = Matrix.Translation((0, y_ridge, 0)) @ Matrix.Rotation(-th, 4, "X")
    bmesh.ops.transform(bm, matrix=M, verts=new)
    for f in {f for v in new for f in v.link_faces}:
        f.normal_update()


def build_eave_manju(fb, NI, y=0.0):
    """Eave tiles' round bosses (manjū / tomoe-gawara ends) at the lower end of each roll."""
    for i in range(-1, NI + 1):
        xc = i * SANG_W + 0.62 * SANG_W + 0.38 * SANG_W / 2
        c = tuple(s2l(hexc("#606367")))
        fb.cyl(xc, y + 0.01, 0.03, 0.05, 0.03, "y", "kawara_tile", seg=16, col=c)
        fb.box(i * SANG_W, (i + 1) * SANG_W, y - 0.03, y + 0.015, -0.02, 0.03, "kawara_tile", grain="x", col=c)


# ----------------------------------------------------------------------------- render + post
def _render(sc, co, fo, name, builder, W, H, res, cx=None, cy=None):
    for ob in [o for o in bpy.data.objects if o.type == "MESH"]:
        me = ob.data; bpy.data.objects.remove(ob); bpy.data.meshes.remove(me)
    mats = F.MATS()
    mats["kawara_tile"] = dict(attr="pcol", rough=0.55)
    fb = F.FB(W, H, seed=7)
    builder(fb)
    fb.to_object(name, mats)
    fb2 = F.FB(W, H); fb2.box(-3, W + 3, -3, H + 3, -0.3, -0.1, "interior"); fb2.to_object("under", mats)
    sc.render.resolution_x, sc.render.resolution_y = res
    co.data.ortho_scale = max(W, H)
    co.location = (W / 2 if cx is None else cx, H / 2 if cy is None else cy, 5.0)
    od = os.path.join(F.PASSDIR, name); os.makedirs(od, exist_ok=True)
    fo.directory = od; fo.file_name = ""
    t = time.time()
    if not (os.environ.get("TEXLIB_REUSE") and len(os.listdir(od)) >= 9):
        bpy.ops.render.render(write_still=False)
    print("  render %-28s %s %.1fs" % (name, res, time.time() - t), flush=True)
    return {f.replace(".exr", ""): F._read_exr(os.path.join(od, f)) for f in os.listdir(od)}


def kawara_post(P, size_m, seed, moss=0.5, wrap=True):
    alb = l2s(P["alb"][..., :3])
    # keep per-tile variation subtle: compress deviations from the local (0.4 m) mean
    mloc = blur(alb, 0.4 / (size_m[0] / alb.shape[1])) if wrap else alb.mean((0, 1), keepdims=True)
    alb = mloc + (alb - mloc) * 0.45
    n = P["Normal"][..., :3]
    ao = np.clip(P["Ambient Occlusion"][..., 0], 0, 1)
    z = P["Position"][..., 2]
    h, w = ao.shape
    px = size_m[0] / w
    nz = lambda **k: fnoise((h, w), seed=seed + k.pop("s", 0), **k) if wrap else fnoise((h, w), seed=seed, **k)
    # fired-clay surface: fine mottling + mm pits (normal detail)
    fine = fnoise((h, w), lo=60, beta=1.0, seed=seed + 1) * 0.0004
    nd = height_to_normal(fine, px, 1.0, wrap=wrap)
    n = renorm(n + np.concatenate([nd[..., :2], np.zeros((h, w, 1))], -1))
    mott = fnoise((h, w), lo=3, hi=80, beta=1.6, seed=seed + 2)
    alb = alb * (1 + 0.035 * mott)[..., None]
    # silvery sheen loss / lime-white bloom streaks running down-slope
    streak = fnoise((h, w), lo=2, hi=60, beta=1.5, seed=seed + 3, aniso=(1.0, 0.12))
    alb = lerp(alb, alb * 1.18 + 0.03, smooth(0.8, 2.2, streak)[..., None] * 0.5)
    # course lines: the thick lower edge of each tile casts a contact shadow on the course below
    dz = np.zeros_like(z)
    dz[:-1] = z[:-1] - z[1:]                       # row r is up-slope of row r+1 (image rows go down-slope)
    lip = (dz > 0.006).astype(np.float32)           # z drops when moving down-slope = thick lower edge of a tile
    band = np.zeros_like(lip)
    for k in range(1, int(0.035 / px) + 1):         # contact shadow on the course below (down-slope = larger row)
        band[k:] = np.maximum(band[k:], lip[:-k] * (1 - k * px / 0.035) ** 1.5)
    band = blur(band, 1.0)
    ao = ao * (1 - 0.55 * band)
    alb = alb * (1 - 0.25 * band)[..., None]
    # moss + lichen: patches, concentrated in the troughs and along the course lines
    low = smooth(0.0, 1.0, (np.percentile(z, 60) - z) / (np.ptp(z) * 0.5 + 1e-6))
    m_n = fnoise((h, w), lo=2, hi=40, beta=2.0, seed=seed + 4)
    mossm = np.clip(smooth(1.0, 2.2, m_n + 0.9 * low + 1.2 * band) * moss, 0, 1)
    speck = smooth(2.3, 2.8, fnoise((h, w), lo=60, beta=0.6, seed=seed + 5))
    mcol = lerp(np.broadcast_to(hexc("#3f4724"), (h, w, 3)), hexc("#5b6332"),
                np.clip(0.5 + 0.5 * fnoise((h, w), lo=100, beta=0.5, seed=seed + 6), 0, 1))
    alb = lerp(alb, mcol, (mossm * 0.8)[..., None])
    lichen = np.clip(speck * 0.6 + smooth(2.0, 2.6, fnoise((h, w), lo=20, beta=1.0, seed=seed + 7)) * 0.5, 0, 1)
    alb = lerp(alb, hexc("#a9a792"), (lichen * 0.45)[..., None])
    rough = np.clip(P["rough"][..., 0] + 0.25 * mossm + 0.15 * lichen + 0.05 * mott, 0, 1)
    return np.clip(alb, 0, 1), n, ao, rough


def build_all(only=None, res=2048):
    F.make_bases()
    sc, co, fo = F.setup_scene()
    sc.world.light_settings.distance = 0.12
    jobs = []
    NI, NK = 8, 9
    Ws, Hs = NI * SANG_W, NK * SANG_L
    jobs.append(("roof_kawara_sangawara", lambda fb: build_sangawara(fb, NI, NK), Ws, Hs, (res, res), True,
                 "J-type 53A sangawara (265 x 235 mm working size), weathered ibushi blue-grey; machiya standard",
                 0.6))
    NIh, NKh = 7, 8
    Wh, Hh = NIh * HON_COL, NKh * HON_ROW
    jobs.append(("roof_kawara_hongawara", lambda fb: build_hongawara(fb, NIh, NKh), Wh, Hh, (res, res), True,
                 "hongawara (temple) 0.30 m columns, 0.27 m marugawara courses, 0.09 m hiragawara steps (generic)",
                 0.7))
    # ridge strip: 2.12 m along ridge x 0.53 m down-slope (top of texture = ridge line)
    Hr = 0.53
    jobs.append(("roof_kawara_ridge", lambda fb: (build_sangawara(fb, NI, NK, k_range=(-1, 4)),
                                                  build_ridge(fb, Ws, Hr)), Ws, Hr, (res, res // 4), False,
                 "ridge strip (noshi-gawara x5 + kanmuri) projected onto the roof plane at ~24 deg; v=1 is the "
                 "ridge line, tiles in u only", 0.4))
    He = 0.53
    jobs.append(("roof_kawara_eave", lambda fb: (build_sangawara(fb, NI, NK, k_range=(0, 4)),
                                                 build_eave_manju(fb, NI, 0.0)), Ws, He, (res, res // 4), False,
                 "eave strip: first courses with round eave-tile bosses (no onigawara); v=0 is the eave line, "
                 "tiles in u only", 0.3))
    for name, builder, W, H, rs, wrap, note, moss in jobs:
        if only and not any(o in name for o in only):
            continue
        P = _render(sc, co, fo, name, builder, W, H, rs)
        alb, n, ao, rough = kawara_post(P, (W, H), seed=len(name), moss=moss, wrap=wrap)
        if not wrap:
            # strips: background (below the frame edge) never shows, but keep it neutral
            pass
        write_set(name, alb, n, ao, rough, size_m=(W, H), category="roof", kind="tileable" if wrap else "strip",
                  tags=["traditional"] if "hongawara" not in name else ["temple"], notes=note,
                  res_bl=rs, res_web=(rs[0] // 2, rs[1] // 2))


if __name__ == "__main__":
    a = sys.argv[1:]
    build_all(a[a.index("--only") + 1].split(",") if "--only" in a else None)
