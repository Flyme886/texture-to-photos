#!/usr/bin/env python3
"""照片质感提示词库 · 展示图生成

用法:
  python3 build_showcase.py sample.json \
      --repo /home/claude/texture-to-photos --out out [--theme light|dark] [--hero-ratio auto|4:5|3:2]

输入 JSON: [{"id": "048_01", "name": "薄雾灰蓝", "slot": "A", "look": "..."}, ...]
  可选字段 focus_y (0–1)：首页网格里该图的竖向取景位置，默认 0.5
输出:
  out/cards/<id>.jpg  对比卡（第一组前后图并排）
  out/hero.jpg        首页封面（前 6–9 份的「后」图网格）
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

LIB_DIR = "提示词素材库"
MAX_BYTES = 600 * 1024
QUALITY = 85

THEMES = {
    # bg, title, sub(gray), faint(gray for meta), frame
    "dark": dict(bg=(28, 28, 27), title=(236, 233, 226), sub=(150, 147, 141),
                 faint=(96, 94, 90), frame=(246, 244, 239)),
    "light": dict(bg=(243, 240, 233), title=(38, 37, 35), sub=(128, 124, 117),
                  faint=(170, 165, 157), frame=(255, 255, 255)),
}


# ---------------------------------------------------------------- fonts
def _fc_path(pattern):
    try:
        out = subprocess.run(["fc-match", "-f", "%{file}", pattern],
                             capture_output=True, text=True, check=True).stdout
        return out.strip() or None
    except Exception:
        return None


def _ttc_index(path, want="SC"):
    """在 .ttc 中找到简体中文 (SC) 子字体的 index。"""
    for i in range(12):
        try:
            fam = ImageFont.truetype(path, 10, index=i).getname()[0]
        except Exception:
            break
        if fam.endswith("CJK " + want):
            return i
    return 0


_font_cache = {}


def font(kind, size):
    """kind: serif / sans / sans-light / sans-medium"""
    key = (kind, size)
    if key in _font_cache:
        return _font_cache[key]
    pattern = {
        "serif": "Noto Serif CJK SC:style=Medium",
        "sans": "Noto Sans CJK SC:style=Regular",
        "sans-light": "Noto Sans CJK SC:style=Light",
        "sans-medium": "Noto Sans CJK SC:style=Medium",
    }[kind]
    path = _fc_path(pattern)
    if not path or "CJK" not in path:
        sys.exit(f"找不到 Noto CJK 字体（{pattern}），请安装 fonts-noto-cjk")
    f = ImageFont.truetype(path, size, index=_ttc_index(path) if path.endswith(".ttc") else 0)
    _font_cache[key] = f
    return f


def text_w(txt, f, track=0):
    if not txt:
        return 0
    return sum(f.getlength(c) for c in txt) + track * (len(txt) - 1)


def draw_text(draw, xy, txt, f, fill, track=0, anchor="ls"):
    """逐字绘制以支持字距 (track, px)。anchor 只用来定基线：ls/ms/rs。"""
    x, y = xy
    w = text_w(txt, f, track)
    if anchor[0] == "m":
        x -= w / 2
    elif anchor[0] == "r":
        x -= w
    for c in txt:
        draw.text((x, y), c, font=f, fill=fill, anchor="l" + anchor[1])
        x += f.getlength(c) + track
    return w


def fit_text(txt, f, max_w, track=0):
    if text_w(txt, f, track) <= max_w:
        return txt
    while txt and text_w(txt + "…", f, track) > max_w:
        txt = txt[:-1]
    return txt + "…"


# ---------------------------------------------------------------- io
def load_pair(repo, pid, group=None):
    d = Path(repo) / LIB_DIR / pid
    meta = json.loads((d / "素材对应.json").read_text(encoding="utf-8"))
    pairs = [c for c in meta.get("对比", []) if c.get("before") and c.get("after")]
    if not pairs:
        raise ValueError(f"{pid}: 素材对应.json 中没有可用的前后对比")
    g = next((c for c in pairs if c.get("group") == group), pairs[0])
    return (open_rgb(d / g["before"]), open_rgb(d / g["after"]), meta)


def open_rgb(p):
    im = Image.open(p)
    im = ImageOps.exif_transpose(im)
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.split()[-1])
        im = bg
    return trim_border(im.convert("RGB"))


def trim_border(im, thresh=240, frac=0.97, cap=0.08):
    """去掉截图自带的纯白/纯黑细边（只裁边缘整行整列，不碰画面内容和水印）。"""
    g = im.convert("L")
    w, h = g.size
    px = g.load()

    def is_edge(vals):
        n = len(vals)
        white = sum(v > thresh for v in vals) / n
        black = sum(v < 255 - thresh for v in vals) / n
        return white > frac or black > frac

    step = 4
    row = lambda y: [px[x, y] for x in range(0, w, step)]
    col = lambda x: [px[x, y] for y in range(0, h, step)]
    t = 0
    while t < h * cap and is_edge(row(t)):
        t += 1
    b = 0
    while b < h * cap and is_edge(row(h - 1 - b)):
        b += 1
    l = 0
    while l < w * cap and is_edge(col(l)):
        l += 1
    r = 0
    while r < w * cap and is_edge(col(w - 1 - r)):
        r += 1
    if t + b + l + r == 0:
        return im
    return im.crop((l, t, w - r, h - b))


def save_jpeg(im, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    scale = 1.0
    while True:
        out = im if scale == 1.0 else im.resize(
            (round(im.width * scale), round(im.height * scale)), Image.LANCZOS)
        out.save(path, "JPEG", quality=QUALITY, optimize=True, progressive=True,
                 subsampling="4:2:0")
        size = path.stat().st_size
        if size <= MAX_BYTES or scale < 0.5:
            return size, out.size
        scale *= 0.92  # 超过 600KB：保持 q85，略缩尺寸


def cover(im, w, h, focus_y=0.5):
    """裁切到 w×h；focus_y 控制竖向取景（0 顶 / 1 底）。"""
    return ImageOps.fit(im, (w, h), Image.LANCZOS, centering=(0.5, focus_y))


def framed(im, border, color):
    out = Image.new("RGB", (im.width + 2 * border, im.height + 2 * border), color)
    out.paste(im, (border, border))
    return out


# ---------------------------------------------------------------- card
W = 1600


def build_card(item, repo, out_dir, th):
    before, after, meta = load_pair(repo, item["id"], item.get("group"))
    pip = item.get("pip", False)  # 原图是作者画中画小窗：只展示带小窗的成片

    M = 96              # 外边距
    GAP = 28            # 两图间距
    B = 4               # 白边
    avail = W - 2 * M - GAP - 4 * B
    # 等高：h * (r1 + r2) = avail
    r1, r2 = before.width / before.height, after.width / after.height
    if pip:
        r1 = 0; avail = W - 2 * M - 2 * B
    h = avail / (r1 + r2)
    max_h = 1100
    if h > max_h:       # 竖图组合时限制高度，水平居中
        h = max_h
    h = round(h)
    w1, w2 = max(1, round(h * r1)), round(h * r2)
    imgs = [before.resize((w1, h), Image.LANCZOS), after.resize((w2, h), Image.LANCZOS)]
    labels = ("BEFORE", "AFTER")
    if pip:
        imgs, labels = imgs[1:], ("AFTER  ·  INSET = BEFORE",)

    TOP = M
    TEXT_H = 270
    H = TOP + h + 2 * B + TEXT_H
    canvas = Image.new("RGB", (W, H), th["bg"])
    draw = ImageDraw.Draw(canvas)

    row_w = sum(i.width for i in imgs) + 2 * B * len(imgs) + GAP * (len(imgs) - 1)
    x = (W - row_w) // 2
    left_edge = x
    label_f = font("sans", 14)
    for im, label in zip(imgs, labels):
        canvas.paste(framed(im, B, th["frame"]), (x, TOP))
        # 左下角极小标签：放在图框外下沿，避开原图里作者自带的文字
        draw_text(draw, (x, TOP + h + 2 * B + 30), label, label_f, th["faint"], track=4)
        x += im.width + 2 * B + GAP
    right_edge = x - GAP
    if pip:  # 单图时文字区仍按版心对齐
        left_edge, right_edge = M, W - M

    # 文字区：与图片左右边缘对齐
    base_y = TOP + h + 2 * B + 136
    name_f = font("serif", 50)
    look_f = font("sans-light", 23)
    meta_f = font("sans", 17)
    meta_txt = f"{item.get('slot', '').upper()}  ·  No.{item['id']}".strip(" ·")
    meta_w = text_w(meta_txt, meta_f, 3)
    name = fit_text(item["name"], name_f, right_edge - left_edge - meta_w - 60, 6)
    draw_text(draw, (left_edge, base_y), name, name_f, th["title"], track=6)
    look = fit_text(item.get("look", ""), look_f, right_edge - left_edge, 2)
    draw_text(draw, (left_edge, base_y + 58), look, look_f, th["sub"], track=2)
    draw_text(draw, (right_edge, base_y), meta_txt, meta_f, th["faint"], track=3, anchor="rs")
    # 细分隔线

    path = out_dir / "cards" / f"{item['id']}.jpg"
    size, dim = save_jpeg(canvas, path)
    return path, size, dim


# ---------------------------------------------------------------- hero
def pick_ratio(ims):
    """在 4:5 与 3:2 中选总裁切损失更小的一种。"""
    def loss(r):
        tot = 0
        for im in ims:
            a = im.width / im.height
            tot += 1 - min(a, r) / max(a, r)
        return tot
    return min((4 / 5, 3 / 2), key=loss)


def build_hero(items, repo, out_dir, th, ratio=None):
    n = len(items)
    if n >= 9:
        k, cols = 9, 3
    elif n >= 8:
        k, cols = 8, 4
    elif n >= 6:
        k, cols = 6, 3
    else:
        raise ValueError("hero 需要至少 6 份")
    items = items[:k]
    rows = k // cols
    afters = [load_pair(repo, it["id"])[1] for it in items]
    ratio = ratio or pick_ratio(afters)

    M = 110
    GAP = 22
    cw = (W - 2 * M - (cols - 1) * GAP) // cols
    ch = round(cw / ratio)
    CAP = 64                        # 每格下方小字区
    HEAD = 330
    FOOT = 110
    grid_w = cols * cw + (cols - 1) * GAP
    gx0 = (W - grid_w) // 2
    H = HEAD + rows * (ch + CAP) + (rows - 1) * (GAP + 6) + FOOT
    canvas = Image.new("RGB", (W, H), th["bg"])
    draw = ImageDraw.Draw(canvas)

    # 标题
    title_f = font("serif", 68)
    sub_f = font("sans-light", 26)
    small_f = font("sans", 15)
    draw_text(draw, (W / 2, 168), "照片质感 · 提示词库", title_f, th["title"], track=10, anchor="ms")
    draw_text(draw, (W / 2, 228), "上传一张照片，给你三种质感", sub_f, th["sub"], track=6, anchor="ms")
    draw.line([(W / 2 - 20, 92), (W / 2 + 20, 92)], fill=th["faint"], width=1)

    cap_f = font("sans", 20)
    for i, it in enumerate(items):
        after = afters[i]
        r, c = divmod(i, cols)
        x = gx0 + c * (cw + GAP)
        y = HEAD + r * (ch + CAP + GAP + 6)
        canvas.paste(cover(after, cw, ch, float(it.get("focus_y", 0.5))), (x, y))
        draw_text(draw, (x, y + ch + 36), fit_text(it["name"], cap_f, cw - 60, 3),
                  cap_f, th["title"], track=3)
        draw_text(draw, (x + cw, y + ch + 36), f"{it.get('slot', '').upper()}",
                  small_f, th["faint"], track=2, anchor="rs")

    draw_text(draw, (W / 2, H - 56), "32 STYLES  ·  A / B / C", small_f,
              th["faint"], track=5, anchor="ms")

    path = out_dir / "hero.jpg"
    size, dim = save_jpeg(canvas, path)
    return path, size, dim


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description="生成对比卡与首页封面")
    ap.add_argument("input", help="JSON 数组 [{id,name,slot,look}]")
    ap.add_argument("--repo", default="/home/claude/texture-to-photos")
    ap.add_argument("--out", default="out")
    ap.add_argument("--theme", choices=THEMES, default="light")
    ap.add_argument("--no-hero", action="store_true")
    ap.add_argument("--hero-ratio", choices=["auto", "4:5", "3:2"], default="auto")
    a = ap.parse_args()

    items = json.loads(Path(a.input).read_text(encoding="utf-8"))
    out = Path(a.out)
    th = THEMES[a.theme]
    ok = True
    for it in items:
        try:
            p, s, d = build_card(it, a.repo, out, th)
            print(f"card  {p}  {d[0]}x{d[1]}  {s // 1024}KB")
        except Exception as e:
            ok = False
            print(f"FAIL  {it.get('id')}: {e}", file=sys.stderr)
    if not a.no_hero:
        ratio = {"auto": None, "4:5": 4 / 5, "3:2": 3 / 2}[a.hero_ratio]
        p, s, d = build_hero(items, a.repo, out, th, ratio)
        print(f"hero  {p}  {d[0]}x{d[1]}  {s // 1024}KB")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
