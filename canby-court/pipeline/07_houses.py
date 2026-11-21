"""Per-house evidence JSON for the 10 Canby Ct houses (+ massing of context buildings).

Confidence classes used throughout:
  measured   - computed from survey/GIS geometry or rasters (footprint, area, ground z, roof colour pixels)
  documented - stated in a public record (City assessor-derived building layer, listing data)
  observed   - seen by a human on the 2022/2024 orthophotos (roof form, ridge direction, decks, garage side)
  inferred   - estimated from rules of thumb (wall/eave/ridge heights, pitch)
No lidar DSM was obtainable, so roof heights/pitches are INFERRED, not measured.
Privacy: only addresses are stored; no owner / person names.
"""
import json
import math

import numpy as np
import rasterio
from rasterio.features import geometry_mask
from shapely.geometry import shape, mapping, Polygon
from shapely.affinity import translate
from shapely.ops import transform as stransform

from common import RAW, PROC, ORIGIN_E, ORIGIN_N, to_local, dump, CANBY_ADDRS

LISTINGS = {
    "3802": {"sources": [
        {"url": "https://www.windermere.com/listing/WA/Bellingham/3802-Canby-Court-98229/171849369", "status": "page blocked from this environment; facts below from web-search result snippets of this and a mirrored agent-site copy of the same listing"}],
        "facts": {"sale": "sold 2023-08-24, $1,020,000, 46 days on market", "type": "rambler (one storey)", "beds_baths": "4 bd / 3 ba",
                  "size_sqft": 2304, "roof": "composition", "exterior": "wood", "garage": "attached garage",
                  "view": "partial view of the bay (Bellingham Bay)", "setting": "south-side, quiet neighbourhood"}},
    "3813": {"sources": [
        {"url": "https://www.windermere.com/listing/WA/Bellingham/3813-Canby-Court-98229/178146638", "status": "blocked; facts from search snippets"},
        {"url": "https://www.windermere.com/listing/WA/Bellingham/3813-Canby-Ct-98229/32794538", "status": "blocked; earlier (2016) listing, search snippets"},
        {"url": "https://orchard.com/homes/details/3813-canby-ct-bellingham-wa-98229", "status": "blocked; search snippets"},
        {"url": "https://www.wicklundre.com/listing/1504244/3813-Canby-Ct-Bellingham-WA-98229", "status": "not fetched; search snippets"}],
        "facts": {"sale": "sold 2023-09-06, $1,200,000 (earlier 2016 new-build sale $650,525)", "style": "Craftsman",
                  "beds_baths": "4 bd / 4 ba", "size_sqft": 3380, "roof": "composition",
                  "exterior": "cement planked (fibre-cement lap) siding + wood (records differ: 'Cement Planked' vs 'Cement/Concrete, Wood')",
                  "features": "deck, skylights; cul-de-sac lot, curbs, sidewalks", "lot_acres": 0.27,
                  "builder": "local custom builder (named in project brief; not re-verified here)", "garage": "attached garage (2016 record)"}},
    "3909": {"sources": [
        {"url": "https://www.estately.com/listings/info/3909-canby-court", "status": "blocked; facts from search snippets"}],
        "facts": {"structure": "house", "exterior": "cement planked + wood", "roof": "composition",
                  "directions": "I-5 Samish Way exit ... left onto Canby Ct", "sale": "date/price not shown in snippet"}},
}
NO_LISTING = {"sources": [], "facts": {}, "note": "web search (2026-11) found no listing/sale page for this address; only street-index pages"}

