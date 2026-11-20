"""Hero landmark: Yasaka Pagoda (八坂の塔, five-storey pagoda of Hōkan-ji 法観寺), procedurally modelled.

Usage as a module (inside Blender / bpy):
    import hero_pagoda
    root = hero_pagoda.build_pagoda(collection=None, detail="high")   # or detail="web"

Usage as a script:
    /home/user/venv/bin/python blender/hero_pagoda.py [--no-render] [--no-glb] [--fast] [--final]
      * opens blender/higashiyama_blockout.blend, hides the PLATEAU placeholder, builds the hero model
      * writes blender/assets/hero_pagoda.blend (pagoda only, for linking)
      * renders renders/hero_pagoda_*.png (Cycles)
      * exports web/assets/pagoda.glb (detail="web", Y-up)

Frame: 1 unit = 1 m, +X east, +Y north, +Z = absolute T.P. height (JGD2011 vertical).
Local origin = EPSG:6674 E -20160 / N -111160 (see docs/boundary.md).

Every modelled dimension is listed in EVIDENCE (also stored as JSON on the root object, property `evidence`)
with a confidence class: measured | documented | observed | estimated | inferred.  The full table, sources and
the list of inferred items is in docs/evidence/yasaka_pagoda_model.md.

The model is built in a pagoda-local frame (origin = plan centre at PLATEAU ground level, local +X normal to one
face) and parented to the empty "LM_Yasaka_Pagoda_HERO", which carries the world position, the measured plan
rotation and the ground elevation.
"""
import json
import math
import os
import random
import sys

import bpy  # noqa: I001  (bpy before bmesh / mathutils)
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# =============================================================================================== evidence / parameters
# Placement (measured): OSM way 371717416 centroid (9.671, 83.458) / PLATEAU roof-edge centroid (9.089, 83.219),
# 0.63 m apart -> midpoint. Rotation: minimum rotated rectangle side bearings, OSM +1.94 deg, PLATEAU +0.95 deg
# (CCW from grid east) -> 1.4 deg (research spec value, mean of both).
CENTRE_XY = (9.38, 83.34)
ROT_DEG = 1.4
GROUND_Z = 61.03            # PLATEAU LOD2 GroundSurface / LOD1 base (61.03-61.04)
TOTAL_HEIGHT = 38.8         # measured/derived: PLATEAU apex 28.7 m + photo-derived sorin (audit telephoto: 39.2-40.0 m)
POPULAR_HEIGHT = 46.0       # widely published / OSM height=46: disputed popular figure (inconsistent with measured geometry)

PLATFORM_W = 9.4            # inferred (spec)
PLATFORM_H = 1.0            # inferred (spec)
# per storey: body width (column-centre square), eave span corner-to-corner, top of eave edge above ground
BODY_W = [6.4, 6.08, 5.76, 5.45, 5.13]          # 6.4 documented (disputed 5.5); upper storeys photo ratio 0.42
EAVE_W = [15.1, 14.35, 13.6, 12.85, 12.1]       # 15.1 measured (PLATEAU roof edge 15.31 x 14.96); taper from photos
EAVE_TOP = [8.29, 12.23, 16.07, 20.47, 24.32]   # measured: PLATEAU LOD2 tier steps above the 61.04 m base
TOP_APEX = 28.7                                  # PLATEAU measuredHeight = top roof apex (measured)
SORIN_H = TOTAL_HEIGHT - TOP_APEX                # 10.1 m (photo ratio 2.3-2.5 tier spacings -> estimated)
SORIN_BASE = TOP_APEX - 1.10                     # tile surface meets the roban here; roban top ~ PLATEAU apex (inferred)
EAVE_THICK = 0.40           # tile edge + fascia band (inferred)
CORNER_LIFT = 0.55          # eave corner up-sweep (observed qualitatively, value estimated)
PLAN_KICK = 0.28            # eave plan sweep: corners project further than mid-face (inferred)
BALCONY_W = 0.78            # railed balcony (koran) depth, storeys 2-5 (observed presence, size inferred)
BRACKET_PROJ = 1.45         # three-step (mitesaki) bracket projection from column line (inferred, wayo practice)
BRACKET_SCALE = [1.35, 0.84, 0.84, 0.84, 0.84]   # vertical size of bracket sets per storey (inferred; storey 1 larger)
LOWER_ROOF_RISE = 0.95      # rise of roofs 1-4 from eave top to the upper balcony (estimated from photos)

EVIDENCE = {
    "position_xy_local": {"value": list(CENTRE_XY), "confidence": "measured",
                          "source": "mean of OSM way 371717416 centroid (9.67,83.46) and PLATEAU bldg_2b477621 roof-edge centroid (9.09,83.22)"},
    "plan_rotation_deg_ccw_from_grid_east": {"value": ROT_DEG, "confidence": "measured",
                                             "source": "minimum rotated rectangle: OSM 1.94 deg, PLATEAU 0.95 deg (range 0.9-1.9)"},
    "ground_z_TP": {"value": GROUND_Z, "confidence": "measured", "source": "PLATEAU LOD2 GroundSurface / LOD1 base (DEM5A at centroid 61.4)"},
    "total_height_incl_sorin_m": {"value": TOTAL_HEIGHT, "confidence": "measured/derived",
                                  "source": "PLATEAU measuredHeight 28.7 m (top roof apex above base) + photo-derived sorin ~10.1 m; "
                                            "independent telephoto measurement in docs/accuracy_report.md F2: 39.2-40.0 m"},
    "ndl_reference_height_m": {"value": 38.8, "confidence": "documented, source not retrievable from this environment",
                               "source": "NDL Collaborative Reference 1000061716 (総高 38.8 m, seen only as a web-search summary; crd.ndl.go.jp unreachable)"},
    "popular_height_m_disputed": {"value": POPULAR_HEIGHT, "confidence": "disputed popular figure",
                                  "source": "widely published '約46 m' (operator/tourist sites, OSM height=46); would need ~17 m sorin or ~19.6 m eaves, "
                                            "contradicted by PLATEAU 15.1 m roof outline, 28.7 m apex and photo proportions"},
    "storeys": {"value": 5, "confidence": "documented", "source": "designation 三間五重塔婆; OSM building:levels=5"},
    "plan_bays": {"value": "3x3", "confidence": "documented", "source": "三間五重塔婆 (souda-kyoto.jp, kyoto-design.jp snippets)"},
    "first_storey_side_m": {"value": BODY_W[0], "confidence": "documented", "source": "'6.4 m 四方' (alt. 5.5 m), spec first_storey_side_m"},
    "upper_body_widths_m": {"value": BODY_W[1:], "confidence": "estimated", "source": "photo ratio body/eave 0.42 (File:Yasaka Pagoda (24922466195).jpg)"},
    "lowest_eave_span_m": {"value": EAVE_W[0], "confidence": "measured", "source": "PLATEAU lod0RoofEdge 15.31 x 14.96 m (area 229.2 m2)"},
    "eave_spans_2_5_m": {"value": EAVE_W[1:], "confidence": "estimated", "source": "~5 %/storey taper, photo widths 5th:4th:3rd = 415:440:465 px"},
    "eave_heights_above_ground_m": {"value": EAVE_TOP, "confidence": "measured",
                                    "source": "PLATEAU LOD2 stepped tiers 8.29/12.23/16.07/20.47/24.32 m (taken as top of eave edge; interpretation inferred)"},
    "eave_spacing_m": {"value": "3.84-4.40 (mean 4.0)", "confidence": "measured", "source": "PLATEAU LOD2 tier steps; photo rhythm agrees (accuracy_report F2)"},
    "top_roof_apex_above_ground_m": {"value": TOP_APEX, "confidence": "measured", "source": "PLATEAU measuredHeight 28.7 m"},
    "sorin_height_m": {"value": round(SORIN_H, 2), "confidence": "estimated", "source": "photo ratio sorin = 2.3-2.5 eave spacings (sorin/(apex-eave1) = 0.51-0.56 in audit); = total 38.8 - apex 28.7"},
    "kurin_rings": {"value": 9, "confidence": "observed", "source": "File:150124 At Yasakakamimachi Kyoto Japan02n.jpg; File:Yasaka-Dori - panoramio.jpg"},
    "platform_w_m": {"value": PLATFORM_W, "confidence": "inferred", "source": "body + ~1.5 m margin; kidan mostly hidden behind street fence"},
    "platform_h_m": {"value": PLATFORM_H, "confidence": "inferred", "source": "typical; spec base_platform"},
    "platform_steps": {"value": "4 sides, 4 risers", "confidence": "inferred", "source": "typical pagoda kidan"},
    "eave_edge_thickness_m": {"value": EAVE_THICK, "confidence": "inferred", "source": "typical hongawara eave"},
    "eave_corner_lift_m": {"value": CORNER_LIFT, "confidence": "estimated", "source": "soft corner upturn observed (File:150124 ... Japan02n.jpg)"},
    "balconies": {"value": "railed (koran) on storeys 2-5, none on storey 1", "confidence": "observed",
                  "source": "File:150124 ... Japan02n.jpg; File:Gion - Nineizaka (48923801861).jpg; storey 1 sits on the platform (File:Yasakanoto Tower of Hokanji Temple.jpg)"},
    "balcony_depth_m": {"value": BALCONY_W, "confidence": "inferred", "source": "typical"},
    "bracketing": {"value": "three-step (mitesaki) with tail rafters, projection %.2f m" % BRACKET_PROJ, "confidence": "observed",
                   "source": "multi-step bracket sets: File:Gion - Nineizaka (48923269328).jpg; File:Kyoto Pagoda.jpg (projection inferred)"},
    "rafters": {"value": "two tiers (二軒繁垂木), pitch 0.27 m", "confidence": "observed", "source": "File:3D photo-cross view ... panoramio.jpg (pitch inferred)"},
    "roof": {"value": "hongawara clay tile, round-tile rows pitch 0.27 m, tomoe end discs", "confidence": "documented",
             "source": "本瓦葺 (designation text); end discs observed (3D photo-cross view)"},
    "infill": {"value": "central plank doors + renji lattice windows, white plaster between brackets", "confidence": "observed",
               "source": "File:Kyoto Pagoda.jpg; File:Yasaka Pagoda (24922466195).jpg"},
    "wind_bells": {"value": "futaku at 4 corners of every roof", "confidence": "observed", "source": "File:Kyoto Pagoda.jpg"},
    "colours": {"value": {"timber": "#2e2420 unpainted dark brown-black (no vermilion)", "tiles": "#7f8279", "sorin": "#504c43 dark bronze",
                          "plaster": "#e8e2d4"}, "confidence": "observed", "source": "spec colours (median pixel samples)"},
}

