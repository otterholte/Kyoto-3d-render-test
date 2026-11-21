"""Trees, hedges and shrubs.

No lidar point cloud could be obtained (see docs/sources.md), so individual trees in the core were
DIGITISED BY EYE from the Whatcom County 2024 ortho (Pictometry, 7.5 cm, leaf-off spring) with a 5 m
local grid (positions +-1 m, crown radius +-0.5 m), cross-checked on the City 2022 ortho (spring,
cherry blossom visible). Leaf-off timing makes the evergreen / deciduous split direct: evergreen crowns
are green, deciduous crowns are bare grey branch-work with long shadows.

Heights: Meta/WRI 1 m global canopy-height model (imagery-derived, source imagery ~2016) max within the
crown when >= 3 m ('modelled'); otherwise a type-specific allometric estimate ('inferred').
Outside the core, tall-canopy peaks of the Meta CHM (>= 6 m, 6 m spacing) are added as 'context'
trees (type from 2024 leaf-off greenness), so the backdrop has believable massing.

Output data/processed/trees.json and hedges in the same file.
"""
import json
import numpy as np
import rasterio
from scipy import ndimage as ndi
from shapely.geometry import shape, Point, LineString
from shapely.ops import unary_union

from common import RAW, PROC, ORIGIN_E, ORIGIN_N, to_local, dump

