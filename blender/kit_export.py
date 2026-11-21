"""Phase 8 (Blender side): export the art-directed world for the Three.js explorer.

  /home/user/venv/bin/python blender/kit_export.py      -> web/assets/world_art.glb (+ size report)

Opens blender/higashiyama_art.blend (never saves it) and builds a light web version in place:
  * names/prefixes kept (Terrain_, B_, LM_, Steps_osm, Paving_osm, Barrier_, Tree*, Lantern_osm, Kit_*)
    with custom props (collide, walkable, plateau_id, osm_id, priority, detail_class ...) exported as extras
  * look baked into COLOR_0 vertex colours (buildings, steps, walls, trees) + 4 small textures:
    terrain_art (1024^2, from surface_mask + palette), ishidatami / sett tiles (512^2), kit atlas (1024^2)
  * Priority-2 machiya kit realised as simplified atlas-textured cards, merged per street (Kit_<street>)
  * trees -> shared low-poly species meshes (glTF mesh reuse)
  * excluded: hero pagoda + PLATEAU pagoda placeholder (web uses web/assets/pagoda.glb), fog, far DEM
    backdrop, fallen leaves, weeds, lights, cameras, OSM centrelines.
Y-up, no normals (flat shading in three.js; the scene is faceted anyway), extras on.
"""
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bpy  # noqa: E402
import bmesh  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image, ImageDraw, ImageFilter  # noqa: E402

ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "web", "assets", "world_art.glb")
import tempfile  # noqa: E402
TEX = tempfile.mkdtemp(prefix="kyoto_web_tex_")
A = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
if "--tex" in A:
    TEX = A[A.index("--tex") + 1]
os.makedirs(TEX, exist_ok=True)

bpy.ops.wm.open_mainfile(filepath=os.path.join(HERE, "higashiyama_art.blend"))
from kit_materials import PAL  # noqa: E402
from kit_common import PROC  # noqa: E402

scene = bpy.context.scene
rng = np.random.default_rng(7)


def srgb_to_lin(c):
    c = np.asarray(c, float) / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def lin_to_srgb8(c):
    c = np.clip(c, 0, 1)
    return (np.where(c <= 0.0031308, c * 12.92, 1.055 * c ** (1 / 2.4) - 0.055) * 255).astype(np.uint8)


# ------------------------------------------------------------------ textures
def tex_terrain():
    m = np.asarray(Image.open(os.path.join(PROC, "surface_mask.png")).convert("RGB"), float) / 255.0
    im = Image.fromarray((m * 255).astype(np.uint8)).resize((1024, 1024), Image.BILINEAR)
    m = np.asarray(im, float) / 255.0
    H, W, _ = m.shape
    yy, xx = np.mgrid[0:H, 0:W]
    n1 = np.asarray(Image.fromarray((rng.random((64, 64)) * 255).astype(np.uint8)).resize((W, H), Image.BICUBIC), float) / 255
    n2 = np.asarray(Image.fromarray((rng.random((256, 256)) * 255).astype(np.uint8)).resize((W, H), Image.BICUBIC), float) / 255
    soil = np.array(PAL["soil"]) * (1 - n1[..., None]) + np.array(PAL["moss"]) * n1[..., None]
    gravel = np.array([0.40, 0.36, 0.30]) * (0.85 + 0.3 * n2[..., None])
    asp = np.array(PAL["asphalt"]) * (0.9 + 0.5 * n1[..., None])
    stone = np.array(PAL["granite"]) * (0.85 + 0.3 * n2[..., None])
    c = soil
    for k, col in ((2, gravel), (0, asp), (1, stone)):
        f = np.clip((m[..., k] - 0.35) / 0.3, 0, 1)[..., None]
        c = c * (1 - f) + col * f
    img = Image.fromarray(lin_to_srgb8(c))
    p = os.path.join(TEX, "terrain_art.jpg")
    img.save(p, quality=85)
    return p


def tex_paving(name, bw_m, rh_m, c1, c2, period=1.24, size=512, mortar=0.016):
    s = size / period
    img = Image.new("RGB", (size, size))
    d = ImageDraw.Draw(img)
    rows = int(round(period / rh_m))
    for r in range(rows):
        off = (r % 2) * 0.45 * bw_m
        x = -off
        while x < period:
            t = rng.random()
            col = lin_to_srgb8(np.array(c1) * (1 - t) + np.array(c2) * t)
            d.rectangle([x * s, r * rh_m * s, (x + bw_m) * s - mortar * s, (r + 1) * rh_m * s - mortar * s], fill=tuple(int(v) for v in col))
            x += bw_m
    a = np.asarray(img, float)
    a *= (0.92 + 0.16 * rng.random(a.shape[:2]))[..., None]
    img = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)).filter(ImageFilter.SMOOTH)
    p = os.path.join(TEX, name)
    img.save(p, quality=88)
    return p


CELLS = {}


