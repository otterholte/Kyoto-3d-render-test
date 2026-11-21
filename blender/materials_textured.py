"""Image-based (texture library) materials and UV helpers for PLATEAU LOD2 buildings.

Usage (inside Blender / bpy):
    import materials_textured as MT
    mat  = MT.make_material("TX_Ishidatami", "ishidatami_granite")            # UVs in metres -> real scale
    fac  = MT.make_facade_material()                                           # facade atlas, per-face module choice
    roof = MT.make_roof_material()                                             # kawara field + eave + ridge strips
    info = MT.assign_facades(obj, building_attrs, streets=MT.load_streets())  # UV + module attributes on wall faces
    MT.apply_roof_uvs(obj)                                                     # tile rows aligned to each eave

Conventions (see docs/texture_library.md): albedo sRGB; normal = OpenGL tangent space (+Y up); ORM = AO/rough/metal.
UV layers written here:
    "FacadeUV"  wall faces: u = bays along the wall (integer bays per wall plane, left->right seen from outside),
                v = metres above the wall base
    "RoofUV"    roof faces: u = metres along the eave, v = metres up-slope from the face's eave line
    "UVMap"     (make_material default) - metres for tileable sets
Face attributes (FLOAT_COLOR, face domain) written by apply_wall_facade_uvs: fac_gf, fac_gf_alt, fac_uf, fac_uf_alt,
fac_top  (= atlas uv rects u0, v0, u1, v1) and fac_h (FLOAT_VECTOR: gf height m, upper storey height m, n upper storeys),
fac_p (FLOAT_VECTOR: p_alt_gf, p_alt_uf, seed).  Corner attribute "roof_ridge_dist" (metres to the face's top edge).
"""
import json
import math
import os
import zlib

import bpy
import bmesh  # noqa: F401  (bpy first)
import numpy as np
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TEX = os.path.join(HERE, "textures")
_LIB = None
_ATLAS = None


def library():
    global _LIB
    if _LIB is None:
        _LIB = json.load(open(os.path.join(TEX, "library.json")))
    return _LIB


def atlas():
    global _ATLAS
    if _ATLAS is None:
        _ATLAS = json.load(open(os.path.join(TEX, "facade_atlas.json")))
    return _ATLAS


def _img(fn, noncolor):
    key = fn
    im = bpy.data.images.get(key)
    if im is None:
        im = bpy.data.images.load(os.path.join(TEX, fn), check_existing=True)
        im.name = key
    if noncolor:
        im.colorspace_settings.name = "Non-Color"
    return im


class _NT:
    def __init__(self, mat):
        self.nt = mat.node_tree
        self.nt.nodes.clear()
        self.x = 0

    def n(self, t, **kw):
        node = self.nt.nodes.new(t)
        for k, v in kw.items():
            setattr(node, k, v)
        node.location = (self.x, 0); self.x += 40
        return node

    def l(self, a, b):
        self.nt.links.new(a, b)

    def math(self, op, a, b=None, clamp=False):
        m = self.n("ShaderNodeMath", operation=op, use_clamp=clamp)
        for i, v in enumerate((a, b)):
            if v is None:
                continue
            if isinstance(v, (int, float)):
                m.inputs[i].default_value = v
            else:
                self.l(v, m.inputs[i])
        return m.outputs[0]

    def mixc(self, fac, a, b):
        m = self.n("ShaderNodeMix", data_type="RGBA")
        for sock, v in ((m.inputs[0], fac), (m.inputs[6], a), (m.inputs[7], b)):
            if isinstance(v, (int, float)):
                sock.default_value = v
            elif isinstance(v, tuple):
                sock.default_value = v
            else:
                self.l(v, sock)
        return m.outputs[2]

    def mixv(self, fac, a, b):
        m = self.n("ShaderNodeMix", data_type="VECTOR")
        for sock, v in ((m.inputs[0], fac), (m.inputs[4], a), (m.inputs[5], b)):
            if isinstance(v, (int, float)):
                sock.default_value = v
            else:
                self.l(v, sock)
        return m.outputs[1]

    def tex(self, vec, fn, noncolor=False, interp="Linear", ext="REPEAT"):
        t = self.n("ShaderNodeTexImage", interpolation=interp, extension=ext)
        t.image = _img(fn, noncolor)
        self.l(vec, t.inputs[0])
        return t


