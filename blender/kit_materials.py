"""Phase 6 painterly, fully procedural materials (Cycles). No external textures.

Brushwork lives in colour only: a shared node group "G_Brush" gives soft, noise-warped, stretched
Voronoi "dabs" (smooth-F1 cell colours) that jitter hue/value of every material by a few percent.
Real PLATEAU facade/roof colours (face-corner attribute "plateau_rgb") stay the base tint of
buildings and are only pushed toward the warm muted palette.
"""
import bpy

# ------------------------------------------------------------------ palette (linear RGB)
PAL = dict(
    # evidence (docs/evidence/building_evidence.json suggested_colours, observed sRGB -> linear) pushed slightly
    # toward the warm, muted storybook palette
    kawara=(0.165, 0.175, 0.195), kawara_hi=(0.26, 0.27, 0.29),               # #7d8085
    plaster=(0.70, 0.59, 0.40), plaster_ochre=(0.52, 0.37, 0.19),              # #e6d6b0 / #c8a878
    plaster_shadow=(0.42, 0.36, 0.33),
    wood_dark=(0.075, 0.032, 0.012), wood_bengara=(0.115, 0.036, 0.018),       # #5a3418 (dark timber)
    wood_weather=(0.16, 0.12, 0.085),
    granite=(0.36, 0.335, 0.30), granite_warm=(0.42, 0.37, 0.31),              # #a9a39a
    sett=(0.24, 0.225, 0.195),                                                 # #8a857a
    asphalt=(0.065, 0.066, 0.072),
    moss=(0.10, 0.16, 0.04), moss_dry=(0.20, 0.21, 0.08), soil=(0.15, 0.10, 0.06),
    indigo=(0.018, 0.032, 0.095), persimmon=(0.55, 0.16, 0.05), cream=(0.62, 0.55, 0.42),
    lantern=(1.0, 0.42, 0.13), glow=(1.0, 0.58, 0.28),
)


# ------------------------------------------------------------------ tiny node DSL
def node(nt, t, inputs=None, **props):
    n = nt.nodes.new(t)
    for k, v in props.items():
        setattr(n, k, v)
    for k, v in (inputs or {}).items():
        sock = n.inputs[k]
        if isinstance(v, bpy.types.NodeSocket):
            nt.links.new(v, sock)
        else:
            sock.default_value = v
    return n


def link(nt, a, b):
    nt.links.new(a, b)


def math(nt, op, a, b=None, c=None, clamp=False):
    n = nt.nodes.new("ShaderNodeMath"); n.operation = op; n.use_clamp = clamp
    for i, v in enumerate((a, b, c)):
        if v is None:
            continue
        if isinstance(v, bpy.types.NodeSocket):
            nt.links.new(v, n.inputs[i])
        else:
            n.inputs[i].default_value = v
    return n.outputs[0]


def vmath(nt, op, a, b=None, scale=None):
    n = nt.nodes.new("ShaderNodeVectorMath"); n.operation = op
    for i, v in enumerate((a, b)):
        if v is None:
            continue
        if isinstance(v, bpy.types.NodeSocket):
            nt.links.new(v, n.inputs[i])
        else:
            n.inputs[i].default_value = v
    if scale is not None:
        if isinstance(scale, bpy.types.NodeSocket):
            nt.links.new(scale, n.inputs["Scale"])
        else:
            n.inputs["Scale"].default_value = scale
    return n.outputs["Value"] if op in ("DOT_PRODUCT", "LENGTH", "DISTANCE") else n.outputs["Vector"]


def mix(nt, fac, a, b, blend="MIX", dtype="RGBA"):
    n = nt.nodes.new("ShaderNodeMix"); n.data_type = dtype; n.blend_type = blend; n.clamp_factor = True
    ia, ib, io = {"RGBA": (6, 7, 2), "FLOAT": (2, 3, 0), "VECTOR": (4, 5, 1)}[dtype]
    for sock, v in ((n.inputs[0], fac), (n.inputs[ia], a), (n.inputs[ib], b)):
        if isinstance(v, bpy.types.NodeSocket):
            nt.links.new(v, sock)
        else:
            sock.default_value = (*v, 1.0) if (dtype == "RGBA" and isinstance(v, tuple) and len(v) == 3) else v
    return n.outputs[io]


def mrange(nt, v, a, b, c=0.0, d=1.0, interp="LINEAR"):
    n = node(nt, "ShaderNodeMapRange", {0: v, 1: a, 2: b, 3: c, 4: d}, interpolation_type=interp)
    return n.outputs[0]


def sep(nt, v):
    n = node(nt, "ShaderNodeSeparateXYZ", {0: v})
    return n.outputs[0], n.outputs[1], n.outputs[2]


def comb(nt, x, y, z):
    return node(nt, "ShaderNodeCombineXYZ", {0: x, 1: y, 2: z}).outputs[0]


def rgb(c):
    return (*c, 1.0)


