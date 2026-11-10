"""
SweepUpsetConstructor — visualizes one SweepDimensionSelfCombine axis as
an UpSet-style matrix: one column per generated combo (sorted by arity,
then generation order — the order self_combine already produces, no extra
sort needed), the actual image as that column's swatch, and a dot-matrix
below marking which base elements the combo contains, with a connecting
line joining them.

Deliberately narrower in scope than SweepGridConstructor: it visualizes
exactly ONE self-combine dimension's own structure. Any OTHER independent
dimension in the graph (e.g. sweeping cfg alongside style combos) is
handled the same way SweepGridConstructor handles leftover axes — as a
page split, producing one matrix per combination of the other axes,
never crammed into the same matrix. A large column count on top of that
paginates further via max_columns_per_page, purely as a safety valve —
the practical ceiling is much higher than it looks in a mockup, since
this is a saved file to scroll/zoom in an image viewer, not a fixed
viewport.
"""

import itertools
import os
from dataclasses import dataclass
from typing import Any

import comfy.model_management
import comfy.utils
import folder_paths
from PIL import Image, ImageDraw

from .sweep_core import (
    GRID_AXIS_OPTIONS,
    counted,
    dim_group_members,
    find_dim_by_id,
    format_group_value,
    next_versioned_path,
    one_per_group,
    resolve_axis_token,
    safe_component,
    ui_images,
    validate_axis_picks,
)
from .sweep_draw import (
    MIN_TITLE_WIDTH,
    check_canvas_size,
    find_font,
    font_size_for_char_width,
    truncate_text_to_width,
    wrap_text_to_width,
    wrap_title,
)
from .sweep_image import (
    BACKGROUND,
    cell_dims,
    cell_key,
    draw_missing_cell,
    grid_title,
    images_by_combo,
    line_height,
    paste_into_cell,
    scratch_draw,
    stack_padded,
    tensor_to_pil,
    unpack_combo,
)


