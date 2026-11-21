"""Shared helpers for the realistic texture library (numpy only, no bpy).

Conventions used everywhere in the library
------------------------------------------
* Albedo maps are sRGB-encoded (8-bit JPG/PNG). Everything else is linear / non-colour.
* Normal maps are tangent space, OpenGL convention: R = +X (u, right), G = +Y (v, up), B = +Z (out).
  (Blender's Normal Map node and Three.js both expect this; for DirectX/Unreal flip G.)
* ORM = R ambient occlusion, G roughness, B metalness (glTF / Three.js aoMap+roughnessMap+metalnessMap layout).
* Arrays are row-major "image" arrays: row 0 is the TOP of the texture (v = 1), as written to disk.
* Every generator works in physical units: a texture covers size_m = (width_m, height_m); px_m = metres per pixel.
"""
import json
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TEX_BL = os.path.join(HERE, "textures")
TEX_WEB = os.path.join(ROOT, "web", "assets", "tex")
SCRATCH = os.environ.get("TEXLIB_SCRATCH", os.path.join("/tmp", "texlib_scratch"))
FONT_JP = next((f for f in ("/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf",
                            "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf") if os.path.exists(f)), None)

for _d in (TEX_BL, TEX_WEB, SCRATCH):
    os.makedirs(_d, exist_ok=True)


# ----------------------------------------------------------------------------- colour
def hexc(h):
    h = h.lstrip("#")
    return np.array([int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)], dtype=np.float32)


def s2l(c):
    c = np.asarray(c, dtype=np.float32)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def l2s(c):
    c = np.clip(np.asarray(c, dtype=np.float32), 0, 1)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(c, 1 / 2.4) - 0.055)


def lerp(a, b, t):
    t = np.asarray(t, dtype=np.float32)
    if t.ndim == 2 and np.ndim(a) >= 1 and (np.ndim(a) == 3 or np.shape(a)[-1:] == (3,)):
        t = t[..., None]
    return a + (b - a) * t


def smooth(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0 + 1e-9), 0, 1)
    return t * t * (3 - 2 * t)


# ----------------------------------------------------------------------------- periodic noise
def fnoise(shape, lo=1.0, hi=None, beta=2.0, seed=0, aniso=(1.0, 1.0), rot=0.0):
    """Perfectly tileable fractal noise (FFT-filtered white noise), zero mean, unit std.

    lo/hi: band limits in cycles per texture (along the larger axis), beta: spectral slope
    (2 = classic fBm look, 0 = white). aniso=(ax, ay) = feature stretch factors: (1, 0.1) -> features 10x
    LONGER in y than in x (vertical streaks); (0.1, 1) -> horizontal streaks.
    """
    h, w = shape
    rng = np.random.default_rng(seed)
    F = np.fft.fft2(rng.standard_normal((h, w)).astype(np.float32))
    fy = np.fft.fftfreq(h)[:, None] * h
    fx = np.fft.fftfreq(w)[None, :] * w
    if rot:
        c, s = np.cos(rot), np.sin(rot)
        fx, fy = c * fx - s * fy, s * fx + c * fy
    f = np.sqrt((fx / aniso[0]) ** 2 + (fy / aniso[1]) ** 2)
    f[0, 0] = 1.0
    amp = f ** (-beta / 2.0)
    amp[f < lo] = 0
    if hi is not None:
        amp *= np.exp(-np.maximum(0, f - hi) ** 2 / (2 * (0.25 * hi) ** 2))
    amp[0, 0] = 0
    n = np.real(np.fft.ifft2(F * amp)).astype(np.float32)
    return (n - n.mean()) / (n.std() + 1e-9)


def blur(img, sigma_px):
    """Wrap-around gaussian blur (FFT), works on HxW or HxWxC."""
    if sigma_px <= 0:
        return img
    h, w = img.shape[:2]
    fy = np.fft.fftfreq(h)[:, None]
    fx = np.fft.fftfreq(w)[None, :]
    g = np.exp(-2 * (np.pi ** 2) * (sigma_px ** 2) * (fx ** 2 + fy ** 2)).astype(np.float32)
    if img.ndim == 2:
        return np.real(np.fft.ifft2(np.fft.fft2(img) * g)).astype(np.float32)
    return np.stack([blur(img[..., i], sigma_px) for i in range(img.shape[2])], -1)


