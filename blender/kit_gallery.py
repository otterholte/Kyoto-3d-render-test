"""Web gallery copies of the final renders: web/assets/renders/<name>.jpg (<= 2560 px wide) + renders.json.

  /home/user/venv/bin/python blender/kit_gallery.py
"""
import glob
import json
import os

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "web", "assets", "renders")
INFO = {
    "a_yasaka_dori_east": ("Yasaka-dōri, looking east to Yasaka Pagoda",
                           "Late afternoon (16:00 JST, sun 231°/11.5°) from OSM way 24516359 at eye height; small granite setts, "
                           "utility poles (observed on this segment), machiya fronts with kawara hisashi."),
    "b_ninenzaka_south": ("Ninenzaka, looking south to its steps",
                          "Dusk (16:25 JST) on OSM way 30913263; ishidatami slabs, lanterns and lit shopfronts, the 17-step flight at the far end."),
    "c_sannenzaka_stairs": ("Sannenzaka stone stair",
                            "Dusk, from the foot of the 46-step flight (OSM way 179116810) looking up-south toward Kiyomizu-zaka."),
    "d_bluehour_roofs": ("Blue hour over the kawara roofs",
                         "14 m above Yasaka-dōri east, looking WNW across the tiled roofs to the illuminated pagoda and the city to the western hills."),
    "e_yasaka_dori_upper_west": ("Yasaka-dōri, the classic view down to the pagoda",
                                 "Dusk, from the position of the Commons photo 'Gojunoto Tower ... at dusk' (local 91.8, 44.7), looking WNW."),
}


def main():
    os.makedirs(OUT, exist_ok=True)
    entries = []
    for f in sorted(glob.glob(os.path.join(ROOT, "renders", "final_*.png"))):
        key = os.path.basename(f)[6:-4]
        im = Image.open(f).convert("RGB")
        if im.width > 2560:
            im = im.resize((2560, round(im.height * 2560 / im.width)), Image.LANCZOS)
        name = key + ".jpg"
        im.save(os.path.join(OUT, name), quality=88, optimize=True, progressive=True)
        t, c = INFO.get(key, (key, ""))
        entries.append(dict(file="assets/renders/" + name, title=t, caption=c + " Cycles render, 3840×2160 source: renders/final_%s.png." % key))
    json.dump(entries, open(os.path.join(OUT, "renders.json"), "w"), ensure_ascii=False, indent=1)
    print("gallery", len(entries))


if __name__ == "__main__":
    main()
