"""
Image and grid helpers shared by SweepAllInOne, SweepGridConstructor and
SweepUpsetConstructor.

Keeping one copy means a fix (e.g. reading image height/width from the
end of the tensor shape) applies to every node at once.

Unlike sweep_core.py this module needs torch, so it is only imported by
the node modules, never by the pure-logic tests.
"""

from __future__ import annotations

import itertools
import os
import time
from dataclasses import dataclass
from typing import Any, Sequence

import comfy.model_management
import comfy.utils
import numpy as np
import torch
from PIL import Image, ImageDraw, ImageFont

from .sweep_core import (
    Dimension,
    dim_group_members,
    format_group_value,
    next_versioned_path,
    resolve_grid_axes,
    resolve_group_index,
    safe_component,
)
from .sweep_draw import (
    check_canvas_size,
    find_font,
    font_size_for_char_width,
    pad_image,
    padded_batch_size,
    wrap_text_to_width,
)

BACKGROUND = (16, 16, 16)
LABEL_COLOR = (210, 210, 210)
TITLE_COLOR = (255, 255, 255)
MISSING_OUTLINE = (90, 30, 30)
MISSING_TEXT = (200, 120, 120)
PENDING_OUTLINE = (55, 55, 55)
PENDING_TEXT = (110, 110, 110)


# ---------------------------------------------------------------- tensors


def tensor_to_pil(tensor: Any) -> Image.Image:
    """ComfyUI IMAGE tensor (values 0..1, channels last) -> PIL image.
    squeeze() drops any size-1 batch/frame dimensions."""
    arr = 255.0 * tensor.cpu().numpy()
    return Image.fromarray(np.clip(arr.squeeze(), 0, 255).astype(np.uint8))


def pil_to_tensor(pil_img: Image.Image) -> Any:
    """PIL image -> ComfyUI IMAGE tensor with a batch dimension of 1."""
    arr = np.array(pil_img).astype(np.float32) / 255.0
    return torch.from_numpy(arr).unsqueeze(0)


def hw_from_tensor(img: Any) -> tuple[int, int]:
    """(height, width) of an image tensor, read from the END of its shape.

    ComfyUI images are channels-last (..., H, W, C). A plain image is
    [batch, H, W, C], but video-capable VAEs (e.g. WanVAE) return
    [batch, frames, H, W, C] even for a still image, so fixed positions
    shape[1]/shape[2] would read the frame count as the height."""
    shape = img.shape
    return shape[-3], shape[-2]


def stack_padded(images: Sequence[Image.Image]) -> Any:
    """Stack PIL images into one IMAGE batch, padding smaller ones with the
    grid background (top-left aligned) instead of stretching them."""
    if not images:
        return torch.zeros(1, 512, 512, 3)
    width, height = padded_batch_size([im.size for im in images])
    return torch.cat([pil_to_tensor(pad_image(im, width, height, BACKGROUND)) for im in images], dim=0)


# ------------------------------------------------------------------ cells


def cell_dims(images: Sequence[Any], cell_size: int, cell_mode: str) -> tuple[int, int]:
    """(cell_w, cell_h) shared by every cell of a grid.

    'fit' scales the first image so its longer side is cell_size,
    'original' uses the largest native size present, 'square' forces
    cell_size x cell_size."""
    real = [img for img in images if img is not None]
    if not real:
        return cell_size, cell_size
    if cell_mode == "original":
        sizes = [hw_from_tensor(img) for img in real]
        return max(w for _, w in sizes), max(h for h, _ in sizes)
    if cell_mode == "fit":
        h0, w0 = hw_from_tensor(real[0])
        scale = cell_size / max(h0, w0)
        return max(1, round(w0 * scale)), max(1, round(h0 * scale))
    return cell_size, cell_size


