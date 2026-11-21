"""Facade module atlas: real-scale machiya / modern / temple wall bays modelled in Blender and baked
(orthographic Cycles render of data passes) into albedo / normal / ORM / emissive.

Module frame: X along the facade (0..W m), Y up (0..H m, Y=0 = storey floor / ground), +Z out of the wall.
Z = 0 is the wall line that PLATEAU LOD2 walls represent; posts are slightly proud, plaster slightly recessed,
lattices proud, interiors deep behind. An orthographic camera looks down -Z, so the Cycles world-space
Normal pass IS the tangent-space normal (X = u, Y = v, Z = out; OpenGL).

Passes used: AOV 'alb' (pure base colour), AOV 'rough', 'metal', 'emit', 'plas' (plaster mask, for rain
streaks), 'wood'; Cycles Normal, Ambient Occlusion (distance 0.35 m) and Position.
Each module is rendered with copies of itself at x-W and x+W so AO/shadows wrap across bay joints.
"""
import json
import math
import os
import sys
import time

import bpy  # noqa: F401  (bpy before bmesh)
import bmesh
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from texlib_common import (SCRATCH, TEX_BL, TEX_WEB, blur, fnoise, hexc, height_to_normal, l2s, lerp, s2l, save_img,
                           smooth, text_mask, to8, renorm, resize, down)
import texlib_surfaces as S

D_PX = 300            # px per metre in the 4096 atlas (3.3 mm / px); web atlas = 150 px/m
BASE = os.path.join(SCRATCH, "facade_base")
PASSDIR = os.path.join(SCRATCH, "facade_pass")
MODDIR = os.path.join(SCRATCH, "facade_mod")
for d in (BASE, PASSDIR, MODDIR):
    os.makedirs(d, exist_ok=True)

BAY = 1.82


def _h(s):
    import zlib
    return zlib.crc32(s.encode()) % 100000
HALF = 0.91


# ============================================================================ base surface images (numpy)
def _save_base(name, col, hgt, rough, size_m):
    px = size_m / col.shape[1]
    Image.fromarray(to8(col)).save(os.path.join(BASE, name + "_alb.png"))
    n = height_to_normal(hgt, px)
    Image.fromarray(to8(n * 0.5 + 0.5)).save(os.path.join(BASE, name + "_nrm.png"))
    Image.fromarray(to8(np.clip(rough, 0, 1))).save(os.path.join(BASE, name + "_rgh.png"))


def make_bases(force=False):
    jobs = {
        "wood_dark": lambda: S.timber(palette="dark", size_m=(1, 1), res=1024, seams=False, write=False, seed=201, weather=0.45, grain_k=0.35),
        "wood_bengara": lambda: S.timber(palette="bengara", size_m=(1, 1), res=1024, seams=False, write=False, seed=202, weather=0.35, grain_k=0.35),
        "wood_honey": lambda: S.timber(palette="honey", size_m=(1, 1), res=1024, seams=False, write=False, seed=203, weather=0.15),
        "wood_silver": lambda: S.timber(palette="silver", size_m=(1, 1), res=1024, seams=False, write=False, seed=204, weather=0.8),
        "plaster_ochre": lambda: S.plaster(kind="ochre", size_m=(1, 1), res=1024, write=False, seed=211),
        "plaster_cream": lambda: S.plaster(kind="cream", size_m=(1, 1), res=1024, write=False, seed=212),
        "plaster_lime": lambda: S.plaster(kind="lime", size_m=(1, 1), res=1024, write=False, seed=213),
        "plaster_earth": lambda: S.plaster(kind="earth", size_m=(1, 1), res=1024, write=False, seed=214),
        "granite": lambda: S.granite_paving("tmp", (1, 1), row_m=2.0, len_m=(3, 3), base_hex="#9d978d", seed=215,
                                            res=1024, write=False, row_jitter=0, joint_m=0.0001),
    }
    for nm, fn in jobs.items():
        if force or not os.path.exists(os.path.join(BASE, nm + "_alb.png")):
            col, hgt, rough = fn()
            _save_base(nm, col, hgt, rough, 1.0)
    # fabric (noren) designs, generic (no real business names / logos): kana for "tea", "sweets", crest circles
    designs = {
        "noren_indigo": ("#1b2436", "#e4dfd2", "茶", "circle"),
        "noren_white": ("#e6e0d0", "#5a3a26", "和", "diamond"),
        "noren_brown": ("#5b3a28", "#efe7d6", "甘味", "none"),
        "noren_ai_short": ("#26355a", "#ece6d8", "", "wave"),
    }
    for nm, (bg, fg, txt, crest) in designs.items():
        p = os.path.join(BASE, nm + "_alb.png")
        if os.path.exists(p) and not force:
            continue
        N = 1024
        bgc = hexc(bg); fgc = hexc(fg)
        m = np.zeros((N, N), np.float32)
        if crest == "circle":
            yy, xx = np.mgrid[0:N, 0:N]
            r = np.hypot(xx - N / 2, yy - N * 0.36)
            m = np.maximum(m, ((r < 150) & (r > 128)).astype(np.float32))
            m = np.maximum(m, text_mask(txt, 190, (N, N))[np.clip(np.arange(N) + int(N * 0.14), 0, N - 1)][:, :])
        elif crest == "diamond":
            yy, xx = np.mgrid[0:N, 0:N]
            d = np.abs(xx - N / 2) + np.abs(yy - N * 0.33)
            m = np.maximum(m, ((d < 120) & (d > 98)).astype(np.float32))
            m = np.maximum(m, text_mask(txt, 140, (N, N))[np.clip(np.arange(N) + int(N * 0.17), 0, N - 1)])
            m = np.maximum(m, text_mask("", 10, (N, N)))
        elif crest == "wave":
            yy, xx = np.mgrid[0:N, 0:N].astype(np.float32)
            wv = np.sin(xx / N * 2 * np.pi * 6) * 18 + N * 0.75
            m = np.maximum(m, (np.abs(yy - wv) < 10).astype(np.float32))
            m = np.maximum(m, (np.abs(yy - wv - 50) < 6).astype(np.float32))
        else:
            m = text_mask(txt, 260, (N, N), vertical=False)
            m = m[np.clip(np.arange(N) - int(N * 0.05), 0, N - 1)]
        m = blur(m, 1.2)
        weave = fnoise((N, N), lo=200, beta=0.2, seed=7) * 0.04
        fade = fnoise((N, N), lo=1, hi=6, beta=2, seed=8) * 0.05
        col = lerp(np.broadcast_to(bgc, (N, N, 3)), fgc, np.clip(m, 0, 1)) * (1 + weave + fade)[..., None]
        Image.fromarray(to8(col)).save(p)
    # signboards (generic words only)
    for nm, txt, bg, fg, vert in (("sign_kanban", "御土産", "#6b4a2e", "#1a120c", False),
                                  ("sign_modern", "おみやげ", "#3b2f28", "#f1ece2", False)):
        p = os.path.join(BASE, nm + "_alb.png")
        if os.path.exists(p) and not force:
            continue
        W_, H_ = 1024, 256
        m = text_mask(txt, 170, (W_, H_), vertical=vert)
        col = lerp(np.broadcast_to(hexc(bg), (H_, W_, 3)), hexc(fg), m)
        if nm == "sign_kanban":
            g = fnoise((H_, W_), lo=4, beta=0.8, seed=3, aniso=(1, 0.05)) * 0.08
            col = col * (1 + g)[..., None]
        Image.fromarray(to8(col)).save(p)
    # modern facade tile cladding (nichōgake 227 x 60 mm, 8-10 mm joints), beige-brown
    p = os.path.join(BASE, "tile_clad_alb.png")
    if force or not os.path.exists(p):
        res = 1024
        lay = S.bond_layout(res, res, 0.070 / (1.0 / res), (0.237 / (1.0 / res), 0.237 / (1.0 / res)), 9, row_jitter=0)
        gap = 1 - smooth(2.5, 3.5, lay["dist"])
        tone = S.per_id(lay["id"], lay["n"], 3, -1, 1)
        col = np.broadcast_to(hexc("#a58f74"), (res, res, 3)) * (1 + 0.07 * tone)[..., None]
        col = col * (1 + 0.05 * fnoise((res, res), lo=60, beta=0.5, seed=4))[..., None]
        col = lerp(col, hexc("#8d8a82"), gap)
        hgt = -gap * 0.004 + fnoise((res, res), lo=40, beta=1, seed=5) * 0.0002
        _save_base("tile_clad", col, hgt, 0.6 + 0.3 * gap, 1.0)


