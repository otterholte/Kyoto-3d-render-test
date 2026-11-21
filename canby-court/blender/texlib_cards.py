"""PNW foliage card atlas (alpha cards): 4 x 4 cells, each a real-scale spray / leaf cluster / frond / twig set.

Cells (index: name, card size w x h metres, stem anchor at bottom-centre unless noted):
  0 fir_spray        Douglas-fir branch tip: pinnate shoots, 2-3 cm needles, lighter new growth
  1 cedar_spray      western redcedar flat fern-like spray of scale leaves (yellow-green)
  2 fir_spray_snow   = 0 with snow clumps on top
  3 cedar_spray_snow = 1 with snow
  4 maple_cluster    bigleaf maple: 3-5 palmate leaves 18-30 cm
  5 birch_cluster    birch / alder twig with ~25 ovate serrated leaves 5-8 cm
  6 cherry_cluster   ornamental cherry leaves 8-11 cm
  7 jmaple_cluster   red-leaf Japanese maple (palmate 7-lobed, 6 cm, deep red-purple)
  8 rhodo_cluster    rhododendron whorls of 12-15 cm leathery leaves
  9 laurel_cluster   English/Portuguese laurel 12-18 cm glossy leaves
 10 arborvitae_spray thuja occidentalis 'Smaragd' scale-leaf spray (bright green)
 11 fern_frond       western sword fern frond 0.9 m
 12 grass_clump      lawn-edge / ornamental grass tuft (vertical card, anchor bottom)
 13 bare_twigs       winter deciduous fine twig spray
 14 azalea_cluster   small-leaved shrub (azalea / boxwood / spirea) 2-4 cm leaves
 15 bare_twigs_snow  = 13 with snow on the upper edges
Normals: OpenGL tangent space, per-leaf tilt + midrib fold. Albedo RGBA (alpha = coverage, colour bled into
transparent texels). ORM: AO (depth order), roughness, metal 0.
"""
import json
import math
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from texcore import TEX_BL, TEX_WEB, blur, hexc, resize, save_img, to8, _lib_update, LIB_JSON_BL, LIB_JSON_WEB

CELL = 512
SS = 2
N = 4

CARDS = {
    0: ("fir_spray", (0.70, 0.90)), 1: ("cedar_spray", (0.60, 0.80)), 2: ("fir_spray_snow", (0.70, 0.90)),
    3: ("cedar_spray_snow", (0.60, 0.80)), 4: ("maple_cluster", (0.90, 0.90)), 5: ("birch_cluster", (0.60, 0.60)),
    6: ("cherry_cluster", (0.55, 0.55)), 7: ("jmaple_cluster", (0.45, 0.45)), 8: ("rhodo_cluster", (0.55, 0.55)),
    9: ("laurel_cluster", (0.60, 0.60)), 10: ("arborvitae_spray", (0.35, 0.50)), 11: ("fern_frond", (0.30, 0.90)),
    12: ("grass_clump", (0.30, 0.28)), 13: ("bare_twigs", (1.00, 1.00)), 14: ("azalea_cluster", (0.40, 0.40)),
    15: ("bare_twigs_snow", (1.00, 1.00)),
}


