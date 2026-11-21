"""Coherent facade-atlas assignment (replaces the per-wall-plane random choice of materials_textured.assign_facades).

Per building ONE module family is chosen, seeded by the PLATEAU id:
  * one upper-storey module for street fronts + one plaster colour (cream or ochre) for every other upper wall;
  * one ground-floor module for street fronts, plus at most ~one feature bay (shop opening / noren entrance) on
    commercial fronts via p_gf_alt ~ 1/bays;
  * side, rear and party walls: plain itabari or plaster base on the ground floor and plain plaster above (no stacked
    window modules on tall blank walls);
  * Priority-2 traditional fronts never get modern modules;
  * where the geometric machiya kit stands (Priority-2 street fronts), the ground floor behind it is plain itabari so the
    kit lattice / doors / shopfronts do not double up with painted ones; the upper storey comes from the atlas (the kit's
    flat 2F pieces are no longer placed).
"""
import numpy as np

import materials_textured as MT

UF_STREET = ["machiya_uf_window_lattice", "machiya_uf_glazed_railing", "machiya_uf_mushikomado", "machiya_uf_plaster"]
UF_W = [0.42, 0.33, 0.12, 0.13]
GF_STREET = ["machiya_gf_senkoshi", "machiya_gf_senkoshi_dark", "machiya_gf_glazed_doors", "machiya_gf_itabari",
             "machiya_gf_plaster_base"]
GF_W = [0.3, 0.25, 0.2, 0.15, 0.1]


def _pick(r, items, w):
    w = np.array(w, float)
    return items[min(int(np.searchsorted(np.cumsum(w) / w.sum(), r)), len(items) - 1)]


def plan_building(ob, attrs, streets, kit_front=False, street_dist=8.0):
    a = {k: ob.get(k) for k in ("storeys", "usage", "structure", "year", "name", "base_z", "plateau_id")}
    a.update({k: v for k, v in attrs.items() if v is not None})
    base_z = float(a.get("base_z") or min((ob.matrix_world @ v.co).z for v in ob.data.vertices))
    eave_h = MT.building_eave_height(ob, base_z)
    key = a.get("plateau_id") or ob.name
    kind = MT.classify(a)
    if ob.get("priority") == 2 and ob.get("traditional"):
        kind = "traditional"
    r = [MT._h(key, i) for i in range(8)]
    storeys = max(1, int(a.get("storeys") or (2 if eave_h > 4.5 else 1)))
    n_up = max(0, storeys - 1)
    gf_h = min(3.0, max(2.4, eave_h if storeys == 1 else 3.0))
    uf_h = 2.4 if n_up == 0 else float(np.clip((eave_h - gf_h) / n_up, 1.9, 3.4))
    commercial = str(a.get("usage") or "") in MT.COMMERCIAL or str(a.get("usage") or "") == "461"
    ochre = r[0] < 0.35
    plain_uf = "machiya_uf_plaster_ochre" if ochre else "machiya_uf_plaster"
    plain_gf = "machiya_gf_itabari" if r[1] < 0.6 else "machiya_gf_plaster_base"
    street_uf = _pick(r[2], UF_STREET, UF_W)
    if street_uf == "machiya_uf_mushikomado" and ochre:
        street_uf = "machiya_uf_mushikomado_ochre"
    if street_uf == "machiya_uf_plaster":
        street_uf = plain_uf
    street_gf = _pick(r[3], GF_STREET, GF_W)
    feature = ("machiya_gf_shop_open" if r[4] < 0.5 else "machiya_gf_noren_entrance") if commercial else "machiya_gf_noren_entrance"
    seed = int(r[5] * 90)

    def plan(info):
        c = np.array([info["center"].x, info["center"].y])
        d, s, foot = MT._dist_to_streets(c, streets)
        facing = False
        if d < street_dist:
            to = foot - c
            nrm = np.array([info["normal"].x, info["normal"].y])
            facing = float(np.dot(to, nrm)) > 0.2 * max(np.linalg.norm(to), 1e-6) or d < 2.0
        facing = facing and info["length"] > 1.5
        base = dict(gf_h=gf_h, uf_h=uf_h, n_upper=n_up, seed=seed, street_facing=facing, kind=kind)
        if kind == "temple":
            wall = "white_plaster_vermilion" if "庚申" in str(a.get("name") or "") else "white_plaster_timber"
            return dict(base, gf=wall, uf=wall, top=wall, p_gf_alt=0, p_uf_alt=0, uf_h=max(uf_h, 2.4))
        if kind == "modern":
            gf = "modern_gf_shopfront" if (facing and commercial) else "modern_uf_window"
            return dict(base, gf=gf, uf="modern_uf_window", top="modern_uf_window", gf_h=3.0,
                        uf_h=float(np.clip(uf_h, 2.8, 3.4)), p_gf_alt=0.0, p_uf_alt=0.0)
        if not facing:
            return dict(base, gf=plain_gf, gf_half=plain_gf + "_half", uf=plain_uf, uf_half="machiya_uf_plaster_half",
                        top=plain_uf, p_gf_alt=0.0, p_uf_alt=0.0)
        bays = max(1, int(round(info["length"] / 1.82)))
        gf = "machiya_gf_itabari" if kit_front else street_gf
        p_feat = 0.0 if (kit_front or bays < 2) else min(0.34, 1.0 / bays)
        return dict(base, gf=gf, gf_alt=feature, gf_half=gf + "_half" if gf + "_half" in MT.atlas()["modules"] else gf,
                    uf=street_uf, uf_alt=street_uf, uf_half="machiya_uf_window_lattice_half", top=plain_uf,
                    p_gf_alt=p_feat, p_uf_alt=0.0)
    return MT.apply_wall_facade_uvs(ob, plan, wall_pred=lambda p, n: abs(n.z) < 0.35 and p.material_index == 1,
                                    base_z=base_z)
