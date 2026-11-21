"""Props: parked cars (generic, no brands), mailboxes, fences, street lights, hydrants, yard features observed
on the orthos (play structure, garden shed, raised beds, gazebo, trampolines, boat, trailer, sport court),
patio furniture, and the ARTISTIC winter sledding features from data/game/jumps.json (3 kickers + run-out berm
with hay bales) + packed sled tracks along the measured run.
"""
import math

import bpy
import numpy as np
import shapely
from shapely.geometry import LineString, Point, Polygon, box, shape
from shapely.ops import unary_union

import cc_common as C
import materials as MAT
import ground as G


def z(x, y):
    return float(C.dtm().sample(x, y))


def _m():
    m = {}
    m["black"] = MAT.M("P_black", lambda: MAT.flat_mat("PAINT_black", "#1b1b1c", rough=0.35, metal=0.2))
    m["galv"] = MAT.M("P_galv", lambda: MAT.flat_mat("METAL_galv", "#9a9c9e", rough=0.4, metal=0.9))
    m["tyre"] = MAT.M("P_tyre", lambda: MAT.flat_mat("RUBBER_tyre", "#161616", rough=0.8))
    m["rim"] = MAT.M("P_rim", lambda: MAT.flat_mat("METAL_rim", "#8e9194", rough=0.3, metal=1.0))
    m["cglass"] = MAT.M("P_cglass", lambda: MAT.flat_mat("GLASS_car", "#0c0f12", rough=0.04, coat=1.0, spec=0.8))
    m["tail"] = MAT.M("P_tail", lambda: MAT.flat_mat("LAMP_tail", "#7a0d0d", rough=0.2))
    m["head"] = MAT.M("P_head", lambda: MAT.flat_mat("LAMP_head", "#d8dcdc", rough=0.1, metal=0.3))
    m["trimblack"] = MAT.M("P_tb", lambda: MAT.flat_mat("PLASTIC_black", "#202022", rough=0.6))
    m["fence"] = MAT.M("P_fence", lambda: MAT.tex_mat("FENCE_cedar", "fence_cedar"))
    m["wood"] = MAT.M("P_wood", lambda: MAT.tex_mat("WOOD_stained", "wood_deck", tint="#b88d6c"))
    m["yellow"] = MAT.M("P_yel", lambda: MAT.flat_mat("PAINT_hydrant", "#d9b21c", rough=0.45))
    m["red"] = MAT.M("P_red", lambda: MAT.flat_mat("PAINT_red", "#9c2a22", rough=0.5))
    m["green"] = MAT.M("P_grn", lambda: MAT.flat_mat("PAINT_court", "#3f6b4c", rough=0.7))
    m["white"] = MAT.M("P_wht", lambda: MAT.flat_mat("PAINT_white", "#ecebe6", rough=0.5))
    m["blue"] = MAT.M("P_blue", lambda: MAT.flat_mat("TARP_blue", "#2c5a9c", rough=0.6))
    m["straw"] = MAT.M("P_straw", lambda: MAT.flat_mat("STRAW_bale", "#c9a65a", rough=0.95))
    m["shingle"] = MAT.M("P_sh", lambda: MAT.tex_mat("ROOF_shed", "roof_arch_shingle", tint="#6e7276"))
    m["shingle_br"] = MAT.M("P_shb", lambda: MAT.tex_mat("ROOF_gazebo", "roof_arch_shingle", tint="#6a5444"))
    m["siding_shed"] = MAT.M("P_ss", lambda: MAT.tex_mat("SID_shed", "siding_t111", tint="#8a8f86"))
    m["soil"] = MAT.M("P_soil", lambda: MAT.tex_mat("SOIL_bed", "bark_mulch", tint="#5a4a40"))
    m["snowp"] = MAT.M("SNOWP", lambda: MAT.tex_mat("SNOW_packed", "snow_packed"))
    m["light"] = MAT.M("P_lamp", lambda: MAT.flat_mat("LIGHT_street", "#fff6e0", rough=0.2, emit="#ffd9a0",
                                                     emit_strength=0.0))
    m["mesh"] = MAT.M("P_mesh", lambda: MAT.flat_mat("NET_tramp", "#151515", rough=0.7, alpha=0.6))
    return m


# ============================================================================ cars
CAR_TYPES = {
    "sedan": dict(L=4.75, W=1.83, h_body=0.78, h_roof=1.44, hood=1.1, trunk=0.95, cab_in=0.12, r=0.33),
    "suv": dict(L=4.85, W=1.9, h_body=0.98, h_roof=1.74, hood=1.0, trunk=0.25, cab_in=0.08, r=0.37),
    "wagon": dict(L=4.6, W=1.8, h_body=0.82, h_roof=1.55, hood=1.0, trunk=0.2, cab_in=0.1, r=0.33),
    "pickup": dict(L=5.6, W=2.0, h_body=1.05, h_roof=1.88, hood=1.3, trunk=1.9, cab_in=0.06, r=0.39),
}