MAT_SPECS = {   # name: (base linear rgb, roughness, metallic)  -- linear values from the observed sRGB hexes
    "PAG_Wood": ((0.036, 0.024, 0.018), 0.78, 0.0),
    "PAG_WoodLight": ((0.060, 0.042, 0.030), 0.75, 0.0),
    "PAG_Plaster": ((0.62, 0.58, 0.49), 0.92, 0.0),
    "PAG_Kawara": ((0.058, 0.061, 0.058), 0.55, 0.0),
    "PAG_Bronze": ((0.075, 0.068, 0.052), 0.48, 0.75),
    "PAG_Stone": ((0.36, 0.345, 0.32), 0.85, 0.0),
    "PAG_Dark": ((0.012, 0.009, 0.007), 0.9, 0.0),
}


# =============================================================================================== small vector helpers
def V(x, y, z):
    return Vector((x, y, z))


FACE_N = [V(1, 0, 0), V(0, 1, 0), V(-1, 0, 0), V(0, -1, 0)]
FACE_T = [V(0, 1, 0), V(-1, 0, 0), V(0, -1, 0), V(1, 0, 0)]
UP = V(0, 0, 1)


def fp(k, d, a, z):
    """face-frame point: distance d along outward normal of face k, a along the face, height z."""
    n, t = FACE_N[k], FACE_T[k]
    return V(n.x * d + t.x * a, n.y * d + t.y * a, z)


