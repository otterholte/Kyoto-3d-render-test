"""Procedural Cycles materials (live in the hi-res .blend) that are also baked
into texture atlases for the web build.

Masks that need anatomical knowledge (lips, cheeks, stubble, hem distance,
denim wear, palm side ...) are computed in numpy and stored as colour
attributes; the shaders combine them with 3D noise / weave patterns.
"""
import math
import numpy as np
import bpy

import geo


# ------------------------------------------------------------------ node helpers
class NB:
    def __init__(self, mat):
        self.mat = mat
        self.nt = mat.node_tree
        self.nt.nodes.clear()
        self.out = self.n("ShaderNodeOutputMaterial", loc=(1200, 0))
        self.x = 0

    def n(self, typ, loc=None, **inputs):
        node = self.nt.nodes.new(typ)
        if loc:
            node.location = loc
        for k, v in inputs.items():
            if k.startswith("_"):
                setattr(node, k[1:], v)
            else:
                self.set(node.inputs[k], v)
        return node

    def set(self, sock, v):
        if isinstance(v, bpy.types.NodeSocket):
            self.nt.links.new(v, sock)
        elif isinstance(v, bpy.types.Node):
            self.nt.links.new(v.outputs[0], sock)
        else:
            if hasattr(sock, "default_value"):
                if isinstance(v, (tuple, list)) and len(v) == 3 and len(sock.default_value) == 4:
                    v = tuple(v) + (1.0,)
                sock.default_value = v

    def link(self, a, b):
        self.nt.links.new(a, b)

    # math shortcuts -------------------------------------------------
    def math(self, op, a, b=0.0, clamp=False):
        m = self.n("ShaderNodeMath", _operation=op, _use_clamp=clamp)
        self.set(m.inputs[0], a)
        self.set(m.inputs[1], b)
        return m.outputs[0]

    def mix(self, fac, a, b, blend="MIX"):
        m = self.n("ShaderNodeMix", _data_type="RGBA", _blend_type=blend)
        self.set(m.inputs["Factor"], fac)
        self.set(m.inputs[6], a)
        self.set(m.inputs[7], b)
        return m.outputs[2]

    def mixf(self, fac, a, b):
        m = self.n("ShaderNodeMix", _data_type="FLOAT")
        self.set(m.inputs["Factor"], fac)
        self.set(m.inputs[2], a)
        self.set(m.inputs[3], b)
        return m.outputs[0]

    def attr(self, name, out="Color"):
        a = self.n("ShaderNodeAttribute", _attribute_name=name)
        return a.outputs[out]

    def sep(self, col):
        s = self.n("ShaderNodeSeparateColor")
        self.set(s.inputs[0], col)
        return s.outputs

    def coord(self, kind="Object"):
        return self.n("ShaderNodeTexCoord").outputs[kind]

    def uv(self, name):
        return self.n("ShaderNodeUVMap", _uv_map=name).outputs[0]

    def mapping(self, vec, scale=(1, 1, 1), rot=(0, 0, 0)):
        m = self.n("ShaderNodeMapping")
        self.set(m.inputs["Vector"], vec)
        m.inputs["Scale"].default_value = scale
        m.inputs["Rotation"].default_value = rot
        return m.outputs[0]

    def noise(self, vec, scale, detail=4.0, rough=0.5, dist=0.0, out="Fac", dims="3D"):
        n = self.n("ShaderNodeTexNoise", _noise_dimensions=dims)
        self.set(n.inputs["Vector"], vec)
        n.inputs["Scale"].default_value = scale
        n.inputs["Detail"].default_value = detail
        n.inputs["Roughness"].default_value = rough
        n.inputs["Distortion"].default_value = dist
        return n.outputs[out]

    def voronoi(self, vec, scale, out="Distance", feature="F1", rand=1.0):
        n = self.n("ShaderNodeTexVoronoi", _feature=feature)
        self.set(n.inputs["Vector"], vec)
        n.inputs["Scale"].default_value = scale
        n.inputs["Randomness"].default_value = rand
        return n.outputs[out]

    def wave(self, vec, scale, kind="BANDS", direction="X", profile="SIN", distortion=0.0, detail=0.0):
        n = self.n("ShaderNodeTexWave", _wave_type=kind, _bands_direction=direction, _wave_profile=profile)
        self.set(n.inputs["Vector"], vec)
        n.inputs["Scale"].default_value = scale
        n.inputs["Distortion"].default_value = distortion
        n.inputs["Detail"].default_value = detail
        return n.outputs["Fac"]

    def ramp(self, fac, stops):
        r = self.n("ShaderNodeValToRGB")
        self.set(r.inputs[0], fac)
        el = r.color_ramp.elements
        while len(el) > 2:
            el.remove(el[-1])
        for i, (pos, col) in enumerate(stops):
            e = el[i] if i < 2 else el.new(pos)
            e.position = pos
            e.color = tuple(col) + ((1.0,) if len(col) == 3 else ())
        return r.outputs[0]

    def bump(self, h, strength=0.3, distance=0.001, normal=None):
        b = self.n("ShaderNodeBump")
        self.set(b.inputs["Height"], h)
        b.inputs["Strength"].default_value = strength
        b.inputs["Distance"].default_value = distance
        if normal is not None:
            self.set(b.inputs["Normal"], normal)
        return b.outputs[0]

    def principled(self, **kw):
        p = self.n("ShaderNodeBsdfPrincipled", loc=(900, 0))
        for k, v in kw.items():
            self.set(p.inputs[k], v)
        self.link(p.outputs[0], self.out.inputs["Surface"])
        return p


