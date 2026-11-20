"""Parse an OSM XML extract into projected features, preserving OSM ids and tags."""
import sys
import xml.etree.ElementTree as ET
from common import ll2en


def parse(path):
    root = ET.parse(path).getroot()
    nodes, ways, rels = {}, {}, {}
    for el in root:
        tags = {t.get("k"): t.get("v") for t in el.findall("tag")}
        if el.tag == "node":
            lon, lat = float(el.get("lon")), float(el.get("lat"))
            e, n = ll2en(lon, lat)
            nodes[int(el.get("id"))] = dict(id=int(el.get("id")), lon=lon, lat=lat, e=e, n=n, tags=tags)
        elif el.tag == "way":
            ways[int(el.get("id"))] = dict(id=int(el.get("id")), nds=[int(nd.get("ref")) for nd in el.findall("nd")], tags=tags)
        elif el.tag == "relation":
            rels[int(el.get("id"))] = dict(
                id=int(el.get("id")),
                members=[dict(type=m.get("type"), ref=int(m.get("ref")), role=m.get("role")) for m in el.findall("member")],
                tags=tags,
            )
    return nodes, ways, rels


def way_coords(way, nodes):
    return [(nodes[i]["e"], nodes[i]["n"]) for i in way["nds"] if i in nodes]


if __name__ == "__main__":
    nodes, ways, rels = parse(sys.argv[1])
    print(len(nodes), len(ways), len(rels))
