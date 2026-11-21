"""Canby Ct houses: measured footprints -> walls with real openings (recessed windows/doors), wing roofs
(hip / gable / shed / dormer / porch) with overhangs, fascia, soffits, gutters, downspouts, ridge caps,
chimneys, skylights, PV, vents, decks, stoops, porch lights, house numbers. Appearance from data/facades.json.

Heights are INFERRED (see house_specs.py); footprints measured (City GIS); roof forms observed (orthos).
"""
import math

import bpy
import numpy as np
from shapely.geometry import Point, Polygon, LineString
from shapely import contains_xy

import cc_common as C
import materials as MAT
from house_specs import SPECS, EAVE

OVER = 0.5          # eave overhang (m)
RAKE = 0.32         # gable rake overhang
SLAB = 0.22         # roof slab thickness at the fascia
STOREY = 2.75


# ============================================================================ wings
class Wing:
    def __init__(self, spec, house_c, frame_deg, pitch12, floor_z, idx, num):
        self.idx = idx
        self.num = num
        self.kind = spec.get("kind", "main")
        self.roof = spec["roof"]
        self.ridge = spec.get("ridge", "u")
        self.high = spec.get("high", "v1")
        self.st = spec.get("st", 2)
        self.p = spec.get("pitch", pitch12) / 12.0
        if "world" in spec:
            cx, cy, a, L, W = spec["world"]
            self.c = np.array([cx, cy], float)
            self.a = math.radians(a)
            self.L, self.W = L, W
        else:
            a = math.radians(frame_deg)
            U = np.array([math.cos(a), math.sin(a)])
            V = np.array([-math.sin(a), math.cos(a)])
            u0, u1 = spec["u"]
            v0, v1 = spec["v"]
            self.c = np.asarray(house_c) + U * (u0 + u1) / 2 + V * (v0 + v1) / 2
            self.a = a
            self.L, self.W = u1 - u0, v1 - v0
        self.U = np.array([math.cos(self.a), math.sin(self.a)])
        self.V = np.array([-math.sin(self.a), math.cos(self.a)])
        self.hl, self.hw = self.L / 2, self.W / 2
        self.floor = floor_z + spec.get("dz", 0.0)
        self.eave = self.floor + spec.get("eave", EAVE[self.st]) + (0.0 if self.kind != "porch" else -0.25)
        self.dormer_main = None

    def local(self, x, y):
        d = np.stack([np.asarray(x) - self.c[0], np.asarray(y) - self.c[1]], -1)
        return d @ self.U, d @ self.V

    def world(self, s, t):
        return self.c + self.U * s + self.V * t

    def contains(self, x, y, grow=0.0):
        s, t = self.local(x, y)
        return (np.abs(s) <= self.hl + grow) & (np.abs(t) <= self.hw + grow)

    def depth(self, x, y):
        s, t = self.local(x, y)
        return np.minimum(self.hl - np.abs(s), self.hw - np.abs(t))

    def ext(self):
        """expanded half sizes (overhang) along u and v."""
        if self.roof == "hip":
            return self.hl + OVER, self.hw + OVER
        if self.roof == "gable":
            return (self.hl + RAKE, self.hw + OVER) if self.ridge == "u" else (self.hl + OVER, self.hw + RAKE)
        if self.roof == "shed":
            eu = self.hl + (OVER if self.high in ("v0", "v1") else 0)
            ev = self.hw + (OVER if self.high in ("u0", "u1") else 0)
            if self.high in ("v0", "v1"):
                ev = self.hw + OVER
            else:
                eu = self.hl + OVER
            return eu, ev
        return self.hl + OVER, self.hw + OVER

    def roof_z(self, x, y):
        """Top-surface height of this wing's roof (incl. overhang zone); -inf outside."""
        s, t = self.local(x, y)
        HU, HV = self.ext()
        inside = (np.abs(s) <= HU + 1e-6) & (np.abs(t) <= HV + 1e-6)
        if self.roof == "hip":
            d = np.minimum(self.hl - np.abs(s), self.hw - np.abs(t))
        elif self.roof == "gable":
            d = (self.hw - np.abs(t)) if self.ridge == "u" else (self.hl - np.abs(s))
        elif self.roof == "shed":
            d = {"v1": t + self.hw, "v0": self.hw - t, "u1": s + self.hl, "u0": self.hl - s}[self.high]
            if self.high in ("v1", "v0"):
                inside &= (t <= self.hw + 1e-6) if self.high == "v1" else (t >= -self.hw - 1e-6)
            else:
                inside &= (s <= self.hl + 1e-6) if self.high == "u1" else (s >= -self.hl - 1e-6)
        else:
            d = 0 * s
        z = self.eave + d * self.p
        return np.where(inside, z, -np.inf)

    def ridge_z(self):
        if self.roof == "hip":
            return self.eave + min(self.hl, self.hw) * self.p
        if self.roof == "gable":
            return self.eave + (self.hw if self.ridge == "u" else self.hl) * self.p
        if self.roof == "shed":
            return self.eave + (2 * self.hw if self.high in ("v0", "v1") else 2 * self.hl) * self.p
        return self.eave

    def P3(self, s, t, z):
        w = self.world(s, t)
        return (float(w[0]), float(w[1]), float(z))

    # --------------------------------------------------------------- roof surface polygons (s,t,z)
    def top_faces(self, lift=0.0, grow=0.0):
        HU, HV = self.ext()
        HU += grow
        HV += grow
        p = self.p
        z0u = self.eave - (HU - self.hl) * p + lift      # z at the outer edge across u
        z0v = self.eave - (HV - self.hw) * p + lift
        faces, loop, eaves, caps = [], [], [], []
        if self.roof == "hip":
            z0 = self.eave - OVER * p - grow * p + lift
            zr = self.eave + min(self.hl, self.hw) * p + lift
            A, B, Cc, D = (-HU, -HV, z0), (HU, -HV, z0), (HU, HV, z0), (-HU, HV, z0)
            if self.hl >= self.hw:
                r = self.hl - self.hw
                R1, R2 = (-r, 0, zr), (r, 0, zr)
                faces = [[A, B, R2, R1], [B, Cc, R2], [Cc, D, R1, R2], [D, A, R1]]
                caps = [(R1, R2), (A, R1), (D, R1), (B, R2), (Cc, R2)]
            else:
                r = self.hw - self.hl
                R1, R2 = (0, -r, zr), (0, r, zr)
                faces = [[A, B, R1], [B, Cc, R2, R1], [Cc, D, R2], [D, A, R1, R2]]
                caps = [(R1, R2), (A, R1), (B, R1), (Cc, R2), (D, R2)]
            if abs(R1[0] - R2[0]) < 1e-6 and abs(R1[1] - R2[1]) < 1e-6:
                faces = [f if len(f) == 3 else [f[0], f[1], f[2]] for f in faces]
                caps = caps[1:]
            loop = [A, B, Cc, D]
            eaves = [(A, B), (B, Cc), (Cc, D), (D, A)]
        elif self.roof == "gable":
            if self.ridge == "u":
                z0 = z0v
                zr = self.eave + self.hw * p + lift
                A, B, Cc, D = (-HU, -HV, z0), (HU, -HV, z0), (HU, HV, z0), (-HU, HV, z0)
                R1, R2 = (-HU, 0, zr), (HU, 0, zr)
                faces = [[A, B, R2, R1], [Cc, D, R1, R2]]
                loop = [A, B, R2, Cc, D, R1]
                eaves = [(A, B), (Cc, D)]
            else:
                z0 = z0u
                zr = self.eave + self.hl * p + lift
                A, B, Cc, D = (-HU, -HV, z0), (HU, -HV, z0), (HU, HV, z0), (-HU, HV, z0)
                R1, R2 = (0, -HV, zr), (0, HV, zr)
                faces = [[B, Cc, R2, R1], [D, A, R1, R2]]
                loop = [A, R1, B, Cc, R2, D]
                eaves = [(B, Cc), (D, A)]
            caps = [(R1, R2)]
        elif self.roof == "shed":
            hi = self.high
            if hi in ("v1", "v0"):
                sg = 1 if hi == "v1" else -1
                zlo = self.eave - OVER * p + lift
                zhi = self.eave + 2 * self.hw * p + lift
                lo_t, hi_t = -sg * HV, sg * self.hw
                A, B = (-HU, lo_t, zlo), (HU, lo_t, zlo)
                Cc, D = (HU, hi_t, zhi), (-HU, hi_t, zhi)
            else:
                sg = 1 if hi == "u1" else -1
                zlo = self.eave - OVER * p + lift
                zhi = self.eave + 2 * self.hl * p + lift
                lo_s, hi_s = -sg * HU, sg * self.hl
                A, B = (lo_s, HV, zlo), (lo_s, -HV, zlo)
                Cc, D = (hi_s, -HV, zhi), (hi_s, HV, zhi)
            f = [A, B, Cc, D]
            if np.cross(np.array(B) - np.array(A), np.array(Cc) - np.array(A))[2] < 0:
                f = f[::-1]
            faces = [f]
            loop = f
            eaves = [(A, B)]
        return faces, loop, eaves, caps


def roof_uv(pts3):
    P = np.asarray(pts3, float)
    n = np.cross(P[1] - P[0], P[2] - P[0])
    n /= np.linalg.norm(n) + 1e-12
    h = np.array([-n[1], n[0], 0.0])
    if np.linalg.norm(h) < 1e-6:
        return P[:, :2]
    h /= np.linalg.norm(h)
    s = np.cross(n, h)
    if s[2] < 0:
        s = -s
    return np.stack([P @ h, P @ s], 1)