def _surface(T, out_mat, alb, nrm, orm, emit=None, tint=None, uv_map="UVMap", normal_strength=1.0, emit_strength=0.0,
             emit_color=(1.0, 0.72, 0.42), ao_mult=0.8, alpha=None):
    """Principled BSDF from albedo/normal/ORM sockets (Color outputs)."""
    bsdf = T.n("ShaderNodeBsdfPrincipled")
    out = T.n("ShaderNodeOutputMaterial")
    T.l(bsdf.outputs[0], out.inputs[0])
    sep = T.n("ShaderNodeSeparateColor")
    T.l(orm, sep.inputs[0])
    col = alb
    if tint is not None:
        col = T.mixc(1.0, col, (*tint, 1.0)); col.node.blend_type = "MULTIPLY"
    # baked AO as micro-occlusion on the base colour (Cycles adds its own large-scale AO/GI)
    aop = T.math("POWER", sep.outputs[0], ao_mult)
    cm = T.n("ShaderNodeMix", data_type="RGBA", blend_type="MULTIPLY")
    cm.inputs[0].default_value = 1.0
    T.l(col, cm.inputs[6])
    cc = T.n("ShaderNodeCombineColor")
    for i in range(3):
        T.l(aop, cc.inputs[i])
    T.l(cc.outputs[0], cm.inputs[7])
    T.l(cm.outputs[2], bsdf.inputs["Base Color"])
    T.l(sep.outputs[1], bsdf.inputs["Roughness"])
    T.l(sep.outputs[2], bsdf.inputs["Metallic"])
    nm = T.n("ShaderNodeNormalMap", uv_map=uv_map)
    nm.inputs["Strength"].default_value = normal_strength
    T.l(nrm, nm.inputs["Color"])
    T.l(nm.outputs[0], bsdf.inputs["Normal"])
    if emit is not None:
        T.l(emit, bsdf.inputs["Emission Color"])
        bsdf.inputs["Emission Strength"].default_value = emit_strength
        # tint emission warm via multiply node
        em = T.n("ShaderNodeMix", data_type="RGBA", blend_type="MULTIPLY"); em.inputs[0].default_value = 1
        T.l(emit, em.inputs[6]); em.inputs[7].default_value = (*emit_color, 1)
        T.l(em.outputs[2], bsdf.inputs["Emission Color"])
    if alpha is not None:
        T.l(alpha, bsdf.inputs["Alpha"])
    return bsdf


def make_material(name, set_name, uv_scale=None, tint=None, uv_map="UVMap", normal_strength=1.0, emit_strength=0.0,
                  replace=True):
    """Image-based Principled material for a tileable/strip set of the library.

    uv_scale: None -> mesh UVs are in METRES and the texture repeats every size_m (real scale);
              float or (su, sv) -> UVs are multiplied by this (e.g. 1.0 for UVs already in texture units).
    tint:     optional linear RGB multiplier on albedo.
    """
    lib = library()["sets"][set_name]
    mat = bpy.data.materials.get(name)
    if mat is None or replace:
        mat = mat or bpy.data.materials.new(name)
    T = _NT(mat)
    uv = T.n("ShaderNodeUVMap", uv_map=uv_map)
    if uv_scale is None:
        sx, sy = 1.0 / lib["size_m"][0], 1.0 / lib["size_m"][1]
    elif isinstance(uv_scale, (int, float)):
        sx = sy = float(uv_scale)
    else:
        sx, sy = uv_scale
    mp = T.n("ShaderNodeMapping")
    mp.inputs["Scale"].default_value = (sx, sy, 1.0)
    T.l(uv.outputs[0], mp.inputs[0])
    v = mp.outputs[0]
    f = lib["files"]
    ext = "REPEAT" if lib.get("kind", "tileable") == "tileable" else "EXTEND"
    alb = T.tex(v, f["albedo"])
    nrm = T.tex(v, f["normal"], True)
    orm = T.tex(v, f["orm"], True)
    emit = T.tex(v, f["emit"], True).outputs[0] if "emit" in f else None
    _surface(T, mat, alb.outputs[0], nrm.outputs[0], orm.outputs[0], emit, tint, uv_map, normal_strength, emit_strength,
             alpha=alb.outputs["Alpha"] if f["albedo"].endswith(".png") else None)
    mat["texlib_set"] = set_name
    return mat


