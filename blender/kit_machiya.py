"""Modular machiya kit (hidden collection "A_Asset_Library") + placement along Priority-2 street facades.

Kit local frame: X along the facade (0 .. width), wall plane at y = 0, OUTWARD = -Y, z = 0 at ground.
Each piece is its own collection (K_*) instanced by an empty (instance_type COLLECTION) carrying
custom props detail_class (observed|inferred|artistic), evidence_ref, kit_piece, building, street.

Proportions (metres) follow published machiya typology and the Commons street photos referenced in
docs/art_direction.md: bay (ken) 1.82, 1F hisashi eave 2.6-3.0, koshi lattice 2.3 tall with
~55 mm slat pitch, mushiko-mado ~1.4 x 0.6 on low (tsushi) second floors, inuyarai ~0.95 tall /
0.42 deep, noren ~1.0 long, chochin ~0.42 tall.
"""
import json
import math
import os

import bpy
import bmesh
import numpy as np
from mathutils import Matrix, Vector

from kit_common import DOCS, data, get_coll, gz, rng_for, evidence
from kit_materials import M

BAY = 1.82
LIB = "A_Asset_Library"


class PB:
    """Piece builder: one mesh per piece with material slots by key."""

    def __init__(self, name):
        self.name = name
        self.bm = bmesh.new()
        self.uv = self.bm.loops.layers.uv.new("UVMap")
        self.col = self.bm.loops.layers.color.new("plateau_rgb")
        self.mats = []

    def mi(self, key):
        if key not in self.mats:
            self.mats.append(key)
        return self.mats.index(key)

    def face(self, vs, key, uvs=None, col=(0.2, 0.21, 0.23, 1)):
        try:
            f = self.bm.faces.new([self.bm.verts.new(v) for v in vs])
        except ValueError:
            return None
        f.material_index = self.mi(key)
        for k, lp in enumerate(f.loops):
            if uvs:
                lp[self.uv].uv = uvs[k]
            lp[self.col] = col
        return f

    def box(self, x0, x1, y0, y1, z0, z1, key, **kw):
        p = lambda x, y, z: (x, y, z)  # noqa: E731
        X, Y, Z = (x0, x1), (y0, y1), (z0, z1)
        quads = [
            [p(X[0], Y[0], Z[0]), p(X[1], Y[0], Z[0]), p(X[1], Y[0], Z[1]), p(X[0], Y[0], Z[1])],   # -y (street)
            [p(X[1], Y[1], Z[0]), p(X[0], Y[1], Z[0]), p(X[0], Y[1], Z[1]), p(X[1], Y[1], Z[1])],
            [p(X[0], Y[1], Z[0]), p(X[0], Y[0], Z[0]), p(X[0], Y[0], Z[1]), p(X[0], Y[1], Z[1])],
            [p(X[1], Y[0], Z[0]), p(X[1], Y[1], Z[0]), p(X[1], Y[1], Z[1]), p(X[1], Y[0], Z[1])],
            [p(X[0], Y[0], Z[1]), p(X[1], Y[0], Z[1]), p(X[1], Y[1], Z[1]), p(X[0], Y[1], Z[1])],
            [p(X[0], Y[1], Z[0]), p(X[1], Y[1], Z[0]), p(X[1], Y[0], Z[0]), p(X[0], Y[0], Z[0])],
        ]
        for q in quads:
            self.face(q, key, uvs=[(0, 0), (1, 0), (1, 1), (0, 1)], **kw)

    def lathe(self, cx, cy, profile, key, n=12, **kw):
        """Surface of revolution around a vertical axis at (cx, cy); profile = [(r, z), ...] bottom->top."""
        rings = []
        for r, z in profile:
            rings.append([(cx + r * math.cos(2 * math.pi * k / n), cy + r * math.sin(2 * math.pi * k / n), z) for k in range(n)])
        for a, b in zip(rings[:-1], rings[1:]):
            for k in range(n):
                k2 = (k + 1) % n
                self.face([a[k], a[k2], b[k2], b[k]], key, **kw)
        if profile[-1][0] > 1e-3:
            self.face(list(rings[-1]), key, **kw)
        if profile[0][0] > 1e-3:
            self.face(list(reversed(rings[0])), key, **kw)

    def blob(self, cx, cy, cz, r, key, seed=0, sub=1, squash=1.0):
        rng = np.random.default_rng(seed)
        tmp = bmesh.new()
        bmesh.ops.create_icosphere(tmp, subdivisions=sub, radius=r)
        for v in tmp.verts:
            v.co *= 1.0 + rng.uniform(-0.18, 0.18)
            v.co.z *= squash
        for f in tmp.faces:
            self.face([(v.co.x + cx, v.co.y + cy, v.co.z + cz) for v in f.verts], key)
        tmp.free()

    def finish(self, coll):
        bmesh.ops.remove_doubles(self.bm, verts=self.bm.verts, dist=1e-4)
        me = bpy.data.meshes.new(self.name)
        self.bm.to_mesh(me); self.bm.free()
        for k in self.mats:
            me.materials.append(M(k))
        ob = bpy.data.objects.new(self.name, me)
        coll.objects.link(ob)
        return ob