def blur_aniso(img, sx, sy):
    h, w = img.shape[:2]
    fy = np.fft.fftfreq(h)[:, None]
    fx = np.fft.fftfreq(w)[None, :]
    g = np.exp(-2 * (np.pi ** 2) * ((sx * fx) ** 2 + (sy * fy) ** 2)).astype(np.float32)
    if img.ndim == 2:
        return np.real(np.fft.ifft2(np.fft.fft2(img) * g)).astype(np.float32)
    return np.stack([blur_aniso(img[..., i], sx, sy) for i in range(img.shape[2])], -1)


def warp(img, dx, dy):
    """Wrap-around bilinear domain warp by pixel offsets dx, dy (HxW arrays)."""
    h, w = img.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    x = (xx + dx) % w
    y = (yy + dy) % h
    x0 = np.floor(x).astype(np.int32); y0 = np.floor(y).astype(np.int32)
    fx = x - x0; fy = y - y0
    x1 = (x0 + 1) % w; y1 = (y0 + 1) % h
    if img.ndim == 3:
        fx = fx[..., None]; fy = fy[..., None]
    a = img[y0, x0] * (1 - fx) + img[y0, x1] * fx
    b = img[y1, x0] * (1 - fx) + img[y1, x1] * fx
    return a * (1 - fy) + b * fy


def cells(shape, n_cells, seed=0, jitter=0.9):
    """Tileable Worley/Voronoi: returns (F1 distance in px, F2-F1 in px, cell id) for ~n_cells points."""
    h, w = shape
    rng = np.random.default_rng(seed)
    g = max(1, int(round(np.sqrt(n_cells * w / h))))
    gy = max(1, int(round(n_cells / g)))
    cw, ch = w / g, h / gy
    pts = []
    for j in range(gy):
        for i in range(g):
            pts.append(((i + 0.5 + jitter * (rng.random() - 0.5)) * cw, (j + 0.5 + jitter * (rng.random() - 0.5)) * ch))
    pts = np.array(pts, dtype=np.float32)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    f1 = np.full((h, w), 1e9, np.float32); f2 = np.full((h, w), 1e9, np.float32)
    idx = np.zeros((h, w), np.int32)
    for k, (px, py) in enumerate(pts):
        dx = np.abs(xx - px); dx = np.minimum(dx, w - dx)
        dy = np.abs(yy - py); dy = np.minimum(dy, h - dy)
        d = np.sqrt(dx * dx + dy * dy)
        closer = d < f1
        f2 = np.where(closer, f1, np.minimum(f2, d))
        idx = np.where(closer, k, idx)
        f1 = np.where(closer, d, f1)
    return f1, f2 - f1, idx


# ----------------------------------------------------------------------------- height -> maps
def height_to_normal(hm, px_m, strength=1.0, wrap=True):
    """Height (metres) -> OpenGL tangent normal (float, -1..1). Row 0 = top (v=1)."""
    if wrap:
        dx = (np.roll(hm, -1, 1) - np.roll(hm, 1, 1)) / (2 * px_m)
        dv = (np.roll(hm, 1, 0) - np.roll(hm, -1, 0)) / (2 * px_m)   # row-1 is "up"
    else:
        p = np.pad(hm, 1, mode="edge")
        dx = (p[1:-1, 2:] - p[1:-1, :-2]) / (2 * px_m)
        dv = (p[:-2, 1:-1] - p[2:, 1:-1]) / (2 * px_m)
    n = np.stack([-dx * strength, -dv * strength, np.ones_like(hm)], -1)
    return n / np.linalg.norm(n, axis=-1, keepdims=True)


def ao_from_height(hm, px_m, radius_m=0.08, dirs=8, steps=6, strength=1.0, wrap=True):
    """Horizon-based AO estimate from a height field (metres). Returns 0..1 (1 = open)."""
    occl = np.zeros_like(hm)
    rpx = max(2.0, radius_m / px_m)
    src = hm if wrap else np.pad(hm, int(rpx) + 2, mode="edge")
    for k in range(dirs):
        a = 2 * np.pi * k / dirs
        best = np.zeros_like(hm)
        for s in range(1, steps + 1):
            d = rpx * (s / steps) ** 1.5
            ox, oy = int(round(np.cos(a) * d)), int(round(np.sin(a) * d))
            if ox == 0 and oy == 0:
                continue
            sh = np.roll(np.roll(src, oy, 0), ox, 1)
            if not wrap:
                p = int(rpx) + 2
                sh = sh[p:-p, p:-p]
            dist = np.hypot(ox, oy) * px_m
            best = np.maximum(best, (sh - hm) / dist)
        occl += 1 - 1 / np.sqrt(1 + best ** 2)       # sin(horizon angle)
    return np.clip(1 - strength * occl / dirs, 0, 1).astype(np.float32)