# ----------------------------------------------------------------------------- facade atlas material
def make_facade_material(name="TX_Facade_Atlas", emit_strength=0.0, normal_strength=1.0):
    """Facade atlas material. Needs FacadeUV + fac_* attributes written by apply_wall_facade_uvs()."""
    A = atlas()
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    T = _NT(mat)
    uv = T.n("ShaderNodeUVMap", uv_map="FacadeUV")
    sp = T.n("ShaderNodeSeparateXYZ"); T.l(uv.outputs[0], sp.inputs[0])
    u, vm = sp.outputs[0], sp.outputs[1]

    def attr(nm):
        a = T.n("ShaderNodeAttribute", attribute_type="GEOMETRY", attribute_name=nm)
        return a
    h = T.n("ShaderNodeSeparateXYZ"); T.l(attr("fac_h").outputs["Vector"], h.inputs[0])
    gfh, ufh, nup = h.outputs[0], h.outputs[1], h.outputs[2]
    p = T.n("ShaderNodeSeparateXYZ"); T.l(attr("fac_p").outputs["Vector"], p.inputs[0])
    pgf, puf, seed = p.outputs[0], p.outputs[1], p.outputs[2]
    bay = T.math("FLOOR", u)
    uu = T.math("FRACT", u)
    # per-bay random (deterministic): white noise on (bay + seed*17.31)
    wn = T.n("ShaderNodeTexWhiteNoise", noise_dimensions="1D")
    T.l(T.math("ADD", bay, T.math("MULTIPLY", seed, 17.31)), wn.inputs["W"])
    rnd = wn.outputs["Value"]
    # storey index
    is_gf = T.math("LESS_THAN", vm, gfh)
    above = T.math("SUBTRACT", vm, gfh)
    k_up = T.math("DIVIDE", above, ufh)
    is_top = T.math("GREATER_THAN", k_up, nup)          # gable / attic above the last full storey
    v_gf = T.math("DIVIDE", vm, gfh)
    v_up = T.math("FRACT", k_up)
    vv = T.mixv(is_gf, v_up, v_gf)  # vector mix: use x component only
    vv_s = T.n("ShaderNodeSeparateXYZ"); T.l(vv, vv_s.inputs[0])
    vv = vv_s.outputs[0]
    # upper-storey random uses bay + storey index
    wn2 = T.n("ShaderNodeTexWhiteNoise", noise_dimensions="2D")
    cxy = T.n("ShaderNodeCombineXYZ")
    T.l(T.math("ADD", bay, T.math("MULTIPLY", seed, 5.13)), cxy.inputs[0]); T.l(T.math("FLOOR", k_up), cxy.inputs[1])
    T.l(cxy.outputs[0], wn2.inputs["Vector"])
    rnd2 = wn2.outputs["Value"]

    def rect(nm):
        a = attr(nm)
        return a.outputs["Color"], a.outputs["Alpha"]
    gf_c, gf_a = rect("fac_gf"); gfa_c, gfa_a = rect("fac_gf_alt")
    uf_c, uf_a = rect("fac_uf"); ufa_c, ufa_a = rect("fac_uf_alt")
    tp_c, tp_a = rect("fac_top")
    use_gfa = T.math("LESS_THAN", rnd, pgf)
    use_ufa = T.math("LESS_THAN", rnd2, puf)
    g_c = T.mixc(use_gfa, gf_c, gfa_c); g_a = T.math("ADD", T.math("MULTIPLY", gf_a, T.math("SUBTRACT", 1.0, use_gfa)),
                                                     T.math("MULTIPLY", gfa_a, use_gfa))
    u_c = T.mixc(use_ufa, uf_c, ufa_c); u_a = T.math("ADD", T.math("MULTIPLY", uf_a, T.math("SUBTRACT", 1.0, use_ufa)),
                                                     T.math("MULTIPLY", ufa_a, use_ufa))
    up_c = T.mixc(is_top, u_c, tp_c); up_a = T.math("ADD", T.math("MULTIPLY", u_a, T.math("SUBTRACT", 1.0, is_top)),
                                                   T.math("MULTIPLY", tp_a, is_top))
    r_c = T.mixc(is_gf, up_c, g_c); r_a = T.math("ADD", T.math("MULTIPLY", up_a, T.math("SUBTRACT", 1.0, is_gf)),
                                                 T.math("MULTIPLY", g_a, is_gf))
    rs = T.n("ShaderNodeSeparateColor"); T.l(r_c, rs.inputs[0])
    u0, v0, u1 = rs.outputs[0], rs.outputs[1], rs.outputs[2]
    v1 = r_a
    # clamp the in-module coordinate half a texel inside the rect (padding handles the rest)
    eps = 0.5 / A["atlas_size_px"][0]
    uu_c = T.math("MINIMUM", T.math("MAXIMUM", uu, 0.0), 1.0)
    vv_c = T.math("MINIMUM", T.math("MAXIMUM", vv, 0.0), 1.0)
    au = T.math("ADD", u0, T.math("MULTIPLY", uu_c, T.math("SUBTRACT", u1, u0)))
    av = T.math("ADD", v0, T.math("MULTIPLY", vv_c, T.math("SUBTRACT", v1, v0)))
    cv = T.n("ShaderNodeCombineXYZ"); T.l(au, cv.inputs[0]); T.l(av, cv.inputs[1])
    f = A["files"]
    alb = T.tex(cv.outputs[0], f["albedo"], ext="EXTEND")
    nrm = T.tex(cv.outputs[0], f["normal"], True, ext="EXTEND")
    orm = T.tex(cv.outputs[0], f["orm"], True, ext="EXTEND")
    emt = T.tex(cv.outputs[0], f["emit"], True, ext="EXTEND")
    _surface(T, mat, alb.outputs[0], nrm.outputs[0], orm.outputs[0], emt.outputs[0], None, "FacadeUV", normal_strength,
             emit_strength, ao_mult=0.9)
    mat["texlib_set"] = "facade_atlas"
    return mat