# ============================================================================ materials
# key: (albedo image or rgb, base texture size m, rough (img|float), metal, emit, plaster mask, wood mask, tint)
def MATS():
    return {
        "wood_dark": dict(img="wood_dark", rough="img", wood=1),
        "wood_bengara": dict(img="wood_bengara", rough="img", wood=1),
        "wood_honey": dict(img="wood_honey", rough="img", wood=1),
        "wood_silver": dict(img="wood_silver", rough="img", wood=1),
        "wood_vermilion": dict(img="wood_honey", rough=0.65, tint=(1.0, 0.40, 0.62), wood=1),
        "lattice_dark": dict(img="wood_dark", rough="img", wood=1, tint=(0.8, 0.8, 0.8)),
        "plaster_ochre": dict(img="plaster_ochre", rough="img", plas=1),
        "plaster_cream": dict(img="plaster_cream", rough="img", plas=1),
        "plaster_lime": dict(img="plaster_lime", rough="img", plas=1),
        "plaster_earth": dict(img="plaster_earth", rough="img", plas=1),
        "granite": dict(img="granite", rough="img"),
        "interior": dict(rgb=(0.030, 0.024, 0.019), rough=0.9),
        "interior_warm": dict(rgb=(0.09, 0.065, 0.045), rough=0.85, emit=0.6),
        "shoji": dict(rgb=(0.42, 0.40, 0.34), rough=0.9, emit=0.9),
        "glass": dict(rgb=(0.030, 0.034, 0.036), rough=0.04),
        "glass_shop": dict(rgb=(0.05, 0.05, 0.05), rough=0.04, emit=0.7),
        "alu": dict(rgb=(0.62, 0.63, 0.64), rough=0.35, metal=1.0),
        "alu_dark": dict(rgb=(0.20, 0.19, 0.18), rough=0.4, metal=1.0),
        "iron": dict(rgb=(0.06, 0.06, 0.06), rough=0.55, metal=0.8),
        "kawara": dict(rgb=(0.085, 0.09, 0.098), rough=0.5),
        "bamboo": dict(img="wood_honey", rough=0.5, tint=(0.75, 0.66, 0.5), wood=1),
        "sudare": dict(img="wood_honey", rough=0.7, tint=(0.95, 0.85, 0.62)),
        "noren_indigo": dict(img="noren_indigo", uvfit=1, rough=0.95),
        "noren_white": dict(img="noren_white", uvfit=1, rough=0.95),
        "noren_brown": dict(img="noren_brown", uvfit=1, rough=0.95),
        "noren_ai_short": dict(img="noren_ai_short", uvfit=1, rough=0.95),
        "sign_kanban": dict(img="sign_kanban", uvfit=1, rough=0.6, wood=1),
        "sign_modern": dict(img="sign_modern", uvfit=1, rough=0.4),
        "tile_clad": dict(img="tile_clad", rough="img"),
        "tile_grey": dict(img="granite", rough=0.45, tint=(0.35, 0.36, 0.38)),
        "goods": dict(attr="pcol", rough=0.5),
        "lamp": dict(rgb=(0.9, 0.85, 0.75), rough=0.5, emit=1.0),
        "concrete": dict(img="plaster_lime", rough="img", tint=(0.72, 0.72, 0.70), plas=1),
    }


def _img(name, noncolor=False):
    key = name + ("_nc" if noncolor else "")
    if key in bpy.data.images:
        return bpy.data.images[key]
    path = os.path.join(BASE, name)
    im = bpy.data.images.load(path)
    im.name = key
    if noncolor:
        im.colorspace_settings.name = "Non-Color"
    return im


def build_material(key, spec):
    if key in bpy.data.materials:
        return bpy.data.materials[key]
    m = bpy.data.materials.new(key)
    nt = m.node_tree
    nt.nodes.clear()
    N = nt.nodes.new
    L = nt.links.new
    out = N("ShaderNodeOutputMaterial")
    bsdf = N("ShaderNodeBsdfPrincipled")
    L(bsdf.outputs[0], out.inputs[0])
    pr = N("ShaderNodeAttribute"); pr.attribute_type = "GEOMETRY"; pr.attribute_name = "prand"

    def aov(name, sock=None, val=None, color=False):
        a = N("ShaderNodeOutputAOV"); a.aov_name = name
        tgt = a.inputs["Color" if color else "Value"]
        if sock is not None:
            L(sock, tgt)
        elif color:
            tgt.default_value = (*val, 1)
        else:
            tgt.default_value = val
        return a

    col_sock = None
    if "img" in spec:
        uv = N("ShaderNodeUVMap"); uv.uv_map = "UVMap"
        vec = uv.outputs[0]
        if not spec.get("uvfit"):
            off = N("ShaderNodeCombineXYZ")
            mul1 = N("ShaderNodeMath"); mul1.operation = "MULTIPLY"; mul1.inputs[1].default_value = 7.31
            mul2 = N("ShaderNodeMath"); mul2.operation = "MULTIPLY"; mul2.inputs[1].default_value = 3.77
            L(pr.outputs["Fac"], mul1.inputs[0]); L(pr.outputs["Fac"], mul2.inputs[0])
            L(mul1.outputs[0], off.inputs[0]); L(mul2.outputs[0], off.inputs[1])
            add = N("ShaderNodeVectorMath"); add.operation = "ADD"
            L(vec, add.inputs[0]); L(off.outputs[0], add.inputs[1])
            vec = add.outputs[0]
        ti = N("ShaderNodeTexImage"); ti.image = _img(spec["img"] + "_alb.png")
        L(vec, ti.inputs[0])
        col_sock = ti.outputs["Color"]
        nimg = os.path.join(BASE, spec["img"] + "_nrm.png")
        if os.path.exists(nimg):
            tn = N("ShaderNodeTexImage"); tn.image = _img(spec["img"] + "_nrm.png", True)
            L(vec, tn.inputs[0])
            nm = N("ShaderNodeNormalMap"); nm.uv_map = "UVMap"; nm.inputs["Strength"].default_value = 1.0
            L(tn.outputs["Color"], nm.inputs["Color"])
            L(nm.outputs[0], bsdf.inputs["Normal"])
        if spec.get("rough") == "img":
            tr = N("ShaderNodeTexImage"); tr.image = _img(spec["img"] + "_rgh.png", True)
            L(vec, tr.inputs[0])
            rough_sock = tr.outputs["Color"]
        else:
            rough_sock = None
    elif "attr" in spec:
        at = N("ShaderNodeAttribute"); at.attribute_type = "GEOMETRY"; at.attribute_name = spec["attr"]
        col_sock = at.outputs["Color"]
        rough_sock = None
    else:
        rough_sock = None
    # tint and per-part variation
    rgbn = N("ShaderNodeRGB"); rgbn.outputs[0].default_value = (*spec.get("rgb", (1, 1, 1)), 1)
    if col_sock is None:
        col_sock = rgbn.outputs[0]
    tint = spec.get("tint")
    if tint:
        mt = N("ShaderNodeMix"); mt.data_type = "RGBA"; mt.blend_type = "MULTIPLY"; mt.inputs[0].default_value = 1
        L(col_sock, mt.inputs[6]); mt.inputs[7].default_value = (*tint, 1)
        col_sock = mt.outputs[2]
    var = N("ShaderNodeMapRange"); var.inputs["To Min"].default_value = 0.88; var.inputs["To Max"].default_value = 1.12
    L(pr.outputs["Fac"], var.inputs["Value"])
    mv = N("ShaderNodeMix"); mv.data_type = "RGBA"; mv.blend_type = "MULTIPLY"; mv.inputs[0].default_value = 1
    L(col_sock, mv.inputs[6])
    cv = N("ShaderNodeCombineColor"); L(var.outputs[0], cv.inputs[0]); L(var.outputs[0], cv.inputs[1]); L(var.outputs[0], cv.inputs[2])
    L(cv.outputs[0], mv.inputs[7])
    col_sock = mv.outputs[2]
    L(col_sock, bsdf.inputs["Base Color"])
    aov("alb", col_sock, color=True)
    r = spec.get("rough", 0.8)
    if rough_sock is not None:
        sepc = N("ShaderNodeSeparateColor"); L(rough_sock, sepc.inputs[0])
        aov("rough", sepc.outputs[0]); L(sepc.outputs[0], bsdf.inputs["Roughness"])
    else:
        aov("rough", val=float(r)); bsdf.inputs["Roughness"].default_value = float(r)
    aov("metal", val=float(spec.get("metal", 0.0)))
    aov("emit", val=float(spec.get("emit", 0.0)))
    aov("plas", val=float(spec.get("plas", 0.0)))
    aov("wood", val=float(spec.get("wood", 0.0)))
    return m