def car(name, x, y, heading_deg, kind, colour, coll, M, snow=None):
    t = CAR_TYPES[kind]
    body = MAT.M("CAR_" + colour, lambda: MAT.flat_mat("CARPAINT_" + colour.lstrip("#"), colour, rough=0.22,
                                                       metal=0.6, coat=1.0))
    mb = C.MeshBuilder()
    L, W = t["L"], t["W"]
    gz = 0.0
    zb0 = 0.32
    # lower body: lofted rounded box in local coords (x fwd, y left)
    secs = [(-L / 2, zb0 + 0.12, t["h_body"] - 0.08), (-L / 2 + 0.15, zb0, t["h_body"]), (L / 2 - 0.2, zb0, t["h_body"] - 0.04),
            (L / 2, zb0 + 0.12, t["h_body"] - 0.18)]
    rings = []
    for (sx, z0, z1) in secs:
        w2 = W / 2 * (0.94 if sx in (-L / 2, L / 2) else 1.0)
        ring = [(sx, -w2, z0), (sx, w2, z0), (sx, w2 * 0.98, z1), (sx, -w2 * 0.98, z1)]
        rings.append(mb.add_verts(ring))
    for i in range(len(rings) - 1):
        for k in range(4):
            a, b = rings[i][k], rings[i][(k + 1) % 4]
            c, d = rings[i + 1][(k + 1) % 4], rings[i + 1][k]
            mb.face([a, d, c, b], [(0, 0)] * 4, body)
    mb.face(rings[0], [(0, 0)] * 4, body)
    mb.face(rings[-1][::-1], [(0, 0)] * 4, body)
    # cabin / greenhouse
    x0 = -L / 2 + t["trunk"]
    x1 = L / 2 - t["hood"]
    if kind == "pickup":
        x0 = x1 - 1.9
    zc0, zc1 = t["h_body"] - 0.02, t["h_roof"]
    ci = t["cab_in"]
    rake = 0.55 if kind in ("sedan",) else 0.35
    bot = [(x0, -W / 2 + ci * 0.5, zc0), (x1, -W / 2 + ci * 0.5, zc0), (x1, W / 2 - ci * 0.5, zc0), (x0, W / 2 - ci * 0.5, zc0)]
    top = [(x0 + rake * (0.9 if kind == "sedan" else 0.25), -W / 2 + ci + 0.08, zc1),
           (x1 - rake, -W / 2 + ci + 0.08, zc1), (x1 - rake, W / 2 - ci - 0.08, zc1),
           (x0 + rake * (0.9 if kind == "sedan" else 0.25), W / 2 - ci - 0.08, zc1)]
    B = mb.add_verts(bot)
    T = mb.add_verts(top)
    for k in range(4):
        mb.face([B[k], B[(k + 1) % 4], T[(k + 1) % 4], T[k]], [(0, 0)] * 4, M["cglass"])
    mb.face(T, [(0, 0)] * 4, body)
    # pillars (B pillar)
    xm = (x0 + x1) / 2
    for sg in (-1, 1):
        mb.box((xm, sg * (W / 2 - ci * 0.6), (zc0 + zc1) / 2), (0.1, 0.05, zc1 - zc0), body)
        mb.box((x1 - 0.1, sg * (W / 2 + 0.06), zc0 + 0.1), (0.12, 0.14, 0.1), M["trimblack"])     # mirrors
    if kind == "pickup":
        mb.box((-L / 2 + 0.95, 0, t["h_body"] + 0.02), (1.8, W - 0.12, 0.04), M["trimblack"])
    # wheels
    wb = L * 0.3
    for sx in (-wb, wb * 1.05):
        for sg in (-1, 1):
            cy = sg * (W / 2 - 0.12)
            pts = [(sx, cy - 0.12, t["r"]), (sx, cy + 0.12, t["r"])]
            mb.tube(pts, t["r"], M["tyre"], sides=14, cap=True)
            mb.tube([(sx, cy + sg * 0.121, t["r"]), (sx, cy + sg * 0.125, t["r"])], t["r"] * 0.62, M["rim"], sides=14,
                    cap=True)
    # lights + grille + bumpers
    for sg in (-1, 1):
        mb.box((L / 2 - 0.02, sg * (W / 2 - 0.25), t["h_body"] - 0.25), (0.06, 0.38, 0.12), M["head"])
        mb.box((-L / 2 + 0.02, sg * (W / 2 - 0.2), t["h_body"] - 0.2), (0.06, 0.3, 0.12), M["tail"])
    mb.box((L / 2 + 0.01, 0, 0.5), (0.08, W * 0.92, 0.18), M["trimblack"])
    mb.box((-L / 2 - 0.01, 0, 0.5), (0.08, W * 0.92, 0.18), M["trimblack"])
    # transform to world
    a = math.radians(heading_deg)
    ca, sa = math.cos(a), math.sin(a)
    gz = z(x, y)
    V = np.array(mb.v)
    Xw = x + V[:, 0] * ca - V[:, 1] * sa
    Yw = y + V[:, 0] * sa + V[:, 1] * ca
    mb.v = [tuple(p) for p in np.column_stack([Xw, Yw, V[:, 2] + gz])]
    ob = mb.emit(name, coll)
    bev = ob.modifiers.new("soft", "BEVEL")
    bev.width = 0.03
    bev.segments = 2
    bev.limit_method = "ANGLE"
    C.set_extras(ob, kind="car", collide=True, generic=True, artistic=True,
                 note="generic car (no brand); position observed on 2022/2024 orthos")
    out = [ob]
    if snow is not None:
        sb = C.MeshBuilder()
        # pillows of snow on roof, hood, trunk
        for (cx, cz, lx, wy, th) in (((x0 + x1) / 2, zc1, (x1 - x0) - 2 * rake * 0.6, W - 2 * ci - 0.25, 0.14),
                                     ((x1 + L / 2) / 2, t["h_body"], L / 2 - x1 - 0.15, W - 0.2, 0.09),
                                     ((-L / 2 + x0) / 2, t["h_body"], max(0.3, x0 + L / 2 - 0.15), W - 0.2, 0.09)):
            if kind == "pickup" and cx < x0:
                continue
            sb.box((cx, 0, cz + th / 2), (lx, wy, th), snow)
        V = np.array(sb.v)
        Xw = x + V[:, 0] * ca - V[:, 1] * sa
        Yw = y + V[:, 0] * sa + V[:, 1] * ca
        sb.v = [tuple(p) for p in np.column_stack([Xw, Yw, V[:, 2] + gz])]
        so = sb.emit(name + "_Snow", coll)
        sub = so.modifiers.new("soft", "SUBSURF")
        sub.levels = 2
        sub.render_levels = 2
        so.data.polygons.foreach_set("use_smooth", np.ones(len(so.data.polygons), bool))
        C.set_extras(so, kind="snow", season="winter", collide=False)
        out.append(so)
    return out


