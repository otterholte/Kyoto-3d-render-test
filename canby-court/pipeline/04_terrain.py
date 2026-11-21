"""Terrain: bare-earth DTM at 0.5 m, slope analysis, validation, sledding-run search.

Input  data/raw/rasters/dem_3dep.tif  (USGS 3DEP dynamic service; source at this site = USGS NED 1/9"
       'ned19_n48x75_w122x50_wa_northpugetsound_2006' = North Puget Sound 2006 lidar bare earth)
       data/raw/city/catch_basins.geojson  (GPS-surveyed rim elevations, ft)
       data/raw/city/contours_2013_utm.geojson (optional; City 2013 lidar 5-ft contours)
Output data/processed/terrain/dtm_0p5m.tif, slope_deg_0p5m.tif, heightmap_u16.png (+json),
       data/processed/terrain.json, data/processed/sledding.json
"""
import json

import numpy as np
import rasterio
from rasterio.transform import from_origin
from scipy import ndimage
from shapely.geometry import shape, LineString, Point, mapping
from shapely.ops import unary_union, linemerge
from PIL import Image

from common import RAW, PROC, ORIGIN_E, ORIGIN_N, CRS, to_local, dump, CANBY_ADDRS

FT = 0.3048006096  # US survey foot
OUT = PROC / "terrain"
OUT.mkdir(parents=True, exist_ok=True)
B = json.load(open(PROC / "boundary.json"))
RES = 0.5


def load(name):
    return json.load(open(RAW / "city" / f"{name}.geojson"))["features"]


def local_geom(g):
    from shapely.ops import transform
    return transform(lambda x, y, z=None: to_local(x, y), g)


