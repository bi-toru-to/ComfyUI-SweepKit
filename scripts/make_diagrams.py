#!/usr/bin/env python3
"""Draw the README flowcharts as SVG files (docs/img/*.svg). Standard library only.

    python scripts/make_diagrams.py

Each diagram sits on its own dark panel, so it reads the same on light and dark pages and on sites that
don't render Mermaid. Colours match the node colours in ComfyUI: blue = what to vary, green = makes or
collects the images, purple = grids, grey = your own nodes.
"""

from __future__ import annotations

import os
from html import escape

OUT = os.path.join(os.path.dirname(__file__), "..", "docs", "img")

PANEL = "#15171c"
INK = "#e8eaf0"
MUTED = "#98a2b3"
LINE = "#8a93a6"
STYLES = {  # fill, stroke
    "axis": ("#2f3470", "#6f78d8"),
    "gen": ("#2c5a35", "#58b36b"),
    "out": ("#5a2f66", "#b06fd0"),
    "user": ("#2b2f38", "#6b7488"),
    "result": ("#1d2a3a", "#4f8fcf"),
    "note": ("none", "none"),
}
FONT = 'font-family="Segoe UI, Helvetica, Arial, sans-serif"'


class Svg:
    def __init__(self, width: int, height: int, title: str):
        self.w, self.h, self.title = width, height, title
        self.parts: list[str] = []

    def box(self, x, y, w, h, kind, lines, bold_first=True, size=15):
        fill, stroke = STYLES[kind]
        if kind != "note":
            self.parts.append(
                f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" fill="{fill}" stroke="{stroke}" stroke-width="1.6"/>'
            )
        n = len(lines)
        step = size + 5
        top = y + h / 2 - (n - 1) * step / 2 + size * 0.35
        for i, line in enumerate(lines):
            weight = "600" if (i == 0 and bold_first and kind != "note") else "400"
            color = INK if i == 0 or kind == "note" else "#c9d0dc"
            self.parts.append(
                f'<text x="{x + w / 2}" y="{top + i * step}" text-anchor="middle" font-size="{size if i == 0 else size - 2}" '
                f'font-weight="{weight}" fill="{color}" {FONT}>{escape(line)}</text>'
            )

    def text(self, x, y, s, size=13, color=MUTED, anchor="middle", weight="400"):
        self.parts.append(
            f'<text x="{x}" y="{y}" text-anchor="{anchor}" font-size="{size}" font-weight="{weight}" fill="{color}" {FONT}>{escape(s)}</text>'
        )

    def arrow(self, points, label=None, label_at=None, dashed=False):
        d = "M " + " L ".join(f"{x} {y}" for x, y in points)
        dash = ' stroke-dasharray="6 5"' if dashed else ""
        self.parts.append(
            f'<path d="{d}" fill="none" stroke="{LINE}" stroke-width="1.8"{dash} marker-end="url(#arrow)"/>'
        )
        if label and label_at:
            self.text(label_at[0], label_at[1], label, size=12)

    def render(self) -> str:
        head = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" height="{self.h}" viewBox="0 0 {self.w} {self.h}" role="img" '
            f'aria-label="{escape(self.title)}"><title>{escape(self.title)}</title>'
            f'<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
            f'<path d="M 0 0 L 10 5 L 0 10 z" fill="{LINE}"/></marker></defs>'
            f'<rect width="{self.w}" height="{self.h}" rx="14" fill="{PANEL}"/>'
        )
        return head + "".join(self.parts) + "</svg>\n"


def quickstart() -> Svg:
    s = Svg(980, 330, "Sweep All-in-One: axes in, every combination out")
    s.text(24, 34, "Quick start: Sweep All-in-One", 18, INK, "start", "600")
    s.box(30, 80, 200, 62, "axis", ["Sweep Axis", "seed: 1, 2, 3"])
    s.box(30, 190, 200, 62, "axis", ["Sweep Axis", "cfg: 4, 7, 10"])
    s.box(330, 120, 250, 100, "gen", ["Sweep All-in-One", "samples every combination", "and builds the grids"])
    s.box(330, 258, 250, 44, "user", ["your checkpoint + prompt"], size=14)
    s.box(690, 70, 250, 58, "result", ["9 images", "named by the values used"])
    s.box(690, 146, 250, 58, "result", ["1 labelled 3 × 3 grid", "fills in live while it runs"])
    s.box(690, 222, 250, 58, "result", ["run list (CSV)", "one row per image"])
    s.arrow([(230, 111), (280, 111), (280, 150), (330, 150)])
    s.arrow([(230, 221), (280, 221), (280, 190), (330, 190)])
    s.arrow([(455, 258), (455, 220)])
    for y in (99, 175, 251):
        s.arrow([(580, 170), (635, 170), (635, y), (690, y)])
    return s


