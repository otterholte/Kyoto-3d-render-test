"""Generic modern moulded-plastic toboggan sled (no brand, no logo) + pull rope.

Sled space: front = -Y, floor near z=0, origin at the ground under the sled
centre. The empty "SledSeat" marks where the character root goes (sled clips
are authored in that space).
"""
import math
import numpy as np
import bpy

import geo
from materials import new_material

LENGTH = 1.20
Y_BACK = 0.62
SEAT = (0.0, 0.18, 0.020)


def _path(u):
    """Centreline of the floor (y, z) and the tangent angle along the length u in [0,1] (back->front)."""
    curl0 = 0.80
    flat_len = LENGTH * curl0
    if u <= curl0:
        y = Y_BACK - u * LENGTH
        return y, 0.012, 0.0
    R = 0.16
    s = (u - curl0) * LENGTH            # arc length along the curl
    ang = min(s / R, math.radians(100))
    y = Y_BACK - flat_len - R * math.sin(ang)
    z = 0.012 + R * (1 - math.cos(ang))
    return y, z, ang


def _width(u):
    return 0.255 - 0.02 * u - 0.03 * max(0.0, u - 0.85) / 0.15


def _wall(u):
    # side wall height above the floor; lower at the very back, rising toward the front
    return 0.095 + 0.02 * math.sin(math.pi * min(u / 0.85, 1.0)) - 0.03 * max(0.0, u - 0.82) / 0.18


def build(collection):
    nu, profile = 44, []
    # half profile (x>=0) from centre floor to the rim, then mirrored
    half = [(0.00, 0.000), (0.05, -0.004), (0.06, 0.0), (0.11, -0.004), (0.12, 0.0), (0.17, -0.004),
            (0.18, 0.0), (0.215, 0.004), (0.235, 0.020), (0.245, 0.05), (0.250, 0.09), (0.252, 1.0),
            (0.262, 1.02), (0.270, 0.99)]
    # last 3 points describe the rolled rim (z given as fraction of wall)
    prof = [(-x, z) for x, z in half[::-1]] + [(x, z) for x, z in half[1:]]
    verts, faces, uvs = [], [], []
    nv = len(prof)
    for i in range(nu + 1):
        u = i / nu
        y, z0, ang = _path(u)
        w = _width(u) / 0.255
        wall = _wall(u)
        for j, (x, zz) in enumerate(prof):
            zr = zz if zz <= 0.1 else zz * wall
            if abs(x) >= 0.25:
                zr = (zz * wall) if zz > 0.5 else zz
            # local (x, up) -> world: up direction rotates with the curl
            up_y, up_z = -math.sin(ang) * -1, math.cos(ang)
            yy = y + zr * (math.sin(ang))
            zz_w = z0 + zr * math.cos(ang)
            verts.append((x * w, yy, zz_w))
            uvs.append((j / (nv - 1), u))
    # handle slots: skip wall faces in two windows per side
    slots = [(0.38, 0.46), (0.60, 0.68)]
    for i in range(nu):
        ui = (i + 0.5) / nu
        for j in range(nv - 1):
            xj = abs(prof[j][0]) + abs(prof[j + 1][0])
            in_wall = min(abs(prof[j][0]), abs(prof[j + 1][0])) >= 0.245 and max(prof[j][1], prof[j + 1][1]) > 0.08 \
                and min(prof[j][1], prof[j + 1][1]) >= 0.09 and max(prof[j][1], prof[j + 1][1]) <= 1.0
            if in_wall and any(a < ui < b for a, b in slots):
                continue
            a = i * nv + j
            faces.append([a, a + 1, a + nv + 1, a + nv])
    floor = []
    for f in faces:
        floor.append([(uvs[k][0], uvs[k][1]) for k in f])
    uvl = np.array([uv for f in floor for uv in f])
    ob = geo.make_object("Sled", np.array(verts), faces, collection, uv_loops=uvl)
    so = ob.modifiers.new("thickness", "SOLIDIFY")
    so.thickness = 0.006
    so.offset = -1
    so.use_rim = True
    so.use_even_offset = True
    bv = ob.modifiers.new("bevel", "BEVEL")
    bv.width = 0.002
    bv.segments = 1
    bv.limit_method = "ANGLE"
    sub = ob.modifiers.new("smooth", "SUBSURF")
    sub.levels = 0
    sub.render_levels = 1
    ob.data.materials.append(sled_material())

    # pull rope: front loop + side grab ropes threaded through the slots
    ropes = []
    def tube(name, pts, r=0.0055):
        cu = bpy.data.curves.new(name, "CURVE")
        cu.dimensions = "3D"
        sp = cu.splines.new("NURBS")
        sp.points.add(len(pts) - 1)
        for p, q_ in zip(sp.points, pts):
            p.co = (q_[0], q_[1], q_[2], 1.0)
        sp.use_endpoint_u = True
        sp.order_u = 3
        cu.bevel_depth = r
        cu.bevel_resolution = 2
        cu.resolution_u = 6
        o = bpy.data.objects.new(name, cu)
        collection.objects.link(o)
        return o
    yF, zF, _ = _path(0.93)
    front = [(0.10, yF + 0.01, zF + 0.05), (0.16, yF - 0.10, zF - 0.02), (0.10, yF - 0.30, 0.02),
             (0.0, yF - 0.36, 0.015), (-0.10, yF - 0.30, 0.02), (-0.16, yF - 0.10, zF - 0.02), (-0.10, yF + 0.01, zF + 0.05)]
    ropes.append(tube("SledRope_Front", front))
    for sx in (1, -1):
        pts = []
        for u, dz in ((0.33, 0.0), (0.42, -0.035), (0.52, -0.01), (0.64, -0.035), (0.73, 0.0)):
            y, z0, ang = _path(u)
            pts.append((sx * 0.262, y, z0 + _wall(u) + dz))
        ropes.append(tube("SledRope_Side" + ("_L" if sx > 0 else "_R"), pts, r=0.005))
    rm = rope_material()
    for r in ropes:
        r.data.materials.append(rm)
        r.parent = ob
    seat = bpy.data.objects.new("SledSeat", None)
    seat.empty_display_type = "ARROWS"
    seat.empty_display_size = 0.15
    seat.location = SEAT
    collection.objects.link(seat)
    seat.parent = ob
    return ob, seat, ropes