# ------------------------------------------------------------------ brush group
def brush_group():
    g = bpy.data.node_groups.get("G_Brush")
    if g:
        return g
    g = bpy.data.node_groups.new("G_Brush", "ShaderNodeTree")
    g.interface.new_socket("Vector", in_out="INPUT", socket_type="NodeSocketVector")
    s = g.interface.new_socket("Scale", in_out="INPUT", socket_type="NodeSocketFloat"); s.default_value = 3.0
    s = g.interface.new_socket("Stretch", in_out="INPUT", socket_type="NodeSocketVector"); s.default_value = (1, 1, 3)
    g.interface.new_socket("Fac", in_out="OUTPUT", socket_type="NodeSocketFloat")
    g.interface.new_socket("Fac2", in_out="OUTPUT", socket_type="NodeSocketFloat")
    nt = g
    gi = nt.nodes.new("NodeGroupInput"); go = nt.nodes.new("NodeGroupOutput")
    # noise warp
    nz = node(nt, "ShaderNodeTexNoise", {"Vector": gi.outputs["Vector"], "Scale": 0.7, "Detail": 2.0, "Distortion": 0.4})
    link(nt, gi.outputs["Scale"], nz.inputs["Scale"])
    w = vmath(nt, "SUBTRACT", nz.outputs["Color"], (0.5, 0.5, 0.5))
    inv = math(nt, "DIVIDE", 0.55, gi.outputs["Scale"])
    w = vmath(nt, "SCALE", w, scale=inv)
    p = vmath(nt, "ADD", gi.outputs["Vector"], w)
    p = vmath(nt, "DIVIDE", p, gi.outputs["Stretch"])
    # F1 cells (cheap: 27 cells) give the dabs; a noise octave gives the second, softer factor
    v1 = node(nt, "ShaderNodeTexVoronoi", {"Vector": p, "Randomness": 0.9}, feature="F1")
    link(nt, gi.outputs["Scale"], v1.inputs["Scale"])
    s2 = math(nt, "MULTIPLY", gi.outputs["Scale"], 2.7)
    n2 = node(nt, "ShaderNodeTexNoise", {"Vector": p, "Detail": 1.0, "Roughness": 0.5})
    link(nt, s2, n2.inputs["Scale"])
    r1 = sep(nt, v1.outputs["Color"])[0]
    f = mix(nt, 0.35, r1, n2.outputs["Factor"], dtype="FLOAT")
    link(nt, f, go.inputs["Fac"])
    link(nt, sep(nt, v1.outputs["Color"])[2], go.inputs["Fac2"])
    return g


def brush(nt, vec=None, scale=3.0, stretch=(1, 1, 3)):
    g = node(nt, "ShaderNodeGroup"); g.node_tree = brush_group()
    if vec is None:
        vec = node(nt, "ShaderNodeTexCoord").outputs["Object"]
    link(nt, vec, g.inputs["Vector"])
    g.inputs["Scale"].default_value = scale
    g.inputs["Stretch"].default_value = stretch
    return g.outputs["Fac"], g.outputs["Fac2"]


def paint(nt, col, fac, fac2, val=0.16, hue=0.025, sat=0.10):
    """Jitter hue/sat/value of `col` with brush factors."""
    h = math(nt, "MULTIPLY_ADD", fac2, hue * 2, 0.5 - hue)
    v = math(nt, "MULTIPLY_ADD", fac, val * 2, 1.0 - val)
    s = math(nt, "MULTIPLY_ADD", fac2, sat * 2, 1.0 - sat)
    n = node(nt, "ShaderNodeHueSaturation", {"Hue": h, "Saturation": s, "Value": v, "Color": col})
    return n.outputs[0]


def new_mat(name):
    m = bpy.data.materials.get(name)
    if m:
        bpy.data.materials.remove(m)
    m = bpy.data.materials.new(name)
    nt = m.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    return m, nt, out


def principled(nt, out, base, rough=0.8, spec=0.35, normal=None, **extra):
    b = node(nt, "ShaderNodeBsdfPrincipled")
    for k, v in (("Base Color", base), ("Roughness", rough), ("Specular IOR Level", spec), ("Normal", normal)):
        if v is None:
            continue
        if isinstance(v, bpy.types.NodeSocket):
            link(nt, v, b.inputs[k])
        else:
            b.inputs[k].default_value = rgb(v) if (k == "Base Color" and len(v) == 3) else v
    for k, v in extra.items():
        k = k.replace("_", " ")
        if isinstance(v, bpy.types.NodeSocket):
            link(nt, v, b.inputs[k])
        else:
            b.inputs[k].default_value = v
    if out is not None:
        link(nt, b.outputs[0], out.inputs["Surface"])
    return b


def bump(nt, h, strength=0.4, dist=0.02, normal=None):
    n = node(nt, "ShaderNodeBump", {"Height": h, "Strength": strength, "Distance": dist})
    if normal is not None:
        link(nt, normal, n.inputs["Normal"])
    return n.outputs[0]


def edge_mask(nt, radius=0.03, samples=3):
    """1 at softened edges (bevel normal vs true normal)."""
    bv = node(nt, "ShaderNodeBevel", {"Radius": radius}, samples=samples)
    geo = node(nt, "ShaderNodeNewGeometry")
    d = vmath(nt, "DOT_PRODUCT", bv.outputs[0], geo.outputs["Normal"])
    return mrange(nt, d, 0.995, 0.85), bv.outputs[0]


def world_pos(nt):
    return node(nt, "ShaderNodeNewGeometry").outputs["Position"]


def wetness(nt, pos, scale=0.12, cover=0.10):
    """Restrained post-rain puddle mask (0..1) from low-frequency noise in world XY."""
    nz = node(nt, "ShaderNodeTexNoise", {"Vector": pos, "Scale": scale, "Detail": 4.0, "Roughness": 0.6})
    thr = 0.5 + (0.5 - cover) * 0.5
    return mrange(nt, nz.outputs["Factor"], thr, thr + 0.035)