CARS = [
    # observed parked-car positions (2022 City ortho, analysis only); colours/types generic
    ("Car_3905_a", 16.6, -0.5, 92, "suv", "#d9dadb"),
    ("Car_3905_b", 19.3, -1.2, 95, "sedan", "#2a2c30"),
    ("Car_3813_a", -32.0, -9.8, 95, "sedan", "#e3e4e2"),
    ("Car_3813_b", -36.0, -10.5, 88, "pickup", "#23262a"),
    ("Car_3807_a", -69.0, -9.0, 80, "suv", "#24382f"),
    ("Car_3806_a", -62.5, -37.5, 270, "wagon", "#8a8d90"),
    ("Car_bulb", -27.5, -18.0, 175, "sedan", "#e6e6e4"),
    ("Car_3909_a", 3.0, -33.0, 300, "pickup", "#5a5d61"),
]


def cars(coll, M, snow=None):
    out = []
    for (n, x, y, h, k, c) in CARS:
        out += car(n, x, y, h, k, c, coll, M, snow)
    return out


# ============================================================================ street furniture
def mailboxes(coll, M, drives):
    mb = C.MeshBuilder()
    st = G.street_poly()
    for d in drives:
        t = np.array(d["t_street"])
        b = st.boundary
        s = b.project(Point(*t))
        p1 = b.interpolate(s + d["width"] / 2 + 1.0)
        p0 = b.interpolate(s + d["width"] / 2 + 0.9)
        tan = np.array([p1.x - p0.x, p1.y - p0.y])
        tan /= np.linalg.norm(tan) + 1e-9
        nrm = np.array([-tan[1], tan[0]])
        q = np.array([p1.x, p1.y])
        if st.contains(Point(*(q + nrm * 0.5))):
            nrm = -nrm
        q = q + nrm * 0.35
        g = z(*q)
        a = math.atan2(tan[1], tan[0])
        mb.box((q[0], q[1], g + 0.55), (0.09, 0.09, 1.2), M["wood"], rotz=a)
        mb.box((q[0] - nrm[0] * 0.05, q[1] - nrm[1] * 0.05, g + 1.08), (0.24, 0.5, 0.06), M["wood"], rotz=a)
        mb.box((q[0], q[1], g + 1.21), (0.2, 0.48, 0.2), M["black"], rotz=a)
        mb.tube([(q[0] - tan[0] * 0.1, q[1] - tan[1] * 0.1, g + 1.21), (q[0] + tan[0] * 0.1, q[1] + tan[1] * 0.1,
                                                                        g + 1.21)], 0.1, M["black"], sides=10)
        mb.box((q[0] + tan[0] * 0.12, q[1] + tan[1] * 0.12, g + 1.3), (0.02, 0.15, 0.05), M["red"], rotz=a)
    ob = mb.emit("Mailboxes", coll)
    C.set_extras(ob, kind="mailbox", collide=True, artistic=True, note="inferred: individual post mailboxes")
    return ob


