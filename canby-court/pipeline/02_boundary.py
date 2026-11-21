"""Define the project boundary.

core    = union(parcels addressed on Canby Ct) + Canby Ct road (city centerline buffered by
          half street width + sidewalk) buffered 30 m.
context = axis-aligned rectangle (local metres) around core + 45 m, rounded to 10 m,
          which also takes in the Canby Ct / 38th St entrance and the neighbouring houses.
Writes data/processed/boundary.json (+ geojson of core/context).
"""
import json
from shapely.geometry import shape, mapping, box
from shapely.ops import unary_union, transform as stransform
from common import RAW, PROC, CRS, ORIGIN_E, ORIGIN_N, TO_UTM, TO_LL, dump, CANBY_ADDRS


def to_local_geom(g):
    return stransform(lambda x, y, z=None: (TO_UTM.transform(x, y)[0] - ORIGIN_E,
                                            TO_UTM.transform(x, y)[1] - ORIGIN_N), g)


def to_ll_geom(g):
    return stransform(lambda x, y, z=None: TO_LL.transform(x + ORIGIN_E, y + ORIGIN_N), g)


def load(name):
    return json.load(open(RAW / "city" / f"{name}.geojson"))["features"]


def main():
    parcels = {}
    for f in load("parcels"):
        a = str(f["properties"].get("Site_Address") or "")
        if a.endswith("CANBY CT"):
            parcels[int(a.split()[0])] = to_local_geom(shape(f["geometry"])).buffer(0)
    assert sorted(parcels) == CANBY_ADDRS, sorted(parcels)

    cl = [to_local_geom(shape(f["geometry"])) for f in load("street_centerlines")
          if f["properties"].get("Name") == "CANBY CT"]
    canby_cl = unary_union(cl)
    # StreetWidth 26 ft curb-to-curb -> 3.96 m half width; + ~2.5 m planter/sidewalk
    road = canby_cl.buffer(3.96 + 2.5)
    # the cul-de-sac bulb: use the city street pavement polygon clipped near the centerline
    pav = unary_union([to_local_geom(shape(f["geometry"])).buffer(0) for f in load("street_pavement")])
    bulb = pav.intersection(canby_cl.buffer(25))
    road = unary_union([road, bulb])

    lots = unary_union(list(parcels.values()))
    core = unary_union([lots, road]).buffer(30, join_style=2)
    minx, miny, maxx, maxy = core.bounds
    pad = 45
    r10 = lambda v, f: f(v / 10.0) * 10
    import math
    ctx = box(r10(minx - pad, math.floor), r10(miny - pad, math.floor),
              r10(maxx + pad, math.ceil), r10(maxy + pad, math.ceil))

    out = {
        "crs": CRS,
        "crs_name": "NAD83(2011) / UTM zone 10N",
        "vertical_datum": "NAVD88 (metres); geoid GEOID18 where sources specify",
        "origin": {"easting": ORIGIN_E, "northing": ORIGIN_N,
                   "lonlat": list(TO_LL.transform(ORIGIN_E, ORIGIN_N)),
                   "definition": "3905 Canby Ct address point (city DD_LAT/DD_Long 48.72334394,-122.4653697) in EPSG:6339, rounded to 1 m"},
        "local_axes": "x = easting - origin.easting (m, east), y = northing - origin.northing (m, north), z = NAVD88 m",
        "core": {"description": "Canby Ct right-of-way + the 10 Canby Ct parcels, buffered 30 m",
                 "local": mapping(core.simplify(0.5)), "bounds_local": [round(v, 2) for v in core.bounds],
                 "area_m2": round(core.area)},
        "context": {"description": "rectangle = core bounds + 45 m, rounded to 10 m; neighbouring houses and the 38th St entrance",
                    "bounds_local": list(ctx.bounds),
                    "size_m": [ctx.bounds[2] - ctx.bounds[0], ctx.bounds[3] - ctx.bounds[1]],
                    "bounds_lonlat": list(to_ll_geom(ctx).bounds),
                    "bounds_utm": [ctx.bounds[0] + ORIGIN_E, ctx.bounds[1] + ORIGIN_N,
                                   ctx.bounds[2] + ORIGIN_E, ctx.bounds[3] + ORIGIN_N]},
        "parcels_local": {str(k): mapping(v) for k, v in sorted(parcels.items())},
        "canby_ct_centerline_local": mapping(canby_cl),
        "canby_ct_road_local": mapping(road.simplify(0.2)),
    }
    dump(PROC / "boundary.json", out)
    print(json.dumps({k: out[k] for k in ("origin",)}, indent=1))
    print("core bounds", out["core"]["bounds_local"], "area", out["core"]["area_m2"])
    print("context", out["context"]["bounds_local"], out["context"]["size_m"], out["context"]["bounds_lonlat"])


if __name__ == "__main__":
    main()