# ------------------------------------------------------------------ pieces
def p_koshi(pb, W=BAY, lit=False):
    pb.box(0, W, -0.14, 0.0, -0.3, 0.38, "wood_dark")                      # base board (kekomi)
    for x0 in (0.0, W - 0.1):
        pb.box(x0, x0 + 0.1, -0.15, 0.0, -0.3, 2.5, "wood_dark")            # posts
    pb.box(0, W, -0.17, 0.0, 2.42, 2.6, "wood_dark")                        # lintel (kamoi)
    pb.box(0.1, W - 0.1, -0.12, -0.06, 0.38, 0.45, "wood_lattice")          # bottom rail
    pb.box(0.1, W - 0.1, -0.12, -0.06, 2.3, 2.42, "wood_lattice")           # top rail
    pb.box(0.1, W - 0.1, -0.115, -0.07, 1.86, 1.9, "wood_lattice")          # mid rail
    x = 0.13
    k = 0
    while x < W - 0.13:
        top = 2.3 if k % 4 == 0 else 1.86                                   # oya-ko goshi rhythm
        pb.box(x, x + 0.03, -0.11, -0.065, 0.45, top, "wood_lattice")
        if k % 4 != 0:
            pb.box(x + 0.012, x + 0.024, -0.105, -0.07, 1.9, 2.3, "wood_lattice")
        x += 0.056; k += 1
    pb.box(0.1, W - 0.1, -0.035, -0.02, 0.45, 2.3, "glow_soft" if lit else "plaster_dark")


def p_door(pb, W=BAY):
    pb.box(0, W, -0.2, 0.05, -0.3, 0.06, "stone_lantern")                   # threshold stone
    for x0 in (0.0, W - 0.1):
        pb.box(x0, x0 + 0.1, -0.15, 0.0, -0.3, 2.5, "wood_dark")
    pb.box(0, W, -0.17, 0.0, 2.2, 2.6, "wood_dark")
    # left sliding panel closed (lattice over paper), right panel half open onto a lit doma
    pb.box(0.1, 0.95, -0.09, -0.05, 0.06, 2.2, "wood_lattice")
    pb.box(0.15, 0.9, -0.1, -0.095, 0.12, 0.6, "wood_dark")
    pb.box(0.15, 0.9, -0.1, -0.095, 0.62, 2.12, "paper")
    for i in range(7):
        xx = 0.18 + i * 0.1
        pb.box(xx, xx + 0.02, -0.105, -0.1, 0.62, 2.12, "wood_lattice")
    pb.box(0.6, 1.45, -0.05, -0.01, 0.06, 2.2, "wood_lattice")
    pb.box(0.95, W - 0.1, -0.02, -0.01, 0.06, 2.2, "glow")                 # lit interior beyond


def p_noren(pb, W=BAY, length=1.0, key="noren_indigo"):
    pb.box(0.0, W, -0.24, -0.21, 2.2, 2.23, "bamboo")                       # pole
    n = 3
    gap = 0.03
    pw = (W - 0.16 - gap * (n - 1)) / n
    for i in range(n):
        x0 = 0.08 + i * (pw + gap)
        rows, cols = 6, 4
        verts = []
        for r in range(rows + 1):
            for c in range(cols + 1):
                u = c / cols; v = r / rows
                sway = 0.025 * math.sin(3.1 * u + i) * v
                verts.append((x0 + u * pw, -0.225 - sway - 0.02 * v * v, 2.2 - v * length))
        for r in range(rows):
            for c in range(cols):
                a = r * (cols + 1) + c
                q = [verts[a], verts[a + 1], verts[a + cols + 2], verts[a + cols + 1]]
                uu = [((x0 - 0.08 + (c + cc) / cols * pw) / (W - 0.16), 1 - (r + rr) / rows) for cc, rr in ((0, 0), (1, 0), (1, 1), (0, 1))]
                pb.face(q, key, uvs=uu)


def p_hisashi(pb):
    """1 m pent-roof module (scaled along x). Origin at wall/roof junction (z = 0 at the wall)."""
    d, drop, t = 0.95, 0.36, 0.07
    pb.face([(0, 0.0, 0.0), (0, -d, -drop), (1, -d, -drop), (1, 0.0, 0.0)], "roof")                     # top (up)
    pb.face([(0, 0.0, -t), (1, 0.0, -t), (1, -d, -drop - t), (0, -d, -drop - t)], "wood_weather")       # soffit
    pb.face([(0, -d, -drop), (0, -d, -drop - t), (1, -d, -drop - t), (1, -d, -drop)], "wood_weather")
    pb.box(0, 1, -d - 0.06, -d + 0.06, -drop - 0.1, -drop + 0.04, "roof")       # nokigawara roll
    pb.box(0, 1, -0.1, 0.0, -0.12, 0.08, "plaster")                               # flashing to wall


