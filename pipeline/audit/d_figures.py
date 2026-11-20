"""D: audit figures -> docs/audit/*.png (<= 6 files, each < 1 MB).
Photo panels: Wikimedia Commons thumbnails (licences in captions); render panels: low-res Cycles renders of
blender/higashiyama_blockout.blend from c2_photos.py."""
import json
import os
import pickle
import sys
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
font_manager.fontManager.addfont("/usr/share/fonts/opentype/ipafont-gothic/ipagp.ttf")
plt.rcParams["font.family"] = ["DejaVu Sans", "IPAPGothic"]
from PIL import Image
from acommon import ROOT, OUT

SCR = sys.argv[1]  # scratch dir with refs/ and audit/renders/
DST = os.path.join(ROOT, "docs", "audit")
os.makedirs(DST, exist_ok=True)
P = json.load(open(os.path.join(ROOT, "docs", "references", "commons_geotagged.json")))
C2 = pickle.load(open(os.path.join(OUT, "c2_photos.pkl"), "rb"))


def vis_str(v):
    keys = ["eave3", "eave5", "apex", "tip"]
    return "".join("V" if v[k] == "visible" else "-" for k in keys)


def pair_fig(ids, fname, title, notes):
    fig, axs = plt.subplots(len(ids), 2, figsize=(11, 4.3 * len(ids)))
    for row, i in enumerate(ids):
        p = P[i]; r = C2[i]
        im = Image.open(os.path.join(SCR, "refs", p["scratch_ref_id"])).convert("RGB")
        axs[row, 0].imshow(im); axs[row, 0].axis("off")
        axs[row, 0].set_title("%s\n%s, %s (Wikimedia Commons)" % (p["title"][5:60], p["artist"][:40], p["license_short"]), fontsize=8)
        rd = Image.open(os.path.join(SCR, "audit", "renders", "blk_%03d.png" % i)).convert("RGB")
        axs[row, 1].imshow(rd); axs[row, 1].axis("off")
        c = r["render_cam"]
        axs[row, 1].set_title("blockout render at (%.1f, %.1f) local, yaw %.0f deg, %d mm\n"
                              "geotag snapped %.1f m to OSM way %s. Pagoda eave3/eave5/apex/tip: blockout %s, art %s"
                              % (c["xyz"][0], c["xyz"][1], c["yaw_deg"], c["lens"], r["snap_dist"], r["snap_way"],
                                 vis_str(r["vis"]["blockout_snapped"]), vis_str(r["vis"]["art_snapped"])), fontsize=8)
        if notes.get(i):
            axs[row, 1].text(0.01, 0.02, notes[i], transform=axs[row, 1].transAxes, fontsize=8, color="w",
                             bbox=dict(facecolor="k", alpha=0.6))
    fig.suptitle(title, fontsize=11)
    fig.tight_layout()
    out = os.path.join(DST, fname)
    fig.savefig(out, dpi=72); plt.close(fig)
    shrink(out)


def shrink(path):
    im = Image.open(path).convert("RGB")
    if os.path.getsize(path) > 950_000:
        im.quantize(colors=256, method=Image.Quantize.MEDIANCUT).save(path, optimize=True)


pair_fig([244, 238], "01_sightline_yasaka_dori_lower.png", "Sightline check 1: lower Yasaka-dori looking east (agreement)",
         {244: "photo ~163 m from pagoda: tiers 2-5 + sorin visible; model: same", 238: "geotag 11 m off the street; snapped to way 24516359"})
pair_fig([199, 274], "02_sightline_yasaka_dori_upper.png", "Sightline check 2: upper Yasaka-dori looking west",
         {199: "DISAGREES at geotag/junction: model hides the pagoda\n(visible from x<=135 m, or the south kerb only)", 274: "mid-street: agreement"})
pair_fig([6, 268], "03_sightline_alley_and_elevated.png", "Sightline check 3: alley from Kiyomizu-michi (way 157527424) and elevated NE view",
         {6: "agreement (blockout); art pass: documented trees hide 1-3 tiers along part of the alley",
          268: "render eye +6 m (photo is elevated). Art scene at eye level:\nwhole pagoda hidden by artistic tree TreeArt_666214492_699"})