def new_material(name):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    return m, NB(m)


def set_color_attr(ob, name, cols):
    me = ob.data
    a = me.color_attributes.get(name) or me.color_attributes.new(name, "FLOAT_COLOR", "POINT")
    c = np.ones((len(me.vertices), 4), dtype=np.float32)
    c[:, :cols.shape[1]] = cols
    a.data.foreach_set("color", c.ravel())


def gauss(d, r):
    return np.exp(-(d / r) ** 2)


# ------------------------------------------------------------------ skin
def skin_masks(body, landmarks):
    co, faces, _ = geo.mesh_arrays(body)
    L = landmarks
    mouth, eye_l, eye_r, nose = L["mouth"], L["eye_l"], L["eye_r"], L["nose"]
    head = L["head"]
    # redness: cheeks, nose, ears, lips surround, knuckles/fingertips, elbows
    red = np.zeros(len(co))
    for sx in (1, -1):
        cheek = np.array([sx * 0.042, eye_l[1] + 0.012, eye_l[2] - 0.035])
        red += 0.55 * gauss(np.linalg.norm((co - cheek) * [1, 1.6, 1.0], axis=1), 0.024)
        ear = co[:, 0] * sx > 0.060
        red += 0.45 * ear * gauss(np.abs(co[:, 2] - eye_l[2] + 0.005), 0.035) * (co[:, 1] > eye_l[1] + 0.05)
    red += 0.65 * gauss(np.linalg.norm(co - nose, axis=1), 0.016)
    red += 0.3 * gauss(np.linalg.norm((co - mouth) * [0.8, 1, 1.4], axis=1), 0.03)
    hand = L["hand_pts"]
    for hp in hand:
        red += 0.35 * gauss(np.linalg.norm(co - hp, axis=1), 0.012)
    red = np.clip(red, 0, 1)
    # lips (vermilion) : thin ellipse in front of the mouth joint
    d = (co - (mouth + np.array([0, -0.006, 0.0]))) / np.array([0.026, 0.03, 0.0105])
    lips = np.clip(1.25 - np.linalg.norm(d, axis=1), 0, 1) ** 0.6 * (co[:, 1] < mouth[1] - 0.004)
    lips = np.clip(lips * 1.4, 0, 1)
    # stubble zone: jaw, chin, upper lip, cheeks below the cheekbones, upper neck
    rel = co - head
    jaw_line = eye_l[2] - 0.050 - 0.012 * np.abs(co[:, 0]) / 0.06
    front = co[:, 1] < (eye_l[1] + 0.085)
    face_low = (co[:, 2] < jaw_line) & front & (co[:, 2] > head[2] - 0.075)
    stub = face_low.astype(float)
    stub *= np.clip((0.074 - np.abs(co[:, 0])) / 0.012, 0, 1)        # not on the ears
    stub *= 1 - np.clip(lips * 2, 0, 1)
    stub *= 1 - gauss(np.linalg.norm((co - nose) * [1, 1, 1.3], axis=1), 0.02)  # not on nostrils
    # fade on the neck
    stub *= np.clip((co[:, 2] - (head[2] - 0.075)) / 0.03, 0, 1)
    # under-eye darkening
    dark = np.zeros(len(co))
    for e in (eye_l, eye_r):
        dark += 0.6 * gauss(np.linalg.norm((co - (e + np.array([0, -0.006, -0.014]))) * [1, 1, 1.8], axis=1), 0.013)
    A = geo.adjacency(len(co), faces)
    stub = geo.smooth_field(stub, A, 6)
    red = geo.smooth_field(red, A, 3)
    lips = geo.smooth_field(lips, A, 2)
    dark = geo.smooth_field(dark, A, 3)
    set_color_attr(body, "skin_mask", np.stack([red, lips, stub, np.clip(dark, 0, 1)], 1))


