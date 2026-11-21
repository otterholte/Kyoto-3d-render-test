"""Blender materials built from the PNW texture library (blender/textures/library.json).

Node layout is kept glTF-exporter friendly:
  Image(albedo) -> [Mix MULTIPLY tint] -> Principled Base Color     (tint -> glTF baseColorFactor)
  Image(orm, Non-Color) -> Separate Color: G -> Roughness, B -> Metallic   (-> metallicRoughnessTexture)
  Image(normal, Non-Color) -> Normal Map -> Normal                  (-> normalTexture)
  UV (metres) -> Mapping scale 1/size_m                             (-> KHR_texture_transform)
Every material stores custom props: tex_set, tint (sRGB hex), alpha_mode, double_sided, emissive (for export
post-processing in export_web.py).
"""
import json
import os

import bpy

from cc_common import TEX_BL, hex2lin, srgb2lin

_LIB = None


def lib():
    global _LIB
    if _LIB is None:
        _LIB = json.load(open(os.path.join(TEX_BL, "library.json")))["sets"]
    return _LIB


def img(fn, noncolor=False):
    key = fn
    im = bpy.data.images.get(key)
    if im is None:
        im = bpy.data.images.load(os.path.join(TEX_BL, fn), check_existing=True)
        im.name = key
    if noncolor:
        im.colorspace_settings.name = "Non-Color"
    return im


def _new(name):
    m = bpy.data.materials.get(name)
    if m is not None:
        return m, False
    m = bpy.data.materials.new(name)
    try:
        m.use_nodes = True
    except Exception:
        pass
    return m, True


def tex_mat(name, tex_set, tint=None, rough_mul=None, normal_strength=1.0, uv="UVMap", alpha=False,
            double_sided=False, emissive=None, emit_strength=0.0, scale=None, spec=0.5, translucency=0.0,
            ao_in_albedo=0.0, rough_override=None):
    """tint: sRGB hex multiplied with the (neutral) albedo. scale: override texture repeat (metres)."""
    m, new = _new(name)
    if not new:
        return m
    L = lib()[tex_set]
    sx, sy = scale or L["size_m"]
    nt = m.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    out.location = (600, 0)
    bs = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bs.location = (300, 0)
    nt.links.new(bs.outputs[0], out.inputs["Surface"])
    uvn = nt.nodes.new("ShaderNodeUVMap")
    uvn.uv_map = uv
    uvn.location = (-900, 0)
    mp = nt.nodes.new("ShaderNodeMapping")
    mp.location = (-700, 0)
    mp.inputs["Scale"].default_value = (1.0 / sx, 1.0 / sy, 1.0)
    nt.links.new(uvn.outputs[0], mp.inputs[0])
    f = L["files"]
    ta = nt.nodes.new("ShaderNodeTexImage")
    ta.image = img(f["albedo"])
    ta.location = (-450, 250)
    nt.links.new(mp.outputs[0], ta.inputs[0])
    col_out = ta.outputs["Color"]
    if tint:
        mx = nt.nodes.new("ShaderNodeMix")
        mx.data_type = "RGBA"
        mx.blend_type = "MULTIPLY"
        mx.inputs["Factor"].default_value = 1.0
        mx.location = (-150, 250)
        nt.links.new(col_out, mx.inputs[6])
        mx.inputs[7].default_value = hex2lin(tint)
        col_out = mx.outputs[2]
        m["tint"] = tint
    nt.links.new(col_out, bs.inputs["Base Color"])
    if alpha:
        nt.links.new(ta.outputs["Alpha"], bs.inputs["Alpha"])
        m["alpha_mode"] = "MASK"
        try:
            m.surface_render_method = "DITHERED"
        except Exception:
            pass
    to = nt.nodes.new("ShaderNodeTexImage")
    to.image = img(f["orm"], True)
    to.location = (-450, -50)
    nt.links.new(mp.outputs[0], to.inputs[0])
    sep = nt.nodes.new("ShaderNodeSeparateColor")
    sep.location = (-150, -50)
    nt.links.new(to.outputs["Color"], sep.inputs[0])
    if rough_override is not None:
        bs.inputs["Roughness"].default_value = rough_override
    elif rough_mul:
        mm = nt.nodes.new("ShaderNodeMath")
        mm.operation = "MULTIPLY"
        mm.inputs[1].default_value = rough_mul
        nt.links.new(sep.outputs[1], mm.inputs[0])
        nt.links.new(mm.outputs[0], bs.inputs["Roughness"])
    else:
        nt.links.new(sep.outputs[1], bs.inputs["Roughness"])
    nt.links.new(sep.outputs[2], bs.inputs["Metallic"])
    tn = nt.nodes.new("ShaderNodeTexImage")
    tn.image = img(f["normal"], True)
    tn.location = (-450, -350)
    nt.links.new(mp.outputs[0], tn.inputs[0])
    nm = nt.nodes.new("ShaderNodeNormalMap")
    nm.location = (-150, -350)
    nm.inputs["Strength"].default_value = normal_strength
    nt.links.new(tn.outputs["Color"], nm.inputs["Color"])
    nt.links.new(nm.outputs[0], bs.inputs["Normal"])
    try:
        bs.inputs["Specular IOR Level"].default_value = spec
    except Exception:
        pass
    if translucency > 0:
        # subsurface-ish leaf transmission for Cycles (not exported)
        try:
            bs.inputs["Subsurface Weight"].default_value = 0.0
            bs.inputs["Transmission Weight"].default_value = 0.0
        except Exception:
            pass
        _add_translucency(nt, bs, out, col_out, translucency)
    if emissive is not None:
        if isinstance(emissive, str) and emissive in f:
            te = nt.nodes.new("ShaderNodeTexImage")
            te.image = img(f[emissive], True)
            nt.links.new(mp.outputs[0], te.inputs[0])
            nt.links.new(te.outputs["Color"], bs.inputs["Emission Color"])
        else:
            bs.inputs["Emission Color"].default_value = emissive
        bs.inputs["Emission Strength"].default_value = emit_strength
    m["tex_set"] = tex_set
    m["double_sided"] = bool(double_sided)
    m.use_backface_culling = not double_sided
    return m