class Card:
    def __init__(self, size_m):
        self.wm, self.hm = size_m
        R = CELL * SS
        self.R = R
        self.sc = R / max(self.wm, self.hm)          # px per metre (uniform), card drawn centred horizontally
        self.ox = (R - self.wm * self.sc) / 2
        self.col = Image.new("RGB", (R, R), (0, 0, 0))
        self.alpha = Image.new("L", (R, R), 0)
        self.nrm = Image.new("RGB", (R, R), (128, 128, 255))
        self.ao = Image.new("L", (R, R), 255)
        self.rough = Image.new("L", (R, R), 190)
        self.d = [ImageDraw.Draw(im) for im in (self.col, self.alpha, self.nrm, self.ao, self.rough)]

    def P(self, x, y):
        """card metres (x from left, y up from bottom) -> pixel."""
        return (self.ox + x * self.sc, self.R - y * self.sc)

    def poly(self, pts, col, n=(0, 0), ao=1.0, rough=0.7):
        P = [self.P(*p) for p in pts]
        c = tuple(int(255 * min(1, max(0, v))) for v in col)
        nx, ny = n
        nz = math.sqrt(max(0.05, 1 - nx * nx - ny * ny))
        ncol = (int(128 + 127 * nx), int(128 + 127 * ny), int(128 + 127 * nz))
        self.d[0].polygon(P, fill=c)
        self.d[1].polygon(P, fill=255)
        self.d[2].polygon(P, fill=ncol)
        self.d[3].polygon(P, fill=int(255 * ao))
        self.d[4].polygon(P, fill=int(255 * rough))

    def line(self, pts, w_m, col, n=(0, 0), ao=1.0, rough=0.8):
        P = [self.P(*p) for p in pts]
        w = max(1, int(round(w_m * self.sc)))
        c = tuple(int(255 * min(1, max(0, v))) for v in col)
        nx, ny = n
        nz = math.sqrt(max(0.05, 1 - nx * nx - ny * ny))
        ncol = (int(128 + 127 * nx), int(128 + 127 * ny), int(128 + 127 * nz))
        for i, (im, f) in enumerate(((0, c), (1, 255), (2, ncol), (3, int(255 * ao)), (4, int(255 * rough)))):
            self.d[im].line(P, fill=f, width=w, joint="curve")

    def ellipse(self, cx, cy, rx, ry, col, ao=1.0, rough=0.8, n=(0, 0)):
        a, b = self.P(cx - rx, cy + ry), self.P(cx + rx, cy - ry)
        c = tuple(int(255 * min(1, max(0, v))) for v in col)
        nx, ny = n
        nz = math.sqrt(max(0.05, 1 - nx * nx - ny * ny))
        ncol = (int(128 + 127 * nx), int(128 + 127 * ny), int(128 + 127 * nz))
        self.d[0].ellipse([a, b], fill=c)
        self.d[1].ellipse([a, b], fill=255)
        self.d[2].ellipse([a, b], fill=ncol)
        self.d[3].ellipse([a, b], fill=int(255 * ao))
        self.d[4].ellipse([a, b], fill=int(255 * rough))

    def leaf(self, base, ang, length, outline, col, rng, fold=0.35, ao=1.0, rough=0.7, vein=True, width=1.0):
        """outline: list of (x, y) in a unit leaf frame (y 0..1 base->tip, x +-half width)."""
        ca, sa = math.cos(ang), math.sin(ang)
        tilt = rng.normal(0, 0.25, 2)
        pts = [(base[0] + (x * width * ca * 0 + 0) + length * (y * ca - x * width * sa),
                base[1] + length * (y * sa + x * width * ca)) for x, y in outline]
        # split into halves along midrib for the fold normal
        left = [p for (p, (x, y)) in zip(pts, outline) if x >= 0]
        right = [p for (p, (x, y)) in zip(pts, outline) if x <= 0]
        tip = (base[0] + length * ca, base[1] + length * sa)
        nl = (-sa * fold + tilt[0], ca * fold + tilt[1])
        nr = (sa * fold + tilt[0], -ca * fold + tilt[1])
        c1 = np.asarray(col) * rng.uniform(0.92, 1.05)
        if len(left) > 2:
            self.poly([base] + left + [tip], c1 * 1.04, nl, ao, rough)
        if len(right) > 2:
            self.poly([base] + right[::-1] + [tip], c1 * 0.94, nr, ao, rough)
        if vein:
            self.line([base, tip], length * 0.025, np.asarray(col) * 1.25 + 0.05, (tilt[0], tilt[1]), ao, rough)


def maple_outline(lobes=5, depth=0.55, serr=0.03):
    """Palmate outline in leaf frame: y along the midrib (0 base .. 1 tip)."""
    if lobes == 5:
        L = [(0.0, 1.0), (0.95, 0.9), (-0.95, 0.9), (1.9, 0.6), (-1.9, 0.6)]
        gw = 0.34
    else:
        L = [(0.0, 1.0), (0.6, 0.95), (-0.6, 0.95), (1.2, 0.85), (-1.2, 0.85), (1.85, 0.6), (-1.85, 0.6)]
        gw = 0.16
    pts = []
    for t in np.linspace(-math.pi * 0.92, math.pi * 0.92, 160):
        r = (1 - depth) * 0.5 + depth * max(l * math.exp(-((t - a) / gw) ** 2) for a, l in L)
        r *= 1 + serr * math.sin(t * 50)
        pts.append((r * math.sin(t) * 0.5, 0.35 + r * math.cos(t) * 0.62))
    pts.append((0.0, 0.25))
    return [(x, max(0.0, y)) for x, y in pts]


