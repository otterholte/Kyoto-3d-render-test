"""A3b: OSM highway centreline samples (1 m) that fall inside a scene building's wall outline (art + blockout)."""
import os
import pickle
import collections
from shapely.geometry import Point
from shapely.strtree import STRtree
from acommon import OUT, save

R = {}
for tag in ("blockout", "art"):
    S = pickle.load(open(os.path.join(OUT, "scene_%s.pkl" % tag), "rb"))["buildings"]
    W = [(k, v[0]["wall15"].buffer(-0.25)) for k, v in S.items() if v[0]["wall15"] is not None]
    tr = STRtree([w[1] for w in W])
    cl = pickle.load(open(os.path.join(OUT, "probe_%s.pkl" % tag), "rb"))["centreline"]
    hit = collections.defaultdict(list)
    for c in cl:
        p = Point(c["x"], c["y"])
        for i in tr.query(p):
            if W[i][1].contains(p):
                hit[(c["osm_id"], c["highway"], c["name"], W[i][0])].append((round(c["x"], 1), round(c["y"], 1)))
    R[tag] = dict(n_points=len(cl), n_inside=sum(len(v) for v in hit.values()),
                  by_way=sorted([dict(osm_id=k[0], highway=k[1], name=k[2], bldg=k[3], n_m=len(v), first=v[0]) for k, v in hit.items()],
                                key=lambda d: -d["n_m"]))
save("a3b_centreline_buildings.json", R)
for t in R:
    print(t, R[t]["n_points"], R[t]["n_inside"])
    for d in R[t]["by_way"][:14]:
        print("  ", d)