# ------------------------------------------------------------------ building materials
def m_roof(name="ART_Roof_Kawara"):
    m, nt, out = new_mat(name)
    geo = node(nt, "ShaderNodeNewGeometry")
    P, N = geo.outputs["Position"], geo.outputs["Normal"]
    nx, ny, nz = sep(nt, N)
    h = vmath(nt, "NORMALIZE", comb(nt, nx, ny, 0.0))
    hx, hy, _ = sep(nt, h)
    across = comb(nt, math(nt, "MULTIPLY", hy, -1.0), hx, 0.0)
    sa = vmath(nt, "DOT_PRODUCT", P, across)
    sd = vmath(nt, "DOT_PRODUCT", P, h)
    # sangawara wave across the slope (0.30 m pitch), overlapping courses down the slope (0.27 m)
    ch = math(nt, "ABSOLUTE", math(nt, "SINE", math(nt, "MULTIPLY", sa, 3.14159 / 0.30)))
    ch = math(nt, "POWER", ch, 0.6)
    course = math(nt, "FRACT", math(nt, "DIVIDE", sd, 0.27))
    course = math(nt, "POWER", course, 2.0)
    hgt = math(nt, "MULTIPLY_ADD", ch, 0.7, math(nt, "MULTIPLY", course, 0.35))
    slope_w = mrange(nt, nz, 0.25, 0.45)      # tiles only on sloped tops
    hgt = math(nt, "MULTIPLY", hgt, slope_w)
    # per-tile variation
    cell = comb(nt, math(nt, "FLOOR", math(nt, "DIVIDE", sa, 0.30)), math(nt, "FLOOR", math(nt, "DIVIDE", sd, 0.27)), 0.0)
    wn = node(nt, "ShaderNodeTexWhiteNoise", {"Vector": cell}, noise_dimensions="3D").outputs["Value"]
    att = node(nt, "ShaderNodeAttribute", attribute_name="plateau_rgb", attribute_type="GEOMETRY").outputs["Color"]
    base = mix(nt, 0.35, PAL["kawara"], att)
    base = node(nt, "ShaderNodeHueSaturation", {"Color": base, "Saturation": 0.55, "Value": 1.0}).outputs[0]
    base = mix(nt, math(nt, "MULTIPLY", wn, 0.35), base, PAL["kawara_hi"])
    f1, f2 = brush(nt, P, 1.6, (1, 1, 1))
    base = paint(nt, base, f1, f2, val=0.12, hue=0.02)
    # vertical faces = fascia / slab edge (dark wood-grey), undersides = soffit (dark wood)
    fascia = mrange(nt, math(nt, "ABSOLUTE", nz), 0.3, 0.15)
    base = mix(nt, fascia, base, (0.07, 0.06, 0.055))
    under = mrange(nt, nz, -0.3, -0.6)
    soffit = paint(nt, rgb(PAL["wood_weather"]), f1, f2, val=0.2)
    base = mix(nt, under, base, soffit)
    # moss / lichen in the lower courses, very light
    mz = node(nt, "ShaderNodeTexNoise", {"Vector": P, "Scale": 0.9, "Detail": 3.0}).outputs["Factor"]
    moss = math(nt, "MULTIPLY", mrange(nt, mz, 0.62, 0.75), math(nt, "MULTIPLY", slope_w, 0.45))
    base = mix(nt, moss, base, PAL["moss_dry"])
    rough = math(nt, "MULTIPLY_ADD", ch, -0.15, 0.55)
    nrm = bump(nt, hgt, 0.55, 0.035)
    principled(nt, out, base, rough, 0.45, nrm)
    return m


def m_facade(name="ART_Facade"):
    """Walls: plateau_rgb as base; dark walls read as weathered wood boards, light as lime plaster."""
    m, nt, out = new_mat(name)
    geo = node(nt, "ShaderNodeNewGeometry")
    P, N = geo.outputs["Position"], geo.outputs["Normal"]
    att = node(nt, "ShaderNodeAttribute", attribute_name="plateau_rgb", attribute_type="GEOMETRY").outputs["Color"]
    lum = node(nt, "ShaderNodeRGBToBW", {"Color": att}).outputs[0]
    woodness = mrange(nt, lum, 0.16, 0.07)
    f1, f2 = brush(nt, P, 2.4, (1, 1, 3.5))
    # plaster: keep the real tint, muted + warmed
    pl = node(nt, "ShaderNodeHueSaturation", {"Color": att, "Saturation": 0.7, "Value": 1.0}).outputs[0]
    pl = mix(nt, 0.42, pl, PAL["plaster"])
    stain = node(nt, "ShaderNodeTexNoise", {"Vector": P, "Scale": 0.5, "Detail": 5.0, "Roughness": 0.65}).outputs["Factor"]
    pl = mix(nt, mrange(nt, stain, 0.45, 0.75, 0.0, 0.35), pl, PAL["plaster_shadow"])
    pl = paint(nt, pl, f1, f2, val=0.10, hue=0.02, sat=0.12)
    # wood: vertical boards 0.18 m
    nx, ny, _ = sep(nt, N)
    tang = comb(nt, math(nt, "MULTIPLY", ny, -1.0), nx, 0.0)
    along = vmath(nt, "DOT_PRODUCT", P, tang)
    board = math(nt, "FRACT", math(nt, "DIVIDE", along, 0.18))
    joint = mrange(nt, board, 0.0, 0.06, 0.0, 1.0)
    bid = node(nt, "ShaderNodeTexWhiteNoise", {"Vector": comb(nt, math(nt, "FLOOR", math(nt, "DIVIDE", along, 0.18)), 0, 0)},
               noise_dimensions="3D").outputs["Value"]
    wd = mix(nt, 0.55, att, PAL["wood_dark"])
    wd = mix(nt, math(nt, "MULTIPLY", bid, 0.5), wd, PAL["wood_weather"])
    grain = node(nt, "ShaderNodeTexWave", {"Vector": P, "Scale": 1.2, "Distortion": 6.0, "Detail": 3.0},
                 wave_type="BANDS", bands_direction="Z").outputs["Factor"]
    wd = mix(nt, math(nt, "MULTIPLY", grain, 0.25), wd, (0.02, 0.012, 0.008))
    wd = mix(nt, math(nt, "SUBTRACT", 1.0, joint), wd, (0.012, 0.008, 0.005))
    wd = paint(nt, wd, f1, f2, val=0.18, hue=0.02)
    base = mix(nt, woodness, pl, wd)
    h = math(nt, "MULTIPLY", math(nt, "MULTIPLY", joint, woodness), 0.5)
    h = math(nt, "ADD", h, math(nt, "MULTIPLY", f1, 0.15))
    principled(nt, out, base, mix(nt, woodness, 0.88, 0.7, dtype="FLOAT"), 0.3, bump(nt, h, 0.3, 0.01))
    return m