def p_bracket(pb):
    pb.box(-0.05, 0.05, -0.85, 0.0, -0.5, -0.37, "wood_dark")
    pb.box(-0.05, 0.05, -0.85, -0.75, -0.62, -0.37, "wood_dark")


def p_mushiko(pb, W=BAY):
    w, h = 1.4, 0.62
    x0 = (W - w) / 2
    pb.box(x0 - 0.08, x0 + w + 0.08, -0.08, 0.0, -0.08, h + 0.08, "plaster")      # raised plaster frame
    pb.box(x0, x0 + w, -0.03, -0.02, 0.0, h, "plaster_dark")
    nb = 9
    bw = 0.075
    gap = (w - nb * bw) / (nb + 1)
    for i in range(nb):
        xx = x0 + gap + i * (bw + gap)
        pb.box(xx, xx + bw, -0.075, -0.02, 0.0, h, "plaster")


def p_window2f(pb, W=BAY):
    w, h = 1.5, 0.95
    x0 = (W - w) / 2
    pb.box(x0 - 0.06, x0 + w + 0.06, -0.1, 0.0, -0.06, h + 0.06, "wood_dark")
    pb.box(x0, x0 + w, -0.04, -0.03, 0.0, h, "paper")
    for i in range(1, 16):
        xx = x0 + i * w / 16
        pb.box(xx - 0.01, xx + 0.01, -0.07, -0.04, 0.0, h, "wood_lattice")
    pb.box(x0 - 0.04, x0 + w + 0.04, -0.2, -0.17, 0.25, h + 0.05, "sudare")        # sudare blind
    pb.box(x0 - 0.06, x0 + w + 0.06, -0.24, -0.17, -0.12, -0.06, "wood_dark")     # rail


def p_inuyarai(pb, W=BAY):
    prof = [(0.0, 0.95), (-0.1, 0.9), (-0.22, 0.75), (-0.33, 0.5), (-0.4, 0.25), (-0.42, 0.06), (-0.42, -0.1)]
    x = 0.06
    while x < W - 0.05:
        for (y0, z0), (y1, z1) in zip(prof[:-1], prof[1:]):
            vs = [(x, y0, z0), (x + 0.03, y0, z0), (x + 0.03, y1, z1), (x, y1, z1)]
            pb.face(vs, "bamboo")
            pb.face([(x, y0 + 0.015, z0), (x, y0, z0), (x, y1, z1), (x, y1 + 0.015, z1)], "bamboo")
        x += 0.065
    for (y, z) in (prof[2], prof[4]):
        pb.box(0.02, W - 0.02, y - 0.02, y + 0.01, z - 0.015, z + 0.015, "bamboo")
    pb.box(0, 0.04, -0.44, 0.0, -0.1, 0.1, "wood_dark")
    pb.box(W - 0.04, W, -0.44, 0.0, -0.1, 0.1, "wood_dark")


def p_kanban(pb):
    """Hanging signboard perpendicular to the wall (tsuri-kanban) + wall plaque."""
    pb.box(-0.02, 0.02, -0.75, 0.0, 2.58, 2.63, "metal")
    pb.box(-0.025, 0.025, -0.68, -0.18, 1.75, 2.55, "kanban")
    pb.box(0.15, 0.47, -0.035, 0.0, 0.9, 2.1, "kanban")


def p_chochin(pb, key="chochin_red"):
    prof = [(0.0, -0.42), (0.07, -0.42), (0.12, -0.38), (0.16, -0.3), (0.175, -0.21), (0.16, -0.12), (0.12, -0.05), (0.07, -0.02), (0.0, -0.02)]
    pb.lathe(0, -0.55, [(r, z + 2.55) for r, z in prof], key, n=14)
    pb.lathe(0, -0.55, [(0.075, 2.12), (0.075, 2.16)], "metal", n=10)
    pb.lathe(0, -0.55, [(0.075, 2.52), (0.075, 2.56)], "metal", n=10)
    pb.box(-0.01, 0.01, -0.57, -0.53, 2.56, 2.75, "metal")
    pb.box(-0.015, 0.015, -0.6, 0.0, 2.74, 2.77, "metal")


def p_andon(pb):
    pb.box(-0.02, 0.02, -0.25, -0.21, 0.0, 0.6, "wood_dark")
    pb.box(-0.14, 0.14, -0.37, -0.09, 0.6, 1.15, "andon")
    pb.box(-0.16, 0.16, -0.39, -0.07, 1.15, 1.19, "wood_dark")
    pb.box(-0.16, 0.16, -0.39, -0.07, 0.56, 0.6, "wood_dark")


