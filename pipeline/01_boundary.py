"""Phase 1: define the 400 x 400 m playable boundary in EPSG:6674 and derive everything else from it."""
import json
import math
import os
from common import PROC, ll2en, en2ll
from osm_parse import parse, way_coords
from shapely.geometry import Polygon

os.makedirs(PROC, exist_ok=True)
nodes, ways, _ = parse(os.path.join(os.path.dirname(__file__), "..", "data", "raw", "osm", "osm_wide.osm"))

# Yasaka Pagoda = OSM way 371717416 (building=pagoda, name=八坂の塔, height=46, wikidata via heritage).
pag = Polygon(way_coords(ways[371717416], nodes))
pe, pn = pag.centroid.x, pag.centroid.y
plon, plat = en2ll(pe, pn)

# Box centre: pagoda shifted 10 m W and 84 m S (rounded to whole metres), so the 400 m box
# contains the whole of Ninenzaka (N -111139..-110998), Ichinenzaka, the full Sannenzaka
# incl. its stone stairs (N -111337), and Yasaka-dori to the Higashioji junction (E -20338).
OE, ON = -20160.0, -111160.0
HALF = 200.0
xmin, xmax, ymin, ymax = OE - HALF, OE + HALF, ON - HALF, ON + HALF
corners_en = [(xmin, ymin), (xmax, ymin), (xmax, ymax), (xmin, ymax)]
corners_ll = [en2ll(e, n) for e, n in corners_en]


def mesh3(lat, lon):
    """JIS X 0410 third-order (1 km) standard mesh code."""
    p = int(lat * 1.5); u = int(lon - 100)
    q = int((lat * 1.5 - p) * 8); v = int((lon - 100 - u) * 8)
    r = int(((lat * 1.5 - p) * 8 - q) * 10 + 1e-9); w = int(((lon - 100 - u) * 8 - v) * 10 + 1e-9)
    return f"{p:02d}{u:02d}{q}{v}{r}{w}"


# Sample the box edge densely to find every 3rd-order mesh it touches
meshes = set()
for i in range(41):
    for j in range(41):
        lon, lat = en2ll(xmin + i * 10, ymin + j * 10)
        meshes.add(mesh3(lat, lon))

# Grid convergence at the centre (angle between grid north and true north)
lon0, lat0 = en2ll(OE, ON)
e1, n1 = ll2en(lon0, lat0 + 0.001)
conv = math.degrees(math.atan2(e1 - OE, n1 - ON))

b = dict(
    crs="EPSG:6674 (JGD2011 / Japan Plane Rectangular CS VI)",
    vertical="JGD2011 vertical (T.P. orthometric height, m)",
    origin_e=OE, origin_n=ON, half_size_m=HALF,
    xmin=xmin, xmax=xmax, ymin=ymin, ymax=ymax,
    corners_en=corners_en,
    corners_lonlat=[[round(a, 7), round(c, 7)] for a, c in corners_ll],
    centre_lonlat=[round(lon0, 7), round(lat0, 7)],
    pagoda=dict(osm_way=371717416, e=round(pe, 2), n=round(pn, 2), lon=round(plon, 7), lat=round(plat, 7),
                local_x=round(pe - OE, 2), local_y=round(pn - ON, 2), osm_height_m=46,
                footprint_area_m2=round(pag.area, 1)),
    grid_convergence_deg=round(conv, 4),
    jis_mesh3=sorted(meshes),
    lonlat_bbox=[min(c[0] for c in corners_ll), min(c[1] for c in corners_ll),
                 max(c[0] for c in corners_ll), max(c[1] for c in corners_ll)],
)
with open(os.path.join(PROC, "boundary.json"), "w") as f:
    json.dump(b, f, indent=2, ensure_ascii=False)
print(json.dumps(b, indent=2, ensure_ascii=False))