def m_plinth(name="ART_Plinth_Stone"):
    m, nt, out = new_mat(name)
    P = world_pos(nt)
    vor = node(nt, "ShaderNodeTexVoronoi", {"Vector": P, "Scale": 3.2, "Randomness": 0.8}, feature="DISTANCE_TO_EDGE")
    vc = node(nt, "ShaderNodeTexVoronoi", {"Vector": P, "Scale": 3.2, "Randomness": 0.8}).outputs["Color"]
    j = mrange(nt, vor.outputs["Distance"], 0.0, 0.06)
    base = mix(nt, math(nt, "MULTIPLY", sep(nt, vc)[0], 0.6), PAL["granite"], PAL["granite_warm"])
    base = mix(nt, math(nt, "SUBTRACT", 1.0, j), base, (0.05, 0.05, 0.045))
    f1, f2 = brush(nt, P, 3.0, (1, 1, 1))
    base = paint(nt, base, f1, f2, 0.14)
    principled(nt, out, base, 0.82, 0.3, bump(nt, j, 0.5, 0.02))
    return m


def m_backdrop(name="ART_Backdrop"):
    """Priority 4: massing in an atmospheric, slightly desaturated tone (roof silhouettes read)."""
    m, nt, out = new_mat(name)
    geo = node(nt, "ShaderNodeNewGeometry")
    nz = sep(nt, geo.outputs["Normal"])[2]
    att = node(nt, "ShaderNodeAttribute", attribute_name="plateau_rgb", attribute_type="GEOMETRY").outputs["Color"]
    roof = mrange(nt, nz, 0.25, 0.5)
    wall = mix(nt, 0.5, att, (0.45, 0.42, 0.40))
    base = mix(nt, roof, wall, PAL["kawara"])
    f1, f2 = brush(nt, geo.outputs["Position"], 0.8, (1, 1, 2))
    base = paint(nt, base, f1, f2, 0.15)
    principled(nt, out, base, 0.85, 0.3)
    return m


# ------------------------------------------------------------------ ground
def _ishidatami(nt, uv_vec, P, width_socket=None, bw=0.62, rh=0.31, c1=None, c2=None, mortar=0.016):
    """Granite slab pattern on a 2D vector (x across, y along) in metres. Returns colour, joint.
    Defaults: ishidatami slabs ~0.3 x 0.6 m in running bond (building_evidence.json, Ninenzaka paving, observed)."""
    br = node(nt, "ShaderNodeTexBrick", {"Vector": uv_vec, "Scale": 1.0, "Mortar Size": mortar, "Mortar Smooth": 0.35,
                                         "Bias": 0.0, "Brick Width": bw, "Row Height": rh,
                                         "Color1": rgb(c1 or PAL["granite"]), "Color2": rgb(c2 or PAL["granite_warm"]),
                                         "Mortar": (0, 0, 0, 1)}, offset=0.45, offset_frequency=2)
    joint = br.outputs["Factor"]   # 1 in mortar
    col = br.outputs["Color"]
    speck = node(nt, "ShaderNodeTexNoise", {"Vector": P, "Scale": 38.0, "Detail": 1.0}).outputs["Factor"]
    col = mix(nt, mrange(nt, speck, 0.45, 0.7, 0.0, 0.25), col, (0.55, 0.53, 0.5))
    col = mix(nt, joint, col, (0.035, 0.04, 0.025))
    return col, joint