def skin_material(name="Skin"):
    m, b = new_material(name)
    mask = b.sep(b.attr("skin_mask"))
    alpha = b.attr("skin_mask", "Alpha")
    red, lips, stub = mask[0], mask[1], mask[2]
    oc = b.coord("Object")
    # base complexion with large-scale mottling
    mott = b.noise(oc, 9.0, detail=6, rough=0.6)
    base = b.ramp(mott, [(0.30, (0.36, 0.215, 0.145)), (0.70, (0.45, 0.285, 0.195))])
    fine = b.noise(oc, 90.0, detail=8, rough=0.7)
    base = b.mix(b.math("MULTIPLY", b.math("ABSOLUTE", b.math("SUBTRACT", fine, 0.5)), 0.9), base, (0.30, 0.17, 0.11))
    # freckles / spots (very subtle)
    spots = b.voronoi(oc, 220.0, out="Distance")
    spot_m = b.math("LESS_THAN", spots, 0.12)
    spot_m = b.math("MULTIPLY", spot_m, b.math("GREATER_THAN", b.noise(oc, 30.0), 0.6))
    base = b.mix(b.math("MULTIPLY", spot_m, 0.35), base, (0.40, 0.22, 0.14))
    base = b.mix(b.math("MULTIPLY", red, 0.5), base, (0.46, 0.20, 0.15))
    base = b.mix(b.math("MULTIPLY", lips, 0.8), base, (0.36, 0.14, 0.12))
    # stubble: grainy blue-grey shadow
    grain = b.noise(oc, 900.0, detail=2, rough=0.5)
    stg = b.math("MULTIPLY", stub, b.math("ADD", 0.55, b.math("MULTIPLY", grain, 0.6)))
    base = b.mix(b.math("MULTIPLY", stg, 0.75), base, (0.13, 0.10, 0.085))
    base = b.mix(b.math("MULTIPLY", alpha, 0.35), base, (0.24, 0.13, 0.11))
    # roughness: oilier T-zone/lips, rougher elsewhere
    rough = b.math("ADD", 0.48, b.math("MULTIPLY", b.math("SUBTRACT", b.noise(oc, 40.0), 0.5), 0.15))
    rough = b.math("SUBTRACT", rough, b.math("MULTIPLY", lips, 0.12))
    rough = b.math("ADD", rough, b.math("MULTIPLY", stub, 0.08))
    # micro relief: pores + fine wrinkles
    pores = b.voronoi(oc, 1400.0, out="Distance")
    wr = b.noise(b.mapping(oc, scale=(60, 60, 260)), 1.0, detail=6, rough=0.65)
    h = b.math("ADD", b.math("MULTIPLY", pores, 0.6), b.math("MULTIPLY", wr, 0.4))
    h = b.math("ADD", h, b.math("MULTIPLY", grain, b.math("MULTIPLY", stub, 0.6)))
    nrm = b.bump(h, strength=0.22, distance=0.0004)
    b.principled(**{"Base Color": base, "Roughness": rough, "Normal": nrm,
                    "Subsurface Weight": 1.0, "Subsurface Radius": (1.0, 0.4, 0.25),
                    "Subsurface Scale": 0.0045, "IOR": 1.4, "Specular IOR Level": 0.5,
                    "Sheen Weight": 0.08, "Sheen Roughness": 0.6, "Sheen Tint": (0.9, 0.85, 0.8)})
    return m