def p_pot(pb, seed=0, kind="shrub"):
    rng = np.random.default_rng(seed)
    r = rng.uniform(0.14, 0.22)
    h = rng.uniform(0.22, 0.38)
    pb.lathe(0, -0.3, [(r * 0.75, 0.0), (r, h * 0.85), (r * 1.08, h)], "ceramic" if seed % 2 else "ceramic_ochre", n=12)
    if kind == "shrub":
        for k in range(4):
            pb.blob(rng.uniform(-0.08, 0.08), -0.3 + rng.uniform(-0.08, 0.08), h + 0.12 + k * 0.07, r * rng.uniform(0.7, 1.0),
                    "leaf_shrub", seed=seed * 7 + k, sub=2)
    elif kind == "maple":
        pb.box(-0.015, 0.015, -0.315, -0.285, h, h + 0.5, "bark")
        for k in range(5):
            pb.blob(rng.uniform(-0.18, 0.18), -0.3 + rng.uniform(-0.15, 0.15), h + 0.45 + rng.uniform(0, 0.2), 0.13,
                    "leaf_maple", seed=seed * 11 + k, sub=2, squash=0.6)
    else:  # grass/fern
        for k in range(14):
            a = rng.uniform(0, 2 * math.pi); L = rng.uniform(0.25, 0.45)
            x1, y1 = math.cos(a) * L * 0.6, math.sin(a) * L * 0.6
            pb.face([(-0.02, -0.3, h), (0.02, -0.3, h), (x1 + 0.01, -0.3 + y1, h + L), (x1 - 0.01, -0.3 + y1, h + L)], "grass")


def p_shopfront(pb, W=BAY):
    for x0 in (0.0, W - 0.1):
        pb.box(x0, x0 + 0.1, -0.15, 0.0, -0.3, 2.5, "wood_dark")
    pb.box(0, W, -0.17, 0.0, 2.2, 2.6, "wood_dark")
    pb.box(0.1, W - 0.1, -0.03, -0.01, 0.0, 2.2, "glow")
    # shelves / goods silhouettes in front of the glow
    rng = np.random.default_rng(int(W * 100))
    pb.box(0.1, W - 0.1, -0.6, -0.03, 0.0, 0.75, "wood_weather")             # display table
    for i in range(6):
        x = 0.2 + i * (W - 0.4) / 6
        hh = rng.uniform(0.08, 0.2)
        pb.box(x, x + 0.18, -0.5, -0.2, 0.75, 0.75 + hh, "ceramic_ochre" if i % 2 else "ceramic")
    pb.box(0.1, W - 0.1, -0.12, -0.05, 1.45, 1.49, "wood_weather")
    pb.box(0.1, W - 0.1, -0.12, -0.05, 1.85, 1.89, "wood_weather")


def p_bench(pb):
    pb.box(0, 1.6, -0.75, -0.35, 0.42, 0.47, "red_felt")
    pb.box(0, 1.6, -0.76, -0.34, 0.36, 0.42, "wood_weather")
    for x in (0.08, 1.48):
        for y in (-0.72, -0.42):
            pb.box(x, x + 0.05, y, y + 0.05, 0.0, 0.36, "wood_weather")


def p_railing2f(pb, W=BAY):
    """Projecting wooden balcony railing (te-suri) in front of a 2F window (observed, Yasaka-dori east / Ninenzaka)."""
    pb.box(0.05, W - 0.05, -0.42, -0.36, 0.55, 0.62, "wood_dark")              # top rail
    pb.box(0.05, W - 0.05, -0.42, -0.36, -0.05, 0.02, "wood_dark")             # bottom rail
    for x in np.arange(0.12, W - 0.08, 0.11):
        pb.box(x, x + 0.025, -0.41, -0.38, 0.02, 0.55, "wood_dark")
    for x0 in (0.05, W - 0.11):
        pb.box(x0, x0 + 0.06, -0.42, 0.0, -0.08, -0.02, "wood_dark")


def p_post(pb):
    """1 m tall exposed timber post (scaled in z): 真壁 framing between plaster panels."""
    pb.box(-0.06, 0.06, -0.035, 0.0, 0.0, 1.0, "wood_dark")


def p_beam(pb):
    """1 m long exposed beam under the main eave (scaled in x)."""
    pb.box(0.0, 1.0, -0.04, 0.0, -0.16, 0.0, "wood_dark")


def p_lamppost(pb):
    """Old-style lamp post with a hexagonal glass lantern head (observed type; positions artistic)."""
    pb.lathe(0, -0.6, [(0.11, -0.2), (0.09, 0.15), (0.05, 0.25), (0.045, 2.6), (0.06, 2.65)], "metal", n=8)
    pb.lathe(0, -0.6, [(0.07, 2.65), (0.16, 2.72), (0.17, 3.05), (0.12, 3.12)], "andon", n=6)
    pb.lathe(0, -0.6, [(0.22, 3.12), (0.05, 3.3), (0.0, 3.36)], "metal", n=6)