def ovate(width=0.42, serr=0.03, acum=0.25, n=60):
    pts = []
    for t in np.linspace(0, 2 * math.pi, n, endpoint=False):
        y = 0.5 - 0.5 * math.cos(t)
        w = width * abs(math.sin(t)) ** 0.8 * (1 + 0.2 * math.cos(t)) * (1 - acum * max(0, 2 * y - 1) ** 3)
        w *= 1 + serr * math.sin(t * 40)
        pts.append((w * (1 if t < math.pi else -1) * 0.5, y))
    return pts


def lance(width=0.18, n=40):
    pts = []
    for t in np.linspace(0, 2 * math.pi, n, endpoint=False):
        y = 0.5 - 0.5 * math.cos(t)
        w = width * abs(math.sin(t)) ** 0.7 * (1 - 0.3 * max(0, 2 * y - 1) ** 2)
        pts.append((w * (1 if t < math.pi else -1) * 0.5, y))
    return pts


def _curve(p0, ang, L, bend, n=8):
    pts = [p0]
    x, y = p0
    for i in range(n):
        a = ang + bend * (i / n)
        x += math.cos(a) * L / n
        y += math.sin(a) * L / n
        pts.append((x, y))
    return pts


# ----------------------------------------------------------------------------- conifers
def fir_spray(c, rng, snow=False):
    W, H = c.wm, c.hm
    main = _curve((W / 2, 0.0), math.pi / 2 + rng.normal(0, 0.05), H * 0.95, rng.normal(0, 0.15), 12)
    twig = hexc("#5a4632")
    needles = [hexc(h) for h in ("#2a4426", "#30502c", "#26402a", "#3a5a30")]
    tipc = hexc("#5f8240")
    shoots = []

    def shoot(pts, depth):
        shoots.append((pts, depth))
        c.line(pts, 0.006 if depth == 0 else 0.003, twig, ao=0.6)

    shoot(main, 0)
    mx = np.array(main)
    seg = np.linalg.norm(np.diff(mx, axis=0), axis=1)
    cum = np.concatenate([[0], np.cumsum(seg)])
    s = 0.06
    side = 1
    while s < cum[-1] - 0.04:
        p = np.array([np.interp(s, cum, mx[:, 0]), np.interp(s, cum, mx[:, 1])])
        k = min(len(mx) - 2, np.searchsorted(cum, s) - 1)
        d = mx[k + 1] - mx[k]
        base_a = math.atan2(d[1], d[0])
        frac = s / cum[-1]
        L = (0.26 * (1 - frac) + 0.05) * rng.uniform(0.8, 1.15)
        a = base_a + side * rng.uniform(0.75, 1.0)
        sp = _curve(tuple(p), a, L, -side * rng.uniform(0.1, 0.4), 6)
        shoot(sp, 1)
        if L > 0.12:
            sp2 = np.array(sp)
            for j in (2, 4):
                q = sp2[j]
                a2 = a + side * rng.uniform(-0.9, 0.9)
                shoot(_curve(tuple(q), a2 + (0.7 if rng.random() < 0.5 else -0.7), L * 0.35, 0.1, 4), 2)
        side = -side
        s += rng.uniform(0.035, 0.055)
    # needles
    for pts, depth in shoots:
        P = np.array(pts)
        seg = np.linalg.norm(np.diff(P, axis=0), axis=1)
        cum = np.concatenate([[0], np.cumsum(seg)])
        t = 0.0
        while t < cum[-1]:
            k = min(len(P) - 2, np.searchsorted(cum, t, side="right") - 1)
            d = P[k + 1] - P[k]
            a0 = math.atan2(d[1], d[0])
            q = (np.interp(t, cum, P[:, 0]), np.interp(t, cum, P[:, 1]))
            tipness = t / max(cum[-1], 1e-6)
            for sd in (1, -1):
                ln = rng.uniform(0.018, 0.03)
                aa = a0 + sd * rng.uniform(0.9, 1.4)
                e = (q[0] + math.cos(aa) * ln, q[1] + math.sin(aa) * ln)
                col = needles[rng.integers(len(needles))] * rng.uniform(0.85, 1.15)
                if tipness > 0.7 and depth > 0:
                    col = col * 0.5 + tipc * 0.5
                c.line([q, e], 0.0016, col, n=(math.cos(aa) * 0.35 * sd * 0, sd * 0.3), ao=0.75 + 0.25 * rng.random(),
                       rough=0.55)
            t += 0.0035
    if snow:
        _snow_on(c, shoots, rng, cover=0.35)