def make_roof_material(name="TX_Roof_Kawara", field="roof_kawara_sangawara", eave="roof_kawara_eave",
                       ridge="roof_kawara_ridge", tint=None, use_strips=True):
    """Kawara roof: tile field (RoofUV metres) + eave strip at v < strip height + ridge strip near the top edge."""
    L = library()["sets"]
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    T = _NT(mat)
    uv = T.n("ShaderNodeUVMap", uv_map="RoofUV")
    sp = T.n("ShaderNodeSeparateXYZ"); T.l(uv.outputs[0], sp.inputs[0])
    u, v = sp.outputs[0], sp.outputs[1]
    rd = T.n("ShaderNodeAttribute", attribute_type="GEOMETRY", attribute_name="roof_ridge_dist").outputs["Fac"]

    def vec(a, b):
        c = T.n("ShaderNodeCombineXYZ"); T.l(a, c.inputs[0]); T.l(b, c.inputs[1]); return c.outputs[0]
    F = L[field]; E = L[eave]; R = L[ridge]
    vf = vec(T.math("DIVIDE", u, F["size_m"][0]), T.math("DIVIDE", v, F["size_m"][1]))
    sets = [(T.tex(vf, F["files"]["albedo"]), T.tex(vf, F["files"]["normal"], True), T.tex(vf, F["files"]["orm"], True))]
    a_s, n_s, o_s = sets[0][0].outputs[0], sets[0][1].outputs[0], sets[0][2].outputs[0]
    if use_strips:
        ve = vec(T.math("DIVIDE", u, E["size_m"][0]), T.math("DIVIDE", v, E["size_m"][1]))
        vr = vec(T.math("DIVIDE", u, R["size_m"][0]), T.math("SUBTRACT", 1.0, T.math("DIVIDE", rd, R["size_m"][1])))
        for S_, vv, mask in ((E, ve, T.math("LESS_THAN", v, E["size_m"][1] * 0.98)),
                             (R, vr, T.math("LESS_THAN", rd, R["size_m"][1] * 0.98))):
            ta = T.tex(vv, S_["files"]["albedo"], ext="EXTEND"); tn = T.tex(vv, S_["files"]["normal"], True, ext="EXTEND")
            to = T.tex(vv, S_["files"]["orm"], True, ext="EXTEND")
            # repeat in u: EXTEND clamps v only if we wrap u ourselves
            for t_ in (ta, tn, to):
                t_.extension = "REPEAT"
            a_s = T.mixc(mask, a_s, ta.outputs[0]); n_s = T.mixc(mask, n_s, tn.outputs[0]); o_s = T.mixc(mask, o_s, to.outputs[0])
    _surface(T, mat, a_s, n_s, o_s, None, tint, "RoofUV", 1.0, 0.0)
    mat["texlib_set"] = field
    return mat


# ----------------------------------------------------------------------------- geometry helpers
def _wall_groups(me, mw, wall_faces, tol_deg=4.0, tol_off=0.2):
    groups = {}
    for p in wall_faces:
        n = mw.to_3x3() @ p.normal
        nh = Vector((n.x, n.y, 0.0))
        if nh.length < 1e-6:
            continue
        nh.normalize()
        az = math.degrees(math.atan2(nh.y, nh.x)) % 360
        c = mw @ p.center
        off = c.dot(nh)
        key = None
        for k in groups:
            daz = abs((k[0] - az + 180) % 360 - 180)
            if daz < tol_deg and abs(k[1] - off) < tol_off:
                key = k; break
        if key is None:
            key = (az, off)
            groups[key] = {"faces": [], "n": nh}
        groups[key]["faces"].append(p)
    return list(groups.values())


def _rect(name):
    return tuple(atlas()["modules"][name]["uv_rect"])