# (x, y, crown_radius_m, type, species_guess, note)   local metres, observed on 2024 ortho
# type: conifer | deciduous | broadleaf_evergreen | ornamental (small deciduous ornamental)
OBS = [
    # --- north of 3811/3813 (rear yards, Viewmont side boundary strip)
    (-25.0, 17.0, 3.5, "conifer", "Douglas-fir", "large conifer, 3813 rear yard"),
    (-37.0, 19.0, 4.0, "deciduous", "bigleaf maple / large deciduous", "spreading bare crown, 3811/3813 rear"),
    (-46.0, 24.0, 3.0, "deciduous", "deciduous", "rear boundary strip"),
    (-49.2, 27.9, 3.0, "conifer", "Douglas-fir / western redcedar", "rear boundary strip"),
    (-60.7, 22.2, 3.0, "conifer", "conifer", "3807/3811 rear boundary"),
    (-68.0, 23.8, 2.5, "conifer", "conifer", "3807 rear"),
    (-55.8, 35.3, 3.5, "conifer", "Douglas-fir", "Viewmont Ct side"),
    (-28.3, 25.5, 2.5, "deciduous", "deciduous", "3813 rear boundary"),
    (-19.7, 21.4, 2.0, "deciduous", "shrubby deciduous", "3813/3905 rear boundary"),
    (-14.0, 30.0, 2.5, "deciduous", "deciduous", "north of 3905 lawn"),
    # --- 3813 / 3811 front beds
    (-18.9, -0.8, 1.2, "ornamental", "Japanese maple / ornamental", "3813 east bed"),
    (-16.4, -5.7, 1.2, "ornamental", "ornamental shrub-tree", "3813 east bed"),
    (-14.4, -9.8, 1.5, "ornamental", "ornamental shrub-tree", "3813/3905 frontage"),
    (-12.8, -12.2, 1.2, "ornamental", "ornamental shrub-tree", "3813/3905 frontage"),
    (-40.2, -4.0, 1.0, "conifer", "columnar conifer (arborvitae/juniper)", "3811 east side"),
    (-39.8, -7.3, 1.0, "conifer", "columnar conifer (arborvitae/juniper)", "3811 east side"),
    (-37.8, -9.8, 1.2, "ornamental", "shrub", "3811/3813 frontage"),
    # --- 3905 front
    (1.2, -12.2, 1.5, "ornamental", "red-leaf Japanese maple (2022: flowering cherry pink nearby)", "3905 south bed"),
    (5.7, -11.4, 1.2, "ornamental", "ornamental shrub", "3905 south bed"),
    (-10.5, -16.5, 2.5, "ornamental", "flowering cherry (pink blossom on City 2022 ortho)", "3905 SW corner by street"),
    (-19.0, -34.8, 2.5, "deciduous", "deciduous street-side tree", "between bulb and 3900 drive"),
    # --- 3909 front bed
    (-7.4, -33.0, 1.5, "ornamental", "deciduous shrub", "3909 front bed (boulders, mulch)"),
    (-5.0, -34.7, 1.5, "conifer", "rounded dwarf conifer", "3909 front bed"),
    # --- 3803 surroundings
    (-105.6, 37.0, 4.0, "conifer", "Douglas-fir", "3803 rear (north)"),
    (-111.0, 35.3, 3.0, "conifer", "conifer", "3803 rear (north-west)"),
    (-100.7, 32.9, 2.5, "conifer", "conifer", "3803 rear"),
    (-95.8, 33.7, 2.0, "conifer", "blue spruce (blue-grey crown)", "3803 rear NE"),
    (-93.3, 31.2, 2.5, "deciduous", "deciduous", "3803 rear NE"),
    (-108.9, 4.2, 1.5, "ornamental", "small deciduous", "3803 front lawn"),
    (-93.3, 3.3, 2.0, "deciduous", "small deciduous", "3803/3807 frontage"),
    # --- 3807 front
    (-81.9, -2.8, 1.5, "conifer", "clipped globe conifer / shrub", "3807 front lawn"),
    (-81.0, -6.5, 2.0, "deciduous", "small deciduous", "3807 front lawn near street"),
    # --- 3802 surroundings (38th St embankment etc.)
    (-110.5, -18.0, 4.0, "conifer", "Douglas-fir / cedar clump", "3802 NW corner at Canby/38th"),
    (-113.8, -29.8, 3.0, "conifer", "conifer", "3802 west embankment"),
    (-116.3, -40.5, 3.0, "conifer", "conifer", "3802 west embankment"),
    (-112.0, -47.0, 2.5, "deciduous", "deciduous", "3802 SW embankment"),
    (-81.0, -32.3, 4.0, "deciduous", "large deciduous (bare)", "3802 east / 3806 west"),
    (-76.0, -46.0, 3.0, "deciduous", "deciduous", "3802/3806 boundary"),
    # --- 3806 / 3900
    (-70.5, -39.7, 4.0, "conifer", "Douglas-fir", "3806 west boundary"),
    (-68.9, -56.9, 3.0, "conifer", "conifer", "3806 west boundary"),
    (-35.3, -48.7, 2.5, "conifer", "conifer", "3806/3900 boundary"),
    (-35.3, -52.8, 2.0, "conifer", "conifer", "3806/3900 boundary"),
    (-41.9, -81.5, 3.5, "conifer", "conifer", "south of 3806/3900"),
    (12.2, -62.6, 2.0, "deciduous", "small deciduous", "3904 east"),
    # --- 3905 / 3909 east side
    (19.8, 26.5, 3.0, "deciduous", "deciduous", "east of 3905 shed"),
    (11.5, 8.5, 1.5, "conifer", "small conifer", "3905 NE corner"),
    (19.8, -12.5, 3.5, "deciduous", "deciduous (bare)", "east of 3909 / 3905 drive"),
    # --- wooded greenbelt south of 3900/3904 (conifer-dominated with bare deciduous)
    (-27.0, -90.5, 4.0, "conifer", "Douglas-fir", "greenbelt"),
    (-34.5, -95.4, 4.0, "conifer", "Douglas-fir", "greenbelt"),
    (-13.2, -87.2, 3.5, "conifer", "Douglas-fir / western redcedar", "greenbelt"),
    (-7.4, -84.0, 3.0, "conifer", "western redcedar", "greenbelt"),
    (-1.7, -91.3, 4.0, "conifer", "Douglas-fir", "greenbelt"),
    (9.0, -82.3, 4.0, "conifer", "Douglas-fir", "greenbelt"),
    (13.0, -77.4, 3.0, "conifer", "conifer", "greenbelt edge"),
    (3.2, -98.7, 4.0, "deciduous", "bigleaf maple / red alder", "greenbelt"),
    (13.0, -98.8, 5.0, "deciduous", "bigleaf maple", "greenbelt"),
    (19.8, -106.0, 4.0, "deciduous", "bigleaf maple / alder", "greenbelt"),
    (-15.6, -97.9, 4.0, "conifer", "Douglas-fir", "greenbelt"),
    (-22.0, -106.0, 4.0, "conifer", "Douglas-fir", "greenbelt"),
    (-38.6, -102.0, 3.5, "conifer", "conifer", "greenbelt"),
    (-9.0, -106.0, 4.0, "conifer", "Douglas-fir", "greenbelt"),
    (1.8, -98.8, 3.5, "conifer", "conifer", "greenbelt"),
    (7.8, -87.5, 4.0, "conifer", "conifer", "greenbelt"),
    # --- east side (40th St backyards)
    (29.0, -43.0, 3.0, "deciduous", "deciduous", "east context"),
    (34.0, -50.0, 3.0, "deciduous", "deciduous", "east context"),
    (47.5, -51.5, 3.0, "conifer", "conifer", "east context"),
    (53.5, -52.3, 3.5, "deciduous", "deciduous", "east context"),
    (-112.0, -97.0, 3.5, "conifer", "conifer", "south-west context"),
    (-118.7, -102.8, 3.0, "deciduous", "deciduous", "south-west context"),
]

