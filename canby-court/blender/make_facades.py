"""ONE-OFF bootstrap of data/facades.json (the appearance source of truth read by build_scene.py).

Run once; afterwards edit data/facades.json directly (e.g. replace inferred colours with values sampled from
real photos and set confidence to "documented"/"observed (photo)"). Re-running overwrites manual edits unless
--force is NOT given and the file exists.

Roof colours: computed from the aerial pixel medians already stored in data/processed/houses.json (City 2022
EagleView + County 2024 Pictometry orthos, sampled locally for analysis only; no imagery is copied).
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "data", "facades.json")

H = {h["number"]: h for h in json.load(open(os.path.join(ROOT, "data", "processed", "houses.json")))["houses"]}


def roof_hex(n):
    c = H[n]["roof"]["colour"]
    a = c["ortho_cob2022_core"]["median_rgb"]
    b = c["ortho_wc2024_core"]["median_rgb"]
    rgb = [min(255, round(0.5 * (x + y) * 0.85)) for x, y in zip(a, b)]
    return "#%02x%02x%02x" % tuple(rgb)


def F(value, conf, src):
    return {"value": value, "confidence": conf, "source": src}


ERA80 = "era/style norm: 1984-88 Bellingham builder homes (inferred, no photo)"
CRAFT = "era/style norm: 2015 Pacific-Northwest Craftsman new build (inferred, no photo)"
NOEV = "no facade evidence (nadir orthos show roofs only; no street-level imagery available)"
ORTHO = "observed on City 2022 / County 2024 orthophotos (analysis only)"
LIST = "listing snippet (docs/evidence.md)"


def roof(n, extra_src=""):
    return F({"material": "architectural (laminated) asphalt shingle", "colour_hex": roof_hex(n),
              "texture": "roof_arch_shingle", "ridge_caps": True},
             "measured (aerial colour) / documented or observed (material)",
             "colour = mean of 2022+2024 ortho pixel medians in houses.json x0.85 exposure correction; " +
             ("material: " + LIST if n in (3802, 3813, 3909) else "material: shingle texture " + ORTHO) + extra_src)


houses = []


def add(n, **kw):
    rec = {"number": n, "address": "%d Canby Ct" % n}
    rec.update(kw)
    houses.append(rec)


add(3802,
    siding=F({"type": "lap", "texture": "siding_lap_wood", "exposure_in": 7}, "documented (material) / inferred (profile)",
             LIST + ": 'wood' exterior; horizontal lap profile = " + ERA80),
    body_colour=F("#7f8577", "inferred", NOEV + "; muted sage-grey, " + ERA80),
    trim_colour=F("#ecebe4", "inferred", ERA80),
    door=F({"style": "6panel", "colour": "#6b2a26"}, "inferred", ERA80),
    garage_door=F({"count": 1, "width_m": 4.88, "height_m": 2.13, "style": "steel short raised panel",
                   "colour": "trim", "wall_point": [-96.0, -23.5]}, "observed (garage side) / inferred (doors)",
                  "houses.json garage: NE wing facing Canby Ct, 2 cars; " + ORTHO),
    front_door=F({"wall_point": [-102.0, -24.4], "porch": "small covered stoop", "steps": 2}, "inferred",
                 "entry on the NW (street-side) face near the observed light-wood deck/porch at the NW corner"),
    windows=F({"type": "white vinyl slider", "frame_hex": "#f1f1ec", "grilles": False, "storeys": 1},
              "inferred", ERA80 + "; likely replacement vinyl (sold 2023)"),
    chimney=F(None, "observed (aerial)", "none seen on the orthos"),
    gutters=F({"style": "K-style aluminium", "colour": "trim"}, "inferred", ERA80),
    deck=F({"where": "NW corner", "material": "light wood", "railing": "wood", "point": [-104.5, -21.5],
            "size_m": [4.0, 3.0]}, "observed (aerial)", ORTHO),
    skylights=F([[-98.0, -33.0]], "observed (aerial)", ORTHO),
    solar=F(None, "observed (aerial)", "none"),
    roof=roof(3802))

add(3803,
    siding=F({"type": "lap", "texture": "siding_lap_wood", "exposure_in": 7}, "inferred", ERA80),
    body_colour=F("#b9ad94", "inferred", NOEV + "; warm tan, " + ERA80),
    trim_colour=F("#f0eee6", "inferred", ERA80),
    door=F({"style": "6panel", "colour": "#2f4a3c"}, "inferred", ERA80),
    garage_door=F({"count": 1, "width_m": 4.88, "height_m": 2.13, "style": "steel short raised panel",
                   "colour": "trim", "wall_point": [-99.0, 8.25]}, "observed (garage end) / inferred (doors)",
                  "houses.json: garage at the east end, drive from Canby Ct; " + ORTHO),
    front_door=F({"wall_point": [-110.3, 11.2], "porch": "recessed entry", "steps": 2}, "inferred",
                 "footprint notch on the street (south) face"),
    windows=F({"type": "white vinyl slider", "frame_hex": "#f1f1ec", "grilles": False}, "inferred", ERA80),
    chimney=F(None, "observed (aerial)", "none seen"),
    gutters=F({"style": "K-style aluminium", "colour": "trim"}, "inferred", ERA80),
    deck=F({"where": "rear (north) low-slope sunroom + white pergola", "point": [-104.0, 27.5],
            "size_m": [5.0, 3.0], "material": "white pergola"}, "observed (aerial)", ORTHO),
    skylights=F([], "observed (aerial)", "none"),
    solar=F(None, "observed (aerial)", "none"),
    roof=roof(3803))

add(3806,
    siding=F({"type": "T1-11", "texture": "siding_t111", "upper": "lap"}, "inferred",
             ERA80 + "; split-levels of the mid-80s commonly used T1-11 panel siding"),
    body_colour=F("#6e7c84", "inferred", NOEV + "; slate blue-grey"),
    trim_colour=F("#e9e8e1", "inferred", ERA80),
    door=F({"style": "6panel", "colour": "#e9e8e1"}, "inferred", ERA80),
    garage_door=F({"count": 1, "width_m": 4.88, "height_m": 2.13, "style": "steel short raised panel",
                   "colour": "trim", "wall_point": [-58.0, -41.8]}, "observed (garage side) / inferred (doors)",
                  "houses.json: garage on the north side, long drive along the west; " + ORTHO),
    front_door=F({"wall_point": [-46.5, -46.1], "porch": "covered stoop", "steps": 3}, "inferred",
                 "split-level entry on the street (north) face"),
    windows=F({"type": "white vinyl slider", "frame_hex": "#f1f1ec", "grilles": False}, "inferred", ERA80),
    chimney=F(None, "observed (aerial)", "none seen"),
    gutters=F({"style": "K-style aluminium", "colour": "#e9e8e1"}, "inferred", ERA80),
    deck=F({"where": "rear (south) deck with raised planter boxes", "point": [-52.0, -59.5], "size_m": [6.0, 3.5],
            "material": "wood", "railing": "wood"}, "observed (aerial)", ORTHO),
    skylights=F([[-55.0, -50.0]], "observed (aerial)", ORTHO),
    solar=F(None, "observed (aerial)", "none"),
    split_level=F({"high_part_point": [-48.0, -52.0], "offset_m": 1.3}, "inferred",
                  "City STYLE 'SPLIT'; half-storey offset placed on the downhill side (inferred)"),
    roof=roof(3806))

add(3807,
    siding=F({"type": "lap", "texture": "siding_lap_wood", "exposure_in": 7}, "inferred",
             ERA80 + "; stained cedar lap fits the observed brown roof"),
    body_colour=F("#7a6150", "inferred", NOEV + "; warm brown stain (goes with the observed brown roof)"),
    trim_colour=F("#e6dfcf", "inferred", ERA80),
    door=F({"style": "6panel", "colour": "#4a3326"}, "inferred", ERA80),
    garage_door=F({"count": 1, "width_m": 4.88, "height_m": 2.13, "style": "steel short raised panel",
                   "colour": "trim", "wall_point": [-70.5, -2.3]}, "observed (drive) / inferred (doors)",
                  "houses.json: garage east side, concrete drive to Canby Ct; " + ORTHO),
    front_door=F({"wall_point": [-78.0, 1.5], "porch": "recessed entry", "steps": 3}, "inferred",
                 "footprint recess on the street face"),
    windows=F({"type": "bronze aluminium slider", "frame_hex": "#4b4038", "grilles": False}, "inferred",
              ERA80 + " (1984: original anodised aluminium plausible)"),
    chimney=F({"type": "brick", "point": [-84.0, 9.0]}, "observed (aerial) / inferred (material)", ORTHO),
    gutters=F({"style": "K-style aluminium", "colour": "#6a5444"}, "inferred", ERA80),
    deck=F({"where": "rear (north) deck, white railing", "point": [-74.0, 14.5], "size_m": [8.0, 3.2],
            "material": "wood", "railing": "white"}, "observed (aerial)", ORTHO),
    skylights=F([[-83.0, 5.0], [-77.0, 8.0]], "observed (aerial)", ORTHO),
    solar=F(None, "observed (aerial)", "none"),
    split_level=F({"high_part_point": [-70.0, 5.0], "offset_m": 1.3}, "inferred", "City STYLE 'SPLIT'"),
    roof=roof(3807))

add(3811,
    siding=F({"type": "lap", "texture": "siding_lap_wood", "exposure_in": 7}, "inferred", ERA80),
    body_colour=F("#c9c2b0", "inferred", NOEV + "; light warm grey-beige"),
    trim_colour=F("#3e4a44", "inferred", ERA80 + "; dark green-grey trim variant"),
    door=F({"style": "6panel", "colour": "#7a2b24"}, "inferred", ERA80),
    garage_door=F({"count": 1, "width_m": 4.88, "height_m": 2.13, "style": "steel short raised panel",
                   "colour": "#efeee8", "wall_point": [-47.2, -9.9]}, "observed (drive) / inferred (doors)",
                  "houses.json: garage east side; " + ORTHO),
    front_door=F({"wall_point": [-54.0, -8.3], "porch": "covered stoop", "steps": 3}, "inferred", "street face"),
    windows=F({"type": "white vinyl slider", "frame_hex": "#f1f1ec", "grilles": False}, "inferred", ERA80),
    chimney=F({"type": "brick", "point": [-61.0, -1.0]}, "observed (aerial) / inferred (material)",
              "chimney at the west gable end, " + ORTHO),
    gutters=F({"style": "K-style aluminium", "colour": "#efeee8"}, "inferred", ERA80),
    deck=F({"where": "rear patio with fire pit", "point": [-52.0, 6.5], "size_m": [6.0, 3.0],
            "material": "concrete"}, "observed (aerial)", ORTHO),
    skylights=F([], "observed (aerial)", "none"),
    solar=F(None, "observed (aerial)", "none"),
    roof=roof(3811))

add(3813,
    siding=F({"type": "fibre-cement lap", "texture": "siding_lap_fibercement", "exposure_in": 7.25,
              "gables": "siding_shingle_cedar", "wainscot": "stone_ledgestone"},
             "documented (material) / inferred (layout)",
             LIST + ": 'cement planked' + wood; gable shingles + stone column bases = " + CRAFT),
    body_colour=F("#5d6562", "inferred", NOEV + "; dark grey-green, typical 2015 Craftsman palette"),
    trim_colour=F("#f2f1ec", "inferred", CRAFT),
    door=F({"style": "craftsman", "colour": "#7a4e2d"}, "inferred", CRAFT + " (stained fir door)"),
    garage_door=F({"count": 1, "width_m": 4.88, "height_m": 2.29, "style": "carriage-style steel with top lites",
                   "colour": "trim", "wall_point": [-33.9, -4.81]}, "observed (drive) / inferred (doors)",
                  "houses.json: garage SW, drive to the bulb; " + ORTHO),
    front_door=F({"wall_point": [-27.0, -5.78], "porch": "Craftsman covered porch, tapered columns on stone bases",
                  "steps": 3}, "inferred", CRAFT),
    windows=F({"type": "white vinyl single-hung, Craftsman 3-over-1 grilles", "frame_hex": "#f4f4f0",
               "grilles": True}, "inferred", CRAFT),
    chimney=F(None, "observed (aerial)", "none seen"),
    gutters=F({"style": "K-style aluminium", "colour": "trim"}, "inferred", CRAFT),
    deck=F({"where": "rear (north) deck", "point": [-30.0, 11.5], "size_m": [7.0, 3.5], "material": "composite",
            "railing": "black metal"}, "documented (deck) / inferred (layout)", LIST + ": 'deck'"),
    skylights=F([[-27.0, 4.0]], "documented / observed (aerial)", LIST + "; " + ORTHO),
    solar=F(None, "observed (aerial)", "none"),
    roof=roof(3813))

add(3900,
    siding=F({"type": "lap", "texture": "siding_lap_wood", "exposure_in": 7}, "inferred", ERA80),
    body_colour=F("#9ba6a8", "inferred", NOEV + "; soft grey-blue (1.5-storey cross-gable, Cape-Cod-ish)"),
    trim_colour=F("#f0efe9", "inferred", ERA80),
    door=F({"style": "6panel", "colour": "#28374a"}, "inferred", ERA80),
    garage_door=F({"count": 2, "width_m": 2.74, "height_m": 2.13, "style": "steel short raised panel",
                   "colour": "trim", "wall_point": [-21.5, -54.4]}, "observed (drive) / inferred (doors)",
                  "houses.json: garage east side, drive from the bulb; " + ORTHO),
    front_door=F({"wall_point": [-28.6, -58.1], "porch": "recessed entry", "steps": 2}, "inferred",
                 "footprint recess on the bulb-facing face"),
    windows=F({"type": "white vinyl slider", "frame_hex": "#f1f1ec", "grilles": False}, "inferred", ERA80),
    chimney=F(None, "observed (aerial)", "none seen"),
    gutters=F({"style": "K-style aluminium", "colour": "trim"}, "inferred", ERA80),
    deck=F({"where": "west pergola/arbor", "point": [-36.5, -66.0], "size_m": [3.0, 4.0], "material": "white pergola"},
           "observed (aerial)", ORTHO),
    skylights=F([], "observed (aerial)", "none"),
    solar=F({"plane": "south", "panels": 24}, "observed (aerial)", ORTHO + "; large PV array on the south plane"),
    dormers=F({"count": 3, "face": "north"}, "observed (aerial)", ORTHO),
    roof=roof(3900))

add(3904,
    siding=F({"type": "lap", "texture": "siding_lap_wood", "exposure_in": 7}, "inferred", ERA80),
    body_colour=F("#c4b79c", "inferred", NOEV + "; beige"),
    trim_colour=F("#f3f1ea", "inferred", ERA80),
    door=F({"style": "6panel", "colour": "#5b3a2a"}, "inferred", ERA80),
    garage_door=F({"count": 1, "width_m": 4.88, "height_m": 2.13, "style": "steel short raised panel",
                   "colour": "trim", "wall_point": [-9.2, -50.1]}, "observed (drive) / inferred (doors)",
                  "houses.json: garage NW, drive from the bulb; " + ORTHO),
    front_door=F({"wall_point": [-2.4, -50.25], "porch": "covered entry court", "steps": 1}, "inferred",
                 "footprint notch on the bulb-facing face"),
    windows=F({"type": "white vinyl slider", "frame_hex": "#f1f1ec", "grilles": False}, "inferred", ERA80),
    chimney=F(None, "observed (aerial)", "none seen"),
    gutters=F({"style": "K-style aluminium", "colour": "trim"}, "inferred", ERA80),
    deck=F({"where": "rear (SE) deck", "point": [9.0, -62.5], "size_m": [6.0, 3.5], "material": "wood",
            "railing": "wood"}, "observed (aerial)", ORTHO),
    skylights=F([[4.0, -52.0], [7.0, -57.0]], "observed (aerial)", ORTHO),
    solar=F({"plane": "south-west", "panels": 14}, "observed (aerial)", "PV array on the SW plane, City 2022 ortho"),
    roof=roof(3904))

add(3905,
    siding=F({"type": "lap", "texture": "siding_lap_wood", "exposure_in": 7}, "inferred",
             NOEV + "; horizontal lap = " + ERA80 + ". HIGHEST-VALUE GAP: family photos of each elevation."),
    body_colour=F("#a39c8e", "inferred", NOEV + "; neutral taupe-grey chosen to sit with the observed light-grey roof"),
    trim_colour=F("#f1f0ea", "inferred", ERA80),
    door=F({"style": "6panel", "colour": "#2e4436"}, "inferred", ERA80),
    garage_door=F({"count": 2, "width_m": 2.74, "height_m": 2.13, "style": "steel short raised panel",
                   "colour": "trim", "wall_point": [11.1, -2.0]}, "observed (doors face south) / inferred (count)",
                  "houses.json: east garage wing, doors face south onto a concrete drive (6.4 m wide wall -> "
                  "2 single doors or 1 double: unknown)"),
    front_door=F({"wall_point": [-7.4, -3.3], "porch": "covered porch strip along the WSW face", "steps": 2},
                 "observed (lower roof strip, walk to the SW) / inferred (door position)",
                 "houses.json: lower roof strip on the SW face; walkway from the SW front to the bulb sidewalk"),
    windows=F({"type": "white vinyl slider", "frame_hex": "#f1f1ec", "grilles": False,
               "entry_transom": "half-round"}, "inferred", ERA80),
    chimney=F({"type": "siding-clad chase with metal cap", "point": [-5.0, 3.5]},
              "observed (position) / inferred (material)", "chimney on the NW part of the main roof, " + ORTHO),
    gutters=F({"style": "K-style aluminium", "colour": "trim"}, "inferred", ERA80),
    deck=F({"where": "back (NNW) deck off the main floor + patio in the NE re-entrant corner",
            "point": [-1.5, 8.2], "size_m": [6.0, 3.6], "material": "stained wood", "railing": "wood",
            "patio_point": [10.5, 7.0]}, "observed (patio, furniture) / inferred (deck)",
           ORTHO + "; deck size/position inferred for a believable back yard"),
    skylights=F([], "observed (aerial)", "none seen (row of roof vents instead)"),
    solar=F(None, "observed (aerial)", "none"),
    roof=roof(3905))

add(3909,
    siding=F({"type": "fibre-cement lap", "texture": "siding_lap_fibercement", "exposure_in": 7.25},
             "documented (material) / inferred (profile)", LIST + ": 'cement planked + wood'"),
    body_colour=F("#7e8a7d", "inferred", NOEV + "; sage green"),
    trim_colour=F("#ece9de", "inferred", ERA80),
    door=F({"style": "6panel", "colour": "#7a2f28"}, "inferred", ERA80),
    garage_door=F({"count": 1, "width_m": 4.88, "height_m": 2.13, "style": "steel short raised panel",
                   "colour": "trim", "wall_point": [5.7, -36.5]}, "observed (drive) / inferred (doors)",
                  "houses.json: garage SW end, drive from the bulb; " + ORTHO),
    front_door=F({"wall_point": [4.2, -22.0], "porch": "covered stoop", "steps": 2}, "inferred",
                 "bulb-facing (west) face"),
    windows=F({"type": "white vinyl slider", "frame_hex": "#f1f1ec", "grilles": False}, "inferred", ERA80),
    chimney=F(None, "observed (aerial)", "none seen"),
    gutters=F({"style": "K-style aluminium", "colour": "trim"}, "inferred", ERA80),
    deck=F(None, "observed (aerial)", "none seen (trampoline in the east yard)"),
    skylights=F([], "observed (aerial)", "none"),
    solar=F(None, "observed (aerial)", "none"),
    roof=roof(3909))

doc = {
    "schema": "Canby Court facade / exterior appearance record, one per house. SINGLE SOURCE OF TRUTH for the "
              "Blender build (blender/build_scene.py reads it). Every field = {value, confidence, source}.",
    "confidence_levels": {
        "documented": "public record / listing text",
        "measured": "computed from imagery pixels or GIS geometry",
        "observed (aerial)": "seen on the 2022/2024 nadir orthophotos (roof-level features only)",
        "inferred": "era/style norm or artistic choice - REPLACE when photos are available",
    },
    "how_to_update": "Edit values here (e.g. body_colour.value = '#hex' from a photo, confidence = "
                     "'observed (photo)'), then re-run: /home/user/venv/bin/python blender/build_scene.py && "
                     "blender/export_web.py. Colours are sRGB hex. 'trim' as a colour means use trim_colour. "
                     "wall_point = a point on/near the footprint wall where the door is centred (local metres).",
    "privacy": "addresses only; no owner names",
    "palette_note": "muted Pacific-Northwest suburban palette; colours deliberately varied between neighbours",
    "houses": houses,
}

if __name__ == "__main__":
    if os.path.exists(OUT) and "--force" not in sys.argv:
        print("exists, not overwriting (use --force):", OUT)
    else:
        json.dump(doc, open(OUT, "w"), indent=1)
        print("wrote", OUT)