# ------------------------------------------------------------------ eyes
def eye_material(img_path):
    m, b = new_material("Eyes")
    tex = b.n("ShaderNodeTexImage")
    tex.image = bpy.data.images.load(img_path, check_existing=True)
    b.set(tex.inputs["Vector"], b.uv("UVMap"))
    col = tex.outputs[0]
    b.principled(**{"Base Color": col, "Alpha": tex.outputs["Alpha"], "Roughness": 0.35, "Coat Weight": 1.0, "Coat Roughness": 0.02,
                    "Coat IOR": 1.376, "Subsurface Weight": 0.15, "Subsurface Radius": (1, 0.5, 0.4),
                    "Subsurface Scale": 0.002})
    return m


# ------------------------------------------------------------------ fabric helpers
def _hem_stitch(b, hem_d, oc, depth=0.010, color=None, base=None, width=0.0011, double=True):
    """Stitch line(s) at `depth` metres from the garment edge; returns (mask, base, height)."""
    d1 = b.math("ABSOLUTE", b.math("SUBTRACT", hem_d, depth))
    line = b.math("LESS_THAN", d1, width)
    if double:
        d2 = b.math("ABSOLUTE", b.math("SUBTRACT", hem_d, depth + 0.006))
        line = b.math("MAXIMUM", line, b.math("LESS_THAN", d2, width))
    dash = b.math("GREATER_THAN", b.wave(oc, 260.0, kind="BANDS", direction="DIAGONAL"), 0.35)
    st = b.math("MULTIPLY", line, dash)
    return st


def tshirt_material():
    m, b = new_material("Tshirt")
    oc = b.coord("Object")
    hem = b.attr("garment", "Color")
    s = b.sep(hem)
    hem_d = s[0]
    heather = b.noise(b.mapping(oc, scale=(1, 1, 3)), 160.0, detail=3, rough=0.6)
    base = b.ramp(heather, [(0.3, (0.075, 0.105, 0.15)), (0.7, (0.12, 0.16, 0.215))])
    fibers = b.noise(oc, 1100.0, detail=1)
    base = b.mix(b.math("MULTIPLY", b.math("GREATER_THAN", fibers, 0.72), 0.25), base, (0.25, 0.28, 0.32))
    # knit wales (vertical) and courses
    wales = b.wave(b.mapping(oc, scale=(1, 1, 0.05)), 900.0, kind="BANDS", direction="X")
    wales2 = b.wave(b.mapping(oc, scale=(0.05, 1, 1)), 900.0, kind="BANDS", direction="Y")
    knit = b.math("MAXIMUM", wales, wales2)
    # rib collar band (first 15 mm from neck edge), hems double stitched
    st = _hem_stitch(b, hem_d, oc, depth=0.011)
    base = b.mix(b.math("MULTIPLY", st, 0.6), base, (0.05, 0.07, 0.1))
    folds = b.noise(oc, 14.0, detail=3)
    h = b.math("ADD", b.math("MULTIPLY", knit, 0.25), b.math("MULTIPLY", st, -0.6))
    h = b.math("ADD", h, b.math("MULTIPLY", folds, 0.5))
    nrm = b.bump(h, strength=0.25, distance=0.0006)
    b.principled(**{"Base Color": base, "Roughness": 0.88, "Normal": nrm, "Sheen Weight": 0.5,
                    "Sheen Roughness": 0.45, "Sheen Tint": (0.8, 0.85, 0.95)})
    return m