def tex_atlas():
    """1024^2 atlas, 4x4 cells of 256^2 (u right, v up)."""
    S = 256
    img = Image.new("RGB", (1024, 1024), (255, 255, 255))
    d = ImageDraw.Draw(img)
    C = lambda c: tuple(int(v) for v in lin_to_srgb8(np.array(c)))  # noqa: E731

    def cell(name, i, j):
        x0, y0 = i * S, (3 - j) * S          # image rows are top-down
        CELLS[name] = (i, j)
        return x0, y0

    x, y = cell("koshi", 0, 0)
    d.rectangle([x, y, x + S, y + S], fill=C((0.03, 0.025, 0.022)))
    for k in range(0, S, 8):
        d.rectangle([x + k, y, x + k + 4, y + S], fill=C(PAL["wood_bengara"]))
    d.rectangle([x, y + 40, x + S, y + 44], fill=C(PAL["wood_bengara"]))
    x, y = cell("koshi_lit", 1, 0)
    d.rectangle([x, y, x + S, y + S], fill=C((0.9, 0.55, 0.25)))
    for k in range(0, S, 8):
        d.rectangle([x + k, y, x + k + 4, y + S], fill=C(PAL["wood_bengara"]))
    d.rectangle([x, y + 40, x + S, y + 44], fill=C(PAL["wood_bengara"]))
    x, y = cell("door", 2, 0)
    d.rectangle([x, y, x + S, y + S], fill=C((0.75, 0.68, 0.55)))
    for k in range(0, S, 18):
        d.rectangle([x + k, y, x + k + 3, y + S], fill=C(PAL["wood_bengara"]))
    d.rectangle([x, y + 180, x + S, y + S], fill=C(PAL["wood_dark"]))
    d.rectangle([x + 124, y, x + 132, y + S], fill=C(PAL["wood_dark"]))
    x, y = cell("shop", 3, 0)
    d.rectangle([x, y, x + S, y + S], fill=C((1.0, 0.6, 0.3)))
    for k in (90, 150):
        d.rectangle([x, y + k, x + S, y + k + 6], fill=C(PAL["wood_weather"]))
    for k in range(10, S, 40):
        d.rectangle([x + k, y + 160, x + k + 25, y + 190], fill=C((0.2, 0.1, 0.05)))
    d.rectangle([x, y + 190, x + S, y + S], fill=C(PAL["wood_weather"]))
    for (nm, i, col, crest) in (("noren_indigo", 0, PAL["indigo"], (0.85, 0.82, 0.74)), ("noren_brown", 1, (0.10, 0.05, 0.025), (0.85, 0.82, 0.74)),
                                ("noren_cream", 2, (0.55, 0.48, 0.36), (0.05, 0.05, 0.08)), ("noren_persimmon", 3, PAL["persimmon"], (0.85, 0.82, 0.74))):
        x, y = cell(nm, i, 1)
        d.rectangle([x, y, x + S, y + S], fill=C(col))
        d.ellipse([x + 98, y + 70, x + 158, y + 130], outline=C(crest), width=8)
        for k in (85, 171):
            d.rectangle([x + k - 2, y + 60, x + k + 2, y + S], fill=C(np.array(col) * 0.4))
    x, y = cell("mushiko", 0, 2)
    d.rectangle([x, y, x + S, y + S], fill=C(PAL["plaster"]))
    for k in range(20, S - 20, 26):
        d.rounded_rectangle([x + k, y + 40, x + k + 12, y + S - 40], 5, fill=C((0.04, 0.03, 0.03)))
    x, y = cell("window", 1, 2)
    d.rectangle([x, y, x + S, y + S], fill=C((0.8, 0.72, 0.58)))
    for k in range(0, S, 16):
        d.rectangle([x + k, y, x + k + 3, y + S], fill=C(PAL["wood_dark"]))
    for k in range(120, S, 5):
        d.line([x, y + k, x + S, y + k], fill=C((0.30, 0.22, 0.11)), width=3)
    x, y = cell("bamboo", 2, 2)
    d.rectangle([x, y, x + S, y + S], fill=C((0.06, 0.05, 0.04)))
    for k in range(0, S, 12):
        d.rectangle([x + k, y, x + k + 8, y + S], fill=C((0.30, 0.24, 0.10)))
    x, y = cell("wood", 3, 2)
    d.rectangle([x, y, x + S, y + S], fill=C(PAL["wood_dark"]))
    for k in range(0, S, 32):
        d.line([x + k, y, x + k, y + S], fill=C((0.02, 0.012, 0.008)), width=2)
    x, y = cell("chochin_red", 0, 3)
    d.rectangle([x, y, x + S, y + S], fill=C((1.0, 0.2, 0.06)))
    for k in range(0, S, 14):
        d.line([x, y + k, x + S, y + k], fill=C((0.7, 0.1, 0.03)), width=2)
    d.rectangle([x + 100, y + 60, x + 156, y + 200], fill=C((0.05, 0.01, 0.01)))
    x, y = cell("paper_glow", 1, 3)
    d.rectangle([x, y, x + S, y + S], fill=C((1.0, 0.72, 0.42)))
    for k in range(0, S, 64):
        d.rectangle([x + k, y, x + k + 6, y + S], fill=C((0.03, 0.03, 0.03)))
    x, y = cell("stone", 2, 3)
    d.rectangle([x, y, x + S, y + S], fill=C(PAL["granite"]))
    x, y = cell("white", 3, 3)
    d.rectangle([x, y, x + S, y + S], fill=(255, 255, 255))
    p = os.path.join(TEX, "kit_atlas.png")
    img.save(p)
    return p


