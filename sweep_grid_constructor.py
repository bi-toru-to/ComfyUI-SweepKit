"""
SweepGridConstructor — builds X/Y/Title grids from an already-sampled
image list, instead of doing it inline at the end of a monolithic sampling
loop. This is almost a verbatim port of SweepAllInOne's old "Build
grids" section (resolve_grid_axes / make_grid / save-to-disk) — the only
real change is WHERE the per-combo image lookup dict comes from: it used
to be built incrementally during sampling (`all_images[key] = image`
inside the loop); here it's rebuilt in one pass from `images` +
`combo_records`, which are already fully materialized by the time this
node runs.

That's the whole point of the split: tweaking cell_size, cell_mode, or
which dimension is X/Y/Title now only reruns THIS node — ComfyUI's normal
node-level caching means sampling stays cached, since none of its inputs
changed.

images must be a PYLIST (one entry per combo, same order as
combo_records) rather than a single batched IMAGE tensor — feed it from
VAEDecode's IMAGE List output through List-Utils' "List To PyList", since
per-combo images aren't guaranteed to share one resolution the way a
single batch tensor requires.
"""

import os
import torch
import numpy as np
from PIL import Image, ImageDraw
import folder_paths
import itertools

from .sweep_core import (
    GRID_AXIS_OPTIONS,
    safe_component,
    resolve_grid_axes,
    resolve_group_index,
    dim_group_members,
    format_group_value,
    find_font,
    font_size_for_char_width,
    wrap_text_to_width,
    next_versioned_path,
)


