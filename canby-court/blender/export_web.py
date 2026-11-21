"""Export web/assets/world_summer.glb and world_winter.glb from blender/canby_court.blend.

  /home/user/venv/bin/python blender/export_web.py [--season summer|winter|both]

Contract (see docs/scene.md):
* glTF Y-up (Blender exporter): glTF X = local east, glTF Y = NAVD88 height (m), glTF Z = -local north.
* One node per object, extras = {collide, walkable, kind, address?, artistic, season, ...}.
* Geometry only in the GLB; all images are EXTERNAL and shared by both seasons: uri "tex/<file>" relative to
  the GLB (web/assets/tex/, <= 1024 px). Materials are rebuilt here from the texture library:
  baseColorTexture * baseColorFactor (house tints), metallicRoughnessTexture + occlusionTexture (same ORM
  image: R=AO, G=roughness, B=metal), normalTexture, KHR_texture_transform (scale = 1/repeat size in metres,
  offset compensates the glTF V flip).
"""
import json
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bpy  # noqa: E402
import numpy as np  # noqa: E402

import cc_common as C  # noqa: E402

A = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
SEASONS = ["summer", "winter"]
if "--season" in A:
    s = A[A.index("--season") + 1]
    SEASONS = SEASONS if s == "both" else [s]

WEBLIB = json.load(open(os.path.join(C.TEX_WEB, "library.json")))["sets"]


def lin(hexc):
    return [float(v) for v in C.hex2lin(hexc)[:3]]


DEFAULTS = dict(collide=False, walkable=False, kind="misc", artistic=False)


def pick_objects(season):
    S = season == "summer"
    out = []
    for ob in bpy.data.objects:
        if ob.type == "EMPTY" and ob.get("kind") == "marker":
            if ob.get("season") == "winter" and S:
                continue
            out.append(ob)
            continue
        if ob.type not in ("MESH",):
            continue
        cols = {c.name for c in ob.users_collection}
        if "Protos" in cols or "GrassClumps" in cols or ob.get("render_only") or ob.get("web_variant"):
            continue
        if "Web_Only" in cols:
            if ob.name.startswith("House_"):
                out.append(ob)
                continue
            if ob.name.startswith("Snow_Ground"):
                if S:
                    continue
            else:
                if not S:
                    continue          # winter: the snow surface replaces the ground
            out.append(ob)
            continue
        if "Ground" in cols:
            if ob.name.startswith("Street_Details") and S:
                out.append(ob)
            continue                  # render-resolution ground is never exported
        if "Summer_Only" in cols and not S:
            continue
        if "Winter_Only" in cols:
            if S or ob.name.startswith("Snow_Ground"):
                continue
        out.append(ob)
    return out


def prepare(objs, season):
    for ob in objs:
        wk = "proto_%s_web" % season
        if wk in ob.keys():
            me = bpy.data.meshes.get(ob[wk])
            if me is not None:
                ob.data = me
    for ob in objs:
        for k, v in DEFAULTS.items():
            if k not in ob.keys():
                ob[k] = v
        if "season" not in ob.keys():
            ob["season"] = "both"
        ob["season_file"] = season
        for k in ("proto_summer", "proto_winter", "web_materials", "cards", "proto_summer_web", "proto_winter_web"):
            if k in ob.keys():
                del ob[k]
    # web stand-in materials for the splat ground
    for ob in objs:
        if ob.name.startswith("Ground_Soft"):
            names = ["GROUND_lawn", "GROUND_mulch", "GROUND_forest", "GROUND_paved"]
            for i, n in enumerate(names):
                ob.data.materials[i] = bpy.data.materials[n]


def export(season):
    import seasons
    seasons.apply(season)
    objs = pick_objects(season)
    prepare(objs, season)
    sc = bpy.data.scenes.get("Export") or bpy.data.scenes.new("Export")
    for o in list(sc.collection.objects):
        sc.collection.objects.unlink(o)
    for o in objs:
        sc.collection.objects.link(o)
    win = bpy.context.window
    if win is not None:
        win.scene = sc
    with bpy.context.temp_override(scene=sc):
        out = os.path.join(C.WEB_ASSETS, "world_%s.glb" % season)
        bpy.ops.export_scene.gltf(filepath=out, export_format="GLB", use_active_scene=True, export_extras=True,
                                  export_yup=True, export_apply=True, export_image_format="NONE",
                                  export_materials="EXPORT", export_cameras=False, export_lights=False,
                                  export_animations=False, export_attributes=False, export_vertex_color="NONE",
                                  export_tangents=False)
    postprocess(out, season)
    return out, len(objs)


# ============================================================================ GLB post-processing
def read_glb(path):
    d = open(path, "rb").read()
    magic, ver, L = struct.unpack("<III", d[:12])
    off = 12
    js, binc = None, b""
    while off < L:
        cl, ct = struct.unpack("<II", d[off:off + 8])
        chunk = d[off + 8:off + 8 + cl]
        if ct == 0x4E4F534A:
            js = json.loads(chunk.decode())
        else:
            binc = chunk
        off += 8 + cl
    return js, binc