def _add_translucency(nt, bs, out, col_out, amount):
    tr = nt.nodes.new("ShaderNodeBsdfTranslucent")
    tr.location = (300, -300)
    hsv = nt.nodes.new("ShaderNodeHueSaturation")
    hsv.inputs["Saturation"].default_value = 1.25
    hsv.inputs["Value"].default_value = 1.3
    nt.links.new(col_out, hsv.inputs["Color"])
    nt.links.new(hsv.outputs[0], tr.inputs["Color"])
    mix = nt.nodes.new("ShaderNodeMixShader")
    mix.location = (450, -100)
    mix.inputs[0].default_value = amount
    nt.links.new(bs.outputs[0], mix.inputs[1])
    nt.links.new(tr.outputs[0], mix.inputs[2])
    # keep alpha: wrap the mix in a transparent mix driven by albedo alpha (Principled alpha only affects itself)
    alpha_src = None
    for l in nt.links:
        if l.to_socket == bs.inputs["Alpha"]:
            alpha_src = l.from_socket
    if alpha_src is not None:
        tp = nt.nodes.new("ShaderNodeBsdfTransparent")
        mx2 = nt.nodes.new("ShaderNodeMixShader")
        nt.links.new(alpha_src, mx2.inputs[0])
        nt.links.new(tp.outputs[0], mx2.inputs[1])
        nt.links.new(mix.outputs[0], mx2.inputs[2])
        nt.links.new(mx2.outputs[0], out.inputs["Surface"])
    else:
        nt.links.new(mix.outputs[0], out.inputs["Surface"])


