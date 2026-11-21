"""Render hero shots from blender/canby_court.blend.

  /home/user/venv/bin/python blender/render.py --season summer --shots a,c --res 960 --samples 48 [--out test_]
Final: --res 1920 --samples 256 ; 4K: --res 3840 --samples 160 --time-limit 1200
Outputs renders/<out><season>_<shot>.png
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bpy  # noqa: E402

import cc_common as C  # noqa: E402

A = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]


def arg(k, d=None):
    return A[A.index(k) + 1] if k in A else d


bpy.ops.wm.open_mainfile(filepath=C.BLEND)
import lighting  # noqa: E402
import seasons  # noqa: E402

season = arg("--season", "summer")
seasons.apply(season)
res = int(arg("--res", 960))
lighting.render_settings(int(arg("--samples", 48)), (res, res * 9 // 16), int(arg("--threads", 3)))
if arg("--time-limit"):
    sc = bpy.context.scene
    sc.cycles.time_limit = float(arg("--time-limit"))
if "--no-grass" in A:
    g = bpy.data.objects.get("Grass_Zone")
    if g:
        g.hide_render = True
sc = bpy.context.scene
cams = {o.name.split("_")[1]: o for o in bpy.data.objects if o.type == "CAMERA" and o.name.startswith("Cam_")}
prefix = arg("--out", "test_")
for sh in arg("--shots", "a").split(","):
    cam = cams[sh]
    sc.camera = cam
    out = os.path.join(C.RENDERS, "%s%s_%s.png" % (prefix, season, cam.name[4:]))
    sc.render.filepath = out
    t = time.time()
    bpy.ops.render.render(write_still=True)
    print("RENDERED %s %.1fs" % (out, time.time() - t), flush=True)