def m_paving(name="ART_Ishidatami", sett=False):
    """UV ribbon along P2 streets: u = along (m), v = across (m). Granite slabs (or small setts on Yasaka-dori west,
    OSM surface=sett), gutters, wet sheen."""
    m, nt, out = new_mat(name)
    uv = node(nt, "ShaderNodeUVMap", uv_map="UVMap").outputs[0]
    u, v, _ = sep(nt, uv)
    P = world_pos(nt)
    vec = comb(nt, v, u, 0.0)
    if sett:
        col, joint = _ishidatami(nt, vec, P, bw=0.24, rh=0.12, c1=PAL["sett"], c2=PAL["granite"], mortar=0.012)
    else:
        col, joint = _ishidatami(nt, vec, P)
    # edge band (gutter stones) |v| > half-width - 0.35 : stored in UV w via second attribute "edge"
    ue = node(nt, "ShaderNodeUVMap", uv_map="UVEdge").outputs[0]
    edge = mrange(nt, sep(nt, ue)[1], 0.30, 0.26)
    col = mix(nt, math(nt, "MULTIPLY", edge, 0.55), col, (0.16, 0.155, 0.15))
    f1, f2 = brush(nt, P, 2.0, (1.5, 1.5, 1))
    col = paint(nt, col, f1, f2, 0.12, 0.015)
    # worn, slightly polished centre; puddles
    wet = wetness(nt, P, 0.18, 0.09)
    dark = math(nt, "MAXIMUM", math(nt, "MULTIPLY", wet, 0.55), math(nt, "MULTIPLY", joint, 0.3))
    col = mix(nt, dark, col, (0.03, 0.03, 0.032), blend="MULTIPLY")
    rnoise = node(nt, "ShaderNodeTexNoise", {"Vector": P, "Scale": 1.4, "Detail": 3.0}).outputs["Factor"]
    rough = mrange(nt, rnoise, 0.35, 0.65, 0.22, 0.55)
    rough = mix(nt, wet, rough, 0.04, dtype="FLOAT")
    h = math(nt, "MULTIPLY", math(nt, "SUBTRACT", 1.0, joint), math(nt, "SUBTRACT", 1.0, wet))
    principled(nt, out, col, rough, 0.5, bump(nt, h, 0.35, 0.012))
    return m


def m_terrain(name="ART_Terrain", mask_img=None):
    m, nt, out = new_mat(name)
    P = world_pos(nt)
    uvn = node(nt, "ShaderNodeUVMap", uv_map="UVMap").outputs[0]
    # painterly warp of class borders (~0.4 m)
    wn = node(nt, "ShaderNodeTexNoise", {"Vector": P, "Scale": 1.3, "Detail": 2.0}).outputs["Color"]
    warp = vmath(nt, "SCALE", vmath(nt, "SUBTRACT", wn, (0.5, 0.5, 0.5)), scale=0.4 / 600.0)
    tex = node(nt, "ShaderNodeTexImage", {"Vector": vmath(nt, "ADD", uvn, warp)}, image=mask_img, interpolation="Cubic")
    R, G, B = sep(nt, tex.outputs["Color"])
    G = mrange(nt, G, 0.35, 0.65); R = mrange(nt, R, 0.35, 0.65); B = mrange(nt, B, 0.35, 0.65)
    f1, f2 = brush(nt, P, 1.5, (1.4, 1.4, 1))
    # soil / moss garden ground
    mz = node(nt, "ShaderNodeTexNoise", {"Vector": P, "Scale": 0.35, "Detail": 4.0}).outputs["Factor"]
    soil = mix(nt, mrange(nt, mz, 0.4, 0.6), PAL["soil"], PAL["moss"])
    leaflit = node(nt, "ShaderNodeTexNoise", {"Vector": P, "Scale": 2.5, "Detail": 2.0}).outputs["Factor"]
    soil = mix(nt, mrange(nt, leaflit, 0.62, 0.7, 0.0, 0.6), soil, (0.32, 0.08, 0.02))
    gravel = mix(nt, node(nt, "ShaderNodeTexNoise", {"Vector": P, "Scale": 60.0}).outputs["Factor"], (0.30, 0.27, 0.22), (0.48, 0.44, 0.37))
    # asphalt: worn, patched, cracked
    pz = node(nt, "ShaderNodeTexNoise", {"Vector": P, "Scale": 0.25, "Detail": 3.0}).outputs["Factor"]
    asp = mix(nt, mrange(nt, pz, 0.45, 0.7, 0.0, 0.5), PAL["asphalt"], (0.12, 0.115, 0.11))
    crk = node(nt, "ShaderNodeTexVoronoi", {"Vector": P, "Scale": 0.6, "Randomness": 1.0}, feature="DISTANCE_TO_EDGE").outputs["Distance"]
    asp = mix(nt, mrange(nt, crk, 0.012, 0.0, 0.0, 0.7), asp, (0.02, 0.02, 0.02))
    # stone paving in world coords (outside the ribbons)
    pav, joint = _ishidatami(nt, P, P)
    c = mix(nt, B, soil, gravel)
    c = mix(nt, R, c, asp)
    c = mix(nt, G, c, pav)
    c = paint(nt, c, f1, f2, 0.14, 0.02)
    wet = wetness(nt, P, 0.15, 0.10)
    hard = math(nt, "MAXIMUM", R, G)
    wet = math(nt, "MULTIPLY", wet, hard)
    c = mix(nt, math(nt, "MULTIPLY", wet, 0.5), c, (0.03, 0.03, 0.035), blend="MULTIPLY")
    rough = mix(nt, hard, 0.92, 0.5, dtype="FLOAT")
    rough = mix(nt, wet, rough, 0.05, dtype="FLOAT")
    h = math(nt, "MULTIPLY", math(nt, "SUBTRACT", 1.0, joint), G)
    principled(nt, out, c, rough, 0.45, bump(nt, h, 0.25, 0.01))
    return m


