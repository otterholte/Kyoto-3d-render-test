"""Master map PNGs: aerial background + parcels, footprints, address labels, street, sidewalks,
curb line, trees, hedges, sledding run, core + context boundaries, local grid.
  docs/master_map.png        background = Whatcom County 2024 ortho (0.15 m, leaf-off spring)
  docs/master_map_naip.png   background = USGS NAIP 2017-09 (1 m, leaf-on) - public domain
  docs/terrain_map.png       hillshade + 1 m contours + slope + sledding run
"""
import json

import numpy as np
import rasterio
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, Polygon as MplPoly
from shapely.geometry import shape

from common import RAW, PROC, DOCS, ORIGIN_E, ORIGIN_N, to_local

B = json.load(open(PROC / "boundary.json"))
H = json.load(open(PROC / "houses.json"))["houses"]
T = json.load(open(PROC / "trees.json"))
S = json.load(open(PROC / "sledding.json"))


def lines_local(name, key=None, val=None):
    out = []
    for f in json.load(open(RAW / "city" / f"{name}.geojson"))["features"]:
        if not f["geometry"] or (key and f["properties"].get(key) != val):
            continue
        g = shape(f["geometry"])
        for ln in getattr(g, "geoms", [g]):
            out.append(np.array([to_local(*c[:2]) for c in ln.coords]))
    return out


def overlay(ax, light=True):
    for a, g in B["parcels_local"].items():
        xy = np.array(shape(g).exterior.coords)
        ax.plot(xy[:, 0], xy[:, 1], color="yellow", lw=1.0, ls="--")
    for f in json.load(open(RAW / "city" / "parcels.geojson"))["features"]:
        g = shape(f["geometry"])
        for p in getattr(g, "geoms", [g]):
            xy = np.array([to_local(*c) for c in p.exterior.coords])
            ax.plot(xy[:, 0], xy[:, 1], color="yellow", lw=0.3, alpha=0.5)
    for f in json.load(open(RAW / "city" / "buildings_agol.geojson"))["features"]:
        g = shape(f["geometry"])
        xy = np.array([to_local(*c) for c in g.exterior.coords])
        canby = str(f["properties"].get("MAIN_ADDRE", "")).endswith("CANBY CT")
        ax.add_patch(MplPoly(xy, closed=True, fill=False, ec="red" if canby else "orange", lw=1.6 if canby else 0.7))
    for h in H:
        x, y = h["centroid_local"]
        ax.text(x, y, str(h["number"]), color="white", fontsize=11, weight="bold", ha="center", va="center",
                bbox=dict(boxstyle="round,pad=0.15", fc="black", alpha=0.6, lw=0))
    for xy in lines_local("sidewalks"):
        ax.plot(xy[:, 0], xy[:, 1], color="white", lw=1.0, alpha=0.8)
    for xy in lines_local("street_centerlines"):
        ax.plot(xy[:, 0], xy[:, 1], color="cyan", lw=0.8, ls=":")
    cl = np.array(B["canby_ct_centerline_local"]["coordinates"]) if B["canby_ct_centerline_local"]["type"] == "LineString" else None
    if cl is not None:
        ax.plot(cl[:, 0], cl[:, 1], color="cyan", lw=1.5)
    colors = {"conifer": "#1b7f2a", "deciduous": "#e08a1e", "ornamental": "#e05fb0", "broadleaf_evergreen": "#3fbf7f"}
    for t in T["trees"]:
        ax.add_patch(Circle((t["x"], t["y"]), t["crown_radius_m"], fill=False, ec=colors[t["type"]],
                            lw=1.3 if t["id"].startswith("T") else 0.7, ls="-" if t["id"].startswith("T") else "--"))
    for hd in T["hedges"]:
        xy = np.array(hd["points"])
        ax.plot(xy[:, 0], xy[:, 1], color="#00e08a", lw=3, alpha=0.8, solid_capstyle="round")
    r = S["recommended_run"]
    if r:
        xy = np.array(r["path_local"])
        ax.plot(xy[:, 0], xy[:, 1], color="#3399ff", lw=3)
        ax.annotate("", xy=xy[-1], xytext=xy[-4], arrowprops=dict(arrowstyle="-|>", color="#3399ff", lw=3))
        ax.text(xy[0][0] + 2, xy[0][1] - 4, f"sled run {r['length_m']:.0f} m, drop {r['drop_m']:.1f} m", color="#3399ff",
                fontsize=9, weight="bold", bbox=dict(fc="white", alpha=0.7, lw=0))
    core = np.array(B["core"]["local"]["coordinates"][0])
    ax.plot(core[:, 0], core[:, 1], color="magenta", lw=1.2)
    ax.plot(0, 0, marker="+", color="magenta", ms=14, mew=2)
    ax.text(1, 1, "origin", color="magenta", fontsize=8)


