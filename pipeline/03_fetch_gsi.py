"""Phase 2B: GSI (国土地理院) tiles covering the boundary.
 - DEM5A (laser survey 5 m grid) text tiles at z15, fallback DEM5B/DEM10B per pixel  -> elevation
 - experimental_fgd z18 GeoJSON (基盤地図情報: 建築物の外周線 BldL, 道路縁 RdEdg, 等) -> verification layers
 - pale / seamlessphoto z17-18 PNG/JPG for the master map backdrop (reference only, not facade source)
All GSI tiles: 出典 国土地理院 (GSI terms of use; attribution required)."""
import math, os, time, requests
from common import RAW, load_boundary
UA = {"User-Agent": "higashiyama-research/1.0 (open-data reconstruction)"}
b = load_boundary()
lon0, lat0, lon1, lat1 = b["lonlat_bbox"]
pad = 0.0015

def tiles(z):
    def t(lon, lat):
        n = 2 ** z
        x = int((lon + 180) / 360 * n)
        y = int((1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * n)
        return x, y
    x0, y1 = t(lon0 - pad, lat0 - pad); x1, y0 = t(lon1 + pad, lat1 + pad)
    return [(x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)]

def get(url, dst):
    if os.path.exists(dst): return True
    for a in range(4):
        try:
            r = requests.get(url, headers=UA, timeout=60)
            if r.status_code == 404: return False
            r.raise_for_status()
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            open(dst, "wb").write(r.content); return True
        except Exception as e:
            time.sleep(2 * (a + 1))
    print("FAIL", url); return False

base = "https://cyberjapandata.gsi.go.jp/xyz"
out = os.path.join(RAW, "gsi")
jobs = []
for (x, y) in tiles(15):
    for lay in ("dem5a", "dem5b", "dem10b"):
        jobs.append((f"{base}/{lay}/15/{x}/{y}.txt", f"{out}/{lay}/15/{x}/{y}.txt"))
for (x, y) in tiles(18):
    jobs.append((f"{base}/experimental_fgd/18/{x}/{y}.geojson", f"{out}/experimental_fgd/18/{x}/{y}.geojson"))
for (x, y) in tiles(17):
    jobs.append((f"{base}/pale/17/{x}/{y}.png", f"{out}/pale/17/{x}/{y}.png"))
    jobs.append((f"{base}/seamlessphoto/17/{x}/{y}.jpg", f"{out}/seamlessphoto/17/{x}/{y}.jpg"))
ok = 0
for u, d in jobs:
    ok += get(u, d)
print("tiles ok", ok, "of", len(jobs))
