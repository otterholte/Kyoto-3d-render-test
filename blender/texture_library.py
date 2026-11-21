"""Realistic texture & facade library for the Higashiyama reconstruction - build entry point.

    /home/user/venv/bin/python blender/texture_library.py                 # everything
    /home/user/venv/bin/python blender/texture_library.py --only surfaces,roof,facade,foliage,web
    env: TEXLIB_SCRATCH (intermediate passes, default /tmp/texlib_scratch), TEXLIB_SPP (bake samples, default 48),
         TEXLIB_THREADS (Cycles threads, default 3)

Outputs
  blender/textures/<set>_{albedo,normal,orm[,emit]}.jpg   2048² sets (facade atlas 4096², foliage atlas 2048x1024 PNG)
  blender/textures/library.json, facade_atlas.json, foliage_atlas.json
  web/assets/tex/...   same names, web resolutions (see web_pack), total <= 8 MB
Pieces
  texlib_common.py    numpy noise / height->normal / AO / writer
  texlib_surfaces.py  ground, timber, plaster, stone, bamboo, bark, copper/metal/slate roofs (real-scale height fields)
  texlib_facade.py    facade modules: Blender geometry at real scale -> Cycles orthographic data passes -> atlas
  texlib_roof.py      kawara (sangawara / hongawara) tile geometry -> passes, + eave and ridge strips
  texlib_foliage.py   alpha leaf cards atlas
  materials_textured.py  Blender material builders + UV helpers (facade / roof assignment)
  texlib_demo.py      street-level check render (renders/texlib_demo_ninenzaka.png)
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

WEB_BUDGET = 8 * 1024 * 1024
# web priority: higher = keep resolution longer
PRIORITY = {"ground": 3, "roof": 3, "misc": 2, "foliage": 3}
KEY_SETS = {"ishidatami_granite", "roof_kawara_sangawara", "roof_kawara_eave", "plaster_ochre", "timber_planks_weathered",
            "setts_granite", "asphalt_worn", "stone_steps_trim"}


def web_pack(budget=WEB_BUDGET, verbose=True):
    """Re-encode the web copies of tileable sets from the Blender masters so the web folder fits the budget.
    Facade and foliage atlases keep their resolution; tileables step down (normal/ORM first, low-priority first)."""
    import numpy as np
    from PIL import Image
    from texlib_common import TEX_BL, TEX_WEB, LIB_JSON_WEB, load_img, resize, renorm, save_img
    lib = json.load(open(LIB_JSON_WEB))
    sets = {k: v for k, v in lib["sets"].items() if v.get("kind") in ("tileable", "strip", "trim")}
    # resolution plan per set: dict map -> scale divisor relative to the Blender master (2 = half)
    plan = {k: {"albedo": 2, "normal": 2, "orm": 4} for k in sets}
    steps = []
    for k, v in sets.items():
        pr = PRIORITY.get(v.get("category"), 2) + (2 if k in KEY_SETS else 0)
        steps.append((pr, k, "normal")); steps.append((pr + 0.5, k, "albedo"))
    steps.sort()

    def encode(k, m, div, q=80):
        v = sets[k]
        fn = v["files"][m]
        src = load_img(os.path.join(TEX_BL, fn))
        h, w = src.shape[:2]
        dst = resize(src, (max(64, w // div), max(64, h // div)))
        if m == "normal":
            dst = renorm(dst * 2 - 1) * 0.5 + 0.5
        return save_img(os.path.join(TEX_WEB, fn), dst, q), (dst.shape[1], dst.shape[0])

    def total():
        return sum(os.path.getsize(os.path.join(TEX_WEB, f)) for f in os.listdir(TEX_WEB)
                   if f.endswith((".jpg", ".png")) and not f.startswith("_"))
    res = {}
    for k in sets:
        for m in ("albedo", "normal", "orm"):
            _, res[(k, m)] = encode(k, m, plan[k][m])
    i = 0
    while total() > budget and i < len(steps):
        _, k, m = steps[i]
        plan[k][m] *= 2
        _, res[(k, m)] = encode(k, m, plan[k][m])
        i += 1
    for k in sets:
        lib["sets"][k]["resolution"] = {m: list(res[(k, m)]) for m in ("albedo", "normal", "orm")}
    json.dump(lib, open(LIB_JSON_WEB, "w"), indent=1, ensure_ascii=False)
    if verbose:
        print("web total %.2f MB (budget %.1f MB)" % (total() / 1048576, budget / 1048576))
    return total()


def main(argv):
    only = (argv[argv.index("--only") + 1].split(",") if "--only" in argv else
            ["surfaces", "facade", "roof", "foliage", "web"])
    if "surfaces" in only:
        import texlib_surfaces
        texlib_surfaces.build_all()
    if "foliage" in only:
        import texlib_foliage
        texlib_foliage.build_all()
    if "facade" in only:
        import texlib_facade
        texlib_facade.build_all()
    if "roof" in only:
        import texlib_roof
        texlib_roof.build_all()
    if "web" in only:
        web_pack()


if __name__ == "__main__":
    main(sys.argv[1:])