def p_lantern_black(pb):
    """Black hanging lantern with white paper panels (observed, Yasaka-dori east)."""
    pb.box(-0.015, 0.015, -0.6, 0.0, 2.72, 2.75, "metal")
    pb.box(-0.01, 0.01, -0.56, -0.52, 2.5, 2.72, "metal")
    pb.box(-0.15, 0.15, -0.69, -0.39, 2.45, 2.5, "metal")
    pb.box(-0.13, 0.13, -0.67, -0.41, 2.05, 2.45, "andon")
    for dx in (-0.14, 0.12):
        for dy in (-0.68, -0.42):
            pb.box(dx, dx + 0.02, dy, dy + 0.02, 2.0, 2.47, "metal")
    pb.box(-0.15, 0.15, -0.69, -0.39, 1.98, 2.05, "metal")


PIECES = {
    "K_Koshi": lambda pb: p_koshi(pb),
    "K_Koshi_Lit": lambda pb: p_koshi(pb, lit=True),
    "K_Door": lambda pb: p_door(pb),
    "K_Noren_Indigo": lambda pb: p_noren(pb, key="noren_indigo"),
    "K_Noren_Brown": lambda pb: p_noren(pb, key="noren_brown"),
    "K_Noren_Cream": lambda pb: p_noren(pb, key="noren_cream"),
    "K_Noren_Persimmon": lambda pb: p_noren(pb, key="noren_persimmon"),
    "K_Hisashi": p_hisashi,
    "K_Bracket": p_bracket,
    "K_Mushiko": lambda pb: p_mushiko(pb),
    "K_Window2F": lambda pb: p_window2f(pb),
    "K_Inuyarai": lambda pb: p_inuyarai(pb),
    "K_Kanban": p_kanban,
    "K_Chochin_Red": lambda pb: p_chochin(pb, "chochin_red"),
    "K_Chochin_White": lambda pb: p_chochin(pb, "chochin_white"),
    "K_Andon": p_andon,
    "K_Pot_A": lambda pb: p_pot(pb, 1, "shrub"),
    "K_Pot_B": lambda pb: p_pot(pb, 2, "maple"),
    "K_Pot_C": lambda pb: p_pot(pb, 3, "grass"),
    "K_ShopFront": lambda pb: p_shopfront(pb),
    "K_Bench": p_bench,
    "K_Railing2F": lambda pb: p_railing2f(pb),
    "K_Post": p_post,
    "K_Beam": p_beam,
    "K_LampPost": p_lamppost,
    "K_Lantern_Black": p_lantern_black,
}


def m_kanban():
    """Weathered signboard with abstract brushed calligraphy (no legible invented text)."""
    from kit_materials import new_mat, node, sep, comb, math as mth, mrange, mix, principled, rgb, brush, paint, PAL
    m, nt, out = new_mat("ART_Kanban")
    P = node(nt, "ShaderNodeTexCoord").outputs["Object"]
    x, y, z = sep(nt, P)
    nz = node(nt, "ShaderNodeTexNoise", {"Vector": comb(nt, mth(nt, "MULTIPLY", x, 14.0), mth(nt, "MULTIPLY", y, 14.0), mth(nt, "MULTIPLY", z, 5.0)),
                                         "Scale": 1.0, "Detail": 2.0}).outputs["Factor"]
    ink = mrange(nt, nz, 0.58, 0.63)
    f1, f2 = brush(nt, P, 6.0, (1, 1, 3))
    base = paint(nt, rgb((0.20, 0.13, 0.07)), f1, f2, 0.2)
    base = mix(nt, ink, base, (0.015, 0.012, 0.01))
    principled(nt, out, base, 0.6, 0.3)
    return m


def build_library():
    lib = get_coll(LIB)
    import kit_materials as km
    if "kanban" not in km._LIB:
        km._LIB["kanban"] = m_kanban()
    out = {}
    for name, fn in PIECES.items():
        c = bpy.data.collections.get(name)
        if c is None:
            c = bpy.data.collections.new(name)
            lib.children.link(c)
            pb = PB(name)
            fn(pb)
            pb.finish(c)
        out[name] = c
    from kit_common import exclude_coll
    exclude_coll(LIB, True)
    lib.hide_render = False
    return out


# ------------------------------------------------------------------ evidence + POIs
def _commons_near(x, y, r=35.0):
    p = os.path.join(DOCS, "references", "commons_geotagged.json")
    key = "_commons"
    if key not in _commons_near.__dict__:
        try:
            _commons_near.__dict__[key] = [c for c in json.load(open(p)) if c.get("local_xy_m")]
        except Exception:
            _commons_near.__dict__[key] = []
    best = []
    for c in _commons_near.__dict__[key]:
        cx, cy = c["local_xy_m"]
        d = math.hypot(cx - x, cy - y)
        if d < r:
            best.append((d, c["title"].replace("File:", "")))
    best.sort()
    return [t for _, t in best[:2]]