def paste_into_cell(
    canvas: Image.Image, pil_img: Image.Image, x: int, y: int, cell_w: int, cell_h: int, cell_mode: str
) -> None:
    """Draw one image into its cell. 'square' stretches to fill the cell;
    'fit'/'original' keep the image's own aspect ratio and centre it, so
    nothing is distorted even when resolutions differ across a sweep."""
    if cell_mode == "square":
        canvas.paste(pil_img.resize((cell_w, cell_h), Image.LANCZOS), (x, y))
        return
    iw, ih = pil_img.size
    scale = min(cell_w / iw, cell_h / ih)
    new_w, new_h = max(1, round(iw * scale)), max(1, round(ih * scale))
    resized = pil_img.resize((new_w, new_h), Image.LANCZOS)
    canvas.paste(resized, (x + (cell_w - new_w) // 2, y + (cell_h - new_h) // 2))


def draw_missing_cell(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    cell_w: int,
    cell_h: int,
    font: Any,
    width: int = 3,
    pending: bool = False,
) -> None:
    """Placeholder for a combination with no image: red 'missing' for a
    deduped slot, or a quiet grey 'pending' tile while a live preview is
    still waiting for that image."""
    outline, color, text = (
        (PENDING_OUTLINE, PENDING_TEXT, "…") if pending else (MISSING_OUTLINE, MISSING_TEXT, "missing")
    )
    draw.rectangle([x, y, x + cell_w, y + cell_h], outline=outline, width=width)
    draw.text((x + cell_w // 2, y + cell_h // 2), text, fill=color, font=font, anchor="mm")


def line_height(scratch: ImageDraw.ImageDraw, font: Any) -> int:
    """Rendered height of one line of text in this font."""
    box = scratch.textbbox((0, 0), "Ag0jJ", font=font)
    return max(1, box[3] - box[1])


def scratch_draw() -> ImageDraw.ImageDraw:
    """A throwaway drawing context for measuring text."""
    return ImageDraw.Draw(Image.new("RGB", (1, 1)))


# ------------------------------------------------------------------- grid


@dataclass
class GridLayout:
    """Every measurement make_grid needs, computed before drawing."""

    cols: int
    rows: int
    cell_w: int
    cell_h: int
    font_title: ImageFont.ImageFont
    font_x: ImageFont.ImageFont
    font_y: ImageFont.ImageFont
    base_px: int
    wrapped_x: list[list[str]]
    wrapped_y: list[list[str]]
    x_line_spacing: int
    y_line_spacing: int
    label_w: int
    label_h: int
    y_left_x: int
    title_h: int
    title_gap: int
    width: int
    height: int

    @property
    def labels_top(self) -> int:
        return self.title_h + self.title_gap

    @property
    def grid_top(self) -> int:
        return self.labels_top + self.label_h


def layout_grid(
    images: Sequence[Any],
    x_labels: Sequence[str],
    y_labels: Sequence[str],
    title: str,
    cell_size: int,
    cell_mode: str,
    font_size: float,
    base_px: int | None,
) -> GridLayout:
    """Measure fonts, wrapped labels and canvas. Fonts scale with the real
    cell width (font_size 1.0 ~ 16 characters per cell); base_px fixes it."""
    cell_w, cell_h = cell_dims(images, cell_size, cell_mode)
    if base_px is None:
        base_px = font_size_for_char_width(cell_w / 16.0 * font_size)
    spacing = max(8, round(base_px * 0.3))
    font_title = find_font(round(base_px * 1.6))
    font_x = find_font(base_px)
    font_y = find_font(round(base_px * 1.1))
    scratch = scratch_draw()

    # Column labels wrap within their own column; the label band grows to
    # the tallest wrapped label so nothing is clipped.
    wrapped_x = [wrap_text_to_width(lab, font_x, cell_w + 12, scratch) for lab in x_labels]
    x_line_spacing = line_height(scratch, font_x) + 3
    label_h = max((len(w) for w in wrapped_x), default=1) * x_line_spacing + spacing

    # Row labels wrap within a left column that scales with the cell size.
    label_w = max(140, round(cell_w * 0.25))
    y_left_x = spacing
    wrapped_y = [wrap_text_to_width(lab, font_y, max(10, label_w - 2 * spacing), scratch) for lab in y_labels]

    pad = max(20, round(base_px * 0.6))
    title_h = line_height(scratch, font_title) + pad
    cols, rows = max(len(x_labels), 1), max(len(y_labels), 1)
    # The canvas is at least as wide as the title, so a long combined title
    # on a narrow grid isn't clipped.
    title_w = scratch.textbbox((0, 0), str(title), font=font_title)[2] + 40
    return GridLayout(
        cols=cols,
        rows=rows,
        cell_w=cell_w,
        cell_h=cell_h,
        font_title=font_title,
        font_x=font_x,
        font_y=font_y,
        base_px=base_px,
        wrapped_x=wrapped_x,
        wrapped_y=wrapped_y,
        x_line_spacing=x_line_spacing,
        y_line_spacing=line_height(scratch, font_y) + 3,
        label_w=label_w,
        label_h=label_h,
        y_left_x=y_left_x,
        title_h=title_h,
        title_gap=spacing,
        width=max(cols * cell_w + label_w + pad, title_w),
        height=rows * cell_h + title_h + spacing + label_h + pad,
    )


def _draw_grid_labels(draw: ImageDraw.ImageDraw, lay: GridLayout, title: str) -> None:
    draw.text(
        (lay.width // 2, max(8, round(lay.base_px * 0.2))),
        str(title),
        fill=TITLE_COLOR,
        font=lay.font_title,
        anchor="mt",
    )
    for i, lines in enumerate(lay.wrapped_x):
        x = lay.label_w + i * lay.cell_w + lay.cell_w // 2
        for li, line in enumerate(lines):
            draw.text(
                (x, lay.labels_top + li * lay.x_line_spacing), line, fill=LABEL_COLOR, font=lay.font_x, anchor="mt"
            )
    for r, lines in enumerate(lay.wrapped_y[: lay.rows]):
        # Centre the whole wrapped block on the row, not just its first line.
        first_y = lay.grid_top + r * lay.cell_h + lay.cell_h // 2 - (len(lines) - 1) * lay.y_line_spacing / 2
        for li, line in enumerate(lines):
            draw.text(
                (lay.y_left_x, round(first_y + li * lay.y_line_spacing)),
                line,
                fill=LABEL_COLOR,
                font=lay.font_y,
                anchor="lm",
            )


def make_grid(
    images: Sequence[Any],
    x_labels: Sequence[str],
    y_labels: Sequence[str],
    title: str,
    cell_size: int = 512,
    cell_mode: str = "fit",
    font_size: float = 0.4,
    base_px: int | None = None,
    node_tag: str = "SweepGridConstructor",
    pending: bool = False,
) -> Image.Image:
    """Render one labelled X/Y grid. `images` is row-major (len rows*cols);
    a None entry draws a 'missing' placeholder ('pending' for live previews)."""
    lay = layout_grid(images, x_labels, y_labels, title, cell_size, cell_mode, font_size, base_px)
    check_canvas_size(lay.width, lay.height, node_tag)
    grid = Image.new("RGB", (lay.width, lay.height), BACKGROUND)
    draw = ImageDraw.Draw(grid)
    _draw_grid_labels(draw, lay, title)
    for idx in range(lay.rows * lay.cols):
        r, c = divmod(idx, lay.cols)
        x, y = lay.label_w + c * lay.cell_w, lay.grid_top + r * lay.cell_h
        img = images[idx] if idx < len(images) else None
        if img is None:
            draw_missing_cell(draw, x, y, lay.cell_w, lay.cell_h, lay.font_x, pending=pending)
        else:
            paste_into_cell(grid, tensor_to_pil(img), x, y, lay.cell_w, lay.cell_h, cell_mode)
    return grid


# ------------------------------------------------------------ grid sets


def unpack_combo(
    images: Sequence[Any], combo: dict, node_tag: str, hint: str = ""
) -> tuple[list[Dimension], list[Any], list[dict]]:
    """(dimensions in chain order, images, combo_records) from a node's
    `images` + `combo` inputs, checking they line up one-to-one."""
    dims_sorted = sorted([dict(d) for d in combo["dimensions"]], key=lambda d: d["index"])
    images, combo_records = list(images), list(combo["combo_records"])
    if len(images) != len(combo_records):
        raise ValueError(
            f"[{node_tag}] images has {len(images)} entries but combo has {len(combo_records)} combo_records — "
            f"they must be the same length and in the same order (did dedup/gather get wired up correctly?)."
            + (f" {hint}" if hint else "")
        )
    return dims_sorted, images, combo_records


def images_by_combo(
    combo_records: Sequence[dict], images: Sequence[Any], dims_sorted: Sequence[Dimension]
) -> dict[tuple, Any]:
    """Map each combination's per-dimension value indices (in chain order)
    to its image, from parallel combo_records / images lists."""
    return {
        tuple(rec["idx_by_dim"][d["index"]] for d in dims_sorted): img
        for rec, img in zip(combo_records, images, strict=True)
    }


def axis_values(dim: Dimension | None, dims_sorted: Sequence[Dimension]) -> tuple[list[int], list[str]]:
    """Index range and display labels for a grid axis (one blank slot when
    the axis is unused). Zipped groups show every member's value."""
    if dim is None:
        return [0], [""]
    indices = list(range(len(dim["values"])))
    members = dim_group_members(dim, dims_sorted)
    return indices, [format_group_value(members, i) for i in indices]


def axis_caption(x_dim: Dimension | None, y_dim: Dimension | None) -> str:
    """'X: <label>   Y: <label>' so axes are named even with no title dim."""
    bits = [f"{name}: {d.get('group_label', d['dim_id'])}" for name, d in (("X", x_dim), ("Y", y_dim)) if d]
    return "   ".join(bits)


def cell_key(dims_sorted: Sequence[Dimension], fixed: dict[int, int], *axes: tuple[Dimension | None, int]) -> tuple:
    """all_images key for one cell: the grouping indices in `fixed` plus
    each (axis dimension, index). A zip partner without its own role takes
    its groupmate's index."""
    full_idx = dict(fixed)
    for dim, i in axes:
        if dim:
            full_idx[dim["index"]] = i
    return tuple(resolve_group_index(d, full_idx, dims_sorted) for d in dims_sorted)


def grid_title(grouping: Sequence[Dimension], shown: Sequence[str], caption: str, fallback: str) -> str:
    """'label: value | ...' for the grouping axes, plus the X/Y caption."""
    bits = [f"{d.get('group_label', d['dim_id'])}: {v}" for d, v in zip(grouping, shown, strict=True)]
    if not bits:
        return caption or fallback
    return f"{' | '.join(bits)}   •   {caption}" if caption else " | ".join(bits)


@dataclass
class GridSpec:
    """Everything build_grids needs besides the images."""

    grid_x_dim: str
    grid_y_dim: str
    grid_title_dim: str
    cell_size: int
    cell_mode: str
    prefix_folder: str
    output_dir: str
    node_tag: str
    font_size: float = 0.4
    base_px: int | None = None


@dataclass
class GridAxes:
    """The resolved X / Y / title / grouping dimensions of a grid set, with
    their labels. One grid is drawn per combination of `grouping` values."""

    x_dim: Dimension | None
    y_dim: Dimension | None
    title_dim: Dimension | None
    grouping: list[Dimension]
    x_range: list[int]
    x_labels: list[str]
    y_range: list[int]
    y_labels: list[str]
    caption: str


def resolve_axes(dims_sorted: Sequence[Dimension], spec: GridSpec) -> GridAxes:
    """Resolve the X/Y/Title picks of `spec` into a GridAxes."""
    x_dim, y_dim, title_dim, other_dims = resolve_grid_axes(
        dims_sorted, spec.grid_x_dim, spec.grid_y_dim, spec.grid_title_dim, node_tag=spec.node_tag
    )
    x_range, x_labels = axis_values(x_dim, dims_sorted)
    y_range, y_labels = axis_values(y_dim, dims_sorted)
    return GridAxes(
        x_dim,
        y_dim,
        title_dim,
        ([title_dim] if title_dim else []) + other_dims,
        x_range,
        x_labels,
        y_range,
        y_labels,
        axis_caption(x_dim, y_dim),
    )


def page_title(
    axes: GridAxes, dims_sorted: Sequence[Dimension], page: Sequence[int], fallback: str
) -> tuple[str, list[str]]:
    """(grid title, shown grouping values) for one page of a grid set."""
    shown = [
        format_group_value(dim_group_members(d, dims_sorted), vi) for d, vi in zip(axes.grouping, page, strict=True)
    ]
    return grid_title(axes.grouping, shown, axes.caption, fallback), shown


def build_grids(
    all_images: dict[tuple, Any],
    dims_sorted: Sequence[Dimension],
    spec: GridSpec,
    axes: GridAxes | None = None,
) -> tuple[list[Image.Image], list[str]]:
    """Resolve the X/Y/Title axes (unless `axes` is given), then render and
    save one grid per combination of the remaining (grouping) axes.

    Returns (grid images, saved paths). Checks for interrupts and reports
    progress once per grid. Grids are saved under
    <output>/<prefix>/_grids/<grouping values...>_NNNNN.png and never
    overwrite earlier runs."""
    axes = axes or resolve_axes(dims_sorted, spec)
    x_dim, y_dim, grouping = axes.x_dim, axes.y_dim, axes.grouping
    combos = list(itertools.product(*[range(len(d["values"])) for d in grouping]))
    print(
        f"[{spec.node_tag}] Building {len(combos)} grid(s) (x={x_dim['dim_id'] if x_dim else '—'}, "
        f"y={y_dim['dim_id'] if y_dim else '—'}{', title=' + axes.title_dim['dim_id'] if axes.title_dim else ''})"
    )

    pbar = comfy.utils.ProgressBar(len(combos))
    grids, paths = [], []
    for group_combo in combos:
        comfy.model_management.throw_exception_if_processing_interrupted()
        fixed = {d["index"]: vi for d, vi in zip(grouping, group_combo, strict=True)}
        cells = [
            all_images.get(cell_key(dims_sorted, fixed, (x_dim, xi), (y_dim, yi)))
            for yi in axes.y_range
            for xi in axes.x_range
        ]
        title, shown = page_title(axes, dims_sorted, group_combo, spec.prefix_folder)
        grid = make_grid(
            cells,
            axes.x_labels,
            axes.y_labels,
            title,
            spec.cell_size,
            spec.cell_mode,
            spec.font_size,
            spec.base_px,
            spec.node_tag,
        )
        folders = [safe_component(v) for v in shown]
        grid_dir = os.path.join(spec.output_dir, spec.prefix_folder, "_grids", *folders[:-1])
        path = next_versioned_path(grid_dir, folders[-1] if folders else "grid")
        grid.save(path)
        grids.append(grid)
        paths.append(path)
        pbar.update(1)
    return grids, paths


# ------------------------------------------------------------ live preview

PREVIEW_CELL = 192  # cell size of the on-node preview; the saved grid keeps its own size
PREVIEW_MAX_SIDE = 768  # longest side of the preview image sent to the browser
PREVIEW_MIN_INTERVAL = 0.3  # seconds between previews, so fast sweeps don't flood the socket


class LiveGrid:
    """The grid so far, drawn on the node while a sweep is still sampling.

    Cells that haven't finished show as quiet 'pending' tiles. With several
    grids (extra dimensions) it shows the page of the newest image. Only
    small thumbnails are kept, so this costs little RAM and no extra
    sampling. Frames go out through ComfyUI's progress-bar preview."""

    def __init__(self, dims_sorted: Sequence[Dimension], spec: GridSpec, axes: GridAxes) -> None:
        self.dims_sorted, self.spec, self.axes = dims_sorted, spec, axes
        self.pages: dict[tuple, dict[tuple[int, int], Any]] = {}
        self.latest: tuple | None = None
        self._last_sent = 0.0

    def add(self, idx_by_dim: dict[int, int], image: Any) -> None:
        """Record a finished image under its page and cell."""
        ax = self.axes
        page = tuple(idx_by_dim[d["index"]] for d in ax.grouping)
        cell = (idx_by_dim[ax.x_dim["index"]] if ax.x_dim else 0, idx_by_dim[ax.y_dim["index"]] if ax.y_dim else 0)
        thumb = tensor_to_pil(image)
        thumb.thumbnail((PREVIEW_CELL, PREVIEW_CELL))
        self.pages.setdefault(page, {})[cell] = pil_to_tensor(thumb)
        self.latest = page

    def due(self, final: bool) -> bool:
        """True when a frame should be sent now (rate-limited unless final)."""
        now = time.monotonic()
        if final or now - self._last_sent >= PREVIEW_MIN_INTERVAL:
            self._last_sent = now
            return True
        return False

    def render(self) -> Image.Image | None:
        """The current page as one labelled image, or None before any image."""
        if self.latest is None:
            return None
        ax, done = self.axes, self.pages[self.latest]
        cells = [done.get((xi, yi)) for yi in ax.y_range for xi in ax.x_range]
        title, _ = page_title(ax, self.dims_sorted, self.latest, self.spec.prefix_folder)
        grid = make_grid(
            cells,
            ax.x_labels,
            ax.y_labels,
            title,
            min(self.spec.cell_size, PREVIEW_CELL),
            self.spec.cell_mode,
            1.0,
            None,
            self.spec.node_tag,
            pending=True,
        )
        grid.thumbnail((PREVIEW_MAX_SIDE, PREVIEW_MAX_SIDE))
        return grid