# hedges / shrub rows: polyline (local), width, height estimate, type
HEDGES = [
    {"id": "H1", "points": [[-8.2, 11.5], [-3.7, 19.7]], "width_m": 1.2, "height_m_est": 4.5, "kind": "columnar arborvitae row (~9 plants)", "where": "3905 west lawn, diagonal"},
    {"id": "H2", "points": [[-12.0, -8.0], [-15.0, -2.0], [-15.0, 6.0], [-11.0, 10.0]], "width_m": 0.8, "height_m_est": 1.0, "kind": "low clipped hedge / shrub border", "where": "3905 curved west lawn edge"},
    {"id": "H3", "points": [[22.0, 64.0], [22.0, 32.0]], "width_m": 1.5, "height_m_est": 5.0, "kind": "tall arborvitae screen", "where": "east boundary north of 3905 (40th St lots)"},
    {"id": "H4", "points": [[26.5, 7.0], [30.0, 10.5], [35.5, 12.5]], "width_m": 1.2, "height_m_est": 4.0, "kind": "columnar conifer row", "where": "north of sport court, east of 3905"},
    {"id": "H5", "points": [[27.0, 2.0], [27.5, -26.0]], "width_m": 1.2, "height_m_est": 4.0, "kind": "columnar conifer row", "where": "west side of sport court (east of 3905/3909)"},
    {"id": "H6", "points": [[21.5, -20.0], [22.5, -39.0]], "width_m": 1.2, "height_m_est": 4.0, "kind": "columnar conifer row", "where": "3909 east boundary"},
    {"id": "H7", "points": [[-121.0, 36.0], [-121.0, 5.0], [-118.0, 0.0], [-112.0, -2.0]], "width_m": 2.5, "height_m_est": 2.5, "kind": "dense clipped hedge (laurel/privet type)", "where": "3803 along 38th St and Canby corner"},
    {"id": "H8", "points": [[-91.0, 64.0], [-91.0, 25.0]], "width_m": 1.5, "height_m_est": 4.5, "kind": "tall arborvitae screen", "where": "3803/3807 boundary north"},
    {"id": "H9", "points": [[-62.0, 57.0], [-62.0, 38.0]], "width_m": 2.0, "height_m_est": 2.5, "kind": "row of rounded shrubs", "where": "Viewmont Ct lot west of 3811 rear"},
    {"id": "H10", "points": [[-38.0, 61.0], [-38.0, 33.0]], "width_m": 2.0, "height_m_est": 4.0, "kind": "tall hedge / tree row", "where": "rear boundary north of 3811/3813"},
    {"id": "H11", "points": [[-73.0, -78.6], [-50.0, -78.6]], "width_m": 1.2, "height_m_est": 3.5, "kind": "columnar conifer row", "where": "3806 south boundary"},
    {"id": "H12", "points": [[-39.4, -47.0], [-39.4, -77.0]], "width_m": 1.5, "height_m_est": 2.5, "kind": "mixed shrub row", "where": "3806/3900 boundary"},
]

ALLO = {"conifer": lambda r: min(6.0 * r, 35.0), "deciduous": lambda r: min(3.5 * r + 2.0, 25.0),
        "ornamental": lambda r: 2.0 * r + 1.5, "broadleaf_evergreen": lambda r: 2.5 * r + 1.0}