def m_steps(name="ART_Stone_Steps"):
    m, nt, out = new_mat(name)
    P = world_pos(nt)
    e, bn = edge_mask(nt, 0.04, 3)
    vc = node(nt, "ShaderNodeTexVoronoi", {"Vector": P, "Scale": 1.4}).outputs["Color"]
    base = mix(nt, math(nt, "MULTIPLY", sep(nt, vc)[0], 0.7), PAL["granite"], PAL["granite_warm"])
    speck = node(nt, "ShaderNodeTexNoise", {"Vector": P, "Scale": 40.0}).outputs["Factor"]
    base = mix(nt, mrange(nt, speck, 0.45, 0.7, 0, 0.25), base, (0.55, 0.53, 0.5))
    base = mix(nt, math(nt, "MULTIPLY", e, 0.55), base, (0.62, 0.6, 0.55))           # worn bright edges
    ao = node(nt, "ShaderNodeAmbientOcclusion", {"Distance": 0.35}, samples=2).outputs["AO"]
    mz = node(nt, "ShaderNodeTexNoise", {"Vector": P, "Scale": 2.0, "Detail": 3.0}).outputs["Factor"]
    moss = math(nt, "MULTIPLY", mrange(nt, ao, 0.8, 0.4), mrange(nt, mz, 0.4, 0.6))
    base = mix(nt, moss, base, PAL["moss"])
    f1, f2 = brush(nt, P, 3.0, (1, 1, 1))
    base = paint(nt, base, f1, f2, 0.12)
    wet = wetness(nt, P, 0.4, 0.12)
    rough = mix(nt, wet, mix(nt, e, 0.6, 0.35, dtype="FLOAT"), 0.12, dtype="FLOAT")
    principled(nt, out, base, rough, 0.45, bn)
    return m


def m_stonewall(name="ART_Stone_Wall_Mossy"):
    m, nt, out = new_mat(name)
    geo = node(nt, "ShaderNodeNewGeometry")
    P, N = geo.outputs["Position"], geo.outputs["Normal"]
    st = vmath(nt, "MULTIPLY", P, (1.0, 1.0, 1.6))
    vd = node(nt, "ShaderNodeTexVoronoi", {"Vector": st, "Scale": 2.2, "Randomness": 0.9}, feature="DISTANCE_TO_EDGE").outputs["Distance"]
    vc = node(nt, "ShaderNodeTexVoronoi", {"Vector": st, "Scale": 2.2, "Randomness": 0.9}).outputs["Color"]
    j = mrange(nt, vd, 0.0, 0.07)
    base = mix(nt, math(nt, "MULTIPLY", sep(nt, vc)[0], 0.8), (0.24, 0.22, 0.19), (0.38, 0.35, 0.30))
    base = mix(nt, math(nt, "SUBTRACT", 1.0, j), base, (0.03, 0.035, 0.02))
    nz = sep(nt, N)[2]
    mz = node(nt, "ShaderNodeTexNoise", {"Vector": P, "Scale": 1.2, "Detail": 4.0}).outputs["Factor"]
    moss = math(nt, "MAXIMUM", mrange(nt, nz, 0.4, 0.8), math(nt, "MULTIPLY", mrange(nt, mz, 0.48, 0.62), 0.85))
    base = mix(nt, moss, base, mix(nt, mz, PAL["moss"], PAL["moss_dry"]))
    f1, f2 = brush(nt, P, 2.5, (1, 1, 1.5))
    base = paint(nt, base, f1, f2, 0.14, 0.02)
    principled(nt, out, base, 0.85, 0.3, bump(nt, math(nt, "ADD", j, math(nt, "MULTIPLY", moss, 0.3)), 0.6, 0.03))
    return m


# ------------------------------------------------------------------ kit / prop materials
def m_simple(name, col, rough=0.75, brush_scale=4.0, stretch=(1, 1, 4), val=0.16, bevel=0.0, spec=0.35,
             grain=False, sheen=0.0, emission=None, estr=0.0, trans=0.0):
    m, nt, out = new_mat(name)
    P = node(nt, "ShaderNodeTexCoord").outputs["Object"]
    base = rgb(col)
    if grain:
        g = node(nt, "ShaderNodeTexWave", {"Vector": P, "Scale": 2.5, "Distortion": 8.0, "Detail": 3.0},
                 wave_type="BANDS", bands_direction="Z").outputs["Factor"]
        base = mix(nt, math(nt, "MULTIPLY", g, 0.35), base, tuple(c * 0.45 for c in col))
    f1, f2 = brush(nt, P, brush_scale, stretch)
    base = paint(nt, base, f1, f2, val, 0.02)
    nrm = None
    if bevel:
        e, nrm = edge_mask(nt, bevel, 2)
        base = mix(nt, math(nt, "MULTIPLY", e, 0.25), base, tuple(min(1, c * 1.8 + 0.03) for c in col))
    extra = {}
    if sheen:
        extra["Sheen_Weight"] = sheen
    if emission is not None:
        extra["Emission_Color"] = rgb(emission); extra["Emission_Strength"] = estr
    b = principled(nt, None, base, rough, spec, nrm, **extra)
    if trans:
        t = node(nt, "ShaderNodeBsdfTranslucent", {"Color": base})
        mx = node(nt, "ShaderNodeMixShader", {0: trans, 1: b.outputs[0], 2: t.outputs[0]})
        link(nt, mx.outputs[0], out.inputs["Surface"])
    else:
        link(nt, b.outputs[0], out.inputs["Surface"])
    return m


def m_noren(name, col, crest=(0.85, 0.82, 0.74)):
    m, nt, out = new_mat(name)
    uv = node(nt, "ShaderNodeUVMap").outputs[0]
    u, v, _ = sep(nt, uv)
    # crest: a soft circle centred in the cloth + a painted band
    d = vmath(nt, "DISTANCE", comb(nt, u, v, 0), (0.5, 0.55, 0))
    ring = math(nt, "MULTIPLY", mrange(nt, d, 0.17, 0.15), mrange(nt, d, 0.10, 0.12))
    band = mrange(nt, math(nt, "ABSOLUTE", math(nt, "SUBTRACT", v, 0.18)), 0.03, 0.02)
    P = node(nt, "ShaderNodeTexCoord").outputs["Object"]
    f1, f2 = brush(nt, P, 6.0, (1, 1, 3))
    base = paint(nt, rgb(col), f1, f2, 0.18)
    base = mix(nt, math(nt, "MAXIMUM", ring, band), base, crest)
    t = node(nt, "ShaderNodeBsdfTranslucent", {"Color": base})
    b = principled(nt, None, base, 0.9, 0.2, Sheen_Weight=0.4)
    mx = node(nt, "ShaderNodeMixShader", {0: 0.25, 1: b.outputs[0], 2: t.outputs[0]})
    link(nt, mx.outputs[0], out.inputs["Surface"])
    return m