def any_setting() -> Svg:
    s = Svg(1040, 470, "Sweep any setting of your own workflow")
    s.text(24, 34, "Sweep any setting of your own workflow", 18, INK, "start", "600")
    s.text(
        24, 56, "Right-click a setting, choose “Sweep…”, and the axis is added and wired for you.", 13, MUTED, "start"
    )
    ax = [("seed", "1–2"), ("cfg", "4, 7, 10"), ("prompt", "2 versions")]
    x = 30
    for name, vals in ax:
        s.box(x, 84, 150, 58, "axis", [f"Sweep Axis: {name}", vals], size=14)
        x += 190
    s.box(610, 78, 170, 70, "axis", ["Sweep Plan", "12 images: 2 × 3 × 2"], size=15)
    s.arrow([(180, 113), (220, 113)])
    s.arrow([(370, 113), (410, 113)])
    s.arrow([(560, 113), (610, 113)])
    s.text(30, 190, "your own workflow (any nodes)", 13, MUTED, "start")
    s.box(30, 210, 140, 60, "user", ["Load Checkpoint"], size=14)
    s.box(215, 210, 160, 60, "user", ["CLIP Text Encode", "prompt"], size=14)
    s.box(420, 210, 150, 60, "user", ["KSampler", "seed · cfg"], size=14)
    s.box(615, 210, 130, 60, "user", ["VAE Decode"], size=14)
    s.box(790, 200, 220, 80, "gen", ["Sweep Collect", "gathers every image"])
    s.arrow([(170, 240), (215, 240)])
    s.arrow([(375, 240), (420, 240)])
    s.arrow([(570, 240), (615, 240)])
    s.arrow([(745, 240), (790, 240)])
    s.arrow([(640, 148), (640, 175), (295, 175), (295, 210)], "prompt list", (470, 169))
    s.arrow([(700, 148), (700, 188), (495, 188), (495, 210)], "seed + cfg lists", (600, 202))
    s.arrow([(780, 113), (900, 113), (900, 200)], "combo", (860, 107))
    s.box(630, 350, 190, 54, "result", ["named images", "seed1_cfg4_….png"], size=14)
    s.box(840, 350, 170, 54, "result", ["labelled grids", "one per prompt"], size=14)
    s.box(420, 350, 190, 54, "result", ["run list (CSV)", "values for every image"], size=14)
    for tx in (725, 925, 515):
        s.arrow([(900, 280), (900, 312), (tx, 312), (tx, 350)])
    s.text(
        520,
        445,
        "ComfyUI runs the connected nodes once per combination, one image at a time; the grid fills in as they finish.",
        13,
        MUTED,
    )
    return s


def cross_vs_pair() -> Svg:
    s = Svg(900, 330, "Crossed axes versus paired axes")
    s.text(24, 34, "Cross (default) or pair?", 18, INK, "start", "600")
    s.text(230, 72, "Cross: every A with every B", 15, INK, "middle", "600")
    s.text(230, 92, "3 × 3 = 9 images", 13, MUTED)
    cols = ["B1", "B2", "B3"]
    for j, c in enumerate(cols):
        s.text(120 + j * 70 + 30, 122, c, 13, MUTED)
    for i in range(3):
        s.text(88, 160 + i * 52, f"A{i + 1}", 13, MUTED)
        for j in range(3):
            s.box(120 + j * 70, 130 + i * 52, 60, 42, "axis", [f"{i + 1}·{j + 1}"], bold_first=False, size=13)
    s.text(670, 72, "Pair: A and B move together", 15, INK, "middle", "600")
    s.text(670, 92, "Sweep Pair Axes → 3 images", 13, MUTED)
    for i in range(3):
        s.box(560, 130 + i * 52, 220, 42, "out", [f"A{i + 1} with B{i + 1}"], bold_first=False, size=14)
    s.text(
        450,
        300,
        "Example: pair a LoRA’s model strength with its clip strength, then cross the pairs with cfg.",
        13,
        MUTED,
    )
    return s


def which_path() -> Svg:
    s = Svg(1000, 470, "Which SweepKit path fits")
    s.text(24, 34, "Which path fits?", 18, INK, "start", "600")
    s.box(380, 60, 240, 50, "user", ["I want to compare settings"], size=15)
    s.box(60, 160, 340, 74, "user", ["Fastest start,", "the built-in sampler is fine"], size=15)
    s.box(600, 160, 340, 74, "user", ["My own workflow", "(any sampler, ControlNet, LoRA stack…)"], size=15)
    s.box(60, 270, 340, 60, "gen", ["Sweep Axis → Sweep All-in-One"], size=15)
    s.box(600, 270, 340, 60, "gen", ["Sweep Axis → Sweep Plan → Sweep Collect"], size=15)
    s.arrow([(450, 110), (450, 135), (230, 135), (230, 160)])
    s.arrow([(550, 110), (550, 135), (770, 135), (770, 160)])
    s.arrow([(230, 234), (230, 270)])
    s.arrow([(770, 234), (770, 270)])
    s.text(500, 370, "then add what you need", 14, INK, "middle", "600")
    extras = [
        ("Sweep Pair Axes", "settings that move together"),
        ("Sweep Subsets + UpSet Matrix", "which items of a list work together"),
        ("Sweep Skip Repeats + Gather", "don’t repeat identical runs"),
        ("run_sweep_api.py", "no browser, overnight or on a server"),
    ]
    for i, (title, sub) in enumerate(extras):
        kind = "result" if title.endswith(".py") else "out"  # the script is a way to run, not a node
        s.box(30 + i * 242, 390, 228, 58, kind, [title, sub], size=13)
    return s


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    for name, build in (
        ("flow_quickstart", quickstart),
        ("flow_any_setting", any_setting),
        ("flow_cross_vs_pair", cross_vs_pair),
        ("flow_which_path", which_path),
    ):
        path = os.path.join(OUT, f"{name}.svg")
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(build().render())
        print("wrote", os.path.normpath(path))


if __name__ == "__main__":
    main()