# ---- 04 footprints / walls / widths
A2 = pickle.load(open(os.path.join(OUT, "a2_rows.pkl"), "rb"))
PB = pickle.load(open(os.path.join(OUT, "plateau_bldg.pkl"), "rb"))
SA = pickle.load(open(os.path.join(OUT, "scene_art.pkl"), "rb"))["buildings"]
SB = pickle.load(open(os.path.join(OUT, "scene_blockout.pkl"), "rb"))["buildings"]
R2 = json.load(open(os.path.join(OUT, "a2_footprints.json")))
X = json.load(open(os.path.join(OUT, "xsections.json")))
fig, axs = plt.subplots(1, 3, figsize=(15, 5))
# (a) wall inset example
for k, col in (("bldg_85c9cc4e-d5e2-4593-bcc1-59a53f019a12", "C0"), ("bldg_65cf46dc-681b-4a9d-8667-72ffadaccca9", "C2")):
    r = PB[k]["roof_edge_ring"]
    axs[0].plot(r[:, 0], r[:, 1], "k-", lw=2)
    for s in SA[k][0]["segs15"]:
        axs[0].plot(s[:, 0], s[:, 1], "-", color="r", lw=1.2)
from acommon import gsi_fgd
for f in gsi_fgd("BldL"):
    xy = f["xy"]
    if xy[:, 0].min() < -5 and xy[:, 0].max() > -50 and xy[:, 1].min() < 100 and xy[:, 1].max() > 80:
        axs[0].plot(xy[:, 0], xy[:, 1], "b--", lw=1)
axs[0].set_xlim(-30, -5); axs[0].set_ylim(80, 100); axs[0].set_aspect("equal")
axs[0].set_title("(a) Yasaka-dori P2 buildings: black = PLATEAU roof edge (= blockout walls)\nred = art-pass walls at +1.5 m, blue dashed = GSI BldL", fontsize=8)
# (b) signed GSI offset histogram
s = R2["gsi_bldl_vs_plateau"]
P2rows = [r for r in A2["wrows"] if r["prio"] == 2 and "area_loss" in r]
axs[1].hist([r["area_loss"] * 100 for r in P2rows], bins=20, color="C3", alpha=0.8)
axs[1].set_xlabel("P2 wall-footprint area removed by the art-pass inset (%)"); axs[1].set_ylabel("buildings")
axs[1].set_title("(b) 123 P2 buildings: median %.0f%% of wall area removed, wall centroid moved median %.2f m (max %.2f m)\n"
                 "GSI BldL vs PLATEAU vertices: %.0f%% inside, %.0f%% outside -> no systematic eave offset"
                 % (100 * R2["art_wall_inset_P2"]["area_loss"]["median"], R2["art_wall_inset_P2"]["centroid_shift"]["median"],
                    R2["art_wall_inset_P2"]["centroid_shift"]["max"], 100 * s["frac_bldl_inside_plateau"], 100 * s["frac_bldl_outside_plateau"]), fontsize=8)
# (c) widths
mk = {"Yasaka-dori": "o", "Ninenzaka": "s", "Sannenzaka": "^", "Higashioji": "D"}
for name, m in mk.items():
    A = [x for x in X if x["street"] == name and x["gsi_width"] and x["gsi_width"] < (25 if name == "Higashioji" else 9)]
    axs[2].scatter([x["gsi_width"] for x in A], [x["scene_width_used"] for x in A], marker=m, s=18, label="%s (n=%d)" % (name, len(A)))
axs[2].plot([2, 18], [2, 18], "k:", lw=1)
axs[2].set_xscale("log"); axs[2].set_yscale("log")
axs[2].set_xlabel("GSI 道路縁 edge-to-edge width (m)"); axs[2].set_ylabel("scene mapped width (m)")
axs[2].legend(fontsize=7); axs[2].set_title("(c) %d cross-sections: scene width vs GSI road edges" % sum(1 for x in X if x["gsi_width"]), fontsize=8)
fig.tight_layout(); fig.savefig(os.path.join(DST, "04_footprints_walls_widths.png"), dpi=80); plt.close(fig)
shrink(os.path.join(DST, "04_footprints_walls_widths.png"))