def sled_material():
    m, b = new_material("SledPlastic")
    oc = b.coord("Object")
    uvp = b.sep(b.uv("UVMap"))
    # moulded HDPE: saturated blue with slight translucency, scuffs underneath
    base = (0.010, 0.07, 0.30)
    scuff = b.noise(b.mapping(oc, scale=(30, 3, 30)), 6.0, detail=8, rough=0.7)
    scr = b.wave(b.mapping(oc, scale=(1, 0.05, 1)), 60.0, kind="BANDS", direction="X", distortion=12, detail=4)
    under = b.math("LESS_THAN", b.n("ShaderNodeNewGeometry").outputs["Normal"], 0.0)
    nz = b.sep(b.n("ShaderNodeNewGeometry").outputs["Normal"])[2]
    under = b.math("LESS_THAN", nz, -0.3)
    sc = b.math("MULTIPLY", b.math("GREATER_THAN", scr, 0.94), b.math("ADD", 0.15, under))
    col = b.mix(b.math("MULTIPLY", sc, 0.3), base, (0.25, 0.32, 0.48))
    rough = b.math("ADD", 0.28, b.math("MULTIPLY", sc, 0.35))
    h = b.math("ADD", b.math("MULTIPLY", scuff, 0.2), b.math("MULTIPLY", sc, 0.4))
    nrm = b.bump(h, strength=0.15, distance=0.0005)
    b.principled(**{"Base Color": col, "Roughness": rough, "Normal": nrm, "Subsurface Weight": 0.15,
                    "Subsurface Radius": (0.2, 0.4, 1.0), "Subsurface Scale": 0.01, "Coat Weight": 0.3,
                    "Coat Roughness": 0.15})
    return m


def rope_material():
    m, b = new_material("SledRope")
    oc = b.coord("Object")
    twist = b.wave(b.mapping(oc, scale=(1, 1, 1)), 180.0, kind="BANDS", direction="DIAGONAL", distortion=1)
    col = b.ramp(twist, [(0.2, (0.45, 0.42, 0.36)), (0.8, (0.75, 0.72, 0.64))])
    nrm = b.bump(twist, strength=0.5, distance=0.001)
    b.principled(**{"Base Color": col, "Roughness": 0.85, "Normal": nrm, "Sheen Weight": 0.4})
    return m