def street_lights_hydrants(coll, M):
    mb = C.MeshBuilder()
    ctx = box(*G.CTX)
    lights = []
    for f in C.jload(C.RAW, "city", "streetlights.geojson")["features"]:
        g = G._to_local_geom(shape(f["geometry"]))
        if not ctx.contains(g):
            continue
        gz = z(g.x, g.y)
        st = G.street_poly()
        bp = st.boundary.interpolate(st.boundary.project(g))
        a = math.atan2(bp.y - g.y, bp.x - g.x)
        if (f["properties"].get("FixtureType") or "").lower().startswith("cobra"):
            H = 7.6
            mb.tube([(g.x, g.y, gz - 0.3), (g.x, g.y, gz + H)], 0.09, M["galv"], sides=8, r_end=0.06)
            ex, ey = g.x + math.cos(a) * 1.6, g.y + math.sin(a) * 1.6
            mb.tube([(g.x, g.y, gz + H - 0.2), (ex, ey, gz + H + 0.1)], 0.04, M["galv"], sides=6)
            mb.box((ex, ey, gz + H + 0.05), (0.7, 0.3, 0.14), M["galv"], rotz=a)
            mb.box((ex, ey, gz + H - 0.03), (0.5, 0.22, 0.03), M["light"], rotz=a)
            lights.append((ex, ey, gz + H - 0.1))
        else:
            H = 4.3
            mb.tube([(g.x, g.y, gz - 0.3), (g.x, g.y, gz + H)], 0.08, M["black"], sides=8, r_end=0.05)
            mb.tube([(g.x, g.y, gz + H), (g.x, g.y, gz + H + 0.55)], 0.2, M["light"], sides=10, r_end=0.12)
            mb.box((g.x, g.y, gz + H + 0.62), (0.32, 0.32, 0.08), M["black"])
            lights.append((g.x, g.y, gz + H + 0.3))
    for f in C.jload(C.RAW, "city", "hydrants.geojson")["features"]:
        g = G._to_local_geom(shape(f["geometry"]))
        if not ctx.contains(g):
            continue
        gz = z(g.x, g.y)
        mb.tube([(g.x, g.y, gz - 0.1), (g.x, g.y, gz + 0.62)], 0.11, M["yellow"], sides=12)
        mb.tube([(g.x, g.y, gz + 0.62), (g.x, g.y, gz + 0.78)], 0.09, M["yellow"], sides=12, r_end=0.03)
        mb.tube([(g.x - 0.18, g.y, gz + 0.45), (g.x + 0.18, g.y, gz + 0.45)], 0.05, M["yellow"], sides=8)
        mb.tube([(g.x, g.y, gz + 0.45), (g.x, g.y - 0.2, gz + 0.45)], 0.07, M["yellow"], sides=8)
    ob = mb.emit("Street_Furniture", coll)
    C.set_extras(ob, kind="street_furniture", collide=True, note="positions from City street-light / hydrant layers")
    return ob, lights


# ============================================================================ fences
def fences(coll, M, hbs):
    """Inferred 1.8 m cedar board fences on rear/side parcel lines (>14 m from the street centreline and not
    where a hedge row already screens the line)."""
    parcels = C.data("boundary")["parcels_local"]
    cl = LineString(C.data("boundary")["canby_ct_centerline_local"]["coordinates"])
    st = G.street_poly()
    hed = unary_union([LineString(h["points"]).buffer(2.0) for h in C.data("trees")["hedges"]])
    # 3905's large open lawns N and W (observed: no fences, low hedge only) + its east side (tall hedge)
    open_lawn = shape(parcels["3905"]).buffer(1.5)
    seen = []
    mb = C.MeshBuilder()
    segs = []
    for key, pg in parcels.items():
        ring = np.asarray(pg["coordinates"][0])
        for a, b in zip(ring[:-1], ring[1:]):
            line = LineString([a, b])
            if line.length < 1:
                continue
            pts, s = C.resample_line([a, b], 0.5)
            keep = []
            for p in pts:
                P = Point(*p)
                ok = cl.distance(P) > 14 and st.distance(P) > 18 and not hed.contains(P) and not open_lawn.contains(P)
                ok = ok and not any(Polygon(hb.fp).buffer(1.0).contains(P) for hb in hbs.values())
                keep.append(ok)
            i = 0
            while i < len(pts):
                if not keep[i]:
                    i += 1
                    continue
                j = i
                while j < len(pts) and keep[j]:
                    j += 1
                if j - i >= 4:
                    seg = (tuple(pts[i]), tuple(pts[j - 1]))
                    mid = (np.array(seg[0]) + np.array(seg[1])) / 2
                    if not any(np.linalg.norm(mid - m) < 1.0 for m in seen):
                        seen.append(mid)
                        segs.append(seg)
                i = j
    for (a, b) in segs:
        pts, s = C.resample_line([a, b], 2.4)
        d = np.array(b) - np.array(a)
        L = np.linalg.norm(d)
        d /= L
        n = np.array([-d[1], d[0]])
        prev = None
        for i, p in enumerate(pts):
            g = z(*p)
            mb.box((p[0], p[1], g + 0.9), (0.09, 0.09, 1.9), M["wood"], rotz=math.atan2(d[1], d[0]))
            if prev is not None:
                pa, ga = prev
                q = [(pa[0] + n[0] * 0.05, pa[1] + n[1] * 0.05, ga + 0.05), (p[0] + n[0] * 0.05, p[1] + n[1] * 0.05, g + 0.05),
                     (p[0] + n[0] * 0.05, p[1] + n[1] * 0.05, g + 1.83), (pa[0] + n[0] * 0.05, pa[1] + n[1] * 0.05, ga + 1.83)]
                u0 = float(np.dot(pa, d))
                uv = [(u0, 0.05), (u0 + 2.4, 0.05), (u0 + 2.4, 1.83), (u0, 1.83)]
                mb.poly(q, M["fence"], uvs=uv)
                mb.poly(q[::-1], M["fence"], uvs=uv[::-1])
                # top cap rail
                mid = (np.array(pa) + np.array(p)) / 2
                mb.box((mid[0] + n[0] * 0.05, mid[1] + n[1] * 0.05, (ga + g) / 2 + 1.86),
                       (float(np.linalg.norm(np.array(p) - np.array(pa))), 0.14, 0.04), M["wood"],
                       rotz=math.atan2(d[1], d[0]))
            prev = (p, g)
    ob = mb.emit("Fences", coll)
    C.set_extras(ob, kind="fence", collide=True, artistic=True,
                 note="INFERRED 6 ft cedar fences on rear/side parcel lines (no evidence of type/height)")
    return ob