def denim_material():
    m, b = new_material("Denim")
    oc = b.coord("Object")
    g = b.sep(b.attr("garment"))
    hem_d, wear, seam = g[0], g[1], g[2]
    slub = b.noise(b.mapping(oc, scale=(6, 6, 0.6)), 30.0, detail=6, rough=0.65)
    twill = b.wave(b.mapping(oc, scale=(1, 1, 1)), 700.0, kind="BANDS", direction="DIAGONAL", distortion=0.5, detail=1)
    indigo = b.ramp(slub, [(0.3, (0.010, 0.016, 0.042)), (0.7, (0.018, 0.028, 0.065))])
    white_weft = (0.32, 0.36, 0.45)
    base = b.mix(b.math("MULTIPLY", twill, 0.10), indigo, white_weft)
    # fades and whiskers
    whisk = b.wave(b.mapping(oc, scale=(1, 3, 1), rot=(0, 0.35, 0)), 25.0, kind="BANDS", direction="Z", distortion=4)
    fade = b.math("MULTIPLY", wear, b.math("ADD", 0.55, b.math("MULTIPLY", whisk, 0.45)))
    base = b.mix(b.math("MULTIPLY", fade, 0.45), base, (0.06, 0.09, 0.16))
    # seams from a smooth distance field (B = metres to the nearest seam / 0.05)
    sd = b.math("MULTIPLY", seam, 0.05)
    seam_line = b.math("LESS_THAN", sd, 0.0012)
    base = b.mix(b.math("MULTIPLY", seam_line, 0.5), base, (0.006, 0.009, 0.02))
    dash = b.math("GREATER_THAN", b.wave(oc, 240.0, kind="BANDS", direction="DIAGONAL"), 0.4)
    st1 = b.math("LESS_THAN", b.math("ABSOLUTE", b.math("SUBTRACT", sd, 0.0045)), 0.0007)
    st2 = b.math("LESS_THAN", b.math("ABSOLUTE", b.math("SUBTRACT", sd, 0.0105)), 0.0007)
    thread = b.math("MULTIPLY", b.math("MAXIMUM", st1, st2), dash)
    thread = b.math("MAXIMUM", thread, _hem_stitch(b, hem_d, oc, depth=0.012))
    base = b.mix(thread, base, (0.42, 0.26, 0.09))
    h = b.math("ADD", b.math("MULTIPLY", twill, 0.35), b.math("MULTIPLY", seam_line, -0.8))
    h = b.math("ADD", h, b.math("MULTIPLY", thread, 0.4))
    nrm = b.bump(h, strength=0.35, distance=0.0006)
    b.principled(**{"Base Color": base, "Roughness": 0.82, "Normal": nrm, "Sheen Weight": 0.25, "Sheen Roughness": 0.6})
    return m