def apply_wall_facade_uvs(obj, facade_assignments, wall_pred=None, base_z=None):
    """UV-map PLATEAU wall faces and write per-face module attributes.

    facade_assignments: dict (same for every wall) or callable(group_info) -> dict with keys
        gf, gf_alt, uf, uf_alt, top (module names), p_gf_alt, p_uf_alt (0..1), gf_h, uf_h (m), n_upper (int),
        optional gf_half / uf_half (used when the wall plane is narrower than 0.7 bay).
      group_info = {"normal": Vector, "length": m, "center": Vector, "zmin": m, "zmax": m, "index": i}
    wall_pred(poly, world_normal) -> bool selects wall faces (default: |n.z| < 0.35 and material slot != roof).
    Returns the list of group infos (with the chosen assignment) for logging.
    """
    me = obj.data
    mw = obj.matrix_world
    if wall_pred is None:
        def wall_pred(p, n):
            return abs(n.z) < 0.35 and p.material_index != 2
    walls = [p for p in me.polygons if wall_pred(p, (mw.to_3x3() @ p.normal).normalized())]
    uvl = me.uv_layers.get("FacadeUV") or me.uv_layers.new(name="FacadeUV")
    names = ("fac_gf", "fac_gf_alt", "fac_uf", "fac_uf_alt", "fac_top")
    for nm in names:
        if nm not in me.attributes:
            me.attributes.new(nm, "FLOAT_COLOR", "FACE")
    for nm in ("fac_h", "fac_p"):
        if nm not in me.attributes:
            me.attributes.new(nm, "FLOAT_VECTOR", "FACE")
    attrs = {nm: me.attributes[nm].data for nm in names + ("fac_h", "fac_p")}
    infos = []
    mods = atlas()["modules"]
    for gi, g in enumerate(_wall_groups(me, mw, walls)):
        n = g["n"]
        t = Vector((0, 0, 1)).cross(n).normalized()          # along the wall, left->right seen from outside
        pts = [mw @ me.vertices[vi].co for p in g["faces"] for vi in p.vertices]
        s = [q.dot(t) for q in pts]
        zs = [q.z for q in pts]
        smin, smax = min(s), max(s)
        Lw = max(smax - smin, 1e-3)
        zmin = min(zs) if base_z is None else max(min(zs), base_z - 0.6)
        info = {"normal": n, "length": Lw, "center": sum(pts, Vector()) / len(pts), "zmin": zmin, "zmax": max(zs),
                "index": gi}
        asg = facade_assignments(info) if callable(facade_assignments) else dict(facade_assignments)
        half = Lw < 0.7 * mods[asg["gf"]]["width_m"]
        gfm = asg.get("gf_half", asg["gf"]) if half else asg["gf"]
        ufm = asg.get("uf_half", asg["uf"]) if half else asg["uf"]
        w = mods[gfm]["width_m"]
        nb = max(1, int(round(Lw / w)))
        info.update(asg=asg, bays=nb)
        infos.append(info)
        r = {"fac_gf": _rect(gfm), "fac_gf_alt": _rect(asg.get("gf_alt") or gfm) if not half else _rect(gfm),
             "fac_uf": _rect(ufm), "fac_uf_alt": _rect(asg.get("uf_alt") or ufm) if not half else _rect(ufm),
             "fac_top": _rect(asg.get("top", ufm))}
        hv = (asg.get("gf_h", 3.0), asg.get("uf_h", 2.4), float(asg.get("n_upper", 1)))
        pv = (asg.get("p_gf_alt", 0.0), asg.get("p_uf_alt", 0.0), float(asg.get("seed", gi % 97)))
        for p in g["faces"]:
            for nm, rv in r.items():
                attrs[nm][p.index].color = rv
            attrs["fac_h"][p.index].vector = hv
            attrs["fac_p"][p.index].vector = pv
            for li in p.loop_indices:
                q = mw @ me.vertices[me.loops[li].vertex_index].co
                uvl.data[li].uv = ((q.dot(t) - smin) / Lw * nb, q.z - zmin)
    return infos