# ============================================================================ yard features
def yard_features(coll, M):
    out = []
    mb = C.MeshBuilder()
    # 3905 play structure (red roof) + swing set at about (-12, 20)
    x, y = -12.0, 20.0
    g = z(x, y)
    for (dx, dy) in ((-0.8, -0.8), (0.8, -0.8), (0.8, 0.8), (-0.8, 0.8)):
        mb.box((x + dx, y + dy, g + 1.4), (0.1, 0.1, 2.8), M["wood"])
    mb.box((x, y, g + 1.5), (1.8, 1.8, 0.08), M["wood"])
    mb.prism([(x - 1.0, y - 1.0), (x + 1.0, y - 1.0), (x + 1.0, y + 1.0), (x - 1.0, y + 1.0)], g + 2.8, g + 2.85,
             M["wood"])
    rb = [(x - 1.05, y - 1.1, g + 2.85), (x + 1.05, y - 1.1, g + 2.85), (x + 1.05, y, g + 3.5), (x - 1.05, y, g + 3.5)]
    mb.poly(rb, M["red"], uv_mode="plane")
    mb.poly([(x + 1.05, y + 1.1, g + 2.85), (x - 1.05, y + 1.1, g + 2.85), (x - 1.05, y, g + 3.5), (x + 1.05, y, g + 3.5)],
            M["red"], uv_mode="plane")
    # slide
    mb.poly([(x + 0.9, y - 0.3, g + 1.5), (x + 0.9, y + 0.3, g + 1.5), (x + 3.2, y + 0.3, g + 0.3), (x + 3.2, y - 0.3, g + 0.3)],
            M["green"], uv_mode="plane")
    # swing beam
    sx0, sx1 = x - 4.2, x - 1.2
    for xx in (sx0, sx1):
        for sg in (-1, 1):
            mb.tube([(xx, y + sg * 0.9, g - 0.1), (xx, y, g + 2.4)], 0.06, M["wood"], sides=6)
    mb.tube([(sx0 - 0.2, y, g + 2.4), (sx1 + 0.2, y, g + 2.4)], 0.07, M["wood"], sides=6)
    for xx in (sx0 + 0.8, sx1 - 0.8):
        for sg in (-0.2, 0.2):
            mb.tube([(xx + sg, y, g + 2.35), (xx + sg, y, g + 0.5)], 0.008, M["black"], sides=4)
        mb.box((xx, y, g + 0.48), (0.5, 0.18, 0.03), M["black"])
    ob = mb.emit("Yard_3905_PlayStructure", coll)
    C.set_extras(ob, kind="play_structure", address="3905 Canby Ct", collide=True, note="observed (orthos)")
    out.append(ob)
    # 3905 garden shed ~5 x 4 m at (14, 25), grey roof
    mb = C.MeshBuilder()
    x, y = 14.0, 25.0
    g = z(x, y)
    P = [(x - 2.5, y - 2.0), (x + 2.5, y - 2.0), (x + 2.5, y + 2.0), (x - 2.5, y + 2.0)]
    mb.prism(P, g - 0.3, g + 2.3, M["siding_shed"], cap_top=False)
    for sg in (-1, 1):
        mb.poly([(x - 2.8, y + sg * 2.3, g + 2.2), (x + 2.8, y + sg * 2.3, g + 2.2), (x + 2.8, y, g + 3.2), (x - 2.8, y, g + 3.2)][::(1 if sg < 0 else -1)],
                M["shingle"], uv_mode="plane")
    for sx in (-2.5, 2.5):
        mb.poly([(x + sx, y - 2.0, g + 2.3), (x + sx, y + 2.0, g + 2.3), (x + sx, y, g + 3.1)][::(1 if sx > 0 else -1)],
                M["siding_shed"], uv_mode="wall")
    mb.box((x, y - 2.02, g + 1.0), (1.6, 0.04, 2.0), M["white"])
    ob = mb.emit("Yard_3905_Shed", coll)
    C.set_extras(ob, kind="shed", address="3905 Canby Ct", collide=True, note="observed position/size (orthos)")
    out.append(ob)
    # raised vegetable beds at (5..12, 28..32)
    mb = C.MeshBuilder()
    for (bx, by) in ((6.0, 29.0), (8.6, 29.0), (11.2, 29.0), (6.0, 31.4), (8.6, 31.4), (11.2, 31.4)):
        g = z(bx, by)
        P = [(bx - 1.1, by - 0.55), (bx + 1.1, by - 0.55), (bx + 1.1, by + 0.55), (bx - 1.1, by + 0.55)]
        mb.prism(P, g - 0.1, g + 0.4, M["wood"], cap_top=False)
        mb.poly([(p[0], p[1], g + 0.33) for p in P], M["soil"], uv_mode="xy")
    ob = mb.emit("Yard_3905_RaisedBeds", coll)
    C.set_extras(ob, kind="raised_beds", address="3905 Canby Ct", collide=True, note="observed (orthos)")
    out.append(ob)
    # patio furniture (3905 NE corner) - table + 4 chairs + umbrella
    mb = C.MeshBuilder()
    x, y = 10.6, 7.4
    g = z(x, y) + 0.06
    mb.tube([(x, y, g), (x, y, g + 0.72)], 0.03, M["black"], sides=6)
    mb.tube([(x, y, g + 0.72), (x, y, g + 0.75)], 0.55, M["black"], sides=16)
    for k in range(4):
        a = k * math.pi / 2 + 0.4
        cx, cy = x + math.cos(a) * 0.95, y + math.sin(a) * 0.95
        mb.box((cx, cy, g + 0.44), (0.5, 0.5, 0.05), M["black"], rotz=a)
        mb.box((cx + math.cos(a) * 0.23, cy + math.sin(a) * 0.23, g + 0.7), (0.05, 0.5, 0.5), M["black"], rotz=a)
        for (dx, dy) in ((-0.2, -0.2), (0.2, -0.2), (0.2, 0.2), (-0.2, 0.2)):
            mb.tube([(cx + dx, cy + dy, g), (cx + dx, cy + dy, g + 0.44)], 0.015, M["black"], sides=4)
    mb.tube([(x, y, g + 0.75), (x, y, g + 2.3)], 0.02, M["galv"], sides=6)
    mb.tube([(x, y, g + 2.1), (x, y, g + 2.45)], 1.3, M["white"], sides=10, r_end=0.05)
    ob = mb.emit("Yard_3905_PatioFurniture", coll)
    C.set_extras(ob, kind="furniture", address="3905 Canby Ct", collide=True, note="observed (orthos)")
    out.append(ob)
    # 3803 octagonal gazebo (brown roof) in the rear yard
    mb = C.MeshBuilder()
    x, y = -97.5, 29.5
    g = z(x, y)
    R = 1.9
    oct_ = [(x + R * math.cos(k * math.pi / 4 + math.pi / 8), y + R * math.sin(k * math.pi / 4 + math.pi / 8)) for k in range(8)]
    mb.prism(oct_, g - 0.3, g + 0.25, M["wood"])
    for p in oct_:
        mb.box((p[0], p[1], g + 1.4), (0.12, 0.12, 2.3), M["white"])
    for k in range(8):
        a, b = oct_[k], oct_[(k + 1) % 8]
        f = 1.18
        mb.poly([(x + (a[0] - x) * f, y + (a[1] - y) * f, g + 2.5), (x + (b[0] - x) * f, y + (b[1] - y) * f, g + 2.5),
                 (x, y, g + 3.7)], M["shingle_br"], uv_mode="plane")
    ob = mb.emit("Yard_3803_Gazebo", coll)
    C.set_extras(ob, kind="gazebo", address="3803 Canby Ct", collide=True, note="observed (orthos)")
    out.append(ob)
    # trampolines (3909 east yard, 3806 rear lawn)
    for nm, (x, y), addr in (("Yard_3909_Trampoline", (19.5, -41.0), "3909"), ("Yard_3806_Trampoline", (-48.0, -66.0), "3806")):
        mb = C.MeshBuilder()
        g = z(x, y)
        R = 1.8
        for k in range(6):
            a = k * math.pi / 3
            mb.tube([(x + R * math.cos(a), y + R * math.sin(a), g - 0.05), (x + R * math.cos(a), y + R * math.sin(a), g + 2.6)],
                    0.025, M["black"], sides=5)
        ring = [(x + R * math.cos(a), y + R * math.sin(a), g + 0.9) for a in np.linspace(0, 2 * math.pi, 25)]
        mb.tube(ring, 0.03, M["galv"], sides=5)
        mb.tube([(x, y, g + 0.88), (x, y, g + 0.9)], R * 0.92, M["black"], sides=24)
        net = [(x + R * math.cos(a), y + R * math.sin(a)) for a in np.linspace(0, 2 * math.pi, 25)[:-1]]
        mb.prism(net, g + 0.92, g + 2.55, M["mesh"], cap_top=False)
        ob = mb.emit(nm, coll)
        C.set_extras(ob, kind="trampoline", address="%s Canby Ct" % addr, collide=True, note="observed (orthos)")
        out.append(ob)
    # 3900 boat under blue cover beside the drive; 3909 white trailer north of the house
    mb = C.MeshBuilder()
    x, y = -14.6, -62.5
    g = z(x, y)
    mb.box((x, y, g + 0.9), (2.3, 6.0, 1.3), M["blue"], rotz=math.radians(17))
    for sg in (-1, 1):
        mb.tube([(x + sg * 0.8, y - 1.5, g + 0.3), (x + sg * 0.8, y - 1.5, g + 0.32)], 0.3, M["tyre"], sides=12)
    ob = mb.emit("Yard_3900_Boat", coll)
    C.set_extras(ob, kind="boat", address="3900 Canby Ct", collide=True, note="observed (orthos)")
    out.append(ob)
    mb = C.MeshBuilder()
    x, y = 14.5, -12.5
    g = z(x, y)
    mb.box((x, y, g + 1.55), (5.8, 2.3, 2.4), M["white"], rotz=math.radians(2))
    mb.box((x - 3.6, y, g + 0.5), (1.5, 0.1, 0.1), M["black"], rotz=math.radians(2))
    for sg in (-1, 1):
        mb.tube([(x, y + sg * 1.16, g + 0.33), (x, y + sg * 1.2, g + 0.33)], 0.33, M["tyre"], sides=12)
    ob = mb.emit("Yard_3909_Trailer", coll)
    C.set_extras(ob, kind="trailer", address="3909 Canby Ct", collide=True, note="observed (orthos)")
    out.append(ob)
    # neighbour's sport court east of 3905/3909 (observed)
    mb = C.MeshBuilder()
    x0, x1, y0, y1 = 27.5, 39.5, -22.0, -4.0
    g = z((x0 + x1) / 2, (y0 + y1) / 2)
    mb.prism([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], g - 0.4, g + 0.05, M["green"])
    for (a, b) in (((x0 + 0.4, y0 + 0.4), (x1 - 0.4, y0 + 0.4)), ((x1 - 0.4, y0 + 0.4), (x1 - 0.4, y1 - 0.4)),
                   ((x1 - 0.4, y1 - 0.4), (x0 + 0.4, y1 - 0.4)), ((x0 + 0.4, y1 - 0.4), (x0 + 0.4, y0 + 0.4)),
                   ((x0 + 0.4, (y0 + y1) / 2), (x1 - 0.4, (y0 + y1) / 2))):
        c = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, g + 0.055)
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        mb.box(c, (L, 0.06, 0.005), M["white"], rotz=math.atan2(b[1] - a[1], b[0] - a[0]))
    ob = mb.emit("Yard_SportCourt_east", coll)
    C.set_extras(ob, kind="sport_court", walkable=True, note="observed (orthos), neighbouring lot")
    out.append(ob)
    return out