def img_mat(name, path, rough=0.85, emissive=False, double=False, repeat=True):
    m = bpy.data.materials.new(name)
    nt = m.node_tree
    b = nt.nodes.get("Principled BSDF")
    im = bpy.data.images.load(path)
    t = nt.nodes.new("ShaderNodeTexImage"); t.image = im
    t.extension = "REPEAT" if repeat else "EXTEND"
    vc = nt.nodes.new("ShaderNodeVertexColor"); vc.layer_name = "web_col"
    mul = nt.nodes.new("ShaderNodeMix"); mul.data_type = "RGBA"; mul.blend_type = "MULTIPLY"; mul.inputs[0].default_value = 1.0
    nt.links.new(t.outputs["Color"], mul.inputs[6]); nt.links.new(vc.outputs["Color"], mul.inputs[7])
    nt.links.new(mul.outputs[2], b.inputs["Base Color"])
    b.inputs["Roughness"].default_value = rough
    if emissive:
        nt.links.new(t.outputs["Color"], b.inputs["Emission Color"])
        b.inputs["Emission Strength"].default_value = 1.0
    m.use_backface_culling = not double
    return m


def vc_mat(name, rough=0.85, emissive=False, uv_map=None):
    """Vertex-colour material. With uv_map, a 4x4 white placeholder texture is multiplied in through that UV layer
    so the glTF exporter keeps the layer as TEXCOORD_0 (FacadeUV / RoofUV for web/assets/tex/ in Three.js)."""
    m = bpy.data.materials.new(name)
    nt = m.node_tree
    b = nt.nodes.get("Principled BSDF")
    vc = nt.nodes.new("ShaderNodeVertexColor"); vc.layer_name = "web_col"
    if uv_map:
        im = bpy.data.images.get("web_uv_placeholder")
        if im is None:
            im = bpy.data.images.new("web_uv_placeholder", 4, 4)
            im.pixels.foreach_set(np.ones(64, np.float32))
            im.pack()
        uv = nt.nodes.new("ShaderNodeUVMap"); uv.uv_map = uv_map
        t = nt.nodes.new("ShaderNodeTexImage"); t.image = im
        nt.links.new(uv.outputs[0], t.inputs[0])
        mul = nt.nodes.new("ShaderNodeMix"); mul.data_type = "RGBA"; mul.blend_type = "MULTIPLY"; mul.inputs[0].default_value = 1.0
        nt.links.new(t.outputs["Color"], mul.inputs[6]); nt.links.new(vc.outputs["Color"], mul.inputs[7])
        nt.links.new(mul.outputs[2], b.inputs["Base Color"])
        m["web_uv"] = uv_map
    else:
        nt.links.new(vc.outputs["Color"], b.inputs["Base Color"])
    b.inputs["Roughness"].default_value = rough
    if emissive:
        nt.links.new(vc.outputs["Color"], b.inputs["Emission Color"])
        b.inputs["Emission Strength"].default_value = 1.0
    return m


# ------------------------------------------------------------------ vertex colours
def set_corner_colors(me, cols):
    """cols: (n_loops, 3) linear -> FLOAT_COLOR corner attribute web_col (active), drop other colour attrs."""
    for a in list(me.color_attributes):
        if a.name != "web_col":
            me.color_attributes.remove(a)
    a = me.color_attributes.get("web_col") or me.color_attributes.new("web_col", "BYTE_COLOR", "CORNER")
    c4 = np.ones((len(me.loops), 4)); c4[:, :3] = np.clip(cols, 0, 1)
    a.data.foreach_set("color", c4.ravel())
    me.color_attributes.active_color = a
    me.color_attributes.render_color_index = me.color_attributes.find("web_col")


def poly_loop_arrays(me):
    mi = np.empty(len(me.polygons), np.int32); me.polygons.foreach_get("material_index", mi)
    ls = np.empty(len(me.polygons), np.int32); me.polygons.foreach_get("loop_start", ls)
    lt = np.empty(len(me.polygons), np.int32); me.polygons.foreach_get("loop_total", lt)
    nz = np.empty(len(me.polygons) * 3); me.polygons.foreach_get("normal", nz); nz = nz.reshape(-1, 3)[:, 2]
    loop_poly = np.repeat(np.arange(len(me.polygons)), lt)
    return mi, loop_poly, nz