def shoe_material(kind="sneaker"):
    m, b = new_material("Sneaker" if kind == "sneaker" else "Boot")
    uvp = b.sep(b.uv("UVBody"))
    u, v = uvp[0], uvp[1]
    oc = b.coord("Object")
    is_sole = b.math("GREATER_THAN", u, 0.75)
    # sole layer index (v in [0,1] across the sole side band)
    sole_v = v
    lthr = b.noise(oc, 400.0, detail=3)
    if kind == "sneaker":
        upper = b.ramp(lthr, [(0.3, (0.70, 0.70, 0.68)), (0.7, (0.78, 0.78, 0.76))])
        # suede toe/heel overlays (grey) + navy accent panel on the side
        toe = b.math("GREATER_THAN", u, 0.62)
        heel = b.math("LESS_THAN", u, 0.12)
        panel = b.math("MULTIPLY", b.math("GREATER_THAN", u, 0.28), b.math("LESS_THAN", u, 0.55))
        side = b.math("LESS_THAN", b.math("ABSOLUTE", b.math("SUBTRACT", v, 0.5)), 0.17)
        side2 = b.math("LESS_THAN", b.math("ABSOLUTE", b.math("SUBTRACT", v, 0.0)), 0.17)
        side2 = b.math("MAXIMUM", side2, b.math("LESS_THAN", b.math("ABSOLUTE", b.math("SUBTRACT", v, 1.0)), 0.17))
        stripe = b.math("MULTIPLY", panel, b.math("MAXIMUM", side, side2))
        upper = b.mix(b.math("MAXIMUM", toe, heel), upper, (0.42, 0.43, 0.44))
        upper = b.mix(stripe, upper, (0.05, 0.08, 0.17))
        # laces on top (crossing pattern) for u in 0.38..0.66, v near 0.75 (top)
        top = b.math("LESS_THAN", b.math("ABSOLUTE", b.math("SUBTRACT", v, 0.25)), 0.07)
        lz = b.math("MULTIPLY", b.math("GREATER_THAN", u, 0.36), b.math("LESS_THAN", u, 0.62))
        lace_pat = b.math("GREATER_THAN", b.wave(b.uv("UVBody"), 22.0, kind="BANDS", direction="X"), 0.55)
        laces = b.math("MULTIPLY", b.math("MULTIPLY", top, lz), lace_pat)
        upper = b.mix(laces, upper, (0.86, 0.86, 0.84))
        sole = b.ramp(sole_v, [(0.0, (0.12, 0.12, 0.12)), (0.22, (0.12, 0.12, 0.12)), (0.25, (0.85, 0.84, 0.80)), (1.0, (0.85, 0.84, 0.80))])
        rough_u, rough_s = 0.55, 0.75
    else:
        upper = b.ramp(lthr, [(0.3, (0.17, 0.095, 0.045)), (0.7, (0.24, 0.14, 0.07))])
        rubber = b.math("MAXIMUM", b.math("GREATER_THAN", u, 0.60), b.math("LESS_THAN", u, 0.10))
        lower = b.math("LESS_THAN", b.math("ABSOLUTE", b.math("SUBTRACT", v, 0.75)), 0.12)
        shell = b.math("MAXIMUM", rubber, lower)
        upper = b.mix(shell, upper, (0.035, 0.035, 0.035))
        top = b.math("LESS_THAN", b.math("ABSOLUTE", b.math("SUBTRACT", v, 0.25)), 0.08)
        lz = b.math("MULTIPLY", b.math("GREATER_THAN", u, 0.20), b.math("LESS_THAN", u, 0.58))
        lace_pat = b.math("GREATER_THAN", b.wave(b.uv("UVBody"), 26.0, kind="BANDS", direction="X"), 0.55)
        laces = b.math("MULTIPLY", b.math("MULTIPLY", top, lz), lace_pat)
        upper = b.mix(laces, upper, (0.55, 0.12, 0.06))
        sole = b.ramp(sole_v, [(0.0, (0.03, 0.03, 0.03)), (1.0, (0.05, 0.045, 0.04))])
        rough_u, rough_s = 0.7, 0.85
        shell = shell
    base = b.mix(is_sole, upper, sole)
    tread = b.voronoi(b.mapping(oc, scale=(1, 1, 1)), 90.0 if kind == "sneaker" else 45.0)
    h = b.math("ADD", b.math("MULTIPLY", lthr, 0.3), b.math("MULTIPLY", tread, is_sole))
    h = b.math("ADD", h, b.math("MULTIPLY", laces, 0.6))
    nrm = b.bump(h, strength=0.3, distance=0.001)
    rough = b.mixf(is_sole, rough_u, rough_s)
    b.principled(**{"Base Color": base, "Roughness": rough, "Normal": nrm})
    return m