# ============================================================================ winter: jumps, berm, tracks
_SNOW_BVH = None


def set_snow_surface(ob):
    """Use the built winter snow mesh as the base height for jumps / berm / tracks."""
    global _SNOW_BVH
    from mathutils.bvhtree import BVHTree
    me = ob.data
    V = [tuple(v.co) for v in me.vertices]
    F = [tuple(p.vertices) for p in me.polygons]
    _SNOW_BVH = BVHTree.FromPolygons(V, F)


def snow_base(x, y):
    if _SNOW_BVH is not None:
        from mathutils import Vector
        hit = _SNOW_BVH.ray_cast(Vector((x, y, 400.0)), Vector((0, 0, -1)))
        if hit[0] is not None:
            return hit[0].z
    st = G.street_poly()
    inside = st.contains(Point(x, y))
    return z(x, y) + (-G.CURB_H + 0.07 if inside else 0.2)


def kicker(j, coll, M):
    c = np.array(j["center_local"])
    hd = C.heading_vec(j["heading_deg"])
    sd = np.array([-hd[1], hd[0]])
    Lr, h, ang, W = j["ramp_length_m"], j["lip_height_m"], math.radians(j["lip_angle_deg"]), j["width_m"]
    Ll = j["landing_length_m"]
    # ramp profile: circular transition reaching `ang` at the lip, scaled to lip height
    s = np.linspace(0, 1, 18)
    prof = (1 - np.cos(s * ang)) / (1 - math.cos(ang))
    zs = h * prof
    xs = -Lr / 2 + s * Lr
    back = h / math.tan(math.radians(55))
    xs = np.concatenate([[-Lr / 2 - 0.6], xs, [Lr / 2 + 0.25, Lr / 2 + 0.25 + back]])
    zs = np.concatenate([[0.0], zs, [h * 0.97, 0.0]])
    # landing: gentle mound after a 1.5 m gap
    lx = np.linspace(0, 1, 10)
    land_x = Lr / 2 + back + 1.0 + lx * Ll
    land_z = 0.45 * h * np.sin(np.pi * np.clip(lx * 1.25, 0, 1)) ** 0.7 * (1 - lx) ** 0.3
    xs = np.concatenate([xs, land_x])
    zs = np.concatenate([zs, land_z])
    ts = np.linspace(-1, 1, 11)
    mb = C.MeshBuilder()
    rows = []
    for xi, zi in zip(xs, zs):
        row = []
        for t in ts:
            sh = np.clip((1 - abs(t)) / 0.22, 0, 1)
            sh = sh * sh * (3 - 2 * sh)
            wide = W / 2 * (1.25 if xi > Lr / 2 + back else 1.0) + 0.5
            p = c + hd * xi + sd * t * wide
            row.append((p[0], p[1], snow_base(*p) + zi * sh - 0.02))
        rows.append(mb.add_verts(row))
    for i in range(len(rows) - 1):
        for k in range(len(ts) - 1):
            a, b, cc, d = rows[i][k], rows[i][k + 1], rows[i + 1][k + 1], rows[i + 1][k]
            mb.face([a, b, cc, d][::-1], [(xs[i], ts[k] * 2), (xs[i], ts[k + 1] * 2), (xs[i + 1], ts[k + 1] * 2),
                                          (xs[i + 1], ts[k] * 2)][::-1], M["snowp"], True)
    ob = mb.emit("Jump_%s" % j["id"], coll)
    ob.data.polygons.foreach_set("use_smooth", np.ones(len(ob.data.polygons), bool))
    C.set_extras(ob, kind="jump", jump_id=j["id"], artistic=True, season="winter", walkable=True, collide=True,
                 lip_height_m=h, lip_angle_deg=j["lip_angle_deg"], heading_deg=j["heading_deg"],
                 source="data/game/jumps.json")
    return ob