class SweepGridConstructor:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": (
                    "PYLIST",
                    {
                        "forceInput": True,
                        "tooltip": "One image tensor per combo, same order as combo.combo_records — connect via List-Utils' 'List To PyList', fed from VAEDecode's IMAGE List output.",
                    },
                ),
                "combo": (
                    "SWEEP_COMBO",
                    {
                        "tooltip": "Connect SweepCombinationExpander's 'combo' output.",
                    },
                ),
                "filename_prefix": ("STRING", {"default": "SweepKit"}),
                "cell_size": ("INT", {"default": 512, "min": 64, "max": 4096, "step": 64}),
                "cell_mode": (["fit", "square", "original"], {"default": "fit"}),
                "font_size": (
                    "FLOAT",
                    {
                        "default": 0.4,
                        "min": 0.0,
                        "max": 1.0,
                        "step": 0.05,
                        "tooltip": (
                            "Text size as a fraction of the ACTUAL rendered cell width (not the "
                            "cell_size widget) — 1.0 means one character is about 1/16 of a cell's "
                            "width. Sized off the real cell width specifically so cell_mode='original' "
                            "(whose actual size can differ a lot from cell_size) doesn't end up with "
                            "text that's disproportionately tiny or huge next to the images. Title "
                            "text stays proportionally larger than axis labels at every setting."
                        ),
                    },
                ),
                "grid_x_dim": (GRID_AXIS_OPTIONS, {"default": "auto"}),
                "grid_y_dim": (GRID_AXIS_OPTIONS, {"default": "auto"}),
                "grid_title_dim": (GRID_AXIS_OPTIONS, {"default": "auto"}),
            },
        }

    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("grids", "summary")
    FUNCTION = "build"
    CATEGORY = "SweepKit/Modular"
    OUTPUT_NODE = True

    # ---- tensor/PIL helpers (unchanged from the old monolith) ----

    def tensor_to_pil(self, tensor):
        i = 255.0 * tensor.cpu().numpy()
        return Image.fromarray(np.clip(i.squeeze(), 0, 255).astype(np.uint8))

    def pil_to_tensor(self, pil_img):
        arr = np.array(pil_img).astype(np.float32) / 255.0
        return torch.from_numpy(arr).unsqueeze(0)

    def _hw_from_tensor(self, img):
        shape = img.shape
        return shape[-3], shape[-2]

    def _cell_dims(self, images, cell_size, cell_mode):
        real = [img for img in images if img is not None]
        if not real:
            return cell_size, cell_size
        h0, w0 = self._hw_from_tensor(real[0])
        if cell_mode == "original":
            hws = [self._hw_from_tensor(img) for img in real]
            return max(w for h, w in hws), max(h for h, w in hws)
        elif cell_mode == "fit":
            scale = cell_size / max(h0, w0)
            return max(1, round(w0 * scale)), max(1, round(h0 * scale))
        else:
            return cell_size, cell_size

    def _paste_into_cell(self, grid, pil_img, x, y, cell_w, cell_h, cell_mode):
        if cell_mode == "square":
            resized = pil_img.resize((cell_w, cell_h), Image.LANCZOS)
            grid.paste(resized, (x, y))
            return
        iw, ih = pil_img.size
        scale = min(cell_w / iw, cell_h / ih)
        new_w, new_h = max(1, round(iw * scale)), max(1, round(ih * scale))
        resized = pil_img.resize((new_w, new_h), Image.LANCZOS)
        off_x = x + (cell_w - new_w) // 2
        off_y = y + (cell_h - new_h) // 2
        grid.paste(resized, (off_x, off_y))

    def make_grid(self, images, x_labels, y_labels, title, cell_size=512, cell_mode="fit", font_size=0.4):
        cols = max(len(x_labels), 1)
        rows = max(len(y_labels), 1)

        cell_w, cell_h = self._cell_dims(images, cell_size, cell_mode)

        # Font hierarchy matches SweepUpsetConstructor's: title stays
        # clearly the largest, X labels (column headers, playing the same
        # role as Upset's column labels) sit at the base size, Y labels
        # (row headers, playing the same role as Upset's row labels) get
        # a slight emphasis over the base. Sized off the ACTUAL rendered
        # cell width, not the nominal cell_size widget, for the same
        # cell_mode='original' reason as there.
        base_px = font_size_for_char_width(cell_w / 16.0 * font_size)
        font_title = find_font(round(base_px * 1.6))
        font_x_label = find_font(base_px)
        font_y_label = find_font(round(base_px * 1.1))

        scratch = ImageDraw.Draw(Image.new("RGB", (1, 1)))

        def _line_h(font):
            b = scratch.textbbox((0, 0), "Ag0jJ", font=font)
            return max(1, b[3] - b[1])

        title_line_h = _line_h(font_title)
        x_label_line_h = _line_h(font_x_label)
        y_label_line_h = _line_h(font_y_label)

        pad = max(20, round(base_px * 0.6))
        title_h = title_line_h + max(20, round(base_px * 0.6))
        title_gap = max(8, round(base_px * 0.3))

        # X (column) labels word-wrap within their own column's width, the
        # same way SweepUpsetConstructor's column labels do -- a fixed
        # single line routinely ran wider than one column and overflowed
        # behind the image or the neighboring label. label_h grows to fit
        # the tallest wrapped label instead of a fixed guess, so it can
        # never clip either.
        x_label_max_w = cell_w + 12
        wrapped_x = [wrap_text_to_width(lab, font_x_label, x_label_max_w, scratch) for lab in x_labels]
        x_line_spacing = x_label_line_h + 3
        max_x_lines = max((len(w) for w in wrapped_x), default=1)
        label_h = max_x_lines * x_line_spacing + max(8, round(base_px * 0.3))

        # Y (row) labels word-wrap within a reserved left column, scaled to
        # the actual cell width rather than a small fixed guess, so bigger
        # images/fonts get proportionally more room instead of overflowing
        # into the images.
        label_w = max(140, round(cell_w * 0.25))
        y_left_x = max(8, round(base_px * 0.3))
        y_label_max_w = max(10, label_w - y_left_x - max(8, round(base_px * 0.3)))
        wrapped_y = [wrap_text_to_width(lab, font_y_label, y_label_max_w, scratch) for lab in y_labels]
        y_line_spacing = y_label_line_h + 3

        # Canvas width must accommodate the title text too -- a narrow grid
        # (few columns) paired with a long combined title (e.g. several
        # zipped dimensions' values joined together) would otherwise get
        # clipped at both edges, since width used to be computed only from
        # cols * cell_w, never from the title string's own rendered width.
        title_w = scratch.textbbox((0, 0), str(title), font=font_title)[2] + 40

        W = max(cols * cell_w + label_w + pad, title_w)
        H = rows * cell_h + title_h + title_gap + label_h + pad
        grid = Image.new("RGB", (W, H), (16, 16, 16))
        draw = ImageDraw.Draw(grid)

        draw.text(
            (W // 2, max(8, round(base_px * 0.2))), str(title), fill=(255, 255, 255), font=font_title, anchor="mt"
        )

        y_labels_top = title_h + title_gap
        for i, lines in enumerate(wrapped_x):
            x = label_w + i * cell_w + cell_w // 2
            for li, line in enumerate(lines):
                draw.text(
                    (x, y_labels_top + li * x_line_spacing), line, fill=(210, 210, 210), font=font_x_label, anchor="mt"
                )

        grid_top = y_labels_top + label_h
        idx = 0
        for r in range(rows):
            y = grid_top + r * cell_h
            lines = wrapped_y[r] if r < len(wrapped_y) else []
            # Vertically center the whole wrapped block on the row's own
            # center, not just the first line -- otherwise a 2-3 line
            # label would run past the row's midpoint instead of being
            # balanced around it.
            first_center_y = y + cell_h // 2 - (len(lines) - 1) * y_line_spacing / 2
            for li, line in enumerate(lines):
                draw.text(
                    (y_left_x, round(first_center_y + li * y_line_spacing)),
                    line,
                    fill=(210, 210, 210),
                    font=font_y_label,
                    anchor="lm",
                )
            for c in range(cols):
                img = images[idx] if idx < len(images) else None
                cell_x = label_w + c * cell_w
                if img is not None:
                    pil = self.tensor_to_pil(img)
                    self._paste_into_cell(grid, pil, cell_x, y, cell_w, cell_h, cell_mode)
                else:
                    box = [cell_x, y, cell_x + cell_w, y + cell_h]
                    draw.rectangle(box, outline=(90, 30, 30), width=3)
                    draw.text(
                        ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2),
                        "missing",
                        fill=(200, 120, 120),
                        font=font_x_label,
                        anchor="mm",
                    )
                idx += 1
        return grid

    # ---- main ----

    def build(
        self, images, combo, filename_prefix, cell_size, cell_mode, font_size, grid_x_dim, grid_y_dim, grid_title_dim
    ):
        dimensions, combo_records = combo["dimensions"], combo["combo_records"]
        output_dir = folder_paths.get_output_directory()
        # Sanitized to a single safe path component -- this is used
        # directly as a directory name below, so a value containing '/'
        # or other unsafe characters (whether typed deliberately to force
        # a subfolder, the way SaveImage's own filename_prefix works, or
        # just incidentally) can't produce a malformed path. Unlike
        # SaveImage, this node saves files itself rather than delegating
        # to ComfyUI's own filename_prefix parser, so it needs its own
        # folder unconditionally rather than only when the widget happens
        # to contain a '/'.
        prefix_folder = safe_component(filename_prefix) if str(filename_prefix).strip() else "SweepKit"
        active_dims_sorted = sorted([dict(d) for d in dimensions], key=lambda d: d["index"]) if dimensions else []
        images = list(images)
        combo_records = list(combo_records)

        if len(images) != len(combo_records):
            raise ValueError(
                f"[SweepGridConstructor] images has {len(images)} entries but combo has "
                f"{len(combo_records)} combo_records — they must be the same length and in "
                f"the same order (did dedup/gather get wired up correctly?)."
            )

        # Rebuild the same idx-tuple -> image lookup the old inline loop
        # used to build incrementally during sampling.
        all_images = {}
        for rec, img in zip(combo_records, images):
            key = tuple(rec["idx_by_dim"][d["index"]] for d in active_dims_sorted)
            all_images[key] = img

        grids, grid_paths = [], []

        x_dim, y_dim, title_dim, other_dims = resolve_grid_axes(
            active_dims_sorted, grid_x_dim, grid_y_dim, grid_title_dim
        )
        axis_grouping_dims = ([title_dim] if title_dim else []) + other_dims
        axis_grouping_ranges = [range(len(d["values"])) for d in axis_grouping_dims]
        x_range = list(range(len(x_dim["values"]))) if x_dim else [0]
        y_range = list(range(len(y_dim["values"]))) if y_dim else [0]

        total_grids = 1
        for r in axis_grouping_ranges:
            total_grids *= len(r)
        print(
            f"[SweepGridConstructor] Building {total_grids} grid(s) "
            f"(x={x_dim['dim_id'] if x_dim else '—'}, y={y_dim['dim_id'] if y_dim else '—'}"
            f"{', title=' + title_dim['dim_id'] if title_dim else ''})"
        )

        axis_caption_bits = []
        if x_dim:
            axis_caption_bits.append(f"X: {x_dim.get('group_label', x_dim['dim_id'])}")
        if y_dim:
            axis_caption_bits.append(f"Y: {y_dim.get('group_label', y_dim['dim_id'])}")
        axis_caption = "   ".join(axis_caption_bits)

        for axis_group_combo in itertools.product(*axis_grouping_ranges) if axis_grouping_dims else [()]:
            axis_group_idx = {d["index"]: vi for d, vi in zip(axis_grouping_dims, axis_group_combo)}

            cell_images = []
            for yi in y_range:
                for xi in x_range:
                    full_idx = dict(axis_group_idx)
                    if x_dim:
                        full_idx[x_dim["index"]] = xi
                    if y_dim:
                        full_idx[y_dim["index"]] = yi
                    key = tuple(resolve_group_index(d, full_idx, active_dims_sorted) for d in active_dims_sorted)
                    cell_images.append(all_images.get(key))

            x_labels = (
                [format_group_value(dim_group_members(x_dim, active_dims_sorted), xi) for xi in x_range]
                if x_dim
                else [""]
            )
            y_labels = (
                [format_group_value(dim_group_members(y_dim, active_dims_sorted), yi) for yi in y_range]
                if y_dim
                else [""]
            )

            title_bits, folder_parts = [], []
            for d, vi in zip(axis_grouping_dims, axis_group_combo):
                members = dim_group_members(d, active_dims_sorted)
                disp = format_group_value(members, vi)
                title_bits.append(f"{d.get('group_label', d['dim_id'])}: {disp}")
                folder_parts.append(safe_component(disp))
            title_text = " | ".join(title_bits) if title_bits else prefix_folder
            if axis_caption:
                title_text = f"{title_text}   •   {axis_caption}" if title_bits else axis_caption

            grid_pil = self.make_grid(cell_images, x_labels, y_labels, title_text, cell_size, cell_mode, font_size)

            grid_dir = (
                os.path.join(output_dir, prefix_folder, "_grids", *folder_parts[:-1])
                if len(folder_parts) > 1
                else os.path.join(output_dir, prefix_folder, "_grids")
            )
            # tail is used as a bare filename base here, never a path -- it
            # must never itself contain '/', which is exactly what used to
            # break when filename_prefix (now prefix_folder, kept
            # separate from this) contained one: concatenating an
            # un-created subdirectory into a "filename" string makes the
            # save() call below fail with FileNotFoundError. next_versioned_path
            # appends a 5-digit auto-incrementing counter (matching stock
            # SaveImage's own convention) so rerunning this node never
            # silently overwrites a previous grid -- direct PIL save()
            # calls have no such protection unless given one explicitly,
            # unlike SaveImage.
            tail = folder_parts[-1] if folder_parts else "grid"
            path = next_versioned_path(grid_dir, tail)
            grid_pil.save(path)
            grid_paths.append(path)
            grids.append(self.pil_to_tensor(grid_pil))

        if not grids:
            grids = [torch.zeros(1, 512, 512, 3)]

        if len(grids) > 1:
            target_shape = grids[0].shape
            fixed = []
            for g in grids:
                if g.shape != target_shape:
                    pil = self.tensor_to_pil(g[0]).resize((target_shape[2], target_shape[1]), Image.LANCZOS)
                    g = self.pil_to_tensor(pil)
                fixed.append(g)
            grids = fixed

        dim_map = "; ".join(f"dim{d['index']}='{d['dim_id']}'" for d in active_dims_sorted) or "(no active dimensions)"
        summary = (
            f"SweepGridConstructor: {len(grid_paths)} grid(s) built from {len(images)} image(s) "
            f"under {os.path.join(output_dir, prefix_folder, '_grids')} | {dim_map}"
        )
        print(f"[SweepGridConstructor] {summary}")
        return (torch.cat(grids, dim=0), summary)


NODE_CLASS_MAPPINGS = {
    "SweepGridConstructor": SweepGridConstructor,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SweepGridConstructor": "Sweep Grid Constructor",
}