def cedar_spray(c, rng, snow=False, colors=("#4c6a26", "#58772d", "#425f22", "#66853a"), fine=1.0):
    W, H = c.wm, c.hm
    twig = hexc("#6a4a30")
    cols = [hexc(h) for h in colors]
    shoots = []

    def branch(p, ang, L, depth, side):
        pts = _curve(p, ang, L, side * 0.15, 6)
        shoots.append((pts, depth))
        P = np.array(pts)
        seg = np.linalg.norm(np.diff(P, axis=0), axis=1)
        cum = np.concatenate([[0], np.cumsum(seg)])
        w = (0.009 if depth == 0 else 0.007 if depth == 1 else 0.0055) * fine
        col = cols[rng.integers(len(cols))] * rng.uniform(0.9, 1.1)
        c.line(pts, w, col, n=(0, 0.2), ao=0.85, rough=0.6)
        # scale bumps
        for t in np.arange(0.0, cum[-1], w * 1.4):
            q = (np.interp(t, cum, P[:, 0]), np.interp(t, cum, P[:, 1]))
            c.ellipse(q[0], q[1], w * 0.7, w * 0.7, col * rng.uniform(0.9, 1.15), ao=0.9, rough=0.6,
                      n=(rng.normal(0, 0.3), rng.normal(0, 0.3)))
        if depth < 2:
            s = 0.03 if depth == 0 else 0.015
            sd = 1
            step = (0.04 if depth == 0 else 0.018) * fine
            while s < cum[-1] * 0.92:
                k = min(len(P) - 2, np.searchsorted(cum, s) - 1)
                d = P[k + 1] - P[k]
                a0 = math.atan2(d[1], d[0])
                q = (np.interp(s, cum, P[:, 0]), np.interp(s, cum, P[:, 1]))
                frac = s / cum[-1]
                L2 = L * (0.42 if depth == 0 else 0.4) * (1 - 0.7 * frac) * rng.uniform(0.8, 1.2)
                branch(q, a0 + sd * rng.uniform(0.6, 0.9), L2, depth + 1, sd)
                sd = -sd
                s += step

    branch((W / 2, 0.0), math.pi / 2 + rng.normal(0, 0.05), H * 0.95, 0, 1)
    if snow:
        _snow_on(c, shoots, rng, cover=0.35)


def _snow_on(c, shoots, rng, cover=0.5):
    white = np.array([0.93, 0.95, 0.98])
    for pts, depth in shoots:
        if rng.random() > cover:
            continue
        P = np.array(pts)
        for i in range(len(P) - 1):
            if rng.random() < 0.7:
                q = P[i] + (P[i + 1] - P[i]) * rng.random()
                r = rng.uniform(0.006, 0.016) * (1.4 if depth == 0 else 1.0)
                c.ellipse(q[0], q[1], r * rng.uniform(1.0, 1.8), r, white * rng.uniform(0.92, 1.0), ao=1.0, rough=0.6,
                          n=(rng.normal(0, 0.2), rng.normal(0, 0.2)))