def building_colors(ob, pr):
    me = ob.data
    ca = me.color_attributes.get("plateau_rgb")
    n = len(me.loops)
    pc = np.full((n, 3), 0.55)
    if ca is not None and len(ca.data) == n:
        t = np.empty(n * 4); ca.data.foreach_get("color", t); pc = t.reshape(-1, 4)[:, :3]
    mi, lp, nz = poly_loop_arrays(me)
    lmi, lnz = mi[lp], nz[lp]
    jit = 1.0          # no per-face jitter: identical corners merge in the glTF primitive (size)
    pc = np.round(pc * 64) / 64
    lum = pc @ np.array([0.2126, 0.7152, 0.0722])
    grey = lum[:, None]
    roof = 0.8 * np.array(PAL["kawara"]) + 0.2 * (grey + 0.4 * (pc - grey))
    wood_w = np.clip((0.16 - lum) / 0.09, 0, 1)[:, None]
    plaster = 0.58 * (grey + 0.7 * (pc - grey)) + 0.42 * np.array(PAL["plaster"])
    wood = 0.45 * pc + 0.55 * np.array(PAL["wood_dark"])
    wall = plaster * (1 - wood_w) + wood * wood_w
    plinth = np.tile(PAL["granite"], (n, 1))
    if pr == 4:
        isroof = (lnz > 0.3)[:, None]
        col = np.where(isroof, np.array(PAL["kawara"]), 0.5 * pc + 0.5 * np.array([0.45, 0.42, 0.40]))
    else:
        col = np.where((lmi == 0)[:, None], roof, np.where((lmi == 1)[:, None], wall, plinth))
        # roof slab undersides (eave soffits) read as dark timber
        col = np.where(((lmi == 0) & (lnz < -0.5))[:, None], np.array(PAL["wood_weather"]), col)
    set_corner_colors(me, col * jit)


def flat_colors(ob, rgb, var=0.12):
    me = ob.data
    mi, lp, nz = poly_loop_arrays(me)
    jit = (1 - var / 2 + var * rng.random(len(me.polygons)))[lp][:, None]
    set_corner_colors(me, np.tile(rgb, (len(me.loops), 1)) * jit)


