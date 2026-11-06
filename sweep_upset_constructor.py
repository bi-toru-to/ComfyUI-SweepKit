"""
SweepUpsetConstructor — visualizes one SweepDimensionSelfCombine axis as
an UpSet-style matrix: one column per generated combo (sorted by arity,
then generation order — the order self_combine already produces, no extra
sort needed), the actual image as that column's swatch, and a dot-matrix
below marking which base elements the combo contains, with a connecting
line joining them.

Deliberately narrower in scope than SweepGridConstructor: it visualizes
exactly ONE self-combine dimension's own structure. Any OTHER independent
dimension in the graph (e.g. sweeping cfg alongside artist combos) is
handled the same way SweepGridConstructor handles leftover axes — as a
page split, producing one matrix per combination of the other axes,
never crammed into the same matrix. A large column count on top of that
paginates further via max_columns_per_page, purely as a safety valve —
the practical ceiling is much higher than it looks in a mockup, since
this is a saved file to scroll/zoom in an image viewer, not a fixed
viewport.
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
    resolve_group_index,
    dim_group_members,
    format_group_value,
    find_dim_by_id,
    find_font,
    font_size_for_char_width,
    wrap_text_to_width,
    truncate_text_to_width,
    next_versioned_path,
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
                        "tooltip": "One image tensor per combo, same order as combo.combo_records — connect via List-Utils' 'List To PyList'.",
                    },
                ),
                "combo": (
                    "SWEEP_COMBO",
                    {
                        "tooltip": "Connect SweepCombinationExpander's 'combo' output.",
                    },
                ),
                "dim_id": (
                    "STRING",
                    {
                        "default": "",
                        "tooltip": "dim_id of the SweepDimensionSelfCombine-produced dimension to visualize.",
                    },
                ),
                "filename_prefix": ("STRING", {"default": "SweepKit"}),
                "cell_size": (
                    "INT",
                    {
                        "default": 120,
                        "min": 32,
                        "max": 1024,
                        "step": 8,
                        "tooltip": "Target swatch size per column — exact meaning depends on cell_mode.",
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
                            "Text size as a fraction of the ACTUAL rendered swatch width (not the "
                            "cell_size widget) — 1.0 means one character is about 1/16 of a swatch's "
                            "width. Sized off the real swatch width specifically so cell_mode='original' "
                            "(whose actual size can differ a lot from cell_size) doesn't end up with "
                            "text that's disproportionately tiny or huge next to the images. Title, "
                            "row-label, and column-label sizes stay proportionally distinct at every "
                            "setting."
                        ),
                    },
                ),
                "title_dim": (
                    GRID_AXIS_OPTIONS,
                    {
                        "default": "none",
                        "tooltip": "Which OTHER (non-target) dimension's value leads the matrix title, if any. Every other non-target dimension still page-splits normally regardless of this setting — it only reorders which one reads first.",
                    },
                ),
                "max_columns_per_page": (
                    "INT",
                    {
                        "default": 60,
                        "min": 5,
                        "max": 500,
                        "tooltip": "Safety valve for very large combo counts — splits into multiple numbered matrix files past this many columns.",
                    },
                ),
            },
        }

    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("matrices", "summary")
    FUNCTION = "build"
    CATEGORY = "SweepKit/Modular"
    OUTPUT_NODE = True

    # ---- tensor/PIL helpers (cell sizing/pasting ported verbatim from
    # SweepGridConstructor, so cell_mode behaves identically in both) ----

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

    def _paste_into_cell(self, canvas, pil_img, x, y, cell_w, cell_h, cell_mode):
        if cell_mode == "square":
            resized = pil_img.resize((cell_w, cell_h), Image.LANCZOS)
            canvas.paste(resized, (x, y))
            return
        iw, ih = pil_img.size
        scale = min(cell_w / iw, cell_h / ih)
        new_w, new_h = max(1, round(iw * scale)), max(1, round(ih * scale))
        resized = pil_img.resize((new_w, new_h), Image.LANCZOS)
        canvas.paste(resized, (x + (cell_w - new_w) // 2, y + (cell_h - new_h) // 2))

    # ---- matrix drawing ----

    def draw_matrix(self, col_images, base_values, col_values, col_meta, title, cell_size, cell_mode, font_size):
        n_rows = len(base_values)
        n_cols = len(col_images)

        cell_w, cell_h = self._cell_dims(col_images, cell_size, cell_mode)

        # Sized off the ACTUAL rendered swatch width, not the nominal
        # cell_size widget -- cell_mode='original' can make real cell_w
        # diverge a lot from cell_size, which is exactly why fixed pixel
        # font sizes used to look disproportionately tiny (many/large
        # source images) or huge (few/small ones) depending on content
        # rather than the font_size setting. Each tier stays a fixed
        # multiple of the base size, so title/row/column labels stay
        # visually distinct from each other at every font_size value, not
        # just at the default -- kept modest (title/row/group all fairly
        # close to the column-label base) so the hierarchy reads as
        # "slightly emphasized," not "wildly oversized," at high
        # font_size values.
        base_px = font_size_for_char_width(cell_w / 16.0 * font_size)
        font_title = find_font(round(base_px * 1.6))
        font_group = find_font(round(base_px * 1.15))
        font_row = find_font(round(base_px * 1.1))
        font_col = find_font(base_px)

        scratch = ImageDraw.Draw(Image.new("RGB", (1, 1)))

        def _line_h(font):
            b = scratch.textbbox((0, 0), "Ag0jJ", font=font)
            return max(1, b[3] - b[1])

        title_line_h = _line_h(font_title)
        group_line_h = _line_h(font_group)
        row_line_h = _line_h(font_row)
        col_line_h = _line_h(font_col)

        # Every gap below is measured off the actual font metrics at the
        # current font_size, not a fixed pixel constant -- a fixed layout
        # (title band, row-to-row spacing, etc.) only ever worked because
        # the old font sizes were themselves fixed and small. Scale the
        # font up (either via font_size or a large real cell_w under
        # cell_mode='original') and a fixed-height band starts clipping
        # or colliding with its own text; deriving every band from the
        # font it actually holds keeps that from happening at any size.
        pad = max(20, round(base_px * 0.6))
        title_h = title_line_h + max(16, round(base_px * 0.5))
        group_header_h = group_line_h + max(8, round(base_px * 0.3))
        col_w = cell_w + max(10, round(base_px * 0.3))
        dot_r = max(4, round(base_px * 0.35))
        # Row labels are drawn with anchor='lm' (vertically CENTERED on
        # their y-coordinate), not top-anchored like the title/group/
        # column labels -- so they extend roughly row_line_h/2 both above
        # AND below their anchor point. dot_gap (row-to-row) already
        # accounted for that between rows; gap_after_swatch (image-to-
        # first-row) and gap_after_dots (last-row-to-column-labels) used
        # to be small fixed constants that didn't, so at a large enough
        # font_row the first row's own label text poked up into the
        # image above it (and the last row's could reach down into the
        # column labels below it) despite the row spacing itself being
        # fine. Both now reserve at least half a row-label line height.
        row_half_extent = max(round(row_line_h * 0.6), dot_r + 4)
        gap_after_swatch = max(row_half_extent, round(base_px * 0.3), 10)
        dot_gap = max(row_line_h + max(10, round(base_px * 0.3)), round(base_px * 1.6))
        gap_after_dots = max(row_half_extent, round(base_px * 0.3), 8)

        y_group = title_h
        y_swatch = y_group + group_header_h
        y_dots0 = y_swatch + cell_h + gap_after_swatch
        y_last_dot = y_dots0 + max(0, n_rows - 1) * dot_gap
        y_col_label = y_last_dot + gap_after_dots + max(8, round(base_px * 0.3))

        # Row-label reserved width is sized to the LONGEST actual label,
        # not a fixed guess -- a fixed budget either wastes space (short
        # labels) or truncates real ones far too early (long labels, e.g.
        # "@yamamoto souichirou"), regardless of how much page width is
        # genuinely available. Capped at 1.5x a cell's width so one
        # pathologically long label can't blow up the whole layout; text
        # still gets an ellipsis in that case, just from a much more
        # generous budget than before.
        row_label_left_x = max(12, round(base_px * 0.3))
        row_label_right_gap = max(8, round(base_px * 0.3))
        measured_label_w = max((scratch.textbbox((0, 0), str(v), font=font_row)[2] for v in base_values), default=0)
        row_label_cap = round(cell_w * 1.5)
        row_label_w = max(60, row_label_left_x + min(measured_label_w, row_label_cap) + row_label_right_gap)

        # Column labels wrap onto multiple horizontal lines instead of
        # rotating 90 degrees: combo text ("cyberpunk, noir, pastel")
        # routinely runs wider than one column, and a single horizontal
        # line collided into neighbors, but horizontal + word-wrapped
        # reads more naturally than rotated text once it's constrained to
        # each column's own width. Max width matches the swatch's own
        # width plus a little padding, not the wider inter-column pitch,
        # so a wrapped label doesn't visually bleed into its neighbor
        # either.
        label_max_w = cell_w + 12
        wrapped = [wrap_text_to_width(col_values[j], font_col, label_max_w, scratch) for j in range(n_cols)]
        line_h = col_line_h + 3
        max_lines = max((len(w) for w in wrapped), default=1)
        label_block_h = max_lines * line_h

        W = row_label_w + n_cols * col_w + pad
        H = y_col_label + label_block_h + pad
        grid = Image.new("RGB", (W, H), (16, 16, 16))
        draw = ImageDraw.Draw(grid)

        draw.text(
            (W // 2, max(8, round(base_px * 0.2))), str(title), fill=(255, 255, 255), font=font_title, anchor="mt"
        )

        # Arity group headers + dividers -- contiguous runs of equal arity.
        runs, start = [], 0
        for j in range(1, n_cols + 1):
            if j == n_cols or col_meta[j]["arity"] != col_meta[start]["arity"]:
                runs.append((start, j, col_meta[start]["arity"]))
                start = j
        for run_start, run_end, arity in runs:
            cx = row_label_w + (run_start + run_end) / 2 * col_w
            draw.text(
                (cx, y_group),
                f"Arity {arity} ({run_end - run_start})",
                fill=(160, 160, 160),
                font=font_group,
                anchor="mt",
            )
            if run_start > 0:
                bx = row_label_w + run_start * col_w
                draw.line([(bx, y_group - 4), (bx, H - pad // 2)], fill=(70, 70, 70), width=1)

        # Per-row horizontal guide lines, drawn full-width and BEHIND
        # everything else, so a wide matrix stays easy to trace by eye
        # from a row label all the way across to whichever column you're
        # comparing, without losing track of which row you're on.
        for i in range(n_rows):
            y = y_dots0 + i * dot_gap
            draw.line([(0, y), (W, y)], fill=(40, 40, 40), width=1)

        # Row labels -- left-aligned, sized to the actual longest label
        # (see row_label_w above) rather than a small fixed budget, so
        # most realistic labels show in full. Only a label that would
        # still exceed the capped budget gets an ellipsis, measured in
        # real pixels (so it adapts correctly to font_size), not an
        # arbitrary character count.
        row_label_max_w = max(10, row_label_w - row_label_left_x - row_label_right_gap)
        for i, base_val in enumerate(base_values):
            y = y_dots0 + i * dot_gap
            txt = truncate_text_to_width(base_val, font_row, row_label_max_w, scratch)
            draw.text((row_label_left_x, y), txt, fill=(210, 210, 210), font=font_row, anchor="lm")

        # Swatches + dot matrix + connecting lines + column labels
        for j in range(n_cols):
            cx = row_label_w + j * col_w + col_w // 2
            sx = row_label_w + j * col_w + (col_w - cell_w) // 2

            img = col_images[j]
            if img is not None:
                self._paste_into_cell(grid, self.tensor_to_pil(img), sx, y_swatch, cell_w, cell_h, cell_mode)
            else:
                box = [sx, y_swatch, sx + cell_w, y_swatch + cell_h]
                draw.rectangle(box, outline=(90, 30, 30), width=2)
                draw.text(
                    ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2),
                    "missing",
                    fill=(200, 120, 120),
                    font=font_col,
                    anchor="mm",
                )

            members = set(col_meta[j]["members"])
            if len(members) >= 2:
                ys = [y_dots0 + i * dot_gap for i in members]
                draw.line([(cx, min(ys)), (cx, max(ys))], fill=(29, 158, 117), width=2)
            for i in range(n_rows):
                y = y_dots0 + i * dot_gap
                if i in members:
                    draw.ellipse([cx - dot_r, y - dot_r, cx + dot_r, y + dot_r], fill=(29, 158, 117))
                else:
                    unfilled_r = max(2, round(dot_r * 0.5))
                    draw.ellipse([cx - unfilled_r, y - unfilled_r, cx + unfilled_r, y + unfilled_r], fill=(70, 70, 70))

            for li, line in enumerate(wrapped[j]):
                draw.text((cx, y_col_label + li * line_h), line, fill=(180, 180, 180), font=font_col, anchor="mt")

        return grid

    # ---- main ----

    def build(
        self, images, combo, dim_id, filename_prefix, cell_size, cell_mode, font_size, title_dim, max_columns_per_page
    ):
        dimensions, combo_records = combo["dimensions"], combo["combo_records"]
        output_dir = folder_paths.get_output_directory()
        # Sanitized to a single safe path component -- see the identical
        # note in SweepGridConstructor.build(); this node also saves files
        # itself rather than going through SaveImage's own filename_prefix
        # parser, so it needs its own folder unconditionally.
        prefix_folder = safe_component(filename_prefix) if str(filename_prefix).strip() else "SweepKit"
        active_dims_sorted = sorted([dict(d) for d in dimensions], key=lambda d: d["index"]) if dimensions else []
        images = list(images)
        combo_records = list(combo_records)

        if len(images) != len(combo_records):
            raise ValueError(
                f"[SweepUpsetConstructor] images has {len(images)} entries but combo has "
                f"{len(combo_records)} combo_records — they must be the same length and in "
                f"the same order."
            )

        try:
            target = find_dim_by_id(active_dims_sorted, dim_id)
        except ValueError as e:
            raise ValueError(f"[SweepUpsetConstructor] {e}")
        if "combo_meta" not in target:
            raise ValueError(
                f"[SweepUpsetConstructor] '{dim_id}' has no combo_meta — it wasn't produced "
                f"by SweepDimensionSelfCombine. Route that dimension through SweepDimensionSelfCombine first."
            )

        base_values = target["base_values"]
        combo_meta = target["combo_meta"]
        n_cols_total = len(target["values"])

        all_images = {}
        for rec, img in zip(combo_records, images):
            key = tuple(rec["idx_by_dim"][d["index"]] for d in active_dims_sorted)
            all_images[key] = img

        # Group-aware, matching resolve_grid_axes' own other_dims logic: if
        # two OTHER (non-target) dimensions are zipped together, only ONE
        # representative goes into other_dims, or itertools.product below
        # would treat a correlated pair as independent and generate a page
        # for every (a, b) combination instead of just their paired ones.
        other_dims = []
        seen_other_groups = set()
        for d in active_dims_sorted:
            if d["index"] == target["index"]:
                continue
            gid = d.get("group")
            if gid:
                if gid in seen_other_groups:
                    continue
                seen_other_groups.add(gid)
            other_dims.append(d)

        # title_dim: pick which OTHER dimension's value leads the title,
        # if any -- doesn't change page count/membership, just ordering.
        if title_dim != "none":
            by_token = {f"dim{d['index']}": d for d in active_dims_sorted}
            picked = by_token.get(title_dim)
            if picked is None:
                print(f"[SweepUpsetConstructor] title_dim '{title_dim}' doesn't match any active dimension — ignoring.")
            elif picked["index"] == target["index"]:
                print(
                    f"[SweepUpsetConstructor] title_dim '{title_dim}' is the self-combine target dimension itself — ignoring (it already drives the matrix's columns)."
                )
            else:
                rep = next(
                    (
                        d
                        for d in other_dims
                        if d["index"] == picked["index"]
                        or (picked.get("group") and d.get("group") == picked.get("group"))
                    ),
                    None,
                )
                if rep is not None:
                    other_dims = [rep] + [d for d in other_dims if d is not rep]

        other_ranges = [range(len(d["values"])) for d in other_dims]

        matrices, paths = [], []

        for other_combo in itertools.product(*other_ranges) if other_dims else [()]:
            other_idx = {d["index"]: vi for d, vi in zip(other_dims, other_combo)}

            col_images = []
            for j in range(n_cols_total):
                full_idx = dict(other_idx)
                full_idx[target["index"]] = j
                key = tuple(resolve_group_index(d, full_idx, active_dims_sorted) for d in active_dims_sorted)
                col_images.append(all_images.get(key))

            title_bits, folder_parts = [], []
            for d, vi in zip(other_dims, other_combo):
                members = dim_group_members(d, active_dims_sorted)
                disp = format_group_value(members, vi)
                title_bits.append(f"{d.get('group_label', d['dim_id'])}: {disp}")
                folder_parts.append(safe_component(disp))
            base_title = " | ".join(title_bits) if title_bits else prefix_folder

            n_pages = max(1, (n_cols_total + max_columns_per_page - 1) // max_columns_per_page)
            for page in range(n_pages):
                lo = page * max_columns_per_page
                hi = min(lo + max_columns_per_page, n_cols_total)
                title_text = base_title if n_pages == 1 else f"{base_title} (page {page + 1}/{n_pages})"

                matrix_pil = self.draw_matrix(
                    col_images[lo:hi],
                    base_values,
                    target["values"][lo:hi],
                    combo_meta[lo:hi],
                    title_text,
                    cell_size,
                    cell_mode,
                    font_size,
                )

                mat_dir = (
                    os.path.join(output_dir, prefix_folder, "_upset", *folder_parts[:-1])
                    if len(folder_parts) > 1
                    else os.path.join(output_dir, prefix_folder, "_upset")
                )
                # tail (and suffix) are used as a bare filename base here,
                # never a path -- see the identical note in
                # SweepGridConstructor about why filename_prefix must stay
                # out of this string. next_versioned_path appends a
                # 5-digit auto-incrementing counter (matching stock
                # SaveImage's own convention) so rerunning this node never
                # silently overwrites a previous matrix -- direct PIL
                # save() calls have no such protection unless given one
                # explicitly, unlike SaveImage.
                tail = folder_parts[-1] if folder_parts else "matrix"
                suffix = "" if n_pages == 1 else f"_page{page + 1}"
                path = next_versioned_path(mat_dir, f"{tail}{suffix}")
                matrix_pil.save(path)
                paths.append(path)
                matrices.append(self.pil_to_tensor(matrix_pil))

        if not matrices:
            matrices = [torch.zeros(1, 512, 512, 3)]

        if len(matrices) > 1:
            target_shape = matrices[0].shape
            fixed = []
            for m in matrices:
                if m.shape != target_shape:
                    pil = self.tensor_to_pil(m[0]).resize((target_shape[2], target_shape[1]), Image.LANCZOS)
                    m = self.pil_to_tensor(pil)
                fixed.append(m)
            matrices = fixed

        dim_map = "; ".join(f"dim{d['index']}='{d['dim_id']}'" for d in active_dims_sorted) or "(no active dimensions)"
        summary = (
            f"SweepUpsetConstructor: {len(paths)} matrix image(s) for '{dim_id}' "
            f"({n_cols_total} combo(s) of {len(base_values)} base value(s)) "
            f"under {os.path.join(output_dir, prefix_folder, '_upset')} | {dim_map}"
        )
        print(f"[SweepUpsetConstructor] {summary}")
        return (torch.cat(matrices, dim=0), summary)


NODE_CLASS_MAPPINGS = {
    "SweepUpsetConstructor": SweepUpsetConstructor,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SweepUpsetConstructor": "Sweep Upset Constructor",
}