# =============================================================================================== mesh builder
class MB:
    """Accumulates geometry for one object; per-element variation value -> attribute 'pvar' + colour 'Col'."""

    def __init__(self, name, skip_top=False):
        self.name = name
        self.skip_top = skip_top      # web: drop box top faces (never seen from street level)
        self.v, self.f, self.fm, self.fs, self.var = [], [], [], [], []
        self.mats = []

    def mi(self, mat):
        if mat not in self.mats:
            self.mats.append(mat)
        return self.mats.index(mat)

    def add(self, verts, faces, mat, smooth=False, var=None):
        b = len(self.v)
        m = self.mi(mat)
        var = random.random() if var is None else var
        self.v.extend(verts)
        self.var.extend([var] * len(verts))
        for fc in faces:
            self.f.append(tuple(b + i for i in fc))
            self.fm.append(m)
            self.fs.append(smooth)

    # ---------------------------------------------------------------- primitives
    def obox(self, c, ex, ey, ez, mat, var=None, skip=()):
        """oriented box: centre c, half-axis vectors ex, ey, ez."""
        p = [c - ex - ey - ez, c + ex - ey - ez, c + ex + ey - ez, c - ex + ey - ez,
             c - ex - ey + ez, c + ex - ey + ez, c + ex + ey + ez, c - ex + ey + ez]
        faces = {"b": (0, 3, 2, 1), "t": (4, 5, 6, 7), "-y": (0, 1, 5, 4), "+x": (1, 2, 6, 5), "+y": (2, 3, 7, 6), "-x": (3, 0, 4, 7)}
        self.add(p, [fc for kk, fc in faces.items() if kk not in skip], mat, var=var)

    def box(self, x0, x1, y0, y1, z0, z1, mat, var=None, skip=()):
        self.obox(V((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2), V((x1 - x0) / 2, 0, 0), V(0, (y1 - y0) / 2, 0),
                  V(0, 0, (z1 - z0) / 2), mat, var, skip)

    def fbox(self, k, d0, d1, a0, a1, z0, z1, mat, var=None, skip=()):
        """axis box in face frame k."""
        if self.skip_top:
            skip = tuple(skip) + ("t",)
        c = fp(k, (d0 + d1) / 2, (a0 + a1) / 2, (z0 + z1) / 2)
        self.obox(c, FACE_N[k] * ((d1 - d0) / 2), FACE_T[k] * ((a1 - a0) / 2), V(0, 0, (z1 - z0) / 2), mat, var, skip)

    def beam(self, p0, p1, w, h, mat, up=UP, var=None, skip_ends=False, skip=()):
        """box along segment p0->p1, width w (horizontal), height h (perpendicular, roughly 'up')."""
        ax = p1 - p0
        L = ax.length
        if L < 1e-6:
            return
        a = ax / L
        side = a.cross(up)
        if side.length < 1e-6:
            side = a.cross(V(1, 0, 0))
        side.normalize()
        upv = side.cross(a).normalized()
        self.obox((p0 + p1) / 2, a * (L / 2), side * (w / 2), upv * (h / 2), mat, var,
                  skip=(("-x", "+x") if skip_ends else ()) + tuple(skip))

    def cyl(self, p0, p1, r0, r1, seg, mat, caps=True, var=None, smooth=True):
        ax = (p1 - p0)
        a = ax.normalized()
        u = a.cross(V(0, 0, 1) if abs(a.z) < 0.9 else V(1, 0, 0)).normalized()
        w = a.cross(u)
        verts = []
        for (pc, r) in ((p0, r0), (p1, r1)):
            for i in range(seg):
                t = 2 * math.pi * i / seg
                verts.append(pc + (u * math.cos(t) + w * math.sin(t)) * r)
        faces = [(i, (i + 1) % seg, seg + (i + 1) % seg, seg + i) for i in range(seg)]
        if caps:
            faces.append(tuple(reversed(range(seg))))
            faces.append(tuple(range(seg, 2 * seg)))
        self.add(verts, faces, mat, smooth=smooth, var=var)

    def lathe(self, centre, prof, seg, mat, var=None, smooth=True, close_top=True, close_bot=True, rscale=None):
        """surface of revolution around vertical axis; prof = [(r, z), ...] bottom->top (z relative)."""
        verts, faces = [], []
        n = len(prof)
        for (r, z) in prof:
            for i in range(seg):
                t = 2 * math.pi * i / seg
                rr = r * (rscale(t) if rscale else 1.0)
                verts.append(V(centre.x + rr * math.cos(t), centre.y + rr * math.sin(t), centre.z + z))
        for j in range(n - 1):
            for i in range(seg):
                i2 = (i + 1) % seg
                faces.append((j * seg + i, j * seg + i2, (j + 1) * seg + i2, (j + 1) * seg + i))
        if close_bot and prof[0][0] > 1e-4:
            faces.append(tuple(reversed(range(seg))))
        if close_top and prof[-1][0] > 1e-4:
            faces.append(tuple((n - 1) * seg + i for i in range(seg)))
        self.add(verts, faces, mat, smooth=smooth, var=var)

    def grid(self, rows, mat, var=None, smooth=False, closed_u=False):
        """rows: list of lists of Vectors (same length) -> quad grid."""
        nu = len(rows[0])
        verts = [p for r in rows for p in r]
        faces = []
        for j in range(len(rows) - 1):
            for i in range(nu - (0 if closed_u else 1)):
                i2 = (i + 1) % nu
                faces.append((j * nu + i, j * nu + i2, (j + 1) * nu + i2, (j + 1) * nu + i))
        self.add(verts, faces, mat, smooth=smooth, var=var)

    # ---------------------------------------------------------------- to Blender
    def to_object(self, parent, coll, materials, web=False):
        me = bpy.data.meshes.new(self.name)
        me.from_pydata([tuple(p) for p in self.v], [], self.f)
        me.polygons.foreach_set("material_index", self.fm)
        me.polygons.foreach_set("use_smooth", self.fs)
        for m in self.mats:
            me.materials.append(materials[m])
        at = me.attributes.new("pvar", "FLOAT", "POINT")
        at.data.foreach_set("value", self.var)
        ca = me.color_attributes.new("Col", "BYTE_COLOR", "POINT")
        cols = []
        for x in self.var:
            g = 0.80 + 0.20 * x
            cols.extend((g, g * (0.985 + 0.015 * x), g * (0.97 + 0.03 * x), 1.0))
        ca.data.foreach_set("color", cols)
        me.color_attributes.active_color = ca
        me.update()
        ob = bpy.data.objects.new(self.name, me)
        coll.objects.link(ob)
        ob.parent = parent
        return ob


# =============================================================================================== materials
def _node(nt, typ, loc=(0, 0), **kw):
    n = nt.nodes.new(typ)
    n.location = loc
    for k, v in kw.items():
        setattr(n, k, v)
    return n


def _inp(node, *names):
    for nm in names:
        s = node.inputs.get(nm)
        if s is not None:
            return s
    return None


def make_materials(detail):
    mats = {}
    for name, (rgb, rough, metal) in MAT_SPECS.items():
        mname = name if detail == "high" else name + "_web"
        m = bpy.data.materials.get(mname)
        if m is None:
            m = bpy.data.materials.new(mname)
        m.use_nodes = True
        nt = m.node_tree
        for n in list(nt.nodes):
            nt.nodes.remove(n)
        out = _node(nt, "ShaderNodeOutputMaterial", (600, 0))
        bsdf = _node(nt, "ShaderNodeBsdfPrincipled", (300, 0))
        nt.links.new(bsdf.outputs[0], out.inputs["Surface"])
        bsdf.inputs["Base Color"].default_value = (*rgb, 1)
        bsdf.inputs["Roughness"].default_value = rough
        bsdf.inputs["Metallic"].default_value = metal
        m.diffuse_color = (*rgb, 1)
        m["pagoda_role"] = name[4:].lower()
        if detail == "high":
            _painterly(nt, bsdf, name, rgb, rough)
        else:
            # web: plain PBR base colour x vertex colour (per-element tint), restylable in Three.js
            ca = _node(nt, "ShaderNodeVertexColor", (-300, 100))
            ca.layer_name = "Col"
            mul = _node(nt, "ShaderNodeMix", (0, 100), data_type="RGBA", blend_type="MULTIPLY")
            mul.inputs["Factor"].default_value = 1.0
            mul.inputs["A"].default_value = (*rgb, 1)
            nt.links.new(ca.outputs["Color"], mul.inputs["B"])
            nt.links.new(mul.outputs["Result"], bsdf.inputs["Base Color"])
        mats[name] = m
    return mats


def _painterly(nt, bsdf, name, rgb, rough):
    """procedural, softly varied 'storybook realism' shading (Cycles)."""
    L = nt.links
    tc = _node(nt, "ShaderNodeTexCoord", (-1400, 0))
    attr = _node(nt, "ShaderNodeAttribute", (-1400, -300), attribute_name="pvar")
    bev = _node(nt, "ShaderNodeBevel", (-200, -500))
    bev.inputs["Radius"].default_value = 0.012 if name not in ("PAG_Stone",) else 0.03
    bump = _node(nt, "ShaderNodeBump", (100, -400))
    L.new(bev.outputs["Normal"], bump.inputs["Normal"])
    L.new(bump.outputs["Normal"], bsdf.inputs["Normal"])

    def noise(scale, detail=4.0, rough_=0.55, loc=(-1100, 200), distort=0.0):
        n = _node(nt, "ShaderNodeTexNoise", loc)
        n.inputs["Scale"].default_value = scale
        n.inputs["Detail"].default_value = detail
        _inp(n, "Roughness").default_value = rough_
        if _inp(n, "Distortion"):
            n.inputs["Distortion"].default_value = distort
        L.new(tc.outputs["Object"], n.inputs["Vector"])
        return n

    def ramp(fac_socket, c0, c1, loc=(-500, 200)):
        mx = _node(nt, "ShaderNodeMix", loc, data_type="RGBA")
        L.new(fac_socket, mx.inputs["Factor"])
        mx.inputs["A"].default_value = (*c0, 1)
        mx.inputs["B"].default_value = (*c1, 1)
        return mx

    def mixc(fac, a_sock, b_col, loc, blend="MIX"):
        mx = _node(nt, "ShaderNodeMix", loc, data_type="RGBA", blend_type=blend)
        if isinstance(fac, float):
            mx.inputs["Factor"].default_value = fac
        else:
            L.new(fac, mx.inputs["Factor"])
        L.new(a_sock, mx.inputs["A"])
        mx.inputs["B"].default_value = (*b_col, 1)
        return mx

    sc = lambda c, f: tuple(min(1.0, x * f) for x in c)  # noqa: E731
    if name in ("PAG_Wood", "PAG_WoodLight"):
        wave = _node(nt, "ShaderNodeTexWave", (-1100, -100))
        wave.inputs["Scale"].default_value = 9.0
        wave.inputs["Distortion"].default_value = 6.0
        wave.inputs["Detail"].default_value = 3.0
        L.new(tc.outputs["Object"], wave.inputs["Vector"])
        n1 = noise(1.6, 5, 0.6, (-1100, 250))
        c = ramp(n1.outputs["Fac"], sc(rgb, 0.7), sc(rgb, 1.45), (-800, 200))
        c2 = mixc(wave.outputs["Fac"], c.outputs["Result"], sc(rgb, 0.75), (-600, 150))
        c2.inputs["Factor"].default_value = 0.35
        L.new(wave.outputs["Fac"], c2.inputs["Factor"])
        # per-element tone (hand-cut timber) + grey weathering
        c3 = mixc(attr.outputs["Fac"], c2.outputs["Result"], sc(rgb, 1.5), (-400, 100))
        mr = _node(nt, "ShaderNodeMath", (-600, -250), operation="MULTIPLY")
        L.new(attr.outputs["Fac"], mr.inputs[0])
        mr.inputs[1].default_value = 0.45
        L.new(mr.outputs[0], c3.inputs["Factor"])
        n2 = noise(0.35, 3, 0.5, (-1100, 500))
        wr = _node(nt, "ShaderNodeMapRange", (-800, 450))
        L.new(n2.outputs["Fac"], wr.inputs["Value"])
        wr.inputs["From Min"].default_value = 0.5
        wr.inputs["From Max"].default_value = 0.75
        wr.inputs["To Max"].default_value = 0.35
        c4 = mixc(wr.outputs["Result"], c3.outputs["Result"], (0.085, 0.078, 0.07), (-200, 150))
        L.new(c4.outputs["Result"], bsdf.inputs["Base Color"])
        L.new(wave.outputs["Fac"], bump.inputs["Height"])
        bump.inputs["Strength"].default_value = 0.12
    elif name == "PAG_Plaster":
        n1 = noise(2.5, 6, 0.6)
        c = ramp(n1.outputs["Fac"], sc(rgb, 0.82), sc(rgb, 1.05))
        n2 = noise(0.8, 4, 0.6, (-1100, 500))
        dirt = mixc(n2.outputs["Fac"], c.outputs["Result"], (0.40, 0.36, 0.30), (-250, 200))
        dr = _node(nt, "ShaderNodeMapRange", (-600, 500))
        L.new(n2.outputs["Fac"], dr.inputs["Value"])
        dr.inputs["From Min"].default_value = 0.55
        dr.inputs["From Max"].default_value = 0.8
        dr.inputs["To Max"].default_value = 0.45
        L.new(dr.outputs["Result"], dirt.inputs["Factor"])
        L.new(dirt.outputs["Result"], bsdf.inputs["Base Color"])
        L.new(n1.outputs["Fac"], bump.inputs["Height"])
        bump.inputs["Strength"].default_value = 0.08
    elif name == "PAG_Kawara":
        n1 = noise(3.0, 4, 0.5)
        c = ramp(n1.outputs["Fac"], sc(rgb, 0.72), sc(rgb, 1.35))
        c3 = mixc(attr.outputs["Fac"], c.outputs["Result"], sc(rgb, 1.45), (-300, 100))
        mr = _node(nt, "ShaderNodeMath", (-600, -250), operation="MULTIPLY")
        L.new(attr.outputs["Fac"], mr.inputs[0])
        mr.inputs[1].default_value = 0.4
        L.new(mr.outputs[0], c3.inputs["Factor"])
        n2 = noise(0.5, 3, 0.5, (-1100, 500))
        lich = mixc(n2.outputs["Fac"], c3.outputs["Result"], (0.13, 0.14, 0.10), (-150, 150))
        lr = _node(nt, "ShaderNodeMapRange", (-600, 500))
        L.new(n2.outputs["Fac"], lr.inputs["Value"])
        lr.inputs["From Min"].default_value = 0.6
        lr.inputs["From Max"].default_value = 0.8
        lr.inputs["To Max"].default_value = 0.5
        L.new(lr.outputs["Result"], lich.inputs["Factor"])
        L.new(lich.outputs["Result"], bsdf.inputs["Base Color"])
        L.new(n1.outputs["Fac"], bump.inputs["Height"])
        bump.inputs["Strength"].default_value = 0.1
        rr = _node(nt, "ShaderNodeMapRange", (0, -150))
        L.new(n2.outputs["Fac"], rr.inputs["Value"])
        rr.inputs["To Min"].default_value = 0.42
        rr.inputs["To Max"].default_value = 0.7
        L.new(rr.outputs["Result"], bsdf.inputs["Roughness"])
    elif name == "PAG_Bronze":
        n1 = noise(4.0, 6, 0.6)
        pat = _node(nt, "ShaderNodeMapRange", (-800, 200))
        L.new(n1.outputs["Fac"], pat.inputs["Value"])
        pat.inputs["From Min"].default_value = 0.42
        pat.inputs["From Max"].default_value = 0.62
        c = ramp(pat.outputs["Result"], rgb, (0.10, 0.13, 0.105), (-500, 200))
        L.new(c.outputs["Result"], bsdf.inputs["Base Color"])
        mt = _node(nt, "ShaderNodeMapRange", (-300, -150))
        L.new(pat.outputs["Result"], mt.inputs["Value"])
        mt.inputs["To Min"].default_value = 0.75
        mt.inputs["To Max"].default_value = 0.15
        L.new(mt.outputs["Result"], bsdf.inputs["Metallic"])
        L.new(n1.outputs["Fac"], bump.inputs["Height"])
        bump.inputs["Strength"].default_value = 0.15
    elif name == "PAG_Stone":
        n1 = noise(18.0, 3, 0.7)
        n2 = noise(1.2, 4, 0.6, (-1100, 500))
        c = ramp(n1.outputs["Fac"], sc(rgb, 0.75), sc(rgb, 1.2))
        d = mixc(n2.outputs["Fac"], c.outputs["Result"], (0.17, 0.17, 0.14), (-250, 150))
        dr = _node(nt, "ShaderNodeMapRange", (-600, 500))
        L.new(n2.outputs["Fac"], dr.inputs["Value"])
        dr.inputs["From Min"].default_value = 0.5
        dr.inputs["From Max"].default_value = 0.8
        dr.inputs["To Max"].default_value = 0.5
        L.new(dr.outputs["Result"], d.inputs["Factor"])
        c3 = mixc(attr.outputs["Fac"], d.outputs["Result"], sc(rgb, 1.25), (-100, 100))
        c3.inputs["Factor"].default_value = 0.3
        L.new(c3.outputs["Result"], bsdf.inputs["Base Color"])
        L.new(n1.outputs["Fac"], bump.inputs["Height"])
        bump.inputs["Strength"].default_value = 0.2


# =============================================================================================== roof geometry
class Roof:
    """Square hip roof of one storey in the pagoda-local frame.

    Face-wedge parameterisation: point = d*n_k + a*t_k with |a| <= d; s = a/d in [-1, 1] (0 mid-face, +-1 hip).
    E  = height of the eave soffit (underside of the edge) at mid-face; eave edge plan distance d_e(s);
    the tile surface rises with a concave (照り) profile from the eave to d_top; corners lift by CORNER_LIFT.
    """

    def __init__(self, E, W, d_top, z_top, top=False):
        self.E, self.W, self.d_top, self.z_top, self.top = E, W, d_top, z_top, top
        self.rise = z_top - (E + EAVE_THICK)
        self.pw = 1.75 if top else 1.45

    def de(self, s):
        return self.W / 2 - PLAN_KICK * (1 - s * s)

    def lift(self, s, v):
        return CORNER_LIFT * (abs(s) ** 2.6) * ((1 - v) ** 1.4)

    def z_sv(self, s, v):
        """tile-surface height at (s, v)."""
        return self.E + EAVE_THICK + self.rise * (v ** self.pw) + self.lift(s, v)

    def pt_sv(self, k, s, v, dz=0.0):
        de = self.de(s)
        d = de + (self.d_top - de) * v
        return fp(k, d, s * d, self.z_sv(s, v) + dz), d

    def sv_of(self, d, a):
        s = max(-1.0, min(1.0, a / d)) if d > 1e-6 else 0.0
        de = self.de(s)
        v = (de - d) / (de - self.d_top)
        return s, max(0.0, min(1.0, v))

    def z_da(self, d, a):
        s, v = self.sv_of(d, a)
        return self.z_sv(s, v)

    def soffit(self, d, a):
        return self.z_da(d, a) - EAVE_THICK

    def d_eave(self, a):
        """plan distance of the eave edge along the row at offset a (fixed-point)."""
        d = self.W / 2
        for _ in range(8):
            d = self.de(max(-1.0, min(1.0, a / d)))
        return d


# =============================================================================================== builders
def build_platform(mb, detail):
    hw = PLATFORM_W / 2
    zt = PLATFORM_H
    zb = -0.65                                     # buried skirt (terrain under the footprint is 60.8-61.6 m)
    # core + cap stones (葛石) + base course (地覆石)
    mb.box(-hw + 0.06, hw - 0.06, -hw + 0.06, hw - 0.06, zb, zt - 0.16, "PAG_Stone", 0.4)
    mb.box(-hw - 0.08, hw + 0.08, -hw - 0.08, hw + 0.08, zb, 0.12, "PAG_Stone", 0.2)
    mb.box(-hw, hw, -hw, hw, zt - 0.17, zt, "PAG_Stone", 0.55)
    if detail == "high":
        # face panels (羽目石) between posts (束石): slightly recessed slabs give the kerb rhythm
        for k in range(4):
            n = 7
            for i in range(n):
                a0 = -hw + 0.1 + i * (2 * hw - 0.2) / n
                a1 = a0 + (2 * hw - 0.2) / n - 0.035
                if abs((a0 + a1) / 2) < 1.25:
                    continue
                mb.fbox(k, hw - 0.04, hw + 0.012, a0, a1, 0.13, zt - 0.18, "PAG_Stone")
            # cap stone joints
            for i in range(9):
                a0 = -hw + i * (2 * hw) / 9
                mb.fbox(k, hw - 0.42, hw + 0.01, a0 + 0.012, a0 + 2 * hw / 9 - 0.012, zt - 0.16, zt + 0.012, "PAG_Stone")
    # steps (4 sides, inferred)
    nr = 4
    for k in range(4):
        for i in range(nr):
            z1 = zt - (i + 1) * zt / nr + zt / nr
            d1 = hw + 0.34 * (i + 1)
            mb.fbox(k, hw - 0.1, d1, -1.05, 1.05, zb if i == nr - 1 else z1 - zt / nr - 0.05, z1 - 0.0 if i else zt - 0.005,
                    "PAG_Stone", var=0.3 + 0.1 * i)
        if detail == "high":   # side cheek stones
            for sgn in (-1, 1):
                mb.fbox(k, hw - 0.1, hw + 0.34 * nr + 0.05, sgn * 1.05, sgn * 1.3, zb, 0.18, "PAG_Stone")


def build_body(mb_body, mb_brk, k_storey, z_floor, Wt, B, roof, detail, web):
    """columns, sills, doors, renji windows, plaster, head ties, three-step brackets, ceiling boards."""
    hb = B / 2
    col_r = [0.22, 0.19, 0.18, 0.17, 0.16][k_storey]
    H = Wt - z_floor
    seg = 6 if web else 12
    z_nage = z_floor + min(H * 0.78, H - 0.55, 3.0)     # 内法長押 (upper lintel); doors ~2.8 m max
    z_head0 = Wt - 0.30                                  # 頭貫 (head tie)
    # interior core (closed, dark), keeps the body opaque
    mb_body.box(-hb + 0.12, hb - 0.12, -hb + 0.12, hb - 0.12, z_floor, Wt + 0.95, "PAG_Dark", 0.5)
    for k in range(4):
        # columns: corner (a=-hb) + two inner columns per face
        for a in (-hb, -hb / 3, hb / 3):
            p0 = fp(k, hb, a, z_floor)
            mb_body.cyl(p0, p0 + V(0, 0, H), col_r, col_r * 0.96, seg, "PAG_Wood")
        # sill (地覆), lintel (長押), head tie (頭貫) along the face
        mb_body.fbox(k, hb - 0.13, hb + 0.13, -hb - 0.12, hb + 0.12, z_floor, z_floor + 0.22, "PAG_Wood")
        mb_body.fbox(k, hb - 0.02, hb + 0.17, -hb, hb, z_nage, z_nage + 0.2, "PAG_Wood")
        mb_body.fbox(k, hb - 0.12, hb + 0.12, -hb - 0.18, hb + 0.18, z_head0, Wt, "PAG_Wood")
        # small wall (小壁) between lintel and head tie: white plaster
        z_pl = max(z_nage + 0.2, z_head0 - 0.55)
        if z_pl > z_nage + 0.25:
            mb_body.fbox(k, hb - 0.07, hb - 0.01, -hb, hb, z_nage + 0.2, z_pl, "PAG_Wood", 0.7)
            mb_body.fbox(k, hb - 0.02, hb + 0.12, -hb, hb, z_pl - 0.14, z_pl, "PAG_Wood")
        mb_body.fbox(k, hb - 0.06, hb - 0.0, -hb, hb, z_pl, z_head0, "PAG_Plaster")
        bw = B / 3
        for j, ac in enumerate((-bw, 0.0, bw)):
            a0, a1 = ac - bw / 2 + col_r * 0.85, ac + bw / 2 - col_r * 0.85
            zf0 = z_floor + 0.22
            if j == 1:
                # plank double door (板唐戸) with frame, battens and stud rows
                mb_body.fbox(k, hb - 0.10, hb - 0.03, a0, a1, zf0, z_nage, "PAG_WoodLight")
                if not web:
                    am = (a0 + a1) / 2
                    mb_body.fbox(k, hb - 0.04, hb + 0.03, am - 0.02, am + 0.02, zf0, z_nage, "PAG_Wood")
                    mb_body.fbox(k, hb - 0.04, hb + 0.05, a0 - 0.06, a0 + 0.04, zf0, z_nage, "PAG_Wood")
                    mb_body.fbox(k, hb - 0.04, hb + 0.05, a1 - 0.04, a1 + 0.06, zf0, z_nage, "PAG_Wood")
                    for zz in (zf0 + 0.18, z_nage - 0.22, (zf0 + z_nage) / 2):
                        mb_body.fbox(k, hb - 0.04, hb + 0.0, a0, a1, zz - 0.06, zz + 0.06, "PAG_Wood")
                    if k_storey <= 1:
                        for zz in (zf0 + 0.45, (zf0 + z_nage) / 2 + 0.35, z_nage - 0.5):
                            for sgn in (-1, 1):
                                for q in range(4):
                                    aa = am + sgn * (0.12 + q * (bw / 2 - 0.3) / 3.5)
                                    mb_body.fbox(k, hb - 0.03, hb + 0.0, aa - 0.025, aa + 0.025, zz - 0.025, zz + 0.025,
                                                 "PAG_Bronze", 0.3)
            else:
                # renji lattice window (連子窓) over a plank dado
                zw0 = z_floor + max(0.55, (z_nage - z_floor) * 0.42)
                mb_body.fbox(k, hb - 0.08, hb - 0.03, a0, a1, zf0, zw0, "PAG_Wood")
                mb_body.fbox(k, hb - 0.03, hb + 0.07, a0, a1, zw0 - 0.1, zw0, "PAG_Wood")
                mb_body.fbox(k, hb - 0.25, hb - 0.2, a0, a1, zw0, z_nage, "PAG_Dark")
                if web:
                    mb_body.fbox(k, hb - 0.07, hb - 0.03, a0, a1, zw0, z_nage, "PAG_Wood", 0.9)
                else:
                    nbar = max(5, int((a1 - a0) / 0.115))
                    for i in range(nbar):
                        aa = a0 + (i + 0.5) * (a1 - a0) / nbar
                        c = fp(k, hb - 0.05, aa, (zw0 + z_nage) / 2)
                        e = 0.028
                        mb_body.obox(c, (FACE_N[k] + FACE_T[k]) * (e * 0.7071), (FACE_T[k] - FACE_N[k]) * (e * 0.7071),
                                     V(0, 0, (z_nage - zw0) / 2), "PAG_Wood", skip=("t", "b"))
    # ---------------------------------------------------------------- bracket sets (組物): three-step, wayo
    bs = BRACKET_SCALE[k_storey]
    tmp = MB("tmp", skip_top=mb_brk.skip_top)
    build_brackets(tmp, Wt, B, roof, detail, web, k_storey)
    tmp.v = [V(p.x, p.y, Wt + (p.z - Wt) * bs) for p in tmp.v]     # storey-specific bracket scale (vertical)
    b0 = len(mb_brk.v)
    mb_brk.v += tmp.v
    mb_brk.var += tmp.var
    for fc, m, sm in zip(tmp.f, tmp.fm, tmp.fs):
        mb_brk.f.append(tuple(b0 + i for i in fc))
        mb_brk.fm.append(mb_brk.mi(tmp.mats[m]))
        mb_brk.fs.append(sm)


def build_brackets(mb, Wt, B, roof, detail, web, ks):
    hb = B / 2
    P = BRACKET_PROJ
    z = [Wt, Wt + 0.22, Wt + 0.52, Wt + 0.82]       # daito top / tier tops
    zp = Wt + 1.08                                  # purlin (丸桁) bottom
    zpt = zp + 0.24
    blk = "PAG_Wood"
    for k in range(4):
        # continuous members along the face (通肘木) at the wall line and at each projection
        for (dd, z0, z1) in ((0.0, z[1], z[1] + 0.16), (0.0, z[2], z[2] + 0.16), (0.0, z[3], z[3] + 0.16),
                             (P * 0.62, z[3], z[3] + 0.16), (P, zp, zpt)):
            ext = hb + dd + 0.25
            mb.fbox(k, hb + dd - 0.09, hb + dd + 0.09, -ext, ext, z0, z1, blk)
        # plaster between bracket blocks (wall line, observed white patches)
        mb.fbox(k, hb - 0.05, hb + 0.0, -hb, hb, Wt, z[3] + 0.16, "PAG_Plaster")
        # ceiling board (軒天井) from wall line up to purlin: closes the bracket zone
        mb.beam(fp(k, hb, 0, z[3] + 0.2), fp(k, hb + P, 0, zpt), 2 * hb + 2 * P, 0.04, "PAG_Wood", var=0.15)
        # column-top bracket sets at the 4 column lines + corner
        for a in (-hb, -hb / 3, hb / 3, hb):
            corner = abs(abs(a) - hb) < 1e-6
            if a != hb:   # daito (大斗) once per column
                mb.fbox(k, hb - 0.2, hb + 0.2, a - 0.2, a + 0.2, z[0], z[1], blk)
                if corner and not web:
                    pass
            # transverse arms (肘木) along the face with bearing blocks (巻斗)
            if not corner or a == -hb:
                for (dd, zt_) in (((0.0, z[1]), (P * 0.31, z[2]), (P * 0.62, z[3])) if not web else ((0.0, z[1]),)):
                    if dd > 0 or not corner:
                        mb.fbox(k, hb + dd - 0.08, hb + dd + 0.08, a - 0.5, a + 0.5, zt_, zt_ + 0.15, blk)
                    if not web:
                        for aa in (a - 0.42, a + 0.42):
                            if abs(aa) <= hb + 0.45:
                                mb.fbox(k, hb + dd - 0.12, hb + dd + 0.12, aa - 0.12, aa + 0.12, zt_ + 0.15, zt_ + 0.30, blk)
            # projecting arms (outward) + blocks
            for (d1, zt_) in ((P * 0.31, z[1]), (P * 0.62, z[2]), (P, z[3])):
                mb.fbox(k, hb - 0.3, hb + d1 + 0.14, a - 0.08, a + 0.08, zt_, zt_ + 0.16, blk)
                if not web or d1 == P:
                    mb.fbox(k, hb + d1 - 0.12, hb + d1 + 0.12, a - 0.12, a + 0.12, zt_ + 0.16, zt_ + 0.30, blk)
            # tail rafter (尾垂木): inclined, protruding outward-down below the third step
            p0 = fp(k, hb - 0.7, a, z[3] + 0.45)
            p1 = fp(k, hb + P * 0.9, a, z[2] + 0.02)
            mb.beam(p0, p1, 0.17, 0.2, blk)
            if detail == "high":
                # parallel arm under the purlin (三斗) at the outer step
                mb.fbox(k, hb + P - 0.08, hb + P + 0.08, a - 0.48, a + 0.48, z[3] + 0.16 + 0.0, z[3] + 0.31, blk)
                for aa in (a - 0.4, a, a + 0.4):
                    mb.fbox(k, hb + P - 0.11, hb + P + 0.11, aa - 0.11, aa + 0.11, z[3] + 0.31, zp, blk)
        # intercolumnar struts (間斗束) at bay centres
        for a in (-B / 3, 0.0, B / 3):
            mb.fbox(k, hb - 0.07, hb + 0.07, a - 0.07, a + 0.07, Wt, z[2], blk)
            mb.fbox(k, hb - 0.12, hb + 0.12, a - 0.13, a + 0.13, z[2] - 0.14, z[2], blk)
        # corner diagonal bracket arm + hip tail rafter (隅尾垂木)
        dg = (FACE_N[k] + FACE_T[k]).normalized()
        cpt = fp(k, hb, hb, 0)
        for (L_, zt_) in ((P * 0.44, z[1]), (P * 0.88, z[2]), (P * 1.41, z[3])):
            p0 = V(cpt.x, cpt.y, zt_ + 0.08) - dg * 0.3
            p1 = V(cpt.x, cpt.y, zt_ + 0.08) + dg * L_
            mb.beam(p0, p1, 0.17, 0.16, blk)
            q = V(cpt.x, cpt.y, zt_ + 0.23) + dg * L_
            mb.obox(q, dg * 0.13, dg.cross(UP) * 0.13, V(0, 0, 0.07), blk)
        p0 = V(cpt.x, cpt.y, z[3] + 0.5) - dg * 0.8
        p1 = V(cpt.x, cpt.y, z[2] + 0.0) + dg * (P * 1.3)
        mb.beam(p0, p1, 0.2, 0.22, blk)


def build_rafters(mb, roof, B, detail, web, rng):
    """two tiers of parallel rafters (二軒繁垂木), hip rafters (隅木), kioi beam, fascia."""
    hb = B / 2
    pitch = 0.27 if not web else 0.54
    dp = hb + BRACKET_PROJ
    rw, rh = 0.105, 0.13
    k_split = 0.92                       # flying rafters project this far beyond the kioi (木負)
    for k in range(4):
        dmax = roof.d_eave(0)
        n = int(dmax / pitch) + 1
        for i in range(-n, n + 1):
            a = i * pitch + (pitch / 2 if web else 0)
            de = roof.d_eave(a)
            dk = de - k_split
            jit = rng.uniform(-0.006, 0.006)
            # base rafter (地垂木): from inside the purlin to the kioi line
            d0 = max(dp - 0.35, abs(a) + 0.05)
            if not web and dk - d0 > 0.15:
                p0 = fp(k, d0, a, roof.soffit(d0, a) - rh / 2 - 0.16 + jit)
                p1 = fp(k, dk + 0.04, a, roof.soffit(dk, a) - rh / 2 - 0.16 + jit)
                mb.beam(p0, p1, rw, rh, "PAG_Wood", skip=("t", "-x") if web else ())
            # flying rafter (飛檐垂木): kioi -> eave edge (start clipped by the hip)
            d0 = max(dk - 0.3, abs(a) + 0.05)
            if de - 0.03 - d0 > 0.12:
                p0 = fp(k, d0, a, roof.soffit(d0, a) - rh / 2 + jit)
                p1 = fp(k, de - 0.03, a, roof.soffit(de - 0.03, a) - rh / 2 + jit)
                mb.beam(p0, p1, rw * 0.95, rh * 0.95, "PAG_Wood", skip=("t", "-x") if web else ())
        # kioi beam (木負) and kayaoi/fascia (茅負) segmented along the curve
        nseg = 6 if web else 22
        prev_k = prev_f = None
        for j in range(nseg + 1):
            s = -1 + 2 * j / nseg
            de = roof.de(s)
            dk = de - k_split
            ak = s * dk
            pk = fp(k, dk, ak, roof.soffit(dk, ak) - 0.16 - 0.04)
            if prev_k is not None:
                mb.beam(prev_k, pk, 0.13, 0.17, "PAG_Wood", var=0.2, skip=("t",) if web else ())
            prev_k = pk
        # hip rafter (隅木): from body corner to eave corner, under the hip line
        dg_d0 = hb
        de1 = roof.de(1.0)
        p0 = fp(k, dg_d0, dg_d0, roof.soffit(dg_d0 + 0.01, dg_d0) - 0.2)
        p1 = fp(k, de1 + 0.05, de1 + 0.05, roof.soffit(de1 - 0.02, de1 - 0.02) - 0.12)
        mb.beam(p0, p1, 0.22, 0.28, "PAG_Wood", var=0.1)


def build_roof(mb_t, mb_s, roof, detail, web, rng):
    """tile surface with stepped courses, round-tile rows, end discs, eave band, soffit, hip ridges, onigawara."""
    course = 0.30
    ns = 28 if web else 44
    for k in range(4):
        # ------------------------------------------------ tile bed (flat tiles, stepped courses)
        slope_len = math.hypot(roof.de(0) - roof.d_top, roof.rise)
        nc = max(4, int(slope_len / course))
        rows = []
        vs = []
        if web:
            vs = [(j / (nc // 2 + 1), 0.0) for j in range(nc // 2 + 2)]
        else:
            for j in range(nc):
                v0, v1 = j / nc, (j + 1) / nc
                vs.append((v0, 0.035))
                vs.append((v1 - 0.25 / nc, 0.0))
            vs.append((1.0, 0.0))
        for (v, dz) in vs:
            row = []
            for i in range(ns + 1):
                s = -1 + 2 * i / ns
                p, _ = roof.pt_sv(k, s, min(v, 1.0), dz)
                row.append(p)
            rows.append(row)
        mb_t.grid(rows, "PAG_Kawara", var=0.45, smooth=web)
        # ------------------------------------------------ soffit underside (野地) + eave band
        srow = []
        for (v) in (0.0, 0.25, 0.55, 1.0):
            r = []
            for i in range(ns + 1):
                s = -1 + 2 * i / ns
                p, _ = roof.pt_sv(k, s, v, -EAVE_THICK)
                r.append(p)
            srow.append(r)
        mb_s.grid(list(reversed(srow)), "PAG_Wood", var=0.05, smooth=web)
        band_w, band_k = [], []
        for i in range(ns + 1):
            s = -1 + 2 * i / ns
            p, d = roof.pt_sv(k, s, 0.0, 0.0)
            band_k.append((fp(k, d + 0.02, s * (d + 0.02), p.z - 0.17), fp(k, d + 0.03, s * (d + 0.03), p.z + 0.03)))
            band_w.append((fp(k, d - 0.02, s * (d - 0.02), p.z - EAVE_THICK - 0.02),
                           fp(k, d + 0.0, s * d, p.z - 0.15)))
        mb_t.grid([[b[0] for b in band_k], [b[1] for b in band_k]], "PAG_Kawara", var=0.3)
        mb_s.grid([[b[0] for b in band_w], [b[1] for b in band_w]], "PAG_Wood", var=0.15)
        # ------------------------------------------------ round tiles (丸瓦) rows + tomoe end discs
        pitch = 0.27 if not web else 0.54
        dmax = roof.d_eave(0)
        n = int(dmax / pitch) + 1
        rr = 0.085
        nsemi = 5 if not web else 2
        for i in range(-n, n + 1):
            a = i * pitch + pitch / 2
            de = roof.d_eave(a)
            d_start = max(roof.d_top + 0.02, abs(a) + 0.18)
            if de - d_start < 0.25:
                continue
            L = de - d_start
            nsamp = max(3, int(L / (0.42 if not web else 1.0)) + 1)
            wob = rng.uniform(-0.012, 0.012)
            ring_rows = []
            for j in range(nsamp + 1):
                d = de - j * L / nsamp
                zc = roof.z_da(d, a) + 0.025 + (wob if 0 < j < nsamp else 0)
                ring = []
                for q in range(nsemi + 1):
                    th = math.pi * q / nsemi
                    ring.append(fp(k, d, a + rr * math.cos(th), zc + rr * 0.85 * math.sin(th)))
                ring_rows.append(ring)
            mb_t.grid(ring_rows, "PAG_Kawara", var=rng.uniform(0.2, 0.9), smooth=True)
            if True:
                d = de + 0.02
                zc = roof.z_da(de, a) + 0.025
                c = fp(k, d, a, zc - 0.01)
                cb = fp(k, d - 0.06, a, zc - 0.01)
                if web:   # flat end disc as a single outward quad
                    t_, n_ = FACE_T[k] * (rr * 1.1), V(0, 0, rr * 1.1)
                    mb_t.add([c - t_ - n_, c + t_ - n_, c + t_ + n_, c - t_ + n_], [(0, 1, 2, 3)], "PAG_Kawara", var=0.85)
                else:
                    mb_t.cyl(cb, c, rr * 1.12, rr * 1.12, 8, "PAG_Kawara", var=0.85, smooth=False)
        # ------------------------------------------------ hip ridge (隅棟) along s = +1 of face k
        hip = []
        de1 = roof.de(1.0)
        d_hi = (roof.d_top + 0.15) if not roof.top else 0.65
        nh = 12 if not web else 5
        for j in range(nh + 1):
            d = de1 - 0.32 - j * (de1 - 0.32 - d_hi) / nh
            hip.append(fp(k, d, d, roof.z_da(d, d * 0.9999) - 0.02))
        for j in range(nh):
            p0, p1 = hip[j], hip[j + 1]
            mb_t.beam(p0 + V(0, 0, 0.16), p1 + V(0, 0, 0.16), 0.34, 0.36, "PAG_Kawara", var=0.25, skip=("b",))
            if not web:
                mb_t.cyl(p0 + V(0, 0, 0.34), p1 + V(0, 0, 0.34), 0.1, 0.1, 8, "PAG_Kawara", var=0.6, caps=False)
        # onigawara (鬼瓦) at the lower hip end, facing outward along the diagonal, + toribusuma (鳥衾) tile
        dg = (FACE_N[k] + FACE_T[k]).normalized()
        base = hip[0] + V(0, 0, 0.14)
        side = dg.cross(UP).normalized()
        tilt = (dg * 0.25 + UP).normalized()
        mb_t.obox(base + dg * 0.04 + tilt * 0.22, dg * 0.05, side * 0.27, tilt * 0.26, "PAG_Kawara", var=0.12)
        if not web:
            # rounded upper lobes of the onigawara
            for sg in (-1, 1):
                mb_t.cyl(base + dg * 0.0 + tilt * 0.46 + side * (0.15 * sg), base + dg * 0.09 + tilt * 0.46 + side * (0.15 * sg),
                         0.12, 0.12, 8, "PAG_Kawara", var=0.12)
            tb0 = hip[1] + V(0, 0, 0.42)
            mb_t.cyl(tb0, tb0 + dg * 0.62 + V(0, 0, 0.30), 0.075, 0.06, 8, "PAG_Kawara", var=0.35)


def build_balcony(mb, B, z_floor, roof_below, detail, web):
    """railed balcony (縁 + 組高欄) around an upper storey."""
    hb = B / 2
    do = hb + BALCONY_W
    rail_d = do - 0.06
    for k in range(4):
        # floor boards + edge beam + skirt down to the roof below
        mb.fbox(k, hb - 0.02, do, -do, do, z_floor - 0.12, z_floor, "PAG_Wood", 0.6)
        mb.fbox(k, do - 0.12, do + 0.03, -do - 0.03, do + 0.03, z_floor - 0.45, z_floor - 0.05, "PAG_Wood", 0.3)
        if not web:   # balcony support brackets (腰組)
            for i in range(-4, 5):
                a = i * (2 * hb) / 8
                mb.fbox(k, do - 0.35, do - 0.05, a - 0.07, a + 0.07, z_floor - 0.42, z_floor - 0.12, "PAG_Wood")
        # railing: sill (地覆), mid rail (平桁), top rail (架木) with corner cross-overs (跳ね高欄)
        ext = rail_d + 0.18
        mb.fbox(k, rail_d - 0.06, rail_d + 0.06, -rail_d, rail_d, z_floor, z_floor + 0.1, "PAG_Wood")
        mb.fbox(k, rail_d - 0.04, rail_d + 0.04, -ext, ext, z_floor + 0.40, z_floor + 0.47, "PAG_Wood")
        p0, p1 = fp(k, rail_d, -ext, z_floor + 0.72), fp(k, rail_d, ext, z_floor + 0.72)
        if web:
            mb.beam(p0, p1, 0.07, 0.07, "PAG_Wood")
        else:
            mb.cyl(p0, p1, 0.04, 0.04, 6, "PAG_Wood", smooth=True)
            # upturned rail ends at the corner (反り)
            for sgn in (-1, 1):
                pe = fp(k, rail_d, sgn * ext, z_floor + 0.72)
                mb.cyl(pe, pe + FACE_T[k] * (sgn * 0.12) + V(0, 0, 0.06), 0.04, 0.03, 6, "PAG_Wood")
        # posts: tall struts (斗束) between mid & top rail, short between sill & mid rail
        n = 6 if not web else 3
        for i in range(n + 1):
            a = -rail_d + i * (2 * rail_d) / n
            mb.fbox(k, rail_d - 0.03, rail_d + 0.03, a - 0.03, a + 0.03, z_floor + 0.1, z_floor + 0.40, "PAG_Wood")
            mb.fbox(k, rail_d - 0.035, rail_d + 0.035, a - 0.035, a + 0.035, z_floor + 0.47, z_floor + 0.68, "PAG_Wood")
            if not web:
                mb.fbox(k, rail_d - 0.06, rail_d + 0.06, a - 0.06, a + 0.06, z_floor + 0.62, z_floor + 0.69, "PAG_Wood")


def build_bells(mb, roof, web):
    """futaku wind bells (風鐸) hanging from the four hip-rafter ends."""
    de1 = roof.de(1.0)
    for k in range(4):
        d = de1 - 0.28
        top = fp(k, d, d, roof.soffit(d, d * 0.9999) - 0.22)
        mb.cyl(top + V(0, 0, 0.06), top - V(0, 0, 0.12), 0.012, 0.012, 4, "PAG_Bronze", caps=False)
        c = top - V(0, 0, 0.12)
        seg = 8 if web else 14
        mb.lathe(c, [(0.03, 0.0), (0.06, -0.02), (0.085, -0.12), (0.115, -0.28), (0.12, -0.31)], seg, "PAG_Bronze",
                 var=0.4, close_top=True, close_bot=True)
        if not web:   # clapper + wind plate (風招)
            mb.cyl(c - V(0, 0, 0.28), c - V(0, 0, 0.42), 0.008, 0.008, 4, "PAG_Bronze", caps=False)
            mb.obox(c - V(0, 0, 0.5), V(0.07, 0, 0), V(0, 0.006, 0), V(0, 0, 0.08), "PAG_Bronze")


def build_sorin(mb, z0, height, web):
    """bronze finial from the roof top: roban, fukubachi, ukebana, 9 kurin rings, suien, ryusha, hoju.
    Part proportions read from File:Yasaka Pagoda (24922466195).jpg / c242 crop (roban ~0.8 m, rings span ~5.1 m,
    suien ~1.4 m, ryusha+hoju ~1.8 m) and scaled to `height` (estimated)."""
    sc = height / 10.95
    seg = 10 if web else 24

    def Z(h):
        return V(0, 0, z0 + h * sc)
    # roban (露盤): square stepped box sitting on the roof apex
    mb.box(-0.86, 0.86, -0.86, 0.86, z0 - 0.5, z0 + 0.14 * sc, "PAG_Bronze", 0.3)
    mb.box(-0.74, 0.74, -0.74, 0.74, z0 + 0.14 * sc, z0 + 0.72 * sc, "PAG_Bronze", 0.35)
    mb.box(-0.82, 0.82, -0.82, 0.82, z0 + 0.72 * sc, z0 + 0.84 * sc, "PAG_Bronze", 0.3)
    # fukubachi (覆鉢)
    prof = [(0.56 * math.cos(t * math.pi / 2 / 6), 0.84 * sc + 0.44 * sc * math.sin(t * math.pi / 2 / 6)) for t in range(7)]
    prof[-1] = (0.12, prof[-1][1])
    mb.lathe(V(0, 0, z0), prof, seg, "PAG_Bronze", var=0.4)
    # ukebana (請花): lotus bowl with petal lobes
    mb.lathe(V(0, 0, z0), [(0.14, 1.26 * sc), (0.32, 1.34 * sc), (0.5, 1.5 * sc), (0.56, 1.62 * sc), (0.45, 1.64 * sc)],
             seg if web else 32, "PAG_Bronze", var=0.5,
             rscale=None if web else (lambda t: 1.0 + 0.09 * abs(math.cos(4 * t))))
    # shaft (擦管)
    mb.cyl(Z(1.2), Z(9.1), 0.1, 0.085, 8 if web else 12, "PAG_Bronze", var=0.35)
    # kurin (九輪): 9 dished rings
    for i in range(9):
        zc = 2.05 + i * 0.64
        ro = 0.56 - 0.006 * i
        mb.lathe(V(0, 0, z0), [(0.11, (zc - 0.07) * sc), (ro * 0.9, (zc - 0.05) * sc), (ro, (zc + 0.0) * sc),
                               (ro * 0.96, (zc + 0.07) * sc), (0.11, (zc + 0.03) * sc)], seg, "PAG_Bronze", var=0.45)
        if not web:   # small hanging bells (宝鐸) at 4 points of each ring
            for q in range(4):
                t = q * math.pi / 2 + math.pi / 4
                p = V(ro * 0.93 * math.cos(t), ro * 0.93 * math.sin(t), z0 + (zc - 0.08) * sc)
                mb.lathe(p, [(0.0, -0.11), (0.04, -0.1), (0.035, -0.02), (0.0, 0.0)], 6, "PAG_Bronze", var=0.6)
    # suien (水煙): four openwork flame panels around the shaft
    zs0, zs1 = 7.75, 9.2
    for q in range(4):
        ang = q * math.pi / 2
        u = V(math.cos(ang), math.sin(ang), 0)
        outline = []
        nn = 10
        for j in range(nn + 1):
            t = j / nn
            r = 0.1 + 0.46 * math.sin(math.pi * min(1.0, t * 1.12)) * (1 - 0.3 * t)
            zz = zs0 + (zs1 - zs0) * t
            outline.append(V(0, 0, z0 + zz * sc) + u * (r + 0.05 * math.sin(t * 9)))
        for j in range(nn):
            mb.beam(outline[j], outline[j + 1], 0.04, 0.05, "PAG_Bronze", var=0.55)
        for j in range(1, nn, 2 if not web else 4):
            p = outline[j]
            mb.beam(V(0, 0, p.z) + u * 0.1, p, 0.03, 0.03, "PAG_Bronze", var=0.55)
    # ryusha (竜車) + hoju (宝珠) + finial point
    mb.lathe(V(0, 0, z0), [(0.06, 9.3 * sc), (0.2, 9.4 * sc), (0.23, 9.55 * sc), (0.2, 9.7 * sc), (0.06, 9.8 * sc)],
             seg, "PAG_Bronze", var=0.4)
    mb.lathe(V(0, 0, z0), [(0.06, 9.9 * sc), (0.2, 10.05 * sc), (0.25, 10.25 * sc), (0.19, 10.47 * sc), (0.07, 10.65 * sc),
                           (0.03, 10.78 * sc)], seg, "PAG_Bronze", var=0.35)
    mb.cyl(Z(10.78), Z(10.95), 0.03, 0.005, 6, "PAG_Bronze")


# =============================================================================================== layout
def layout(height_basis="evidence"):
    """vertical layout (pagoda-local z = height above GROUND_Z). Returns storeys list and sorin base."""
    scale = 1.0 if height_basis != "popular_46m" else POPULAR_HEIGHT / TOTAL_HEIGHT
    st = []
    z_floor = PLATFORM_H
    for i in range(5):
        B = BODY_W[i]
        E = EAVE_TOP[i] - EAVE_THICK          # soffit of the eave edge at mid-face
        top = i == 4
        if top:
            d_top, z_top = 0.62, SORIN_BASE
        else:
            d_top = BODY_W[i + 1] / 2 + BALCONY_W + 0.05
            z_top = E + EAVE_THICK + LOWER_ROOF_RISE   # roof meets the upper balcony
        roof = Roof(E, EAVE_W[i], d_top, z_top, top)
        # wall top so that purlin top + rafter depth meets the roof soffit at the purlin line
        dp = B / 2 + BRACKET_PROJ
        Wt = roof.soffit(dp, 0.0) - 0.16 - 0.13 - 1.32 * BRACKET_SCALE[i]
        st.append(dict(B=B, roof=roof, z_floor=z_floor, Wt=Wt, i=i))
        z_floor = z_top + 0.16                # balcony floor of the next storey (raised on koshi-gumi)
    return st, SORIN_BASE, scale


# =============================================================================================== main entry
def build_pagoda(collection=None, detail="high", height_basis="evidence", seed=8):
    """Build the hero pagoda at its real position. Returns the root empty 'LM_Yasaka_Pagoda_HERO'."""
    assert detail in ("high", "web")
    web = detail == "web"
    rng = random.Random(seed)
    random.seed(seed)
    scene = bpy.context.scene
    if collection is None:
        collection = bpy.data.collections.get("35_Landmarks") or scene.collection
    coll = bpy.data.collections.new("Yasaka_Pagoda_HERO" + ("" if not web else "_web"))
    collection.children.link(coll)
    mats = make_materials(detail)

    root = bpy.data.objects.new("LM_Yasaka_Pagoda_HERO", None)
    root.empty_display_type = "ARROWS"
    root.empty_display_size = 4
    coll.objects.link(root)
    storeys, apex, vscale = layout(height_basis)

    parts = []
    mb = MB("Yasaka_Platform")
    build_platform(mb, detail)
    parts.append(mb)
    for s in storeys:
        i = s["i"]
        n = i + 1
        mb_body = MB("Yasaka_S%d_Body" % n)
        mb_brk = MB("Yasaka_S%d_Bracketing" % n, skip_top=web)
        mb_raf = MB("Yasaka_S%d_Rafters" % n)
        mb_roof = MB("Yasaka_S%d_Roof" % n)
        mb_sof = mb_raf
        build_body(mb_body, mb_brk, i, s["z_floor"], s["Wt"], s["B"], s["roof"], detail, web)
        build_rafters(mb_raf, s["roof"], s["B"], detail, web, rng)
        build_roof(mb_roof, mb_sof, s["roof"], detail, web, rng)
        build_bells(mb_raf, s["roof"], web)
        parts += [mb_body, mb_brk, mb_raf, mb_roof]
        if i > 0:
            mb_bal = MB("Yasaka_S%d_Balcony" % n)
            build_balcony(mb_bal, s["B"], s["z_floor"], storeys[i - 1]["roof"], detail, web)
            parts.append(mb_bal)
    mb = MB("Yasaka_Sorin")
    build_sorin(mb, apex, TOTAL_HEIGHT - apex, web)
    parts.append(mb)

    tris = 0
    for p in parts:
        ob = p.to_object(root, coll, mats, web)
        ob["pagoda_part"] = p.name
        tris += sum(len(f) - 2 for f in p.f)
    # collision proxy: platform + lowest storey (simple boxes)
    cm = MB("LM_Yasaka_Pagoda_COLLIDER")
    hw = PLATFORM_W / 2
    cm.box(-hw - 0.1, hw + 0.1, -hw - 0.1, hw + 0.1, -0.65, PLATFORM_H, "PAG_Stone")
    b0 = storeys[0]
    hb = b0["B"] / 2 + 0.22
    cm.box(-hb, hb, -hb, hb, PLATFORM_H, b0["Wt"] + 0.9, "PAG_Stone")
    col = cm.to_object(root, coll, mats, web)
    col["collide"] = True
    col["collider_for"] = "LM_Yasaka_Pagoda_HERO"
    col.hide_render = True
    col.display_type = "WIRE"
    col.visible_camera = False
    col.visible_shadow = False

    if vscale != 1.0:
        root.scale = (vscale, vscale, vscale)
    root.location = (CENTRE_XY[0], CENTRE_XY[1], GROUND_Z)
    root.rotation_euler = (0.0, 0.0, math.radians(ROT_DEG))
    total = TOTAL_HEIGHT * vscale
    root["osm_id"] = "371717416"
    root["plateau_id"] = "bldg_2b477621-2b5c-480b-a960-d2b3972db237"
    root["plateau_buildingID"] = "26100-bldg-489160"
    root["wikidata"] = "Q858308"
    root["name_ja"] = "法観寺五重塔（八坂の塔）"
    root["height_m"] = round(total, 2)
    root["height_note"] = ("38.8 m incl. sorin = measured/derived (PLATEAU apex 28.7 m + photo-derived sorin; audit telephoto 39.2-40.0 m); "
                           "NDL 38.8 m entry = documented, source not retrievable here; ~46 m = disputed popular figure"
                           if height_basis == "evidence" else "uniformly scaled to the popular 46 m figure (disputed)")
    root["height_basis"] = height_basis
    root["height_confidence"] = "measured/derived" if height_basis == "evidence" else "disputed popular figure"
    root["sources"] = ("OSM way 371717416 (ODbL); PLATEAU 2025 Kyoto bldg_2b477621-2b5c-480b-a960-d2b3972db237 (LOD0 roof edge, "
                       "LOD2 tiers, measuredHeight 28.7); GSI DEM5A; docs/evidence/yasaka_pagoda_spec.json; NDL CRD 1000061716; "
                       "Wikimedia Commons photos listed in docs/evidence/yasaka_pagoda_model.md")
    root["evidence"] = json.dumps(EVIDENCE, ensure_ascii=False)
    root["detail"] = detail
    root["triangles"] = tris
    root["model_doc"] = "docs/evidence/yasaka_pagoda_model.md"
    return root


# =============================================================================================== script mode
def _look_at(cam, loc, target):
    d = Vector(target) - Vector(loc)
    cam.location = loc
    cam.rotation_euler = (math.atan2(math.hypot(d.x, d.y), -d.z), 0, math.atan2(d.y, d.x) - math.pi / 2)


def _hierarchy(root):
    out = [root]
    for c in root.children:
        out += _hierarchy(c)
    return out


def main():
    args = sys.argv[1:]
    sys.path.insert(0, os.path.join(ROOT, "pipeline"))
    from terrain_sample import ground  # noqa: E402
    gz = lambda x, y: float(ground(x, y))  # noqa: E731

    bpy.ops.wm.open_mainfile(filepath=os.path.join(HERE, "higashiyama_blockout.blend"))
    scene = bpy.context.scene
    ph = bpy.data.objects.get("LM_Yasaka_Pagoda_PLATEAU_LOD2")
    if ph:
        ph.hide_render = True
        ph.hide_viewport = True
        ph.hide_set(True)
    root = build_pagoda(detail="high")
    print("hero built: %d triangles" % root["triangles"])

    # ------------------------------------------------ pagoda-only library file
    os.makedirs(os.path.join(HERE, "assets"), exist_ok=True)
    coll = root.users_collection[0]
    out_lib = os.path.join(HERE, "assets", "hero_pagoda.blend")
    bpy.data.libraries.write(out_lib, {coll}, fake_user=True, compress=True)
    print("saved", out_lib)

    # ------------------------------------------------ renders
    if "--no-render" not in args:
        os.makedirs(os.path.join(ROOT, "renders"), exist_ok=True)
        final = "--final" in args
        scene.render.engine = "CYCLES"
        scene.cycles.device = "CPU"
        scene.cycles.samples = 64 if final else 20
        scene.cycles.use_denoising = True
        scene.render.resolution_x, scene.render.resolution_y = (1920, 1080) if final else (960, 540)
        scene.render.resolution_percentage = 100
        try:
            scene.view_settings.view_transform = "AgX"
            scene.view_settings.look = "AgX - Medium High Contrast"
        except Exception:
            pass
        # soft late-afternoon sky for the check renders (does not touch the shared blockout file)
        w = scene.world
        if w and w.use_nodes:
            bg = w.node_tree.nodes.get("Background")
            if bg:
                bg.inputs["Color"].default_value = (0.62, 0.70, 0.86, 1)
                bg.inputs["Strength"].default_value = 1.1
        sun = bpy.data.objects.get("Sun")
        if sun:
            sun.data.energy = 4.0
            sun.data.angle = math.radians(2.5)
            sun.data.color = (1.0, 0.93, 0.82)
        cx, cy = CENTRE_XY
        g0 = GROUND_Z

        def cam(name, loc, target, lens):
            cd = bpy.data.cameras.new(name)
            cd.lens = lens
            cd.clip_end = 2000
            co = bpy.data.objects.new(name, cd)
            scene.collection.objects.link(co)
            _look_at(co, loc, target)
            return co
        views = {
            # 3/4 view from the street to the SW (pedestrian square at the foot of Yasaka-dori, OSM 710696944)
            # (line of sight checked against all PLATEAU blocks: pedestrian square OSM 550352948, 29 m from the centre)
            "sw_street": cam("Cam_Hero_SW_Street", (-15.0, 68.0, gz(-15.0, 68.0) + 1.6), (cx, cy, g0 + 15.5), 15),
            # looking east up Yasaka-dori (lead-specified viewpoint)
            "yasakadori_east": cam("Cam_Hero_YasakaDori_East", (-79.0, 88.2, gz(-79.0, 88.2) + 1.6),
                                   (cx, cy, g0 + 17.0), 35),
            # eaves / bracket close-up: under the NW corner of the first two roofs
            "eaves_closeup": cam("Cam_Hero_Eaves", (cx - 13.0, cy - 10.0, g0 + 1.9), (cx - 5.2, cy - 5.6, g0 + 7.6), 26),
        }
        only = [a.split("=", 1)[1] for a in args if a.startswith("--only=")]
        for nm, co in views.items():
            if only and nm not in only[0].split(","):
                continue
            scene.camera = co
            scene.render.filepath = os.path.join(ROOT, "renders", "hero_pagoda_%s.png" % nm)
            bpy.ops.render.render(write_still=True)
            print("rendered", nm)

    # ------------------------------------------------ web GLB (fresh scene, detail='web')
    if "--no-glb" not in args:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        wroot = build_pagoda(detail="web")
        bpy.ops.object.select_all(action="DESELECT")
        for o in _hierarchy(wroot):
            o.select_set(True)
        bpy.context.view_layer.objects.active = wroot
        out_glb = os.path.join(ROOT, "web", "assets", "pagoda.glb")
        bpy.ops.export_scene.gltf(filepath=out_glb, export_format="GLB", use_selection=True, export_extras=True,
                                  export_apply=True, export_yup=True, export_vertex_color="ACTIVE",
                                  export_all_vertex_colors=False, export_attributes=False)
        print("web glb: %d triangles, %.2f MB" % (wroot["triangles"], os.path.getsize(out_glb) / 1e6))


if __name__ == "__main__":
    main()