# observed on Whatcom 2024 (7.5 cm) + City 2022 (5 cm) orthos.  azimuths = compass bearing of the ridge line.
OBS = {
    "3802": {"roof_form": "hip roof, two hipped wings in a stepped L (main wing + garage wing)", "ridge_azimuth_deg": 120,
             "features": ["skylight", "deck/porch at NW corner (light wood)"], "garage": "attached, NE wing, faces NE onto Canby Ct (concrete drive, 2 cars)",
             "notes": "one-storey rambler on a steep lot falling west to 38th St (embankment with conifers)"},
    "3803": {"roof_form": "side-gable, ridge E-W; three small gable dormers/vents on the street (south) plane; rear low-slope ribbed addition (sunroom/patio cover) and white pergola",
             "ridge_azimuth_deg": 90, "features": ["octagonal gazebo with brown roof in rear yard", "curved concrete path on west side", "tall clipped hedge along 38th St"],
             "garage": "east end, drive from Canby Ct on the east side", "notes": "corner lot Canby Ct / 38th St"},
    "3806": {"roof_form": "complex hip roof (main hip + hipped wings)", "ridge_azimuth_deg": 90,
             "features": ["skylight", "rear deck with raised planter boxes", "trampoline in rear lawn", "white garden arbor"],
             "garage": "north side, long concrete drive from Canby Ct along the west", "notes": "split-level per City STYLE"},
    "3807": {"roof_form": "hip roof, brown shingles, rectangular plan", "ridge_azimuth_deg": 90,
             "features": ["chimney", "skylights", "rear deck with white railing (north)"], "garage": "east side, concrete drive to Canby Ct",
             "notes": "split-level per City STYLE"},
    "3811": {"roof_form": "side-gable (ridge E-W) with a street-facing cross gable at the west half", "ridge_azimuth_deg": 90,
             "features": ["chimney at west gable end", "rear patio with chairs and fire pit"], "garage": "east side, concrete drive to Canby Ct",
             "notes": ""},
    "3813": {"roof_form": "compact hip/gable mix, grey (2016 Craftsman)", "ridge_azimuth_deg": 0,
             "features": ["skylights / roof vents", "landscaped front beds with boulders", "stone/retaining wall on east side"],
             "garage": "south-west, drive to the bulb", "notes": "built 2015/16 on a lot that was vacant in the 2006 DTM"},
    "3900": {"roof_form": "1.5-storey cross-gable with three gable dormers on the north (street) face", "ridge_azimuth_deg": 110,
             "features": ["large rooftop solar PV array (~24 panels) on the south plane", "pergola/arbor on west", "detached flat-roofed outbuilding to SW", "boat under blue cover beside drive"],
             "garage": "east side, drive from the bulb", "notes": "City STYLE '1&H F' (one-and-a-half with finished basement)"},
    "3904": {"roof_form": "large hip roof, light grey, plan rotated ~45 deg", "ridge_azimuth_deg": 135,
             "features": ["skylights", "rear deck SE"], "garage": "north-west, drive from the bulb", "notes": "one storey"},
    "3905": {"roof_form": "complex: main hip roof with long ridge NNW-SSE, a lower roof strip along the SW face, hipped bay on the north, light low-slope section in the NE re-entrant corner, and a hip/gable garage wing to the east with ridge E-W",
             "ridge_azimuth_deg": 155,
             "features": ["light-grey composition shingles (both orthos)", "chimney on NW part of main roof", "row of roof vents", "garage doors face south onto concrete drive from the bulb (2 cars parked)",
                          "walkway from SW front to the bulb sidewalk", "large rear lawn N and W with play structure (red roof) and swing set at about (-12,20)",
                          "diagonal row of ~9 columnar arborvitae across the west lawn (hedge H1)", "low clipped hedge along the curved west lawn edge (H2)",
                          "paved path NE to a garden shed (~5x4 m, grey roof) at about (14,25)", "raised vegetable beds north at about (5..12,28..32)",
                          "patio/terrace with furniture in the NE corner between wings"],
             "garage": "attached east wing, doors face south", "notes": "no facade evidence in nadir imagery"},
    "3909": {"roof_form": "long side-gable, ridge N-S, light grey", "ridge_azimuth_deg": 0,
             "features": ["trampoline in east yard", "trailer/RV or shed (white) north of house at about (14,-12)"],
             "garage": "south-west end, drive from the bulb", "notes": "City: 2 storeys + basement"},
}