def write_glb(path, js, binc):
    jb = json.dumps(js, separators=(",", ":")).encode()
    jb += b" " * ((4 - len(jb) % 4) % 4)
    binc += b"\0" * ((4 - len(binc) % 4) % 4)
    total = 12 + 8 + len(jb) + (8 + len(binc) if binc else 0)
    with open(path, "wb") as f:
        f.write(struct.pack("<III", 0x46546C67, 2, total))
        f.write(struct.pack("<II", len(jb), 0x4E4F534A))
        f.write(jb)
        if binc:
            f.write(struct.pack("<II", len(binc), 0x004E4942))
            f.write(binc)


def postprocess(path, season):
    js, binc = read_glb(path)
    images, textures = [], []
    img_idx = {}

    def tex(fn, sampler=0):
        if fn not in img_idx:
            img_idx[fn] = len(images)
            images.append({"uri": "tex/" + fn, "name": fn})
            textures.append({"source": img_idx[fn], "sampler": sampler})
        return [t["source"] for t in textures].index(img_idx[fn])

    js["samplers"] = [{"magFilter": 9729, "minFilter": 9987, "wrapS": 10497, "wrapT": 10497}]
    used_ext = set()
    lit_on = season == "winter"
    for m in js.get("materials", []):
        bm = bpy.data.materials.get(m["name"])
        if bm is None:
            continue
        new = {"name": m["name"], "pbrMetallicRoughness": {}}
        pbr = new["pbrMetallicRoughness"]
        ts = bm.get("tex_set")
        tint = bm.get("tint")
        if ts and ts in WEBLIB:
            L = WEBLIB[ts]
            f = L["files"]
            sx, sy = L["size_m"]
            scale = [1.0 / sx, 1.0 / sy]
            if ts in ("foliage_atlas", "window_interior"):
                scale = [1.0, 1.0]
            elif bm.node_tree:
                mp = next((n for n in bm.node_tree.nodes if n.type == "MAPPING"), None)
                if mp is not None:
                    sc_ = mp.inputs["Scale"].default_value
                    scale = [float(sc_[0]), float(sc_[1])]
            tr = {"KHR_texture_transform": {"scale": scale, "offset": [0.0, 1.0 - scale[1]]}}
            used_ext.add("KHR_texture_transform")
            pbr["baseColorTexture"] = {"index": tex(f["albedo"]), "extensions": dict(tr)}
            pbr["metallicRoughnessTexture"] = {"index": tex(f["orm"]), "extensions": dict(tr)}
            new["occlusionTexture"] = {"index": tex(f["orm"]), "strength": 0.8, "extensions": dict(tr)}
            new["normalTexture"] = {"index": tex(f["normal"]), "scale": 1.0, "extensions": dict(tr)}
            pbr["baseColorFactor"] = (lin(tint) if tint else [1.0, 1.0, 1.0]) + [1.0]
            pbr["metallicFactor"] = 1.0
            pbr["roughnessFactor"] = 1.0
            if bm.get("glass"):
                pbr["roughnessFactor"] = 0.15
                pbr["metallicFactor"] = 0.0
                if bm.get("lit") and lit_on:
                    new["emissiveTexture"] = {"index": tex(f["emit"]), "extensions": dict(tr)}
                    new["emissiveFactor"] = [1.0, 0.62, 0.3]
        else:
            bs = next((n for n in bm.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None) if bm.node_tree else None
            col = lin(tint) if tint else [0.5, 0.5, 0.5]
            pbr["baseColorFactor"] = col + [float(bs.inputs["Alpha"].default_value) if bs else 1.0]
            pbr["metallicFactor"] = float(bs.inputs["Metallic"].default_value) if bs else 0.0
            pbr["roughnessFactor"] = float(bs.inputs["Roughness"].default_value) if bs else 0.6
            em = bm.get("emissive")
            if em and lit_on:
                new["emissiveFactor"] = lin(em)
        am = bm.get("alpha_mode")
        if am == "MASK":
            new["alphaMode"] = "MASK"
            new["alphaCutoff"] = 0.45
        elif am == "BLEND":
            new["alphaMode"] = "BLEND"
        if bm.get("double_sided"):
            new["doubleSided"] = True
        new["extras"] = {"tex_set": ts or "", "tint": tint or ""}
        m.clear()
        m.update(new)
    for nd in js.get("nodes", []):
        if nd.get("name", "").endswith("_web"):
            nd["name"] = nd["name"][:-4]
        nd["name"] = nd.get("name", "").replace("_web_", "_")
    for me in js.get("meshes", []):
        me["name"] = me.get("name", "").replace("_web", "")
    js["images"] = images
    js["textures"] = textures
    js.pop("extensionsRequired", None)
    if used_ext:
        js["extensionsUsed"] = sorted(used_ext)
    else:
        js.pop("extensionsUsed", None)
    # drop exporter image bufferViews if any (none with export_image_format=NONE)
    js.setdefault("asset", {})["extras"] = {
        "frame": "local EPSG:6339, origin E 539320 / N 5396840 (3905 Canby Ct address point); glTF +X = east, "
                 "+Y = up (NAVD88 metres, absolute), -Z = north",
        "season": season, "textures": "external, shared: tex/ (relative to this file)",
        "privacy": "addresses only, no owner names"}
    write_glb(path, js, binc)


if __name__ == "__main__":
    bpy.ops.wm.open_mainfile(filepath=C.BLEND)
    for s in SEASONS:
        out, n = export(s)
        print("EXPORTED %s objects=%d size=%.2f MB" % (out, n, os.path.getsize(out) / 1e6), flush=True)