# ============================================================================ house builder
class HouseBuilder:
    def __init__(self, num, coll):
        self.num = num
        self.h = C.house(num)
        self.f = C.facade(num)
        self.spec = SPECS[num]
        self.coll = coll
        self.rng = C.rng_for("house", num)
        fp = C.ccw(self.h["footprint_local"]["value"])
        self.fp = fp
        self.poly = Polygon(fp)
        g = self.h["ground"]
        self.floor = max(g["z_ring_median"] + 0.4, g["z_ring_max"] - 0.25)
        self.c = np.array(self.h["centroid_local"])
        self.wings = [Wing(w, self.c, self.spec["frame"], self.spec["pitch"], self.floor, i, num)
                      for i, w in enumerate(self.spec["wings"])]
        self.main = [w for w in self.wings if w.kind == "main"]
        for w in self.wings:
            if w.kind == "dormer":
                host = max(self.main, key=lambda m: float(m.depth(*w.c)))
                w.dormer_main = host
                w.eave = host.eave + (1.15 if w.st == 2 else 1.55)
        self.dtm = C.dtm()
        self._mats()
        self.mb = C.MeshBuilder()          # walls, trims, windows
        self.rb = C.MeshBuilder()          # roof
        self.extra = []                    # separate objects (doors, deck...)
        self.openings = {}
        self.doors_info = {}
        cl = C.data("boundary")["canby_ct_centerline_local"]["coordinates"]
        self.street = LineString(cl)
        self.plan_doors()

    # ------------------------------------------------------------------ materials
    def _mats(self):
        f = self.f
        n = self.num
        V = C.fval
        body = V(f, "body_colour")
        trim = V(f, "trim_colour")
        sid = V(f, "siding")
        roofc = V(f, "roof")["colour_hex"]
        self.trim_hex = trim
        gd = V(f, "garage_door")
        gcol = trim if gd["colour"] == "trim" else gd["colour"]
        gut = V(f, "gutters")
        gcolg = trim if gut["colour"] == "trim" else gut["colour"]
        win = V(f, "windows")
        door = V(f, "door")
        self.m_siding = MAT.tex_mat("SID_%d" % n, sid["texture"], tint=body, normal_strength=1.2)
        self.m_siding2 = None
        if sid.get("gables"):
            self.m_siding2 = MAT.tex_mat("SID2_%d" % n, sid["gables"], tint=body)
        if sid.get("upper"):
            self.m_siding2 = MAT.tex_mat("SID2_%d" % n, "siding_lap_wood", tint=body)
        self.m_wainscot = MAT.tex_mat("STONE_%d" % n, sid["wainscot"]) if sid.get("wainscot") else None
        self.m_trim = MAT.tex_mat("TRIM_%d" % n, "trim_paint", tint=trim)
        self.m_soffit = self.m_trim
        self.m_roof = MAT.tex_mat("ROOF_%d" % n, "roof_arch_shingle", tint=roofc, normal_strength=1.3)
        self.m_ridge = MAT.tex_mat("RIDGE_%d" % n, "roof_ridge_cap", tint=roofc)
        self.m_found = MAT.M("FOUND", lambda: MAT.tex_mat("FOUNDATION", "concrete_plain", tint="#9a978f"))
        self.m_frame = MAT.flat_mat("WINFRAME_%s" % win["frame_hex"].lstrip("#"), win["frame_hex"], rough=0.45)
        self.m_glass = MAT.glass_mat("GLASS_window")
        self.m_glass_lit = MAT.glass_mat("GLASS_window_lit", lit=True)
        self.m_door = MAT.tex_mat("DOOR_%d" % n, "door_" + door["style"], tint=door["colour"])
        self.m_gdoor = MAT.tex_mat("GDOOR_%d" % n, "garage_door_panel", tint=gcol)
        self.m_gutter = MAT.flat_mat("GUTTER_%d" % n, gcolg, rough=0.4, metal=0.0)
        self.m_dark = MAT.M("DARKMETAL", lambda: MAT.flat_mat("METAL_dark", "#2a2a2a", rough=0.4, metal=0.6))
        self.m_brick = MAT.M("BRICK", lambda: MAT.tex_mat("BRICK", "brick_red"))
        self.m_concrete = MAT.M("CONC", lambda: MAT.tex_mat("CONCRETE_plain", "concrete_plain"))
        self.m_deck = MAT.M("DECK", lambda: MAT.tex_mat("DECK_wood", "wood_deck", tint="#c9a98c"))
        self.m_light = MAT.M("PORCHLIGHT", lambda: MAT.flat_mat("LIGHT_porch", "#fff2d8", rough=0.2,
                                                               emit="#ffc27a", emit_strength=0.0))
        self.m_brass = MAT.M("BRASS", lambda: MAT.flat_mat("METAL_brass", "#b08a4a", rough=0.3, metal=1.0))
        self.m_solar = MAT.M("SOLAR", lambda: MAT.tex_mat("SOLAR_panel", "solar_panel"))
        self.m_skyl = MAT.M("SKYGLASS", lambda: MAT.flat_mat("GLASS_skylight", "#1a2026", rough=0.05, coat=1.0))

    # ------------------------------------------------------------------ helpers
    def ground(self, x, y):
        return float(self.dtm.sample(x, y))

    def roofz(self, x, y, kinds=("main", "dormer")):
        z = -np.inf
        for w in self.wings:
            if w.kind in kinds:
                z = max(z, float(w.roof_z(x, y)))
        return z

    def owner(self, x, y, exclude=None):
        best, bd = None, -1e9
        for w in self.main:
            if w is exclude:
                continue
            if w.contains(x, y, 0.05):
                d = float(w.depth(x, y))
                if d > bd:
                    best, bd = w, d
        return best

    def nearest_wing(self, x, y):
        return min(self.main, key=lambda w: -float(w.depth(x, y)))

    # ------------------------------------------------------------------ wall with openings
    def wall(self, mb, a, b, ztop, zbot_a, zbot_b, mat, openings=(), found=True, zfound_a=None, zfound_b=None,
             upper=False):
        """Planar wall a->b (outward normal = right-hand side for a CCW polygon). openings: list of dicts
        {s0,s1,z0,z1,kind,...} in (along-wall m, absolute z). zbot: siding bottom per end."""
        a = np.asarray(a, float)
        b = np.asarray(b, float)
        d = b - a
        Lw = float(np.linalg.norm(d))
        if Lw < 0.05:
            return
        d /= Lw
        n = np.array([d[1], -d[0]])
        u_off = float(a @ d)

        def P(s, z, depth=0.0):
            q = a + d * s + n * depth
            return (float(q[0]), float(q[1]), float(z))

        def zb(s):
            return zbot_a + (zbot_b - zbot_a) * s / Lw

        ops = sorted(openings, key=lambda o: o["s0"])
        br = sorted(set([0.0, Lw] + [o["s0"] for o in ops] + [o["s1"] for o in ops]))
        br = [x for x in br if 0 <= x <= Lw]
        for sa, sb in zip(br[:-1], br[1:]):
            if sb - sa < 1e-4:
                continue
            cov = sorted([o for o in ops if o["s0"] <= sa + 1e-6 and o["s1"] >= sb - 1e-6], key=lambda o: o["z0"])
            cur_a, cur_b = zb(sa), zb(sb)
            for o in cov:
                if o["z0"] > max(cur_a, cur_b) + 1e-3:
                    quad = [P(sa, cur_a), P(sb, cur_b), P(sb, o["z0"]), P(sa, o["z0"])]
                    mb.poly(quad, mat, uvs=[(u_off + sa, cur_a), (u_off + sb, cur_b), (u_off + sb, o["z0"]),
                                            (u_off + sa, o["z0"])])
                cur_a = cur_b = o["z1"]
            if ztop > max(cur_a, cur_b) + 1e-3:
                quad = [P(sa, cur_a), P(sb, cur_b), P(sb, ztop), P(sa, ztop)]
                mb.poly(quad, mat, uvs=[(u_off + sa, cur_a), (u_off + sb, cur_b), (u_off + sb, ztop),
                                        (u_off + sa, ztop)])
        if found:
            fa = zfound_a if zfound_a is not None else zbot_a - 0.7
            fb = zfound_b if zfound_b is not None else zbot_b - 0.7
            q = [P(0, fa, -0.015), P(Lw, fb, -0.015), P(Lw, zbot_b, -0.015), P(0, zbot_a, -0.015)]
            mb.poly(q, self.m_found, uvs=[(u_off, fa), (u_off + Lw, fb), (u_off + Lw, zbot_b), (u_off, zbot_a)])
        for o in ops:
            self.opening(mb, P, o, u_off)

    def wbox(self, mb, P, s0, s1, z0, z1, d0, d1, mat, uv_off=0.0):
        """box in wall coords: s along the wall, z absolute, d outward from the wall plane."""
        c = [P(s0, z0, d0), P(s1, z0, d0), P(s1, z1, d0), P(s0, z1, d0),
             P(s0, z0, d1), P(s1, z0, d1), P(s1, z1, d1), P(s0, z1, d1)]
        for q in ([4, 5, 6, 7], [5, 1, 2, 6], [0, 4, 7, 3], [7, 6, 2, 3], [0, 1, 5, 4]):
            mb.poly([c[i] for i in q], mat, uv_mode="plane")

    def opening(self, mb, P, o, u_off):
        s0, s1, z0, z1 = o["s0"], o["s1"], o["z0"], o["z1"]
        kind = o["kind"]
        D = 0.14 if kind != "garage" else 0.18
        # reveals (jambs, head, sill)
        rmat = self.m_frame if kind == "window" else self.m_trim
        mb.poly([P(s0, z0, 0), P(s0, z0, -D), P(s0, z1, -D), P(s0, z1, 0)], rmat, uv_mode="plane")
        mb.poly([P(s1, z0, -D), P(s1, z0, 0), P(s1, z1, 0), P(s1, z1, -D)], rmat, uv_mode="plane")
        mb.poly([P(s0, z1, 0), P(s0, z1, -D), P(s1, z1, -D), P(s1, z1, 0)], rmat, uv_mode="plane")
        mb.poly([P(s0, z0, -D), P(s0, z0, 0), P(s1, z0, 0), P(s1, z0, -D)], rmat, uv_mode="plane")
        tw = 0.09 if kind != "garage" else 0.11
        tr = self.m_trim
        if getattr(self, "simple", False) and kind == "window":
            self.wbox(mb, P, s0 - tw, s1 + tw, z1, z1 + tw, 0, 0.03, tr)
            self.wbox(mb, P, s0 - tw, s1 + tw, z0 - 0.045, z0, -0.02, 0.05, tr)
            cell = int(self.rng.integers(0, 4))
            cu, cv = (cell % 2) * 0.5, 1 - (cell // 2 + 1) * 0.5
            dg = -0.085
            mb.poly([P(s0, z0, dg), P(s1, z0, dg), P(s1, z1, dg), P(s0, z1, dg)],
                    self.m_glass_lit if o.get("lit") else self.m_glass,
                    uvs=[(cu + 0.02, cv + 0.02), (cu + 0.48, cv + 0.02), (cu + 0.48, cv + 0.48), (cu + 0.02, cv + 0.48)])
            return
        # casing
        self.wbox(mb, P, s0 - tw, s0, z0, z1 + tw, 0, 0.022, tr)
        self.wbox(mb, P, s1, s1 + tw, z0, z1 + tw, 0, 0.022, tr)
        self.wbox(mb, P, s0 - tw - 0.015, s1 + tw + 0.015, z1, z1 + tw + 0.03, 0, 0.03, tr)
        if kind == "window":
            self.wbox(mb, P, s0 - tw - 0.03, s1 + tw + 0.03, z0 - 0.045, z0, -0.02, 0.05, tr)     # sill
            fw = 0.055
            dg = -0.085
            fm = self.m_frame
            self.wbox(mb, P, s0, s0 + fw, z0, z1, dg, dg + 0.06, fm)
            self.wbox(mb, P, s1 - fw, s1, z0, z1, dg, dg + 0.06, fm)
            self.wbox(mb, P, s0, s1, z1 - fw, z1, dg, dg + 0.06, fm)
            self.wbox(mb, P, s0, s1, z0, z0 + fw, dg, dg + 0.06, fm)
            st = o.get("style", "slider")
            if st in ("slider", "picture3"):
                xs = [(s0 + s1) / 2] if st == "slider" else [s0 + (s1 - s0) / 3, s0 + 2 * (s1 - s0) / 3]
                for x in xs:
                    self.wbox(mb, P, x - 0.035, x + 0.035, z0, z1, dg - 0.01, dg + 0.06, fm)
            elif st == "hung":
                zm = (z0 + z1) / 2
                self.wbox(mb, P, s0, s1, zm - 0.03, zm + 0.03, dg - 0.01, dg + 0.06, fm)
                if o.get("grilles"):
                    for k in (1, 2):
                        x = s0 + (s1 - s0) * k / 3
                        self.wbox(mb, P, x - 0.012, x + 0.012, zm, z1, dg + 0.005, dg + 0.02, fm)
            cell = int(self.rng.integers(0, 4))
            cu, cv = (cell % 2) * 0.5, 1 - (cell // 2 + 1) * 0.5
            lit = o.get("lit", False)
            mb.poly([P(s0, z0, dg), P(s1, z0, dg), P(s1, z1, dg), P(s0, z1, dg)],
                    self.m_glass_lit if lit else self.m_glass,
                    uvs=[(cu + 0.02, cv + 0.02), (cu + 0.48, cv + 0.02), (cu + 0.48, cv + 0.48), (cu + 0.02, cv + 0.48)])
        elif kind == "door":
            dd = -0.1
            mb.poly([P(s0, z0, dd), P(s1, z0, dd), P(s1, z1, dd), P(s0, z1, dd)], self.m_door,
                    uvs=[(0, 0), (0.9144, 0), (0.9144, 2.032), (0, 2.032)])
            self.wbox(mb, P, s0 - 0.05, s1 + 0.05, z0 - 0.02, z0 + 0.01, -D, 0.03, self.m_brass)    # threshold
        elif kind == "garage":
            dd = -0.12
            nrep = max(1, round((s1 - s0) / 2.4384))
            mb.poly([P(s0, z0, dd), P(s1, z0, dd), P(s1, z1, dd), P(s0, z1, dd)], self.m_gdoor,
                    uvs=[(0, 0), (2.4384 * nrep * (1 if nrep > 1 else (s1 - s0) / 2.4384 * 0 + 1), 0),
                         (2.4384 * nrep, 2.1336), (0, 2.1336)])

    # ------------------------------------------------------------------ layout
    def street_facing(self, m, n):
        sp = self.street.interpolate(self.street.project(Point(m[0], m[1])))
        v = np.array([sp.x - m[0], sp.y - m[1]])
        return float(v @ n) / (np.linalg.norm(v) + 1e-9)

    def plan_windows(self, a, b, n, wing, ztop, zbot_a, zbot_b, blocked, upper_from=None, level_min=None):
        a = np.asarray(a)
        b = np.asarray(b)
        Lw = float(np.linalg.norm(b - a))
        sf = self.street_facing((a + b) / 2, n)
        rng = self.rng
        winf = C.fval(self.f, "windows")
        out = []
        storeys = int(math.floor(wing.st + 1e-6))
        levels = list(range(storeys))
        if min(zbot_a, zbot_b) < wing.floor - 2.4:
            levels = [-1] + levels
        if upper_from is not None:
            levels = [k for k in levels if wing.floor + k * STOREY + 0.8 > upper_from + 0.4]
        free = [(0.6, Lw - 0.6)]
        for (b0, b1) in blocked:
            nf = []
            for (f0, f1) in free:
                if b1 <= f0 or b0 >= f1:
                    nf.append((f0, f1))
                else:
                    if b0 > f0:
                        nf.append((f0, b0))
                    if b1 < f1:
                        nf.append((b1, f1))
            free = nf
        for k in levels:
            fz = wing.floor + k * STOREY
            for (f0, f1) in free:
                seg = f1 - f0
                if seg < 1.0:
                    continue
                skip_p = 0.04 if sf > 0.3 else 0.2
                if k == -1:
                    skip_p = 0.5
                if seg > 6 and sf > 0.3 and k == 0 and rng.random() < 0.6:
                    kinds = ["picture"]
                else:
                    kinds = None
                nwin = max(1, int(seg // 2.9))
                for i in range(nwin):
                    if rng.random() < skip_p and nwin > 1:
                        continue
                    cx = f0 + seg * (i + 0.5) / nwin
                    sub = seg / nwin
                    if kinds:
                        w, h, sill, style = min(2.4, sub - 0.6), 1.5, 0.6, "picture3"
                    else:
                        r = rng.random()
                        if sub < 1.6 or r < 0.18:
                            w, h, sill, style = 0.75, 0.6, 1.45, "slider"
                        elif r < 0.6:
                            w, h, sill, style = 1.5, 1.2, 0.95, "slider"
                        else:
                            w, h, sill, style = min(1.8, sub - 0.6), 1.2, 0.95, "slider"
                        if "single-hung" in winf["type"]:
                            w, h, sill, style = min(w, 0.95), (1.45 if h > 1 else 0.7), (0.75 if h > 1 else 1.4), "hung"
                    if w < 0.5:
                        continue
                    s0, s1 = cx - w / 2, cx + w / 2
                    z0 = fz + sill
                    z1 = z0 + h
                    zb = max(zbot_a + (zbot_b - zbot_a) * s0 / Lw, zbot_a + (zbot_b - zbot_a) * s1 / Lw)
                    if z1 > ztop - 0.25 or z0 < zb + 0.25:
                        continue
                    if upper_from is not None and z0 < upper_from + 0.35:
                        continue
                    if style == "hung" and w > 1.2:
                        # pair of single-hung units
                        out.append(dict(s0=s0, s1=cx - 0.05, z0=z0, z1=z1, kind="window", style="hung",
                                        grilles=winf.get("grilles")))
                        out.append(dict(s0=cx + 0.05, s1=s1, z0=z0, z1=z1, kind="window", style="hung",
                                        grilles=winf.get("grilles")))
                    else:
                        out.append(dict(s0=s0, s1=s1, z0=z0, z1=z1, kind="window", style=style,
                                        grilles=winf.get("grilles")))
        # some lit windows (winter / dusk); chosen deterministically
        for o in out:
            o["lit"] = bool(rng.random() < 0.35)
        return out

    # ------------------------------------------------------------------ walls from the measured footprint
    def plan_doors(self):
        """Door / garage-door positions on the footprint (needed before driveway grading)."""
        fp = self.fp
        N = len(fp)
        V = C.fval
        gd = V(self.f, "garage_door")
        fd = V(self.f, "front_door")
        door_edges = {}

        def nearest_edge(pt):
            best = None
            for i in range(N):
                a, b = np.array(fp[i]), np.array(fp[(i + 1) % N])
                seg = LineString([a, b])
                dd = seg.distance(Point(pt))
                if best is None or dd < best[0]:
                    s = seg.project(Point(pt))
                    best = (dd, i, s, float(np.linalg.norm(b - a)))
            return best

        self.plan = []
        if fd:
            _, i, s, Lw = nearest_edge(fd["wall_point"])
            w = 0.9144
            s = min(max(s, w / 2 + 0.25), Lw - w / 2 - 0.25)
            door_edges.setdefault(i, []).append(("door", s - w / 2, s + w / 2, 2.032))
        if gd:
            _, i, s, Lw = nearest_edge(gd["wall_point"])
            cnt, w, hgt = gd["count"], gd["width_m"], gd["height_m"]
            tot = cnt * w + (cnt - 1) * 0.45
            s = min(max(s, tot / 2 + 0.25), Lw - tot / 2 - 0.25)
            x = s - tot / 2
            for k in range(cnt):
                door_edges.setdefault(i, []).append(("garage", x, x + w, hgt))
                x += w + 0.45
        self.door_edges = door_edges
        for i, lst in door_edges.items():
            a, b = np.array(fp[i], float), np.array(fp[(i + 1) % N], float)
            Lw = float(np.linalg.norm(b - a))
            d = (b - a) / Lw
            n = np.array([d[1], -d[0]])
            for (kind, s0, s1, hgt) in lst:
                mid = a + d * ((s0 + s1) / 2)
                q = mid - n * 0.4
                w = self.owner(q[0], q[1]) or self.nearest_wing(q[0], q[1])
                z0 = w.floor if kind == "door" else w.floor - 0.12
                self.plan.append(dict(kind=kind, center=[float(mid[0]), float(mid[1])], z=float(z0),
                                      normal=[float(n[0]), float(n[1])], width=float(s1 - s0), height=float(hgt)))
        return self.plan

    def build_walls(self):
        fp = self.fp
        N = len(fp)
        door_edges = self.door_edges
        for i in range(N):
            a, b = np.array(fp[i], float), np.array(fp[(i + 1) % N], float)
            Lw = float(np.linalg.norm(b - a))
            if Lw < 0.05:
                continue
            d = (b - a) / Lw
            n = np.array([d[1], -d[0]])
            # split by owner wing
            ns = max(2, int(Lw / 0.25))
            ss = np.linspace(0, Lw, ns + 1)
            mids = (ss[:-1] + ss[1:]) / 2
            owners = []
            for s in mids:
                q = a + d * s - n * 0.25
                w = self.owner(q[0], q[1]) or self.nearest_wing(q[0], q[1])
                owners.append(w)
            pieces = []
            st = 0
            for k in range(1, len(mids) + 1):
                if k == len(mids) or owners[k] is not owners[st]:
                    pieces.append((ss[st], ss[k], owners[st]))
                    st = k
            for (p0, p1, w) in pieces:
                pa, pb = a + d * p0, a + d * p1
                Lp = p1 - p0
                ga, gb = self.ground(*pa), self.ground(*pb)
                zt = w.eave + 0.02
                za, zb_ = ga + 0.18, gb + 0.18
                ops = []
                blocked = []
                for (kind, s0, s1, hgt) in door_edges.get(i, []):
                    if s0 >= p0 - 1e-6 and s1 <= p1 + 1e-6:
                        z0 = w.floor if kind == "door" else w.floor - 0.12
                        ops.append(dict(s0=s0 - p0, s1=s1 - p0, z0=z0, z1=z0 + hgt, kind=kind))
                        blocked.append((s0 - p0 - 0.5, s1 - p0 + 0.5))
                        mid = a + d * ((s0 + s1) / 2)
                        info = dict(kind=kind, center=[float(mid[0]), float(mid[1])], z=float(z0),
                                    normal=[float(n[0]), float(n[1])], width=float(s1 - s0), height=float(hgt))
                        self.doors_info.setdefault(kind, []).append(info)
                        if kind == "door":
                            self.front_door = info
                            # door can't start below the siding bottom: lift siding bottom locally
                if Lp > 1.6:
                    ops += self.plan_windows(pa, pb, n, w, zt, za, zb_, blocked)
                # ensure siding bottom stays under doors
                for o in ops:
                    if o["kind"] in ("door", "garage"):
                        za = min(za, o["z0"] - 0.01)
                        zb_ = min(zb_, o["z0"] - 0.01)
                mat = self.m_siding
                self.wall(self.mb, pa, pb, zt, za, zb_, mat, ops, zfound_a=ga - 0.6, zfound_b=gb - 0.6)
                if self.m_siding2 is not None and C.fval(self.f, "siding").get("upper") and w.st >= 2:
                    pass

    # ------------------------------------------------------------------ upper walls (tall wing above a lower one)
    def build_upper_walls(self):
        for R in self.main:
            HU, HV = R.hl, R.hw
            corners = [(-HU, -HV), (HU, -HV), (HU, HV), (-HU, HV)]
            for e in range(4):
                s_a, s_b = np.array(corners[e]), np.array(corners[(e + 1) % 4])
                A = R.world(*s_a)
                B = R.world(*s_b)
                Lw = float(np.linalg.norm(B - A))
                d = (B - A) / Lw
                n = np.array([d[1], -d[0]])
                ns = max(2, int(Lw / 0.25))
                ss = np.linspace(0, Lw, ns + 1)
                mids = (ss[:-1] + ss[1:]) / 2
                need = []
                for s in mids:
                    p = A + d * s
                    q = p + n * 0.3
                    if not self.poly.buffer(-0.05).contains(Point(q)):
                        need.append(None)
                        continue
                    o = self.owner(q[0], q[1], exclude=R)
                    if o is None or o.eave >= R.eave - 0.4:
                        need.append(None)
                        continue
                    zlow = max(float(o.roof_z(*p)), o.eave) - 0.35
                    need.append(zlow if np.isfinite(zlow) else o.eave)
                k = 0
                while k < len(mids):
                    if need[k] is None:
                        k += 1
                        continue
                    j = k
                    while j < len(mids) and need[j] is not None:
                        j += 1
                    p0, p1 = ss[k], ss[j]
                    za = need[k]
                    zb_ = need[j - 1]
                    pa, pb = A + d * p0, A + d * p1
                    if R.roof == "gable":
                        # gable end walls get the triangle from the roof builder
                        pass
                    ops = []
                    if p1 - p0 > 1.6:
                        ops = self.plan_windows(pa, pb, n, R, R.eave, za, zb_, [], upper_from=max(za, zb_))
                    self.wall(self.mb, pa, pb, R.eave + 0.02, za, zb_, self.m_siding, ops, found=False)
                    k = j

    # ------------------------------------------------------------------ roofs
    def build_roofs(self, snow=False):
        for w in self.wings:
            self.roof_wing(w)
            if w.roof == "gable":
                self.gable_ends(w)
            if w.kind == "dormer":
                self.dormer_walls(w)
            if w.kind == "porch":
                self.porch_posts(w)

    def roof_wing(self, w):
        rb = self.rb
        faces, loop, eaves, caps = w.top_faces()
        W3 = lambda q: w.P3(q[0], q[1], q[2])
        for f in faces:
            P = [W3(q) for q in f]
            rb.poly(P, self.m_roof, uvs=roof_uv(P))
            Pb = [(x, y, z - SLAB) for (x, y, z) in P[::-1]]
            rb.poly(Pb, self.m_soffit, uv_mode="xy")
        # fascia / barge skirt around the loop
        L = [W3(q) for q in loop]
        for i in range(len(L)):
            a, b = L[i], L[(i + 1) % len(L)]
            q = [a, b, (b[0], b[1], b[2] - SLAB), (a[0], a[1], a[2] - SLAB)]
            nrm = np.cross(np.subtract(q[1], q[0]), np.subtract(q[3], q[0]))
            rb.poly(q[::-1] if self._outward(w, q, nrm) else q, self.m_trim, uv_mode="plane")
        for (p, q) in caps:
            self.ridge_cap(W3(p), W3(q))
        for (p, q) in eaves:
            self.gutter(w, W3(p), W3(q))

    def _outward(self, w, quad, nrm):
        cen = np.mean(np.array(quad), 0)
        out = np.array([cen[0] - w.c[0], cen[1] - w.c[1], 0])
        return float(np.dot(nrm, out)) < 0

    def ridge_cap(self, p, q):
        p, q = np.array(p), np.array(q)
        dvec = q - p
        L = np.linalg.norm(dvec)
        if L < 0.2:
            return
        d = dvec / L
        up = np.array([0, 0, 1.0]) - d * d[2]
        up /= np.linalg.norm(up)
        side = np.cross(d, up)
        hw = 0.16
        prof = [side * hw - up * 0.02, up * 0.035, -side * hw - up * 0.02]
        A = [p + o for o in prof]
        B = [q + o for o in prof]
        for i in range(2):
            quad = [A[i], B[i], B[i + 1], A[i + 1]]
            uv = [(0, 0.3 * (i)), (L, 0.3 * i), (L, 0.3 * (i + 0.5)), (0, 0.3 * (i + 0.5))]
            self.rb.poly(quad, self.m_ridge, uvs=[(0, 0), (L, 0), (L, 0.15), (0, 0.15)])

    def gutter(self, w, p, q):
        p, q = np.array(p), np.array(q)
        L = float(np.linalg.norm(q[:2] - p[:2]))
        if L < 0.3:
            return
        d = (q - p) / L
        out = np.array([d[1], -d[0], 0])
        mid = (p + q) / 2
        if np.dot(out[:2], mid[:2] - w.c) < 0:
            out = -out
        # sample and clip against other (higher) wings
        ns = max(2, int(L / 0.25))
        keep = []
        for k in range(ns):
            s = (k + 0.5) / ns * L
            x = p + d * s + out * 0.05
            hid = False
            for o in self.wings:
                if o is w or o.kind == "porch":
                    continue
                if float(o.roof_z(x[0], x[1])) > x[2] - 0.15:
                    hid = True
                    break
            keep.append(not hid)
        k = 0
        z = p[2]
        while k < ns:
            if not keep[k]:
                k += 1
                continue
            j = k
            while j < ns and keep[j]:
                j += 1
            s0, s1 = k / ns * L, j / ns * L
            a = p + d * s0
            b = p + d * s1
            pts = []
            for (o0, z0) in ((0.0, -0.03), (0.13, -0.03), (0.13, -0.16), (0.02, -0.17)):
                pass
            A0 = a + out * 0.005
            B0 = b + out * 0.005
            G = [(0.0, -0.02), (0.13, -0.02), (0.12, -0.15), (0.01, -0.15)]
            ring_a = [A0 + out * gx + np.array([0, 0, gz]) for gx, gz in G]
            ring_b = [B0 + out * gx + np.array([0, 0, gz]) for gx, gz in G]
            for i in range(4):
                quad = [ring_a[i], ring_b[i], ring_b[(i + 1) % 4], ring_a[(i + 1) % 4]]
                self.rb.poly(quad, self.m_gutter, uv_mode="plane")
            self.rb.poly(ring_a[::-1], self.m_gutter, uv_mode="plane")
            self.rb.poly(ring_b, self.m_gutter, uv_mode="plane")
            # downspouts at run ends that are wing corners
            for end, sgn in ((a, 1), (b, -1)):
                is_corner = (abs(np.dot(end[:2] - p[:2], d[:2])) < 0.05) or (abs(np.dot(end[:2] - q[:2], d[:2])) < 0.05)
                if not is_corner or w.kind == "dormer":
                    continue
                self.downspout(w, end, d * sgn, out)
            k = j

    def downspout(self, w, end, inward, out):
        # wall corner below: pull back by the overhang
        top = end + inward * (OVER + 0.15) + out * 0.07
        wallp = end[:2] + inward[:2] * (OVER + 0.15) - out[:2] * (OVER - 0.05)
        if self.poly.buffer(-0.1).contains(Point(wallp[0], wallp[1])):
            return
        # must be close to the footprint boundary
        if self.poly.exterior.distance(Point(wallp[0], wallp[1])) > 0.5:
            return
        g = self.ground(*wallp)
        if w.eave - g > 12 or w.kind == "porch":
            return
        z1 = end[2] - 0.15
        path = [(top[0], top[1], z1), (wallp[0], wallp[1], z1 - 0.35), (wallp[0], wallp[1], g + 0.3),
                (wallp[0] + out[0] * 0.3, wallp[1] + out[1] * 0.3, g + 0.06)]
        self.mb.tube(path, 0.04, self.m_gutter, sides=4, cap=True, smooth=False)
        # splash block
        cx, cy = wallp[0] + out[0] * 0.45, wallp[1] + out[1] * 0.45
        self.mb.box((cx, cy, g + 0.02), (0.6, 0.3, 0.05), self.m_concrete, rotz=math.atan2(out[1], out[0]))

    def gable_ends(self, w):
        p = w.p
        for sg in (-1, 1):
            if w.ridge == "u":
                s = sg * w.hl
                pts = [(s, -sg * w.hw, w.eave), (s, sg * w.hw, w.eave), (s, 0, w.eave + w.hw * p)]
                probe = w.world(s + sg * 0.3, 0)
            else:
                t = sg * w.hw
                pts = [(sg * w.hl, t, w.eave), (-sg * w.hl, t, w.eave), (0, t, w.eave + w.hl * p)]
                probe = w.world(0, t + sg * 0.3)
            o = self.owner(probe[0], probe[1], exclude=w)
            if o is not None and o.eave >= w.eave - 0.3 and w.kind != "dormer":
                continue
            P = [w.P3(*q) for q in pts]
            nrm = np.cross(np.subtract(P[1], P[0]), np.subtract(P[2], P[0]))
            outv = np.array([probe[0] - w.c[0], probe[1] - w.c[1], 0])
            if np.dot(nrm, outv) < 0:
                P = P[::-1]
            mat = self.m_siding2 if (self.m_siding2 is not None and C.fval(self.f, "siding").get("gables")) \
                else self.m_siding
            self.mb.poly(P, mat, uv_mode="wall")
            # louvred gable vent / dormer window
            hgt = (w.hw if w.ridge == "u" else w.hl) * p
            base = np.array(P[0][:2]) * 0.5 + np.array(P[1][:2]) * 0.5
            if w.kind == "dormer":
                continue
            if hgt > 1.4:
                dvec = np.array(P[1][:2]) - np.array(P[0][:2])
                dvec /= np.linalg.norm(dvec)
                nn = np.array([dvec[1], -dvec[0]])
                zc = w.eave + hgt * 0.45
                cx = base + nn * 0.02
                self.mb.box((cx[0], cx[1], zc), (0.7, 0.06, 0.45), self.m_trim, rotz=math.atan2(dvec[1], dvec[0]))

    def dormer_walls(self, w):
        host = w.dormer_main
        # front = v end farther from the host centre
        ends = [-w.hw, w.hw] if w.ridge == "v" else [-w.hl, w.hl]
        dists = []
        for t in ends:
            q = w.world(0, t) if w.ridge == "v" else w.world(t, 0)
            dists.append(np.linalg.norm(q - host.c))
        tf = ends[int(np.argmax(dists))]
        sg = 1 if tf > 0 else -1
        if w.ridge == "v":
            a, b = w.world(-w.hl * sg, tf), w.world(w.hl * sg, tf)
        else:
            a, b = w.world(tf, w.hw * sg), w.world(tf, -w.hw * sg)
        zr_a, zr_b = float(host.roof_z(*a)), float(host.roof_z(*b))
        zbot = min(zr_a, zr_b) - 0.05
        # make sure a->b has the outward normal on the right side
        dvec = b - a
        nrm = np.array([dvec[1], -dvec[0]])
        if np.dot(nrm, (a + b) / 2 - w.c) < 0:
            a, b = b, a
        Lw = float(np.linalg.norm(b - a))
        wh = min(0.9, w.eave - zbot - 0.35)
        ops = []
        if wh > 0.35:
            ww = Lw - 0.55
            ops.append(dict(s0=(Lw - ww) / 2, s1=(Lw + ww) / 2, z0=w.eave - 0.2 - wh, z1=w.eave - 0.2,
                            kind="window", style="slider" if ww > 1.0 else "fixed", lit=bool(self.rng.random() < 0.4)))
        self.wall(self.mb, a, b, w.eave + 0.02, zbot, zbot, self.m_siding, ops, found=False)
        # cheek walls
        for side in (-1, 1):
            pts_top, pts_bot = [], []
            for f in np.linspace(0, 1, 9):
                if w.ridge == "v":
                    q = w.world(side * w.hl, tf - sg * f * w.W)
                else:
                    q = w.world(tf - sg * f * w.L, side * w.hw)
                zr = float(host.roof_z(*q))
                if zr >= w.eave:
                    break
                pts_top.append((q[0], q[1], w.eave))
                pts_bot.append((q[0], q[1], zr - 0.05))
            if len(pts_top) >= 2:
                P = pts_bot + pts_top[::-1]
                self.mb.poly(P, self.m_siding, uv_mode="wall")
                self.mb.poly(P[::-1], self.m_siding, uv_mode="wall")

    def porch_posts(self, w):
        HU, HV = w.hl, w.hw
        hi = w.high if w.roof == "shed" else None
        corners = [(-HU, -HV), (HU, -HV), (HU, HV), (-HU, HV)]
        craftsman = self.num == 3813
        for (s, t) in corners:
            p = w.world(s * 0.92, t * 0.92)
            if self.poly.buffer(0.2).contains(Point(p[0], p[1])):
                continue
            g = self.ground(*p)
            zt = float(w.roof_z(*p)) - SLAB
            zb = min(g, w.floor - 0.15)
            if craftsman:
                self.mb.box((p[0], p[1], zb + 0.5), (0.45, 0.45, 1.0 + (g - zb) * 0), self.m_wainscot or self.m_concrete,
                            rotz=w.a)
                self.mb.box((p[0], p[1], (zb + 1.0 + zt) / 2), (0.26, 0.26, zt - zb - 1.0), self.m_trim, rotz=w.a)
            else:
                self.mb.box((p[0], p[1], (zb + zt) / 2), (0.15, 0.15, zt - zb), self.m_trim, rotz=w.a)
        # porch slab
        HUe, HVe = HU, HV
        pts = [w.world(-HUe, -HVe), w.world(HUe, -HVe), w.world(HUe, HVe), w.world(-HUe, HVe)]
        z = w.floor - 0.15
        P = C.ccw([tuple(q) for q in pts])
        self.mb.prism(P, min(self.ground(*q) for q in pts) - 0.3, z, self.m_concrete)

    # ------------------------------------------------------------------ extras
    def chimney(self):
        ch = C.fval(self.f, "chimney")
        if not ch:
            return
        x, y = ch["point"]
        brick = "brick" in ch["type"]
        mat = self.m_brick if brick else self.m_siding
        w = self.owner(x, y) or self.nearest_wing(x, y)
        a = w.a
        sx, sy = (0.75, 0.75) if brick else (1.0, 0.75)
        zmax = -1e9
        for dx in np.linspace(-3, 3, 7):
            for dy in np.linspace(-3, 3, 7):
                zmax = max(zmax, self.roofz(x + dx, y + dy))
        top = max(self.roofz(x, y) + 1.0, zmax + 0.6)
        inside = self.poly.contains(Point(x, y))
        bot = w.floor if inside else self.ground(x, y) - 0.3
        self.mb.box((x, y, (bot + top) / 2), (sx, sy, top - bot), mat, rotz=a)
        self.mb.box((x, y, top + 0.04), (sx + 0.1, sy + 0.1, 0.08), self.m_dark if not brick else self.m_concrete, rotz=a)
        self.mb.tube([(x, y, top + 0.08), (x, y, top + 0.45)], 0.11, self.m_dark, sides=10)
        self.mb.box((x, y, top + 0.5), (0.34, 0.34, 0.06), self.m_dark, rotz=a)

    def plane_at(self, x, y):
        """Top wing + plane normal at (x, y)."""
        best = max(self.wings, key=lambda w: float(w.roof_z(x, y)) if w.kind != "porch" else -1e9)
        e = 0.05
        z = float(best.roof_z(x, y))
        zx = float(best.roof_z(x + e, y)) - float(best.roof_z(x - e, y))
        zy = float(best.roof_z(x, y + e)) - float(best.roof_z(x, y - e))
        n = np.array([-zx / (2 * e), -zy / (2 * e), 1.0])
        n /= np.linalg.norm(n)
        return best, z, n

    def roof_object(self, x, y, size, mat, height=0.06, rot_down=True, frame=None):
        """Box lying on the roof plane at (x, y); size = (across-slope, down-slope)."""
        w, z, n = self.plane_at(x, y)
        if not np.isfinite(z):
            return False
        h = np.array([-n[1], n[0], 0.0])
        if np.linalg.norm(h) < 1e-6:
            h = np.array([1.0, 0, 0])
        h /= np.linalg.norm(h)
        s = np.cross(n, h)
        c = np.array([x, y, z]) + n * (height / 2 + 0.01)
        hx, hy, hz = size[0] / 2, size[1] / 2, height / 2
        corners = []
        for dz in (-hz, hz):
            for (dx, dy) in ((-hx, -hy), (hx, -hy), (hx, hy), (-hx, hy)):
                corners.append(c + h * dx + s * dy + n * dz)
        idx = {"top": [4, 5, 6, 7], "s": [0, 1, 5, 4], "e": [1, 2, 6, 5], "n": [2, 3, 7, 6], "w": [3, 0, 4, 7]}
        for k, q in idx.items():
            P = [tuple(corners[i]) for i in q]
            if k == "top" and isinstance(mat, tuple):
                self.rb.poly(P, mat[0], uvs=[(0, 0), (1.0, 0), (1.0, 1.7), (0, 1.7)])
            else:
                self.rb.poly(P, mat[1] if isinstance(mat, tuple) else mat, uv_mode="plane")
        return True

    def roof_extras(self):
        V = C.fval
        for (x, y) in (V(self.f, "skylights") or []):
            self.roof_object(x, y, (0.75, 1.2), (self.m_skyl, self.m_trim), height=0.12)
        # box vents on the plane facing away from the street
        m0 = max(self.main, key=lambda w: w.L * w.W)
        for k in (-1.5, 0.0, 1.5):
            for sgn in (1, -1):
                if m0.hl >= m0.hw:
                    p = m0.world(k, sgn * 0.9)
                else:
                    p = m0.world(sgn * 0.9, k)
                sp = self.street.interpolate(self.street.project(Point(*p)))
                if np.dot(np.array([sp.x, sp.y]) - m0.c, p - m0.c) > 0:
                    continue
                self.roof_object(p[0], p[1], (0.4, 0.4), self.m_dark, height=0.14)
        sol = V(self.f, "solar")
        if sol:
            target = {"south": (0, -1), "south-west": (-0.7, -0.7)}[sol["plane"]]
            self.solar(sol["panels"], np.array(target))

    def solar(self, count, target):
        placed = 0
        m0 = max(self.main, key=lambda w: w.L * w.W)
        cands = []
        for w in self.main:
            for s in np.arange(-w.hl + 0.9, w.hl - 0.4, 1.05):
                for t in np.arange(-w.hw + 0.9, w.hw - 0.5, 1.75):
                    p = w.world(s, t)
                    ww, z, n = self.plane_at(*p)
                    if ww is not w:
                        continue
                    if np.dot(n[:2], target) < 0.5 * np.linalg.norm(n[:2]) or np.linalg.norm(n[:2]) < 0.2:
                        continue
                    ok = True
                    for (ds, dt) in ((-0.5, -0.85), (0.5, -0.85), (0.5, 0.85), (-0.5, 0.85)):
                        q = w.world(s + ds, t + dt)
                        w2, z2, n2 = self.plane_at(*q)
                        if w2 is not w or np.dot(n2, n) < 0.999:
                            ok = False
                            break
                    if ok:
                        cands.append((w, s, t, p))
        for (w, s, t, p) in cands[:count]:
            self.roof_object(p[0], p[1], (1.0, 1.7), (self.m_solar, self.m_dark), height=0.05)
            placed += 1
        self.n_solar = placed

    def stoop(self):
        fd = getattr(self, "front_door", None)
        if fd is None:
            return
        c = np.array(fd["center"])
        n = np.array(fd["normal"])
        d = np.array([-n[1], n[0]])
        z = fd["z"]
        # is a porch covering the door?
        porch = next((w for w in self.wings if w.kind == "porch" and w.contains(*(c + n * 0.8), 0.3)), None)
        g = self.ground(*(c + n * 1.5))
        drop = z - g
        land = 1.3
        wd = fd["width"] + 0.9
        if porch is None:
            P = [c - d * wd / 2 + n * 0.02, c + d * wd / 2 + n * 0.02, c + d * wd / 2 + n * land, c - d * wd / 2 + n * land]
            self.mb.prism(C.ccw([tuple(q) for q in P]), g - 0.3, z - 0.02, self.m_concrete)
            off = land
        else:
            off = porch.hw * 2 if porch.ridge == "u" else porch.hl * 2
            off = float(np.linalg.norm(np.array(porch.c) - c)) + min(porch.hl, porch.hw)
        nsteps = int(max(0, math.ceil((drop - 0.05) / 0.18)))
        rise = drop / max(1, nsteps + 1) if nsteps else 0
        for k in range(nsteps):
            zt = z - 0.02 - rise * (k + 1)
            P = [c - d * wd / 2 + n * (off + 0.3 * k), c + d * wd / 2 + n * (off + 0.3 * k),
                 c + d * wd / 2 + n * (off + 0.3 * (k + 1)), c - d * wd / 2 + n * (off + 0.3 * (k + 1))]
            self.mb.prism(C.ccw([tuple(q) for q in P]), g - 0.3, zt, self.m_concrete)
        self.stoop_end = c + n * (off + 0.3 * nsteps + 0.3)
        # porch light + house number
        lp = c + d * (fd["width"] / 2 + 0.3) + n * 0.08
        self.mb.box((lp[0], lp[1], z + 1.75), (0.16, 0.16, 0.3), self.m_light, rotz=math.atan2(d[1], d[0]))
        self.mb.box((lp[0], lp[1], z + 1.93), (0.2, 0.2, 0.05), self.m_dark, rotz=math.atan2(d[1], d[0]))
        self.light_points = [(float(lp[0] + n[0] * 0.1), float(lp[1] + n[1] * 0.1), float(z + 1.75))]
        self.number_at = (c - d * (fd["width"] / 2 + 0.45) + n * 0.03, z + 1.5, d, n)
        # hose bib + meter near a corner of the garage wall
        hb = c + d * (fd["width"] / 2 + 1.4) + n * 0.05
        self.mb.tube([(hb[0], hb[1], z + 0.1), (hb[0] + n[0] * 0.1, hb[1] + n[1] * 0.1, z + 0.1)], 0.025,
                     self.m_brass, sides=6)

    def garage_lights(self):
        for gi in self.doors_info.get("garage", [])[:1]:
            c = np.array(gi["center"])
            n = np.array(gi["normal"])
            d = np.array([-n[1], n[0]])
            garages = self.doors_info["garage"]
            span = (len(garages) * gi["width"] + (len(garages) - 1) * 0.45)
            cc = np.mean([g["center"] for g in garages], 0)
            for sg in (-1, 1):
                lp = cc + d * sg * (span / 2 + 0.35) + n * 0.08
                self.mb.box((lp[0], lp[1], gi["z"] + 2.0), (0.14, 0.14, 0.28), self.m_light, rotz=math.atan2(d[1], d[0]))
                self.light_points.append((float(lp[0] + n[0] * 0.1), float(lp[1] + n[1] * 0.1), float(gi["z"] + 2.0)))

    def house_number(self):
        if not hasattr(self, "number_at"):
            return None
        p, z, d, n = self.number_at
        cu = bpy.data.curves.new("num_%d" % self.num, "FONT")
        cu.body = str(self.num)
        cu.size = 0.13
        cu.extrude = 0.004
        cu.resolution_u = 2
        cu.bevel_depth = 0.0
        cu.align_x = "CENTER"
        ob = bpy.data.objects.new("tmpnum", cu)
        self.coll.objects.link(ob)
        ob.location = (p[0], p[1], z)
        ob.rotation_euler = (math.pi / 2, 0, math.atan2(n[1], n[0]) + math.pi / 2)
        bpy.context.view_layer.update()
        dg = bpy.context.evaluated_depsgraph_get()
        me = bpy.data.meshes.new_from_object(ob.evaluated_get(dg))
        me.transform(ob.matrix_world)
        bpy.data.objects.remove(ob)
        bpy.data.curves.remove(cu)
        nob = bpy.data.objects.new("House_%d_Number" % self.num, me)
        me.materials.append(self.m_brass)
        self.coll.objects.link(nob)
        return nob

    def deck(self):
        dk = C.fval(self.f, "deck")
        if not dk or "point" not in dk or dk.get("material") in ("concrete", "white pergola"):
            if dk and dk.get("material") == "concrete":
                self.patio(dk["point"], dk["size_m"])
            if dk and dk.get("material") == "white pergola":
                self.pergola(dk["point"], dk["size_m"])
            return None
        x, y = dk["point"]
        W = self.nearest_wing(x, y)
        sx, sy = dk["size_m"]
        # orient the long side along the nearest footprint edge (outward normal of that edge)
        fp = self.fp
        best = None
        for i in range(len(fp)):
            a, b = np.array(fp[i]), np.array(fp[(i + 1) % len(fp)])
            seg = LineString([a, b])
            dd = seg.distance(Point(x, y))
            if best is None or dd < best[0]:
                best = (dd, a, b, seg)
        _, a, b, seg = best
        dvec = (b - a) / np.linalg.norm(b - a)
        nvec = np.array([dvec[1], -dvec[0]])
        tvec = dvec
        pp = seg.interpolate(seg.project(Point(x, y)))
        base = np.array([pp.x, pp.y]) + nvec * 0.02
        z = self.floor - 0.18
        mb = C.MeshBuilder()
        corners = [base - tvec * sx / 2, base + tvec * sx / 2, base + tvec * sx / 2 + nvec * sy,
                   base - tvec * sx / 2 + nvec * sy]
        P = C.ccw([tuple(q) for q in corners])
        mb.prism(P, z - 0.2, z, self.m_deck)
        # posts
        for f in (0.0, 0.5, 1.0):
            for q in (base + tvec * sx * (f - 0.5) + nvec * (sy - 0.15),):
                g = self.ground(*q)
                if z - g > 0.3:
                    mb.box((q[0], q[1], (g + z - 0.2) / 2), (0.15, 0.15, z - 0.2 - g + 0.1), self.m_deck)
        # railing on the 3 open sides, gap for stairs
        rail_h = 0.95
        rail_mat = self.m_trim if dk.get("railing") == "white" else (self.m_dark if "black" in dk.get("railing", "")
                                                                       else self.m_deck)
        stair_t = 0.75
        segs = [(corners[1], corners[2]), (corners[2], corners[3]), (corners[3], corners[0])]
        for si, (a, b) in enumerate(segs):
            a = np.asarray(a)
            b = np.asarray(b)
            L = np.linalg.norm(b - a)
            dd = (b - a) / L
            pieces = [(0, L)]
            if si == 1:
                pieces = [(0, L * stair_t - 0.6), (L * stair_t + 0.6, L)]
            for (s0, s1) in pieces:
                if s1 - s0 < 0.2:
                    continue
                pa, pb = a + dd * s0, a + dd * s1
                mid = (pa + pb) / 2
                mb.box((mid[0], mid[1], z + rail_h), (s1 - s0, 0.09, 0.05), rail_mat, rotz=math.atan2(dd[1], dd[0]))
                mb.box((mid[0], mid[1], z + 0.12), (s1 - s0, 0.05, 0.05), rail_mat, rotz=math.atan2(dd[1], dd[0]))
                nb = int((s1 - s0) / 0.13)
                for k in range(nb + 1):
                    q = pa + dd * (s1 - s0) * k / max(1, nb)
                    thick = 0.09 if k in (0, nb) else 0.035
                    mb.box((q[0], q[1], z + rail_h / 2 + 0.05), (thick, thick, rail_h - 0.05), rail_mat)
        # stairs down from the outer edge
        a, b = np.asarray(segs[1][0]), np.asarray(segs[1][1])
        sc = a + (b - a) * stair_t
        g = self.ground(*(sc + nvec * 1.5))
        drop = z - g
        nst = max(1, int(math.ceil(drop / 0.19)))
        rise = drop / nst
        for k in range(nst):
            q = sc + nvec * (0.14 + 0.28 * k)
            zt = z - rise * (k + 1)
            mb.box((q[0], q[1], zt - 0.02), (1.1, 0.28, 0.05), self.m_deck, rotz=math.atan2(tvec[1], tvec[0]))
        for sg in (-1, 1):
            p0 = sc + tvec * sg * 0.58
            p1 = p0 + nvec * (0.28 * nst)
            mb.tube([(p0[0], p0[1], z - 0.05), (p1[0], p1[1], g + 0.05)], 0.05, self.m_deck, sides=4)
        ob = mb.emit("House_%d_Deck" % self.num, self.coll)
        C.set_extras(ob, kind="deck", address="%d Canby Ct" % self.num, walkable=True, collide=True)
        self.deck_info = dict(center=[float(c) for c in base + nvec * sy / 2], z=float(z), size=[sx, sy],
                              stairs_bottom=[float(v) for v in sc + nvec * (0.28 * nst + 0.3)])
        pat = dk.get("patio_point")
        if pat:
            self.patio(pat, (4.5, 3.6))
        return ob

    def patio(self, pt, size):
        x, y = pt
        W = self.nearest_wing(x, y)
        g = self.ground(x, y)
        pts = [W.world(0, 0)]
        hU, hV = size[0] / 2, size[1] / 2
        c = np.array([x, y])
        P = [c - W.U * hU - W.V * hV, c + W.U * hU - W.V * hV, c + W.U * hU + W.V * hV, c - W.U * hU + W.V * hV]
        mb = C.MeshBuilder()
        mb.prism(C.ccw([tuple(q) for q in P]), g - 0.25, g + 0.06, self.m_concrete)
        ob = mb.emit("House_%d_Patio" % self.num, self.coll)
        C.set_extras(ob, kind="patio", address="%d Canby Ct" % self.num, walkable=True)
        self.patio_info = dict(center=[float(x), float(y)], z=float(g + 0.06))

    def pergola(self, pt, size):
        x, y = pt
        W = self.nearest_wing(x, y)
        g = self.ground(x, y)
        mb = C.MeshBuilder()
        c = np.array([x, y])
        hU, hV = size[0] / 2, size[1] / 2
        white = MAT.M("WHITEWOOD", lambda: MAT.flat_mat("WOOD_white", "#efeee8", rough=0.6))
        for su in (-1, 1):
            for sv in (-1, 1):
                q = c + W.U * su * hU + W.V * sv * hV
                mb.box((q[0], q[1], g + 1.2), (0.14, 0.14, 2.4), white, rotz=W.a)
        for k in np.linspace(-hU, hU, 9):
            q = c + W.U * k
            mb.box((q[0], q[1], g + 2.45), (0.05, 2 * hV + 0.6, 0.15), white, rotz=W.a)
        for sv in (-1, 1):
            q = c + W.V * sv * hV
            mb.box((q[0], q[1], g + 2.3), (2 * hU + 0.5, 0.1, 0.2), white, rotz=W.a)
        ob = mb.emit("House_%d_Pergola" % self.num, self.coll)
        C.set_extras(ob, kind="pergola", address="%d Canby Ct" % self.num, collide=True)

    # ------------------------------------------------------------------ build
    def build_web_simple(self, coll):
        """Lighter copy of walls+roof for the web GLB (simple windows, no gutters/downspouts)."""
        keep = (self.mb, self.rb, self.coll, getattr(self, "front_door", None), self.doors_info, self.light_points)
        self.mb, self.rb, self.coll = C.MeshBuilder(), C.MeshBuilder(), coll
        self.doors_info = {}
        self.simple = True
        self._gut = self.gutter
        self.gutter = lambda *a, **k: None
        self.build_walls()
        self.build_upper_walls()
        self.build_roofs()
        self.chimney()
        self.stoop()
        self.garage_lights()
        addr = "%d Canby Ct" % self.num
        body = self.mb.emit("House_%d_web" % self.num, coll)
        C.set_extras(body, kind="house", address=addr, collide=True, walkable=False, part="walls",
                     storeys=float(self.h["assessor"]["floors"]), year_built=int(self.h["assessor"]["year_built"]),
                     floor_z=round(self.floor, 2), heights="inferred", footprint="measured (City GIS)")
        roof = self.rb.emit("House_%d_Roof_web" % self.num, coll)
        C.set_extras(roof, kind="roof", address=addr, collide=True, part="roof")
        self.simple = False
        self.gutter = self._gut
        (self.mb, self.rb, self.coll, fd, self.doors_info, self.light_points) = keep
        if fd is not None:
            self.front_door = fd
        return body, roof

    def build(self):
        self.light_points = []
        self.build_walls()
        self.build_upper_walls()
        self.build_roofs()
        self.chimney()
        self.roof_extras()
        self.stoop()
        self.garage_lights()
        addr = "%d Canby Ct" % self.num
        body = self.mb.emit("House_%d" % self.num, self.coll)
        C.set_extras(body, kind="house", address=addr, collide=True, walkable=False, part="walls",
                     storeys=float(self.h["assessor"]["floors"]), year_built=int(self.h["assessor"]["year_built"]),
                     floor_z=round(self.floor, 2), heights="inferred", footprint="measured (City GIS)")
        roof = self.rb.emit("House_%d_Roof" % self.num, self.coll)
        C.set_extras(roof, kind="roof", address=addr, collide=True, part="roof")
        num = self.house_number()
        if num:
            C.set_extras(num, kind="house_number", address=addr)
        self.deck()
        return body, roof

    def snow_cover(self, coll, mat, depth=0.2):
        """Winter: snow slabs on every roof wing (pillowy, bevelled), returns object."""
        sb = C.MeshBuilder()
        for w in self.wings:
            if w.p > 1.2:       # too steep to hold much snow
                continue
            dep = depth * (1.0 if w.p < 0.6 else 0.7)
            faces, loop, eaves, caps = w.top_faces(lift=dep, grow=0.04)
            W3 = lambda q: w.P3(q[0], q[1], q[2])
            for f in faces:
                P = [W3(q) for q in f]
                sb.poly(P, mat, uv_mode="xy")
            L = [W3(q) for q in loop]
            for i in range(len(L)):
                a, b = L[i], L[(i + 1) % len(L)]
                q = [a, b, (b[0], b[1], b[2] - dep - 0.02), (a[0], a[1], a[2] - dep - 0.02)]
                nrm = np.cross(np.subtract(q[1], q[0]), np.subtract(q[3], q[0]))
                sb.poly(q[::-1] if self._outward(w, q, nrm) else q, mat, uv_mode="plane")
        ob = sb.emit("Snow_Roof_%d" % self.num, coll)
        bev = ob.modifiers.new("soft", "BEVEL")
        bev.width = 0.07
        bev.segments = 3
        bev.limit_method = "ANGLE"
        ob.data.polygons.foreach_set("use_smooth", np.ones(len(ob.data.polygons), bool))
        C.set_extras(ob, kind="snow", address="%d Canby Ct" % self.num, season="winter", collide=False)
        return ob


def build_all(coll, only=None):
    out = {}
    for h in C.data("houses")["houses"]:
        n = h["number"]
        if only and n not in only:
            continue
        hb = HouseBuilder(n, coll)
        hb.build()
        out[n] = hb
        print("  house", n, "faces", len(hb.mb) + len(hb.rb), flush=True)
    return out


# ============================================================================ context buildings
CTX_BODY = ["#8f9488", "#b8ad97", "#7d8a8f", "#a39a8a", "#c9c3b4", "#6f6a60", "#9aa39a", "#b5a58c", "#7a6d5f",
            "#d0ccc0", "#5f6a6c", "#a8a294"]
CTX_TRIM = ["#efeee8", "#e8e2d4", "#f3f2ee", "#3f3f3c"]
CTX_ROOF = ["#6c6f70", "#5e605f", "#7d7a73", "#6a5f55", "#7a7e7f", "#55595b", "#857f75"]
CTX_SID = ["siding_lap_wood", "siding_lap_wood", "siding_t111", "siding_shingle_cedar", "siding_lap_fibercement",
           "siding_board_batten"]


class ContextHouse(HouseBuilder):
    """Neighbouring buildings (context_buildings.json): measured footprints + City floors; wings from the
    automatic rectangle decomposition, hip (70 %) or gable roofs, palette colours, windows, no doors (simpler)."""

    def __init__(self, rec, idx, coll, matsets):
        from footprint_rects import decompose, dominant_angles
        self.num = 100000 + idx
        self.rec = rec
        self.coll = coll
        self.rng = C.rng_for("ctx", rec.get("address", idx))
        fp = C.ccw(rec["footprint_local"])
        self.fp = fp
        self.poly = Polygon(fp).buffer(0)
        self.dtm = C.dtm()
        P = np.array(fp)
        gz = self.dtm.sample(P[:, 0], P[:, 1])
        self.floor = max(float(np.median(gz)) + 0.4, float(gz.max()) - 0.25)
        self.c = np.array(self.poly.centroid.coords[0])
        angs = dominant_angles(fp, 1)
        rects, cov = decompose(fp, angs, min_side=2.5, max_rects=4)
        if not rects:
            r = self.poly.minimum_rotated_rectangle
            rects = []
        fl = rec.get("floors") or 1
        st = 2 if fl >= 2 else (1.5 if fl >= 1.5 else 1)
        gable = self.rng.random() < 0.3
        wings = []
        for i, r in enumerate(rects):
            L, W = r["L"], r["W"]
            ridge = "u" if L >= W else "v"
            wings.append(dict(world=(r["c"][0], r["c"][1], r["a"], L, W), roof="gable" if gable else "hip",
                              ridge=ridge, st=st if i == 0 else (st if self.rng.random() < 0.6 else 1)))
        self.spec = dict(frame=angs[0] if angs else 0, pitch=6, wings=wings)
        self.wings = [Wing(w, self.c, self.spec["frame"], 6, self.floor, i, self.num) for i, w in enumerate(wings)]
        self.main = [w for w in self.wings if w.kind == "main"]
        ms = matsets[int(self.rng.integers(len(matsets)))]
        (self.m_siding, self.m_trim, self.m_roof, self.m_ridge, self.m_gutter, self.m_gdoor, self.m_frame) = ms
        self.m_siding2 = None
        self.m_wainscot = None
        self.m_soffit = self.m_trim
        self.m_found = MAT.M("FOUND", lambda: MAT.tex_mat("FOUNDATION", "concrete_plain", tint="#9a978f"))
        self.m_glass = MAT.glass_mat("GLASS_window")
        self.m_glass_lit = MAT.glass_mat("GLASS_window_lit", lit=True)
        self.m_concrete = MAT.M("CONC", lambda: MAT.tex_mat("CONCRETE_plain", "concrete_plain"))
        self.m_dark = MAT.M("DARKMETAL", lambda: MAT.flat_mat("METAL_dark", "#2a2a2a", rough=0.4, metal=0.6))
        self.f = {"windows": {"value": {"type": "white vinyl slider", "frame_hex": "#f1f1ec", "grilles": False}},
                  "siding": {"value": {}}}
        self.mb = C.MeshBuilder()
        self.rb = C.MeshBuilder()
        self.simple = True
        self.door_edges = {}
        self.plan = []
        self.doors_info = {}
        self.light_points = []
        self.street = LineString(C.data("boundary")["canby_ct_centerline_local"]["coordinates"])

    def gutter(self, w, p, q):
        return

    def build(self):
        if not self.wings:
            return None
        self.build_walls()
        self.build_upper_walls()
        for w in self.wings:
            self.roof_wing(w)
            if w.roof == "gable":
                self.gable_ends(w)
        mb = self.mb
        # merge roof into the same object (context = fewer objects)
        off = len(mb.v)
        mb.v.extend(self.rb.v)
        for f, mi in zip(self.rb.f, self.rb.mi):
            mb.f.append([i + off for i in f])
            mb.mi.append(mb.mat(self.rb.mats[mi]))
        mb.uv.extend(self.rb.uv)
        mb.smooth.extend(self.rb.smooth)
        addr = self.rec.get("address") or "context"
        ob = mb.emit("Context_%03d" % (self.num - 100000), self.coll)
        C.set_extras(ob, kind="context_building", address=addr, collide=True, floors=float(self.rec.get("floors") or 1),
                     heights="inferred", footprint="measured (City GIS)")
        return ob


def context_matsets(n=8):
    rng = C.rng_for("ctxmats")
    sets = []
    for i in range(n):
        body = CTX_BODY[i % len(CTX_BODY)]
        trim = CTX_TRIM[int(rng.integers(len(CTX_TRIM)))]
        roof = CTX_ROOF[int(rng.integers(len(CTX_ROOF)))]
        sid = CTX_SID[int(rng.integers(len(CTX_SID)))]
        sets.append((MAT.tex_mat("CTX_SID_%d" % i, sid, tint=body), MAT.tex_mat("CTX_TRIM_%d" % i, "trim_paint", tint=trim),
                     MAT.tex_mat("CTX_ROOF_%d" % i, "roof_arch_shingle", tint=roof),
                     MAT.tex_mat("CTX_RIDGE_%d" % i, "roof_ridge_cap", tint=roof),
                     MAT.flat_mat("CTX_GUT_%d" % i, trim, rough=0.35, metal=0.3),
                     MAT.tex_mat("CTX_GDOOR_%d" % i, "garage_door_panel", tint=trim),
                     MAT.flat_mat("WINFRAME_f1f1ec", "#f1f1ec", rough=0.45)))
    return sets


def build_context(coll):
    from shapely.geometry import box as sbox
    ctx = sbox(-210, -160, 110, 110)
    canby = unary_union_fps()
    sets = context_matsets()
    out = []
    for i, rec in enumerate(C.data("context")["buildings"]):
        p = Polygon(rec["footprint_local"]).buffer(0)
        if not ctx.contains(p.centroid) or p.area < 12:
            continue
        if canby.intersects(p.buffer(-0.5)):
            continue
        try:
            ch = ContextHouse(rec, i, coll, sets)
            ob = ch.build()
            if ob is not None:
                out.append(ob)
        except Exception as ex:
            print("   context building", i, "failed:", ex)
    print("  context buildings", len(out))
    return out


def unary_union_fps():
    from shapely.ops import unary_union
    return unary_union([Polygon(h["footprint_local"]["value"]).buffer(0) for h in C.data("houses")["houses"]])