def flat_mat(name, hex_col, rough=0.6, metal=0.0, emit=None, emit_strength=0.0, alpha=1.0, spec=0.5, coat=0.0):
    m, new = _new(name)
    if not new:
        return m
    nt = m.node_tree
    bs = nt.nodes.get("Principled BSDF")
    if bs is None:
        nt.nodes.clear()
        out = nt.nodes.new("ShaderNodeOutputMaterial")
        bs = nt.nodes.new("ShaderNodeBsdfPrincipled")
        nt.links.new(bs.outputs[0], out.inputs["Surface"])
    bs.inputs["Base Color"].default_value = hex2lin(hex_col)
    bs.inputs["Roughness"].default_value = rough
    bs.inputs["Metallic"].default_value = metal
    try:
        bs.inputs["Specular IOR Level"].default_value = spec
        bs.inputs["Coat Weight"].default_value = coat
    except Exception:
        pass
    if emit:
        bs.inputs["Emission Color"].default_value = hex2lin(emit)
        bs.inputs["Emission Strength"].default_value = emit_strength
        m["emissive"] = emit
    if alpha < 1:
        bs.inputs["Alpha"].default_value = alpha
        m["alpha_mode"] = "BLEND"
    m["tint"] = hex_col
    m.diffuse_color = hex2lin(hex_col)
    return m


def glass_mat(name="GLASS_window", interior_cell=None, lit=False):
    """Opaque window glass: reflective coat over the interior atlas (no transmission -> no empty interiors).
    UV of glass faces spans the atlas cell."""
    m, new = _new(name)
    if not new:
        return m
    nt = m.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bs = nt.nodes.new("ShaderNodeBsdfPrincipled")
    nt.links.new(bs.outputs[0], out.inputs["Surface"])
    L = lib()["window_interior"]["files"]
    uvn = nt.nodes.new("ShaderNodeUVMap")
    uvn.uv_map = "UVMap"
    ta = nt.nodes.new("ShaderNodeTexImage")
    ta.image = img(L["albedo"])
    nt.links.new(uvn.outputs[0], ta.inputs[0])
    mx = nt.nodes.new("ShaderNodeMix")
    mx.data_type = "RGBA"
    mx.blend_type = "MULTIPLY"
    mx.inputs["Factor"].default_value = 1.0
    nt.links.new(ta.outputs["Color"], mx.inputs[6])
    mx.inputs[7].default_value = (0.55, 0.57, 0.6, 1)
    nt.links.new(mx.outputs[2], bs.inputs["Base Color"])
    bs.inputs["Roughness"].default_value = 0.35
    bs.inputs["Metallic"].default_value = 0.0
    try:
        bs.inputs["Coat Weight"].default_value = 1.0
        bs.inputs["Coat Roughness"].default_value = 0.02
        bs.inputs["Coat IOR"].default_value = 1.52
        bs.inputs["Specular IOR Level"].default_value = 0.5
    except Exception:
        pass
    m["tint"] = "#c4c7cc"
    m["tex_set"] = "window_interior"
    m["glass"] = True
    if lit:
        te = nt.nodes.new("ShaderNodeTexImage")
        te.image = img(L["emit"], True)
        nt.links.new(uvn.outputs[0], te.inputs[0])
        mul = nt.nodes.new("ShaderNodeMix")
        mul.data_type = "RGBA"
        mul.blend_type = "MULTIPLY"
        mul.inputs["Factor"].default_value = 1.0
        nt.links.new(te.outputs["Color"], mul.inputs[6])
        mul.inputs[7].default_value = (1.0, 0.62, 0.3, 1)
        nt.links.new(mul.outputs[2], bs.inputs["Emission Color"])
        bs.inputs["Emission Strength"].default_value = 3.0
        m["emissive"] = "#ffb060"
        m["lit"] = True
    return m


_cache = {}


def M(key, factory):
    """Memo helper: M('roof_3905', lambda: tex_mat(...))."""
    if key not in _cache:
        _cache[key] = factory()
    return _cache[key]
