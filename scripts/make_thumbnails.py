"""Draw the template-browser thumbnails for example_workflows/*.json.

ComfyUI's template browser shows example_workflows/<name>.jpg next to each
example. These are drawn, not rendered with a model, so they hold no model
output and no metadata. Run from anywhere:

    python scripts/make_thumbnails.py
"""

import os

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "example_workflows")
W, H = 512, 384

# Same colours as scripts/make_diagrams.py.
PANEL = "#15171c"
INK = "#e8eaf0"
MUTED = "#98a2b3"
CELL = "#2f3470"
CELL_EDGE = "#6f78d8"
ALT = "#5a2f66"
ALT_EDGE = "#b06fd0"
GREEN = "#58b36b"


def font(size, bold=False):
    names = (
        ["segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"]
        if bold
        else ["segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"]
    )
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def canvas(title, caption):
    img = Image.new("RGB", (W, H), PANEL)
    d = ImageDraw.Draw(img)
    d.text((24, 18), title, font=font(26, bold=True), fill=INK)
    d.text((24, H - 40), caption, font=font(18), fill=MUTED)
    return img, d


def grid(d, x, y, cols, rows, cell, gap=6, fill=CELL, edge=CELL_EDGE, col_labels=None, row_labels=None):
    small = font(14)
    for c in range(cols):
        if col_labels:
            d.text((x + c * (cell + gap) + cell // 2, y - 10), col_labels[c], font=small, fill=MUTED, anchor="ms")
        for r in range(rows):
            x0, y0 = x + c * (cell + gap), y + r * (cell + gap)
            f, e = (fill(c, r) if callable(fill) else fill), (edge(c, r) if callable(edge) else edge)
            d.rounded_rectangle([x0, y0, x0 + cell, y0 + cell], radius=6, fill=f, outline=e, width=2)
    if row_labels:
        for r in range(rows):
            d.text((x - 10, y + r * (cell + gap) + cell // 2), row_labels[r], font=small, fill=MUTED, anchor="rm")


def quickstart():
    img, d = canvas("Quick start: seed × cfg", "9 images and one labelled grid")
    grid(d, 186, 92, 3, 3, 70, col_labels=["seed 1", "seed 2", "seed 3"], row_labels=["cfg 4", "cfg 7", "cfg 10"])
    return img


def any_setting():
    img, d = canvas("Sweep any setting", "12 images: one grid per prompt")
    for i, label in enumerate(["prompt 1", "prompt 2"]):
        x = 70 + i * 220
        d.text((x + 94, 74), label, font=font(16, bold=True), fill=INK, anchor="ms")
        grid(d, x, 100, 2, 3, 60, col_labels=None, row_labels=None)
    d.text((W // 2, 330), "seed 1–2 across, cfg 4 · 7 · 10 down", font=font(15), fill=MUTED, anchor="ms")
    return img


def pair_lora():
    img, d = canvas("Pair two LoRA strengths", "5 pairs × 3 cfg values = 15 images")
    rows = ["0.2 · 0.3", "0.4 · 0.5", "0.6 · 0.6", "0.8 · 0.7", "1.0 · 0.9"]
    grid(d, 250, 88, 3, 5, 40, gap=7, col_labels=["cfg 4", "cfg 7", "cfg 10"], row_labels=[f"LoRA {r}" for r in rows])
    return img


def style_upset():
    img, d = canvas("Styles that work together", "14 subsets of 4 styles, as an UpSet matrix")
    cols = [
        (0,),
        (1,),
        (2,),
        (3,),
        (0, 1),
        (0, 2),
        (0, 3),
        (1, 2),
        (1, 3),
        (2, 3),
        (0, 1, 2),
        (0, 1, 3),
        (0, 2, 3),
        (1, 2, 3),
    ]
    x0, step, top = 130, 26, 80
    for i, _ in enumerate(cols):
        d.rounded_rectangle(
            [x0 + i * step, top, x0 + i * step + 20, top + 60], radius=4, fill=ALT, outline=ALT_EDGE, width=2
        )
    names = ["cyberpunk", "noir", "pastel", "vintage"]
    for r, name in enumerate(names):
        y = top + 95 + r * 40
        d.text((x0 - 12, y), name, font=font(14), fill=MUTED, anchor="rm")
        d.line([x0, y, x0 + (len(cols) - 1) * step + 20, y], fill="#2b2f38", width=1)
    for i, members in enumerate(cols):
        cx = x0 + i * step + 10
        ys = [top + 95 + m * 40 for m in members]
        if len(ys) > 1:
            d.line([cx, min(ys), cx, max(ys)], fill=INK, width=3)
        for r in range(len(names)):
            y = top + 95 + r * 40
            on = r in members
            d.ellipse([cx - 6, y - 6, cx + 6, y + 6], fill=INK if on else "#3a3f4b")
    return img


def dedupe():
    img, d = canvas("Skip repeats", "3 images made, shown in all 9 cells")
    shades = ["#2f3470", "#2c5a35", "#5a2f66"]
    edges = [CELL_EDGE, GREEN, ALT_EDGE]
    grid(
        d,
        196,
        92,
        3,
        3,
        70,
        fill=lambda c, r: shades[c],
        edge=lambda c, r: edges[c],
        col_labels=["beach", "forest", "city street"],
        row_labels=["dawn", "noon", "dusk"],
    )
    return img


def model_list():
    img, d = canvas("Three models in a list", "3 models × 2 seeds = 6 images and a grid")
    grid(d, 200, 100, 3, 2, 80, col_labels=["model 1", "model 2", "model 3"], row_labels=["seed 1", "seed 2"])
    return img


THUMBS = {
    "1_quickstart_all_in_one": quickstart,
    "2_sweep_any_setting": any_setting,
    "3_pair_lora_strengths": pair_lora,
    "4_style_combinations_upset": style_upset,
    "5_dedupe_gather": dedupe,
    "6_model_list_pylist": model_list,
}


def main():
    for name, draw in THUMBS.items():
        if not os.path.exists(os.path.join(OUT, name + ".json")):
            raise SystemExit(f"no example_workflows/{name}.json for this thumbnail")
        path = os.path.join(OUT, name + ".jpg")
        draw().save(path, "JPEG", quality=88, optimize=True)  # Pillow adds no EXIF unless asked
        print("wrote", os.path.relpath(path, ROOT))


if __name__ == "__main__":
    main()
