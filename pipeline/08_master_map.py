"""Phase 1 deliverable: georeferenced master map of the 400 x 400 m boundary.
Background = GSI tiles (pale map / seamless aerial photo) properly resampled from Web Mercator into the
EPSG:6674 local frame (pixel-by-pixel inverse projection, so the grid is true metres)."""
import glob
import json
import math
import os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from PIL import Image
from shapely.geometry import Polygon
from common import RAW, PROC, ROOT, load_boundary, en2ll

for fp in glob.glob("/usr/share/fonts/**/*CJK*", recursive=True) + glob.glob("/usr/share/fonts/**/*Noto*JP*", recursive=True):
    try:
        font_manager.fontManager.addfont(fp)
    except Exception:
        pass
cjk = [f.name for f in font_manager.fontManager.ttflist if "CJK" in f.name or "JP" in f.name]
plt.rcParams["font.family"] = (cjk[:1] or ["DejaVu Sans"]) + ["DejaVu Sans"]

b = load_boundary(); OE, ON = b["origin_e"], b["origin_n"]
S = json.load(open(os.path.join(PROC, "streets.json")))
B = json.load(open(os.path.join(PROC, "buildings.json")))
F = json.load(open(os.path.join(PROC, "features.json")))


def basemap(layer, ext, z=17, res=0.5):
    tiles = {}
    for f in glob.glob(os.path.join(RAW, "gsi", layer, str(z), "*", "*")):
        tx = int(f.split(os.sep)[-2]); ty = int(os.path.basename(f).split(".")[0])
        tiles[(tx, ty)] = np.asarray(Image.open(f).convert("RGB"))
    xs = np.arange(ext[0], ext[1], res); ys = np.arange(ext[3], ext[2], -res)
    GX, GY = np.meshgrid(xs, ys)
    lon, lat = en2ll(GX + OE, GY + ON)
    n = 2 ** z
    px = (np.asarray(lon) + 180) / 360 * n * 256
    lr = np.radians(np.asarray(lat))
    py = (1 - np.log(np.tan(lr) + 1 / np.cos(lr)) / math.pi) / 2 * n * 256
    out = np.full(GX.shape + (3,), 255, np.uint8)
    tx = (px // 256).astype(int); ty = (py // 256).astype(int)
    for (kx, ky), im in tiles.items():
        m = (tx == kx) & (ty == ky)
        out[m] = im[(py[m] % 256).astype(int), (px[m] % 256).astype(int)]
    return out


COL = dict(secondary="#c0392b", tertiary="#d35400", residential="#7f8c8d", unclassified="#7f8c8d", service="#95a5a6",
           pedestrian="#8e44ad", footway="#2980b9", path="#2980b9", steps="#e67e22", living_street="#7f8c8d")


def draw(layer, fname, title):
    ext = (-260, 260, -260, 260)
    img = basemap(layer, ext)
    fig, ax = plt.subplots(figsize=(14, 14), dpi=150)
    ax.imshow(img, extent=ext, alpha=0.85 if layer == "pale" else 0.95)
    for x in B["buildings"]:
        p = np.array(x["footprint"])
        ax.fill(p[:, 0], p[:, 1], fc=("#f5d6a0" if x["in_box"] else "#e0e0e0"), ec="#8a5a2b", lw=0.35, alpha=0.55 if layer == "pale" else 0.35)
    for s in S["streets"]:
        c = np.array(s["coords"])
        lw = 2.6 if s["highway"] in ("pedestrian", "steps", "secondary") else 1.4
        ax.plot(c[:, 0], c[:, 1], color=COL.get(s["highway"], "#34495e"), lw=lw, alpha=0.95, solid_capstyle="round")
        if s["highway"] == "steps":
            ax.plot(c[:, 0], c[:, 1], color="white", lw=0.8, ls=(0, (1, 1.2)))
    labels = {}
    for s in S["streets"]:
        if s["name"] and s["in_box"]:
            c = np.array(s["coords"])
            if s["name"] not in labels or len(c) > labels[s["name"]][1]:
                labels[s["name"]] = (c[len(c) // 2], len(c))
    for nm, (p, _) in labels.items():
        if abs(p[0]) < 200 and abs(p[1]) < 200:
            ax.text(p[0], p[1], nm, fontsize=10, color="#1a1a1a", ha="center", va="center", weight="bold",
                    bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="none", alpha=0.75))
    for t in F["trees"]:
        if t["kind"] == "tree":
            ax.plot(t["x"], t["y"], "o", ms=2.5, color="#27ae60", alpha=0.8)
    pg = b["pagoda"]
    ax.plot(pg["local_x"], pg["local_y"], marker="*", ms=22, color="#c0392b", mec="white", mew=1.5, zorder=10)
    ax.annotate("八坂の塔 Yasaka Pagoda\n%.6f N, %.6f E\nOSM way %d" % (pg["lat"], pg["lon"], pg["osm_way"]),
                (pg["local_x"], pg["local_y"]), xytext=(pg["local_x"] - 150, pg["local_y"] + 60), fontsize=10,
                arrowprops=dict(arrowstyle="->", color="#c0392b"), bbox=dict(fc="white", ec="#c0392b", alpha=0.9))
    ax.add_patch(plt.Rectangle((-200, -200), 400, 400, fill=False, ec="#c0392b", lw=3, ls="--", zorder=9))
    for (cx, cy), (lo, la) in zip([(-200, -200), (200, -200), (200, 200), (-200, 200)], b["corners_lonlat"]):
        ax.text(cx, cy + (-14 if cy < 0 else 6), "%.6f N\n%.6f E" % (la, lo), fontsize=8, ha="center", color="#c0392b",
                bbox=dict(fc="white", ec="none", alpha=0.8))
    ax.plot(0, 0, "+", ms=14, color="#c0392b", mew=2)
    ax.plot([-240, -140], [-245, -245], color="k", lw=4); ax.text(-190, -240, "100 m", ha="center", fontsize=10)
    ax.annotate("", xy=(235, 245), xytext=(235, 205), arrowprops=dict(arrowstyle="-|>", lw=2.5, color="k"))
    ax.text(235, 249, "N (grid)", ha="center", fontsize=10)
    ax.set_xlim(ext[0], ext[1]); ax.set_ylim(ext[2], ext[3]); ax.set_aspect("equal")
    ax.set_xticks(range(-250, 251, 50)); ax.set_yticks(range(-250, 251, 50)); ax.grid(alpha=0.25, color="k")
    ax.set_xlabel("local x (m east of origin)   origin = EPSG:6674 E %.0f / N %.0f" % (OE, ON))
    ax.set_ylabel("local y (m north)")
    ax.set_title(title, fontsize=13)
    fig.text(0.01, 0.005, "Background: 国土地理院 (GSI) %s tiles. Streets/trees: © OpenStreetMap contributors (ODbL). "
             "Buildings: PLATEAU 2025 Kyoto City (MLIT). Box: 400 m × 400 m in JGD2011 / Plane Rect. CS VI (EPSG:6674)." %
             ("淡色地図" if layer == "pale" else "シームレス空中写真"), fontsize=8)
    fig.tight_layout()
    fig.savefig(os.path.join(ROOT, "docs", fname))
    plt.close(fig)


os.makedirs(os.path.join(ROOT, "docs"), exist_ok=True)
draw("pale", "master_map.png", "Higashiyama 400 × 400 m playable boundary — master map (EPSG:6674)")
draw("seamlessphoto", "master_map_aerial.png", "Higashiyama boundary over GSI aerial imagery (alignment check)")
print("ok")