KEYWORDS = {
    "K_Koshi": ["sen-koshi", "koshi", "格子"], "K_Koshi_Lit": ["sen-koshi", "koshi", "格子"],
    "K_Door": ["sliding door"], "K_Hisashi": ["hisashi"], "K_Bracket": ["hisashi"],
    "K_Mushiko": ["mushiko", "虫籠"], "K_Window2F": ["lattice window", "sudare"], "K_Railing2F": ["railing"],
    "K_Inuyarai": ["inuyarai"], "K_Kanban": ["signboard", "shop signs", "signs"], "K_Chochin_Red": ["chochin", "red paper"],
    "K_Chochin_White": ["hanging lantern", "white panels", "lantern"], "K_ShopFront": ["shopfront", "shop fronts", "open shop"],
    "K_Noren_Indigo": ["noren"], "K_Noren_Brown": ["noren"], "K_Noren_Cream": ["noren"], "K_Noren_Persimmon": ["noren"],
    "K_Pot_A": ["potted"], "K_Pot_B": ["potted"], "K_Pot_C": ["potted"], "K_Post": ["exposed-timber", "posts", "真壁"],
    "K_LampPost": ["lamp post"], "K_Lantern_Black": ["black hanging lantern", "hanging lanterns"],
}
RANK = {"observed": 3, "documented": 2, "measured": 1, "inferred": 0}


def segment_id(street, osm_way):
    if street == "Yasaka-dori":
        return "yasaka_dori_west" if int(osm_way) == 24516359 else "yasaka_dori_east"
    return {"Ninenzaka": "ninenzaka", "Sannenzaka": "sannenzaka", "Ichinenzaka": "ichinenzaka"}.get(street, street.lower())


def _evidence_for(street, piece, osm_way=0):
    """(detail_class, evidence_ref, confidence) from docs/evidence/building_evidence.json street_segments.

    observed -> detail_class "observed"; documented (district design standard) -> "inferred" with the documented
    source cited (confidence kept in the evidence_confidence prop); nothing found -> "inferred"."""
    ev = evidence()
    seg_id = segment_id(street, osm_way)
    segs = {sg.get("id"): sg for sg in ev.get("street_segments", [])} if isinstance(ev, dict) else {}
    kws = KEYWORDS.get(piece, [])
    best = None
    for sid in ([seg_id, "ninenzaka"] if seg_id == "ichinenzaka" else [seg_id]):
        for it in (segs.get(sid) or {}).get("items", []):
            txt = (it.get("attribute", "") + " " + str(it.get("value", ""))).lower()
            if any(k.lower() in txt for k in kws):
                conf = it.get("confidence", "inferred")
                if sid != seg_id:            # Ichinenzaka facades inferred from Ninenzaka (evidence note)
                    conf = "inferred"
                if best is None or RANK.get(conf, 0) > RANK.get(best[0], 0):
                    src = (it.get("photos") or [it.get("source", "")])[0]
                    best = (conf, "docs/evidence/building_evidence.json#%s/%s (%s: %s)" % (sid, it.get("attribute"), conf, src))
    if best is None:
        return "inferred", "", "inferred"
    return ("observed" if best[0] == "observed" else "inferred"), best[1], best[0]


def _pois():
    out = []
    for p in data("features")["pois"]:
        t = p["tags"]
        kind = None
        if t.get("amenity") in ("restaurant", "cafe", "fast_food", "bar"):
            kind = "food"
        elif "shop" in t or "craft" in t:
            kind = "shop"
        if kind:
            out.append((p["x"], p["y"], kind, p["osm_id"], t.get("name", "")))
    return out


# ------------------------------------------------------------------ placement
def place(facades, lib, log=print):
    root = get_coll("60_Machiya_Kit")
    pois = _pois()
    placed = []
    by_bld = {}
    for s in facades:
        by_bld.setdefault(s["obj"], []).append(s)
    from kit_common import p2_lines
    lines = p2_lines()
    for bname, segs in by_bld.items():
        for s in segs:
            a, b = np.array(s["a"]), np.array(s["b"])
            L = float(np.linalg.norm(b - a))
            if L < 1.3 or s["src"].startswith("party"):
                continue
            u = (b - a) / L
            out = np.array([u[1], -u[0]])
            mid = (a + b) / 2
            # which P2 street does this wall face?
            from shapely.geometry import Point
            best = None
            for key, w, ls, width, hw in lines:
                d = ls.distance(Point(*mid))
                if d > width / 2 + 5.0:
                    continue
                near = np.array(ls.interpolate(ls.project(Point(*mid))).coords[0])
                v = near - mid
                if np.linalg.norm(v) < 1e-6 or np.dot(v / np.linalg.norm(v), out) < 0.6:
                    continue
                if best is None or d < best[0]:
                    best = (d, key, w)
            if best is None:
                continue
            s["street"] = best[1]; s["street_osm"] = best[2]
            placed += _dress(s, a, b, u, L, lib, root, pois)
    log("kit placements", len(placed))
    return placed