def puffer_material():
    m, b = new_material("Puffer")
    oc = b.coord("Object")
    g = b.sep(b.attr("garment"))
    hem_d, quilt, zipm = g[0], g[1], g[2]
    shade = b.noise(oc, 6.0, detail=3)
    base = b.ramp(shade, [(0.3, (0.20, 0.035, 0.022)), (0.7, (0.25, 0.05, 0.03))])
    # baffle valleys a touch darker
    base = b.mix(b.math("MULTIPLY", b.math("SUBTRACT", 1.0, quilt), 0.5), base, (0.10, 0.02, 0.015))
    # ripstop grid
    rip = b.math("MAXIMUM", b.wave(oc, 160.0, kind="BANDS", direction="X", profile="SAW"),
                 b.wave(oc, 160.0, kind="BANDS", direction="Z", profile="SAW"))
    rip = b.math("GREATER_THAN", rip, 0.93)
    zip_teeth = b.math("GREATER_THAN", b.wave(oc, 600.0, kind="BANDS", direction="Z"), 0.5)
    zipm = b.math("LESS_THAN", b.math("MULTIPLY", zipm, 0.05), 0.006)
    base = b.mix(zipm, base, (0.02, 0.02, 0.02))
    base = b.mix(b.math("MULTIPLY", zipm, b.math("MULTIPLY", zip_teeth, 0.5)), base, (0.12, 0.12, 0.12))
    st = _hem_stitch(b, hem_d, oc, depth=0.012, double=False)
    base = b.mix(b.math("MULTIPLY", st, 0.5), base, (0.08, 0.015, 0.01))
    h = b.math("ADD", b.math("MULTIPLY", rip, 0.2), b.math("MULTIPLY", b.noise(oc, 40, detail=4), 0.4))
    h = b.math("ADD", h, b.math("MULTIPLY", zipm, b.math("MULTIPLY", zip_teeth, 0.5)))
    nrm = b.bump(h, strength=0.2, distance=0.0006)
    b.principled(**{"Base Color": base, "Roughness": 0.38, "Normal": nrm, "Sheen Weight": 0.3,
                    "Sheen Roughness": 0.3, "Coat Weight": 0.15, "Coat Roughness": 0.25})
    return m


def snowpants_material():
    m, b = new_material("SnowPants")
    oc = b.coord("Object")
    g = b.sep(b.attr("garment"))
    hem_d, wear, seam = g[0], g[1], g[2]
    base = b.ramp(b.noise(oc, 8.0, detail=3), [(0.3, (0.018, 0.019, 0.022)), (0.7, (0.03, 0.031, 0.035))])
    weave = b.math("MAXIMUM", b.wave(oc, 500.0, kind="BANDS", direction="X"), b.wave(oc, 500.0, kind="BANDS", direction="Z"))
    seam_line = b.math("LESS_THAN", b.math("MULTIPLY", seam, 0.05), 0.0012)
    base = b.mix(b.math("MULTIPLY", seam_line, 0.6), base, (0.005, 0.005, 0.006))
    h = b.math("ADD", b.math("MULTIPLY", weave, 0.15), b.math("MULTIPLY", seam_line, -0.7))
    h = b.math("ADD", h, b.math("MULTIPLY", b.noise(oc, 18, detail=4), 0.5))
    nrm = b.bump(h, strength=0.25, distance=0.0008)
    b.principled(**{"Base Color": base, "Roughness": 0.55, "Normal": nrm, "Sheen Weight": 0.2, "Sheen Roughness": 0.4})
    return m


def glove_material():
    m, b = new_material("Gloves")
    oc = b.coord("Object")
    g = b.sep(b.attr("garment"))
    hem_d, palm = g[0], g[1]
    shell = b.ramp(b.noise(oc, 60.0, detail=4), [(0.3, (0.025, 0.026, 0.03)), (0.7, (0.04, 0.042, 0.046))])
    leather = b.ramp(b.noise(oc, 300.0, detail=4), [(0.3, (0.07, 0.065, 0.06)), (0.7, (0.10, 0.095, 0.09))])
    base = b.mix(palm, shell, leather)
    h = b.math("MULTIPLY", b.voronoi(oc, 700.0), b.math("ADD", 0.3, palm))
    nrm = b.bump(h, strength=0.3, distance=0.0005)
    rough = b.mixf(palm, 0.7, 0.45)
    b.principled(**{"Base Color": base, "Roughness": rough, "Normal": nrm, "Sheen Weight": 0.3})
    return m


