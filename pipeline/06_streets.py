"""Phase 2A/2B/4: streets, paths, steps, barriers, trees, open spaces -> data/processed/streets.json, features.json.

Sources merged (all IDs preserved):
  OSM (ODbL)      : highway network incl. steps/footways, names, surface, width, step_count, access;
                    barriers (wall/fence/gate), trees, gardens/parks, places of worship, POIs, OSM buildings
  PLATEAU tran    : surveyed road AREA polygons (LOD1) -> road surface + width estimation
  GSI 基盤地図情報 : RdEdg (road edge), BldL (building outline), RdCompt (sidewalk), ElevPt, Cntr
"""
import glob
import json
import os
import numpy as np
from lxml import etree
from shapely.geometry import LineString, Polygon, Point, box, mapping, shape
from shapely.ops import unary_union
from common import RAW, PROC, load_boundary, ll2en
from osm_parse import parse, way_coords
from terrain_sample import ground

b = load_boundary()
OE, ON = b["origin_e"], b["origin_n"]
BOX = box(-200, -200, 200, 200)
CLIP = box(-300, -300, 300, 300)


def loc(coords):
    return [(e - OE, n - ON) for e, n in coords]


def r3(seq):
    return [[round(x, 2), round(y, 2)] for x, y in seq]


# ---------------- PLATEAU road polygons ----------------
NS = {"gml": "http://www.opengis.net/gml", "tran": "http://www.opengis.net/citygml/transportation/2.0"}
troot = etree.parse(os.path.join(RAW, "plateau", "udx", "tran", "52353692_tran_6697_op.gml")).getroot()
roads_pl = []
for el in troot.iter("{%s}Road" % NS["tran"]):
    gid = el.get("{%s}id" % NS["gml"])
    fn = el.findtext("tran:function", namespaces=NS)
    for pl in el.findall(".//gml:Polygon", NS):
        ext = np.array(pl.find("gml:exterior//gml:posList", NS).text.split(), float).reshape(-1, 3)
        e, n = ll2en(ext[:, 1], ext[:, 0])
        holes = []
        for h in pl.findall("gml:interior//gml:posList", NS):
            hv = np.array(h.text.split(), float).reshape(-1, 3)
            he, hn = ll2en(hv[:, 1], hv[:, 0])
            holes.append(list(zip(np.asarray(he) - OE, np.asarray(hn) - ON)))
        g = Polygon(list(zip(np.asarray(e) - OE, np.asarray(n) - ON)), holes).buffer(0)
        if g.is_empty or not g.intersects(CLIP):
            continue
        roads_pl.append(dict(id=gid, function=fn, geom=g))
road_area = unary_union([r["geom"] for r in roads_pl])

# ---------------- OSM ----------------
nodes, ways, rels = parse(os.path.join(RAW, "osm", "osm_wide.osm"))
DEFAULT_W = dict(secondary=12.0, tertiary=8.0, unclassified=5.0, residential=4.5, service=3.5, pedestrian=4.5,
                 living_street=4.0, footway=2.0, path=1.5, steps=2.5, track=2.5, cycleway=2.0)


def est_width(line):
    """Median perpendicular extent of the PLATEAU road area across the line (sample every 2 m)."""
    ws = []
    L = line.length
    for s in np.arange(1.0, max(L - 1.0, 1.01), 2.0):
        p = line.interpolate(s)
        q = line.interpolate(min(s + 0.5, L))
        d = np.array([q.x - p.x, q.y - p.y]);
        if np.linalg.norm(d) < 1e-6:
            continue
        d /= np.linalg.norm(d); nrm = np.array([-d[1], d[0]])
        seg = LineString([(p.x - nrm[0] * 15, p.y - nrm[1] * 15), (p.x + nrm[0] * 15, p.y + nrm[1] * 15)])
        inter = seg.intersection(road_area)
        if inter.is_empty:
            continue
        parts = getattr(inter, "geoms", [inter])
        best = min(parts, key=lambda g: g.distance(p))
        if best.distance(p) < 0.5:
            ws.append(best.length)
    return (float(np.median(ws)), len(ws)) if len(ws) >= 2 else (None, len(ws))


