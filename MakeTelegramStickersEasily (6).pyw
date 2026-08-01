#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Make Telegram Stickers Easily  (v7 "Glass")
Gercek yari saydam cam paneller (arka plan kompozit ornekleme), aurora arkaplan,
60fps tween motoru, katmanli tema popover'i, koyu/acik gorunum, toast bildirimleri.
Motor ayni: WebM / VP9 / 512 sabit / <=256KB / 0.3-3sn / sessiz, export orijinalden.
"""

import os
import sys
import io
import json
import math
import time
import queue
import atexit
import shutil
import tempfile
import importlib
import threading
import subprocess
import tkinter as tk
import tkinter.font as tkfont
from collections import OrderedDict
from tkinter import filedialog

CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
CFG_PATH = os.path.join(os.path.expanduser("~"), ".telegram_sticker_maker.json")


# ============================================================
#  Otomatik bagimlilik kurulumu (bir kere)
# ============================================================
def pip_install(pkg):
    try:
        subprocess.run([sys.executable, "-m", "pip", "install", "--quiet",
                        "--disable-pip-version-check", pkg],
                       creationflags=CREATE_NO_WINDOW, timeout=420,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        importlib.invalidate_caches()
        return True
    except Exception:
        return False


def _splash_install(pkgs):
    installed, sp = [], None
    try:
        sp = tk.Tk()
        sp.title("Make Telegram Stickers Easily")
        sp.configure(bg="#0C0D14")
        sp.geometry("380x130")
        sp.resizable(False, False)
        tk.Label(sp, text="MAKE TELEGRAM STICKERS EASILY", bg="#0C0D14", fg="#8B7BFF",
                 font=("Segoe UI", 11, "bold")).pack(pady=(22, 4))
        lbl = tk.Label(sp, text="Downloading required components...", bg="#0C0D14",
                       fg="#F2F3FA", font=("Segoe UI", 9))
        lbl.pack()
        tk.Label(sp, text="(only on first run)", bg="#0C0D14",
                 fg="#8A8FA8", font=("Segoe UI", 8)).pack(pady=(2, 0))
        sp.update()
        for pkg in pkgs:
            lbl.config(text=f"downloading: {pkg}")
            sp.update()
            if pip_install(pkg):
                installed.append(pkg)
    except Exception:
        for pkg in pkgs:
            if pip_install(pkg):
                installed.append(pkg)
    finally:
        if sp is not None:
            try:
                sp.destroy()
            except Exception:
                pass
    return installed


def ensure_deps():
    need = []
    try:
        import tkinterdnd2  # noqa: F401
    except Exception:
        need.append("tkinterdnd2")
    try:
        from PIL import Image, ImageTk  # noqa: F401
    except Exception:
        need.append("pillow")
    if need:
        return _splash_install(need)
    return []


INSTALLED = ensure_deps()

try:
    from PIL import (Image, ImageTk, ImageDraw, ImageFilter,
                     ImageEnhance, ImageChops)
    HAS_PIL = True
except Exception:
    HAS_PIL = False

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    try:
        from tkinterdnd2 import COPY as DND_COPY
    except Exception:
        DND_COPY = "copy"
    HAS_DND = True
except Exception:
    HAS_DND = False
    DND_COPY = "copy"



SIZE_LIMIT = 256 * 1000
MAX_DUR = 2.99
MIN_SEL = 0.3
RES = 512
MAX_PREV_FRAMES = 240
VIDEO_EXT = (".mov", ".mp4", ".webm", ".mkv", ".avi", ".m4v", ".gif")
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
STATIC_LIMIT = 512 * 1000


def is_image(path):
    return str(path).lower().endswith(IMAGE_EXT)

_TMP_DIRS = []


def _cleanup_tmp():
    for d in _TMP_DIRS:
        shutil.rmtree(d, ignore_errors=True)


atexit.register(_cleanup_tmp)


# ============================================================
#  FFMPEG motoru (degismedi)
# ============================================================
def find_bin(name):
    p = shutil.which(name)
    if p:
        return p
    for base in (r"C:\ffmpeg\bin", r"C:\Program Files\ffmpeg\bin"):
        cand = os.path.join(base, name + (".exe" if sys.platform == "win32" else ""))
        if os.path.exists(cand):
            return cand
    return None


FFMPEG = find_bin("ffmpeg")
FFPROBE = find_bin("ffprobe")

if FFMPEG is None:
    try:
        import imageio_ffmpeg
    except Exception:
        if pip_install("imageio-ffmpeg"):
            INSTALLED.append("imageio-ffmpeg")
        try:
            import imageio_ffmpeg
        except Exception:
            imageio_ffmpeg = None
    try:
        if imageio_ffmpeg:
            FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass


def run(cmd):
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          creationflags=CREATE_NO_WINDOW, text=True, errors="ignore")


def probe(path):
    dur, alpha = None, False
    if FFPROBE:
        try:
            r = run([FFPROBE, "-v", "error", "-select_streams", "v:0",
                     "-show_entries", "stream=pix_fmt,duration",
                     "-show_entries", "format=duration", "-of", "json", path])
            data = json.loads(r.stdout or "{}")
            st = (data.get("streams") or [{}])[0]
            pix = (st.get("pix_fmt") or "").lower()
            alpha = any(k in pix for k in ("yuva", "rgba", "argb", "bgra", "pal8", "ya8"))
            d = st.get("duration") or data.get("format", {}).get("duration")
            if d:
                dur = float(d)
        except Exception:
            pass
    if dur is None and FFMPEG:
        try:
            import re
            r = run([FFMPEG, "-i", path])
            m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", r.stdout or "")
            if m:
                dur = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
        except Exception:
            pass
    return dur, alpha


def extract_preview(src, tmpdir):
    dur, _ = probe(src)
    if dur and dur > 0:
        pfps = max(2.0, min(12.0, MAX_PREV_FRAMES / dur))
    else:
        pfps = 10.0
    pat = os.path.join(tmpdir, "f_%04d.png")
    cmd = [FFMPEG, "-y", "-i", src, "-an",
           "-vf", f"fps={pfps:.4f},scale=480:300:force_original_aspect_ratio=decrease",
           "-frames:v", str(MAX_PREV_FRAMES), pat]
    r = run(cmd)
    n = len([f for f in os.listdir(tmpdir) if f.startswith("f_")])
    if r.returncode != 0 and n == 0:
        return 0, pfps, dur
    if not dur or dur <= 0:
        dur = n / pfps
    return n, pfps, dur


def fmt_t(t):
    if t is None:
        return "?"
    if t >= 60:
        m = int(t // 60)
        return f"{m}:{t - m * 60:04.1f}"
    return f"{t:.1f}s"


def detect_chroma(png_path):
    """Onizleme karesinin kenarlarini tarar; yesil/mavi ekran varsa
    anahtar rengi (RRGGBB hex) doner, yoksa None."""
    try:
        img = tk.PhotoImage(file=png_path)
    except Exception:
        return None
    w, h = img.width(), img.height()
    if w < 6 or h < 6:
        return None

    def px(x, y):
        v = img.get(x, y)
        if isinstance(v, str):
            v = tuple(int(a) for a in v.split())
        return v[0], v[1], v[2]

    coords = []
    sx, sy = max(1, w // 60), max(1, h // 60)
    for x in range(0, w, sx):
        coords.append((x, 0))
        coords.append((x, h - 1))
    for y in range(0, h, sy):
        coords.append((0, y))
        coords.append((w - 1, y))
    gc = bc = 0
    gs = [0, 0, 0]
    bs = [0, 0, 0]
    tot = 0
    for (x, y) in coords:
        try:
            r, g, b = px(x, y)
        except Exception:
            continue
        tot += 1
        if g >= 60 and g > r * 1.25 and g > b * 1.15:
            gc += 1
            gs[0] += r
            gs[1] += g
            gs[2] += b
        elif b >= 60 and b > r * 1.25 and b > g * 1.10:
            bc += 1
            bs[0] += r
            bs[1] += g
            bs[2] += b
    if tot == 0:
        return None
    if gc / tot >= 0.30:
        c = [s // gc for s in gs]
        return "%02X%02X%02X" % (c[0], c[1], c[2])
    if bc / tot >= 0.30:
        c = [s // bc for s in bs]
        return "%02X%02X%02X" % (c[0], c[1], c[2])
    return None


def build_cmd(src, out, alpha, crf, fps, dur, dur_mode, start, length, crop=None, chroma=None):
    pix = "yuva420p" if (alpha or chroma) else "yuv420p"
    if crop:
        cf = max(0.05, min(1.0, crop["cf"]))
        cx = min(1.0, max(0.0, crop["cx"]))
        cy = min(1.0, max(0.0, crop["cy"]))
        S = f"min(iw\\,ih)*{cf:.4f}"
        X = f"clip(iw*{cx:.4f}-({S})/2\\,0\\,iw-{S})"
        Y = f"clip(ih*{cy:.4f}-({S})/2\\,0\\,ih-{S})"
        geo = f"crop={S}:{S}:{X}:{Y},scale={RES}:{RES}:flags=lanczos"
    else:
        geo = f"scale='if(gt(a,1),{RES},-2)':'if(gt(a,1),-2,{RES})':flags=lanczos"
    key = ""
    if chroma:
        col = chroma["c"]
        sim = max(0.04, min(0.40, chroma.get("sim", 0.16)))
        blend = round(max(0.03, sim * 0.6), 3)
        key = f"chromakey=0x{col}:{sim:.3f}:{blend},"
        r0, g0, b0 = int(col[0:2], 16), int(col[2:4], 16), int(col[4:6], 16)
        if g0 > r0 and g0 > b0:
            key += "despill=type=green,"
        elif b0 > r0 and b0 > g0:
            key += "despill=type=blue,"
    vf = key + geo
    in_args, t_args, speed = [], [], ""
    if dur_mode == "fit" and dur and dur > MAX_DUR:
        speed = f"setpts={MAX_DUR / dur:.4f}*PTS,"
    elif dur_mode == "custom":
        in_args = ["-ss", str(round(max(0.0, start), 3))]
        t_args = ["-t", str(round(max(MIN_SEL, length), 3))]
    else:
        t_args = ["-t", str(MAX_DUR)]
    vf_full = f"{speed}{vf},fps={fps},format={pix}"
    return [FFMPEG, "-y", *in_args, "-i", src, "-an", *t_args,
            "-c:v", "libvpx-vp9", "-vf", vf_full,
            "-b:v", "0", "-crf", str(crf),
            "-deadline", "good", "-cpu-used", "2",
            "-pix_fmt", pix, out]


def free_path(path):
    """dosya varsa _2, _3 ... ekleyerek bos isim bulur."""
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    i = 2
    while os.path.exists(f"{base}_{i}{ext}"):
        i += 1
    return f"{base}_{i}{ext}"


def convert(src, cfg, log):
    out_dir = cfg["out_dir"] or os.path.dirname(src)
    os.makedirs(out_dir, exist_ok=True)
    name = os.path.splitext(os.path.basename(src))[0]
    out = os.path.join(out_dir, name + "_sticker.webm")
    if os.path.exists(out) and cfg.get("on_conflict") == "rename":
        out = free_path(out)
        log(f"  name conflict → will save as {os.path.basename(out)}")
    dur, alpha_auto = probe(src)
    alpha = alpha_auto if cfg["alpha"] == "auto" else (cfg["alpha"] == "alpha")
    chroma = cfg.get("chroma")
    if chroma:
        alpha = True
    start, length = cfg["start"], cfg["length"]
    if cfg["dur_mode"] == "custom" and dur:
        start = min(start, max(0.0, dur - MIN_SEL))
        length = max(MIN_SEL, min(length, dur - start, MAX_DUR))
    extra = ""
    if chroma:
        extra += f" | chroma #{chroma['c']} (hassasiyet {chroma.get('sim', 0.16):.2f})"
    if cfg.get("crop"):
        extra += " | square crop"
    if cfg["dur_mode"] == "custom":
        log(f"  {'transparent' if alpha else 'opaque'} | trim {start:.1f}s → {start + length:.1f}s "
            f"({length:.1f}s)" + extra)
    else:
        log(f"  duration {fmt_t(dur)} | {'transparent' if alpha else 'opaque'} | {cfg['dur_mode']}" + extra)
    plan = [(30, [28, 34, 40, 46, 52, 58]),
            (24, [40, 48, 56, 62]),
            (18, [50, 58, 63])]
    fps_sel = str(cfg.get("fps", "auto"))
    if fps_sel != "auto":
        f = int(fps_sel)
        plan = [(f, [26, 32, 38, 44, 50, 56, 60, 63])]
        log(f"  fps sabit: {f}")
    for fps, crfs in plan:
        for crf in crfs:
            cmd = build_cmd(src, out, alpha, crf, fps, dur, cfg["dur_mode"],
                            start, length, cfg.get("crop"), chroma)
            r = run(cmd)
            if r.returncode != 0 or not os.path.exists(out):
                tail = "\n".join((r.stdout or "").strip().splitlines()[-4:])
                log("  ✗ ffmpeg error:\n    " + tail.replace("\n", "\n    "))
                return False, None
            kb = os.path.getsize(out) / 1000
            log(f"  crf {crf} @ {fps}fps -> {kb:.0f} KB")
            if os.path.getsize(out) <= SIZE_LIMIT:
                return True, out
    log("  ⚠ couldn't get under 256KB, kept last output")
    return True, out


def convert_image(src, cfg, log):
    """PNG/JPG -> 512px statik WebP sticker (chroma + kirpma destekli)."""
    out_dir = cfg["out_dir"] or os.path.dirname(src)
    os.makedirs(out_dir, exist_ok=True)
    name = os.path.splitext(os.path.basename(src))[0]
    out = os.path.join(out_dir, name + "_sticker.webp")
    if os.path.exists(out) and cfg.get("on_conflict") == "rename":
        out = free_path(out)
        log(f"  name conflict → will save as {os.path.basename(out)}")
    if not HAS_PIL:
        log("  ✗ Pillow required for static sticker")
        return False, None
    try:
        im = Image.open(src).convert("RGBA")
    except Exception as e:
        log(f"  ✗ couldn't open image: {e}")
        return False, None

    ch = cfg.get("chroma")
    if ch:
        ramp = chroma_alpha(im.convert("RGB"), ch["c"], ch.get("sim", 0.16))
        im.putalpha(ImageChops.multiply(im.split()[3], ramp))

    crop = cfg.get("crop")
    w, h = im.size
    if crop:
        side = max(2, int(min(w, h) * max(0.05, min(1.0, crop["cf"]))))
        cx, cy = int(w * crop["cx"]), int(h * crop["cy"])
        x1 = max(0, min(w - side, cx - side // 2))
        y1 = max(0, min(h - side, cy - side // 2))
        im = im.crop((x1, y1, x1 + side, y1 + side)).resize((RES, RES), Image.LANCZOS)
    else:
        sc = RES / max(im.size)
        im = im.resize((max(1, int(im.width * sc)),
                        max(1, int(im.height * sc))), Image.LANCZOS)

    has_alpha = im.getextrema()[3][0] < 255
    if cfg.get("alpha") == "opaque" or not has_alpha:
        im = im.convert("RGB")
        has_alpha = False
    log(f"  🖼 static | {im.width}×{im.height} | {'transparent' if has_alpha else 'opaque'}"
        + (" | chroma" if ch else "") + (" | square crop" if crop else ""))
    for q in (95, 90, 85, 80, 70, 60, 50):
        im.save(out, "WEBP", quality=q, method=4)
        kb = os.path.getsize(out) / 1000
        log(f"  q{q} -> {kb:.0f} KB")
        if os.path.getsize(out) <= STATIC_LIMIT:
            return True, out
    log("  ⚠ couldn't get under 512KB, kept last output")
    return True, out


# ============================================================
#  Renk / kompozit matematigi (saf, test edilebilir)
# ============================================================
def hx(rgb):
    return "#%02x%02x%02x" % (max(0, min(255, int(rgb[0]))),
                              max(0, min(255, int(rgb[1]))),
                              max(0, min(255, int(rgb[2]))))


def rgb(h):
    h = h.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def mix(a, b, t):
    return (a[0] + (b[0] - a[0]) * t,
            a[1] + (b[1] - a[1]) * t,
            a[2] + (b[2] - a[2]) * t)


def _hashn(x, y):
    """Deterministik kucuk gurultu (-7.5..7.5), banding kirar, buz dokusu verir."""
    h = (x * 374761393 + y * 668265263) & 0xFFFFFFFF
    h = ((h ^ (h >> 13)) * 1274126177) & 0xFFFFFFFF
    return ((h >> 16) & 15) - 7.5


def _bg_rows(lw, lh, g1, g2, orbs, vign=0.16, noise=0.35):
    """Dusuk cozunurluk arkaplan: dikey degrade + gauss aurora orblari
    + vinyet + ince gurultu."""
    rows = []
    pre = []
    for (ox, oy, orr, col, inten) in orbs:
        sig2 = 2.0 * (orr * max(lw, lh)) ** 2
        pre.append((ox * lw, oy * lh, sig2, col, inten))
    cxm, cym = (lw - 1) / 2.0, (lh - 1) / 2.0
    for y in range(lh):
        t = y / max(1, lh - 1)
        base = mix(g1, g2, t)
        ny = ((y - cym) / max(1.0, cym)) ** 2
        row = []
        for x in range(lw):
            c = base
            for (px, py, sig2, col, inten) in pre:
                dx, dy = x - px, y - py
                f = inten * math.exp(-(dx * dx + dy * dy) / sig2)
                if f > 0.004:
                    c = mix(c, col, min(1.0, f))
            if vign:
                nx = ((x - cxm) / max(1.0, cxm)) ** 2
                v = 1.0 - vign * min(1.0, (nx + ny) * 0.7)
                c = (c[0] * v, c[1] * v, c[2] * v)
            if noise:
                n = _hashn(x, y) * noise
                c = (c[0] + n, c[1] + n, c[2] + n)
            row.append(c)
        rows.append(row)
    return rows


def _apply_shadows(rows, rects, sc, k=0.36, sig_px=18.0, dy_px=6.0):
    """Panellerin altina yumusak golge piser (rows'u yerinde koyultur).
    rects: tam cozunurluk (x,y,w,h) listesi."""
    if not rows or not rects:
        return rows
    lh = len(rows)
    lw = len(rows[0])
    sig = max(1.0, sig_px / sc)
    inv2s2 = 1.0 / (2.0 * sig * sig)
    reach = int(sig * 3) + 1
    for (X, Y, W, H) in rects:
        rx1 = X / sc
        ry1 = (Y + dy_px) / sc
        rx2 = (X + W) / sc
        ry2 = (Y + H + dy_px) / sc
        x_lo = max(0, int(rx1) - reach)
        x_hi = min(lw - 1, int(rx2) + reach)
        y_lo = max(0, int(ry1) - reach)
        y_hi = min(lh - 1, int(ry2) + reach)
        for y in range(y_lo, y_hi + 1):
            dy = max(ry1 - y, 0.0, y - ry2)
            row = rows[y]
            for x in range(x_lo, x_hi + 1):
                dx = max(rx1 - x, 0.0, x - rx2)
                d2 = dx * dx + dy * dy
                f = k * math.exp(-d2 * inv2s2)
                if f > 0.01:
                    m = 1.0 - f
                    c = row[x]
                    row[x] = (c[0] * m, c[1] * m, c[2] * m)
    return rows


def _in_rrect(x, y, w, h, r):
    if r <= 0:
        return True
    if x < r and y < r:
        return (x - r) ** 2 + (y - r) ** 2 <= r * r
    if x >= w - r and y < r:
        return (x - (w - r - 1)) ** 2 + (y - r) ** 2 <= r * r
    if x < r and y >= h - r:
        return (x - r) ** 2 + (y - (h - r - 1)) ** 2 <= r * r
    if x >= w - r and y >= h - r:
        return (x - (w - r - 1)) ** 2 + (y - (h - r - 1)) ** 2 <= r * r
    return True


def _glass_rows(bg_rows, x0, y0, w, h, tint, ta, radius, border_rgb, border_a, hil_a):
    """Panelin dusuk cozunurluk cam goruntusu: arkaplani ornekle, tint bindir,
    buz gurultusu, ustte parlak altta sonuk kenar cizgisi, ust ic parlamasi;
    kose disi = ham arkaplan (gorunmez kose)."""
    lh_bg = len(bg_rows)
    lw_bg = len(bg_rows[0]) if lh_bg else 0
    out = []
    for y in range(h):
        sy = min(lh_bg - 1, max(0, y0 + y))
        yfrac = y / max(1, h - 1)
        edge_a = min(1.0, border_a * (1.45 - 0.9 * yfrac))
        row = []
        for x in range(w):
            sx = min(lw_bg - 1, max(0, x0 + x))
            base = bg_rows[sy][sx]
            if _in_rrect(x, y, w, h, radius):
                c = mix(base, tint, ta)
                n = _hashn(x0 + x, y0 + y) * 0.55
                c = (c[0] + n, c[1] + n, c[2] + n)
                edge = (x == 0 or y == 0 or x == w - 1 or y == h - 1
                        or not _in_rrect(x - 1, y, w, h, radius)
                        or not _in_rrect(x + 1, y, w, h, radius)
                        or not _in_rrect(x, y - 1, w, h, radius)
                        or not _in_rrect(x, y + 1, w, h, radius))
                if edge:
                    c = mix(c, border_rgb, edge_a)
                elif y == 1 and _in_rrect(x, 1, w, h, radius):
                    c = mix(c, (255, 255, 255), hil_a)
            else:
                c = base
            row.append(hx(c))
        out.append("{" + " ".join(row) + "}")
    return out


# ============================================================
#  Tema / gorunum
# ============================================================
THEMES = {
    "Midnight": dict(accent="#7C6CFF", accent2="#A78BFA",
                   d_g=("#1A1430", "#0A0713"),
                   d_orbs=[(0.16, 0.10, 0.34, rgb("#7C6CFF"), 0.82),
                           (0.88, 0.20, 0.28, rgb("#5B3FBF"), 0.60),
                           (0.55, 1.00, 0.36, rgb("#241A54"), 0.64)],
                   l_g=("#F6F4FF", "#ECE8FA"),
                   l_orbs=[(0.16, 0.10, 0.34, rgb("#E0D8FF"), 0.55),
                           (0.88, 0.20, 0.28, rgb("#EADFFB"), 0.45),
                           (0.55, 1.00, 0.36, rgb("#E7E0FA"), 0.42)]),
    "Classic":   dict(accent="#0A84FF", accent2="#30D158",
                   d_g=("#141A33", "#070A15"),
                   d_orbs=[(0.16, 0.10, 0.34, rgb("#1E63FF"), 0.85),
                           (0.88, 0.20, 0.28, rgb("#6D5BFF"), 0.60),
                           (0.55, 1.00, 0.36, rgb("#0FB5D9"), 0.55)],
                   l_g=("#FAFBFF", "#E9EDF9"),
                   l_orbs=[(0.16, 0.10, 0.34, rgb("#CFE0FF"), 0.60),
                           (0.88, 0.20, 0.28, rgb("#E0DBFF"), 0.48),
                           (0.55, 1.00, 0.36, rgb("#D2EEF6"), 0.45)]),
    "Gray":    dict(accent="#A6AEBF", accent2="#7C8899",
                   d_g=("#23252C", "#0B0C0F"),
                   d_orbs=[(0.14, 0.10, 0.30, rgb("#4A4F5C"), 0.80),
                           (0.90, 0.24, 0.26, rgb("#39404C"), 0.60),
                           (0.55, 0.98, 0.34, rgb("#2C3038"), 0.66)],
                   l_g=("#FCFCFD", "#EBECEF"),
                   l_orbs=[(0.14, 0.10, 0.30, rgb("#E2E4E9"), 0.55),
                           (0.90, 0.24, 0.26, rgb("#DFE2E7"), 0.45),
                           (0.55, 0.98, 0.34, rgb("#E6E8EC"), 0.42)]),
    "Purple":    dict(accent="#8B7BFF", accent2="#22D3EE",
                   d_g=("#1A1B38", "#080A16"),
                   d_orbs=[(0.14, 0.10, 0.30, rgb("#6D5BFF"), 0.85),
                           (0.90, 0.24, 0.26, rgb("#12C7E8"), 0.62),
                           (0.55, 0.98, 0.34, rgb("#4A39B8"), 0.70)],
                   l_g=("#FBFBFE", "#EDEEF6"),
                   l_orbs=[(0.14, 0.10, 0.30, rgb("#DED8FF"), 0.55),
                           (0.90, 0.24, 0.26, rgb("#D6F1F8"), 0.45),
                           (0.55, 0.98, 0.34, rgb("#E6E2FF"), 0.42)]),
    "Emerald": dict(accent="#34D399", accent2="#38BDF8",
                   d_g=("#0E2A20", "#050D0E"),
                   d_orbs=[(0.12, 0.12, 0.30, rgb("#12B87F"), 0.85),
                           (0.90, 0.22, 0.26, rgb("#0F8FC0"), 0.62),
                           (0.55, 0.98, 0.34, rgb("#11785A"), 0.70)],
                   l_g=("#FAFDFB", "#EAF3EE"),
                   l_orbs=[(0.12, 0.12, 0.30, rgb("#D8F5E9"), 0.55),
                           (0.90, 0.22, 0.26, rgb("#DDF0FA"), 0.45),
                           (0.55, 0.98, 0.34, rgb("#E2F6EC"), 0.42)]),
    "Gold":  dict(accent="#F5C451", accent2="#4C7EF3",
                   d_g=("#12121A", "#07070C"),
                   d_orbs=[(0.14, 0.10, 0.30, rgb("#C08F1A"), 0.80),
                           (0.90, 0.24, 0.26, rgb("#3A66CC"), 0.62),
                           (0.55, 0.98, 0.34, rgb("#7A5D16"), 0.66)],
                   l_g=("#FDFBF6", "#F2EDE2"),
                   l_orbs=[(0.14, 0.10, 0.30, rgb("#F8ECCB"), 0.55),
                           (0.90, 0.24, 0.26, rgb("#DEE6FA"), 0.42),
                           (0.55, 0.98, 0.34, rgb("#F5EBD3"), 0.42)]),
    "Fire":   dict(accent="#FB7185", accent2="#FBBF24",
                   d_g=("#190E13", "#0A0507"),
                   d_orbs=[(0.14, 0.10, 0.30, rgb("#D64066"), 0.82),
                           (0.90, 0.24, 0.26, rgb("#CE8C10"), 0.62),
                           (0.55, 0.98, 0.34, rgb("#932F46"), 0.70)],
                   l_g=("#FEFAFB", "#F4E9EB"),
                   l_orbs=[(0.14, 0.10, 0.30, rgb("#FCDDE3"), 0.55),
                           (0.90, 0.24, 0.26, rgb("#FAEED3"), 0.45),
                           (0.55, 0.98, 0.34, rgb("#FAE3E7"), 0.45)]),
}
THEME_ORDER = ["Midnight", "Classic", "Gray", "Purple", "Emerald", "Gold", "Fire"]

MODES = {
    "dark": dict(txt="#ECE9F8", muted="#8C86AD", ok="#43D9B0", err="#FF6B8A",
                 tint=(84, 78, 128), ta=0.32, tint2=(108, 100, 160), ta2=0.42,
                 border=(255, 255, 255), border_a=0.15, hil_a=0.22,
                 dim="#000000"),
    "light": dict(txt="#1B2030", muted="#5D6880", ok="#0E9F6E", err="#E5484D",
                  tint=(255, 255, 255), ta=0.52, tint2=(255, 255, 255), ta2=0.70,
                  border=(255, 255, 255), border_a=0.75, hil_a=0.60,
                  dim="#223"),
}


def luminance(h):
    r, g, b = rgb(h)
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255.0


# ============================================================
#  PIL tabanli puruzsuz kompozit (antialiased, gercek blur)
# ============================================================
SS = 4          # supersample katsayisi (yuvarlak koseler icin)
_MASK_CACHE = {}
_PILL_CACHE = {}
_NOISE = {}


def rounded_mask(w, h, r):
    """Antialiased yuvarlak dikdortgen maskesi (L modu)."""
    key = (w, h, r)
    m = _MASK_CACHE.get(key)
    if m is not None:
        return m
    big = Image.new("L", (w * SS, h * SS), 0)
    d = ImageDraw.Draw(big)
    d.rounded_rectangle((0, 0, w * SS - 1, h * SS - 1), radius=r * SS, fill=255)
    m = big.resize((w, h), Image.LANCZOS)
    if len(_MASK_CACHE) > 80:
        _MASK_CACHE.clear()
    _MASK_CACHE[key] = m
    return m


def noise_layer(w, h, amp):
    """Ince gren (banding kirici). Tek seferlik uretilip yeniden kullanilir."""
    key = (w, h, round(amp, 3))
    n = _NOISE.get(key)
    if n is not None:
        return n
    import random
    rnd = random.Random(7)
    data = bytes(128 + int(rnd.uniform(-amp, amp) * 255) for _ in range(w * h))
    n = Image.frombytes("L", (w, h), data)
    if len(_NOISE) > 6:
        _NOISE.clear()
    _NOISE[key] = n
    return n


def make_backdrop(W, H, g1, g2, orbs, vign=0.20, mode="dark"):
    """Tamamen puruzsuz aurora arkaplan: kucuk uret, LANCZOS ile buyut."""
    sw, sh = max(4, W // 8), max(4, H // 8)
    base = Image.new("RGB", (sw, sh))
    px = base.load()
    for y in range(sh):
        c = mix(g1, g2, y / max(1, sh - 1))
        c = (int(c[0]), int(c[1]), int(c[2]))
        for x in range(sw):
            px[x, y] = c
    # orblar: her biri radial gradient, blur ile eritilir
    for (ox, oy, orr, col, inten) in orbs:
        rad = int(orr * max(sw, sh) * 1.8)
        if rad < 2:
            continue
        layer = Image.new("L", (sw, sh), 0)
        d = ImageDraw.Draw(layer)
        cx, cy = ox * sw, oy * sh
        d.ellipse((cx - rad, cy - rad, cx + rad, cy + rad),
                  fill=int(255 * min(1.0, inten)))
        layer = layer.filter(ImageFilter.GaussianBlur(rad * 0.55))
        base = Image.composite(Image.new("RGB", (sw, sh),
                                         (int(col[0]), int(col[1]), int(col[2]))),
                               base, layer)
    base = base.filter(ImageFilter.GaussianBlur(1.2))
    img = base.resize((W, H), Image.LANCZOS)

    if vign:
        v = Image.new("L", (max(4, W // 8), max(4, H // 8)), 0)
        dv = ImageDraw.Draw(v)
        pad = int(min(v.size) * 0.05)
        dv.ellipse((-pad, -pad, v.size[0] + pad, v.size[1] + pad), fill=255)
        v = v.filter(ImageFilter.GaussianBlur(min(v.size) * 0.18)).resize((W, H), Image.LANCZOS)
        v = v.point(lambda a: int(255 - (255 - a) * vign))
        img = Image.composite(img, Image.new("RGB", (W, H), (0, 0, 0)), v)

    n = noise_layer(W, H, 0.020 if mode == "dark" else 0.012)
    img = ImageChops.add(img, Image.merge("RGB", (n, n, n)), scale=1.0, offset=-128)
    return img


def bake_shadows(img, rects, radius=20, k=0.42, blur=22, dy=10, mode="dark"):
    """Panellerin altina gercek gaussian golge."""
    if not rects:
        return img
    W, H = img.size
    mask = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(mask)
    for (x, y, w, h) in rects:
        d.rounded_rectangle((x, y + dy, x + w, y + h + dy), radius=radius, fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(blur))
    kk = k if mode == "dark" else k * 0.45
    mask = mask.point(lambda a: int(a * kk))
    return Image.composite(Image.new("RGB", (W, H), (0, 0, 0)), img, mask)


def make_glass(bg, box, tint, ta, radius, border_rgb, border_a, hil_a,
               blur=16, sat=1.25):
    """Apple tarzi cam: arkaplani bulaniklastir, doygunlastir, tint bindir,
    antialiased kose + ust parlak/alt sonuk kenar + ust ic parlama."""
    x, y, w, h = box
    W, H = bg.size
    x, y = max(0, min(W - 2, x)), max(0, min(H - 2, y))
    w, h = max(2, min(W - x, w)), max(2, min(H - y, h))
    crop = bg.crop((x, y, x + w, y + h))
    pad = blur * 2
    ex = bg.crop((max(0, x - pad), max(0, y - pad),
                  min(W, x + w + pad), min(H, y + h + pad)))
    # hiz: kucult -> blurla -> buyut (sonuc ayni derecede yumusak)
    ds = 3
    sw2, sh2 = max(4, ex.size[0] // ds), max(4, ex.size[1] // ds)
    small = ex.resize((sw2, sh2), Image.BILINEAR)
    small = small.filter(ImageFilter.GaussianBlur(max(1.0, blur / ds)))
    ex = small.resize(ex.size, Image.LANCZOS)
    ox, oy = x - max(0, x - pad), y - max(0, y - pad)
    g = ex.crop((ox, oy, ox + w, oy + h))
    g = ImageEnhance.Color(g).enhance(sat)
    g = Image.blend(g, Image.new("RGB", (w, h), tint), ta)

    mask = rounded_mask(w, h, radius)
    out = Image.composite(g, crop, mask).convert("RGBA")

    # kenar: ustte parlak, altta sonuk
    ov = Image.new("RGBA", (w * SS, h * SS), (0, 0, 0, 0))
    do = ImageDraw.Draw(ov)
    do.rounded_rectangle((1, 1, w * SS - 2, h * SS - 2), radius=radius * SS,
                         outline=(border_rgb[0], border_rgb[1], border_rgb[2], 255),
                         width=max(2, SS))
    ov = ov.resize((w, h), Image.LANCZOS)
    # dikey alpha rampasi (ust %100 -> alt %35)
    ramp = Image.linear_gradient("L").resize((w, h)).point(
        lambda a: int(border_a * 255 * (1.0 - 0.65 * (a / 255.0))))
    a = ov.split()[3]
    ov.putalpha(ImageChops.multiply(a, ramp))
    out = Image.alpha_composite(out, ov)

    # ust ic parlama
    if hil_a > 0:
        hl = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        dh = ImageDraw.Draw(hl)
        dh.line((radius, 1, w - radius, 1), fill=(255, 255, 255, int(255 * hil_a)))
        out = Image.alpha_composite(out, hl)
    return out


def _q(c):
    return (c[0] // 6 * 6, c[1] // 6 * 6, c[2] // 6 * 6)


_CHECKER = {}


def checkerboard(w, h, cell=10, dark=False):
    key = (w, h, cell, dark)
    im = _CHECKER.get(key)
    if im is not None:
        return im
    a, b = ((58, 60, 66), (44, 46, 52)) if dark else ((214, 216, 222), (188, 191, 198))
    im = Image.new("RGB", (w, h), a)
    d = ImageDraw.Draw(im)
    for y in range(0, h, cell):
        for x in range(0, w, cell):
            if (x // cell + y // cell) % 2:
                d.rectangle((x, y, x + cell - 1, y + cell - 1), fill=b)
    if len(_CHECKER) > 8:
        _CHECKER.clear()
    _CHECKER[key] = im
    return im


def chroma_alpha(rgb_img, key_hex, sim=0.16):
    """Anahtar renge yakinlik -> alfa maskesi (L). 0=seffaf, 255=opak."""
    kr = int(key_hex[0:2], 16)
    kg = int(key_hex[2:4], 16)
    kb = int(key_hex[4:6], 16)
    solid = Image.new("RGB", rgb_img.size, (kr, kg, kb))
    diff = ImageChops.difference(rgb_img, solid)
    r, g, b = diff.split()
    dist = ImageChops.lighter(ImageChops.lighter(r, g), b)
    thr = max(18, int(sim * 255 * 1.15))
    band = max(6, thr // 3)

    def ramp(v):
        if v <= thr - band:
            return 0
        if v >= thr + band:
            return 255
        return int(255 * (v - (thr - band)) / (2.0 * band))

    return dist.point(ramp)


def chroma_preview(img, key_hex, sim=0.16, dark=True):
    """Onizleme icin anahtar rengi seffaflastirip dama tahtasi uzerine koyar."""
    rgb_img = img.convert("RGB")
    alpha = chroma_alpha(rgb_img, key_hex, sim)
    out = rgb_img.convert("RGBA")
    out.putalpha(alpha)
    bgc = checkerboard(img.size[0], img.size[1], dark=dark).convert("RGBA")
    return Image.alpha_composite(bgc, out).convert("RGB")


def pill_image(w, h, color, radius=None, gloss=True):
    """Antialiased, cam parlamali hap buton goruntusu."""
    c = _q(rgb(color) if isinstance(color, str) else color)
    r = radius if radius is not None else min(14, h // 2)
    key = (w, h, c, r, gloss)
    im = _PILL_CACHE.get(key)
    if im is not None:
        return im
    big = Image.new("RGBA", (w * SS, h * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(big)
    d.rounded_rectangle((0, 0, w * SS - 1, h * SS - 1), radius=r * SS,
                        fill=(c[0], c[1], c[2], 255))
    im = big.resize((w, h), Image.LANCZOS)
    if gloss and h > 16:
        gl = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        dg = ImageDraw.Draw(gl)
        hi = tuple(int(v) for v in mix(c, (255, 255, 255), 0.35))
        lo = tuple(int(v) for v in mix(c, (0, 0, 0), 0.28))
        dg.line((r, 1, w - r, 1), fill=hi + (190,))
        dg.line((r, h - 2, w - r, h - 2), fill=lo + (150,))
        im = Image.alpha_composite(im, gl)
    if len(_PILL_CACHE) > 300:
        _PILL_CACHE.clear()
    _PILL_CACHE[key] = im
    return im


_BTN_CACHE = {}
_BTN_SH_CACHE = {}
BTN_PAD = 14


def btn_image(w, h, fill, radius, primary=True, mode="dark", edge=None):
    """Modern buton govdesi. primary: dikey degrade + ince ust parlama.
    secondary: duz dolgu + 1px kenarlik. Tam-hap yerine olculu yaricap."""
    w, h = int(w), int(h)
    c = _q(rgb(fill) if isinstance(fill, str) else fill)
    ec = _q(rgb(edge)) if edge else None
    key = (w, h, c, int(radius), primary, mode, ec)
    im = _BTN_CACHE.get(key)
    if im is not None:
        return im
    R = int(radius) * SS
    W, H = w * SS, h * SS
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, W - 1, H - 1), radius=R, fill=255)
    if primary:
        top = tuple(int(v) for v in mix(c, (255, 255, 255), 0.17))
        bot = tuple(int(v) for v in mix(c, (0, 0, 0), 0.10))
        grad = Image.new("RGB", (1, H))
        gp = grad.load()
        for yy in range(H):
            t = yy / max(1, H - 1)
            gp[0, yy] = tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3))
        big = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        big.paste(grad.resize((W, H)), (0, 0), mask)
        d = ImageDraw.Draw(big)
        d.rounded_rectangle((SS, SS, W - SS - 1, H - SS - 1),
                            radius=max(1, R - SS), outline=(255, 255, 255, 52),
                            width=max(SS, 1))
    else:
        big = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(big)
        d.rounded_rectangle((0, 0, W - 1, H - 1), radius=R,
                            fill=(c[0], c[1], c[2], 255))
        if ec:
            d.rounded_rectangle((1, 1, W - 2, H - 2), radius=R,
                                outline=(ec[0], ec[1], ec[2], 235), width=max(SS, 1))
    im = big.resize((w, h), Image.LANCZOS)
    if len(_BTN_CACHE) > 400:
        _BTN_CACHE.clear()
    _BTN_CACHE[key] = im
    return im


def btn_shadow(w, h, radius, color, mode="dark", strong=True):
    """Buton altina yumusak renkli golge; konumdan bagimsiz -> hover'da cache'ten."""
    w, h = int(w), int(h)
    c = _q(rgb(color) if isinstance(color, str) else color)
    key = (w, h, int(radius), c, mode, strong)
    im = _BTN_SH_CACHE.get(key)
    if im is not None:
        return im
    pad = BTN_PAD
    W, H = w + pad * 2, h + pad * 2
    dy = 6 if strong else 3
    blur = 10 if strong else 6
    m = Image.new("L", (W, H), 0)
    ImageDraw.Draw(m).rounded_rectangle((pad, pad + dy, pad + w, pad + h + dy),
                                        radius=int(radius), fill=255)
    m = m.filter(ImageFilter.GaussianBlur(blur))
    peak = (135 if strong else 78) if mode == "dark" else (66 if strong else 34)
    m = m.point(lambda a: int(a * peak / 255))
    col = Image.new("RGBA", (W, H), (c[0], c[1], c[2], 0))
    col.putalpha(m)
    if len(_BTN_SH_CACHE) > 200:
        _BTN_SH_CACHE.clear()
    _BTN_SH_CACHE[key] = col
    return col


class Look:
    """Aktif tema+mod paletini tasir."""

    def __init__(self, theme, mode):
        self.set(theme, mode)

    def set(self, theme, mode):
        t = THEMES[theme]
        m = MODES[mode]
        self.theme, self.mode = theme, mode
        self.ACCENT, self.ACCENT2 = t["accent"], t["accent2"]
        self.TXT, self.MUTED, self.OK, self.ERR = m["txt"], m["muted"], m["ok"], m["err"]
        self.G1 = rgb(t["d_g"][0] if mode == "dark" else t["l_g"][0])
        self.G2 = rgb(t["d_g"][1] if mode == "dark" else t["l_g"][1])
        self.ORBS = t["d_orbs"] if mode == "dark" else t["l_orbs"]
        self.TINT, self.TA = m["tint"], m["ta"]
        self.TINT2, self.TA2 = m["tint2"], m["ta2"]
        self.BORDER, self.BORDER_A, self.HIL_A = m["border"], m["border_a"], m["hil_a"]
        self.DIM = m["dim"]
        mid = mix(self.G1, self.G2, 0.5)
        self.GLASS_FLAT = hx(mix(mid, self.TINT, self.TA))
        self.GLASS_FLAT2 = hx(mix(mid, self.TINT2, self.TA2))
        self.CHIP = hx(mix(mix(mid, self.TINT, self.TA), rgb(self.TXT), 0.06))
        gf = mix(mid, self.TINT, self.TA)
        self.EDGE = hx(mix(gf, self.BORDER, min(1.0, self.BORDER_A * 1.35)))
        self.HIL = hx(mix(gf, (255, 255, 255), self.HIL_A))
        self.on_accent = "#101018" if luminance(self.ACCENT) > 0.55 else "#FFFFFF"


LOOK = Look("Midnight", "dark")


# ============================================================
#  Backdrop (aurora arkaplan)
# ============================================================
class Backdrop:
    SC = 3

    def __init__(self):
        self.rows = []
        self.photo = None
        self.w = self.h = 0
        self._base_key = None
        self._base_rows = None
        self._base_img = None      # PIL: golgesiz taban
        self.img = None            # PIL: golgeli nihai

    # ---------------- PIL yolu ----------------
    def render(self, w, h, shadow_rects=()):
        self.w, self.h = w, h
        if HAS_PIL:
            key = (LOOK.theme, LOOK.mode, w, h)
            if key != self._base_key:
                self._base_img = make_backdrop(w, h, LOOK.G1, LOOK.G2, LOOK.ORBS,
                                               mode=LOOK.mode)
                self._base_key = key
            img = self._base_img
            if shadow_rects:
                img = bake_shadows(img, list(shadow_rects), mode=LOOK.mode)
            self.img = img
            self.photo = ImageTk.PhotoImage(img)
            return self.photo
        return self._render_legacy(w, h, shadow_rects)

    def glass(self, x, y, w, h, strong=False, radius=20):
        if HAS_PIL and self.img is not None:
            tint = LOOK.TINT2 if strong else LOOK.TINT
            ta = LOOK.TA2 if strong else LOOK.TA
            im = make_glass(self.img, (x, y, w, h),
                            (int(tint[0]), int(tint[1]), int(tint[2])), ta,
                            radius, LOOK.BORDER, LOOK.BORDER_A, LOOK.HIL_A,
                            blur=18 if not strong else 24)
            return ImageTk.PhotoImage(im)
        return self._glass_legacy(x, y, w, h, strong, radius)

    # ---------------- eski (PIL yoksa) ----------------
    def _render_legacy(self, w, h, shadow_rects=()):
        lw, lh = max(2, math.ceil(w / self.SC)), max(2, math.ceil(h / self.SC))
        key = (LOOK.theme, LOOK.mode, lw, lh)
        if key != self._base_key:
            self._base_rows = _bg_rows(lw, lh, LOOK.G1, LOOK.G2, LOOK.ORBS)
            self._base_key = key
        self.rows = [row[:] for row in self._base_rows]
        if shadow_rects:
            k = 0.34 if LOOK.mode == "dark" else 0.16
            _apply_shadows(self.rows, shadow_rects, self.SC, k=k,
                           sig_px=18.0, dy_px=6.0)
        low = tk.PhotoImage(width=lw, height=lh)
        for y, row in enumerate(self.rows):
            low.put("{" + " ".join(hx(c) for c in row) + "}", to=(0, y))
        self.photo = low.zoom(self.SC, self.SC)
        return self.photo

    def _glass_legacy(self, x, y, w, h, strong=False, radius=18):
        sc = self.SC
        gx, gy = int(x / sc), int(y / sc)
        gw, gh = max(2, math.ceil(w / sc)), max(2, math.ceil(h / sc))
        tint = LOOK.TINT2 if strong else LOOK.TINT
        ta = LOOK.TA2 if strong else LOOK.TA
        rows = _glass_rows(self.rows, gx, gy, gw, gh, tint, ta,
                           max(2, radius // sc), LOOK.BORDER, LOOK.BORDER_A, LOOK.HIL_A)
        low = tk.PhotoImage(width=gw, height=gh)
        for yy, r in enumerate(rows):
            low.put(r, to=(0, yy))
        return low.zoom(sc, sc)


# ============================================================
#  Tween motoru
# ============================================================
def ease(t):
    return 1 - (1 - t) ** 3


def ease_back(t):
    c1, c3 = 1.35, 2.35
    t -= 1
    return 1 + c3 * t ** 3 + c1 * t ** 2


class Anim:
    def __init__(self, root):
        self.root = root
        self.tweens = []
        self.tickers = []
        self._go()

    def tween(self, dur, cb, done=None, easing="out"):
        fn = ease_back if easing == "back" else ease
        self.tweens.append([time.perf_counter(), dur, cb, done, fn])

    def add_ticker(self, fn):
        self.tickers.append(fn)

    def _go(self):
        now = time.perf_counter()
        for tw in self.tweens[:]:
            t0, dur, cb, done, fn = tw
            p = min(1.0, (now - t0) / dur)
            try:
                cb(fn(p))
            except Exception:
                p = 1.0
            if p >= 1.0:
                self.tweens.remove(tw)
                if done:
                    try:
                        done()
                    except Exception:
                        pass
        for fn2 in self.tickers[:]:
            try:
                fn2(now)
            except Exception:
                self.tickers.remove(fn2)
        self.root.after(16, self._go)


# ============================================================
#  Cam panel + item tabanli kontroller
# ============================================================
def rrect(cv, x1, y1, x2, y2, r, **kw):
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
           x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return cv.create_polygon(pts, smooth=True, **kw)


def soft_rect(cv, x, y, w, h, r, color, tags="fx", alpha=255, store="_soft"):
    """Antialiased dolu yuvarlak dikdortgen (PIL varsa), yoksa rrect."""
    w, h = int(max(2, w)), int(max(2, h))
    if not HAS_PIL:
        return rrect(cv, x, y, x + w, y + h, r, fill=color, outline="", tags=tags)
    c = rgb(color) if isinstance(color, str) else color
    big = Image.new("RGBA", (w * SS, h * SS), (0, 0, 0, 0))
    ImageDraw.Draw(big).rounded_rectangle(
        (0, 0, w * SS - 1, h * SS - 1), radius=int(r) * SS,
        fill=(int(c[0]), int(c[1]), int(c[2]), alpha))
    im = big.resize((w, h), Image.LANCZOS)
    ph = ImageTk.PhotoImage(im)
    if not hasattr(cv, store):
        setattr(cv, store, [])
    getattr(cv, store).append(ph)
    if len(getattr(cv, store)) > 60:
        getattr(cv, store).pop(0)
    return cv.create_image(int(x), int(y), image=ph, anchor="nw", tags=tags)


class GlassPanel(tk.Canvas):
    def __init__(self, root, app, strong=False, radius=20):
        super().__init__(root, highlightthickness=0, bd=0, bg=LOOK.GLASS_FLAT)
        self.app = app
        self.strong = strong
        self.radius = radius
        self.rect = (0, 0, 10, 10)
        self.img = None
        self.controls = []

    def set_geometry(self, x, y, w, h):
        self.rect = (x, y, w, h)
        self.place(x=x, y=y, width=w, height=h)

    def refresh(self):
        x, y, w, h = self.rect
        self.config(bg=LOOK.GLASS_FLAT)
        self.delete("glass")
        self.delete("glassline")
        try:
            self.img = self.app.backdrop.glass(x, y, w, h, self.strong, self.radius)
            self.create_image(0, 0, image=self.img, anchor="nw", tags="glass")
        except Exception:
            log_exc("glass")
        self.tag_lower("glass")
        if not HAS_PIL:
            r = self.radius
            rrect(self, 1, 1, w - 1, h - 1, r, fill="", outline=LOOK.EDGE,
                  width=1, tags="glassline")
            self.create_line(r, 2, w - r, 2, fill=LOOK.HIL, tags="glassline")
        for c in self.controls:
            try:
                c.draw()
            except Exception:
                log_exc(f"control {getattr(c, 'tag', '?')}")
        try:
            self.draw_content()
        except Exception:
            log_exc(f"draw_content {type(self).__name__}")

    def request(self):
        self.app.mark_dirty(self)

    def draw_content(self):
        pass


class GButton:
    """Cam panel uzerinde item olarak cizilen, hover tweenli buton."""

    def __init__(self, host, tag, x, y, w, h, text, cmd,
                 primary=True, font=None, small=False):
        self.host, self.tag = host, tag
        self.x, self.y, self.w, self.h = x, y, w, h
        self.text, self.cmd, self.primary = text, cmd, primary
        self.small = small
        self.font = font
        self.hp = 0.0
        self.pp = 0.0
        self.enabled = True
        self.visible = True
        host.controls.append(self)
        host.tag_bind(tag, "<Button-1>", self._press)
        host.tag_bind(tag, "<Enter>", lambda e: self._hover(1))
        host.tag_bind(tag, "<Leave>", lambda e: self._hover(0))

    def _press(self, e):
        if not self.enabled:
            return
        def down(p):
            self.pp = p
            self._paint()
        def up():
            def rel(p):
                self.pp = 1 - p
                self._paint()
            self.host.app.anim.tween(0.14, rel)
            if self.cmd:
                self.cmd()
        self.host.app.anim.tween(0.07, down, done=up)

    def _hover(self, target):
        start = self.hp

        def cb(p):
            self.hp = start + (target - start) * p
            self._paint()
        self.host.app.anim.tween(0.16, cb)
        try:
            self.host.config(cursor="hand2" if target else "")
        except Exception:
            pass

    def set_text(self, t):
        self.text = t
        self._paint()

    def set_enabled(self, v):
        self.enabled = v
        self._paint()

    def move(self, x, y, w=None, h=None):
        self.x, self.y = x, y
        if w:
            self.w = w
        if h:
            self.h = h
        self.draw()

    def _colors(self):
        if not self.enabled:
            return LOOK.CHIP, LOOK.MUTED
        if self.primary:
            base = rgb(LOOK.ACCENT)
            tgt = mix(base, (255, 255, 255) if LOOK.mode == "dark" else (0, 0, 0), 0.14)
            c = mix(base, tgt, self.hp)
        else:
            base = rgb(LOOK.CHIP)
            tgt = mix(base, rgb(LOOK.TXT), 0.10)
            c = mix(base, tgt, self.hp)
        if self.pp:
            c = mix(c, (0, 0, 0), 0.14 * self.pp)
        return hx(c), (LOOK.on_accent if self.primary else LOOK.TXT)

    def draw(self):
        shtag = self.tag + "_sh"
        self.host.delete(self.tag)
        self.host.delete(shtag)
        if not self.visible:
            return
        fill, fg = self._colors()
        w, h = int(self.w), int(self.h)
        r = max(8, min(16, round(h * 0.34)))
        if HAS_PIL:
            if self.enabled:
                shc = LOOK.ACCENT if self.primary else (0, 0, 0)
                sh = btn_shadow(w, h, r, shc, LOOK.mode, strong=self.primary)
                self._sph = ImageTk.PhotoImage(sh)
                self.host.create_image(int(self.x - BTN_PAD), int(self.y - BTN_PAD),
                                       image=self._sph, anchor="nw", tags=shtag)
            im = btn_image(w, h, fill, r, primary=self.primary and self.enabled,
                           mode=LOOK.mode, edge=None if self.primary else LOOK.EDGE)
            self._ph = ImageTk.PhotoImage(im)
            self.host.create_image(int(self.x), int(self.y), image=self._ph,
                                   anchor="nw", tags=self.tag)
        else:
            rrect(self.host, self.x, self.y, self.x + self.w, self.y + self.h, r,
                  fill=fill, outline=("" if self.primary else LOOK.EDGE),
                  tags=self.tag)
        fnt = self.font or (FONT, 9 if self.small else 10, "bold")
        self.host.create_text(self.x + self.w / 2, self.y + self.h / 2,
                              text=self.text, fill=fg, font=fnt, tags=self.tag)

    def _paint(self):
        # sadece renk/yazi guncelle (hizli)
        self.draw()


class GSegmented:
    """Kayan secili hapli segment kontrolu."""

    def __init__(self, host, tag, x, y, w, h, options, var, on_change=None):
        self.host, self.tag = host, tag
        self.x, self.y, self.w, self.h = x, y, w, h
        self.options, self.var, self.on_change = options, var, on_change
        self.knob_x = None
        self.visible = True
        host.controls.append(self)
        host.tag_bind(tag, "<Button-1>", self._click)

    def _idx(self):
        cur = self.var.get()
        for i, (_, v) in enumerate(self.options):
            if v == cur:
                return i
        return 0

    def _seg_x(self, i):
        seg = self.w / len(self.options)
        return self.x + i * seg + 3

    def _click(self, e):
        seg = self.w / len(self.options)
        i = max(0, min(len(self.options) - 1, int((e.x - self.x) // seg)))
        if self.options[i][1] == self.var.get():
            return
        self.var.set(self.options[i][1])
        start = self.knob_x if self.knob_x is not None else self._seg_x(i)
        target = self._seg_x(i)

        def cb(p):
            self.knob_x = start + (target - start) * p
            self.draw()
        self.host.app.anim.tween(0.24, cb, easing="back",
                                 done=lambda: self.on_change and self.on_change(self.var.get()))

    def move(self, x, y, w=None, h=None):
        self.x, self.y = x, y
        if w:
            self.w = w
        if h:
            self.h = h
        self.knob_x = None
        self.draw()

    def draw(self):
        self.host.delete(self.tag)
        if not self.visible:
            return
        seg = self.w / len(self.options)
        if self.knob_x is None:
            self.knob_x = self._seg_x(self._idx())
        w, h = int(self.w), int(self.h)
        tr_r = max(8, round(h * 0.34))
        if HAS_PIL:
            tr = btn_image(w, h, LOOK.GLASS_FLAT2, tr_r, primary=False,
                           mode=LOOK.mode, edge=LOOK.EDGE)
            self._tph = ImageTk.PhotoImage(tr)
            self.host.create_image(int(self.x), int(self.y), image=self._tph,
                                   anchor="nw", tags=self.tag)
            kw, kh = max(2, int(seg - 6)), max(2, int(h - 6))
            kr = max(6, round(kh * 0.40))
            ksh = btn_shadow(kw, kh, kr, LOOK.ACCENT, LOOK.mode, strong=False)
            self._ksh = ImageTk.PhotoImage(ksh)
            self.host.create_image(int(self.knob_x - BTN_PAD),
                                   int(self.y + 3 - BTN_PAD),
                                   image=self._ksh, anchor="nw", tags=self.tag)
            kn = btn_image(kw, kh, LOOK.ACCENT, kr, primary=True, mode=LOOK.mode)
            self._kph = ImageTk.PhotoImage(kn)
            self.host.create_image(int(self.knob_x), int(self.y + 3),
                                   image=self._kph, anchor="nw", tags=self.tag)
        else:
            rrect(self.host, self.x, self.y, self.x + self.w, self.y + self.h, tr_r,
                  fill=LOOK.GLASS_FLAT2, outline=LOOK.EDGE, tags=self.tag)
            rrect(self.host, self.knob_x, self.y + 3, self.knob_x + seg - 6,
                  self.y + self.h - 3, tr_r - 3, fill=LOOK.ACCENT, outline="",
                  tags=self.tag)
        cur = self.var.get()
        for i, (label, val) in enumerate(self.options):
            cx = self.x + i * seg + seg / 2
            active = (val == cur)
            fg = LOOK.on_accent if active else LOOK.MUTED
            self.host.create_text(cx, self.y + self.h / 2, text=label, fill=fg,
                                  font=(FONT, 9, "bold" if active else "normal"),
                                  tags=self.tag)
        self.host.tag_raise(self.tag)


class GSlider:
    """Ince kaydirici: hassasiyet vb. icin."""

    def __init__(self, host, tag, vmin, vmax, val, on_change=None):
        self.host, self.tag = host, tag
        self.vmin, self.vmax, self.val = vmin, vmax, val
        self.on_change = on_change
        self.x = self.y = 0
        self.w, self.h = 100, 22
        self.visible = True
        host.controls.append(self)
        host.tag_bind(tag, "<Button-1>", self._set)
        host.tag_bind(tag, "<B1-Motion>", self._set)
        host.tag_bind(tag, "<Enter>", lambda e: host.config(cursor="hand2"))
        host.tag_bind(tag, "<Leave>", lambda e: host.config(cursor=""))

    def move(self, x, y, w=None, h=None):
        self.x, self.y = x, y
        if w:
            self.w = w
        if h:
            self.h = h
        self.draw()

    def _set(self, e):
        t = (e.x - self.x - 8) / max(1, self.w - 16)
        self.val = self.vmin + max(0.0, min(1.0, t)) * (self.vmax - self.vmin)
        self.draw()
        if self.on_change:
            self.on_change(self.val)

    def draw(self):
        self.host.delete(self.tag)
        if not self.visible:
            return
        cy = self.y + self.h / 2
        x1, x2 = self.x + 8, self.x + self.w - 8
        rrect(self.host, x1, cy - 3, x2, cy + 3, 3,
              fill=LOOK.GLASS_FLAT2, outline="", tags=self.tag)
        t = (self.val - self.vmin) / max(1e-6, self.vmax - self.vmin)
        kx = x1 + t * (x2 - x1)
        rrect(self.host, x1, cy - 3, max(x1 + 4, kx), cy + 3, 3,
              fill=LOOK.ACCENT, outline="", tags=self.tag)
        self.host.create_oval(kx - 8, cy - 8, kx + 8, cy + 8,
                              fill=LOOK.ACCENT, outline=LOOK.HIL, width=2,
                              tags=self.tag)
        self.host.create_oval(kx - 3, cy - 3, kx + 3, cy + 3,
                              fill=LOOK.on_accent, outline="", tags=self.tag)


FONT = "Segoe UI"

ERRLOG = os.path.join(os.path.expanduser("~"), ".telegram_sticker_maker_error.log")


def wlift(w):
    """Canvas.lift item komutuyla cakistigi icin widget'i guvenli yukselt."""
    try:
        tk.Misc.tkraise(w)
    except Exception:
        pass


def log_exc(where=""):
    try:
        import traceback
        with open(ERRLOG, "a", encoding="utf-8") as f:
            f.write(f"\n--- {time.strftime('%Y-%m-%d %H:%M:%S')} {where}\n")
            f.write(traceback.format_exc())
    except Exception:
        pass


def pick_font(root):
    global FONT
    try:
        fams = set(tkfont.families(root))
        for f in ("SF Pro Display", "Segoe UI Variable Display", "Segoe UI Variable Text",
                  "Segoe UI", "Helvetica Neue"):
            if f in fams:
                FONT = f
                return
    except Exception:
        pass


# ============================================================
#  Player paneli (cam icinde video + kontrol satiri + kirpma)
# ============================================================
class DragChip(tk.Canvas):
    """Cikan sticker'i temsil eden cip: surukle -> Telegram'a birak,
    tikla -> dosya konumunu ac."""
    W, H = 200, 40

    def __init__(self, panel, app):
        super().__init__(panel, width=self.W, height=self.H,
                         highlightthickness=0, bd=0, bg=LOOK.GLASS_FLAT)
        self.panel, self.app = panel, app
        self._bg = None
        self._pill = None
        self._dragging = False
        self._press = None
        self.can_drag = False
        if HAS_DND:
            try:
                self.drag_source_register(1, DND_FILES)
                self.dnd_bind("<<DragInitCmd>>", self._drag_init)
                self.can_drag = True
            except Exception:
                log_exc("dragsrc")
        self.bind("<ButtonPress-1>", self._down)
        self.bind("<ButtonRelease-1>", self._up)
        self.config(cursor="hand2")

    def _drag_init(self, event):
        p = self.app.last_out_file
        if not p or not os.path.exists(p):
            return None
        self._dragging = True
        return (DND_COPY, DND_FILES, "{" + os.path.normpath(p) + "}")

    def _down(self, e):
        self._press = (e.x, e.y)
        self._dragging = False

    def _up(self, e):
        if self._dragging:
            self._dragging = False
            return
        if self._press and abs(e.x - self._press[0]) < 6 \
                and abs(e.y - self._press[1]) < 6:
            self.app.open_last_location()

    def sync(self, abs_x, abs_y):
        """Panelin cam dokusuyla birlesik arka plani ornekle ve ciz."""
        self.delete("all")
        self.config(bg=LOOK.GLASS_FLAT)
        try:
            self._bg = self.app.backdrop.glass(abs_x, abs_y, self.W, self.H,
                                               False, self.H // 2)
            self.create_image(0, 0, image=self._bg, anchor="nw")
        except Exception:
            pass
        if HAS_PIL:
            im = pill_image(self.W, self.H, LOOK.ACCENT2, self.H // 2, gloss=True)
            self._pill = ImageTk.PhotoImage(im)
            self.create_image(0, 0, image=self._pill, anchor="nw")
        else:
            rrect(self, 0, 0, self.W, self.H, self.H // 2,
                  fill=LOOK.ACCENT2, outline="")
        fg = "#FFFFFF" if luminance(LOOK.ACCENT2) < 0.6 else "#101018"
        drag_txt = "drag → Telegram" if self.can_drag else "click = open location"
        self.create_text(self.W / 2, 13, text="🎟 Sticker ready",
                         fill=fg, font=(FONT, 9, "bold"))
        self.create_text(self.W / 2, 28, text=drag_txt,
                         fill=fg, font=(FONT, 7))


class PlayerPanel(GlassPanel):
    CTRL_H = 62

    def __init__(self, root, app):
        super().__init__(root, app)
        self.mode = "idle"
        self._hot = False
        self._img = None
        self._raw = None
        self._cache = OrderedDict()
        self._cdrag = None
        self._imgrect = None
        self.play_btn = GButton(self, "playbtn", 0, 0, 178, 44,
                                "▶  Play Selection", app.toggle_play, primary=False)
        self.chip = DragChip(self, app)
        self._chip_win = None
        self.bind("<Button-1>", self._down)
        self.bind("<B1-Motion>", self._dragmove)
        self.bind("<ButtonRelease-1>", lambda e: setattr(self, "_cdrag", None))

    # video cizim alani
    def _vid_rect(self):
        x, y, w, h = 14, 14, self.rect[2] - 28, self.rect[3] - 28 - self.CTRL_H
        return x, y, w, h

    def set_mode(self, m):
        self.mode = m
        self._cache.clear()
        self.request()

    def hot(self, v):
        self._hot = v
        self.request()

    def request(self):
        self.app.mark_dirty(self)

    # ---- kirpma etkilesimi ----
    def _crop_box_px(self):
        if not self._imgrect:
            return None
        left, top, pw, ph = self._imgrect
        c = self.app.crop
        side = c["cf"] * min(pw, ph)
        cxp = left + c["cx"] * pw
        cyp = top + c["cy"] * ph
        return (cxp - side / 2, cyp - side / 2, cxp + side / 2, cyp + side / 2, side)

    def _get_frame(self, idx, box=None):
        """Kareyi cerceveye sigdirir; chroma acikken onizlemede arka plani kaldirir.
        (PhotoImage, ham_PIL_resimli) doner."""
        s = self.app.sess
        if not s:
            return None, None
        idx = max(1, min(s["n"], idx))
        path = os.path.join(s["dir"], f"f_{idx:04d}.png")
        if not os.path.exists(path):
            return None, None

        if not HAS_PIL:
            if idx in self._cache:
                self._cache.move_to_end(idx)
                return self._cache[idx], None
            try:
                img = tk.PhotoImage(file=path)
            except Exception:
                return None, None
            self._cache[idx] = img
            if len(self._cache) > 48:
                self._cache.popitem(last=False)
            return img, None

        ckey = self.app.preview_chroma()
        key = (idx, box, ckey)
        hit = self._cache.get(key)
        if hit:
            self._cache.move_to_end(key)
            return hit[0], hit[1]
        try:
            im = Image.open(path).convert("RGB")
        except Exception:
            return None, None
        if box:
            bw, bh = box
            sc = min(bw / im.width, bh / im.height)
            if sc < 1.0 or sc > 1.02:
                im = im.resize((max(1, int(im.width * sc)),
                                max(1, int(im.height * sc))), Image.LANCZOS)
        raw = im
        if ckey:
            try:
                im = chroma_preview(im, ckey[0], ckey[1], dark=(LOOK.mode == "dark"))
            except Exception:
                log_exc("chroma_preview")
        ph = ImageTk.PhotoImage(im)
        self._cache[key] = (ph, raw)
        if len(self._cache) > 40:
            self._cache.popitem(last=False)
        return ph, raw

    def _pixel_at(self, e):
        """Tiklanan noktadaki (chroma uygulanmamis) rengi RRGGBB olarak dondurur."""
        if not self._imgrect:
            return None
        left, top, pw, ph = self._imgrect
        x = int(e.x - left)
        y = int(e.y - top)
        if not (0 <= x < pw and 0 <= y < ph):
            return None
        if HAS_PIL and self._raw is not None:
            try:
                v = self._raw.getpixel((x, y))
                return "%02X%02X%02X" % (v[0], v[1], v[2])
            except Exception:
                return None
        if not self._img:
            return None
        try:
            v = self._img.get(x, y)
            if isinstance(v, str):
                v = tuple(int(a) for a in v.split())
            return "%02X%02X%02X" % (v[0], v[1], v[2])
        except Exception:
            return None

    def _down(self, e):
        vx, vy, vw, vh = self._vid_rect()
        inside = vx <= e.x <= vx + vw and vy <= e.y <= vy + vh
        if self.mode == "idle" and inside:
            self.app.pick_files()
            return
        if self.mode != "video" or not inside:
            return
        if self.app.gs_picking:
            col = self._pixel_at(e)
            if col:
                self.app.chroma_picked(col)
            return
        if self.app.crop_on:
            b = self._crop_box_px()
            if b:
                self.app.push_undo()
                x1, y1, x2, y2, _ = b
                corners = [(x1, y1), (x2, y1), (x1, y2), (x2, y2)]
                if any(abs(e.x - cx) <= 12 and abs(e.y - cy) <= 12 for cx, cy in corners):
                    self._cdrag = "resize"
                else:
                    self._cdrag = "move"
                self._dragmove(e)
            return
        self.app.toggle_play()

    def _dragmove(self, e):
        if not self._cdrag or not self._imgrect or self.mode != "video":
            return
        left, top, pw, ph = self._imgrect
        c = self.app.crop
        if self._cdrag == "resize":
            cxp = left + c["cx"] * pw
            cyp = top + c["cy"] * ph
            side = 2 * max(abs(e.x - cxp), abs(e.y - cyp))
            c["cf"] = max(0.15, min(1.0, side / max(1, min(pw, ph))))
        else:
            c["cx"] = (e.x - left) / max(1, pw)
            c["cy"] = (e.y - top) / max(1, ph)
        self.app.clamp_crop(pw, ph)
        self.request()

    def draw_content(self):
        self.delete("fx")
        w, h = self.rect[2], self.rect[3]
        vx, vy, vw, vh = self._vid_rect()
        # video kuyusu (ic cam)
        soft_rect(self, vx, vy, vw, vh, 14, LOOK.GLASS_FLAT2, tags="fx")

        if self._hot:
            self.create_text(vx + vw / 2, vy + vh / 2, text="BIRAK!", fill=LOOK.ACCENT,
                             font=(FONT, 22, "bold"), tags="fx")
        elif self.mode == "idle":
            self.create_rectangle(vx + 14, vy + 14, vx + vw - 14, vy + vh - 14,
                                  outline=LOOK.EDGE, width=1, tags="fx")
            self.create_text(vx + vw / 2, vy + vh / 2 - 22, text="⬇", fill=LOOK.ACCENT,
                             font=(FONT, 32, "bold"), tags="fx")
            self.create_text(vx + vw / 2, vy + vh / 2 + 20, text="DRAG  &  DROP",
                             fill=LOOK.TXT, font=(FONT, 14, "bold"), tags="fx")
            self.create_text(vx + vw / 2, vy + vh - 18,
                             text=".mp4  .mov  .gif  .png  .jpg   •   click = pick file",
                             fill=LOOK.MUTED, font=(FONT, 8), tags="fx")
        elif self.mode == "loading":
            self.create_text(vx + vw / 2, vy + vh / 2 - 10, text="⚡", fill=LOOK.ACCENT2,
                             font=(FONT, 30), tags="fx")
            self.create_text(vx + vw / 2, vy + vh / 2 + 26, text="PREPARING PREVIEW...",
                             fill=LOOK.ACCENT2, font=(FONT, 12, "bold"), tags="fx")
        elif self.mode == "video":
            self._img, self._raw = self._get_frame(
                self.app.idx, (int(vw - 16), int(vh - 16)))
            self._imgrect = None
            if self._img:
                pw, ph = self._img.width(), self._img.height()
                left = vx + vw / 2 - pw / 2
                top = vy + vh / 2 - ph / 2
                self._imgrect = (left, top, pw, ph)
                self.create_image(vx + vw / 2, vy + vh / 2, image=self._img, tags="fx")
            if self.app.crop_on and self._imgrect:
                self._draw_crop()
            t = self.app.cur_t()
            s = self.app.sess
            if s.get("kind") == "image":
                self.create_text(vx + 12, vy + vh - 16, anchor="w",
                                 text="🖼 STATIC IMAGE",
                                 fill=LOOK.ACCENT, font=(FONT, 9, "bold"), tags="fx")
            else:
                self.create_text(vx + 12, vy + vh - 16, anchor="w",
                                 text=f"{fmt_t(t)} / {fmt_t(s['dur'])}",
                                 fill=LOOK.ACCENT, font=("Consolas", 10, "bold"),
                                 tags="fx")
            if self.app.preview_chroma():
                self.create_text(vx + 12, vy + 14, anchor="w",
                                 text="🟢 CHROMA PREVIEW", fill=LOOK.OK,
                                 font=(FONT, 8, "bold"), tags="fx")
            hint = ("🎯 click the color to remove" if self.app.gs_picking
                    else "move box • resize from corner" if self.app.crop_on
                    else "" if (self.app.playing
                                or s.get("kind") == "image")
                    else "▶ click / space")
            if hint:
                self.create_text(vx + vw - 12, vy + vh - 16, anchor="e", text=hint,
                                 fill=LOOK.MUTED, font=(FONT, 8), tags="fx")

        # kontrol satiri
        cy = h - self.CTRL_H + 8
        is_img = bool(self.app.sess and self.app.sess.get("kind") == "image")
        self.play_btn.visible = (self.mode == "video" and not is_img)
        self.play_btn.move(14, cy, 178, 44)
        cx0 = 14 + (178 + 8 if self.play_btn.visible else 0)
        show_chip = bool(self.app.last_out_file)
        if show_chip:
            if self._chip_win is None:
                self._chip_win = self.create_window(cx0, cy + 2, anchor="nw",
                                                    window=self.chip,
                                                    tags="chipwin")
            self.coords(self._chip_win, cx0, cy + 2)
            self.itemconfigure(self._chip_win, state="normal")
            self.chip.sync(self.rect[0] + cx0, self.rect[1] + cy + 2)
            self.tag_raise("chipwin")
        elif self._chip_win is not None:
            self.itemconfigure(self._chip_win, state="hidden")
        used = cx0 + (DragChip.W + 8 if show_chip else 0)
        avail = max(60, w - 16 - used - 12)
        info = self._fit(self.app.finfo_text(), avail)
        if info:
            self.create_text(w - 16, cy + 20, anchor="e", text=info,
                             fill=LOOK.MUTED, font=(FONT, 9), tags="fx")

    def _fit(self, text, maxpx):
        """Metni verilen piksel genisligine sigacak sekilde kisaltir."""
        if not text:
            return ""
        try:
            f = tkfont.Font(font=(FONT, 9))
        except Exception:
            return text if len(text) < 40 else text[:37] + "…"
        if f.measure(text) <= maxpx:
            return text
        lo, hi = 1, len(text)
        while lo < hi:
            mid = (lo + hi) // 2
            if f.measure(text[:mid] + "…") <= maxpx:
                lo = mid + 1
            else:
                hi = mid
        return text[:max(1, lo - 1)] + "…"

    def _draw_crop(self):
        b = self._crop_box_px()
        if not b:
            return
        x1, y1, x2, y2, side = b
        left, top, pw, ph = self._imgrect
        ir = (left, top, left + pw, top + ph)
        for (a1, b1, a2, b2) in ((ir[0], ir[1], ir[2], y1), (ir[0], y2, ir[2], ir[3]),
                                 (ir[0], y1, x1, y2), (x2, y1, ir[2], y2)):
            if a2 - a1 > 1 and b2 - b1 > 1:
                soft_rect(self, a1, b1, a2 - a1, b2 - b1, 0, LOOK.DIM,
                          tags="fx", alpha=130, store="_dim")
        self.create_rectangle(x1, y1, x2, y2, outline=LOOK.ACCENT, width=2, tags="fx")
        for fx in (1 / 3, 2 / 3):
            self.create_line(x1 + (x2 - x1) * fx, y1, x1 + (x2 - x1) * fx, y2,
                             fill=LOOK.ACCENT, dash=(2, 4), tags="fx")
            self.create_line(x1, y1 + (y2 - y1) * fx, x2, y1 + (y2 - y1) * fx,
                             fill=LOOK.ACCENT, dash=(2, 4), tags="fx")
        for (hx_, hy_) in ((x1, y1), (x2, y1), (x1, y2), (x2, y2)):
            self.create_rectangle(hx_ - 5, hy_ - 5, hx_ + 5, hy_ + 5,
                                  fill=LOOK.ACCENT, outline="", tags="fx")
        self.create_text((x1 + x2) / 2, y1 - 10, text="512 × 512", fill=LOOK.ACCENT,
                         font=(FONT, 8, "bold"), tags="fx")


# ============================================================
#  Timeline paneli
# ============================================================
class TimelinePanel(GlassPanel):
    PADX = 18
    RULER_H = 20
    STRIP_H = 56
    HANDLE = 9

    def __init__(self, root, app):
        super().__init__(root, app)
        self.thumbs = []
        self._strip_key = None
        self._strip_ph = None
        self._drag = None
        self._grab_off = 0.0
        self.bind("<Button-1>", self._down)
        self.bind("<B1-Motion>", self._move)
        self.bind("<ButtonRelease-1>", lambda e: setattr(self, "_drag", None))

    def clear_thumbs(self):
        self.thumbs = []
        self._strip_key = None
        self._strip_ph = None

    def _build_strip(self):
        """Tam genislikte, yuvarlak koseli tek parca filmstrip (PIL)."""
        s = self.app.sess
        tw, sh = self._tw(), self.STRIP_H
        key = (s["dir"], tw)
        if getattr(self, "_strip_key", None) == key and self._strip_ph:
            return True
        first = os.path.join(s["dir"], "f_0001.png")
        if not os.path.exists(first):
            return False
        try:
            im0 = Image.open(first)
            ar = im0.width / max(1, im0.height)
            tile_w = max(8, int(sh * ar))
            n = max(1, math.ceil(tw / tile_w))
            strip = Image.new("RGB", (tw, sh), (0, 0, 0))
            x = 0
            for i in range(n):
                idx = (1 + round(i * (s["n"] - 1) / max(1, n - 1))) if n > 1 else 1
                p = os.path.join(s["dir"], f"f_{idx:04d}.png")
                if not os.path.exists(p):
                    continue
                t = Image.open(p).convert("RGB").resize((tile_w, sh), Image.LANCZOS)
                strip.paste(t, (x, 0))
                x += tile_w
                if x >= tw:
                    break
            out = Image.new("RGBA", (tw, sh), (0, 0, 0, 0))
            out.paste(strip, (0, 0), rounded_mask(tw, sh, 8))
            self._strip_ph = ImageTk.PhotoImage(out)
            self._strip_key = key
            return True
        except Exception:
            log_exc("strip")
            return False

    def _tw(self):
        return max(1, self.rect[2] - 2 * self.PADX)

    def _t2x(self, t):
        s = self.app.sess
        return self.PADX + (t / max(0.001, s["dur"])) * self._tw()

    def _x2t(self, x):
        s = self.app.sess
        return min(s["dur"], max(0.0, (x - self.PADX) / self._tw() * s["dur"]))

    def _rows(self):
        ry1 = 30
        ry2 = ry1 + self.RULER_H
        sy1 = ry2 + 2
        sy2 = sy1 + self.STRIP_H
        return ry1, ry2, sy1, sy2

    def _build_thumbs(self):
        s = self.app.sess
        if not s or s["n"] == 0:
            return
        first = os.path.join(s["dir"], "f_0001.png")
        if not os.path.exists(first):
            return
        try:
            pi = tk.PhotoImage(file=first)
        except Exception:
            return
        fw, fh = pi.width(), pi.height()
        factor = max(1, math.ceil(fh / (self.STRIP_H - 4)))
        tw = max(1, fw // factor)
        count = min(s["n"], max(1, math.ceil(self._tw() / tw)))
        self.thumbs = []
        for i in range(count):
            idx = 1 + round(i * (s["n"] - 1) / max(1, count - 1)) if count > 1 else 1
            path = os.path.join(s["dir"], f"f_{idx:04d}.png")
            try:
                self.thumbs.append(tk.PhotoImage(file=path).subsample(factor, factor))
            except Exception:
                self.thumbs.append(None)

    def _down(self, e):
        s = self.app.sess
        if not s:
            return
        ry1, ry2, sy1, sy2 = self._rows()
        if e.y <= ry2:
            self._drag = "seek"
            self._move(e)
            return
        # strip'e dokunulunca kesim modu otomatik acilir (kilitli kalmasin)
        if self.app.durm_var.get() != "custom" and s["dur"] > MAX_DUR:
            self.app.force_custom_mode()
        if self.app.can_trim():
            self.app.push_undo()
            xL = self._t2x(self.app.win_start)
            xR = self._t2x(self.app.win_start + self.app.win_len)
            if abs(e.x - xL) <= self.HANDLE:
                self._drag = "left"
            elif abs(e.x - xR) <= self.HANDLE:
                self._drag = "right"
            elif xL < e.x < xR:
                self._drag = "move"
                self._grab_off = self._x2t(e.x) - self.app.win_start
            else:
                # secim disina tiklandi: pencereyi oraya tasi
                self._drag = "move"
                self._grab_off = self.app.win_len / 2
        else:
            self._drag = "seek"
        self._move(e)

    def _move(self, e):
        s = self.app.sess
        if not s or not self._drag:
            return
        t = self._x2t(e.x)
        if self._drag == "seek":
            self.app.seek(t)
        elif self._drag == "left":
            end = self.app.win_start + self.app.win_len
            ns = min(max(0.0, t), end - MIN_SEL)
            ns = max(ns, end - MAX_DUR)
            self.app.set_window(ns, end - ns)
        elif self._drag == "right":
            st = self.app.win_start
            ne = max(min(t, s["dur"], st + MAX_DUR), st + MIN_SEL)
            self.app.set_window(st, ne - st)
        elif self._drag == "move":
            ln = self.app.win_len
            ns = min(max(0.0, t - self._grab_off), s["dur"] - ln)
            self.app.set_window(ns, ln)

    def draw_content(self):
        self.delete("fx")
        self.delete("ph")
        w = self.rect[2]
        s = self.app.sess
        PADX = self.PADX
        ry1, ry2, sy1, sy2 = self._rows()
        self.create_text(PADX, 16, anchor="w", text="TIMELINE",
                         fill=LOOK.MUTED, font=(FONT, 8, "bold"), tags="fx")

        if not s:
            soft_rect(self, PADX, sy1, w - 2 * PADX, sy2 - sy1, 10,
                      LOOK.GLASS_FLAT2, tags="fx")
            self.create_text(w / 2 - 68, (sy1 + sy2) / 2, text="🎞",
                             fill=LOOK.MUTED, font=(FONT, 13), tags="fx")
            self.create_text(w / 2 + 6, (sy1 + sy2) / 2, text="drop a file first",
                             fill=LOOK.MUTED, font=(FONT, 9), tags="fx")
            return

        if s.get("kind") == "image":
            soft_rect(self, PADX, sy1, w - 2 * PADX, sy2 - sy1, 10,
                      LOOK.GLASS_FLAT2, tags="fx")
            self.create_text(w / 2, (sy1 + sy2) / 2,
                             text="🖼  static image  ·  no duration setting  ·  "
                                  "crop / chroma, then CONVERT",
                             fill=LOOK.MUTED, font=(FONT, 9), tags="fx")
            return

        dur = s["dur"]
        # ruler
        soft_rect(self, PADX, ry1, w - 2 * PADX, ry2 - ry1, 6,
                  LOOK.GLASS_FLAT2, tags="fx")
        step = 1 if dur <= 12 else (5 if dur <= 90 else 15)
        tt = 0
        last_lbl = -999
        while tt <= dur + 0.01:
            x = self._t2x(tt)
            self.create_line(x, ry2 - 6, x, ry2, fill=LOOK.MUTED, tags="fx")
            if x - last_lbl >= 42 and x < w - PADX - 30:
                self.create_text(x + 3, ry1 + 7, anchor="w", text=fmt_t(float(tt)),
                                 fill=LOOK.MUTED, font=(FONT, 7), tags="fx")
                last_lbl = x
            tt += step

        # filmstrip
        if HAS_PIL and self._build_strip():
            self.create_image(PADX, sy1, image=self._strip_ph, anchor="nw",
                              tags="fx")
        else:
            if not self.thumbs:
                self._build_thumbs()
            x = PADX
            for im in self.thumbs:
                if im is None:
                    x += 40
                    continue
                self.create_image(x, (sy1 + sy2) / 2, image=im, anchor="w", tags="fx")
                x += im.width()
                if x > w - PADX:
                    break
            self.create_rectangle(w - PADX, sy1 - 1, w, sy2 + 1,
                                  fill=LOOK.GLASS_FLAT, outline="", tags="fx")

        # secim
        mode = self.app.durm_var.get()
        if mode == "fit" and dur > MAX_DUR:
            self.create_rectangle(PADX, sy1, w - PADX, sy2, outline=LOOK.ACCENT2,
                                  width=2, tags="fx")
            self.create_text(w / 2, sy2 + 13, text="sped up to fit 3s",
                             fill=LOOK.ACCENT2, font=(FONT, 8, "bold"), tags="fx")
        else:
            if mode == "start0":
                start, length = 0.0, min(MAX_DUR, dur)
            else:
                start, length = self.app.win_start, self.app.win_len
            end = start + length
            x1, x2 = self._t2x(start), self._t2x(end)
            if x1 > PADX:
                soft_rect(self, PADX, sy1, x1 - PADX, sy2 - sy1, 0, LOOK.DIM,
                          tags="fx", alpha=130, store="_dim")
            if x2 < w - PADX:
                soft_rect(self, x2, sy1, (w - PADX) - x2, sy2 - sy1, 0, LOOK.DIM,
                          tags="fx", alpha=130, store="_dim")
            self.create_rectangle(x1, sy1, x2, sy2, outline=LOOK.ACCENT,
                                  width=2, tags="fx")
            if mode == "custom":
                for hx_ in (x1, x2):
                    rrect(self, hx_ - 4, sy1 - 7, hx_ + 5, sy2 + 7, 4,
                          fill=LOOK.ACCENT, outline="", tags="fx")
                    self.create_line(hx_, sy1 + 4, hx_, sy2 - 4,
                                     fill=LOOK.GLASS_FLAT, tags="fx")
                lbl = f"{length:.1f}s  ·  {start:.1f}s – {end:.1f}s  ·  trim from edges"
            else:
                lbl = f"first {length:.1f}s (fixed)  ·  drag = switch to trim mode"
            self.create_text(w / 2, sy2 + 13, text=lbl, fill=LOOK.ACCENT,
                             font=(FONT, 8, "bold"), tags="fx")

        # playhead (yumusak, ayri katman)
        self.update_playhead()

    def update_playhead(self):
        self.delete("ph")
        if not self.app.sess or self.app.sess.get("kind") == "image":
            return
        ry1, ry2, sy1, sy2 = self._rows()
        px = self._t2x(self.app.cur_t())
        soft_rect(self, px - 3, ry1, 6, sy2 - ry1, 3, LOOK.ACCENT,
                  tags="ph", alpha=70, store="_glow")
        self.create_polygon(px - 5, ry1, px + 5, ry1, px, ry1 + 7,
                            fill=LOOK.ACCENT, outline="", tags="ph")
        self.create_line(px, ry1, px, sy2, fill=LOOK.ACCENT, width=2, tags="ph")


# ============================================================
#  Diger paneller
# ============================================================
class Sidebar(GlassPanel):
    """Left menu: brand + tabs."""
    ITEMS = [("indir", "▶", "Convert"),
             ("ayarlar", "⚙", "Settings"),
             ("gecmis", "≡", "History")]

    def __init__(self, root, app):
        super().__init__(root, app, strong=False, radius=18)
        self.hover = None
        self.bind("<Button-1>", self._click)
        self.bind("<Motion>", self._motion)
        self.bind("<Leave>", lambda e: self._sethover(None))

    def _item_rects(self):
        w = self.rect[2]
        out = []
        y = 132
        for key, icon, label in self.ITEMS:
            out.append((key, icon, label, 10, y, w - 20, 46))
            y += 54
        return out

    def _hit(self, e):
        for key, icon, label, x, y, w, h in self._item_rects():
            if x <= e.x <= x + w and y <= e.y <= y + h:
                return key
        return None

    def _motion(self, e):
        self._sethover(self._hit(e))

    def _sethover(self, k):
        if k != self.hover:
            self.hover = k
            self.config(cursor="hand2" if k else "")
            self.request()

    def _click(self, e):
        k = self._hit(e)
        if k:
            self.app.set_tab(k)

    def draw_content(self):
        self.delete("fx")
        w, h = self.rect[2], self.rect[3]
        # marka
        self.create_text(22, 26, anchor="w", text="⧗", fill=LOOK.ACCENT,
                         font=(FONT, 15, "bold"), tags="fx")
        self.create_text(20, 52, anchor="w", text="STICKER", fill=LOOK.TXT,
                         font=(FONT, 17, "bold"), tags="fx")
        try:
            bw = 20 + tkfont.Font(font=(FONT, 17, "bold")).measure("STICKER ")
        except Exception:
            bw = 20 + 66
        self.create_text(bw, 52, anchor="w", text="MAKER", fill=LOOK.ACCENT,
                         font=(FONT, 17, "bold"), tags="fx")
        self.create_text(20, 76, anchor="w", text="FOR TELEGRAM", fill=LOOK.MUTED,
                         font=(FONT, 8, "bold"), tags="fx")
        self.create_line(20, 104, w - 20, 104, fill=LOOK.MUTED, tags="fx")

        for key, icon, label, x, y, iw, ih in self._item_rects():
            active = (self.app.tab == key)
            if active:
                if HAS_PIL:
                    ash = btn_shadow(int(iw), int(ih), ih // 2, LOOK.ACCENT,
                                     LOOK.mode, strong=False)
                    self._act_sh = ImageTk.PhotoImage(ash)
                    self.create_image(int(x - BTN_PAD), int(y - BTN_PAD),
                                      image=self._act_sh, anchor="nw", tags="fx")
                    im = btn_image(int(iw), int(ih), LOOK.ACCENT, ih // 2,
                                   primary=True, mode=LOOK.mode)
                    self._act_ph = ImageTk.PhotoImage(im)
                    self.create_image(int(x), int(y), image=self._act_ph,
                                      anchor="nw", tags="fx")
                else:
                    soft_rect(self, x, y, iw, ih, ih // 2, LOOK.ACCENT, tags="fx")
            elif self.hover == key:
                soft_rect(self, x, y, iw, ih, ih // 2, LOOK.CHIP, tags="fx")
            icol = LOOK.on_accent if active else LOOK.MUTED
            tcol = LOOK.on_accent if active else LOOK.MUTED
            self.create_text(x + 26, y + ih / 2, text=icon, fill=icol,
                             font=(FONT, 13, "bold"), tags="fx")
            self.create_text(x + 52, y + ih / 2, anchor="w", text=label, fill=tcol,
                             font=(FONT, 10, "bold" if active else "normal"), tags="fx")

        self.create_text(20, h - 18, anchor="w", text="TELEGRAM • VP9 • 512",
                         fill=LOOK.MUTED, font=(FONT, 7, "bold"), tags="fx")


class HistoryPanel(GlassPanel):
    def __init__(self, root, app):
        super().__init__(root, app)
        self.clear_btn = GButton(self, "hclr", 0, 0, 74, 26, "Temizle",
                                 app.clear_history, primary=False, small=True)
        self.bind("<Button-1>", self._click)

    def _rows(self):
        out = []
        y = 44
        for it in self.app.history[:12]:
            out.append((it, 14, y, self.rect[2] - 28, 40))
            y += 46
        return out

    def _click(self, e):
        for it, x, y, w, h in self._rows():
            if x <= e.x <= x + w and y <= e.y <= y + h:
                self.app.open_file_location(it["path"])
                return

    def draw_content(self):
        self.delete("fx")
        w, h = self.rect[2], self.rect[3]
        self.create_text(16, 18, anchor="w", text="HISTORY", fill=LOOK.MUTED,
                         font=(FONT, 8, "bold"), tags="fx")
        self.clear_btn.move(w - 16 - 74, 6)
        if not self.app.history:
            self.create_text(w / 2, h / 2, text="no stickers converted yet",
                             fill=LOOK.MUTED, font=(FONT, 9), tags="fx")
            return
        for it, x, y, rw, rh in self._rows():
            soft_rect(self, x, y, rw, rh, 10, LOOK.GLASS_FLAT2, tags="fx")
            self.create_text(x + 14, y + rh / 2, text="🎞", fill=LOOK.ACCENT,
                             font=(FONT, 12), tags="fx")
            name = os.path.basename(it["path"])
            if len(name) > 42:
                name = name[:39] + "…"
            self.create_text(x + 36, y + rh / 2 - 8, anchor="w", text=name,
                             fill=LOOK.TXT, font=(FONT, 9, "bold"), tags="fx")
            self.create_text(x + 36, y + rh / 2 + 9, anchor="w",
                             text=f"{it['kb']:.0f} KB  •  {it['time']}  •  click: open file location",
                             fill=LOOK.MUTED, font=(FONT, 8), tags="fx")


class TopBar(GlassPanel):
    def __init__(self, root, app):
        super().__init__(root, app, strong=False, radius=18)
        self.theme_btn = GButton(self, "themebtn", 0, 12, 104, 36, "🎨 Theme",
                                 app.toggle_settings, primary=False)
        self.mode_btn = GButton(self, "modebtn", 0, 12, 44, 36, "🌙",
                                app.toggle_mode, primary=False)
        self.eye_btn = GButton(self, "eyebtn", 0, 12, 44, 36, "💧",
                               app.toggle_pick, primary=False)
        self.tag_bind("chswatch", "<Button-1>", lambda e: app.clear_pick())

    def draw_content(self):
        self.delete("fx")
        w, h = self.rect[2], self.rect[3]
        titles = {"indir": ("CONVERT", "video → telegram sticker"),
                  "ayarlar": ("SETTINGS", "appearance & preferences"),
                  "gecmis": ("HISTORY", "converted stickers")}
        t, sub = titles.get(self.app.tab, ("", ""))
        self.create_text(18, h / 2 - 10, anchor="w", text=t,
                         fill=LOOK.TXT, font=(FONT, 16, "bold"), tags="fx")
        self.create_text(18, h / 2 + 12, anchor="w", text=sub,
                         fill=LOOK.MUTED, font=(FONT, 8), tags="fx")
        self.theme_btn.move(w - 18 - 104, (h - 36) // 2)
        mx = w - 18 - 104 - 8 - 44
        self.mode_btn.set_text("☀️" if LOOK.mode == "dark" else "🌙")
        self.mode_btn.move(mx, (h - 36) // 2, 44, 36)

        show = (self.app.tab == "indir" and self.app.sess is not None)
        self.eye_btn.visible = show
        self.eye_btn.enabled = True
        self.eye_btn.primary = self.app.gs_picking
        ex = mx - 8 - 44
        self.eye_btn.move(ex, (h - 36) // 2, 44, 36)
        if not show:
            return
        sw = 148
        sx = ex - 8 - sw
        sy = (h - 36) // 2
        soft_rect(self, sx, sy, sw, 36, 11, LOOK.GLASS_FLAT2,
                  tags=("fx", "chswatch"), store="_sw")
        col = self.app.gs_picked or self.app.gs_detected
        # renk karesi
        qx, qy = sx + 10, sy + 9
        if col and self.app.gs_var.get() != "off":
            self.create_rectangle(qx, qy, qx + 18, qy + 18, fill="#" + col,
                                  outline=LOOK.EDGE, tags=("fx", "chswatch"))
        else:
            self.create_rectangle(qx, qy, qx + 18, qy + 18, fill=LOOK.GLASS_FLAT,
                                  outline=LOOK.EDGE, tags=("fx", "chswatch"))
            self.create_line(qx, qy + 18, qx + 18, qy, fill=LOOK.ERR,
                             tags=("fx", "chswatch"))
        self.create_text(qx + 26, sy + 11, anchor="w", text="CHROMA",
                         fill=LOOK.MUTED, font=(FONT, 7, "bold"),
                         tags=("fx", "chswatch"))
        if self.app.gs_var.get() == "off":
            val, vc = "off", LOOK.MUTED
        elif self.app.gs_picked:
            val, vc = "#" + self.app.gs_picked, LOOK.TXT
        elif self.app.gs_detected:
            val, vc = "auto  #" + self.app.gs_detected, LOOK.TXT
        else:
            val, vc = "not detected", LOOK.MUTED
        self.create_text(qx + 26, sy + 25, anchor="w", text=val, fill=vc,
                         font=(FONT, 9, "bold"), tags=("fx", "chswatch"))


class SettingsPanel(GlassPanel):
    def __init__(self, root, app):
        super().__init__(root, app)
        self.seg_alpha = GSegmented(self, "salpha", 0, 0, 10, 30,
                                    [("Auto", "auto"), ("Transparent", "alpha"),
                                     ("Opaque", "opaque")], app.alpha_var,
                                    on_change=lambda v: app._persist())
        self.seg_gs = GSegmented(self, "sgs", 0, 0, 10, 30,
                                 [("Auto", "auto"), ("Remove", "on"),
                                  ("Off", "off")], app.gs_var,
                                 on_change=lambda v: (app.on_gs_change(v),
                                                      app._persist()))
        self.seg_fps = GSegmented(self, "sfps", 0, 0, 10, 30,
                                  [("Oto", "auto"), ("30", "30"),
                                   ("24", "24"), ("15", "15")], app.fps_var,
                                  on_change=lambda v: app._persist())
        self.seg_crop = GSegmented(self, "scrop", 0, 0, 10, 30,
                                   [("Fit", "off"), ("Square 512", "crop")],
                                   app.crop_var,
                                   on_change=lambda v: (app.on_crop_mode(v),
                                                        app._persist()))
        self.seg_dur = GSegmented(self, "sdur", 0, 0, 10, 30,
                                  [("Trim", "custom"), ("First 3s", "start0"),
                                   ("Speed up", "fit")], app.durm_var,
                                  on_change=lambda v: (app.timeline.request(),
                                                       app._persist()))
        self.pick_btn = GButton(self, "pickbtn", 0, 0, 10, 40, "PICK FILE",
                                app.pick_files, primary=False)
        self.conv_btn = GButton(self, "convbtn", 0, 0, 10, 50, "CONVERT",
                                app.convert_clicked, primary=True)

    def draw_content(self):
        self.delete("fx")
        w, h = self.rect[2], self.rect[3]
        pad = 16
        iw = w - 2 * pad
        y = 12
        STEP = 46

        s = self.app.sess
        has_file = s is not None
        is_vid = has_file and s.get("kind") != "image"

        def block(txt, seg, yy, sub=None, show=True):
            seg.visible = show
            if not show:
                seg.draw()
                return yy
            self.create_text(pad, yy + 4, anchor="w", text=txt, fill=LOOK.MUTED,
                             font=(FONT, 8, "bold"), tags="fx")
            if sub:
                try:
                    off = tkfont.Font(font=(FONT, 8, "bold")).measure(txt) + 5
                except Exception:
                    off = len(txt) * 6 + 5
                self.create_text(pad + off, yy + 4, anchor="w", text=sub,
                                 fill=LOOK.MUTED, font=(FONT, 8), tags="fx")
            seg.move(pad, yy + 14, iw, 32)
            return yy + STEP

        y = block("BACKGROUND", self.seg_alpha, y, show=has_file)
        y = block("GREEN SCREEN", self.seg_gs, y, sub="(background removal)",
                  show=has_file)
        y = block("CROP", self.seg_crop, y, show=has_file)
        y = block("IF LONGER THAN 3S", self.seg_dur, y, show=is_vid)
        y = block("FRAME RATE (FPS)", self.seg_fps, y, show=is_vid)

        if not has_file:
            self.create_text(w / 2, y + 26, text="⚙", fill=LOOK.MUTED,
                             font=(FONT, 22), tags="fx")
            self.create_text(w / 2, y + 58, text="Settings appear when a file is added",
                             fill=LOOK.MUTED, font=(FONT, 9), tags="fx")

        by = h - 116
        self.pick_btn.move(pad, by, iw, 40)
        self.conv_btn.move(pad, by + 48, iw, 52)
        self.create_text(pad, h - 12, anchor="w",
                         text="output: 512px • VP9 • max 256KB • 0.3–3s",
                         fill=LOOK.MUTED, font=(FONT, 8), tags="fx")


class SaveBar(GlassPanel):
    def __init__(self, root, app):
        super().__init__(root, app)
        self.open_btn = GButton(self, "openbtn", 0, 0, 104, 34, "📂 Open Folder",
                                app.open_out, primary=False, small=True)
        self.reset_btn = GButton(self, "resetbtn", 0, 0, 78, 34, "↺ Reset",
                                 app.reset_out, primary=False, small=True)
        self.pickd_btn = GButton(self, "pickdbtn", 0, 0, 104, 34, "Pick Folder",
                                 app.pick_out, primary=True, small=True)

    def draw_content(self):
        self.delete("fx")
        w, h = self.rect[2], self.rect[3]
        self.create_line(16, 3, w - 16, 3, fill=LOOK.ACCENT, width=3, tags="fx")
        self.create_text(20, h / 2, text="📁", fill=LOOK.ACCENT,
                         font=(FONT, 15), tags="fx")
        self.create_text(48, h / 2 - 10, anchor="w", text="SAVE LOCATION",
                         fill=LOOK.MUTED, font=(FONT, 8, "bold"), tags="fx")
        path = self.app.out_dir or "Next to source (same folder as video)"
        fg = LOOK.ACCENT if self.app.out_dir else LOOK.MUTED
        maxlen = max(10, (w - 380) // 7)
        if len(path) > maxlen:
            path = "…" + path[-(maxlen - 1):]
        self.create_text(48, h / 2 + 10, anchor="w", text=path,
                         fill=fg, font=(FONT, 10, "bold"), tags="fx")
        x = w - 16 - 104
        self.pickd_btn.move(x, (h - 34) // 2)
        x -= 80
        self.reset_btn.move(x, (h - 34) // 2)
        x -= 112
        self.open_btn.move(x, (h - 34) // 2)


class LogPanel(GlassPanel):
    def __init__(self, root, app):
        super().__init__(root, app)
        self.clear_btn = GButton(self, "clrbtn", 0, 0, 74, 26, "🗑 Clear",
                                 app.clear_log, primary=False, small=True)
        self.txt = tk.Text(self, relief="flat", wrap="word",
                           font=("Consolas", 9), padx=12, pady=8,
                           state="disabled", highlightthickness=0, bd=0)
        self.win = None

    def draw_content(self):
        self.delete("fx")
        w, h = self.rect[2], self.rect[3]
        self.create_text(16, 16, anchor="w", text="OUTPUT", fill=LOOK.MUTED,
                         font=(FONT, 8, "bold"), tags="fx")
        self.clear_btn.move(w - 16 - 74, 4)
        self.txt.config(bg=LOOK.GLASS_FLAT2, fg=LOOK.TXT, insertbackground=LOOK.TXT)
        for tag, c in (("ok", LOOK.OK), ("err", LOOK.ERR),
                       ("muted", LOOK.MUTED), ("acc", LOOK.ACCENT)):
            self.txt.tag_config(tag, foreground=c)
        if self.win is None:
            self.win = self.create_window(12, 34, anchor="nw", window=self.txt,
                                          tags="txtwin")
        self.coords(self.win, 12, 34)
        self.itemconfig(self.win, width=w - 24, height=h - 46)
        self.tag_raise("txtwin")


class SettingsPopover(GlassPanel):
    """Katman ustune katman: tema/gorunum ayar sayfasi."""

    def __init__(self, root, app):
        super().__init__(root, app, strong=True, radius=20)
        self.mode_seg = GSegmented(self, "modeseg", 0, 0, 10, 36,
                                   [("Dark", "dark"), ("Light", "light")],
                                   app.mode_var, on_change=app.on_mode_change)
        self.close_btn = GButton(self, "closebtn", 0, 0, 84, 32, "Bitti",
                                 app.toggle_settings, primary=True, small=True)
        self.bind("<Button-1>", self._dots_click, add="+")

    def _dot_geo(self):
        pad = 18
        return [(pad + 18 + i * 42, 66) for i in range(len(THEME_ORDER))]

    def _dots_click(self, e):
        for i, (cx, cy) in enumerate(self._dot_geo()):
            if (e.x - cx) ** 2 + (e.y - cy) ** 2 <= 15 ** 2:
                self.app.on_theme_change(THEME_ORDER[i])
                return

    def draw_content(self):
        self.delete("fx")
        w, h = self.rect[2], self.rect[3]
        pad = 18
        self.create_text(pad, 22, anchor="w", text="APPEARANCE SETTINGS",
                         fill=LOOK.TXT, font=(FONT, 11, "bold"), tags="fx")
        self.create_text(pad, 44, anchor="w", text="ACCENT COLOR",
                         fill=LOOK.MUTED, font=(FONT, 8, "bold"), tags="fx")
        for name, (cx, cy) in zip(THEME_ORDER, self._dot_geo()):
            acc = THEMES[name]["accent"]
            if name == LOOK.theme:
                self.create_oval(cx - 15, cy - 15, cx + 15, cy + 15,
                                 outline=LOOK.TXT, width=2, tags="fx")
            self.create_oval(cx - 11, cy - 11, cx + 11, cy + 11,
                             fill=acc, outline="", tags="fx")
        self.create_text(pad, 100, anchor="w", text="MODE",
                         fill=LOOK.MUTED, font=(FONT, 8, "bold"), tags="fx")
        self.mode_seg.move(pad, 110, w - 2 * pad, 34)
        self.close_btn.move(w - pad - 84, h - 44)
        self.create_text(pad, h - 28, anchor="w",
                         text="preferences saved automatically",
                         fill=LOOK.MUTED, font=(FONT, 8), tags="fx")


class Toast(GlassPanel):
    def __init__(self, root, app, text, kind="ok"):
        super().__init__(root, app, strong=True, radius=16)
        self.text = text
        self.kind = kind

    def draw_content(self):
        self.delete("fx")
        w, h = self.rect[2], self.rect[3]
        col = LOOK.OK if self.kind == "ok" else LOOK.ERR
        self.create_line(4, 12, 4, h - 12, fill=col, width=4, tags="fx")
        self.create_text(20, h / 2, anchor="w", text=self.text, fill=LOOK.TXT,
                         font=(FONT, 10, "bold"), tags="fx")


class ConfirmDialog(GlassPanel):
    """Ayni isimde dosya uyarisi: yeni isim / uzerine yaz / iptal."""

    def __init__(self, root, app):
        super().__init__(root, app, strong=True, radius=20)
        self.msg = ""
        self.b_no = GButton(self, "cdno", 0, 0, 10, 40, "Cancel",
                            lambda: app._conflict_pick(None),
                            primary=False, small=True)
        self.b_ow = GButton(self, "cdow", 0, 0, 10, 40, "Overwrite",
                            lambda: app._conflict_pick("overwrite"),
                            primary=False, small=True)
        self.b_ren = GButton(self, "cdren", 0, 0, 10, 40, "Save As New",
                             lambda: app._conflict_pick("rename"),
                             primary=True, small=True)

    def draw_content(self):
        self.delete("fx")
        w, h = self.rect[2], self.rect[3]
        self.create_text(20, 26, anchor="w", text="⚠  A FILE WITH THIS NAME EXISTS",
                         fill=LOOK.TXT, font=(FONT, 12, "bold"), tags="fx")
        self.create_text(20, 54, anchor="w", text=self.msg,
                         fill=LOOK.MUTED, font=(FONT, 9), tags="fx")
        self.create_text(20, 74, anchor="w",
                         text="If you pick a new name, a number like _2, _3 is added to the filename.",
                         fill=LOOK.MUTED, font=(FONT, 8), tags="fx")
        bw = (w - 40 - 16) // 3
        y = h - 56
        self.b_no.move(20, y, bw, 40)
        self.b_ow.move(20 + bw + 8, y, bw, 40)
        self.b_ren.move(20 + 2 * (bw + 8), y, w - 20 - (20 + 2 * (bw + 8)), 40)


# ============================================================
#  App
# ============================================================
def load_cfg():
    try:
        with open(CFG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_cfg(d):
    try:
        with open(CFG_PATH, "w", encoding="utf-8") as f:
            json.dump(d, f)
    except Exception:
        pass


class App:
    def __init__(self, root):
        self.root = root
        self.q = queue.Queue()
        self.busy = False
        self.loading = False
        self.log_lines = []
        cfg = load_cfg()
        if cfg.get("v") != 8:          # eski ayar dosyasi: yeni varsayilana don
            cfg.update({"theme": "Midnight", "mode": "dark", "v": 8,
                        "alpha": "auto", "gs": "auto", "fps": "auto",
                        "crop_m": "crop", "dur": "custom"})
            save_cfg(cfg)              # sifirlamayi hemen diske yaz
        self.out_dir = cfg.get("out_dir") or None
        self.last_out_dir = None
        LOOK.set(cfg.get("theme", "Midnight") if cfg.get("theme") in THEMES else "Midnight",
                 cfg.get("mode", "dark") if cfg.get("mode") in MODES else "dark")

        self.sess = None
        self.idx = 1
        self.playing = False
        self.play_t = 0.0
        self._play_t0 = 0.0
        self._play_start = 0.0
        self.win_start = 0.0
        self.win_len = MAX_DUR
        self.crop_on = False
        self.crop = {"cf": 1.0, "cx": 0.5, "cy": 0.5}
        self.gs_detected = None
        self.gs_picked = None
        self.gs_picking = False
        self.gs_sim = float(cfg.get("gs_sim", 0.16))
        self.tab = "indir"
        self.history = []
        self.last_out_file = None
        self._dirty = set()
        self._resize_job = None
        self.settings_open = False

        self.alpha_var = tk.StringVar(value="auto")
        self.gs_var = tk.StringVar(value="auto")
        self.fps_var = tk.StringVar(value="auto")
        self.crop_var = tk.StringVar(value="crop")
        self.durm_var = tk.StringVar(value="custom")
        self.mode_var = tk.StringVar(value=LOOK.mode)

        # son ayarlar hatirlanir
        def _r(var, key, allowed):
            v = cfg.get(key)
            if v in allowed:
                var.set(v)
        _r(self.alpha_var, "alpha", ("auto", "alpha", "opaque"))
        _r(self.gs_var, "gs", ("auto", "on", "off"))
        _r(self.fps_var, "fps", ("auto", "30", "24", "15"))
        _r(self.crop_var, "crop_m", ("off", "crop"))
        _r(self.durm_var, "dur", ("custom", "start0", "fit"))
        self.crop_on = (self.crop_var.get() == "crop")
        self.adv_open = True
        self._undo = []

        root.title("Make Telegram Stickers Easily")
        root.geometry("1280x880")
        root.minsize(1180, 820)
        pick_font(root)

        self.anim = Anim(root)
        self.anim.add_ticker(self._play_ticker)
        self.backdrop = Backdrop()
        self.bgc = tk.Canvas(root, highlightthickness=0, bd=0)
        self.bgc.pack(fill="both", expand=True)

        self._make_panels()
        root.bind("<Configure>", self._on_resize)
        self._bind_keys()
        self.root.after(60, self._first_layout)
        self.root.after(120, self._pump)

    # ------------------------------------------------ panel kurulum / yerlesim
    def _make_panels(self):
        self.sidebar = Sidebar(self.bgc, self)
        self.topbar = TopBar(self.bgc, self)
        self.playerp = PlayerPanel(self.bgc, self)
        self.player = self.playerp
        self.settingsp = SettingsPanel(self.bgc, self)
        self.timeline = TimelinePanel(self.bgc, self)
        self.savebar = SaveBar(self.bgc, self)
        self.logp = LogPanel(self.bgc, self)
        self.historyp = HistoryPanel(self.bgc, self)
        self.pop = SettingsPopover(self.bgc, self)
        self.dialog = ConfirmDialog(self.bgc, self)
        self._conflict_choice = None
        self.panels = [self.sidebar, self.topbar, self.playerp, self.settingsp,
                       self.timeline, self.savebar, self.logp, self.historyp]
        if HAS_DND:
            for tgt in (self.playerp, self.timeline):
                tgt.drop_target_register(DND_FILES)
                tgt.dnd_bind("<<Drop>>", self._on_drop)
            self.playerp.dnd_bind("<<DropEnter>>", lambda e: self.playerp.hot(True))
            self.playerp.dnd_bind("<<DropLeave>>", lambda e: self.playerp.hot(False))

    def set_tab(self, tab):
        if tab == self.tab:
            return
        self.tab = tab
        self.settings_open = (tab == "ayarlar")
        self._layout()
        # yumusak giris: paneller hafif asagidan yukari suzulur
        panels = [p for p in self.panels + [self.pop]
                  if p.winfo_manager() == "place" and p is not self.sidebar]
        ys = [(p, p.rect[1]) for p in panels]

        def cb(t):
            for p, y0 in ys:
                try:
                    p.place_configure(y=int(y0 + 14 * (1 - t)))
                except Exception:
                    pass
        self.anim.tween(0.26, cb)

    def _first_layout(self):
        self.root.update_idletasks()
        self._layout()
        greet = "Ready. Drop a video, preview, trim, crop, CONVERT."
        if not FFMPEG:
            self.log("✗ ffmpeg not found! C:\\ffmpeg\\bin must be on PATH.", "err")
        else:
            self.log(greet, "muted")
        if INSTALLED:
            self.log("Installed component(s): " + ", ".join(INSTALLED), "ok")
        if not HAS_DND:
            self.log("(drag-and-drop off; use PICK FILE)", "muted")

    def _layout(self):
        W = max(300, self.root.winfo_width())
        H = max(300, self.root.winfo_height())
        pad = 18
        SBW = 210
        cx = pad + SBW + 16
        cw = W - cx - pad

        # 1) yerlesimi hesapla
        rects = {"sidebar": (pad, 14, SBW, H - 28),
                 "topbar": (cx, 14, cw, 64)}
        y = 14 + 64 + 14
        if self.tab == "indir":
            leftw = int(cw * 0.60) - 8
            ph = 400
            rects["playerp"] = (cx, y, leftw, ph)
            rects["settingsp"] = (cx + leftw + 16, y, cw - leftw - 16, ph)
            y += ph + 14
            rects["timeline"] = (cx, y, cw, 134)
            y += 134 + 14
            rects["savebar"] = (cx, y, cw, 66)
            y += 66 + 14
            rects["logp"] = (cx, y, cw, max(80, H - y - pad))
        elif self.tab == "gecmis":
            rects["historyp"] = (cx, y, cw, H - y - pad)
        elif self.tab == "ayarlar":
            rects["pop"] = (cx, y, min(460, cw), 240)
            rects["savebar"] = (cx, y + 254, cw, 66)

        # 2) arkaplani golgelerle birlikte pisir
        try:
            self.backdrop.render(W, H, shadow_rects=list(rects.values()))
        except Exception:
            log_exc("backdrop")
            return
        self.bgc.delete("bg")
        self.bgc.create_image(0, 0, image=self.backdrop.photo, anchor="nw", tags="bg")
        self.bgc.tag_lower("bg")

        # 3) panelleri yerlestir + tazele
        for p in self.panels:
            p.place_forget()
        self.pop.place_forget()
        self.dialog.place_forget()
        for name, rect in rects.items():
            p = getattr(self, name)
            p.set_geometry(*rect)
            if p is self.timeline:
                p.clear_thumbs()
            wlift(p)
            try:
                p.refresh()
            except Exception:
                log_exc(f"refresh {name}")
        if self.tab == "indir":
            self._restore_log()

    def _on_resize(self, e):
        if e.widget is not self.root:
            return
        if self._resize_job:
            self.root.after_cancel(self._resize_job)
        self._resize_job = self.root.after(180, self._layout)

    # ------------------------------------------------ dirty-coalesced cizim
    def mark_dirty(self, panel):
        if not self._dirty:
            self.root.after_idle(self._flush)
        self._dirty.add(panel)

    def _flush(self):
        for p in list(self._dirty):
            try:
                p.delete("fx")
                p.draw_content()
            except Exception:
                pass
        self._dirty.clear()

    # ------------------------------------------------ tema / mod / popover
    def toggle_settings(self):
        self.set_tab("ayarlar" if self.tab != "ayarlar" else "indir")

    def clear_history(self):
        self.history = []
        self.historyp.request()

    def on_theme_change(self, name):
        if name == LOOK.theme:
            return
        LOOK.set(name, LOOK.mode)
        self._persist()
        self._relook()

    def toggle_adv(self):
        self.adv_open = not self.adv_open
        self._persist()
        self.mark_dirty(self.settingsp)

    def toggle_mode(self):
        new = "light" if LOOK.mode == "dark" else "dark"
        self.mode_var.set(new)
        try:
            self.pop.mode_seg.knob_x = None
        except Exception:
            pass
        self.on_mode_change(new)

    def on_mode_change(self, mode):
        LOOK.set(LOOK.theme, mode)
        self._persist()
        self._relook()

    def _relook(self):
        try:
            self.playerp._cache.clear()
        except Exception:
            pass
        self._layout()
        self.playerp.play_btn.set_text(
            "⏸  Stop" if self.playing else "▶  Play Selection")

    def _persist(self):
        save_cfg({"v": 8, "theme": LOOK.theme, "mode": LOOK.mode,
                  "out_dir": self.out_dir, "gs_sim": self.gs_sim,
                  "alpha": self.alpha_var.get(), "gs": self.gs_var.get(),
                  "fps": self.fps_var.get(), "crop_m": self.crop_var.get(),
                  "dur": self.durm_var.get(), "adv": self.adv_open})

    # ------------------------------------------------ log
    def log(self, msg, tag=None):
        self.log_lines.append((msg, tag))
        try:
            t = self.logp.txt
            t.config(state="normal")
            t.insert("end", msg + "\n", tag or "")
            t.see("end")
            t.config(state="disabled")
        except Exception:
            pass

    def _restore_log(self):
        t = self.logp.txt
        t.config(state="normal")
        t.delete("1.0", "end")
        for msg, tag in self.log_lines:
            t.insert("end", msg + "\n", tag or "")
        t.see("end")
        t.config(state="disabled")

    def clear_log(self):
        self.log_lines = []
        t = self.logp.txt
        t.config(state="normal")
        t.delete("1.0", "end")
        t.config(state="disabled")

    # ------------------------------------------------ kayit yeri
    def pick_out(self):
        d = filedialog.askdirectory(title="Sticker'lar nereye kaydedilsin?")
        if d:
            self.out_dir = d
            self._persist()
            self.savebar.request() if hasattr(self.savebar, "request") else None
            self.mark_dirty(self.savebar)

    def reset_out(self):
        self.out_dir = None
        self._persist()
        self.mark_dirty(self.savebar)

    def open_out(self):
        d = self.out_dir or self.last_out_dir
        if not d or not os.path.isdir(d):
            self.log("No folder to open (convert something first).", "muted")
            return
        try:
            if sys.platform == "win32":
                os.startfile(d)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", d])
            else:
                subprocess.Popen(["xdg-open", d])
        except Exception as e:
            self.log(f"Couldn't open folder: {e}", "err")

    def open_file_location(self, path):
        """Explorer'i dosya SECILI halde acar."""
        if not path or not os.path.exists(path):
            self.log("File not found (may have been moved).", "muted")
            return
        try:
            if sys.platform == "win32":
                subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-R", path])
            else:
                subprocess.Popen(["xdg-open", os.path.dirname(path)])
        except Exception as e:
            self.log(f"Couldn't open location: {e}", "err")

    def open_last_location(self):
        self.open_file_location(self.last_out_file)

    # ------------------------------------------------ toast
    def toast(self, text, kind="ok"):
        W = self.root.winfo_width()
        H = self.root.winfo_height()
        tw, th = min(420, max(240, 16 * len(text) // 2 + 60)), 56
        t = Toast(self.bgc, self, text, kind)
        t.set_geometry(W - tw - 22, H + 10, tw, th)
        t.refresh()
        wlift(t)
        y_end = H - th - 22

        def slide(p):
            t.place_configure(y=int(H + 10 - (H + 10 - y_end) * p))
        self.anim.tween(0.28, slide)

        def gone():
            def out(p):
                t.place_configure(y=int(y_end + (H + 20 - y_end) * p))
            self.anim.tween(0.24, out, done=t.destroy)
        self.root.after(2600, gone)

    # ------------------------------------------------ dosya yukleme
    def _on_drop(self, event):
        self.playerp.hot(False)
        self._enqueue(self.root.tk.splitlist(event.data))

    def pick_files(self):
        p = filedialog.askopenfilenames(
            title="Pick file",
            filetypes=[("Video / Image",
                        "*.mov *.mp4 *.webm *.mkv *.avi *.m4v *.gif "
                        "*.png *.jpg *.jpeg *.webp *.bmp"),
                       ("All files", "*.*")])
        self._enqueue(p)

    def _enqueue(self, paths):
        if self.busy or self.loading:
            self.log("⏳ Busy, send when done.", "muted")
            return
        vids = [p for p in paths
                if p.lower().endswith(VIDEO_EXT) or is_image(p)]
        if not vids:
            self.log("✗ No video or image file.", "err")
            return
        needs_ffmpeg = any(not is_image(p) for p in vids)
        if needs_ffmpeg and not FFMPEG:
            self.log("✗ ffmpeg required for video files.", "err")
            return
        if all(is_image(p) for p in vids) and not HAS_PIL:
            self.log("✗ Pillow required for static stickers.", "err")
            return
        self._stop_play()
        self.loading = True
        self.sess = None
        self.settingsp.conv_btn.set_enabled(False)
        self.playerp.set_mode("loading")
        self.topbar.request()
        self.mark_dirty(self.settingsp)
        self.timeline.clear_thumbs()
        self.timeline.request()
        self.log(f"\nloading: {os.path.basename(vids[0])}", "acc")
        threading.Thread(target=self._load_worker, args=(vids,), daemon=True).start()

    def _load_worker(self, vids):
        tmpdir = tempfile.mkdtemp(prefix="tgsticker_")
        _TMP_DIRS.append(tmpdir)
        if is_image(vids[0]):
            try:
                im = Image.open(vids[0]).convert("RGBA")
                im.thumbnail((480, 300), Image.LANCZOS)
                im.save(os.path.join(tmpdir, "f_0001.png"))
            except Exception:
                log_exc("img load")
                self.q.put(("load_fail", tmpdir))
                return
            self.q.put(("loaded", {"dir": tmpdir, "n": 1, "pfps": 1.0, "dur": 0.0,
                                   "kind": "image", "files": vids,
                                   "name": os.path.basename(vids[0])}))
            return
        n, pfps, dur = extract_preview(vids[0], tmpdir)
        if n == 0:
            self.q.put(("load_fail", tmpdir))
            return
        self.q.put(("loaded", {"dir": tmpdir, "n": n, "pfps": pfps, "dur": dur,
                               "kind": "video", "files": vids,
                               "name": os.path.basename(vids[0])}))

    def _on_loaded(self, sess):
        old = self.sess
        self.sess = sess
        self.loading = False
        self.idx = 1
        self.play_t = 0.0
        self.win_start = 0.0
        self.win_len = min(MAX_DUR, sess["dur"])
        self.crop = {"cf": 1.0, "cx": 0.5, "cy": 0.5}
        self.gs_detected = detect_chroma(os.path.join(sess["dir"], "f_0001.png"))
        self.gs_picked = None
        self.gs_picking = False
        self.playerp.config(cursor="hand2")
        self.playerp.set_mode("video")
        self.timeline.clear_thumbs()
        self.timeline.request()
        self.topbar.request()
        self.settingsp.conv_btn.set_enabled(True)
        self._sync_conv_btn()
        self.mark_dirty(self.settingsp)
        extra = (f", +{len(sess['files']) - 1} dosya kuyrukta"
                 if len(sess["files"]) > 1 else "")
        if sess.get("kind") == "image":
            self.log(f"  ready: static image{extra}", "ok")
            self.log("  crop / set chroma, press CONVERT → WebP sticker.", "muted")
        else:
            self.log(f"  ready: {fmt_t(sess['dur'])}{extra}", "ok")
            self.log("  set the window on the timeline, preview with ▶, press CONVERT.", "muted")
        if self.gs_detected and self.gs_var.get() != "off":
            self.log(f"  🟢 green/blue screen detected (#{self.gs_detected}) → "
                     "background will be removed. Use 💧 to pick the exact color.", "ok")
        if old and old.get("dir"):
            shutil.rmtree(old["dir"], ignore_errors=True)

    def finfo_text(self):
        s = self.sess
        if not s:
            return ""
        extra = f"  •  +{len(s['files']) - 1} dosya" if len(s["files"]) > 1 else ""
        return f"🎬 {s['name']}{extra}"

    # ------------------------------------------------ oynatma (zaman bazli, yumusak)
    def cur_t(self):
        if not self.sess:
            return 0.0
        if self.playing:
            return self.play_t
        return (self.idx - 1) / self.sess["pfps"]

    def _sel_range(self):
        s = self.sess
        mode = self.durm_var.get()
        if mode == "custom":
            return self.win_start, min(self.win_start + self.win_len, s["dur"])
        if mode == "start0":
            return 0.0, min(MAX_DUR, s["dur"])
        return 0.0, s["dur"]

    def seek(self, t):
        if not self.sess:
            return
        s = self.sess
        self.play_t = t
        self._play_start = t
        self._play_t0 = time.perf_counter()
        self.idx = max(1, min(s["n"], int(t * s["pfps"]) + 1))
        self.playerp.request()
        self.timeline.request()

    def step(self, d):
        if not self.sess:
            return
        self._stop_play()
        self.idx = max(1, min(self.sess["n"], self.idx + d))
        self.playerp.request()
        self.timeline.request()

    def toggle_play(self):
        if not self.sess or self.sess.get("kind") == "image":
            return
        if self.playing:
            self._stop_play()
            return
        start, end = self._sel_range()
        cur = self.cur_t()
        if not (start <= cur < end):
            cur = start
        self.play_t = cur
        self._play_start = cur
        self._play_t0 = time.perf_counter()
        self.playing = True
        self.playerp.play_btn.set_text("⏸  Stop")

    def _stop_play(self):
        if not self.playing:
            try:
                self.playerp.play_btn.set_text("▶  Play Selection")
            except Exception:
                pass
            return
        self.playing = False
        s = self.sess
        if s:
            self.idx = max(1, min(s["n"], int(self.play_t * s["pfps"]) + 1))
        try:
            self.playerp.play_btn.set_text("▶  Play Selection")
        except Exception:
            pass

    def _play_ticker(self, now):
        if not self.playing or not self.sess:
            return
        s = self.sess
        start, end = self._sel_range()
        span = max(0.05, end - start)
        t = self._play_start + (now - self._play_t0)
        while t >= end:
            t -= span
            self._play_start = start
            self._play_t0 = now - (t - start)
        self.play_t = max(start, t)
        new_idx = max(1, min(s["n"], int(self.play_t * s["pfps"]) + 1))
        if new_idx != self.idx:
            self.idx = new_idx
            self.playerp.request()
        self.timeline.update_playhead()

    # ------------------------------------------------ pencere / kirpma
    def can_trim(self):
        return self.sess and self.durm_var.get() == "custom"

    def push_undo(self):
        st = {"ws": self.win_start, "wl": self.win_len,
              "crop": dict(self.crop), "con": self.crop_on}
        if self._undo and self._undo[-1] == st:
            return
        self._undo.append(st)
        del self._undo[:-20]

    def undo(self):
        if not self._undo:
            return
        st = self._undo.pop()
        self.win_start, self.win_len = st["ws"], st["wl"]
        self.crop = dict(st["crop"])
        if st["con"] != self.crop_on:
            self.crop_on = st["con"]
            self.crop_var.set("crop" if self.crop_on else "off")
            try:
                self.settingsp.seg_crop.knob_x = None
            except Exception:
                pass
            self.mark_dirty(self.settingsp)
        self.timeline.request()
        self.playerp.request()
        self.log("↩ undone", "muted")

    def force_custom_mode(self):
        """Timeline'a dokunulunca kesim modunu ac."""
        if self.durm_var.get() == "custom":
            return
        self.durm_var.set("custom")
        try:
            self.settingsp.seg_dur.knob_x = None
        except Exception:
            pass
        self.mark_dirty(self.settingsp)

    def set_window(self, start, length):
        self.win_start = max(0.0, start)
        self.win_len = max(MIN_SEL, min(length, MAX_DUR))
        self.timeline.request()

    def on_crop_mode(self, val):
        self.crop_on = (val == "crop")
        if self.crop_on:
            self.crop = {"cf": 1.0, "cx": 0.5, "cy": 0.5}
        self.playerp.request()

    def clamp_crop(self, pw, ph):
        c = self.crop
        c["cf"] = max(0.15, min(1.0, c["cf"]))
        side = c["cf"] * min(pw, ph)
        hxx = (side / 2) / pw
        hyy = (side / 2) / ph
        c["cx"] = min(1 - hxx, max(hxx, c["cx"]))
        c["cy"] = min(1 - hyy, max(hyy, c["cy"]))

    def _sync_conv_btn(self):
        if not self.sess:
            self.settingsp.conv_btn.set_text("CONVERT")
            return
        n = len(self.sess["files"])
        self.settingsp.conv_btn.set_text(f"CONVERT ({n} files)" if n > 1 else "CONVERT")

    # ------------------------------------------------ cevirme
    def toggle_pick(self):
        if not self.sess or self.playerp.mode != "video":
            self.log("Load a video first, then click a color with 💧.", "muted")
            return
        self.gs_picking = not self.gs_picking
        self.playerp._cache.clear()
        self.playerp.config(cursor="tcross" if self.gs_picking else "hand2")
        if self.gs_picking:
            self.log("💧 eyedropper active: click the color to remove in the video.", "acc")
        self.topbar.request()
        self.playerp.request()

    def chroma_picked(self, col):
        self.gs_picked = col
        self.gs_picking = False
        self.playerp.config(cursor="hand2")
        if self.gs_var.get() == "off":
            self.gs_var.set("on")
            self.settingsp.seg_gs.knob_x = None
            self.mark_dirty(self.settingsp)
        self.log(f"  🎯 chroma picked: #{col} → this color will be removed", "ok")
        self.playerp._cache.clear()
        self.topbar.request()
        self.playerp.request()

    def clear_pick(self):
        changed = self.gs_picking or self.gs_picked
        if self.gs_picking:
            self.gs_picking = False
            self.playerp.config(cursor="hand2")
        if self.gs_picked:
            self.gs_picked = None
            self.log("  chroma selection cleared (back to auto detection)", "muted")
        if changed:
            self.playerp._cache.clear()
            self.topbar.request()
            self.playerp.request()

    def on_gs_change(self, val):
        self.playerp._cache.clear()
        self.playerp.request()
        self.topbar.request()

    def preview_chroma(self):
        """Onizlemede uygulanacak (renk, sim) ya da None."""
        if self.gs_var.get() == "off" or self.gs_picking:
            return None
        col = self.gs_picked or self.gs_detected
        return (col, self.gs_sim) if col else None

    def _chroma(self):
        v = self.gs_var.get()
        if v == "off":
            return None
        col = self.gs_picked or self.gs_detected
        if v == "on":
            col = col or "00D800"
        if not col:
            return None
        return {"c": col, "sim": self.gs_sim}

    def _cfg(self):
        return {"alpha": self.alpha_var.get(), "dur_mode": self.durm_var.get(),
                "start": self.win_start, "length": self.win_len,
                "out_dir": self.out_dir,
                "fps": self.fps_var.get(),
                "crop": dict(self.crop) if self.crop_on else None,
                "chroma": self._chroma()}

    def _expected_out(self, src):
        d = self.out_dir or os.path.dirname(src)
        ext = "_sticker.webp" if is_image(src) else "_sticker.webm"
        return os.path.join(d, os.path.splitext(os.path.basename(src))[0] + ext)

    def convert_clicked(self):
        if self.busy or not self.sess:
            return
        vids = self.sess["files"]
        conflicts = [v for v in vids if os.path.exists(self._expected_out(v))]
        if conflicts and self._conflict_choice is None:
            self._show_conflict(conflicts)
            return
        choice = self._conflict_choice or "overwrite"
        self._conflict_choice = None
        self._stop_play()
        self.busy = True
        self.settingsp.conv_btn.set_enabled(False)
        self.settingsp.conv_btn.set_text("CONVERTING...")
        self.last_out_dir = self.out_dir or os.path.dirname(vids[0])
        cfg = self._cfg()
        cfg["on_conflict"] = choice
        threading.Thread(target=self._work, args=(vids, cfg), daemon=True).start()

    def _show_conflict(self, conflicts):
        if len(conflicts) == 1:
            nm = os.path.basename(self._expected_out(conflicts[0]))
            self.dialog.msg = f'"{nm}" already exists in this folder. What now?'
        else:
            self.dialog.msg = (f"{len(conflicts)} files already have a sticker with the "
                               "same name. What now?")
        W = max(300, self.root.winfo_width())
        H = max(300, self.root.winfo_height())
        dw, dh = 500, 168
        self.dialog.set_geometry((W - dw) // 2, (H - dh) // 2, dw, dh)
        wlift(self.dialog)
        try:
            self.dialog.refresh()
        except Exception:
            log_exc("dialog")

    def _conflict_pick(self, choice):
        self.dialog.place_forget()
        if choice:
            self._conflict_choice = choice
            self.convert_clicked()

    def _work(self, vids, cfg):
        done = fail = 0
        for i, src in enumerate(vids, 1):
            self.q.put(("log", (f"\n[{i}/{len(vids)}] {os.path.basename(src)}", "acc")))
            try:
                fn = convert_image if is_image(src) else convert
                ok, out = fn(src, cfg,
                             lambda m, t=None: self.q.put(("log", (m, t))))
                if ok:
                    kb = os.path.getsize(out) / 1000
                    self.q.put(("log", (f"  ✓ {os.path.basename(out)}  ({kb:.0f} KB)", "ok")))
                    self.q.put(("hist", {"path": out, "kb": kb,
                                         "time": time.strftime("%H:%M")}))
                    done += 1
                else:
                    fail += 1
            except Exception as e:
                self.q.put(("log", (f"  ✗ error: {e}", "err")))
                fail += 1
        self.q.put(("log", (f"\nDone: {done} ok, {fail} failed. Send to @Stickers.", "ok")))
        self.q.put(("toastdone", (done, fail)))
        self.q.put(("done", None))

    # ------------------------------------------------ kisayollar / pompa
    def _bind_keys(self):
        self.root.bind_all("<space>", lambda e: self.toggle_play())
        self.root.bind_all("<Control-z>", lambda e: self.undo())
        self.root.bind_all("<Control-Z>", lambda e: self.undo())
        self.root.bind_all("<Left>", lambda e: self.step(-1))
        self.root.bind_all("<Right>", lambda e: self.step(1))

    def _pump(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "log":
                    self.log(*(payload if isinstance(payload, tuple) else (payload,)))
                elif kind == "loaded":
                    self._on_loaded(payload)
                elif kind == "load_fail":
                    self.loading = False
                    shutil.rmtree(payload, ignore_errors=True)
                    self.playerp.set_mode("idle")
                    self.topbar.request()
                    self.mark_dirty(self.settingsp)
                    self.log("  ✗ couldn't extract preview (file may be corrupt)", "err")
                elif kind == "hist":
                    self.history.insert(0, payload)
                    self.last_out_file = payload["path"]
                    if self.tab == "gecmis":
                        self.historyp.request()
                    if self.tab == "indir":
                        self.playerp.request()
                elif kind == "toastdone":
                    done, fail = payload
                    if fail == 0:
                        self.toast(f"✓ {done} stickers ready", "ok")
                    else:
                        self.toast(f"{done} ok, {fail} failed", "err")
                elif kind == "done":
                    self.busy = False
                    self.settingsp.conv_btn.set_enabled(self.sess is not None)
                    self._sync_conv_btn()
        except queue.Empty:
            pass
        self.root.after(120, self._pump)


def main():
    root = TkinterDnD.Tk() if HAS_DND else tk.Tk()

    def _cb_exc(exc, val, tb):
        try:
            import traceback
            with open(ERRLOG, "a", encoding="utf-8") as f:
                f.write(f"\n--- {time.strftime('%Y-%m-%d %H:%M:%S')} callback\n")
                f.write("".join(traceback.format_exception(exc, val, tb)))
        except Exception:
            pass
    root.report_callback_exception = _cb_exc
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