def _inst(lib, name, coll, loc, rotz, sx=1.0, props=None):
    e = bpy.data.objects.new("%s.%s" % (name, props.get("building", "")[2:10] if props else ""), None)
    e.instance_type = "COLLECTION"
    e.instance_collection = lib[name]
    e.location = loc
    e.rotation_euler = (0, 0, rotz)
    e.scale = (sx, 1, 1)
    e.empty_display_size = 0.3
    coll.objects.link(e)
    for k, v in (props or {}).items():
        e[k] = v
    e["kit_piece"] = name
    return e


def _dress(s, a, b, u, L, lib, root, pois):
    coll = get_coll("60_Kit_%s" % s["street"], root)
    rng = rng_for(s["obj"], s["i"])
    rot = math.atan2(u[1], u[0])
    nb = max(1, int(round(L / BAY)))
    bw = L / nb
    g = gz(np.array([a[0], b[0]]), np.array([a[1], b[1]]))
    eave_h = s["top_min"] - s["ground_min"]
    storeys = s["storeys"] or (2 if eave_h > 4.3 else 1)
    modern = (storeys >= 3) or (s["height"] or 0) > 11.5
    if eave_h < 2.75:
        return []
    mid = (a + b) / 2
    near_poi = [p for p in pois if math.hypot(p[0] - mid[0], p[1] - mid[1]) < max(6.0, L / 2 + 2)]
    shop = bool(near_poi) or s["usage"] in ("402", "404", "413", "414")
    food = any(p[2] == "food" for p in near_poi)
    commons = _commons_near(mid[0], mid[1])
    base = dict(building=s["obj"], plateau_id=s["plateau_id"], street=s["street"], street_osm=str(s["street_osm"]))
    poi_ref = ("osm:node/%s %s" % (near_poi[0][3], near_poi[0][4])).strip() if near_poi else ""
    use_ref = "plateau:usage=%s" % s["usage"] if s["usage"] else ""

    def props(piece, cls=None, extra=""):
        c, ref, conf = _evidence_for(s["street"], piece, s["street_osm"])
        refs = [r for r in (ref, extra, ("commons-near:" + " | ".join(commons)) if commons else "",
                            "docs/art_direction.md#machiya-kit") if r]
        d = dict(base)
        d["detail_class"] = cls or c
        d["evidence_confidence"] = "artistic" if cls == "artistic" else conf
        d["evidence_ref"] = "; ".join(refs)
        return d

    out = []

    def P(t, z):
        p = a + u * t
        return (float(p[0]), float(p[1]), float(z))

    bay_ground = []
    for k in range(nb):
        t0, t1 = k * bw, (k + 1) * bw
        zz = gz(np.array([a[0] + u[0] * t0, a[0] + u[0] * t1]), np.array([a[1] + u[1] * t0, a[1] + u[1] * t1]))
        bay_ground.append(float(np.min(zz)))
    if modern:
        if shop:
            for k in range(nb):
                if eave_h > 3.0 and rng.random() < 0.7:
                    out.append(_inst(lib, "K_ShopFront", coll, P(k * bw, bay_ground[k]), rot, bw / BAY,
                                     props("K_ShopFront", extra=poi_ref or use_ref)))
        return out
    door = 0 if nb == 1 else int(rng.integers(0, nb))
    # 1F bays
    for k in range(nb):
        z0 = bay_ground[k]
        if k == door:
            out.append(_inst(lib, "K_Door", coll, P(k * bw, z0), rot, bw / BAY, props("K_Door", extra=use_ref)))
            if shop or rng.random() < 0.35:
                nk = ["K_Noren_Indigo", "K_Noren_Brown", "K_Noren_Cream", "K_Noren_Persimmon"][int(rng.integers(0, 4))]
                out.append(_inst(lib, nk, coll, P(k * bw, z0), rot, bw / BAY, props(nk, extra=poi_ref or use_ref)))
            if shop:
                ck = "K_Chochin_Red" if food else ("K_Lantern_Black" if rng.random() < 0.6 else "K_Chochin_White")
                out.append(_inst(lib, ck, coll, P(k * bw + 0.15, z0), rot, 1.0, props(ck, extra=poi_ref or use_ref)))
                if rng.random() < 0.35:
                    out.append(_inst(lib, "K_Andon", coll, P(k * bw + bw + 0.05, z0), rot, 1.0, props("K_Andon", cls="artistic")))
            if rng.random() < 0.8:
                pk = ["K_Pot_A", "K_Pot_B", "K_Pot_C"][int(rng.integers(0, 3))]
                tt = k * bw - 0.35 if k > 0 else k * bw + bw + 0.3
                out.append(_inst(lib, pk, coll, P(min(max(tt, 0.2), L - 0.2), gz(*P(tt, 0)[:2])), rot + rng.uniform(-0.3, 0.3), 1.0,
                                 props(pk, cls="artistic")))
        elif shop and rng.random() < 0.7:
            out.append(_inst(lib, "K_ShopFront", coll, P(k * bw, z0), rot, bw / BAY, props("K_ShopFront", extra=poi_ref or use_ref)))
            if rng.random() < 0.5:
                out.append(_inst(lib, "K_Noren_Cream" if rng.random() < 0.5 else "K_Noren_Indigo", coll, P(k * bw, z0), rot, bw / BAY,
                                 props("K_Noren_Cream", extra=poi_ref or use_ref)))
        else:
            lit = rng.random() < 0.45
            out.append(_inst(lib, "K_Koshi_Lit" if lit else "K_Koshi", coll, P(k * bw, z0), rot, bw / BAY, props("K_Koshi", extra=use_ref)))
            if not shop and rng.random() < 0.12:
                out.append(_inst(lib, "K_Inuyarai", coll, P(k * bw, z0), rot, bw / BAY, props("K_Inuyarai", extra=use_ref)))
            elif rng.random() < 0.25:
                pk = ["K_Pot_A", "K_Pot_C"][int(rng.integers(0, 2))]
                tt = k * bw + rng.uniform(0.3, bw - 0.3)
                out.append(_inst(lib, pk, coll, P(tt, gz(*P(tt, 0)[:2])), rot, 1.0, props(pk, cls="artistic")))
    if shop and nb >= 2 and rng.random() < 0.7:
        kk = (door + 1) % nb
        out.append(_inst(lib, "K_Kanban", coll, P(kk * bw + 0.05, bay_ground[kk]), rot, 1.0, props("K_Kanban", extra=poi_ref or use_ref)))
    # hisashi + 2F
    zmax_bay = max(bay_ground)
    if storeys >= 2 and eave_h > 4.1:
        zh = zmax_bay + 2.98
        if zh + 0.15 < s["top_min"] - 0.9:
            out.append(_inst(lib, "K_Hisashi", coll, P(0, zh), rot, L, props("K_Hisashi", extra=use_ref)))
            for k in range(nb + 1):
                out.append(_inst(lib, "K_Bracket", coll, P(min(max(k * bw, 0.06), L - 0.06), zh), rot, 1.0, props("K_Hisashi")))
            z2 = zh + 0.45
            room = s["top_min"] - 0.12 - z2
            low = eave_h < 6.0
            for k in range(nb + 1):                                   # exposed posts (shinkabe)
                if room > 0.4:
                    out.append(_inst(lib, "K_Post", coll, P(min(max(k * bw, 0.06), L - 0.06), zh + 0.1), rot, 1.0,
                                     props("K_Post", extra=use_ref)))
                    out[-1].scale = (1, 1, s["top_min"] - zh - 0.1)
            if room > 0.4:
                out.append(_inst(lib, "K_Beam", coll, P(0, s["top_min"] - 0.02), rot, L, props("K_Post", extra=use_ref)))
            for k in range(nb):
                r = rng.random()
                if low and room > 0.7 and r < 0.3:
                    out.append(_inst(lib, "K_Mushiko", coll, P(k * bw, z2 + min(0.15, room - 0.7)), rot, bw / BAY,
                                     props("K_Mushiko", extra=use_ref + " storeys=%s eave %.1f m" % (storeys, eave_h))))
                elif room > 1.0 and r < 0.85:
                    zw = z2 + min(0.25, room - 1.0)
                    out.append(_inst(lib, "K_Window2F", coll, P(k * bw, zw), rot, bw / BAY,
                                     props("K_Window2F", extra=use_ref + " storeys=%s" % storeys)))
                    if rng.random() < 0.3:
                        out.append(_inst(lib, "K_Railing2F", coll, P(k * bw, zw), rot, bw / BAY, props("K_Railing2F", extra=use_ref)))
    # old-style lamp post in front of roughly every third street-facing facade (type observed, position artistic)
    if rng.random() < 0.3 and L > 3.0:
        tt = rng.uniform(0.6, L - 0.6)
        out.append(_inst(lib, "K_LampPost", coll, P(tt, gz(*P(tt, 0)[:2]) - 0.05), rot, 1.0,
                         props("K_LampPost", cls="artistic")))
        out[-1]["evidence_ref"] = "type observed (building_evidence.json street_furniture: old-style lamp posts); position artistic"
    return out