def beanie_material():
    m, b = new_material("Beanie")
    oc = b.coord("Object")
    g = b.sep(b.attr("garment"))
    hem_d, cuff, az = g[0], g[1], g[2]
    # azimuth-based vertical ribs; courses along height
    rib = b.math("SINE", b.math("MULTIPLY", az, 2 * math.pi * 70))
    rib = b.math("MULTIPLY", b.math("ADD", rib, 1.0), 0.5)
    course = b.wave(oc, 450.0, kind="BANDS", direction="Z")
    heather = b.noise(oc, 200.0, detail=3)
    base = b.ramp(heather, [(0.3, (0.23, 0.20, 0.16)), (0.7, (0.33, 0.29, 0.24))])
    base = b.mix(b.math("MULTIPLY", b.math("SUBTRACT", 1.0, rib), 0.35), base, (0.12, 0.1, 0.08))
    h = b.math("ADD", b.math("MULTIPLY", rib, 0.7), b.math("MULTIPLY", course, 0.2))
    nrm = b.bump(h, strength=0.45, distance=0.0015)
    b.principled(**{"Base Color": base, "Roughness": 0.92, "Normal": nrm, "Sheen Weight": 0.6, "Sheen Roughness": 0.5})
    return m


# ------------------------------------------------------------------ garment attribute fields
def garment_fields(ob, kind, bd=None, extra=None):
    """Store per-vertex fields in colour attribute 'garment':
    R = distance to nearest open edge (m), G/B garment specific."""
    co, faces, _ = geo.mesh_arrays(ob)
    loops = geo.boundary_loops(faces)
    bverts = np.array(sorted(set(v for l in loops for v in l)), dtype=np.int64)
    from scipy.spatial import cKDTree
    if len(bverts):
        dist, _ = cKDTree(co[bverts]).query(co)
    else:
        dist = np.full(len(co), 1.0)
    G = np.zeros(len(co))
    B = np.zeros(len(co))
    if kind in ("jeans", "pants"):
        # wear: front thighs + knees + seat; seams at lateral/medial angles of each leg
        z = co[:, 2]
        front = np.clip(-co[:, 1] / 0.08, 0, 1)
        G = np.clip(front * (np.exp(-((z - 0.75) / 0.12) ** 2) + 0.7 * np.exp(-((z - 0.50) / 0.05) ** 2)), 0, 1)
        G += 0.5 * np.clip(co[:, 1] / 0.08, 0, 1) * np.exp(-((z - 0.88) / 0.06) ** 2)
        B = np.ones(len(co))
        for sx in (1, -1):
            sel = (np.sign(co[:, 0]) == sx) & (z < 0.84)
            cx = 0.10 * sx
            r = np.hypot(co[:, 0] - cx, co[:, 1])
            ang = np.arctan2(co[:, 1], (co[:, 0] - cx) * sx)
            dd = np.minimum(np.abs(ang), np.pi - np.abs(ang)) * r
            B = np.where(sel, np.minimum(B, dd / 0.05), B)
        B = np.clip(B, 0, 1)
        if kind == "pants":
            G *= 0.2
    elif kind == "puffer":
        G = extra["quilt"] if extra is not None else np.ones(len(co))
        B = np.where(co[:, 1] < 0, np.clip(np.abs(co[:, 0]) / 0.05, 0, 1), 1.0)
    elif kind == "gloves":
        # palm side: normals facing the hand's palm direction (towards the thumb side, inward)
        n = geo.vertex_normals_fast(co, faces)
        palm_dir = np.stack([-np.sign(co[:, 0]) * 0.55, -0.25 * np.ones(len(co)), np.full(len(co), -0.8)], 1)
        palm_dir /= np.linalg.norm(palm_dir, axis=1, keepdims=True)
        G = np.clip((np.sum(n * palm_dir, 1) - 0.1) * 3, 0, 1)
    elif kind == "beanie":
        hc = extra["head"]
        G = np.clip(1 - (dist - 0.045) / 0.004, 0, 1)
        B = (np.arctan2(co[:, 0] - hc[0], -(co[:, 1] - hc[1])) + np.pi) / (2 * np.pi)
    set_color_attr(ob, "garment", np.stack([dist, G, B], 1))