# ------------------------------------------------------------------ web kit (atlas cards)
def build_web_kit(mat_kit, mat_glow):
    """Realise every P2 kit placement as simple cards, merged per street -> Kit_<street> objects."""
    def uvq(cell):
        i, j = CELLS[cell]
        e = 2 / 1024
        return [(i / 4 + e, j / 4 + e), ((i + 1) / 4 - e, j / 4 + e), ((i + 1) / 4 - e, (j + 1) / 4 - e), (i / 4 + e, (j + 1) / 4 - e)]

    W = 1.82

    def quad(x0, x1, y0, y1, z0, z1, cell, glow=False, col=(1, 1, 1)):
        # card facing -Y (street); bottom-left, bottom-right, top-right, top-left
        return [([(x0, y0, z0), (x1, y1, z0), (x1, y1, z1), (x0, y0, z1)], uvq(cell), glow, col)]

    def box(x0, x1, y0, y1, z0, z1, col, glow=False):
        q = []
        P = lambda x, y, z: (x, y, z)  # noqa: E731
        X, Y, Z = (x0, x1), (y0, y1), (z0, z1)
        for vs in ([P(X[0], Y[0], Z[0]), P(X[1], Y[0], Z[0]), P(X[1], Y[0], Z[1]), P(X[0], Y[0], Z[1])],
                   [P(X[0], Y[0], Z[1]), P(X[1], Y[0], Z[1]), P(X[1], Y[1], Z[1]), P(X[0], Y[1], Z[1])],
                   [P(X[0], Y[1], Z[0]), P(X[0], Y[0], Z[0]), P(X[0], Y[0], Z[1]), P(X[0], Y[1], Z[1])],
                   [P(X[1], Y[0], Z[0]), P(X[1], Y[1], Z[0]), P(X[1], Y[1], Z[1]), P(X[1], Y[0], Z[1])],
                   [P(X[0], Y[1], Z[0]), P(X[1], Y[1], Z[0]), P(X[1], Y[0], Z[0]), P(X[0], Y[0], Z[0])]):
            q.append((vs, uvq("white"), glow, col))
        return q

    wd, ww, kw = PAL["wood_dark"], PAL["wood_weather"], PAL["kawara"]
    K = {
        "K_Koshi": quad(0.05, W - 0.05, -0.11, -0.11, -0.3, 2.42, "koshi") + box(0, W, -0.17, 0, 2.42, 2.6, wd),
        "K_Koshi_Lit": quad(0.05, W - 0.05, -0.11, -0.11, -0.3, 2.42, "koshi_lit", glow=True) + box(0, W, -0.17, 0, 2.42, 2.6, wd),
        "K_Door": quad(0.05, W - 0.05, -0.08, -0.08, 0.0, 2.2, "door") + box(0, W, -0.17, 0, 2.2, 2.6, wd),
        "K_ShopFront": quad(0.05, W - 0.05, -0.03, -0.03, 0.0, 2.2, "shop", glow=True) + box(0, W, -0.17, 0, 2.2, 2.6, wd)
        + box(0.1, W - 0.1, -0.38, -0.05, 0.0, 0.75, ww),
        "K_Noren_Indigo": quad(0.08, W - 0.08, -0.225, -0.225, 1.2, 2.2, "noren_indigo"),
        "K_Noren_Brown": quad(0.08, W - 0.08, -0.225, -0.225, 1.2, 2.2, "noren_brown"),
        "K_Noren_Cream": quad(0.08, W - 0.08, -0.225, -0.225, 1.2, 2.2, "noren_cream"),
        "K_Noren_Persimmon": quad(0.08, W - 0.08, -0.225, -0.225, 1.2, 2.2, "noren_persimmon"),
        "K_Hisashi": [([(0, 0, 0), (0, -0.95, -0.36), (1, -0.95, -0.36), (1, 0, 0)][::-1], uvq("white"), False, kw),
                      ([(0, 0, -0.07), (1, 0, -0.07), (1, -0.95, -0.43), (0, -0.95, -0.43)][::-1], uvq("white"), False, ww),
                      ([(0, -0.95, -0.43), (1, -0.95, -0.43), (1, -0.95, -0.36), (0, -0.95, -0.36)], uvq("white"), False, kw)],
        "K_Mushiko": quad(0.13, W - 0.13, -0.075, -0.075, -0.05, 0.67, "mushiko"),
        "K_Window2F": quad(0.12, W - 0.12, -0.1, -0.1, -0.06, 1.0, "window"),
        "K_Railing2F": box(0.05, W - 0.05, -0.42, -0.36, 0.55, 0.62, wd) + box(0.05, W - 0.05, -0.42, -0.36, -0.05, 0.02, wd),
        "K_Inuyarai": [([(0, -0.42, 0.0), (W, -0.42, 0.0), (W, -0.33, 0.5), (0, -0.33, 0.5)], uvq("bamboo"), False, (1, 1, 1)),
                       ([(0, -0.33, 0.5), (W, -0.33, 0.5), (W, 0.0, 0.95), (0, 0.0, 0.95)], uvq("bamboo"), False, (1, 1, 1))],
        "K_Kanban": box(-0.025, 0.025, -0.68, -0.18, 1.75, 2.55, (0.2, 0.13, 0.07)) + box(0.15, 0.47, -0.035, 0, 0.9, 2.1, (0.2, 0.13, 0.07)),
        "K_Chochin_Red": box(-0.17, 0.17, -0.72, -0.38, 2.13, 2.53, (1, 1, 1), glow=True),
        "K_Chochin_White": box(-0.17, 0.17, -0.72, -0.38, 2.13, 2.53, (1, 1, 1), glow=True),
        "K_Lantern_Black": box(-0.13, 0.13, -0.67, -0.41, 2.05, 2.45, (1, 1, 1), glow=True) + box(-0.15, 0.15, -0.69, -0.39, 2.45, 2.5, (0.03, 0.03, 0.03)),
        "K_Andon": box(-0.14, 0.14, -0.37, -0.09, 0.6, 1.15, (1, 1, 1), glow=True) + box(-0.02, 0.02, -0.25, -0.21, 0, 0.6, wd),
        "K_LampPost": box(-0.05, 0.05, -0.65, -0.55, 0.0, 2.65, (0.03, 0.03, 0.03)) + box(-0.15, 0.15, -0.75, -0.45, 2.65, 3.1, (1, 1, 1), glow=True),
        "K_Bracket": box(-0.05, 0.05, -0.85, 0.0, -0.5, -0.37, wd),
        "K_Post": box(-0.06, 0.06, -0.035, 0.0, 0.0, 1.0, wd),
        "K_Beam": box(0.0, 1.0, -0.04, 0.0, -0.16, 0.0, wd),
        "K_Pot_A": box(-0.18, 0.18, -0.48, -0.12, 0, 0.3, (0.06, 0.05, 0.07)) + box(-0.22, 0.22, -0.52, -0.08, 0.3, 0.7, PAL["moss"]),
        "K_Pot_B": box(-0.18, 0.18, -0.48, -0.12, 0, 0.3, (0.30, 0.15, 0.06)) + box(-0.3, 0.3, -0.6, 0.0, 0.6, 1.0, (0.55, 0.08, 0.02)),
        "K_Pot_C": box(-0.18, 0.18, -0.48, -0.12, 0, 0.3, (0.06, 0.05, 0.07)) + box(-0.2, 0.2, -0.5, -0.1, 0.3, 0.75, (0.12, 0.16, 0.04)),
        "K_Bench": box(0, 1.6, -0.75, -0.35, 0.36, 0.47, (0.45, 0.04, 0.03)),
    }
    glow_cells = {"K_Chochin_Red": "chochin_red"}
    streets = {}
    for e in bpy.data.objects:
        kp = e.get("kit_piece") if e.type == "EMPTY" else None
        if not kp or kp not in K:
            continue
        st = e.get("street", "misc")
        mw = np.array(e.matrix_world)
        for vs, uvs, glow, col in K[kp]:
            if glow and kp in glow_cells:
                uvs = uvq(glow_cells[kp])
            elif glow and kp != "K_Koshi_Lit" and kp != "K_ShopFront":
                uvs = uvq("paper_glow")
            v = np.c_[np.array(vs), np.ones(4)] @ mw.T
            streets.setdefault(st, []).append((v[:, :3], uvs, glow, col))
    out = []
    for st, quads in streets.items():
        V = np.concatenate([q[0] for q in quads])
        F = np.arange(len(V)).reshape(-1, 4)
        me = bpy.data.meshes.new("Kit_" + st)
        me.from_pydata(V.tolist(), [], F.tolist())
        me.materials.append(mat_kit); me.materials.append(mat_glow)
        me.polygons.foreach_set("material_index", np.array([1 if q[2] else 0 for q in quads], np.int32))
        uv = me.uv_layers.new(name="UVMap")
        uv.data.foreach_set("uv", np.array([q[1] for q in quads]).reshape(-1, 2).ravel())
        cols = np.repeat(np.array([q[3] for q in quads], float), 4, axis=0)
        set_corner_colors(me, cols)
        ob = bpy.data.objects.new("Kit_" + st, me)
        scene.collection.objects.link(ob)
        ob["street"] = st; ob["collide"] = False
        ob["detail_class"] = "inferred/observed per placement (see blender/higashiyama_art.blend 60_Machiya_Kit)"
        ob["note"] = "Priority-2 machiya kit realised as simplified atlas cards, merged per street"
        out.append(ob)
    return out