def apply_roof_uvs(obj, roof_pred=None, tol_deg=3.0):
    """RoofUV per coplanar roof plane: u = metres along the eave (horizontal), v = metres up-slope from the plane's
    lowest point (eave line); corner attr roof_ridge_dist = metres down from the plane's highest point.
    Flat roofs (slope < 3 deg) get u = x, v = y and ridge distance 99."""
    me = obj.data
    mw = obj.matrix_world
    if roof_pred is None:
        def roof_pred(p, n):
            return n.z > 0.15 and p.material_index != 2
    m3 = mw.to_3x3()
    roofs = [p for p in me.polygons if roof_pred(p, (m3 @ p.normal).normalized())]
    uvl = me.uv_layers.get("RoofUV") or me.uv_layers.new(name="RoofUV")
    if "roof_ridge_dist" not in me.attributes:
        me.attributes.new("roof_ridge_dist", "FLOAT", "CORNER")
    rd = me.attributes["roof_ridge_dist"].data
    planes = []
    for p in roofs:
        n = (m3 @ p.normal).normalized()
        off = (mw @ p.center).dot(n)
        for pl in planes:
            if pl["n"].dot(n) > math.cos(math.radians(tol_deg)) and abs(pl["off"] - off) < 0.15:
                pl["faces"].append(p); break
        else:
            planes.append({"n": n, "off": off, "faces": [p]})
    Z = Vector((0, 0, 1))
    for pl in planes:
        n = pl["n"]
        flat = n.z > math.cos(math.radians(3))
        if flat:
            e, s = Vector((1, 0, 0)), Vector((0, 1, 0))
        else:
            s = (Z - n * Z.dot(n)).normalized()                 # up-slope
            e = s.cross(n).normalized()                         # along the eave; (e, s, n) right-handed
        pts = [mw @ me.vertices[vi].co for p in pl["faces"] for vi in p.vertices]
        vs = [q.dot(s) for q in pts]
        vmin, vmax = min(vs), max(vs)
        for p in pl["faces"]:
            for li in p.loop_indices:
                q = mw @ me.vertices[me.loops[li].vertex_index].co
                v = q.dot(s)
                uvl.data[li].uv = (q.dot(e), v - vmin if not flat else v)
                rd[li].value = (vmax - v) if not flat else 99.0
    return planes


# ----------------------------------------------------------------------------- module choice from attributes
STRUCT = {"601": "wood", "602": "src", "603": "rc", "604": "steel", "605": "light_steel", "606": "masonry",
          "610": "non_wood", "611": "unknown"}          # PLATEAU BuildingDetailAttribute_buildingStructureType
COMMERCIAL = {"402", "403", "404", "413", "414"}         # Building_usage codes with shops / lodging
TEMPLE_WORDS = ("寺", "院", "堂", "神社", "宮", "庵")


def load_streets(path=None):
    """OSM street centrelines (local metres) from data/processed/streets.json, as list of Nx2 arrays + names."""
    path = path or os.path.join(ROOT, "data", "processed", "streets.json")
    S = json.load(open(path))
    out = []
    for s in S["streets"]:
        if s.get("highway") in ("footway", "path", "steps", "pedestrian", "residential", "living_street", "service",
                                "unclassified", "tertiary", "secondary"):
            out.append({"xy": np.array(s["coords"], float), "name": s.get("name") or "", "osm_id": s["osm_id"],
                        "highway": s["highway"]})
    return out


def _dist_to_streets(p, streets):
    best = (1e9, None)
    for s in streets:
        a, b = s["xy"][:-1], s["xy"][1:]
        ab = b - a
        t = np.clip(((p - a) * ab).sum(1) / np.maximum((ab * ab).sum(1), 1e-9), 0, 1)
        d = np.linalg.norm(a + ab * t[:, None] - p, axis=1)
        i = int(np.argmin(d))
        if d[i] < best[0]:
            best = (float(d[i]), s, a[i] + ab[i] * t[i])
    return best


def _h(*a):
    return zlib.crc32(("|".join(map(str, a))).encode()) / 0xFFFFFFFF


def classify(attrs):
    st = str(attrs.get("structure_code") or attrs.get("structure") or "")
    code = next((k for k in STRUCT if k in st), None)
    if code is None and "wood" in st.lower() or "木造" in st:
        code = "601"
    if code is None and ("steel" in st.lower() or "RC" in st or "鉄" in st):
        code = "603"
    name = str(attrs.get("name") or "")
    storeys = int(attrs.get("storeys") or 0)
    year = int(str(attrs.get("year") or "0")[:4] or 0) if str(attrs.get("year") or "0")[:4].isdigit() else 0
    if any(w in name for w in TEMPLE_WORDS):
        return "temple"
    if code in ("602", "603", "604", "605", "606", "610"):
        return "modern"
    if code == "601":
        return "traditional"
    if storeys >= 4 or (storeys >= 3 and year >= 1970):
        return "modern"
    return "traditional"