# ----------------------------------------------------------------------------- broadleaf
def leaf_cluster(c, rng, n_leaves, length, outline, colors, twig_hex="#5a4a3a", fold=0.35, rough=0.7,
                 whorl=False, palmate=False, petiole=0.03):
    W, H = c.wm, c.hm
    cols = [hexc(h) for h in colors]
    twig = hexc(twig_hex)
    main = _curve((W / 2, 0.0), math.pi / 2 + rng.normal(0, 0.12), H * 0.62, rng.normal(0, 0.4), 8)
    c.line(main, 0.006, twig, ao=0.6)
    P = np.array(main)
    seg = np.linalg.norm(np.diff(P, axis=0), axis=1)
    cum = np.concatenate([[0], np.cumsum(seg)])
    leaves = []
    if whorl:
        tips = [P[-1]]
        for k in range(2):
            a = math.pi / 2 + rng.uniform(-1.0, 1.0)
            sp = _curve(tuple(P[len(P) // 2]), a, H * 0.3, 0.2, 4)
            c.line(sp, 0.005, twig, ao=0.6)
            tips.append(np.array(sp[-1]))
        for tp in tips:
            for j in range(rng.integers(6, 9)):
                a = 2 * math.pi * j / 8 + rng.normal(0, 0.2)
                leaves.append((tuple(tp), a, length * rng.uniform(0.8, 1.15)))
    else:
        for i in range(n_leaves):
            s = rng.uniform(0.08, 1.0) * cum[-1]
            k = min(len(P) - 2, np.searchsorted(cum, s) - 1)
            q = np.array([np.interp(s, cum, P[:, 0]), np.interp(s, cum, P[:, 1])])
            d = P[k + 1] - P[k]
            a0 = math.atan2(d[1], d[0])
            sd = 1 if i % 2 else -1
            a = a0 + sd * rng.uniform(0.5, 1.3)
            if palmate:
                a = a0 + sd * rng.uniform(0.2, 1.1)
            # petiole
            pl = petiole * rng.uniform(0.6, 1.4) * (3 if palmate else 1)
            e = (q[0] + math.cos(a) * pl, q[1] + math.sin(a) * pl)
            c.line([tuple(q), e], 0.0025, twig * 1.3, ao=0.7)
            leaves.append((e, a + rng.normal(0, 0.3), length * rng.uniform(0.75, 1.15)))
    order = rng.permutation(len(leaves))
    for j, i in enumerate(order):
        base, a, L = leaves[i]
        col = cols[rng.integers(len(cols))]
        depth = j / max(1, len(leaves) - 1)
        c.leaf(base, a, L, outline, col * (0.75 + 0.3 * depth), rng, fold=fold, ao=0.55 + 0.45 * depth, rough=rough)


def fern(c, rng):
    W, H = c.wm, c.hm
    rach = _curve((W / 2, 0.0), math.pi / 2, H * 0.97, -0.25, 16)
    col = hexc("#2c4a20")
    c.line(rach, 0.004, hexc("#4a5a2a"), ao=0.8)
    P = np.array(rach)
    seg = np.linalg.norm(np.diff(P, axis=0), axis=1)
    cum = np.concatenate([[0], np.cumsum(seg)])
    s = 0.08
    while s < cum[-1] - 0.01:
        k = min(len(P) - 2, np.searchsorted(cum, s) - 1)
        d = P[k + 1] - P[k]
        a0 = math.atan2(d[1], d[0])
        q = (np.interp(s, cum, P[:, 0]), np.interp(s, cum, P[:, 1]))
        frac = s / cum[-1]
        L = 0.08 * math.sin(math.pi * min(1, 0.15 + frac * 0.95)) + 0.012
        for sd in (1, -1):
            c.leaf(q, a0 + sd * 1.25, L, lance(0.32), col * rng.uniform(0.85, 1.15), rng, fold=0.25, rough=0.6)
        s += 0.018 + 0.01 * (1 - frac)


def grass(c, rng):
    W, H = c.wm, c.hm
    cols = [hexc(h) for h in ("#4d7a2c", "#5e8a33", "#3f6b26", "#6f9a3c", "#8a9a4a")]
    for i in range(70):
        a = math.pi / 2 + rng.normal(0, 0.35)
        L = H * rng.uniform(0.5, 0.98)
        pts = _curve((W / 2 + rng.normal(0, 0.02), 0.0), a, L, rng.normal(0, 0.5), 6)
        P = np.array(pts)
        w0 = 0.004
        poly = []
        for j, p in enumerate(P):
            w = w0 * (1 - j / len(P))
            poly.append((p[0] - w, p[1]))
        for j, p in enumerate(P[::-1]):
            w = w0 * (j / len(P))
            poly.append((p[0] + w, p[1]))
        c.poly(poly, cols[rng.integers(len(cols))] * rng.uniform(0.8, 1.1), n=(rng.normal(0, 0.3), 0),
               ao=0.6 + 0.4 * i / 70, rough=0.7)


def twigs(c, rng, snow=False):
    W, H = c.wm, c.hm
    col = hexc("#55493f")
    segs = []

    def br(p, a, L, w, depth):
        pts = _curve(p, a, L, rng.normal(0, 0.3), 5)
        c.line(pts, w, col * rng.uniform(0.85, 1.15), ao=0.8, rough=0.85)
        segs.append((pts, w))
        if depth < 5:
            P = np.array(pts)
            for k in range(rng.integers(2, 5)):
                j = rng.integers(1, len(P))
                br(tuple(P[j]), a + rng.choice([-1, 1]) * rng.uniform(0.3, 0.8), L * rng.uniform(0.45, 0.65),
                   max(0.0012, w * 0.62), depth + 1)

    br((W / 2, 0.0), math.pi / 2 + rng.normal(0, 0.1), H * 0.5, 0.012, 0)
    if snow:
        white = np.array([0.94, 0.96, 0.99])
        for pts, w in segs:
            if w < 0.002 or rng.random() < 0.3:
                continue
            P = np.array(pts) + np.array([0, w * 0.6])
            c.line([tuple(p) for p in P], w * 0.9, white, ao=1.0, rough=0.6, n=(0, 0.3))


# ----------------------------------------------------------------------------- atlas
def bleed(rgb, a, iters=6):
    """Push colour into transparent texels (no dark fringes when mip-mapped)."""
    out = rgb.copy()
    m = a[..., None]
    acc = out * m
    wsum = m.copy()
    for i in range(iters):
        s = 2 ** i
        acc = blur(acc, s)
        wsum = blur(wsum, s)
        fill = acc / np.maximum(wsum, 1e-4)
        out = np.where(m > 0.5, out, np.where(wsum > 1e-3, fill, out))
    return out


def build(res_bl=CELL * N, res_web=1024):
    R = CELL * N
    alb = np.zeros((R, R, 3), np.float32)
    alpha = np.zeros((R, R), np.float32)
    nrm = np.zeros((R, R, 3), np.float32)
    orm = np.zeros((R, R, 3), np.float32)
    meta = {"atlas": "foliage_atlas", "grid": [N, N], "cells": {}}
    for idx, (name, size) in CARDS.items():
        rng = np.random.default_rng(1000 + idx)
        c = Card(size)
        if name.startswith("fir_spray"):
            fir_spray(c, rng, snow=name.endswith("snow"))
        elif name.startswith("cedar_spray"):
            cedar_spray(c, np.random.default_rng(1001), snow=name.endswith("snow"))
        elif name == "maple_cluster":
            leaf_cluster(c, rng, 10, 0.25, maple_outline(5, 0.6), ["#4a6e2a", "#5a7e30", "#3f6224", "#66883a"],
                         palmate=True, petiole=0.04, fold=0.25)
        elif name == "birch_cluster":
            leaf_cluster(c, rng, 48, 0.07, ovate(0.6, 0.06), ["#56802e", "#6a9238", "#4a7228", "#7a9e40"],
                         petiole=0.012)
        elif name == "cherry_cluster":
            leaf_cluster(c, rng, 20, 0.095, ovate(0.45, 0.04, 0.4), ["#3d5e25", "#4a6c2a", "#35541f"],
                         petiole=0.015, rough=0.55)
        elif name == "jmaple_cluster":
            leaf_cluster(c, rng, 16, 0.07, maple_outline(7, 0.75), ["#5a1a1c", "#6e2222", "#4a1418", "#7a2a26"],
                         palmate=True, petiole=0.02)
        elif name == "rhodo_cluster":
            leaf_cluster(c, rng, 0, 0.14, lance(0.36), ["#25421c", "#2e4f22", "#203a18"], whorl=True, rough=0.4,
                         fold=0.45)
        elif name == "laurel_cluster":
            leaf_cluster(c, rng, 14, 0.15, ovate(0.42, 0.0, 0.2), ["#2a4f1e", "#33592a", "#244418"], rough=0.35,
                         petiole=0.01)
        elif name == "arborvitae_spray":
            cedar_spray(c, rng, colors=("#4a7a2c", "#5a8a34", "#3f6b26", "#6a9a3c"), fine=0.7)
        elif name == "fern_frond":
            fern(c, rng)
        elif name == "grass_clump":
            grass(c, rng)
        elif name.startswith("bare_twigs"):
            twigs(c, np.random.default_rng(1013), snow=name.endswith("snow"))
        elif name == "azalea_cluster":
            leaf_cluster(c, rng, 60, 0.03, ovate(0.5, 0.0, 0.1), ["#3a5d25", "#4a6e2c", "#2f4d1f", "#557a30"],
                         petiole=0.004)
        ci, cj = idx // N, idx % N
        sl = (slice(ci * CELL, (ci + 1) * CELL), slice(cj * CELL, (cj + 1) * CELL))
        a = np.asarray(c.alpha.resize((CELL, CELL), Image.LANCZOS), np.float32) / 255
        col = np.asarray(c.col.resize((CELL, CELL), Image.LANCZOS), np.float32) / 255
        col = col / np.maximum(a[..., None], 1e-3)     # un-premultiply (drawn on black)
        col = np.clip(col, 0, 1)
        n_ = np.asarray(c.nrm.resize((CELL, CELL), Image.LANCZOS), np.float32) / 255 * 2 - 1
        n_ = np.where(a[..., None] > 0.02, n_ / np.maximum(a[..., None], 1e-3), np.array([0, 0, 1.0]))
        n_[..., 2] = np.abs(n_[..., 2])
        n_ = n_ / np.maximum(1e-6, np.linalg.norm(n_, axis=-1, keepdims=True))
        ao = np.asarray(c.ao.resize((CELL, CELL), Image.LANCZOS), np.float32) / 255
        ao = np.where(a > 0.02, ao / np.maximum(a, 1e-3), 1)
        ro = np.asarray(c.rough.resize((CELL, CELL), Image.LANCZOS), np.float32) / 255
        ro = np.where(a > 0.02, ro / np.maximum(a, 1e-3), 0.7)
        alb[sl] = bleed(col, a)
        alpha[sl] = a
        nrm[sl] = n_
        orm[sl] = np.stack([np.clip(ao, 0, 1), np.clip(ro, 0, 1), np.zeros_like(ao)], -1)
        cx = (c.ox / c.R)
        meta["cells"][name] = {"index": idx, "row_from_top": ci, "col": cj, "size_m": list(size),
                               "uv_rect": [cj / N + cx / N, 1 - (ci + 1) / N, (cj + 1) / N - cx / N,
                                           1 - (ci + 1) / N + (size[1] / max(size)) / N],
                               "anchor": "bottom-centre"}
        print("   card", idx, name, flush=True)
    files = {}
    for tgt, res, d in (("bl", res_bl, TEX_BL), ("web", res_web, TEX_WEB)):
        rgba = np.concatenate([resize(alb, (res, res)), resize(alpha, (res, res))[..., None]], -1)
        Image.fromarray(to8(rgba), "RGBA").save(os.path.join(d, "foliage_atlas_albedo.png"), optimize=True)
        nn = resize(nrm, (res, res))
        nn = nn / np.maximum(1e-6, np.linalg.norm(nn, axis=-1, keepdims=True))
        save_img(os.path.join(d, "foliage_atlas_normal.jpg"), nn * 0.5 + 0.5, 90 if tgt == "bl" else 80)
        save_img(os.path.join(d, "foliage_atlas_orm.jpg"), resize(orm, (res, res)), 90 if tgt == "bl" else 80)
        json.dump(meta, open(os.path.join(d, "foliage_atlas.json"), "w"), indent=1)
        entry = {"kind": "atlas", "category": "foliage", "size_m": [1, 1], "tags": ["foliage", "alpha", "cards"],
                 "notes": "4x4 alpha card atlas, see foliage_atlas.json", "resolution": [res, res],
                 "files": {"albedo": "foliage_atlas_albedo.png", "normal": "foliage_atlas_normal.jpg",
                           "orm": "foliage_atlas_orm.jpg"}}
        _lib_update(LIB_JSON_BL if tgt == "bl" else LIB_JSON_WEB, "foliage_atlas", entry)
    return meta


if __name__ == "__main__":
    build()