def frame(ax, title):
    x0, y0, x1, y1 = B["context"]["bounds_local"]
    ax.set_xlim(x0, x1); ax.set_ylim(y0, y1); ax.set_aspect("equal")
    ax.set_xticks(np.arange(x0, x1 + 1, 20)); ax.set_yticks(np.arange(y0, y1 + 1, 20))
    ax.tick_params(labelsize=7); ax.grid(color="white", alpha=0.25, lw=0.5)
    ax.set_title(title, fontsize=10)
    ax.plot([x1 - 60, x1 - 10], [y0 + 8, y0 + 8], color="white", lw=4); ax.text(x1 - 35, y0 + 11, "50 m", color="white", ha="center")
    ax.annotate("N", xy=(x1 - 8, y1 - 5), xytext=(x1 - 8, y1 - 22), color="white", ha="center", fontsize=12, weight="bold",
                arrowprops=dict(arrowstyle="-|>", color="white", lw=2))
    ax.set_xlabel(f"local x (m east of E {ORIGIN_E}, EPSG:6339)", fontsize=8)
    ax.set_ylabel(f"local y (m north of N {ORIGIN_N})", fontsize=8)


def background(ax, name, bands=(1, 2, 3)):
    with rasterio.open(RAW / "rasters" / f"{name}.tif") as s:
        a = s.read(list(bands)).transpose(1, 2, 0)
        t = s.transform
        ext = [t.c - ORIGIN_E, t.c + t.a * s.width - ORIGIN_E, t.f + t.e * s.height - ORIGIN_N, t.f - ORIGIN_N]
    ax.imshow(a, extent=ext, interpolation="bilinear")


def main():
    for name, fn, title in [("ortho_wc2024", "master_map.png", "Canby Court - Whatcom Co. 2024 ortho (leaf-off spring)"),
                            ("naip", "master_map_naip.png", "Canby Court - USGS NAIP 2017-09-02 (leaf-on, 1 m)")]:
        fig, ax = plt.subplots(figsize=(16, 13.5))
        background(ax, name)
        overlay(ax)
        frame(ax, title + " | red = Canby Ct footprints, yellow = parcels, green/orange/pink circles = conifer/deciduous/ornamental, "
                          "mint = hedges, blue = sledding run, magenta = core boundary")
        fig.tight_layout(); fig.savefig(DOCS / fn, dpi=110); plt.close(fig)

    with rasterio.open(PROC / "terrain" / "dtm_0p5m.tif") as s:
        z = s.read(1); t = s.transform
    ext = [t.c - ORIGIN_E, t.c + t.a * z.shape[1] - ORIGIN_E, t.f + t.e * z.shape[0] - ORIGIN_N, t.f - ORIGIN_N]
    gy, gx = np.gradient(z, 0.5)
    az, alt = np.radians(315), np.radians(45)
    sl = np.arctan(np.hypot(gx, gy)); asp = np.arctan2(-gx, gy)
    hs = np.sin(alt) * np.cos(sl) + np.cos(alt) * np.sin(sl) * np.cos(az - asp)
    slope = np.degrees(sl)
    fig, axs = plt.subplots(1, 2, figsize=(22, 9.5))
    axs[0].imshow(hs, extent=ext, cmap="gray")
    axs[0].imshow(z, extent=ext, cmap="terrain", alpha=0.45)
    cs = axs[0].contour(z, levels=np.arange(110, 170, 1), extent=ext, origin="upper", colors="k", linewidths=0.3)
    axs[0].clabel(cs, cs.levels[::5], fontsize=6, fmt="%d")
    im = axs[1].imshow(slope, extent=ext, cmap="magma", vmin=0, vmax=35)
    plt.colorbar(im, ax=axs[1], label="slope (deg)", shrink=0.8)
    for ax, ttl in zip(axs, ["DTM 0.5 m (3DEP 2006 bare earth), 1 m contours NAVD88", "slope (deg)"]):
        for h in H:
            xy = np.array(h["footprint_local"]["value"])
            ax.plot(xy[:, 0], xy[:, 1], color="cyan", lw=1)
            ax.text(*h["centroid_local"], str(h["number"]), color="white", fontsize=8, ha="center")
        r = S["recommended_run"]
        xy = np.array(r["path_local"]); ax.plot(xy[:, 0], xy[:, 1], color="#3399ff", lw=2.5)
        frame(ax, ttl)
    fig.tight_layout(); fig.savefig(DOCS / "terrain_map.png", dpi=90); plt.close(fig)
    print("maps written")


if __name__ == "__main__":
    main()