def facade_plan(attrs, street_facing, wall_len, eave_h, rng_key):
    """Deterministic module choice for one wall plane of a building."""
    kind = classify(attrs)
    storeys = max(1, int(attrs.get("storeys") or (2 if eave_h > 4.5 else 1)))
    usage = str(attrs.get("usage") or "")
    commercial = usage in COMMERCIAL or usage == "461"     # 461 = unknown; most street fronts here are shops
    r = [_h(rng_key, i) for i in range(6)]
    gf_h = min(3.0, max(2.4, eave_h if storeys == 1 else 3.0))
    n_up = max(0, storeys - 1)
    uf_h = 2.4 if n_up == 0 else float(np.clip((eave_h - gf_h) / n_up, 1.9, 3.4))
    if kind == "temple":
        wall = "white_plaster_vermilion" if "庚申" in str(attrs.get("name") or "") else "white_plaster_timber"
        return dict(gf=wall, uf=wall, top=wall, gf_h=gf_h, uf_h=max(uf_h, 2.4), n_upper=n_up, p_gf_alt=0, p_uf_alt=0,
                    seed=int(r[0] * 90), kind=kind)
    if kind == "modern":
        gf = "modern_gf_shopfront" if (street_facing and commercial) else "modern_uf_window"
        return dict(gf=gf, uf="modern_uf_window", top="modern_uf_window", gf_h=3.0, uf_h=float(np.clip(uf_h, 2.8, 3.4)),
                    n_upper=n_up, p_gf_alt=0.0, p_uf_alt=0.0, seed=int(r[0] * 90), kind=kind)
    if not street_facing:
        gf = "machiya_gf_itabari" if r[1] < 0.5 else "machiya_gf_plaster_base"
        return dict(gf=gf, gf_half=gf + "_half", uf="machiya_uf_plaster", uf_half="machiya_uf_plaster_half",
                    top="machiya_uf_plaster", gf_h=gf_h, uf_h=uf_h, n_upper=n_up, p_gf_alt=0, p_uf_alt=0,
                    seed=int(r[0] * 90), kind=kind)
    gfs = (["machiya_gf_shop_open", "machiya_gf_noren_entrance", "machiya_gf_senkoshi", "machiya_gf_senkoshi_dark",
            "machiya_gf_itabari"] if commercial else
           ["machiya_gf_senkoshi", "machiya_gf_senkoshi_dark", "machiya_gf_plaster_base", "machiya_gf_noren_entrance",
            "machiya_gf_itabari"])
    wts = np.array([0.34, 0.26, 0.18, 0.12, 0.10])
    i = int(np.searchsorted(np.cumsum(wts), r[1] * wts.sum()))
    gf = gfs[min(i, 4)]
    alt = gfs[(min(i, 4) + 1 + int(r[2] * 3)) % 5]
    low_uf = uf_h < 2.5            # tsushi-nikai (low second floor) -> mushiko-mado plausible
    ufs = (["machiya_uf_window_lattice", "machiya_uf_glazed_railing", "machiya_uf_mushikomado", "machiya_uf_plaster"]
           if low_uf else ["machiya_uf_glazed_railing", "machiya_uf_window_lattice", "machiya_uf_plaster",
                           "machiya_uf_mushikomado"])
    uw = np.array([0.4, 0.3, 0.18, 0.12])
    j = int(np.searchsorted(np.cumsum(uw), r[3] * uw.sum()))
    uf = ufs[min(j, 3)]
    return dict(gf=gf, gf_alt=alt, gf_half="machiya_gf_senkoshi_half", uf=uf, uf_alt="machiya_uf_plaster",
                uf_half="machiya_uf_window_lattice_half", top="machiya_uf_plaster", gf_h=gf_h, uf_h=uf_h,
                n_upper=n_up, p_gf_alt=0.3 if wall_len > 4 else 0.0, p_uf_alt=0.25, seed=int(r[0] * 90), kind=kind)


def building_eave_height(obj, base_z):
    me = obj.data; mw = obj.matrix_world; m3 = mw.to_3x3()
    zs = [(mw @ me.vertices[v].co).z for p in me.polygons if (m3 @ p.normal).normalized().z > 0.15
          and p.material_index != 2 for v in p.vertices]
    return (min(zs) - base_z) if zs else 6.0