def obb(poly):
    r = poly.minimum_rotated_rectangle
    c = list(r.exterior.coords)[:4]
    e = [(math.dist(c[i], c[i + 1]), c[i], c[i + 1]) for i in range(3)]
    L = max(e[0][0], e[1][0]); Wd = min(e[0][0], e[1][0])
    a, p0, p1 = max(e[:2], key=lambda t: t[0])
    az = (math.degrees(math.atan2(p1[0] - p0[0], p1[1] - p0[1]))) % 180
    return round(L, 2), round(Wd, 2), round(az, 1)


def hexc(rgb):
    return "#%02x%02x%02x" % tuple(int(v) for v in rgb)


def main():
    terrain = json.load(open(PROC / "terrain.json"))
    parcels = {f["properties"]["Site_Address"]: f["properties"] for f in
               json.load(open(RAW / "city" / "parcels.geojson"))["features"] if f["properties"].get("Site_Address")}
    rasters = {k: rasterio.open(RAW / "rasters" / f"{k}.tif") for k in ("ortho_wc2024_core", "ortho_cob2022_core", "naip")}
    houses, context = [], []
    for f in json.load(open(RAW / "city" / "buildings_agol.geojson"))["features"]:
        p = f["properties"]
        g = stransform(lambda x, y, z=None: to_local(x, y), shape(f["geometry"])).buffer(0)
        ad = str(p.get("MAIN_ADDRE") or "")
        if not ad.endswith("CANBY CT"):
            L, Wd, az = obb(g)
            context.append({"address": ad, "footprint_local": [[round(x, 2), round(y, 2)] for x, y in g.exterior.coords],
                            "floors": p.get("NUM_FLOORS"), "year_built": p.get("YRBUILT"), "style": p.get("STYLE"),
                            "bldg_type": p.get("BLDGTYPE"), "area_m2": round(g.area, 1), "obb_long_axis_deg": az})
            continue
        num = ad.split()[0]
        L, Wd, az = obb(g)
        # roof colour stats (inset 0.6 m to avoid edges/lean)
        cols = {}
        for k, ds in rasters.items():
            gi = translate(g.buffer(-0.6), ORIGIN_E, ORIGIN_N)
            win = ds.window(*gi.bounds).round_offsets().round_lengths()
            a = ds.read(window=win).astype(np.float32)
            m = geometry_mask([mapping(gi)], out_shape=a.shape[1:], transform=ds.window_transform(win), invert=True)
            px = a[:3, m].T
            lum = px.mean(1)
            q75 = px[lum >= np.percentile(lum, 60)]
            q25 = px[lum <= np.percentile(lum, 40)]
            cols[k] = {"median_rgb": [int(v) for v in np.median(px, 0)], "median_hex": hexc(np.median(px, 0)),
                       "sunlit_planes_hex": hexc(np.median(q75, 0)), "shaded_planes_hex": hexc(np.median(q25, 0)),
                       "n_pixels": int(m.sum())}
        par = parcels.get(ad, {})
        floors = p.get("NUM_FLOORS") or 1
        # ---- inferred heights ----
        storey = 2.75
        plate = {1: 2.75, 1.5: 4.0, 2: 5.6}.get(floors, 2.75 * floors) + 0.45  # top plate above grade incl. ~0.45 m crawlspace/stem wall
        pitch = 8 / 12 if num == "3813" else 6 / 12
        rise = min(Wd / 2, 7.0) * pitch  # wings of complex plans are rarely deeper than ~14 m
        tb = terrain["house_ground"][num]
        o = OBS[num]
        lst = LISTINGS.get(num, NO_LISTING)
        houses.append({
            "address": f"{num} Canby Ct, Bellingham, WA 98229",
            "number": int(num),
            "parcel_code": p.get("PARCEL_COD"),
            "footprint_local": {"value": [[round(x, 2), round(y, 2)] for x, y in g.exterior.coords], "class": "measured",
                                "source": "City of Bellingham 'Bellingham_Buildings_With_Addresses' (footprint YEAR 2019 edit)"},
            "footprint_area_m2": {"value": round(g.area, 1), "class": "measured"},
            "obb": {"length_m": L, "width_m": Wd, "long_axis_bearing_deg": az, "class": "measured"},
            "centroid_local": [round(g.centroid.x, 2), round(g.centroid.y, 2)],
            "assessor": {"class": "documented", "source": "City building layer (assessor-derived)",
                         "floors": p.get("NUM_FLOORS"), "year_built": p.get("YRBUILT"), "style": p.get("STYLE"),
                         "sf_1st": round(p.get("SF_1ST") or 0), "sf_2nd": round(p.get("SF_2ND") or 0), "sf_3rd": round(p.get("SF_3RD") or 0),
                         "sf_basement": round(p.get("SF_BASEMEN") or 0), "sf_attic": round(p.get("SF_ATTIC") or 0), "total_sf": round(p.get("TOTAL_SF") or 0),
                         "bldg_type": p.get("BLDGTYPE"),
                         "parcel_land_use": par.get("Land_Use_Description"), "parcel_acres": par.get("Legal_Acreage"),
                         "parcel_area_sqft": par.get("FeatureAreaFeet")},
            "ground": {"class": "measured", "source": "3DEP 2006 bare-earth DTM, 1.5 m ring around footprint", **tb},
            "roof": {
                "form": {"value": o["roof_form"], "class": "observed"},
                "ridge_bearing_deg": {"value": o["ridge_azimuth_deg"], "class": "observed", "note": "main ridge, +-10 deg"},
                "material": {"value": "asphalt/composition shingle", "class": "documented" if num in LISTINGS else "observed",
                             "note": "listing says 'composition'" if num in LISTINGS else "shingle texture on 5-7.5 cm ortho"},
                "colour": {"class": "measured", "note": "pixel medians inside footprint (inset 0.6 m); illumination-dependent - use sunlit_planes_hex as albedo-ish base colour, 2024 = Pictometry spring, 2022 = EagleView spring, NAIP = 2017-09 1 m",
                           **cols},
                "pitch": {"value_rise_per_12": round(pitch * 12), "deg": round(math.degrees(math.atan(pitch)), 1), "class": "inferred",
                          "note": "typical for 1984-88 PNW tract homes (6:12); 8:12 for the 2016 Craftsman"},
                "eave_height_above_grade_m": {"value": round(plate + 0.15, 2), "class": "inferred", "note": f"{floors} storey(s) x ~{storey} m + 0.45 m stem wall"},
                "ridge_height_above_grade_m": {"value": round(plate + 0.15 + rise, 2), "class": "inferred", "note": "eave + min(OBB width/2, 7 m) x pitch; complex roofs have lower secondary ridges"},
                "eave_z_navd88_m": {"value": round(tb["z_ring_median"] + plate + 0.15, 2), "class": "inferred"},
                "ridge_z_navd88_m": {"value": round(tb["z_ring_median"] + plate + 0.15 + rise, 2), "class": "inferred"},
            },
            "garage": {"value": o["garage"], "class": "observed"},
            "observed_features": {"value": o["features"], "class": "observed"},
            "notes": o["notes"],
            "listing": {"class": "documented (listing data, human-read via search snippets)", **lst},
            "facade": {"colour": None, "class": "gap",
                       "note": "nadir orthophotos show roofs only; no facade colour evidence" + ("" if num not in LISTINGS else "; siding material documented in listing")},
        })
    houses.sort(key=lambda h: h["number"])
    assert [h["number"] for h in houses] == CANBY_ADDRS
    dump(PROC / "houses.json", {"crs": "local metres (boundary.json)", "confidence_classes": __doc__.strip(), "houses": houses})
    dump(PROC / "context_buildings.json", {"crs": "local metres", "note": "City footprints for non-Canby buildings in the fetch box; floors/year from City layer (documented); no roof evidence",
                                           "buildings": context})
    for h in houses:
        print(h["number"], h["assessor"]["floors"], h["assessor"]["style"], h["obb"], h["roof"]["colour"]["ortho_wc2024_core"]["sunlit_planes_hex"],
              h["roof"]["colour"]["ortho_cob2022_core"]["sunlit_planes_hex"], h["roof"]["ridge_height_above_grade_m"]["value"])
    print("context buildings", len(context))


if __name__ == "__main__":
    main()