def cavity(hm, px_m, r_m=0.01):
    """Positive on ridges/edges, negative in creases (curvature-ish)."""
    s = max(0.7, r_m / px_m)
    return (hm - blur(hm, s)) / (r_m + 1e-9)


# ----------------------------------------------------------------------------- shapes
def raster(size, draw_fn, ss=2, mode="L"):
    """Draw with PIL at ss x supersampling and return float 0..1 array (h,w)."""
    w, h = size
    im = Image.new(mode, (w * ss, h * ss), 0)
    draw_fn(ImageDraw.Draw(im), ss)
    im = im.resize((w, h), Image.LANCZOS)
    return np.asarray(im, dtype=np.float32) / 255.0


def text_mask(text, size_px, box=(512, 512), vertical=False, font=FONT_JP, weight=0):
    """White text on black (float mask), centred. vertical=True stacks characters top-to-bottom."""
    W, H = box
    im = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(im)
    f = ImageFont.truetype(font, size_px) if font else ImageFont.load_default()
    if vertical:
        n = len(text)
        y = (H - n * size_px * 1.05) / 2
        for ch in text:
            bb = d.textbbox((0, 0), ch, font=f)
            d.text(((W - (bb[2] - bb[0])) / 2 - bb[0], y - bb[1] + (size_px - (bb[3] - bb[1])) / 2), ch, fill=255, font=f,
                   stroke_width=weight, stroke_fill=255)
            y += size_px * 1.05
    else:
        bb = d.textbbox((0, 0), text, font=f, stroke_width=weight)
        d.text(((W - (bb[2] - bb[0])) / 2 - bb[0], (H - (bb[3] - bb[1])) / 2 - bb[1]), text, fill=255, font=f,
               stroke_width=weight, stroke_fill=255)
    return np.asarray(im, dtype=np.float32) / 255.0


# ----------------------------------------------------------------------------- resampling / io
def down(img, f):
    """Box downsample by integer factor f."""
    if f == 1:
        return img
    h, w = img.shape[:2]
    h2, w2 = h // f, w // f
    img = img[:h2 * f, :w2 * f]
    if img.ndim == 2:
        return img.reshape(h2, f, w2, f).mean((1, 3))
    return img.reshape(h2, f, w2, f, img.shape[2]).mean((1, 3))


def resize(img, wh):
    """High-quality resize of float image (0..1) to (w, h) via PIL per channel."""
    w, h = wh
    if img.shape[1] == w and img.shape[0] == h:
        return img
    chans = [img] if img.ndim == 2 else [img[..., i] for i in range(img.shape[2])]
    out = [np.asarray(Image.fromarray(c.astype(np.float32), "F").resize((w, h), Image.LANCZOS)) for c in chans]
    return out[0] if img.ndim == 2 else np.stack(out, -1)


def renorm(n):
    """n: -1..1 normal array -> renormalised."""
    return n / np.maximum(1e-6, np.linalg.norm(n, axis=-1, keepdims=True))


def to8(img):
    return (np.clip(img, 0, 1) * 255 + 0.5).astype(np.uint8)


def save_img(path, img, quality=90):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    a = to8(img)
    if path.lower().endswith((".jpg", ".jpeg")):
        Image.fromarray(a).save(path, quality=quality, subsampling=0 if quality >= 90 else 2, optimize=True)
    else:
        Image.fromarray(a).save(path, optimize=True)
    return os.path.getsize(path)


def load_img(path):
    return np.asarray(Image.open(path), dtype=np.float32) / 255.0


# ----------------------------------------------------------------------------- set writer
LIB_JSON_BL = os.path.join(TEX_BL, "library.json")
LIB_JSON_WEB = os.path.join(TEX_WEB, "library.json")


def _lib_update(path, name, entry):
    lib = {}
    if os.path.exists(path):
        try:
            lib = json.load(open(path))
        except Exception:
            lib = {}
    lib.setdefault("conventions", {
        "albedo": "sRGB, no lighting baked in (except deep-interior darkness on facade modules, see docs)",
        "normal": "tangent space, OpenGL (+Y up / green = up). Flip G for DirectX.",
        "orm": "R = ambient occlusion, G = roughness, B = metalness (linear)",
        "emit": "greyscale emissive mask (linear); multiply by a warm light colour at night",
        "units": "size_m = physical width x height covered by one texture repeat (metres)",
    })
    lib.setdefault("sets", {})[name] = entry
    lib["sets"] = dict(sorted(lib["sets"].items()))
    json.dump(lib, open(path, "w"), indent=1, ensure_ascii=False)