# ------------------------------------------------------------------ web trees
def build_web_trees():
    coll = bpy.data.collections.new("W_Trees")
    scene.collection.children.link(coll)
    spec = {
        "Maple": dict(trunk=1.8, crown=[(0, 0, 3.4, 2.4, 1.3)], col=(0.55, 0.08, 0.02)),
        "Cherry": dict(trunk=2.4, crown=[(0, 0, 4.2, 3.0, 1.5)], col=(0.45, 0.16, 0.04)),
        "Pine": dict(trunk=3.0, crown=[(0.4, 0, 3.0, 1.3, 0.45), (-0.3, 0.3, 4.3, 1.0, 0.4), (0, 0, 5.6, 0.9, 0.35)], col=(0.03, 0.06, 0.025)),
        "Broad": dict(trunk=3.0, crown=[(0, 0, 5.4, 2.8, 2.3)], col=(0.07, 0.11, 0.03)),
        "Ginkgo": dict(trunk=3.0, crown=[(0, 0, 5.4, 2.4, 2.6)], col=(0.70, 0.50, 0.05)),
        "Bamboo": dict(trunk=6.0, crown=[(0, 0, 6.5, 1.6, 2.5)], col=(0.10, 0.16, 0.04)),
        "Shrub": dict(trunk=0.0, crown=[(0, 0, 0.5, 0.7, 0.45)], col=(0.04, 0.08, 0.025)),
        "Weeds": None,
    }
    meshes = {}
    for k, sp in spec.items():
        if sp is None:
            continue
        bm = bmesh.new()
        cols = []
        if sp["trunk"] > 0:
            r = bmesh.ops.create_cone(bm, cap_ends=False, segments=5, radius1=0.2, radius2=0.12, depth=sp["trunk"])
            for v in r["verts"]:
                v.co.z += sp["trunk"] / 2
        nf = len(bm.faces)
        for (x, y, z, rx, rz) in sp["crown"]:
            r = bmesh.ops.create_icosphere(bm, subdivisions=1, radius=1.0)
            for v in r["verts"]:
                v.co.x = v.co.x * rx * (1 + 0.15 * rng.normal()) + x
                v.co.y = v.co.y * rx * (1 + 0.15 * rng.normal()) + y
                v.co.z = v.co.z * rz + z
        me = bpy.data.meshes.new("W_Tree_" + k)
        bm.to_mesh(me); bm.free()
        me.materials.append(MAT["leaf"])
        n = len(me.polygons)
        mi, lp, nz = poly_loop_arrays(me)
        c = np.where((lp < nf)[:, None], np.array([0.06, 0.045, 0.035]), np.array(sp["col"]))
        c = c * (0.85 + 0.3 * rng.random(n))[lp][:, None]
        set_corner_colors(me, c)
        meshes[k] = me
    n = 0
    for e in list(bpy.data.objects):
        if e.type != "EMPTY" or not e.get("proto"):
            continue
        k = e["proto"].split("_")[1]
        if k not in meshes:
            bpy.data.objects.remove(e, do_unlink=True)
            continue
        # one node per tree: a mesh object sharing the species mesh, same name + props as the empty
        ch = bpy.data.objects.new(e.name + "_w", meshes[k])
        ch.matrix_world = e.matrix_world.copy()
        for kk in e.keys():
            ch[kk] = e[kk]
        for c in e.users_collection:
            c.objects.link(ch)
        nm = e.name
        bpy.data.objects.remove(e, do_unlink=True)
        ch.name = nm
        ch["web_tree"] = True
        n += 1
    return n


# ------------------------------------------------------------------ main
MAT = {}