def lamp_scale(nt, strength):
    """strength x per-shot lamp multiplier (Value node "LampScale", set by kit_light.apply_preset)."""
    v = nt.nodes.new("ShaderNodeValue"); v.name = "LampScale"; v.outputs[0].default_value = 1.0
    return math(nt, "MULTIPLY", v.outputs[0], strength)


def m_lantern(name="ART_Chochin", col=PAL["lantern"], strength=5.0, stripes=True):
    m, nt, out = new_mat(name)
    P = node(nt, "ShaderNodeTexCoord").outputs["Object"]
    z = sep(nt, P)[2]
    rib = math(nt, "POWER", math(nt, "ABSOLUTE", math(nt, "SINE", math(nt, "MULTIPLY", z, 90.0))), 8.0)
    e = mix(nt, math(nt, "MULTIPLY", rib, 0.5), rgb(col), tuple(c * 0.4 for c in col))
    if stripes:
        # dark calligraphy-ish band
        x = sep(nt, P)[0]
        mk = node(nt, "ShaderNodeTexNoise", {"Vector": comb(nt, math(nt, "MULTIPLY", x, 3.0), math(nt, "MULTIPLY", z, 9.0), 0), "Scale": 2.0, "Detail": 1.0}).outputs["Factor"]
        ink = math(nt, "MULTIPLY", mrange(nt, mk, 0.55, 0.62), mrange(nt, math(nt, "ABSOLUTE", z), 0.16, 0.12))
        e = mix(nt, ink, e, (0.03, 0.01, 0.01))
    em = node(nt, "ShaderNodeEmission", {"Color": e, "Strength": lamp_scale(nt, strength)})
    tr = node(nt, "ShaderNodeBsdfTranslucent", {"Color": e})
    add = node(nt, "ShaderNodeAddShader", {0: em.outputs[0], 1: tr.outputs[0]})
    link(nt, add.outputs[0], out.inputs["Surface"])
    return m


def m_glow(name="ART_ShopGlow", col=PAL["glow"], strength=1.1):
    m, nt, out = new_mat(name)
    P = node(nt, "ShaderNodeTexCoord").outputs["Object"]
    nz = node(nt, "ShaderNodeTexNoise", {"Vector": P, "Scale": 2.0, "Detail": 2.0}).outputs["Factor"]
    s = mrange(nt, nz, 0.3, 0.7, strength * 0.6, strength * 1.2)
    em = node(nt, "ShaderNodeEmission", {"Color": rgb(col), "Strength": lamp_scale(nt, s)})
    link(nt, em.outputs[0], out.inputs["Surface"])
    return m


def m_leaf(name, c0, c1, c2=None, trans=0.35, scale=0.25):
    """Leaves: colour varies by world-space noise and per-object random (Object Info)."""
    m, nt, out = new_mat(name)
    P = world_pos(nt)
    oi = node(nt, "ShaderNodeObjectInfo").outputs["Random"]
    nz = node(nt, "ShaderNodeTexNoise", {"Vector": P, "Scale": scale, "Detail": 2.0}).outputs["Factor"]
    t = math(nt, "MULTIPLY_ADD", oi, 0.35, math(nt, "MULTIPLY", nz, 0.9))
    col = mix(nt, mrange(nt, t, 0.35, 0.85), c0, c1)
    if c2 is not None:
        n2 = node(nt, "ShaderNodeTexNoise", {"Vector": P, "Scale": 1.7, "Detail": 1.0}).outputs["Factor"]
        col = mix(nt, mrange(nt, n2, 0.58, 0.72), col, c2)
    f1, f2 = brush(nt, P, 3.0, (1, 1, 1))
    col = paint(nt, col, f1, f2, 0.18, 0.025, 0.1)
    b = principled(nt, None, col, 0.6, 0.3)
    tr = node(nt, "ShaderNodeBsdfTranslucent", {"Color": col})
    mx = node(nt, "ShaderNodeMixShader", {0: trans, 1: b.outputs[0], 2: tr.outputs[0]})
    link(nt, mx.outputs[0], out.inputs["Surface"])
    return m


_LIB = {}