streets = []
adj = {}
for w in ways.values():
    t = w["tags"]
    hw = t.get("highway")
    if not hw or hw in ("construction", "proposed", "platform", "bus_stop"):
        continue
    c = loc(way_coords(w, nodes))
    if len(c) < 2:
        continue
    ln = LineString(c)
    if not ln.intersects(CLIP):
        continue
    wtag = None
    try:
        wtag = float(t.get("width", "").replace("m", "").strip()) if t.get("width") else None
    except ValueError:
        pass
    if hw in ("secondary", "tertiary", "unclassified", "residential", "service", "pedestrian", "living_street"):
        w_est, nsamp = est_width(ln)
    else:
        w_est, nsamp = None, 0
    if wtag:
        width, wsrc = wtag, "osm:width"
    elif w_est and 1.2 < w_est < 25:
        width, wsrc = round(w_est, 2), "plateau:road-area (median of %d cross-sections)" % nsamp
    else:
        width, wsrc = DEFAULT_W.get(hw, 3.0), "default-by-highway-type (inferred)"
    z = ground([p[0] for p in c], [p[1] for p in c])
    streets.append(dict(
        osm_id=w["id"], highway=hw, name=t.get("name"), name_en=t.get("name:en"), surface=t.get("surface"),
        width_m=width, width_src=wsrc, step_count=t.get("step_count"), incline=t.get("incline"),
        access=t.get("access"), foot=t.get("foot"), handrail=t.get("handrail"), lit=t.get("lit"),
        oneway=t.get("oneway"), layer=t.get("layer"), tunnel=t.get("tunnel"), bridge=t.get("bridge"),
        nodes=w["nds"], coords=r3(c), z=[round(float(v), 2) for v in z],
        in_box=ln.intersects(BOX), length_m=round(ln.length, 1), tags=t,
    ))
    for a, bb in zip(w["nds"][:-1], w["nds"][1:]):
        adj.setdefault(a, set()).add(bb); adj.setdefault(bb, set()).add(a)

# connectivity: components of the walkable graph restricted to nodes inside the box
inbox_nodes = {nid for nid in adj if nid in nodes and BOX.contains(Point(nodes[nid]["e"] - OE, nodes[nid]["n"] - ON))}
comp, cid = {}, 0
for s in inbox_nodes:
    if s in comp:
        continue
    stack = [s]; comp[s] = cid
    while stack:
        u = stack.pop()
        for v in adj[u]:
            if v in inbox_nodes and v not in comp:
                comp[v] = cid; stack.append(v)
    cid += 1
sizes = {}
for v in comp.values():
    sizes[v] = sizes.get(v, 0) + 1
main = max(sizes, key=sizes.get)
for s in streets:
    cs = {comp[n] for n in s["nodes"] if n in comp}
    s["component"] = sorted(cs)
    s["connected_to_main"] = main in cs

# step validation: elevation change and implied riser height
for s in streets:
    if s["highway"] == "steps":
        dz = abs(s["z"][-1] - s["z"][0])
        s["dz_terrain_m"] = round(dz, 2)
        if s["step_count"]:
            try:
                s["riser_m_implied"] = round(dz / int(s["step_count"]), 3)
            except ValueError:
                pass

# ---------------- other OSM features ----------------
features = dict(barriers=[], trees=[], areas=[], pois=[], osm_buildings=[])
for w in ways.values():
    t = w["tags"]; c = loc(way_coords(w, nodes))
    if len(c) < 2 or not LineString(c).intersects(CLIP):
        continue
    closed = len(c) > 3 and w["nds"][0] == w["nds"][-1]
    if "barrier" in t:
        features["barriers"].append(dict(osm_id=w["id"], barrier=t["barrier"], material=t.get("material"),
                                         height=t.get("height"), coords=r3(c), tags=t))
    if "building" in t and closed:
        features["osm_buildings"].append(dict(osm_id=w["id"], building=t["building"], name=t.get("name"),
                                              levels=t.get("building:levels"), height=t.get("height"),
                                              roof_shape=t.get("roof:shape"), coords=r3(c), tags=t))
    if closed and any(k in t for k in ("landuse", "leisure", "natural", "amenity", "tourism", "historic", "place")) and "building" not in t and "highway" not in t:
        features["areas"].append(dict(osm_id=w["id"], coords=r3(c), tags=t))
    if t.get("natural") == "tree_row":
        features["trees"].append(dict(osm_id=w["id"], kind="tree_row", coords=r3(c), tags=t))