def berm(b, coll, M):
    c = np.array(b["center_local"])
    hd = C.heading_vec(b["heading_deg"])
    sd = np.array([-hd[1], hd[0]])
    W, H, D = b["width_m"], b["height_m"], b["depth_m"]
    mb = C.MeshBuilder()
    xs = np.linspace(-D / 2 - 1.2, D / 2 + 0.8, 14)
    ts = np.linspace(-1, 1, 15)
    rows = []
    for xi in xs:
        row = []
        for t in ts:
            f = np.clip(1 - ((xi + 0.2) / (D / 2 + 1.0)) ** 2, 0, 1) ** 0.8
            sh = np.clip((1 - abs(t)) / 0.25, 0, 1)
            sh = sh * sh * (3 - 2 * sh)
            p = c + hd * xi + sd * t * (W / 2 + 0.6)
            row.append((p[0], p[1], snow_base(*p) + H * f * sh - 0.02))
        rows.append(mb.add_verts(row))
    for i in range(len(rows) - 1):
        for k in range(len(ts) - 1):
            a, bb, cc, d = rows[i][k], rows[i][k + 1], rows[i + 1][k + 1], rows[i + 1][k]
            mb.face([a, bb, cc, d][::-1], [(xs[i], ts[k] * 3), (xs[i], ts[k + 1] * 3), (xs[i + 1], ts[k + 1] * 3),
                                           (xs[i + 1], ts[k] * 3)][::-1], M["snowp"], True)
    ob = mb.emit("Berm_runout", coll)
    ob.data.polygons.foreach_set("use_smooth", np.ones(len(ob.data.polygons), bool))
    C.set_extras(ob, kind="berm", artistic=True, season="winter", walkable=True, collide=True, height_m=H,
                 source="data/game/jumps.json")
    # hay bales on the uphill face
    hb = C.MeshBuilder()
    nb = 7
    for k in range(nb):
        t = -1 + 2 * (k + 0.5) / nb
        p = c - hd * (D / 2 + 1.2) + sd * t * (W / 2 - 0.4)
        hb.box((p[0], p[1], snow_base(*p) + 0.2), (0.48, 1.0, 0.38), M["straw"],
               rotz=math.atan2(hd[1], hd[0]))
        hb.box((p[0], p[1], snow_base(*p) + 0.4), (0.4, 0.9, 0.03), M["snowp"],
               rotz=math.atan2(hd[1], hd[0]))
    ob2 = hb.emit("Berm_haybales", coll)
    C.set_extras(ob2, kind="hay_bales", artistic=True, season="winter", collide=True)
    return [ob, ob2]


def sled_tracks(coll, M):
    path = C.data("jumps")["run_path_local"]
    pts, s = C.resample_line(path, 0.75)
    nrm, tan = C.line_normals(pts)
    mb = C.MeshBuilder()
    W = 3.0
    rows = []
    for p, n in zip(pts, nrm):
        row = []
        for t in (-1, -0.5, 0, 0.5, 1):
            q = p + n * t * W / 2
            row.append((q[0], q[1], snow_base(*q) + 0.012))
        rows.append(mb.add_verts(row))
    for i in range(len(rows) - 1):
        for k in range(4):
            mb.face([rows[i][k], rows[i][k + 1], rows[i + 1][k + 1], rows[i + 1][k]][::-1],
                    [(s[i], k * 0.75), (s[i], (k + 1) * 0.75), (s[i + 1], (k + 1) * 0.75), (s[i + 1], k * 0.75)][::-1],
                    M["snowp"], True)
    ob = mb.emit("SledRun_Tracks", coll)
    C.set_extras(ob, kind="sled_run", season="winter", walkable=True, collide=False,
                 note="measured run path (sledding.json); packed snow with sled tracks")
    return ob