class SweepUpsetConstructor:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": (
                    "PYLIST",
                    {
                        "forceInput": True,
                        "tooltip": (
                            "Every image of the sweep, in order. Turn your image output into one list with List-Utils' List To PyList, then connect it here."
                        ),
                    },
                ),
                "combo": (
                    "SWEEP_COMBO",
                    {
                        "tooltip": ("Connect Sweep Plan's combo output."),
                    },
                ),
                "dim_id": (
                    "STRING",
                    {
                        "default": "",
                        "tooltip": ("The name (dim_id) of the axis that goes through Sweep Subsets of a List."),
                    },
                ),
                "filename_prefix": (
                    "STRING",
                    {
                        "default": "SweepKit",
                        "tooltip": (
                            "Folder (inside ComfyUI's output folder) for the matrices. Leave blank for SweepKit. Files never replace earlier ones: a number like _00001 is added; matrices go in _upset."
                        ),
                    },
                ),
                "cell_size": (
                    "INT",
                    {
                        "default": 120,
                        "min": 32,
                        "max": 1024,
                        "step": 8,
                        "tooltip": ("Size of each image in the matrix, in pixels (see cell_mode)."),
                    },
                ),
                "cell_mode": (
                    ["fit", "square", "original"],
                    {
                        "default": "fit",
                        "tooltip": "fit: scale preserving aspect ratio (recommended). square: stretch to cell_size x cell_size. original: no resizing at all.",
                    },
                ),
                "font_size": (
                    "FLOAT",
                    {
                        "default": 1.0,
                        "min": 0.0,
                        "max": 1.0,
                        "step": 0.05,
                        "tooltip": (
                            "Label size compared with the image width: 1.0 fits about 16 characters across an image. Titles stay larger than labels."
                        ),
                    },
                ),
                "title_dim": (
                    GRID_AXIS_OPTIONS,
                    {
                        "default": "none",
                        "tooltip": (
                            "Another axis to name first in each matrix's title and folder. auto prefers a text axis; none keeps the chain's order. The list shows your axes by their names (dim_id)."
                        ),
                    },
                ),
                "max_columns_per_page": (
                    "INT",
                    {
                        "default": 60,
                        "min": 5,
                        "max": 500,
                        "tooltip": ("Most columns in one matrix image; more columns continue in numbered files."),
                    },
                ),
            },
        }

    @classmethod
    def VALIDATE_INPUTS(cls, title_dim):
        # The picker lists the connected axes' dim_ids, which ComfyUI's fixed-list check doesn't know.
        return validate_axis_picks(title_dim=title_dim)

    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("matrices", "summary")
    FUNCTION = "build"
    CATEGORY = "SweepKit/Advanced"
    DESCRIPTION = "Draws an UpSet matrix: one column per subset made by Sweep Subsets of a List, with dots showing which items it uses and its image above."
    SEARCH_ALIASES = ["upset constructor", "upset plot", "subset matrix"]
    OUTPUT_NODE = True

    def build(
        self, images, combo, dim_id, filename_prefix, cell_size, cell_mode, font_size, title_dim, max_columns_per_page
    ):
        dims_sorted, images, combo_records = unpack_combo(images, combo, "Sweep UpSet Matrix")
        target = self.find_target(dims_sorted, dim_id)
        output_dir = folder_paths.get_output_directory()
        # Saves files itself (not via SaveImage), so the prefix is always one
        # sanitized folder name.
        prefix_folder = safe_component(filename_prefix) if str(filename_prefix).strip() else "SweepKit"
        all_images = images_by_combo(combo_records, images, dims_sorted)

        # Every other dimension splits pages (zip groups count once);
        # title_dim only changes which one leads the title and folders.
        other_dims = self.order_other_dims(
            one_per_group(d for d in dims_sorted if d["index"] != target["index"]), title_dim, dims_sorted, target
        )
        n_cols = len(target["values"])
        n_pages = max(1, -(-n_cols // max_columns_per_page))
        other_combos = list(itertools.product(*[range(len(d["values"])) for d in other_dims]))
        pbar = comfy.utils.ProgressBar(len(other_combos) * n_pages)

        matrices, paths = [], []
        for other_combo in other_combos:
            fixed = {d["index"]: vi for d, vi in zip(other_dims, other_combo, strict=True)}
            col_images = [all_images.get(cell_key(dims_sorted, fixed, (target, j))) for j in range(n_cols)]
            shown = [
                format_group_value(dim_group_members(d, dims_sorted), vi)
                for d, vi in zip(other_dims, other_combo, strict=True)
            ]
            base_title = grid_title(other_dims, shown, "", prefix_folder)
            folders = [safe_component(v) for v in shown]
            mat_dir = os.path.join(output_dir, prefix_folder, "_upset", *folders[:-1])

            for page in range(n_pages):
                comfy.model_management.throw_exception_if_processing_interrupted()
                lo, hi = page * max_columns_per_page, min((page + 1) * max_columns_per_page, n_cols)
                title = base_title if n_pages == 1 else f"{base_title} (page {page + 1}/{n_pages})"
                matrix = draw_matrix(col_images[lo:hi], target, lo, hi, title, cell_size, cell_mode, font_size)
                suffix = "" if n_pages == 1 else f"_page{page + 1}"
                path = next_versioned_path(mat_dir, f"{folders[-1] if folders else 'matrix'}{suffix}")
                matrix.save(path)
                matrices.append(matrix)
                paths.append(path)
                pbar.update(1)

        dim_map = "; ".join(f"dim{d['index']}='{d['dim_id']}'" for d in dims_sorted) or "(no active axes)"
        summary = (
            f"Sweep UpSet Matrix: {counted(len(paths), 'matrix image')} for '{dim_id}' "
            f"({counted(n_cols, 'subset')} of {counted(len(target['base_values']), 'item')}) "
            f"under {os.path.join(output_dir, prefix_folder, '_upset')} | {dim_map}"
        )
        print(f"[Sweep UpSet Matrix] {summary}")
        return {
            "ui": {"images": ui_images(paths, output_dir), "text": [summary]},
            "result": (stack_padded(matrices), summary),
        }

    @staticmethod
    def find_target(dims_sorted, dim_id):
        """The self-combined dimension to draw, or a clear error."""
        try:
            target = find_dim_by_id(dims_sorted, dim_id)
        except ValueError as e:
            raise ValueError(f"[Sweep UpSet Matrix] {e}") from e
        if "combo_meta" not in target:
            raise ValueError(
                f"[Sweep UpSet Matrix] dim_id is '{dim_id}', but that axis doesn't go through Sweep Subsets of a "
                f"List. Set dim_id to the axis that does, or connect '{dim_id}' through Sweep Subsets of a List."
            )
        return target

    @staticmethod
    def order_other_dims(other_dims, title_dim, dims_sorted, target):
        """Move the title_dim pick to the front: 'auto' = first text/static
        dimension, a dim_id or 'dimN' = that axis (or its zip group), 'none'
        = keep chain order."""
        if title_dim == "none":
            return other_dims
        if title_dim == "auto":
            lead = next((d for d in other_dims if d["type"] in ("text", "static")), None)
        else:
            picked = resolve_axis_token(dims_sorted, title_dim)
            if picked is None or picked["index"] == target["index"]:
                why = "doesn't match any active axis" if picked is None else "is the self-combine target itself"
                print(f"[Sweep UpSet Matrix] title_dim '{title_dim}' {why} — ignoring.")
                return other_dims
            lead = next(
                (
                    d
                    for d in other_dims
                    if d["index"] == picked["index"] or (picked.get("group") and d.get("group") == picked["group"])
                ),
                None,
            )
        if lead is None:
            return other_dims
        return [lead] + [d for d in other_dims if d is not lead]


# --------------------------------------------------------------- drawing

DOT_COLOR = (29, 158, 117)
EMPTY_DOT_COLOR = (70, 70, 70)
GUIDE_COLOR = (40, 40, 40)
DIVIDER_COLOR = (70, 70, 70)
GROUP_TEXT_COLOR = (160, 160, 160)
COLUMN_TEXT_COLOR = (180, 180, 180)


@dataclass
class MatrixLayout:
    """Every measurement draw_matrix needs, computed before drawing.

    Fonts scale with the ACTUAL swatch width (see font_size); every band
    and gap is derived from the font it holds so nothing clips at large
    sizes. Row labels are centred on their row (anchor 'lm'), so the gaps
    above the first row and below the last reserve half a line."""

    cell_w: int
    cell_h: int
    base_px: int
    font_title: Any
    font_group: Any
    font_row: Any
    font_col: Any
    pad: int
    col_w: int
    dot_r: int
    dot_gap: int
    y_group: int
    y_swatch: int
    y_dots0: int
    y_col_label: int
    row_label_x: int
    row_label_w: int
    row_label_max_w: int
    wrapped: list
    line_h: int
    title_lines: list
    title_line_h: int
    width: int
    height: int


def layout_matrix(col_images, base_values, col_values, cell_size, cell_mode, font_size, title=""):
    cell_w, cell_h = cell_dims(col_images, cell_size, cell_mode)
    base_px = font_size_for_char_width(cell_w / 16.0 * font_size)
    small = max(8, round(base_px * 0.3))
    fonts = {k: find_font(round(base_px * m)) for k, m in (("title", 1.6), ("group", 1.15), ("row", 1.1), ("col", 1))}
    scratch = scratch_draw()
    row_line_h = line_height(scratch, fonts["row"])

    pad = max(20, round(base_px * 0.6))
    dot_r = max(4, round(base_px * 0.35))
    row_half_extent = max(round(row_line_h * 0.6), dot_r + 4)
    dot_gap = max(row_line_h + max(10, round(base_px * 0.3)), round(base_px * 1.6))
    # Row labels get the width of the longest one, capped at 1.5 cells so a
    # single huge label can't blow up the layout (it gets an ellipsis).
    row_label_x = max(12, round(base_px * 0.3))
    longest = max((scratch.textbbox((0, 0), str(v), font=fonts["row"])[2] for v in base_values), default=0)
    row_label_w = max(60, row_label_x + min(longest, round(cell_w * 1.5)) + small)

    # The title wraps (a whole prompt can be long) and is cut to a few lines, so it
    # can't stretch the matrix; the matrix is never narrower than the title's lines.
    content_w = row_label_w + len(col_images) * (cell_w + max(10, round(base_px * 0.3))) + pad
    title_lines = wrap_title(title, fonts["title"], max(content_w, MIN_TITLE_WIDTH) - 40, scratch)
    title_line_h = line_height(scratch, fonts["title"]) + 4
    title_w = max((scratch.textbbox((0, 0), line, font=fonts["title"])[2] for line in title_lines), default=0) + 40
    y_group = len(title_lines) * title_line_h + max(16, round(base_px * 0.5))
    y_swatch = y_group + line_height(scratch, fonts["group"]) + small
    y_dots0 = y_swatch + cell_h + max(row_half_extent, round(base_px * 0.3), 10)
    y_last_dot = y_dots0 + max(0, len(base_values) - 1) * dot_gap
    y_col_label = y_last_dot + max(row_half_extent, small) + small

    # Column labels wrap horizontally within their own swatch width.
    wrapped = [wrap_text_to_width(v, fonts["col"], cell_w + 12, scratch) for v in col_values]
    line_h = line_height(scratch, fonts["col"]) + 3
    col_w = cell_w + max(10, round(base_px * 0.3))
    return MatrixLayout(
        cell_w=cell_w,
        cell_h=cell_h,
        base_px=base_px,
        font_title=fonts["title"],
        font_group=fonts["group"],
        font_row=fonts["row"],
        font_col=fonts["col"],
        pad=pad,
        col_w=col_w,
        dot_r=dot_r,
        dot_gap=dot_gap,
        y_group=y_group,
        y_swatch=y_swatch,
        y_dots0=y_dots0,
        y_col_label=y_col_label,
        row_label_x=row_label_x,
        row_label_w=row_label_w,
        row_label_max_w=max(10, row_label_w - row_label_x - small),
        wrapped=wrapped,
        line_h=line_h,
        title_lines=title_lines,
        title_line_h=title_line_h,
        width=max(row_label_w + len(col_images) * col_w + pad, title_w),
        height=y_col_label + max((len(w) for w in wrapped), default=1) * line_h + pad,
    )


def _arity_runs(col_meta):
    """(start, end, arity) for each run of consecutive equal-arity columns."""
    runs, start = [], 0
    for j in range(1, len(col_meta) + 1):
        if j == len(col_meta) or col_meta[j]["arity"] != col_meta[start]["arity"]:
            runs.append((start, j, col_meta[start]["arity"]))
            start = j
    return runs


def _draw_headers_and_rows(draw, lay, base_values, col_meta):
    top = max(8, round(lay.base_px * 0.2))
    for n, line in enumerate(lay.title_lines):
        draw.text(
            (lay.width // 2, top + n * lay.title_line_h), line, fill=(255, 255, 255), font=lay.font_title, anchor="mt"
        )
    for start, end, arity in _arity_runs(col_meta):
        cx = lay.row_label_w + (start + end) / 2 * lay.col_w
        draw.text(
            (cx, lay.y_group), f"Arity {arity} ({end - start})", fill=GROUP_TEXT_COLOR, font=lay.font_group, anchor="mt"
        )
        if start > 0:
            bx = lay.row_label_w + start * lay.col_w
            draw.line([(bx, lay.y_group - 4), (bx, lay.height - lay.pad // 2)], fill=DIVIDER_COLOR, width=1)
    # Full-width guides behind everything keep wide matrices traceable by row.
    for i in range(len(base_values)):
        y = lay.y_dots0 + i * lay.dot_gap
        draw.line([(0, y), (lay.width, y)], fill=GUIDE_COLOR, width=1)
    scratch = scratch_draw()
    for i, value in enumerate(base_values):
        y = lay.y_dots0 + i * lay.dot_gap
        label = truncate_text_to_width(value, lay.font_row, lay.row_label_max_w, scratch)
        draw.text((lay.row_label_x, y), label, fill=(210, 210, 210), font=lay.font_row, anchor="lm")


def _draw_column(canvas, draw, lay, j, img, members, n_rows, cell_mode):
    cx = lay.row_label_w + j * lay.col_w + lay.col_w // 2
    sx = lay.row_label_w + j * lay.col_w + (lay.col_w - lay.cell_w) // 2
    if img is None:
        draw_missing_cell(draw, sx, lay.y_swatch, lay.cell_w, lay.cell_h, lay.font_col, width=2)
    else:
        paste_into_cell(canvas, tensor_to_pil(img), sx, lay.y_swatch, lay.cell_w, lay.cell_h, cell_mode)
    if len(members) > 1:  # a connecting line needs at least two dots
        ys = [lay.y_dots0 + i * lay.dot_gap for i in members]
        draw.line([(cx, min(ys)), (cx, max(ys))], fill=DOT_COLOR, width=2)
    for i in range(n_rows):
        y = lay.y_dots0 + i * lay.dot_gap
        r = lay.dot_r if i in members else max(2, round(lay.dot_r * 0.5))
        draw.ellipse([cx - r, y - r, cx + r, y + r], fill=DOT_COLOR if i in members else EMPTY_DOT_COLOR)
    for li, line in enumerate(lay.wrapped[j]):
        draw.text((cx, lay.y_col_label + li * lay.line_h), line, fill=COLUMN_TEXT_COLOR, font=lay.font_col, anchor="mt")


def draw_matrix(col_images, target, lo, hi, title, cell_size, cell_mode, font_size):
    """One UpSet page for columns lo..hi of the self-combined `target`: a
    swatch per column, a dot per (row, column) showing which base values
    each combination contains, and labels."""
    base_values, col_values, col_meta = target["base_values"], target["values"][lo:hi], target["combo_meta"][lo:hi]
    lay = layout_matrix(col_images, base_values, col_values, cell_size, cell_mode, font_size, title)
    check_canvas_size(lay.width, lay.height, "Sweep UpSet Matrix", "lower max_columns_per_page")
    canvas = Image.new("RGB", (lay.width, lay.height), BACKGROUND)
    draw = ImageDraw.Draw(canvas)
    _draw_headers_and_rows(draw, lay, base_values, col_meta)
    for j, img in enumerate(col_images):
        _draw_column(canvas, draw, lay, j, img, set(col_meta[j]["members"]), len(base_values), cell_mode)
    return canvas


NODE_CLASS_MAPPINGS = {
    "SweepUpsetConstructor": SweepUpsetConstructor,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SweepUpsetConstructor": "Sweep UpSet Matrix",
}