for r in rels.values():
    t = r["tags"]
    if t.get("type") == "multipolygon" and ("building" in t or "amenity" in t or "leisure" in t or "landuse" in t):
        outers = [ways[m["ref"]] for m in r["members"] if m["type"] == "way" and m["role"] == "outer" and m["ref"] in ways]
        for ow in outers:
            c = loc(way_coords(ow, nodes))
            if len(c) > 3 and LineString(c).intersects(CLIP):
                tgt = "osm_buildings" if "building" in t else "areas"
                features[tgt].append(dict(osm_id=r["id"], relation=True, building=t.get("building"), name=t.get("name"),
                                          coords=r3(c), tags=t))
for n in nodes.values():
    t = n["tags"]
    if not t:
        continue
    x, y = n["e"] - OE, n["n"] - ON
    if not CLIP.contains(Point(x, y)):
        continue
    rec = dict(osm_id=n["id"], x=round(x, 2), y=round(y, 2), z=round(float(ground(x, y)), 2), tags=t)
    if t.get("natural") == "tree":
        features["trees"].append(dict(kind="tree", **rec))
    elif "barrier" in t:
        features["barriers"].append(dict(barrier=t["barrier"], point=True, **rec))
    elif any(k in t for k in ("name", "amenity", "shop", "tourism", "historic", "man_made", "highway")):
        features["pois"].append(rec)

# ---------------- GSI 基盤地図情報 vector (experimental_fgd z18) ----------------
gsi = dict(RdEdg=[], BldL=[], RdCompt=[], ElevPt=[], Cntr=[])
seen = set()
for f in glob.glob(os.path.join(RAW, "gsi", "experimental_fgd", "18", "*", "*.geojson")):
    for ft in json.load(open(f))["features"]:
        p = ft["properties"]; cl = p.get("class")
        if cl not in gsi:
            continue
        key = (p.get("fid"), json.dumps(ft["geometry"]["coordinates"])[:80])
        if key in seen:
            continue
        seen.add(key)
        g = ft["geometry"]
        if g["type"] == "Point":
            e, n = ll2en(*g["coordinates"][:2])
            gsi[cl].append(dict(fid=p.get("fid"), type=p.get("type"), alti=p.get("alti"), x=round(e - OE, 2), y=round(n - ON, 2)))
        elif g["type"] == "LineString":
            c = [ll2en(lo, la) for lo, la in g["coordinates"]]
            c = loc(c)
            if LineString(c).intersects(CLIP):
                gsi[cl].append(dict(fid=p.get("fid"), type=p.get("type"), alti=p.get("alti"), coords=r3(c)))

out = dict(
    sources=dict(osm="OpenStreetMap contributors, ODbL 1.0 (api.openstreetmap.org map call, 2026-11-20)",
                 plateau="PLATEAU 2025 Kyoto City tran LOD1, mesh 52353692",
                 gsi="国土地理院 基盤地図情報 via experimental_fgd vector tiles z18"),
    streets=streets,
    plateau_roads=[dict(id=r["id"], function=r["function"],
                        exterior=r3(r["geom"].exterior.coords) if r["geom"].geom_type == "Polygon" else [r3(g.exterior.coords) for g in r["geom"].geoms],
                        multi=r["geom"].geom_type != "Polygon") for r in roads_pl],
    gsi=gsi,
    connectivity=dict(components_in_box=len(sizes), main_component_nodes=sizes[main],
                      other_component_sizes=sorted([v for k, v in sizes.items() if k != main], reverse=True)),
)
json.dump(out, open(os.path.join(PROC, "streets.json"), "w"), ensure_ascii=False)
json.dump(features, open(os.path.join(PROC, "features.json"), "w"), ensure_ascii=False)
inb = [s for s in streets if s["in_box"]]
print("streets clipped", len(streets), "in box", len(inb), "steps in box", sum(s["highway"] == "steps" for s in inb))
print("connectivity", out["connectivity"])
print("width src", {k: sum(1 for s in inb if s["width_src"].startswith(k)) for k in ("osm", "plateau", "default")})
print("plateau road polys", len(roads_pl), "gsi", {k: len(v) for k, v in gsi.items()})
print({k: len(v) for k, v in features.items()})
for s in inb:
    if s["name"] in ("二寧坂", "産寧坂", "八坂通", "一念坂", "京都市道 八坂通", "夢見坂") or s["highway"] == "steps":
        print(s["osm_id"], s["highway"], s["name"], s["width_m"], s["width_src"][:20], s["surface"], s.get("step_count"), s.get("dz_terrain_m"), s["connected_to_main"])