def main():
    src = rasterio.open(RAW / "rasters" / "dem_3dep.tif")
    z1 = src.read(1).astype(np.float64)
    t1 = src.transform
    assert (z1 > 0).all()
    # local coords of 1 m grid cell centres
    x0 = t1.c - ORIGIN_E; y1 = t1.f - ORIGIN_N
    # 0.5 m grid via cubic spline (order 3) on the 1 m grid
    ny, nx = z1.shape
    nY, nX = ny * 2, nx * 2
    rr = (np.arange(nY) + 0.5) * RES - 0.5   # row coordinate in 1 m-pixel-centre units
    cc = (np.arange(nX) + 0.5) * RES - 0.5
    R, C = np.meshgrid(rr, cc, indexing="ij")
    z = ndimage.map_coordinates(z1, [R, C], order=3, mode="nearest").astype(np.float32)
    tr = from_origin(t1.c, t1.f, RES, RES)
    prof = dict(driver="GTiff", width=nX, height=nY, count=1, dtype="float32", crs=CRS, transform=tr,
                compress="deflate", nodata=-9999)
    with rasterio.open(OUT / "dtm_0p5m.tif", "w", **prof) as d:
        d.write(z, 1)

    def sample(xl, yl):
        """bilinear sample of the 0.5 m DTM at local coords"""
        c = (np.asarray(xl) - (x0)) / RES - 0.5
        r = ((y1) - np.asarray(yl)) / RES - 0.5
        return ndimage.map_coordinates(z, [np.atleast_1d(r), np.atleast_1d(c)], order=1, mode="nearest")

    gy, gx = np.gradient(z.astype(np.float64), RES)
    gy = -gy  # rows go south
    slope = np.degrees(np.arctan(np.hypot(gx, gy))).astype(np.float32)
    aspect = (np.degrees(np.arctan2(-gx, -gy)) % 360).astype(np.float32)  # downslope direction, 0=N, 90=E
    with rasterio.open(OUT / "slope_deg_0p5m.tif", "w", **prof) as d:
        d.write(slope, 1)

    # 16-bit heightmap for engines
    zmin, zmax = float(z.min()), float(z.max())
    hm = np.round((z - zmin) / (zmax - zmin) * 65535).astype(np.uint16)
    Image.fromarray(hm).save(OUT / "heightmap_u16.png")

    # ---------------- validation ----------------
    val = []
    for f in load("catch_basins"):
        p = f["properties"]
        if p.get("ELEVATION") in (None, 0):
            continue
        x, y = to_local(*f["geometry"]["coordinates"])
        if not (B["context"]["bounds_local"][0] <= x <= B["context"]["bounds_local"][2] and
                B["context"]["bounds_local"][1] <= y <= B["context"]["bounds_local"][3]):
            continue
        zd = float(sample(x, y)[0])
        val.append({"x": round(x, 2), "y": round(y, 2), "rim_ft": p["ELEVATION"], "rim_m": round(p["ELEVATION"] * FT, 3),
                    "dtm_m": round(zd, 3), "diff_m": round(zd - p["ELEVATION"] * FT, 3), "accuracy": p.get("ACCURACY"),
                    "source": p.get("SOURCE")})
    d_cb = np.array([v["diff_m"] for v in val]) if val else np.array([np.nan])

    contour_val = None
    try:
        cf = json.load(open(RAW / "city" / "contours_2013_utm.geojson"))["features"]
        diffs = []
        for f in cf:
            zc = f["properties"]["Contour"] * FT
            g = shape(f["geometry"])
            lines = getattr(g, "geoms", [g])
            for ln in lines:
                if ln.geom_type != "LineString":
                    continue
                for d_ in np.arange(0, ln.length, 2.0):
                    pt = ln.interpolate(d_)
                    xl, yl = pt.x - ORIGIN_E, pt.y - ORIGIN_N
                    diffs.append(float(sample(xl, yl)[0]) - zc)
        diffs = np.array(diffs)
        contour_val = {"n_samples": int(diffs.size), "mean_m": round(float(diffs.mean()), 3),
                       "median_m": round(float(np.median(diffs)), 3), "rmse_m": round(float(np.sqrt((diffs ** 2).mean())), 3),
                       "p95_abs_m": round(float(np.percentile(np.abs(diffs), 95)), 3)}
    except FileNotFoundError:
        pass

    # ---------------- masks & per-feature slope stats ----------------
    def mask_of(geom):
        from rasterio.features import geometry_mask
        from shapely.affinity import translate
        g = translate(geom, ORIGIN_E, ORIGIN_N)
        return ~geometry_mask([mapping(g)], out_shape=z.shape, transform=tr)

    bld = []
    for f in load("buildings_agol"):
        bld.append(local_geom(shape(f["geometry"])))
    bld_u = unary_union(bld)
    parcels = {int(k): shape(v) for k, v in B["parcels_local"].items()}
    road = shape(B["canby_ct_road_local"])
    stats = {}
    for a, g in parcels.items():
        m = mask_of(g.difference(bld_u.buffer(1.0)))
        s = slope[m]
        zz = z[m]
        stats[str(a)] = {"ground_z_min": round(float(zz.min()), 2), "ground_z_max": round(float(zz.max()), 2),
                         "relief_m": round(float(zz.max() - zz.min()), 2),
                         "slope_deg_mean": round(float(s.mean()), 1), "slope_deg_p90": round(float(np.percentile(s, 90)), 1),
                         "slope_deg_max": round(float(s.max()), 1),
                         "share_over_15deg": round(float((s > 15).mean()), 3)}
    m = mask_of(road)
    stats["canby_ct_road"] = {"ground_z_min": round(float(z[m].min()), 2), "ground_z_max": round(float(z[m].max()), 2),
                              "slope_deg_mean": round(float(slope[m].mean()), 1),
                              "slope_deg_p90": round(float(np.percentile(slope[m], 90)), 1)}

    # house base heights: min/max DTM around footprint (1.5 m ring outside the wall)
    house_base = {}
    for f in load("buildings_agol"):
        ad = str(f["properties"].get("MAIN_ADDRE"))
        if not ad.endswith("CANBY CT"):
            continue
        g = local_geom(shape(f["geometry"]))
        ring = g.buffer(1.5).difference(g)
        mm = mask_of(ring)
        house_base[ad.split()[0]] = {"z_ring_min": round(float(z[mm].min()), 2), "z_ring_max": round(float(z[mm].max()), 2),
                                     "z_ring_median": round(float(np.median(z[mm])), 2),
                                     "grade_drop_across_footprint_m": round(float(z[mm].max() - z[mm].min()), 2)}

    # ---------------- sledding: Canby Ct street profile ----------------
    cl = unary_union([local_geom(shape(f["geometry"])) for f in load("street_centerlines")
                      if f["properties"].get("Name") == "CANBY CT"])
    if cl.geom_type == "MultiLineString":
        cl = linemerge(cl)
    if cl.geom_type != "LineString":
        cl = max(cl.geoms, key=lambda g: g.length)
    # orient high -> low
    za, zb = sample(*cl.coords[0])[0], sample(*cl.coords[-1])[0]
    if za < zb:
        cl = LineString(list(cl.coords)[::-1])
    # extend through the bulb: the city centreline stops at the bulb centre; the run starts at the bulb's
    # far (uphill) curb. Find the bulb from the pavement polygon.
    d = np.arange(0, cl.length + 0.01, 1.0)
    pts = [cl.interpolate(v) for v in d]
    zp = sample([p.x for p in pts], [p.y for p in pts])
    # robust gradient: 5 m window
    w = 5
    gr = np.array([(zp[max(i - w // 2, 0)] - zp[min(i + w // 2, len(zp) - 1)]) /
                   (d[min(i + w // 2, len(zp) - 1)] - d[max(i - w // 2, 0)]) for i in range(len(zp))])
    street = {
        "name": "Canby Ct (street) - bulb to 38th St junction, along the city centreline",
        "centerline_local": [[round(p.x, 2), round(p.y, 2), round(float(zz), 2)] for p, zz in zip(pts, zp)][::2],
        "length_m": round(float(cl.length), 1),
        "z_top": round(float(zp[0]), 2), "z_bottom": round(float(zp[-1]), 2),
        "drop_m": round(float(zp[0] - zp[-1]), 2),
        "avg_gradient_pct": round(float((zp[0] - zp[-1]) / cl.length * 100), 1),
        "max_gradient_pct_5m": round(float(gr.max() * 100), 1),
        "max_gradient_at_m": float(d[int(gr.argmax())]),
        "profile_every_5m": [[float(d[i]), round(float(zp[i]), 2), round(float(gr[i] * 100), 1)] for i in range(0, len(d), 5)],
    }

    # ---------------- generic search: steepest-descent runs in the core (off-building) ----------------
    core = shape(B["core"]["local"])
    obstacles = bld_u.buffer(1.0)
    cand = []
    xs = np.arange(core.bounds[0], core.bounds[2], 4.0)
    ys = np.arange(core.bounds[1], core.bounds[3], 4.0)
    zs = ndimage.gaussian_filter(z.astype(np.float64), 2.0)  # smooth so paths don't zig-zag on 0.5 m noise
    gys, gxs = np.gradient(zs, RES); gys = -gys
    for sx in xs:
        for sy in ys:
            p = Point(sx, sy)
            if not core.contains(p) or obstacles.contains(p):
                continue
            path = [(sx, sy)]
            for _ in range(600):
                cx, cy = path[-1]
                c = (cx - x0) / RES - 0.5; r = (y1 - cy) / RES - 0.5
                gxv = ndimage.map_coordinates(gxs, [[r], [c]], order=1)[0]
                gyv = ndimage.map_coordinates(gys, [[r], [c]], order=1)[0]
                gn = np.hypot(gxv, gyv)
                if gn < 0.03:  # < 3 % : sled stops
                    break
                nxp, nyp = cx - gxv / gn * 0.5, cy - gyv / gn * 0.5
                if obstacles.contains(Point(nxp, nyp)) or not core.contains(Point(nxp, nyp)):
                    break
                path.append((nxp, nyp))
            if len(path) < 30:
                continue
            ln = LineString(path)
            zz = sample(*zip(*path))
            drop = float(zz[0] - zz[-1])
            cand.append((drop, ln, zz))
    cand.sort(key=lambda c: -c[0])
    runs = []
    for drop, ln, zz in cand:
        if any(ln.buffer(3).intersection(r[1]).length > 0.5 * ln.length for r in runs):
            continue
        L = ln.length
        dd = np.linspace(0, L, max(int(L), 2))
        zl = sample(*zip(*[(ln.interpolate(v).x, ln.interpolate(v).y) for v in dd]))
        g5 = [(zl[max(i - 2, 0)] - zl[min(i + 2, len(zl) - 1)]) / (dd[min(i + 2, len(zl) - 1)] - dd[max(i - 2, 0)]) for i in range(len(zl))]
        on_street = ln.intersection(road).length / L
        owner = [str(a) for a, g in parcels.items() if g.intersection(ln).length > 0.3 * L]
        runs.append((drop, ln, {"length_m": round(L, 1), "drop_m": round(drop, 2), "avg_gradient_pct": round(drop / L * 100, 1),
                                "max_gradient_pct_5m": round(float(max(g5)) * 100, 1), "share_on_canby_ct_road": round(on_street, 2),
                                "mostly_on_parcel": owner[0] if owner else None,
                                "start_local": [round(ln.coords[0][0], 1), round(ln.coords[0][1], 1)],
                                "end_local": [round(ln.coords[-1][0], 1), round(ln.coords[-1][1], 1)],
                                "path_local": [[round(x, 1), round(y, 1)] for x, y in ln.simplify(0.3).coords]}))
        if len(runs) >= 6:
            break

    terrain = {
        "dtm": {"file": "data/processed/terrain/dtm_0p5m.tif", "resolution_m": RES, "crs": CRS,
                "vertical": "NAVD88 m", "origin_upper_left_utm": [t1.c, t1.f], "shape_rows_cols": [nY, nX],
                "bounds_local": [round(x0, 2), round(y1 - nY * RES, 2), round(x0 + nX * RES, 2), round(y1, 2)],
                "z_min": round(zmin, 2), "z_max": round(zmax, 2),
                "heightmap_png": {"file": "data/processed/terrain/heightmap_u16.png", "z_min": round(zmin, 3), "z_max": round(zmax, 3),
                                  "decode": "z = z_min + v/65535*(z_max-z_min); row 0 = north edge"},
                "source": "USGS 3DEP dynamic elevation (exportImage 1 m bilinear) -> cubic spline to 0.5 m. Best-available "
                          "source at the site per 3DEP catalogue: USGS NED 1/9 arc-second 'ned19_n48x75_w122x50_wa_northpugetsound_2006' "
                          "(North Puget Sound 2006 lidar, bare earth). Newer lidar (City/DNR 'Bellingham 2013', DNR 'Cascades North "
                          "Wali 2023') exists but could not be downloaded (DNR portal disallows /download in robots.txt and returns 403; "
                          "not in USGS LPC/EPT buckets).",
                "caveats": ["2006 bare earth: predates 3813 (built 2015/16) - its pad/driveway grading is not in the DTM",
                            "under-building ground is interpolated; building pads must be flattened by the scene builder",
                            "curb faces (~15 cm) are not resolved"]},
        "validation": {"catch_basin_rims": {"n": len(val), "mean_diff_m": round(float(np.nanmean(d_cb)), 3),
                                             "rmse_m": round(float(np.sqrt(np.nanmean(d_cb ** 2))), 3), "points": val,
                                             "note": "DTM minus GPS-surveyed catch-basin rim (City storm layer, ft -> m). Rims sit in the "
                                                     "gutter, typically 0.1-0.2 m below the crown; positions are 'High' accuracy."},
                       "contours_2013": contour_val},
        "slope_stats": stats,
        "house_ground": house_base,
        "overall": {"slope_deg_mean_core": round(float(slope[mask_of(core)].mean()), 1),
                    "general_fall": "ground falls from east (~160 m) to west (~120 m) across the context box; Canby Ct "
                                    "climbs east from 38th St to the cul-de-sac bulb"},
    }
    dump(PROC / "terrain.json", terrain)
    best = next((r[2] for r in runs if r[2]["share_on_canby_ct_road"] >= 0.5), None)
    sled = {"recommended_run": dict(best, name="Canby Ct sledding run: from the top of the bulb (SE apron by the 3904/3909 drives) "
                                              "down the street to the 38th St junction (steepest-descent line on the DTM)",
                                    evidence="measured on 3DEP 2006 bare-earth DTM; user reports the sledding hill is Canby Ct itself",
                                    hazards="ends at the 38th St T-junction (through street) - the game should add a run-out / stop "
                                            "zone before 38th St; parked cars, mailboxes and curbs line the street") if best else None,
            "canby_ct_street_run": street,
            "other_candidates_steepest_descent": [r[2] for r in runs],
            "method": "Street: DTM profile along the City street centreline, 1 m steps, gradient over 5 m windows. "
                      "Candidates: steepest-descent paths seeded every 4 m in the core on a 2 m-Gaussian-smoothed DTM, "
                      "stopping where gradient < 3 %, at buildings (+1 m) or the core edge; ranked by drop, de-duplicated."}
    dump(PROC / "sledding.json", sled)
    print(json.dumps({k: v for k, v in street.items() if k not in ("centerline_local", "profile_every_5m")}, indent=1))
    print("profile", street["profile_every_5m"])
    for r in runs:
        print({k: v for k, v in r[2].items() if k != "path_local"})
    print("catch basins", terrain["validation"]["catch_basin_rims"]["n"], terrain["validation"]["catch_basin_rims"]["mean_diff_m"],
          terrain["validation"]["catch_basin_rims"]["rmse_m"], "contours", contour_val)
    for k, v in stats.items():
        print(k, v)
    print(house_base)


if __name__ == "__main__":
    main()