# ---- 05 terrain
PR = pickle.load(open(os.path.join(OUT, "probe_art.pkl"), "rb"))
t = PR["tin"]; d = t[:, 3] - t[:, 2]
dm = PR["dem5a"]; dd = dm[:, 3] - dm[:, 2]
rows8 = pickle.load(open(os.path.join(OUT, "a8_rows.pkl"), "rb"))
fig, axs = plt.subplots(1, 2, figsize=(13, 5.5))
sc = axs[0].scatter(t[:, 0], t[:, 1], c=d, cmap="RdBu_r", vmin=-3, vmax=3, s=8)
bur = [r for r in rows8 if r["scene_min"] - r["base"] > 1.0]
axs[0].scatter([r["cx"] for r in bur], [r["cy"] for r in bur], facecolors="none", edgecolors="k", s=40, label="building with terrain >1 m above PLATEAU base (n=%d)" % len(bur))
axs[0].plot([-200, 200, 200, -200, -200], [-200, -200, 200, 200, -200], "k-", lw=0.8)
axs[0].set_aspect("equal"); plt.colorbar(sc, ax=axs[0], label="scene terrain - PLATEAU DEM TIN (m)")
axs[0].legend(fontsize=7, loc="lower left"); axs[0].set_title("(a) terrain mesh minus PLATEAU TIN at 2,500 triangle centroids", fontsize=9)
axs[1].hist(d, bins=60, range=(-4, 5), alpha=0.7, label="vs PLATEAU TIN: bias %+.2f, RMSE %.2f m" % (d.mean(), np.sqrt((d ** 2).mean())))
axs[1].hist(dd, bins=60, range=(-4, 5), alpha=0.7, label="vs DEM5A pixels (n=%d): bias %+.3f, RMSE %.3f m" % (len(dd), dd.mean(), np.sqrt((dd ** 2).mean())))
c = PR["contours"]; dc = c[:, 3] - c[:, 2]
axs[1].hist(dc, bins=30, range=(-4, 5), alpha=0.7, label="vs GSI 1:25k contours (n=%d): bias %+.2f, RMSE %.2f m" % (len(dc), dc.mean(), np.sqrt((dc ** 2).mean())))
axs[1].set_yscale("log"); axs[1].legend(fontsize=8); axs[1].set_xlabel("scene - reference (m)")
axs[1].set_title("(b) residual distributions", fontsize=9)
fig.tight_layout(); fig.savefig(os.path.join(DST, "05_terrain_residuals.png"), dpi=80); plt.close(fig)
shrink(os.path.join(DST, "05_terrain_residuals.png"))

# ---- 06 pagoda height
im = Image.open(os.path.join(SCR, "refs", P[244]["scratch_ref_id"])).convert("RGB").crop((400, 380, 700, 900))
fig, axs = plt.subplots(1, 2, figsize=(11, 6.5), gridspec_kw=dict(width_ratios=[1, 1.3]))
axs[0].imshow(im, extent=(400, 700, 900, 380)); axs[0].set_ylim(900, 380)
for y, lab in ((416, "finial tip 416"), (565, "roban top 565"), (577, "top-roof apex 577"), (628, "eave 5"), (684, "eave 4"),
               (746, "eave 3"), (806, "eave 2"), (867, "eave 1 867")):
    axs[0].axhline(y, color="y", lw=0.8); axs[0].text(402, y - 3, lab, color="y", fontsize=7)
axs[0].set_title("Yasaka-Dori - panoramio.jpg (Koichi Shibata, CC BY-SA 3.0)\npixel rows on the 960x1280 thumbnail, camera ~163 m W", fontsize=8)
axs[0].set_xticks([])
apex_e1 = 28.7 - 8.3
lo = 28.7 + (565 - 416) / (867 - 565 + 0) * 0 + (565 - 416) / (867 - 577) * apex_e1 * 0  # placeholder
r1 = (577 - 416) / (867 - 577); r2 = (565 - 416) / (867 - 577)
est = [28.7 + r2 * apex_e1, 28.7 + r1 * apex_e1]
labels = ["PLATEAU\nmeasuredHeight\n(top-roof apex)", "audit photo ratio\n(this report)", "hero model\n(adopted)", "OSM height /\npopular figure"]
vals = [28.7, np.mean(est), 38.8, 46.0]
axs[1].bar(range(4), vals, color=["0.6", "C2", "C0", "C3"])
axs[1].errorbar([1], [np.mean(est)], yerr=[[np.mean(est) - est[0] + 1.0], [est[1] - np.mean(est) + 1.0]], color="k", capsize=6)
for k, v in enumerate(vals):
    axs[1].text(k, v + 0.6, "%.1f m" % v, ha="center", fontsize=9)
axs[1].set_xticks(range(4)); axs[1].set_xticklabels(labels, fontsize=8); axs[1].set_ylabel("height above PLATEAU ground 61.03 m T.P.")
axs[1].set_ylim(0, 50)
axs[1].set_title("sorin/(apex - eave1) = %.2f-%.2f; anchored on PLATEAU eave1 8.3 m / apex 28.7 m\n=> tip %.1f-%.1f m (+-1 m for tilt/edge definition). 46 m needs a ~17 m sorin (~245 px)" % (r2, r1, est[0], est[1]), fontsize=8)
fig.tight_layout(); fig.savefig(os.path.join(DST, "06_pagoda_height.png"), dpi=80); plt.close(fig)
shrink(os.path.join(DST, "06_pagoda_height.png"))
for f in sorted(os.listdir(DST)):
    print(f, os.path.getsize(os.path.join(DST, f)))
print("height estimate", est)