def write_set(name, albedo, normal, ao, rough, metal=None, emit=None, alpha=None, size_m=(1.0, 1.0), kind="tileable",
              category="misc", tags=(), notes="", res_bl=None, res_web=None, extra=None, web_quality=82):
    """Write a texture set (Blender + web). Inputs are float arrays at the generation resolution.

    albedo: HxWx3 sRGB 0..1 ; normal: HxWx3 in -1..1 (OpenGL) ; ao/rough/metal/emit: HxW 0..1 ; alpha: HxW or None.
    """
    h, w = albedo.shape[:2]
    res_bl = res_bl or (w, h)
    res_web = res_web or (max(1, w // 2), max(1, h // 2))
    metal = np.zeros((h, w), np.float32) if metal is None else metal
    orm = np.stack([ao, rough, metal], -1)
    entry = {"kind": kind, "category": category, "size_m": [round(float(size_m[0]), 4), round(float(size_m[1]), 4)],
             "tags": list(tags), "notes": notes, "files": {}, "resolution": list(res_bl)}
    went = dict(entry); went["files"] = {}; went["resolution"] = list(res_web)
    if extra:
        entry.update(extra); went.update(extra)
    sizes = {}
    for tgt, res, d, e in (("bl", res_bl, TEX_BL, entry), ("web", res_web, TEX_WEB, went)):
        alb = resize(albedo, res)
        nrm = renorm(resize(normal, res))
        ormr = resize(orm, res)
        q_alb = 92 if tgt == "bl" else web_quality
        if alpha is not None:
            a = resize(alpha, res)
            rgba = np.concatenate([alb, a[..., None]], -1)
            fn = "%s_albedo.png" % name
            Image.fromarray(to8(rgba), "RGBA").save(os.path.join(d, fn), optimize=True)
            sizes[(tgt, "albedo")] = os.path.getsize(os.path.join(d, fn))
        else:
            fn = "%s_albedo.jpg" % name
            sizes[(tgt, "albedo")] = save_img(os.path.join(d, fn), alb, q_alb)
        e["files"]["albedo"] = fn
        fn = "%s_normal.jpg" % name
        sizes[(tgt, "normal")] = save_img(os.path.join(d, fn), nrm * 0.5 + 0.5, 95 if tgt == "bl" else web_quality)
        e["files"]["normal"] = fn
        fn = "%s_orm.jpg" % name
        sizes[(tgt, "orm")] = save_img(os.path.join(d, fn), ormr, 92 if tgt == "bl" else web_quality)
        e["files"]["orm"] = fn
        if emit is not None:
            fn = "%s_emit.jpg" % name
            er = resize(emit, (max(1, res[0] // 2), max(1, res[1] // 2)))
            sizes[(tgt, "emit")] = save_img(os.path.join(d, fn), np.repeat(er[..., None], 3, -1), 90)
            e["files"]["emit"] = fn
    _lib_update(LIB_JSON_BL, name, entry)
    _lib_update(LIB_JSON_WEB, name, went)
    tot_web = sum(v for (t, _), v in sizes.items() if t == "web")
    print("  set %-28s bl %s web %s  web %.0f KB" % (name, res_bl, res_web, tot_web / 1024))
    return entry


def finish_height(albedo, hm, rough, size_m, ao_radius_m=0.05, ao_strength=1.0, nstrength=1.0, metal=None,
                  ao_extra=None, cavity_dark=0.0, **kw):
    """Common tail for numpy height-field materials: normal + AO from height, then write_set."""
    h, w = hm.shape
    px = size_m[0] / w
    nrm = height_to_normal(hm, px, nstrength)
    ao = ao_from_height(hm, px, ao_radius_m, strength=ao_strength)
    if ao_extra is not None:
        ao = ao * ao_extra
    if cavity_dark:
        albedo = albedo * (1 - cavity_dark * (1 - ao))[..., None]
    return write_set(albedo=np.clip(albedo, 0, 1), normal=nrm, ao=ao, rough=np.clip(rough, 0.02, 1), metal=metal,
                     size_m=size_m, **kw)


def preview(paths_or_arrays, out, cols=4, cell=384):
    """Contact sheet for quick visual checks (scratch only)."""
    ims = []
    for p in paths_or_arrays:
        a = load_img(p) if isinstance(p, str) else p
        if a.ndim == 2:
            a = np.repeat(a[..., None], 3, -1)
        a = a[..., :3]
        im = Image.fromarray(to8(a)); im.thumbnail((cell, cell))
        ims.append(im)
    rows = (len(ims) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * cell, rows * cell), (40, 40, 40))
    for i, im in enumerate(ims):
        sheet.paste(im, ((i % cols) * cell, (i // cols) * cell))
    sheet.save(out, quality=88)
    return out
