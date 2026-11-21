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
    MT = None
    if os.path.exists(os.path.join(HERE, "materials_textured.py")):
        try:
            import materials_textured as MT
            tx_fac = MT.make_facade_material()
            try:
                tx_roof = MT.make_roof_material()
            except Exception as ex:
                log("textured kawara not available yet (%s) -> procedural kawara roof" % ex)
                tx_roof = mr
            streets_mt = MT.load_streets()
            log("texture library: materials_textured (facade atlas + kawara)")
        except Exception as ex:
            import traceback
            traceback.print_exc()
            log("materials_textured failed (%s) -> procedural fallback" % ex)
            MT = None
    # structure per building from the evidence file (PLATEAU structure is missing in buildings.json)
    from shapely.geometry import Point as _Pt, Polygon as _Poly
    _evb = [b for v in (kc.evidence().get("buildings_by_street") or {}).values() for b in v]
    _recs = {b["id"]: b for b in kc.data("buildings")["buildings"]}

    def _structure(rec):
        poly = _Poly(rec["footprint"])
        for b in _evb:
            c = b.get("local_centroid_xy")
            if c and poly.distance(_Pt(*c)) < 1.0:
                st = str(b.get("structure") or "")
                return "601" if st.startswith("wooden") else ("603" if st in ("RC", "steel") else None)
        return None
    n_tx = 0
    for ob in bpy.data.objects:
        if ob.type != "MESH" or not (ob.name.startswith("B_") or ob.name.startswith("LM_")) or ob.name.startswith("LM_Yasaka_Pagoda"):
            continue
        me = ob.data
        pr = ob.get("priority", 3)
        mats = [mb, mb, mb] if (pr == 4 and MT is None) else [mr, mf, mp]
        for i in range(min(3, len(me.materials))):
            me.materials[i] = mats[i]
        if MT is not None:
            rec = _recs.get(ob.get("plateau_id"), {})
            attrs = dict(storeys=rec.get("storeys"), usage=rec.get("usage"), year=rec.get("year"), name=rec.get("name"),
                         base_z=rec.get("base_z"), plateau_id=rec.get("id"), structure=_structure(rec) if rec else None)
            try:
                MT.assign_facades(ob, attrs, streets=streets_mt)
                MT.apply_roof_uvs(ob, roof_pred=lambda p, n: n.z > 0.15 and p.material_index == 0)
                MT.ensure_slots(ob, tx_fac, tx_roof, mp)
                ob["facade_textures"] = "materials_textured facade atlas (module choice inferred per wall plane)"
                n_tx += 1
            except Exception as ex:
                log("texture assign failed on", ob.name, ex)
    log("textured buildings", n_tx)
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
    pav_mat = M("paving")
    try:
        import materials_textured as MT2
        pav_mat = MT2.make_material("TX_Ishidatami", "ishidatami_granite", uv_map="UVPave")
        log("paving: textured ishidatami_granite")
    except Exception as ex:
        log("textured paving unavailable:", ex)
    sett_mat = M("paving_sett")
    try:
        sett_mat = MT2.make_material("TX_Setts", "setts_granite", uv_map="UVPave")
    except Exception as ex:
        log("textured setts unavailable:", ex)
    rib = kit_ground.build(cg, pav_mat, sett_mat)
    log("paving ribbons", len(rib))
    kit_ground.carve_terrain_under_steps(log=log)
    kit_ground.utility_poles(kc.get_coll("40_Walls_Barriers"), log=log)
    # real surroundings from the backdrop workstream (PLATEAU neighbours + GSI DEM hills); my DEM10B painted
    # backdrop is only the fallback
    bd = None
    if os.path.exists(os.path.join(HERE, "build_backdrop.py")) and os.path.exists(
            os.path.join(kc.PROC, "backdrop_render.npz")):
        try:
            from build_backdrop import add_backdrop
            bd = add_backdrop(scene, detail="render")
            log("backdrop: build_backdrop.add_backdrop(render)", len(bd.objects))
        except Exception as ex:
            import traceback
            traceback.print_exc()
            log("build_backdrop failed (%s) -> fallback" % ex)
            bd = None
    if bd is None:
        import kit_backdrop
        kit_backdrop.build(log=log)
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
    try:
        import kit_texground
        kit_texground.run(log=log)
    except Exception as ex:
        import traceback
        traceback.print_exc()
        log("textured ground unavailable (%s) -> procedural" % ex)
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
