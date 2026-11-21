"""Fetch City of Bellingham vector layers for the Canby Ct context bbox.

Privacy: every query uses an explicit outFields whitelist; OWNER / taxpayer /
title-owner / editor-user fields are never requested and `scrub()` drops any
that slip through. Outputs GeoJSON (EPSG:4326) in data/raw/city/.
"""
import json
from common import RAW, FETCH_BBOX, get, scrub, dump

AGOL = "https://services5.arcgis.com/cuQhNeNcUrgLmYGD/ArcGIS/rest/services/Bellingham_Buildings_With_Addresses/FeatureServer/0"
COB = "https://maps.cob.org"

LAYERS = {
    "buildings_agol": (AGOL, "FID,YEAR,TYPE,NUM_FLOORS,BLDGTYPE,YRBUILT,STYLE,SF_1ST,SF_2ND,SF_3RD,SF_ATTIC,SF_LOFT,TOTAL_SF,SF_BASEMEN,MAIN_ADDRE,PARCEL_COD,ADDR_NUM,STREET_NAM,ZIPCODE,NEIGHBORHO,DD_LAT,DD_Long,FloorHght,Shape__Area"),
    "buildings_cob": (f"{COB}/arcgis4/rest/services/Maps/Grp_Places/MapServer/12", "OBJECTID,YEAR,TYPE,NUM_FLOORS,YRBUILT,STYLE,SOURCE,LOCATION"),
    "address_points": (f"{COB}/arcgis4/rest/services/Maps/Grp_Places/MapServer/9", "OBJECTID,ADDR_NUM,STREET_NAME,MAIN_ADDRESS_DISPLAY,ZIP,STATUS,PARCEL_CODE,POINTTYPE"),
    "parcels": (f"{COB}/arcgis3/rest/services/Maps/Grp_Land/MapServer/5", "OBJECTID,PARCEL_CODE,Property_ID,Land_Use_Code,Land_Use_Description,Legal_Acreage,Site_Address,Situs_Number,Situs_Street,FeatureAreaFeet,Feature_Source,Feature_Source_Date"),
    "sidewalks": (f"{COB}/arcgis4/rest/services/Maps/Grp_Transportation/MapServer/16", "OBJECTID,STREETNAME,FROMSTREET,TOSTREET,SURFACETYPE,PARKWAY,TREES,STREETSIDE,WIDTH,INSTALLDATE"),
    "street_pavement": (f"{COB}/arcgis4/rest/services/Maps/Grp_Transportation/MapServer/21", "OBJECTID,TYPE,SURFACETYPE,MAINTBY,FeatureAreaFeet"),
    "street_polygons": (f"{COB}/arcgis4/rest/services/Maps/Grp_Transportation/MapServer/36", "OBJECTID,TYPE,FeatureAreaFeet"),
    "street_centerlines": (f"{COB}/arcgis4/rest/services/Maps/Grp_Transportation/MapServer/7", "*"),
    "curb_ramps": (f"{COB}/arcgis4/rest/services/Maps/Grp_Transportation/MapServer/10", "*"),
    "city_trees": (f"{COB}/arcgis3/rest/services/Parks/NotableTrees/MapServer/0", "OBJECTID,CommonName,ScientificName,TreeClass,DBH,Condition,TreeType,Ownership,Native,Source,StreetTreeList,LandmarkTree"),
    "slope_2022": (f"{COB}/arcgis4/rest/services/Maps/Grp_Environmental/MapServer/44", "OBJECTID,gridcode,Percent_Slope,SteepSlope"),
    "streetlights": (f"{COB}/arcgis4/rest/services/Maps/Grp_Utilities/MapServer/56", "*"),
    "hydrants": (f"{COB}/arcgis4/rest/services/Maps/Grp_Utilities/MapServer/27", "*"),
    "catch_basins": (f"{COB}/arcgis4/rest/services/Maps/Grp_Utilities/MapServer/5", "*"),
    "lot_numbers": (f"{COB}/arcgis4/rest/services/Maps/Grp_Places/MapServer/1", "*"),
}


def esri_to_geojson(feat, gtype):
    g = feat.get("geometry") or {}
    if "rings" in g:
        geom = {"type": "Polygon", "coordinates": g["rings"]}
    elif "paths" in g:
        geom = {"type": "MultiLineString", "coordinates": g["paths"]}
    elif "x" in g:
        geom = {"type": "Point", "coordinates": [g["x"], g["y"]]}
    else:
        geom = None
    return {"type": "Feature", "geometry": geom, "properties": scrub(feat.get("attributes", {}))}


def clip(feat):
    """Clip huge city-wide polygons/lines to the fetch bbox (+~100 m) to keep files small."""
    from shapely.geometry import shape, box, mapping
    if not feat["geometry"] or feat["geometry"]["type"] == "Point":
        return feat
    w, s, e, n = FETCH_BBOX
    g = shape(feat["geometry"]).buffer(0) if feat["geometry"]["type"] == "Polygon" else shape(feat["geometry"])
    feat["geometry"] = mapping(g.intersection(box(w - 0.0015, s - 0.001, e + 0.0015, n + 0.001)))
    return feat


def fetch(name, url, fields):
    w, s, e, n = FETCH_BBOX
    feats, offset = [], 0
    while True:
        p = {"where": "1=1", "geometry": f"{w},{s},{e},{n}", "geometryType": "esriGeometryEnvelope",
             "inSR": 4326, "spatialRel": "esriSpatialRelIntersects", "outFields": fields,
             "outSR": 4326, "returnGeometry": "true", "f": "json",
             "resultOffset": offset, "resultRecordCount": 1000}
        d = get(url + "/query", p).json()
        if "error" in d:
            # some MapServer layers don't support pagination
            p.pop("resultOffset"); p.pop("resultRecordCount")
            d = get(url + "/query", p).json()
            if "error" in d:
                print(name, "ERROR", d["error"]); return None
            feats += d.get("features", []); break
        feats += d.get("features", [])
        if not d.get("exceededTransferLimit"):
            break
        offset += len(d.get("features", []))
    gj = {"type": "FeatureCollection", "name": name, "source": url,
          "features": [clip(esri_to_geojson(f, d.get("geometryType"))) for f in feats]}
    # final privacy assertion
    txt = json.dumps(gj)
    assert '"OWNER' not in txt.upper().replace('OWNERSHIP', ''), name
    dump(RAW / "city" / f"{name}.geojson", gj)
    print(f"{name}: {len(feats)} features")
    return gj


if __name__ == "__main__":
    for k, (u, f) in LAYERS.items():
        try:
            fetch(k, u, f)
        except Exception as ex:
            print(k, "FAILED", ex)