def main():
    chm_ds = rasterio.open(RAW / "rasters" / "chm_meta.tif")
    chm = chm_ds.read(1)
    ct = chm_ds.transform
    ort = rasterio.open(RAW / "rasters" / "ortho_wc2024.tif")
    o = ort.read().astype(np.float32)
    ot = ort.transform
    exg = 2 * o[1] - o[0] - o[2]

    def chm_max(x, y, r):
        e, n = x + ORIGIN_E, y + ORIGIN_N
        c0 = int((e - r - ct.c) / ct.a); c1 = int((e + r - ct.c) / ct.a) + 1
        r0 = int((ct.f - (n + r)) / -ct.e); r1 = int((ct.f - (n - r)) / -ct.e) + 1
        w = chm[max(r0, 0):r1, max(c0, 0):c1]
        return float(w.max()) if w.size else 0.0

    def green_frac(x, y, r):
        e, n = x + ORIGIN_E, y + ORIGIN_N
        c0 = int((e - r - ot.c) / ot.a); c1 = int((e + r - ot.c) / ot.a)
        r0 = int((ot.f - (n + r)) / -ot.e); r1 = int((ot.f - (n - r)) / -ot.e)
        w = exg[r0:r1, c0:c1]
        return float((w > 20).mean()) if w.size else 0.0

    core = shape(json.load(open(PROC / "boundary.json"))["core"]["local"])
    trees = []
    for i, (x, y, r, typ, sp, note) in enumerate(OBS):
        hc = chm_max(x, y, max(r, 1.5))
        if hc >= 3.0 and r >= 2.0 and typ in ("conifer", "deciduous"):
            h, hsrc = round(hc, 1), "modelled (Meta CHM max in crown)"
        else:
            h, hsrc = round(ALLO[typ](r), 1), "inferred (allometry from crown radius)"
        trees.append({"id": f"T{i + 1:03d}", "x": x, "y": y, "crown_radius_m": r, "height_m": h, "height_source": hsrc,
                      "chm_max_m": round(hc, 1), "type": typ, "evergreen": typ in ("conifer", "broadleaf_evergreen"),
                      "species_guess": sp, "note": note, "leafoff_green_fraction_2024": round(green_frac(x, y, r * 0.7), 2),
                      "position_source": "observed (digitised on Whatcom 2024 ortho, +-1 m)", "in_core": core.contains(Point(x, y))})

    # context trees from CHM peaks outside the core
    sm = ndi.gaussian_filter(chm, 1.0)
    mx = ndi.maximum_filter(sm, size=7)
    pk = np.argwhere((sm == mx) & (sm >= 6.0))
    obs_pts = unary_union([Point(t["x"], t["y"]).buffer(max(t["crown_radius_m"], 3)) for t in trees])
    n = 0
    for r_, c_ in pk:
        e = ct.c + (c_ + 0.5) * ct.a; nn = ct.f + (r_ + 0.5) * ct.e
        x, y = e - ORIGIN_E, nn - ORIGIN_N
        if core.contains(Point(x, y)) or obs_pts.contains(Point(x, y)):
            continue
        h = float(chm[r_, c_])
        rad = round(float(np.clip(h * 0.18, 1.5, 5.0)), 1)
        gf = green_frac(x, y, rad * 0.7)
        typ = "conifer" if gf > 0.35 else "deciduous"
        n += 1
        trees.append({"id": f"C{n:03d}", "x": round(x, 1), "y": round(y, 1), "crown_radius_m": rad, "height_m": round(h, 1),
                      "height_source": "modelled (Meta CHM peak)", "chm_max_m": round(h, 1), "type": typ,
                      "evergreen": typ == "conifer", "species_guess": "Douglas-fir/redcedar" if typ == "conifer" else "bigleaf maple/alder/birch",
                      "note": "context tree (outside core) from CHM peak; type from 2024 leaf-off greenness",
                      "leafoff_green_fraction_2024": round(gf, 2), "position_source": "modelled (CHM peak, +-2 m)", "in_core": False})

    # sanity: observed type vs leaf-off greenness
    mism = [t["id"] for t in trees if t["id"].startswith("T") and t["type"] == "deciduous" and t["leafoff_green_fraction_2024"] > 0.6]
    out = {"crs": "local metres (see boundary.json)", "z": "tree base = DTM at (x,y)",
           "count": {"total": len(trees), "observed_core_and_near": len(OBS), "context_chm": n,
                     "conifer": sum(t["type"] == "conifer" for t in trees),
                     "deciduous": sum(t["type"] == "deciduous" for t in trees),
                     "ornamental": sum(t["type"] == "ornamental" for t in trees)},
           "method": __doc__.strip(), "warnings": {"deciduous_but_green_in_leafoff": mism},
           "trees": trees, "hedges": HEDGES}
    dump(PROC / "trees.json", out)
    print(out["count"], "mismatch", mism)
    hs = [t["height_m"] for t in trees if t["id"].startswith("T")]
    print("obs heights", np.percentile(hs, [10, 50, 90]))


if __name__ == "__main__":
    main()
