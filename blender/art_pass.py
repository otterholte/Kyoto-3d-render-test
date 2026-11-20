"""Phases 5/6 art pass: blockout -> painterly, art-directed Higashiyama scene.

Run:  /home/user/venv/bin/python blender/art_pass.py [--stages arch,ground,veg,light,pagoda]
Input:  blender/higashiyama_blockout.blend (build_world.py)  -- surveyed geometry is never moved, except the
        documented wall inset of Priority-2 buildings (see kit_arch.py).
Output: blender/higashiyama_art.blend (checkpoint saved after every stage)

Stages
  arch    priority classes, eave-correct P2 walls, roof slabs/ridges, machiya kit library + placements,
          painterly building materials
  ground  ishidatami ribbons on P2 streets, terrain / steps / wall materials
  veg     documented OSM trees -> painterly species trees; 55_Vegetation_Artistic additions
  light   sky, sun, lanterns, shop glow, fog volume, cameras, compositor grade
  pagoda  hero pagoda from blender/hero_pagoda.py (if available)
Render:  blender/kit_render.py     Web export:  blender/kit_export.py
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bpy  # noqa: E402

ARGS = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
SRC = os.path.join(HERE, "higashiyama_blockout.blend")
OUT = os.path.join(HERE, "higashiyama_art.blend")
STAGES = ["arch", "ground", "veg", "light", "pagoda"]
if "--stages" in ARGS:
    STAGES = ARGS[ARGS.index("--stages") + 1].split(",")
T0 = time.time()


def log(*a):
    print("[art %6.1fs]" % (time.time() - T0), *a, flush=True)


def save():
    bpy.ops.wm.save_as_mainfile(filepath=OUT, compress=True)
    log("checkpoint saved", OUT)


bpy.ops.wm.open_mainfile(filepath=SRC)
scene = bpy.context.scene
scene["art_pass"] = "blender/art_pass.py stages=%s" % ",".join(STAGES)

import kit_common as kc  # noqa: E402
from kit_materials import M  # noqa: E402

# ------------------------------------------------------------------ 1 architecture
if "arch" in STAGES:
    import kit_arch
    import kit_machiya
    facades, stats = kit_arch.run(log=log)
    scene["arch_stats"] = json.dumps(stats)
    mr, mf, mp, mb = M("roof"), M("facade"), M("plinth"), M("backdrop")
    for ob in bpy.data.objects:
        if ob.type != "MESH" or not (ob.name.startswith("B_") or ob.name.startswith("LM_")):
            continue
        me = ob.data
        pr = ob.get("priority", 3)
        mats = [mb, mb, mb] if pr == 4 else [mr, mf, mp]
        for i in range(min(3, len(me.materials))):
            me.materials[i] = mats[i]
    lib = kit_machiya.build_library()
    placed = kit_machiya.place(facades, lib, log=log)
    scene["kit_placements"] = len(placed)
    cls = {}
    for e in placed:
        cls[e["detail_class"]] = cls.get(e["detail_class"], 0) + 1
    scene["kit_detail_classes"] = json.dumps(cls)
    log("kit detail classes", cls)
    save()

# ------------------------------------------------------------------ 2 ground
if "ground" in STAGES:
    import kit_ground
    cg = kc.get_coll("20_Streets_Stairs")
    rib = kit_ground.build(cg, M("paving"))
    log("paving ribbons", len(rib))
    ter = bpy.data.objects.get("Terrain_GSI_DEM5A")
    img = None
    for im in bpy.data.images:
        if "surface_mask" in im.name:
            img = im
    if ter is not None:
        import kit_materials
        ter.data.materials[0] = kit_materials.m_terrain("ART_Terrain", img)
    for ob in bpy.data.objects:
        if ob.type != "MESH":
            continue
        if ob.name.startswith("Steps_osm"):
            ob.data.materials[0] = M("steps")
        elif ob.name.startswith("Barrier_"):
            kind = ob.get("barrier", "")
            ob.data.materials[0] = M("stonewall") if kind in ("wall", "retaining_wall", "city_wall") else M("fence")
    save()

# ------------------------------------------------------------------ 3 vegetation
if "veg" in STAGES:
    import kit_veg
    kit_veg.run(log=log)
    save()

# ------------------------------------------------------------------ 4 lighting + cameras + grade
if "light" in STAGES:
    import kit_light
    kit_light.run(log=log)
    save()

# ------------------------------------------------------------------ 5 hero pagoda
if "pagoda" in STAGES:
    import kit_light
    kit_light.pagoda(log=log)
    save()

log("done")