# ============================================================================ geometry builder
class FB:
    """Facade builder collecting parts into one bmesh (one material slot per key)."""

    def __init__(self, W, H, seed=0):
        self.W, self.H = W, H
        self.bm = bmesh.new()
        self.uv = self.bm.loops.layers.uv.new("UVMap")
        self.pr = self.bm.faces.layers.float.new("prand")
        self.pc = self.bm.faces.layers.float_color.new("pcol")
        self.keys = []
        self.rng = np.random.default_rng(seed)
        self.glass = []     # (x0, x1, y0, y1, z, kind): glazing is applied in post (camera must see through it)

    def mi(self, key):
        if key not in self.keys:
            self.keys.append(key)
        return self.keys.index(key)

    def _finish_faces(self, faces, key, grain, rnd=None, col=None, uvfit=None):
        idx = self.mi(key)
        r = self.rng.random() if rnd is None else rnd
        for f in faces:
            f.material_index = idx
            f[self.pr] = r
            if col is not None:
                f[self.pc] = (*col, 1.0)
            n = f.normal
            ax = int(np.argmax(np.abs([n.x, n.y, n.z])))
            for lp in f.loops:
                x, y, z = lp.vert.co
                if uvfit is not None:
                    x0, x1, y0, y1 = uvfit
                    lp[self.uv].uv = ((x - x0) / (x1 - x0), (y - y0) / (y1 - y0))
                    continue
                if ax == 2:
                    uv = (x, y) if grain == "y" else (y, x)
                elif ax == 0:
                    uv = (z, y) if grain == "y" else (z, y)
                else:
                    uv = (x, z) if grain == "y" else (z, x)
                lp[self.uv].uv = uv

    def box(self, x0, x1, y0, y1, z0, z1, key, grain="y", rnd=None, col=None, back=False, bevel=None):
        """Box with a chamfered front (+Z) face so the orthographic normal pass picks up edge highlights."""
        if x1 - x0 <= 1e-5 or y1 - y0 <= 1e-5 or z1 - z0 <= 1e-5:
            return
        b = 0.004 if bevel is None else bevel
        b = min(b, 0.3 * (x1 - x0), 0.3 * (y1 - y0), 0.5 * (z1 - z0))
        bm = self.bm
        zf = z1 - b
        v = [bm.verts.new(c) for c in ((x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
                                         (x0, y0, zf), (x1, y0, zf), (x1, y1, zf), (x0, y1, zf),
                                         (x0 + b, y0 + b, z1), (x1 - b, y0 + b, z1), (x1 - b, y1 - b, z1),
                                         (x0 + b, y1 - b, z1))]
        fs = [(8, 9, 10, 11), (4, 5, 9, 8), (5, 6, 10, 9), (6, 7, 11, 10), (7, 4, 8, 11),
              (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
        if back:
            fs.append((3, 2, 1, 0))
        faces = [bm.faces.new([v[i] for i in f]) for f in fs]
        for f in faces:
            f.normal_update()
        self._finish_faces(faces, key, grain, rnd, col)

    def panel(self, x0, x1, y0, y1, z, key, holes=(), step=0.04, amp=0.0015, reveal=0.06, grain="y", seed=None,
              edge_dip=0.0):
        """Plaster-like grid panel at depth z with rectangular holes (with reveals), gently uneven."""
        xs = set(np.linspace(x0, x1, max(2, int((x1 - x0) / step) + 1)).round(5))
        ys = set(np.linspace(y0, y1, max(2, int((y1 - y0) / step) + 1)).round(5))
        for hx0, hx1, hy0, hy1 in holes:
            xs |= {round(hx0, 5), round(hx1, 5)}; ys |= {round(hy0, 5), round(hy1, 5)}
        xs = sorted(xs); ys = sorted(ys)
        rng = np.random.default_rng(self.rng.integers(1 << 30) if seed is None else seed)
        ph = rng.uniform(0, 6.28, 8)

        def disp(x, y):
            d = (np.sin(x * 3.1 + ph[0]) * np.sin(y * 2.3 + ph[1]) + 0.6 * np.sin(x * 7.7 + y * 5.1 + ph[2])
                 + 0.4 * np.sin(x * 13.0 - y * 11.0 + ph[3]))
            e = min(x - x0, x1 - x, y - y0, y1 - y)
            dip = edge_dip * math.exp(-max(e, 0) / 0.02)
            return amp * d / 2.0 - dip

        vmap = {}
        bm = self.bm

        def V(i, j):
            if (i, j) not in vmap:
                x, y = xs[i], ys[j]
                vmap[(i, j)] = bm.verts.new((x, y, z + disp(x, y)))
            return vmap[(i, j)]

        faces = []
        for i in range(len(xs) - 1):
            for j in range(len(ys) - 1):
                cx, cy = (xs[i] + xs[i + 1]) / 2, (ys[j] + ys[j + 1]) / 2
                if any(hx0 < cx < hx1 and hy0 < cy < hy1 for hx0, hx1, hy0, hy1 in holes):
                    continue
                f = bm.faces.new([V(i, j), V(i + 1, j), V(i + 1, j + 1), V(i, j + 1)])
                f.normal_update()
                faces.append(f)
        self._finish_faces(faces, key, grain, rnd=rng.random())
        for hx0, hx1, hy0, hy1 in holes:      # reveals
            for (a, b, c, d_) in (((hx0, hy0), (hx1, hy0), None, "b"), ((hx1, hy0), (hx1, hy1), None, "r"),
                                  ((hx1, hy1), (hx0, hy1), None, "t"), ((hx0, hy1), (hx0, hy0), None, "l")):
                p = [bm.verts.new((a[0], a[1], z)), bm.verts.new((b[0], b[1], z)),
                     bm.verts.new((b[0], b[1], z - reveal)), bm.verts.new((a[0], a[1], z - reveal))]
                f = bm.faces.new(p[::-1]); f.normal_update()
                self._finish_faces([f], key, grain)

    def ribbon(self, pts, width, key, normal_dir=(0, 0, 1), rnd=None, grain="y", thick=0.0):
        """Strip along a polyline pts (Nx3) of given width in X (for curved slats)."""
        bm = self.bm
        L_ = [bm.verts.new((p[0] - width / 2, p[1], p[2])) for p in pts]
        R_ = [bm.verts.new((p[0] + width / 2, p[1], p[2])) for p in pts]
        faces = []
        for i in range(len(pts) - 1):
            f = bm.faces.new([L_[i], R_[i], R_[i + 1], L_[i + 1]]); f.normal_update()
            if f.normal.z < 0:
                f.normal_flip()
            faces.append(f)
        self._finish_faces(faces, key, grain, rnd)

    def cyl(self, x, y, z, r, length, axis, key, seg=12, rnd=None, col=None):
        bm = self.bm
        ret = bmesh.ops.create_cone(bm, cap_ends=True, segments=seg, radius1=r, radius2=r, depth=length)
        vs = ret["verts"]
        from mathutils import Matrix
        rot = {"x": Matrix.Rotation(math.pi / 2, 4, "Y"), "y": Matrix.Rotation(math.pi / 2, 4, "X"),
               "z": Matrix.Identity(4)}[axis]
        bmesh.ops.transform(bm, matrix=Matrix.Translation((x, y, z)) @ rot, verts=vs)
        faces = list({f for v in vs for f in v.link_faces})
        for f in faces:
            f.normal_update()
        self._finish_faces(faces, key, "x" if axis == "x" else "y", rnd, col)

    def cloth(self, x0, x1, ytop, ybot, z, key, panels=3, slit=0.025, slit_from_top=0.12, amp=0.012, period=0.11,
              seed=0, uvfit=None):
        """Noren: panels hanging from a pole, with soft vertical folds and slits between panels."""
        bm = self.bm
        rng = np.random.default_rng(seed)
        total = x1 - x0
        pw = (total - slit * (panels - 1)) / panels
        uvfit = uvfit or (x0, x1, ybot, ytop)
        faces = []
        top_v = {}
        for p in range(panels):
            px0 = x0 + p * (pw + slit)
            nx, ny = max(8, int(pw / 0.012)), max(6, int((ytop - ybot) / 0.04))
            ph = rng.uniform(0, 6.28); sway = rng.uniform(-0.01, 0.01)
            grid = {}
            for i in range(nx + 1):
                for j in range(ny + 1):
                    x = px0 + pw * i / nx
                    t = j / ny                    # 0 = bottom, 1 = top
                    y = ybot + (ytop - ybot) * t
                    a = amp * (0.35 + 0.65 * (1 - t))
                    zz = z + a * math.sin((x - px0) / period * 2 * math.pi + ph) + 0.4 * a * math.sin(
                        (x - px0) / (period * 0.43) * 2 * math.pi + 2 * ph) + sway * (1 - t) ** 2
                    grid[(i, j)] = bm.verts.new((x, y, zz))
            for i in range(nx):
                for j in range(ny):
                    f = bm.faces.new([grid[(i, j)], grid[(i + 1, j)], grid[(i + 1, j + 1)], grid[(i, j + 1)]])
                    f.normal_update(); faces.append(f)
        self._finish_faces(faces, key, "y", uvfit=uvfit)
        # the slits are closed in the top band (the noren is one cloth there)
        self.box(x0, x1, ytop - slit_from_top, ytop, z - 0.004, z + 0.004, key, rnd=0.5)
        self.bm.faces.ensure_lookup_table()
        for f in list(self.bm.faces)[-9:]:
            for lp in f.loops:
                x, y, _ = lp.vert.co
                lp[self.uv].uv = ((x - uvfit[0]) / (uvfit[1] - uvfit[0]), (y - uvfit[2]) / (uvfit[3] - uvfit[2]))

    def to_object(self, name, mats):
        me = bpy.data.meshes.new(name)
        self.bm.normal_update()
        self.bm.to_mesh(me)
        self.bm.free()
        for k in self.keys:
            me.materials.append(build_material(k, mats[k]))
        ob = bpy.data.objects.new(name, me)
        bpy.context.scene.collection.objects.link(ob)
        return ob


# ============================================================================ module vocabulary
def posts(fb, key="wood_dark", y0=0.08, y1=None, w=0.12, z0=-0.12, z1=0.015):
    y1 = fb.H if y1 is None else y1
    fb.box(0, w / 2, y0, y1, z0, z1, key, rnd=0.31)
    fb.box(fb.W - w / 2, fb.W, y0, y1, z0, z1, key, rnd=0.31)


def base_stone(fb, h=0.08):
    fb.box(-0.0, fb.W, 0, h, -0.06, 0.035, "granite", grain="x")


def beam(fb, y0, y1, key="wood_dark", z0=-0.1, z1=0.03, rnd=None):
    fb.box(0, fb.W, y0, y1, z0, z1, key, grain="x", rnd=rnd)


def interior(fb, y0, y1, z=-0.9, key="interior", x0=0.0, x1=None):
    x1 = fb.W if x1 is None else x1
    fb.box(x0, x1, y0, y1, z - 0.02, z, key)


def lattice(fb, x0, x1, y0, y1, key, slat=0.022, gap=0.018, depth=0.04, z=0.0, rails=(), thick_every=0, grain="y"):
    n = int((x1 - x0 + gap) / (slat + gap))
    used = n * (slat + gap) - gap
    xs = x0 + (x1 - x0 - used) / 2
    for i in range(n):
        a = xs + i * (slat + gap)
        dd = depth * (1.3 if thick_every and i % thick_every == 0 else 1.0)
        fb.box(a, a + slat, y0, y1, z, z + dd, key, grain=grain)
    for ry in rails:
        fb.box(x0, x1, ry - 0.015, ry + 0.015, z - 0.025, z, key, grain="x")


def sliding_glass_door(fb, x0, x1, y0, y1, z, key="wood_dark", glass="glass", panes=(2, 3), kumiko=True):
    fr = 0.035
    fb.box(x0, x1, y0, y0 + 0.12, z, z + 0.03, key, grain="x")          # bottom rail / kickboard
    fb.box(x0, x1, y1 - fr, y1, z, z + 0.03, key, grain="x")
    fb.box(x0, x0 + fr, y0, y1, z, z + 0.03, key)
    fb.box(x1 - fr, x1, y0, y1, z, z + 0.03, key)
    if glass.startswith("glass"):
        fb.glass.append((x0 + fr, x1 - fr, y0 + 0.12, y1 - fr, z + 0.005, glass))
    else:
        fb.box(x0 + fr, x1 - fr, y0 + 0.12, y1 - fr, z - 0.01, z + 0.005, glass)
    if kumiko:
        nx, ny = panes
        for i in range(1, nx):
            xx = x0 + (x1 - x0) * i / nx
            fb.box(xx - 0.008, xx + 0.008, y0 + 0.12, y1 - fr, z, z + 0.02, key)
        for j in range(1, ny):
            yy = y0 + 0.12 + (y1 - fr - y0 - 0.12) * j / ny
            fb.box(x0 + fr, x1 - fr, yy - 0.008, yy + 0.008, z, z + 0.02, key, grain="x")


def goods_shelf(fb, x0, x1, y, z0, z1, rng, density=1.0):
    """Shelf board + random generic goods (boxes, jars, bowls) - colours only, no branding."""
    fb.box(x0, x1, y - 0.025, y, z0, z1, "wood_honey", grain="x")
    pal = [hexc(c) for c in ("#d8cdb8", "#8c3a2c", "#2f4a6b", "#c99a3b", "#e8e2d4", "#5e7046", "#b85f3c",
                             "#3c3a3a", "#d6a0a0", "#f2efe8", "#6a4b8a", "#9fb3c4")]
    x = x0 + 0.02
    while x < x1 - 0.06:
        w = rng.uniform(0.05, 0.16) * (1 if rng.random() < 0.7 else 0.6)
        if x + w > x1 - 0.02:
            break
        h = rng.uniform(0.05, 0.22)
        d = rng.uniform(0.06, min(0.2, z1 - z0 - 0.02))
        zc = rng.uniform(z0 + 0.01, z1 - d)
        c = pal[rng.integers(len(pal))] * rng.uniform(0.8, 1.1)
        c = s2l(np.clip(c, 0, 1))
        if rng.random() < 0.3:
            fb.cyl(x + w / 2, y + h / 2, zc + d / 2, min(w, d) / 2, h, "y", "goods", seg=10, col=tuple(c))
        else:
            fb.box(x, x + w, y, y + h, zc, zc + d, "goods", col=tuple(c))
        x += w + rng.uniform(0.005, 0.04) / density


def kawara_cap(fb, y0, y1, depth=0.30):
    """Tiled coping seen frontally (dobei / fence cap): eave board, eave tiles with round ends,
    marugawara ribs on the short slope, noshi stack + kanmuri ridge."""
    W = fb.W
    p = 0.30
    fb.box(0, W, y0, y0 + 0.07, -0.05, depth * 0.5, "wood_dark", grain="x")                # kayaoi board
    ye = y0 + 0.07
    fb.box(0, W, ye, ye + 0.05, -0.05, depth, "kawara", grain="x", bevel=0.01)            # eave tile lip
    for x in np.arange(p / 2 - p, W + p, p):
        fb.cyl(x, ye + 0.07, depth + 0.012, 0.065, 0.03, "z", "kawara", seg=18)           # round tile ends
    ys = ye + 0.05
    yr = y1 - 0.13
    fb.box(0, W, ys, yr, -0.05, depth * 0.55, "kawara", grain="x", bevel=0.0)
    for x in np.arange(p / 2 - p, W + p, p):
        fb.cyl(x, (ys + yr) / 2, depth * 0.55, 0.055, yr - ys, "y", "kawara", seg=12)
    for k in range(3):                                                                    # noshi stack
        yy = yr + k * 0.03
        fb.box(-0.01, W + 0.01, yy, yy + 0.027, -0.05, 0.1 - k * 0.015, "kawara", grain="x", bevel=0.006)
    fb.cyl(W / 2, y1 - 0.035, 0.04, 0.05, W + 0.4, "x", "kawara", seg=14)


def inuyarai(fb, x0, x1, h=0.95, depth=0.42, pitch=0.05, key="bamboo"):
    n = int((x1 - x0) / pitch)
    for i in range(n):
        x = x0 + (i + 0.5) * (x1 - x0) / n
        pts = [(x, h * math.sin(a), 0.02 + depth * math.cos(a)) for a in np.linspace(0, math.pi / 2, 16)]
        fb.ribbon(pts, 0.022, key, rnd=0.2 + 0.1 * (i % 3))
    for yy in (0.25, 0.6, 0.9):  # horizontal ties
        zt = 0.02 + depth * math.sqrt(max(0.0, 1 - (yy / h) ** 2))
        fb.box(x0, x1, yy, yy + 0.02, zt, zt + 0.02, "iron", grain="x")


# ----------------------------------------------------------------------------- the modules
def m_senkoshi(fb, wood="wood_bengara", upper="plaster_ochre"):
    W = fb.W
    base_stone(fb)
    interior(fb, 0.08, 2.05)
    fb.box(0, W, 0.08, 0.22, -0.1, 0.04, wood, grain="x")                       # dodai / sill
    # shoji & glass doors behind the lattice
    sliding_glass_door(fb, 0.06, W / 2 + 0.02, 0.22, 2.0, -0.2, "wood_dark", "shoji", panes=(3, 6))
    sliding_glass_door(fb, W / 2 - 0.02, W - 0.06, 0.22, 2.0, -0.24, "wood_dark", "glass", panes=(2, 4))
    # degōshi frame + slats (oyako-gōshi: every 4th slat deeper)
    fb.box(0.06, 0.11, 0.22, 2.05, -0.05, 0.06, wood)
    fb.box(W - 0.11, W - 0.06, 0.22, 2.05, -0.05, 0.06, wood)
    fb.box(0.11, W - 0.11, 0.22, 0.32, -0.05, 0.057, wood, grain="x")
    fb.box(0.11, W - 0.11, 1.94, 2.05, -0.05, 0.057, wood, grain="x")
    lattice(fb, 0.11, W - 0.11, 0.32, 1.94, wood, slat=0.022, gap=0.017, depth=0.04, z=0.01,
            rails=(0.75, 1.45), thick_every=4)
    posts(fb, wood)
    beam(fb, 2.05, 2.2, wood)
    fb.panel(0.06, W - 0.06, 2.2, 2.8, -0.01, upper, step=0.05, amp=0.0015)
    beam(fb, 2.8, 2.92, wood, z1=0.04)
    fb.box(0.06, W - 0.06, 2.92, 3.0, -0.08, -0.01, wood, grain="x")


def m_shop_open(fb, noren="noren_brown", seed=5, wall="plaster_cream", kanban=True):
    W = fb.W
    rng = np.random.default_rng(seed)
    base_stone(fb)
    interior(fb, 0.0, 2.05, z=-1.6, key="interior_warm")
    # back shelves (lit)
    for y in (0.75, 1.15, 1.55):
        goods_shelf(fb, 0.15, W - 0.15, y, -1.5, -1.2, rng)
    fb.box(0.1, W - 0.1, 1.95, 2.0, -1.55, -0.5, "lamp", grain="x")
    # front display platform with goods
    fb.box(0.06, W - 0.06, 0.08, 0.55, -0.3, 0.06, "wood_honey", grain="x")
    fb.box(0.06, W - 0.06, 0.08, 0.5, 0.0, 0.07, "wood_dark", grain="x")
    goods_shelf(fb, 0.1, W - 0.1, 0.57, -0.28, 0.04, rng, density=0.8)
    goods_shelf(fb, 0.2, W - 0.2, 1.0, -0.6, -0.4, rng)
    posts(fb, "wood_dark")
    beam(fb, 2.05, 2.2, "wood_dark")
    fb.cyl(W / 2, 2.03, 0.05, 0.012, W - 0.12, "x", "bamboo")
    fb.cloth(0.07, W - 0.07, 2.04, 1.6, 0.06, noren, panels=4, slit=0.012, slit_from_top=0.1, amp=0.008, seed=seed)
    fb.box(0.25, W - 0.25, 2.3, 2.66, 0.0, 0.04, "sign_kanban" if kanban else "wood_dark", grain="x")
    fb.bm.faces.ensure_lookup_table()
    # re-map the signboard front face to the sign image
    f = fb.bm.faces[-9]
    for lp in f.loops:
        x, y, _ = lp.vert.co
        lp[fb.uv].uv = ((x - 0.25) / (W - 0.5), (y - 2.3) / 0.36) if kanban else (x, y)
    fb.panel(0.06, W - 0.06, 2.2, 2.8, -0.01, wall, step=0.05)
    beam(fb, 2.8, 2.92, "wood_dark", z1=0.04)
    fb.box(0.06, W - 0.06, 2.92, 3.0, -0.08, -0.01, "wood_dark", grain="x")


def m_noren_entrance(fb):
    W = fb.W
    base_stone(fb)
    interior(fb, 0.08, 2.05, z=-1.2, key="interior_warm")
    fb.box(0.06, W - 0.06, 0.0, 0.06, -1.2, 0.02, "granite", grain="x")
    # sliding entrance door (half open) recessed
    sliding_glass_door(fb, 0.62, 1.22, 0.06, 2.0, -0.16, "wood_dark", "glass", panes=(1, 5))
    fb.box(0.06, 0.62, 0.06, 2.0, -1.2, -1.15, "interior")
    # fixed koshi on the right
    fb.box(1.22, W - 0.06, 0.08, 0.3, -0.1, 0.03, "wood_dark", grain="x")
    lattice(fb, 1.25, W - 0.09, 0.3, 2.0, "wood_dark", slat=0.02, gap=0.016, depth=0.035, z=-0.02, rails=(1.0,))
    interior(fb, 0.3, 2.0, z=-0.3, x0=1.22, x1=W - 0.06)
    fb.box(1.2, 1.25, 0.06, 2.05, -0.12, 0.03, "wood_dark")
    posts(fb, "wood_dark")
    beam(fb, 2.05, 2.2, "wood_dark")
    fb.cyl(0.65, 2.02, 0.07, 0.014, 1.15, "x", "bamboo")
    fb.cloth(0.1, 1.2, 2.02, 0.95, 0.07, "noren_indigo", panels=3, slit=0.02, slit_from_top=0.18, amp=0.014, seed=4)
    fb.panel(0.06, W - 0.06, 2.2, 2.8, -0.01, "plaster_ochre", step=0.05)
    beam(fb, 2.8, 2.92, "wood_dark", z1=0.04)
    fb.box(0.06, W - 0.06, 2.92, 3.0, -0.08, -0.01, "wood_dark", grain="x")


def m_plaster_base(fb, with_inuyarai=True, plaster="plaster_ochre"):
    W = fb.W
    base_stone(fb)
    fb.box(0.0, W, 0.08, 0.18, -0.08, 0.035, "wood_dark", grain="x")
    # koshi-ita (vertical board skirting) to 0.9 m with a cap batten
    x = 0.06
    rng = np.random.default_rng(int(W * 100))
    while x < W - 0.07:
        bw = min(rng.uniform(0.17, 0.24), W - 0.06 - x)
        fb.box(x + 0.0015, x + bw - 0.0015, 0.18, 0.9, -0.01, 0.012, "wood_silver")
        x += bw
    fb.box(0.06, W - 0.06, 0.9, 0.95, -0.02, 0.03, "wood_dark", grain="x")
    fb.panel(0.06, W - 0.06, 0.95, 2.8, -0.012, plaster, step=0.05, amp=0.002, edge_dip=0.002)
    posts(fb, "wood_dark")
    fb.box(0.06, W - 0.06, 2.05, 2.17, -0.1, 0.01, "wood_dark", grain="x")              # nuki beam
    beam(fb, 2.8, 2.92, "wood_dark", z1=0.04)
    fb.box(0.06, W - 0.06, 2.92, 3.0, -0.08, -0.01, "wood_dark", grain="x")
    if with_inuyarai:
        inuyarai(fb, 0.08, W - 0.08)


def m_itabari(fb):
    W = fb.W
    base_stone(fb)
    fb.box(0, W, 0.08, 0.18, -0.08, 0.03, "wood_dark", grain="x")
    rng = np.random.default_rng(int(W * 77))
    x = 0.06
    while x < W - 0.07:
        bw = min(rng.uniform(0.18, 0.26), W - 0.06 - x)
        key = "wood_dark" if rng.random() < 0.75 else "wood_silver"
        fb.box(x + 0.002, x + bw - 0.002, 0.18, 2.05, -0.012, 0.008 + rng.uniform(0, 0.004), key)
        x += bw
    for yy in (0.7, 1.45):                                                           # oshibuchi battens
        fb.box(0.06, W - 0.06, yy, yy + 0.04, 0.008, 0.03, "wood_dark", grain="x")
    posts(fb, "wood_dark")
    beam(fb, 2.05, 2.2, "wood_dark")
    fb.panel(0.06, W - 0.06, 2.2, 2.8, -0.01, "plaster_cream", step=0.05)
    beam(fb, 2.8, 2.92, "wood_dark", z1=0.04)
    fb.box(0.06, W - 0.06, 2.92, 3.0, -0.08, -0.01, "wood_dark", grain="x")


def m_modern_shopfront(fb):
    W = fb.W
    rng = np.random.default_rng(11)
    fb.box(0, W, 0, 0.3, -0.04, 0.02, "granite", grain="x")
    interior(fb, 0.0, 2.6, z=-2.0, key="interior_warm")
    for y in (0.6, 1.0, 1.4, 1.8):
        goods_shelf(fb, 0.1, W - 0.1, y, -1.9, -1.6, rng)
    goods_shelf(fb, 0.3, W - 0.3, 0.85, -0.9, -0.5, rng)
    fb.box(0.1, W - 0.1, 2.5, 2.55, -1.9, -0.3, "lamp", grain="x")
    fb.box(0, 0.035, 0.3, 2.35, -0.06, 0.02, "alu")
    fb.box(W - 0.035, W, 0.3, 2.35, -0.06, 0.02, "alu")
    fb.box(W / 2 - 0.02, W / 2 + 0.02, 0.3, 2.35, -0.06, 0.01, "alu")
    fb.box(0, W, 0.3, 0.36, -0.06, 0.01, "alu", grain="x")
    fb.box(0, W, 2.3, 2.36, -0.06, 0.02, "alu", grain="x")
    fb.glass.append((0.035, W - 0.035, 0.36, 2.3, -0.04, "glass_shop"))
    # signage band (generic word on a dark panel), drawn over two bays via uv
    fb.box(0, W, 2.36, 2.95, -0.02, 0.05, "sign_modern", grain="x")
    fb.bm.faces.ensure_lookup_table()
    f = fb.bm.faces[-9]
    for lp in f.loops:
        x, y, _ = lp.vert.co
        lp[fb.uv].uv = (x / W, (y - 2.36) / 0.59)
    fb.box(0, W, 2.95, 3.0, -0.02, 0.06, "alu_dark", grain="x")


def m_temple_dobei(fb):
    W = fb.W
    # rough cut-stone base
    rng = np.random.default_rng(3)
    x = 0.0
    while x < W:
        bw = min(rng.uniform(0.35, 0.6), W - x)
        fb.box(x + 0.006, x + bw - 0.006, 0.0, 0.42, -0.05, 0.06 + rng.uniform(0, 0.01), "granite", grain="x")
        x += bw
    fb.panel(0.0, W, 0.42, 2.38, 0.0, "plaster_ochre", step=0.05, amp=0.003)
    for k in range(5):                                                               # sujibei lines (white)
        yy = 1.7 + k * 0.1
        fb.box(0.0, W, yy, yy + 0.022, -0.001, 0.004, "plaster_lime", grain="x", rnd=0.5)
    kawara_cap(fb, 2.38, 3.0)


def m_white_plaster_timber(fb, wood="wood_dark"):
    W = fb.W
    fb.box(0, W, 0, 0.3, -0.04, 0.05, "granite", grain="x")
    fb.box(0, W, 0.3, 0.45, -0.1, 0.04, wood, grain="x")
    fb.panel(0.06, W - 0.06, 0.45, 2.85, -0.01, "plaster_lime", step=0.05, amp=0.0015, edge_dip=0.0015)
    posts(fb, wood, y0=0.3)
    for y0, y1 in ((1.05, 1.18), (2.15, 2.3)):
        beam(fb, y0, y1, wood, z0=-0.05, z1=0.035)
    beam(fb, 2.85, 3.0, wood, z1=0.05)


def m_uf_common(fb, wood="wood_dark", posts_on=True):
    W = fb.W
    beam(fb, 0.0, 0.16, wood, z1=0.035)                    # dōsashi (floor beam) - hisashi meets it
    beam(fb, 2.24, 2.4, wood, z0=-0.1, z1=0.05)            # nokigeta / eave plate
    if posts_on:
        posts(fb, wood, y0=0.16, y1=2.24)


def m_uf_mushikomado(fb, plaster="plaster_cream", n=1):
    W = fb.W
    beam(fb, 0.0, 0.14, "wood_dark", z1=0.03)
    holes = []
    ww = min(1.3, W - 0.4)
    x0 = (W - ww) / 2
    holes.append((x0, x0 + ww, 0.75, 1.32))
    fb.panel(0.0, W, 0.14, 2.28, 0.01, plaster, holes=holes, step=0.04, amp=0.003, reveal=0.1)
    interior(fb, 0.7, 1.4, z=-0.45)
    fb.box(x0, x0 + ww, 0.75, 1.32, -0.33, -0.31, "shoji")
    # plaster-coated bars (rounded look via two boxes)
    pitch = 0.085
    nb = int(ww / pitch)
    for i in range(nb):
        xc = x0 + (i + 0.5) * ww / nb
        fb.box(xc - 0.022, xc + 0.022, 0.75, 1.32, -0.07, 0.005, plaster, rnd=0.4)
        fb.box(xc - 0.015, xc + 0.015, 0.75, 1.32, 0.005, 0.012, plaster, rnd=0.4)
    # raised moulded frame
    fb.box(x0 - 0.05, x0 + ww + 0.05, 0.70, 0.75, 0.01, 0.04, plaster, grain="x", rnd=0.45)
    fb.box(x0 - 0.05, x0 + ww + 0.05, 1.32, 1.37, 0.01, 0.04, plaster, grain="x", rnd=0.45)
    fb.box(x0 - 0.05, x0, 0.75, 1.32, 0.01, 0.04, plaster, rnd=0.45)
    fb.box(x0 + ww, x0 + ww + 0.05, 0.75, 1.32, 0.01, 0.04, plaster, rnd=0.45)
    fb.box(0, W, 2.28, 2.4, -0.1, 0.05, "wood_dark", grain="x")


def m_uf_window_lattice(fb, plaster="plaster_ochre"):
    W = fb.W
    m_uf_common(fb)
    ww = W - 0.12 - 0.2
    x0 = 0.06 + 0.1
    hole = (x0, x0 + ww, 0.55, 1.65)
    fb.panel(0.06, W - 0.06, 0.16, 2.24, -0.01, plaster, holes=[hole], step=0.05, reveal=0.12)
    interior(fb, 0.5, 1.7, z=-0.6)
    sliding_glass_door(fb, x0, x0 + ww / 2 + 0.02, 0.55, 1.65, -0.13, "wood_dark", "shoji", panes=(3, 4))
    sliding_glass_door(fb, x0 + ww / 2 - 0.02, x0 + ww, 0.55, 1.65, -0.16, "wood_dark", "glass", panes=(1, 2), kumiko=False)
    fb.box(x0 - 0.03, x0 + ww + 0.03, 0.5, 0.56, -0.03, 0.06, "wood_dark", grain="x")
    fb.box(x0 - 0.03, x0 + ww + 0.03, 1.65, 1.71, -0.03, 0.05, "wood_dark", grain="x")
    lattice(fb, x0, x0 + ww, 0.56, 1.65, "wood_dark", slat=0.03, gap=0.03, depth=0.035, z=0.012, rails=(1.1,))


def m_uf_plaster(fb, plaster="plaster_cream"):
    W = fb.W
    m_uf_common(fb)
    fb.panel(0.06, W - 0.06, 0.16, 2.24, -0.012, plaster, step=0.05, amp=0.002, edge_dip=0.002)
    fb.box(0.06, W - 0.06, 1.2, 1.3, -0.08, 0.008, "wood_dark", grain="x")      # exposed nuki


def m_uf_glazed_railing(fb, plaster="plaster_ochre"):
    W = fb.W
    m_uf_common(fb)
    hole = (0.06, W - 0.06, 0.35, 1.9)
    fb.panel(0.06, W - 0.06, 0.16, 2.24, -0.012, plaster, holes=[hole], step=0.05, reveal=0.1)
    interior(fb, 0.3, 1.95, z=-0.7)
    sliding_glass_door(fb, 0.06, W / 2 + 0.015, 0.35, 1.9, -0.1, "wood_honey", "glass", panes=(2, 2))
    sliding_glass_door(fb, W / 2 - 0.015, W - 0.06, 0.35, 1.9, -0.13, "wood_honey", "glass", panes=(2, 2))
    # sudare blind half lowered over the right pane
    for k in range(int(0.55 / 0.012)):
        yy = 1.88 - k * 0.012
        fb.box(W / 2, W - 0.08, yy - 0.006, yy, -0.04, -0.035, "sudare", grain="x", rnd=0.3 + 0.2 * (k % 2))
    # railing (tesuri)
    fb.box(0.0, W, 0.78, 0.84, 0.10, 0.16, "wood_dark", grain="x")
    fb.box(0.0, W, 0.2, 0.24, 0.10, 0.14, "wood_dark", grain="x")
    for x in np.arange(0.055, W, 0.11):
        fb.box(x - 0.012, x + 0.012, 0.24, 0.78, 0.11, 0.135, "wood_dark")


def m_modern_uf_window(fb):
    W = fb.W
    fb.panel(0.0, W, 0.0, fb.H, 0.0, "tile_clad", holes=[(0.3, W - 0.3, 0.9, 2.1)], step=0.1, amp=0.0003, reveal=0.12)
    interior(fb, 0.85, 2.15, z=-0.8)
    fb.box(0.3, W - 0.3, 0.9, 2.1, -0.5, -0.48, "shoji")                         # curtain (light)
    fb.glass.append((0.3, W - 0.3, 0.9, 2.1, -0.1, "glass"))
    for (a, b, c, d) in ((0.3, W - 0.3, 0.9, 0.95), (0.3, W - 0.3, 2.05, 2.1), (0.3, 0.35, 0.9, 2.1),
                         (W - 0.35, W - 0.3, 0.9, 2.1), (W / 2 - 0.02, W / 2 + 0.02, 0.9, 2.1)):
        fb.box(a, b, c, d, -0.12, -0.06, "alu", grain="x" if b - a > d - c else "y")
    fb.box(0.25, W - 0.25, 0.85, 0.9, -0.05, 0.05, "alu", grain="x")             # sill flashing
    fb.box(0, W, fb.H - 0.12, fb.H, -0.02, 0.03, "concrete", grain="x")          # floor slab edge band


def m_glazed_doors(fb):
    """Renovated shop front: four glazed wooden sliding doors with lower kick boards + short wave-pattern noren."""
    W = fb.W
    base_stone(fb)
    interior(fb, 0.06, 2.05, z=-1.4, key="interior_warm")
    rng = np.random.default_rng(21)
    for y in (0.9, 1.35):
        goods_shelf(fb, 0.15, W - 0.15, y, -1.35, -1.1, rng)
    fb.box(0.06, W - 0.06, 0.0, 0.06, -1.3, 0.02, "granite", grain="x")
    pw = (W - 0.12) / 2
    for k in range(2):
        x0 = 0.06 + k * pw
        sliding_glass_door(fb, x0, x0 + pw + (0.02 if k == 0 else 0), 0.06, 2.0, -0.08 - 0.03 * k, "wood_honey", "glass",
                           panes=(2, 4))
        fb.box(x0 + 0.035, x0 + pw - 0.035, 0.06, 0.45, -0.09 - 0.03 * k, -0.07 - 0.03 * k, "wood_honey")
    posts(fb, "wood_dark")
    beam(fb, 2.05, 2.2, "wood_dark")
    fb.cyl(W / 2, 2.03, 0.06, 0.012, W - 0.12, "x", "bamboo")
    fb.cloth(0.07, W - 0.07, 2.04, 1.62, 0.07, "noren_ai_short", panels=3, slit=0.015, slit_from_top=0.1, amp=0.01, seed=8)
    fb.panel(0.06, W - 0.06, 2.2, 2.8, -0.01, "plaster_ochre", step=0.05)
    beam(fb, 2.8, 2.92, "wood_dark", z1=0.04)
    fb.box(0.06, W - 0.06, 2.92, 3.0, -0.08, -0.01, "wood_dark", grain="x")


def m_kura_namako(fb):
    """Kura (storehouse) wall: white shikkui with a namako-kabe dado (grey square tiles, raised white diagonal joints)."""
    W = fb.W
    fb.box(0, W, 0, 0.25, -0.04, 0.06, "granite", grain="x")
    fb.panel(0.0, W, 1.05, 3.0, 0.0, "plaster_lime", step=0.05, amp=0.0012)
    fb.box(0.0, W, 1.0, 1.08, 0.0, 0.04, "plaster_lime", grain="x", rnd=0.5)              # mizukiri ledge
    fb.box(0.0, W, 0.25, 1.0, -0.01, 0.0, "tile_grey")
    p = 0.182 * 2 ** 0.5                                   # 6-sun (182 mm) square tiles set diagonally
    for k in range(-6, int(W / p) + 7):
        for sgn in (1, -1):
            pts = [(k * p + sgn * (y - 0.25), y, 0.004 + 0.008) for y in np.linspace(0.25, 1.0, 10)]
            fb.ribbon(pts, 0.03, "plaster_lime", rnd=0.5)
            pts = [(k * p + sgn * (y - 0.25), y, 0.016) for y in np.linspace(0.25, 1.0, 10)]
            fb.ribbon(pts, 0.016, "plaster_lime", rnd=0.5)


def m_itabei_fence(fb):
    """Tall board fence (板塀) with a plaster upper band and tile coping on a rubble plinth - observed on Yasaka-dori east."""
    W = fb.W
    rng = np.random.default_rng(31)
    x = 0.0
    while x < W:
        bw = min(rng.uniform(0.25, 0.4), W - x)
        fb.box(x + 0.004, x + bw - 0.004, 0.0, 0.35, -0.05, 0.06 + rng.uniform(0, 0.02), "granite", grain="x", bevel=0.02)
        x += bw
    x = 0.06
    while x < W - 0.07:
        bw = min(rng.uniform(0.17, 0.24), W - 0.06 - x)
        fb.box(x + 0.002, x + bw - 0.002, 0.35, 1.75, -0.01, 0.01, "wood_dark" if rng.random() < 0.7 else "wood_silver")
        x += bw
    for yy in (0.8, 1.45):
        fb.box(0.06, W - 0.06, yy, yy + 0.035, 0.01, 0.03, "wood_dark", grain="x")
    posts(fb, "wood_dark", y0=0.35, y1=2.0, z1=0.04)
    fb.box(0.06, W - 0.06, 1.75, 1.85, -0.04, 0.03, "wood_dark", grain="x")
    fb.panel(0.06, W - 0.06, 1.85, 2.0, -0.005, "plaster_lime", step=0.04)
    kawara_cap(fb, 2.0, 2.4, depth=0.22)


def m_modern_gf_entrance(fb):
    """Modern house ground floor: tile cladding, aluminium entrance door with frosted glass."""
    W = fb.W
    fb.box(0, W, 0, 0.12, -0.04, 0.03, "granite", grain="x")
    fb.panel(0.0, W, 0.12, fb.H, 0.0, "tile_clad", holes=[(0.35, 1.3, 0.12, 2.1)], step=0.1, amp=0.0003, reveal=0.1)
    fb.box(0.35, 1.3, 0.12, 2.1, -0.12, -0.08, "alu_dark")
    fb.box(0.45, 1.2, 0.5, 1.95, -0.08, -0.075, "shoji")
    fb.box(1.1, 1.16, 1.0, 1.2, -0.075, -0.04, "alu")
    fb.box(1.45, W - 0.08, 2.3, 2.42, 0.0, 0.25, "alu", grain="x")                         # canopy edge
    fb.box(0, W, fb.H - 0.12, fb.H, -0.02, 0.03, "concrete", grain="x")


# name -> (builder, W, H, floor, kind, tags, has_emissive, evidence note)
MODULES = [
    ("machiya_gf_senkoshi", lambda fb: m_senkoshi(fb, "wood_bengara", "plaster_ochre"), BAY, 3.0, "gf", "lattice",
     ["traditional"], True, "documented: 出格子/平格子 on 1F, べんがら timber (Sanneizaka plan); slat 22 mm / gap 17 mm inferred"),
    ("machiya_gf_senkoshi_dark", lambda fb: m_senkoshi(fb, "wood_dark", "plaster_cream"), BAY, 3.0, "gf", "lattice",
     ["traditional"], True, "observed: dark-stained sen-koshi on closed bays"),
    ("machiya_gf_shop_open", m_shop_open, BAY, 3.0, "gf", "shop", ["traditional", "commercial"], True,
     "observed: open shopfronts, short noren, display platforms; goods generic"),
    ("machiya_gf_noren_entrance", m_noren_entrance, BAY, 3.0, "gf", "entrance", ["traditional", "commercial"], True,
     "observed: glazed wooden sliding doors + indigo noren; crest/kana generic"),
    ("machiya_gf_plaster_base", m_plaster_base, BAY, 3.0, "gf", "wall", ["traditional"], False,
     "documented/observed: plaster with board skirting; inuyarai observed on Ishin-no-michi, inferred on slopes"),
    ("machiya_gf_itabari", m_itabari, BAY, 3.0, "gf", "wall", ["traditional"], False,
     "observed: vertical dark board walls (板張り) with battens"),
    ("modern_gf_shopfront", m_modern_shopfront, BAY, 3.0, "gf", "shop", ["modern", "commercial"], True,
     "observed: aluminium/glass shopfronts + sign band on Yasaka-dori west; text generic"),
    ("temple_dobei", m_temple_dobei, BAY, 3.0, "gf", "wall", ["temple"], False,
     "inferred: earthen tsuiji wall with 5 sujibei lines + tile coping (generic temple vocabulary)"),
    ("white_plaster_timber", m_white_plaster_timber, BAY, 3.0, "gf", "wall", ["temple"], False,
     "observed: white plaster between dark timber (Koshin-do main hall, kura)"),
    ("white_plaster_vermilion", lambda fb: m_white_plaster_timber(fb, "wood_vermilion"), BAY, 3.0, "gf", "wall",
     ["temple"], False, "observed: Koshin-do vermilion (#c0503a) posts/beams with white plaster"),
    ("machiya_gf_senkoshi_half", lambda fb: m_senkoshi(fb, "wood_bengara", "plaster_ochre"), HALF, 3.0, "gf", "lattice",
     ["traditional", "half"], True, "half-bay variant"),
    ("machiya_gf_itabari_half", m_itabari, HALF, 3.0, "gf", "wall", ["traditional", "half"], False, "half-bay variant"),
    ("machiya_gf_plaster_base_half", lambda fb: m_plaster_base(fb, False), HALF, 3.0, "gf", "wall",
     ["traditional", "half"], False, "half-bay variant (no inuyarai)"),
    ("machiya_uf_mushikomado", m_uf_mushikomado, BAY, 2.4, "uf", "window", ["traditional"], True,
     "documented: 虫籠窓 district rule; placed sparingly (photos mostly show glazed lattice windows)"),
    ("machiya_uf_window_lattice", m_uf_window_lattice, BAY, 2.4, "uf", "window", ["traditional"], True,
     "observed: glazed wooden lattice windows on 2F"),
    ("machiya_uf_plaster", m_uf_plaster, BAY, 2.4, "uf", "wall", ["traditional"], False,
     "observed: cream/pale-ochre plaster between dark posts and beams"),
    ("machiya_uf_glazed_railing", m_uf_glazed_railing, BAY, 2.4, "uf", "window", ["traditional"], True,
     "observed: glazed sliding windows, sudare, wooden balcony railings on 2F fronts"),
    ("machiya_uf_plaster_half", m_uf_plaster, HALF, 2.4, "uf", "wall", ["traditional", "half"], False, "half-bay"),
    ("machiya_uf_window_lattice_half", m_uf_window_lattice, HALF, 2.4, "uf", "window", ["traditional", "half"], True,
     "half-bay"),
    ("modern_uf_window", m_modern_uf_window, BAY, 3.0, "uf", "window", ["modern"], True,
     "generic: RC/steel building, nichōgake tile cladding + aluminium sash"),
    ("machiya_gf_shop_open_b", lambda fb: m_shop_open(fb, "noren_white", 17, "plaster_ochre", False), BAY, 3.0, "gf",
     "shop", ["traditional", "commercial"], True, "observed: open shopfront with white noren; goods generic"),
    ("machiya_gf_glazed_doors", m_glazed_doors, BAY, 3.0, "gf", "entrance", ["traditional", "commercial"], True,
     "observed: glazed wooden sliding doors with kick boards and short noren (renovated shops)"),
    ("kura_white_namako", m_kura_namako, BAY, 3.0, "gf", "wall", ["traditional", "kura"], False,
     "observed: white kura-style plastered building (Kiyomizu Sannenzaka Museum); namako dado generic"),
    ("modern_gf_entrance", m_modern_gf_entrance, BAY, 3.0, "gf", "entrance", ["modern"], False,
     "generic: modern house entrance, tile cladding + aluminium door"),
    ("board_fence_itabei", m_itabei_fence, BAY, 2.4, "gf", "fence", ["traditional", "fence"], False,
     "observed: tall board fences with plaster band and tile coping on rubble plinths (Yasaka-dori east, south side)"),
    ("machiya_uf_mushikomado_ochre", lambda fb: m_uf_mushikomado(fb, "plaster_ochre"), BAY, 2.4, "uf", "window",
     ["traditional"], True, "documented 虫籠窓, ochre plaster variant"),
    ("machiya_uf_plaster_ochre", lambda fb: m_uf_plaster(fb, "plaster_ochre"), BAY, 2.4, "uf", "wall", ["traditional"],
     False, "observed: pale-ochre plaster variant"),
]


# ============================================================================ render
def setup_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.device = "CPU"
    sc.render.compositor_device = "CPU"
    sc.cycles.samples = int(os.environ.get("TEXLIB_SPP", "48"))
    sc.cycles.use_denoising = False
    sc.cycles.use_adaptive_sampling = False
    sc.cycles.max_bounces = 0
    sc.cycles.caustics_reflective = False
    sc.render.film_transparent = False
    sc.render.threads_mode = "FIXED"
    sc.render.threads = int(os.environ.get("TEXLIB_THREADS", "3"))
    w = bpy.data.worlds.new("W"); sc.world = w
    w.light_settings.distance = 0.35
    vl = sc.view_layers[0]
    for nm, t in (("alb", "COLOR"), ("rough", "VALUE"), ("metal", "VALUE"), ("emit", "VALUE"), ("plas", "VALUE"),
                  ("wood", "VALUE")):
        a = vl.aovs.add(); a.name = nm; a.type = t
    vl.use_pass_normal = True; vl.use_pass_ambient_occlusion = True; vl.use_pass_position = True
    cam = bpy.data.cameras.new("cam"); cam.type = "ORTHO"
    co = bpy.data.objects.new("cam", cam); sc.collection.objects.link(co); sc.camera = co
    co.rotation_euler = (0, 0, 0)
    ng = bpy.data.node_groups.new("comp", "CompositorNodeTree"); sc.compositing_node_group = ng
    rl = ng.nodes.new("CompositorNodeRLayers")
    fo = ng.nodes.new("CompositorNodeOutputFile")
    fo.format.media_type = "IMAGE"; fo.format.file_format = "OPEN_EXR"; fo.format.color_depth = "16"
    fo.format.exr_codec = "ZIP"
    for s in ("Normal", "Ambient Occlusion", "Position", "alb", "rough", "metal", "emit", "plas", "wood"):
        fo.file_output_items.new("RGBA", s)
        ng.links.new(rl.outputs[s], fo.inputs[s])
    return sc, co, fo


def _read_exr(path):
    im = bpy.data.images.load(path)
    a = np.array(im.pixels[:], dtype=np.float32).reshape(im.size[1], im.size[0], -1)[::-1]
    bpy.data.images.remove(im)
    return a


def render_module(sc, co, fo, name, builder, W, H, ppm=D_PX):
    # clear old geometry
    for ob in [o for o in bpy.data.objects if o.type == "MESH"]:
        me = ob.data
        bpy.data.objects.remove(ob)
        bpy.data.meshes.remove(me)
    mats = MATS()
    for k, dx in enumerate((-W, 0.0, W)):
        fb = FB(W, H, seed=_h(name))
        builder(fb)
        if k == 1:
            glass = list(fb.glass)
        ob = fb.to_object("%s_%d" % (name, k), mats)
        ob.location.x = dx
    # backstop (deep interior) behind everything
    fb = FB(W, H); fb.box(-W, 2 * W, -0.5, H + 0.5, -3.2, -3.0, "interior"); fb.to_object("back", mats)
    rx, ry = int(round(W * ppm)), int(round(H * ppm))
    sc.render.resolution_x, sc.render.resolution_y = rx, ry
    sc.render.resolution_percentage = 100
    co.data.ortho_scale = max(W, H)
    co.location = (W / 2, H / 2, 5.0)
    co.data.clip_start = 0.1; co.data.clip_end = 20
    od = os.path.join(PASSDIR, name)
    os.makedirs(od, exist_ok=True)
    fo.directory = od; fo.file_name = ""
    t = time.time()
    if not (os.environ.get("TEXLIB_REUSE") and len(os.listdir(od)) >= 9):   # TEXLIB_REUSE=1: re-run post only
        bpy.ops.render.render(write_still=False)
    print("  render %-32s %dx%d  %.1fs" % (name, rx, ry, time.time() - t), flush=True)
    P = {}
    for f in os.listdir(od):
        key = f.replace(".exr", "")
        P[key] = _read_exr(os.path.join(od, f))
    P["_glass"] = glass
    return P


# ============================================================================ post (weathering) + module maps
def post_module(name, P, W, H, floor, seed=0):
    rng = np.random.default_rng(_h(name))
    alb_lin = P["alb"][..., :3]
    nrm = P["Normal"][..., :3]
    ao = P["Ambient Occlusion"][..., 0]
    pos = P["Position"][..., :3]
    rough = P["rough"][..., 0]; metal = P["metal"][..., 0]; emit = P["emit"][..., 0]
    plas = P["plas"][..., 0]; wood = P["wood"][..., 0]
    h, w = ao.shape
    px = W / w
    alb = l2s(alb_lin)
    y = pos[..., 1]; z = pos[..., 2]
    # --- rain streaks on plaster below anything protruding (sills, beams, bars), and under the top beam
    occ = (plas < 0.5).astype(np.float32) * (z > -0.05)
    src = np.zeros_like(occ)
    src[1:] = np.clip(occ[:-1] - occ[1:], 0, 1)          # bottom edge of a non-plaster element (row below = plaster)
    cn = fnoise((1, w), lo=3, hi=w / 6, beta=1.0, seed=rng.integers(1000))[0]
    colmod = np.clip(0.5 + 0.6 * cn, 0, 1.4)
    streak = np.zeros_like(src)
    acc = np.zeros(w, np.float32)
    decay = math.exp(-px / 0.35)
    for r in range(h):
        acc = np.maximum(acc * decay, src[r] * colmod)
        streak[r] = acc
    streak = blur(streak, 1.2) * plas
    fine = fnoise((h, w), lo=2, hi=w / 4, beta=1.2, seed=rng.integers(1000), aniso=(1.0, 0.08))
    streak = np.clip(streak * (0.7 + 0.6 * fine) * 1.1, 0, 1)
    # plaster: low-frequency stains / old patch repairs, darker band at the bottom of each plaster panel
    stain = smooth(0.2, 1.8, fnoise((h, w), lo=1, hi=12, beta=2.2, seed=rng.integers(1000))) * plas
    patchy = smooth(1.2, 1.6, fnoise((h, w), lo=2, hi=10, beta=2.5, seed=rng.integers(1000))) * plas
    # --- top grime (under eave / hisashi), splash zone at the bottom (gf only), general mottling
    top = smooth(H - 0.6, H, y) * 0.5
    splash = (1 - smooth(0.0, 0.5, y)) * (1.0 if floor == "gf" else 0.0)
    splash *= 0.6 + 0.4 * fnoise((h, w), lo=4, hi=80, beta=1.2, seed=rng.integers(1000))
    dirt = np.clip(0.8 * streak + top * plas + 0.5 * splash + 0.35 * stain, 0, 1)
    grime_col = np.array([0.36, 0.33, 0.28])
    alb = lerp(alb, alb * grime_col / 0.55, (dirt * 0.55)[..., None])
    alb = lerp(alb, alb * np.array([1.06, 1.05, 1.02]), (patchy * 0.6)[..., None])
    # wood: lower boards silver/bleach, upper dark
    wbleach = (1 - smooth(0.2, 1.4, y)) * wood * 0.25 * (floor == "gf")
    alb = lerp(alb, np.array([0.48, 0.45, 0.40]), wbleach[..., None] * np.clip(0.5 + fine * 0.5, 0, 1)[..., None])
    rough = np.clip(rough + 0.05 * dirt, 0, 1)
    # deep interior: albedo darkened by depth (fakes indoor light falloff on a flat wall)
    depth = np.clip(-z - 0.05, 0, 3)
    alb = alb * (0.35 + 0.65 * np.exp(-depth / 0.35))[..., None] ** (1.0 - emit[..., None] * 0.5)
    ao = np.clip(ao, 0, 1)
    ao = ao * (0.5 + 0.5 * np.exp(-depth / 0.6))
    # glazing: camera saw through it; mark as glossy dielectric with a faint grey-blue film
    for (gx0, gx1, gy0, gy1, gz, gk) in P.get("_glass", []):
        c0, c1 = int(round(gx0 / W * w)), int(round(gx1 / W * w))
        r0, r1 = int(round((H - gy1) / H * h)), int(round((H - gy0) / H * h))
        sl = (slice(max(r0, 0), min(r1, h)), slice(max(c0, 0), min(c1, w)))
        behind = (z[sl] < gz)
        a_ = alb[sl]
        a_[behind] = a_[behind] * (0.8 if gk == "glass_shop" else 0.6) + np.array([0.025, 0.03, 0.035])
        alb[sl] = a_
        r_ = rough[sl]; r_[behind] = 0.05; rough[sl] = r_
        m_ = metal[sl]; m_[behind] = 0.0; metal[sl] = m_
        nn = nrm[sl]; nn[behind] = (0, 0, 1); nrm[sl] = nn
    n = renorm(np.where(np.linalg.norm(nrm, axis=-1, keepdims=True) < 0.1, np.array([0, 0, 1.0]), nrm))
    return dict(alb=np.clip(alb, 0, 1), nrm=n, ao=ao, rough=rough, metal=np.clip(metal, 0, 1),
                emit=np.clip(emit * (depth > 0.04), 0, 1), height=z)


# ============================================================================ atlas
def pack(mods, size=4096, pad=8):
    """Shelf packing, tallest first. Returns {name: (x, y, w, h)} in pixels (top-left origin), excl. padding."""
    order = sorted(mods.items(), key=lambda kv: (-kv[1]["alb"].shape[0], -kv[1]["alb"].shape[1]))
    x = y = 0
    shelf_h = 0
    out = {}
    for nm, m in order:
        h, w = m["alb"].shape[:2]
        if x + w + 2 * pad > size:
            x = 0; y += shelf_h; shelf_h = 0
        out[nm] = (x + pad, y + pad, w, h)
        x += w + 2 * pad
        shelf_h = max(shelf_h, h + 2 * pad)
    if y + shelf_h > size:
        raise RuntimeError("atlas overflow: %d > %d" % (y + shelf_h, size))
    return out


def build_atlas(mods, meta, size=4096, pad=8):
    rects = pack(mods, size, pad)
    A = {"alb": np.zeros((size, size, 3), np.float32) + 0.5, "nrm": np.zeros((size, size, 3), np.float32),
         "orm": np.zeros((size, size, 3), np.float32), "emit": np.zeros((size, size), np.float32)}
    A["nrm"][..., 2] = 1
    A["orm"][..., 0] = 1; A["orm"][..., 1] = 0.8
    for nm, (x, y, w, h) in rects.items():
        m = mods[nm]
        orm = np.stack([m["ao"], m["rough"], m["metal"]], -1)
        for key, img in (("alb", m["alb"]), ("nrm", m["nrm"]), ("orm", orm), ("emit", m["emit"])):
            # wrap padding in x (bays repeat), clamp in y
            pw = ((pad, pad), (pad, pad)) + (((0, 0),) if img.ndim == 3 else ())
            p = np.pad(img, ((0, 0), (pad, pad)) + (((0, 0),) if img.ndim == 3 else ()), mode="wrap")
            p = np.pad(p, ((pad, pad), (0, 0)) + (((0, 0),) if img.ndim == 3 else ()), mode="edge")
            A[key][y - pad:y + h + pad, x - pad:x + w + pad] = p
    descr = {"schema": "facade_atlas v1", "atlas_size_px": [size, size], "px_per_m": D_PX * size / 4096,
             "padding_px": pad, "uv_origin": "bottom-left (OpenGL/Blender UV); px_rect is top-left image pixels",
             "normal": "OpenGL tangent space (+Y up)", "orm": "R=AO G=roughness B=metalness",
             "files": {}, "modules": {}}
    for nm, (x, y, w, h) in sorted(rects.items()):
        mt = meta[nm]
        descr["modules"][nm] = {
            "uv_rect": [round(x / size, 6), round(1 - (y + h) / size, 6), round((x + w) / size, 6), round(1 - y / size, 6)],
            "px_rect": [x, y, w, h], "width_m": mt["W"], "height_m": mt["H"], "kind": mt["kind"], "floor": mt["floor"],
            "tags": mt["tags"], "has_emissive": mt["emissive"], "evidence": mt["note"]}
    return A, descr


def write_atlas(A, descr, name="facade_atlas"):
    sizes = {}
    for tgt, d, res, q in (("bl", TEX_BL, 4096, 92), ("web", TEX_WEB, 2048, 82)):
        f = A["alb"].shape[0] // res
        alb = down(A["alb"], f); nrm = renorm(down(A["nrm"], f)); orm = down(A["orm"], f); em = down(A["emit"], f * 2)
        dd = dict(descr)
        dd["atlas_size_px"] = [res, res]; dd["px_per_m"] = D_PX * res / 4096; dd["padding_px"] = descr["padding_px"] // f
        dd["modules"] = {k: dict(v, px_rect=[v["px_rect"][0] // f, v["px_rect"][1] // f, v["px_rect"][2] // f,
                                             v["px_rect"][3] // f]) for k, v in descr["modules"].items()}
        files = {"albedo": name + "_albedo.jpg", "normal": name + "_normal.jpg", "orm": name + "_orm.jpg",
                 "emit": name + "_emit.jpg"}
        sizes[(tgt, "a")] = save_img(os.path.join(d, files["albedo"]), alb, q)
        sizes[(tgt, "n")] = save_img(os.path.join(d, files["normal"]), nrm * 0.5 + 0.5, 95 if tgt == "bl" else q)
        sizes[(tgt, "o")] = save_img(os.path.join(d, files["orm"]), orm, q)
        sizes[(tgt, "e")] = save_img(os.path.join(d, files["emit"]), np.repeat(em[..., None], 3, -1), 85)
        dd["files"] = files
        dd["emit_resolution_px"] = [res // 2, res // 2]
        json.dump(dd, open(os.path.join(d, name + ".json"), "w"), indent=1, ensure_ascii=False)
    for k, v in sizes.items():
        print("  atlas %s %s %.0f KB" % (k[0], k[1], v / 1024))


def build_all(only=None, reuse=False):
    make_bases()
    sc, co, fo = setup_scene()
    mods, meta = {}, {}
    for (nm, builder, W, H, floor, kind, tags, emissive, note) in MODULES:
        cache = os.path.join(MODDIR, nm + ".npz")
        if (only and not any(o == nm or o in nm for o in only)) or (reuse and os.path.exists(cache)):
            if os.path.exists(cache):
                z = np.load(cache)
                mods[nm] = {k: z[k] for k in z.files}
            else:
                continue
        else:
            P = render_module(sc, co, fo, nm, builder, W, H)
            m = post_module(nm, P, W, H, floor)
            np.savez(cache, **m)
            mods[nm] = m
        meta[nm] = dict(W=W, H=H, floor=floor, kind=kind, tags=tags, emissive=emissive, note=note)
        Image.fromarray(to8(mods[nm]["alb"])).save(os.path.join(MODDIR, nm + "_alb.png"))
    A, descr = build_atlas(mods, meta)
    write_atlas(A, descr)
    return mods, descr


if __name__ == "__main__":
    args = sys.argv[1:]
    only = args[args.index("--only") + 1].split(",") if "--only" in args else None
    build_all(only, reuse="--reuse" in args)