def assign_facades(obj, building_attrs=None, streets=None, street_dist=8.0, evidence=None):
    """Choose facade modules per wall plane from building attributes and write FacadeUV + attributes.

    building_attrs: dict with storeys, usage, structure (PLATEAU code '601'.. or text), year, name, base_z,
                    plateau_id (defaults to the object's custom properties).
    streets: list from load_streets(); a wall plane is street-facing when its centre is within street_dist m of a
             centreline and its outward normal points towards it.
    evidence: optional dict plateau_buildingID-like key -> record (building_evidence.json) used to fill structure.
    """
    a = {k: obj.get(k) for k in ("storeys", "usage", "structure", "year", "name", "base_z", "plateau_id", "top_z")}
    if building_attrs:
        a.update({k: v for k, v in building_attrs.items() if v is not None})
    base_z = float(a.get("base_z") or min((obj.matrix_world @ v.co).z for v in obj.data.vertices))
    eave_h = building_eave_height(obj, base_z)
    streets = streets if streets is not None else load_streets()
    key = a.get("plateau_id") or obj.name

    def plan(info):
        c = np.array([info["center"].x, info["center"].y])
        d, s, foot = _dist_to_streets(c, streets)
        facing = False
        if d < street_dist:
            to = foot - c
            nrm = np.array([info["normal"].x, info["normal"].y])
            facing = float(np.dot(to, nrm)) > 0.2 * max(np.linalg.norm(to), 1e-6) or d < 2.0
        p = facade_plan(a, facing and info["length"] > 1.0, info["length"], eave_h - 0.0, (key, info["index"] // 1))
        p["street_facing"] = facing
        return p
    return apply_wall_facade_uvs(obj, plan, base_z=base_z)


def ensure_slots(obj, wall_mat, roof_mat, plinth_mat=None):
    """Replace the blockout BO_Roof / BO_Wall / BO_Plinth slots with textured materials."""
    me = obj.data
    while len(me.materials) < 3:
        me.materials.append(None)
    me.materials[0] = roof_mat
    me.materials[1] = wall_mat
    if plinth_mat is not None:
        me.materials[2] = plinth_mat


def make_foliage_material(name="TX_Foliage_Cards", translucency=0.35):
    """Alpha leaf-card material on the foliage atlas (mesh UVs = atlas UVs, see foliage_atlas.json card rects)."""
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    T = _NT(mat)
    uv = T.n("ShaderNodeUVMap", uv_map="UVMap")
    alb = T.tex(uv.outputs[0], "foliage_atlas_albedo.png")
    nrm = T.tex(uv.outputs[0], "foliage_atlas_normal.jpg", True)
    orm = T.tex(uv.outputs[0], "foliage_atlas_orm.jpg", True)
    bsdf = _surface(T, mat, alb.outputs[0], nrm.outputs[0], orm.outputs[0], uv_map="UVMap", alpha=alb.outputs["Alpha"])
    out = [n for n in mat.node_tree.nodes if n.type == "OUTPUT_MATERIAL"][0]
    tr = T.n("ShaderNodeBsdfTranslucent"); T.l(alb.outputs[0], tr.inputs[0])
    mx = T.n("ShaderNodeMixShader"); mx.inputs[0].default_value = translucency
    T.l(bsdf.outputs[0], mx.inputs[1]); T.l(tr.outputs[0], mx.inputs[2])
    tp = T.n("ShaderNodeBsdfTransparent")
    mx2 = T.n("ShaderNodeMixShader"); T.l(alb.outputs["Alpha"], mx2.inputs[0])
    T.l(tp.outputs[0], mx2.inputs[1]); T.l(mx.outputs[0], mx2.inputs[2])
    T.l(mx2.outputs[0], out.inputs[0])
    try:
        mat.surface_render_method = "DITHERED"
    except Exception:
        pass
    return mat


def foliage_cards(name, center, radii, cards, n=250, seed=0, card_scale=1.0, coll=None):
    """Fill an ellipsoidal crown with randomly oriented alpha cards. cards: list of (card_name, weight)."""
    F = json.load(open(os.path.join(TEX, "foliage_atlas.json")))["cards"]
    rng = np.random.default_rng(seed)
    names = [c for c, _ in cards]; w = np.array([x for _, x in cards], float); w /= w.sum()
    verts, faces, uvs = [], [], []
    for k in range(n):
        while True:
            p = rng.uniform(-1, 1, 3)
            if (p * p).sum() < 1:
                break
        p = p * (0.55 + 0.45 * np.sqrt((p * p).sum()))     # bias outwards
        c = np.array(center) + p * np.array(radii)
        cn = names[rng.choice(len(names), p=w)]
        r = F[cn]["uv_rect"]; s = F[cn]["size_m"][0] * card_scale * rng.uniform(0.8, 1.3)
        a, b_ = rng.uniform(0, 2 * np.pi), rng.uniform(-0.6, 0.9)
        out = np.array([math.cos(a), math.sin(a), 0.0])
        up = np.array([0, 0, 1.0]) * math.cos(b_) + out * math.sin(b_)
        side = np.cross(up, out); side /= np.linalg.norm(side)
        up = np.cross(out, side)
        base = c - up * s * 0.5
        q = [base - side * s / 2, base + side * s / 2, base + side * s / 2 + up * s, base - side * s / 2 + up * s]
        i0 = len(verts); verts += [tuple(v) for v in q]; faces.append((i0, i0 + 1, i0 + 2, i0 + 3))
        uvs += [(r[0], r[1]), (r[2], r[1]), (r[2], r[3]), (r[0], r[3])]
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    uvl = me.uv_layers.new(name="UVMap")
    for i, uv in enumerate(uvs):
        uvl.data[i].uv = uv
    me.materials.append(make_foliage_material())
    ob = bpy.data.objects.new(name, me)
    (coll or bpy.context.scene.collection).objects.link(ob)
    return ob