def M(name):
    """Get (building on first use) a named art material."""
    if name in _LIB and _LIB[name].name in bpy.data.materials:
        return _LIB[name]
    f = {
        "roof": m_roof, "facade": m_facade, "plinth": m_plinth, "backdrop": m_backdrop,
        "paving": m_paving, "paving_sett": lambda: m_paving("ART_Sett", sett=True), "steps": m_steps, "stonewall": m_stonewall,
        "wood_dark": lambda: m_simple("ART_Wood_Dark", PAL["wood_dark"], 0.7, grain=True, bevel=0.012),
        "wood_lattice": lambda: m_simple("ART_Wood_Bengara", PAL["wood_bengara"], 0.65, grain=True, bevel=0.006),
        "wood_weather": lambda: m_simple("ART_Wood_Weathered", PAL["wood_weather"], 0.8, grain=True, bevel=0.01),
        "plaster": lambda: m_simple("ART_Plaster_Kit", PAL["plaster"], 0.9, 3.0, (1, 1, 2.5), 0.10, bevel=0.015),
        "plaster_dark": lambda: m_simple("ART_Plaster_Shadow", (0.035, 0.028, 0.024), 0.9),
        "bamboo": lambda: m_simple("ART_Bamboo", (0.30, 0.24, 0.10), 0.55, 6.0, (1, 1, 6), 0.2, bevel=0.004),
        "bamboo_green": lambda: m_simple("ART_Bamboo_Green", (0.14, 0.22, 0.06), 0.45, 5.0, (1, 1, 8), 0.2),
        "sudare": lambda: m_simple("ART_Sudare", (0.36, 0.28, 0.15), 0.8, 8.0, (4, 1, 1), 0.22, trans=0.3),
        "ceramic": lambda: m_simple("ART_Ceramic_Glaze", (0.06, 0.05, 0.07), 0.25, 3.0, (1, 1, 1), 0.2, spec=0.6),
        "ceramic_ochre": lambda: m_simple("ART_Ceramic_Ochre", (0.30, 0.15, 0.06), 0.35, 3.0, (1, 1, 1), 0.2, spec=0.5),
        "stone_lantern": lambda: m_simple("ART_Stone_Lantern", (0.28, 0.27, 0.24), 0.85, 2.5, (1, 1, 1), 0.2, bevel=0.02),
        "metal": lambda: m_simple("ART_Metal_Dark", (0.03, 0.03, 0.03), 0.45, spec=0.5),
        "paper": lambda: m_simple("ART_Shoji_Paper", (0.75, 0.70, 0.60), 0.9, trans=0.4, emission=(1.0, 0.75, 0.45), estr=0.0),
        "red_felt": lambda: m_simple("ART_Red_Felt", (0.45, 0.04, 0.03), 0.95, sheen=0.5),
        "noren_indigo": lambda: m_noren("ART_Noren_Indigo", PAL["indigo"]),
        "noren_brown": lambda: m_noren("ART_Noren_Brown", (0.10, 0.05, 0.025)),
        "noren_cream": lambda: m_noren("ART_Noren_Cream", (0.55, 0.48, 0.36), (0.05, 0.05, 0.08)),
        "noren_persimmon": lambda: m_noren("ART_Noren_Persimmon", PAL["persimmon"]),
        "chochin_red": lambda: m_lantern("ART_Chochin_Red", (1.0, 0.18, 0.06), 2.2),
        "chochin_white": lambda: m_lantern("ART_Chochin_White", (1.0, 0.68, 0.38), 1.6),
        "andon": lambda: m_lantern("ART_Andon_Paper", (1.0, 0.72, 0.42), 1.6, stripes=False),
        "lantern_fire": lambda: m_lantern("ART_Lantern_Fire", (1.0, 0.5, 0.18), 6.0, stripes=False),
        "glow": m_glow,
        "glow_soft": lambda: m_glow("ART_ShopGlow_Soft", (1.0, 0.55, 0.25), 0.3),
        "bark": lambda: m_simple("ART_Bark", (0.05, 0.04, 0.035), 0.9, 4.0, (1, 1, 6), 0.25),
        "bark_cherry": lambda: m_simple("ART_Bark_Cherry", (0.07, 0.035, 0.03), 0.8, 4.0, (6, 6, 1), 0.25),
        "leaf_maple": lambda: m_leaf("ART_Leaf_Maple", (0.55, 0.035, 0.012), (0.75, 0.22, 0.02), (0.55, 0.42, 0.05)),
        "leaf_cherry": lambda: m_leaf("ART_Leaf_Cherry_Autumn", (0.42, 0.10, 0.03), (0.60, 0.33, 0.07), (0.25, 0.22, 0.05)),
        "leaf_pine": lambda: m_leaf("ART_Leaf_Pine", (0.025, 0.05, 0.02), (0.06, 0.09, 0.03), None, 0.2),
        "leaf_broad": lambda: m_leaf("ART_Leaf_Broadleaf", (0.05, 0.10, 0.025), (0.16, 0.18, 0.04), (0.45, 0.30, 0.04)),
        "leaf_ginkgo": lambda: m_leaf("ART_Leaf_Ginkgo", (0.70, 0.50, 0.04), (0.85, 0.66, 0.10), None),
        "leaf_bamboo": lambda: m_leaf("ART_Leaf_Bamboo", (0.08, 0.14, 0.03), (0.20, 0.24, 0.06), None, 0.4),
        "leaf_shrub": lambda: m_leaf("ART_Leaf_Shrub", (0.03, 0.07, 0.02), (0.09, 0.13, 0.03), (0.30, 0.10, 0.03), 0.25),
        "grass": lambda: m_leaf("ART_Grass_Weeds", (0.08, 0.12, 0.03), (0.22, 0.20, 0.06), None, 0.3),
        "moss": lambda: m_leaf("ART_Moss", (0.05, 0.10, 0.015), (0.14, 0.18, 0.03), None, 0.1, 1.5),
        "fallen_leaf": lambda: m_leaf("ART_Fallen_Leaves", (0.45, 0.06, 0.015), (0.62, 0.30, 0.04), (0.28, 0.14, 0.04), 0.2, 2.0),
        "fence": lambda: m_simple("ART_Fence_Bamboo", (0.22, 0.17, 0.09), 0.7, 5.0, (1, 1, 5), 0.2, grain=True),
    }[name]
    _LIB[name] = f()
    return _LIB[name]