def main():
    print("textures...")
    p_ter = tex_terrain()
    p_pav = tex_paving("ishidatami.jpg", 0.62, 0.31, PAL["granite"], PAL["granite_warm"])
    p_set = tex_paving("sett.jpg", 0.24, 0.124, PAL["sett"], PAL["granite"], period=0.992, size=256, mortar=0.012)
    p_atl = tex_atlas()
    MAT["roof"] = vc_mat("W_Roof", 0.6); MAT["wall"] = vc_mat("W_Wall", 0.9); MAT["plinth"] = vc_mat("W_Plinth", 0.9)
    for k_, nm_, col_ in (("p4roof", "W_Backdrop_Roof", PAL["kawara"]), ("p4wall", "W_Backdrop_Wall", (0.42, 0.38, 0.33))):
        m_ = bpy.data.materials.new(nm_); b_ = m_.node_tree.nodes.get("Principled BSDF")
        b_.inputs["Base Color"].default_value = (*col_, 1); b_.inputs["Roughness"].default_value = 0.85
        MAT[k_] = m_

    def uv_mat(name, col, rough):
        """placeholder texture through WebUV x constant colour (web swaps in web/assets/tex/)"""
        m_ = vc_mat(name, rough, uv_map="WebUV")
        nt_ = m_.node_tree
        vcn = next(n for n in nt_.nodes if n.type == "VERTEX_COLOR")
        rgbn = nt_.nodes.new("ShaderNodeRGB"); rgbn.outputs[0].default_value = (*col, 1)
        mul_ = next(n for n in nt_.nodes if n.type == "MIX")
        nt_.links.new(rgbn.outputs[0], mul_.inputs[7]); nt_.nodes.remove(vcn)
        return m_
    MAT["roof_uv"] = uv_mat("W_Roof_Kawara", PAL["kawara"], 0.6)
    MAT["wall_uv"] = uv_mat("W_Wall_Facade", (0.55, 0.47, 0.34), 0.9)
    MAT["plinth_uv"] = uv_mat("W_Plinth_Stone", PAL["granite"], 0.9)
    MAT["stone"] = vc_mat("W_Stone", 0.85); MAT["leaf"] = vc_mat("W_Foliage", 0.8); MAT["glowvc"] = vc_mat("W_LampGlow", 0.5, emissive=True)
    MAT["terrain"] = img_mat("W_Terrain", p_ter, 0.9, repeat=False)
    MAT["paving"] = img_mat("W_Ishidatami", p_pav, 0.55); MAT["sett"] = img_mat("W_Sett", p_set, 0.6)
    MAT["kit"] = img_mat("W_Kit", p_atl, 0.8, double=True); MAT["kitglow"] = img_mat("W_KitGlow", p_atl, 0.6, emissive=True, double=True)

    # --- drop what the web must not get
    drop_prefix = ("FX_", "Backdrop_DEM10B", "Veg_FallenLeaves", "Weeds_art", "OSM_", "Boundary", "Cam_", "KitLight", "Sun")
    hero = set()
    for c in bpy.data.collections:
        if c.name.startswith("Yasaka_Pagoda_HERO") or c.name == "36_Hero_Pagoda":
            hero |= set(c.all_objects)
    for ob in list(bpy.data.objects):
        if ob in hero or ob.name.startswith(drop_prefix) or ob.type in ("LIGHT", "CAMERA") or ob.get("exclude_web") \
                or ob.name.startswith("LM_Yasaka_Pagoda"):
            bpy.data.objects.remove(ob, do_unlink=True)
    kit_web = build_web_kit(MAT["kit"], MAT["kitglow"])
    print("kit streets", [o.name for o in kit_web])
    # instances of kit pieces are now realised -> remove empties
    for ob in list(bpy.data.objects):
        if ob.type == "EMPTY" and ob.get("kit_piece"):
            bpy.data.objects.remove(ob, do_unlink=True)
    nt = build_web_trees()
    print("web trees", nt)

    # --- per-object look baking
    for ob in list(bpy.data.objects):
        if ob.type != "MESH" or ob.name.startswith(("Kit_", "W_Tree")) or ob.parent is not None:
            continue
        me = ob.data
        nm = ob.name
        if ob.get("web_tree"):
            continue
        if nm.startswith(("Steps_", "Barrier_", "UtilityPole", "UtilityWires")):
            for uvl in list(me.uv_layers):
                me.uv_layers.remove(uvl)
        if nm.startswith(("UtilityPole", "UtilityWires")):
            flat_colors(ob, (0.30, 0.29, 0.27) if nm.startswith("UtilityPole") else (0.02, 0.02, 0.02))
            me.materials.clear(); me.materials.append(MAT["stone"])
            continue
        if nm.startswith(("B_", "LM_")):
            pr = ob.get("priority", 3)
            building_colors(ob, pr)
            if pr == 4:       # backdrop massing: constant materials, roof (normal up) vs wall split by face normal
                mi_, lp_, nz_ = poly_loop_arrays(me)
                me.polygons.foreach_set("material_index", np.where(nz_ > 0.3, 0, 1).astype(np.int32))
                me.color_attributes.remove(me.color_attributes["web_col"])
                me["web_p4"] = True
            has_uv = pr != 4 and me.uv_layers.get("FacadeUV") is not None and me.uv_layers.get("RoofUV") is not None
            ks = ("roof_uv", "wall_uv", "plinth_uv") if has_uv else (("p4roof", "p4wall", "p4wall") if pr == 4 else ("roof", "wall", "plinth"))
            if has_uv:
                # one UV layer for the web: FacadeUV on wall faces (u = bays, v = m), RoofUV on roof faces (m)
                mi, lp, nz = poly_loop_arrays(me)
                fa = np.empty(len(me.loops) * 2); me.uv_layers["FacadeUV"].data.foreach_get("uv", fa)
                ra = np.empty(len(me.loops) * 2); me.uv_layers["RoofUV"].data.foreach_get("uv", ra)
                isroof = (mi[lp] == 0)
                w = np.where(np.repeat(isroof, 2), ra, fa)
                w = np.round(w * 256) / 256
                for uvl in list(me.uv_layers):
                    me.uv_layers.remove(uvl)
                me.uv_layers.new(name="WebUV").data.foreach_set("uv", w)
                me.color_attributes.remove(me.color_attributes["web_col"])
                me["web_p4"] = True       # (exported without vertex colours)
            else:
                for uvl in list(me.uv_layers):
                    me.uv_layers.remove(uvl)
            for i in range(len(me.materials)):        # (materials.clear() would reset the face material indices)
                me.materials[i] = MAT[ks[min(i, 2)]]
        elif nm.startswith("Terrain_"):
            dec = ob.modifiers.new("dec", "DECIMATE"); dec.ratio = 0.25
            bpy.context.view_layer.objects.active = ob
            with bpy.context.temp_override(object=ob, active_object=ob):
                bpy.ops.object.modifier_apply(modifier="dec")
            for uvl in list(me.uv_layers):
                if uvl.name != "UVMap":
                    me.uv_layers.remove(uvl)
            flat_colors(ob, (1, 1, 1), 0.0)
            me.materials.clear(); me.materials.append(MAT["terrain"])
        elif nm.startswith("Paving_"):
            uv = me.uv_layers["UVMap"]
            a = np.empty(len(uv.data) * 2); uv.data.foreach_get("uv", a)
            sett = ob.get("surface") == "sett"
            a = a / (0.992 if sett else 1.24)
            a = a.reshape(-1, 2)[:, ::-1].ravel()          # texture x across, y along
            uv.data.foreach_set("uv", a)
            for nmuv in ("UVEdge", "UVPave"):
                if me.uv_layers.get(nmuv):
                    me.uv_layers.remove(me.uv_layers[nmuv])
            flat_colors(ob, (1, 1, 1), 0.0)
            me.materials.clear(); me.materials.append(MAT["sett" if sett else "paving"])
        elif nm.startswith("Steps_"):
            flat_colors(ob, np.array(PAL["granite"]) * 1.1)
            me.materials.clear(); me.materials.append(MAT["stone"])
        elif nm.startswith("Barrier_"):
            kind = ob.get("barrier", "")
            col = (0.30, 0.28, 0.24) if kind in ("wall", "retaining_wall", "city_wall") else (0.22, 0.17, 0.09)
            flat_colors(ob, col)
            me.materials.clear(); me.materials.append(MAT["stone"])
        elif nm.startswith(("Lantern_osm", "StreetLamp_osm")):
            mi, lp, nz = poly_loop_arrays(me)
            names = [m.name for m in me.materials]
            glow = np.array([("Fire" in names[i] or "Andon" in names[i]) if i < len(names) else False for i in mi])
            c = np.where(glow[lp][:, None], np.array([1.0, 0.6, 0.3]), np.array([0.30, 0.29, 0.26]))
            set_corner_colors(me, c)
            me.materials.clear(); me.materials.append(MAT["stone"]); me.materials.append(MAT["glowvc"])
            me.polygons.foreach_set("material_index", glow.astype(np.int32))
        else:
            # anything else (unknown helper meshes) is not exported
            ob["_skip"] = True
    # --- select and export
    bpy.ops.object.select_all(action="DESELECT")
    keep = 0
    for ob in bpy.data.objects:
        if ob.get("_skip"):
            continue
        if ob.type == "MESH" and ob.data.color_attributes.get("web_col") is None and not ob.data.get("web_p4"):
            continue
        if ob.type in ("MESH", "EMPTY"):
            if ob.type == "EMPTY" and not ob.name.startswith(("Tree", "Shrub")):
                continue
            ob.hide_set(False)
            try:
                ob.select_set(True); keep += 1
            except RuntimeError:
                pass
    # unhide collections so selection works
    def unexclude(lc):
        lc.exclude = False
        for ch in lc.children:
            unexclude(ch)
    unexclude(bpy.context.view_layer.layer_collection)
    for ob in bpy.data.objects:
        if not ob.get("_skip") and (ob.type == "MESH" and (ob.data.color_attributes.get("web_col") is not None or ob.data.get("web_p4"))
                                    or ob.type == "EMPTY" and ob.name.startswith(("Tree", "Shrub"))):
            try:
                ob.hide_set(False); ob.hide_viewport = False; ob.select_set(True)
            except RuntimeError:
                pass
    KEEP = {"plateau_id", "priority", "collide", "walkable", "osm_id", "detail_class", "species", "species_src", "documented",
            "artistic", "street_front", "height", "storeys", "usage", "usage_ja", "year", "name", "name_ja", "width_m", "surface",
            "barrier", "height_m", "n_steps", "in_boundary", "street", "note", "source", "evidence_ref", "wall_inset_m"}
    sel = [o for o in bpy.context.selected_objects]
    for o in sel:
        for k in list(o.keys()):
            if k not in KEEP:
                del o[k]
        if o.name.startswith(("Tree", "Shrub")) and "evidence_ref" in o:
            del o["evidence_ref"]
    print("exporting", len(sel), "objects")
    bpy.ops.export_scene.gltf(filepath=OUT, export_format="GLB", use_selection=True, export_extras=True,
                              export_yup=True, export_apply=False, export_normals=False, export_tangents=False,
                              export_vertex_color="ACTIVE", export_all_vertex_colors=False,
                              export_image_format="AUTO", export_materials="EXPORT", export_cameras=False,
                              export_lights=False, export_animations=False)
    sz = os.path.getsize(OUT)
    print("GLB %s %.2f MB" % (OUT, sz / 1e6))


main()
