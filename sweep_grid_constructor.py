"""
SweepGridConstructor — builds X/Y/Title grids from an already-sampled
image list, using the same grid code as SweepAllInOne
(sweep_image.build_grids).

Keeping grid building in its own node means tweaking cell_size, cell_mode
or the X/Y/Title picks only reruns THIS node; ComfyUI's caching keeps the
sampling upstream untouched.

images must be a PYLIST (one entry per combo, same order as
combo_records) rather than a single batched IMAGE tensor — feed it from
VAEDecode's IMAGE List output through List-Utils' "List To PyList", since
per-combo images aren't guaranteed to share one resolution the way a
single batch tensor requires.
"""

import os

import folder_paths

from .sweep_core import GRID_AXIS_OPTIONS, safe_component, ui_images
from .sweep_image import GridSpec, build_grids, images_by_combo, stack_padded, unpack_combo


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
                "filename_prefix": (
                    "STRING",
                    {
                        "default": "SweepKit",
                        "tooltip": "Top-level output folder for this node's files (sanitized to one folder name; blank = 'SweepKit'). Files never overwrite earlier runs: a _00001, _00002... counter is added. Grids go in <prefix>/_grids/.",
                    },
                ),
                "cell_size": (
                    "INT",
                    {
                        "default": 512,
                        "min": 64,
                        "max": 4096,
                        "step": 64,
                        "tooltip": "Cell size in pixels: the longer side for fit, both sides for square; ignored by original.",
                    },
                ),
                "cell_mode": (
                    ["fit", "square", "original"],
                    {
                        "default": "fit",
                        "tooltip": "fit: scale to cell_size keeping the aspect ratio (recommended). square: stretch to cell_size x cell_size. original: native resolution (largest grids).",
                    },
                ),
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
                "grid_x_dim": (
                    GRID_AXIS_OPTIONS,
                    {
                        "default": "auto",
                        "tooltip": "Dimension for the columns, by chain position (dim1, dim2, ... as listed in the summary). auto prefers a seed, then any non-text dimension; none = one column.",
                    },
                ),
                "grid_y_dim": (
                    GRID_AXIS_OPTIONS,
                    {
                        "default": "auto",
                        "tooltip": "Dimension for the rows. auto prefers a non-text dimension not used for X; none = one row.",
                    },
                ),
                "grid_title_dim": (
                    GRID_AXIS_OPTIONS,
                    {
                        "default": "auto",
                        "tooltip": "Dimension shown in the title and used as the top folder; each value gets its own grid. auto takes whatever X and Y left over; none = no title dimension. Any remaining dimensions still split into extra grids.",
                    },
                ),
            },
        }

    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("grids", "summary")
    FUNCTION = "build"
    CATEGORY = "SweepKit/Advanced"
    DESCRIPTION = (
        "Builds labelled X/Y grids from the images and their combinations, and saves them to the output folder."
    )
    SEARCH_ALIASES = ["grid constructor", "xy grid", "x/y plot"]
    OUTPUT_NODE = True

    def build(
        self, images, combo, filename_prefix, cell_size, cell_mode, font_size, grid_x_dim, grid_y_dim, grid_title_dim
    ):
        dims_sorted, images, combo_records = unpack_combo(images, combo, "SweepGridConstructor")
        output_dir = folder_paths.get_output_directory()
        # This node saves files itself (not via SaveImage), so the prefix is
        # always one sanitized folder name; '/' can't create stray subfolders.
        prefix_folder = safe_component(filename_prefix) if str(filename_prefix).strip() else "SweepKit"
        spec = GridSpec(
            grid_x_dim=grid_x_dim,
            grid_y_dim=grid_y_dim,
            grid_title_dim=grid_title_dim,
            cell_size=cell_size,
            cell_mode=cell_mode,
            prefix_folder=prefix_folder,
            output_dir=output_dir,
            node_tag="SweepGridConstructor",
            font_size=font_size,
        )
        grids, grid_paths = build_grids(images_by_combo(combo_records, images, dims_sorted), dims_sorted, spec)

        dim_map = "; ".join(f"dim{d['index']}='{d['dim_id']}'" for d in dims_sorted) or "(no active dimensions)"
        summary = (
            f"SweepGridConstructor: {len(grid_paths)} grid(s) built from {len(images)} image(s) "
            f"under {os.path.join(output_dir, prefix_folder, '_grids')} | {dim_map}"
        )
        print(f"[SweepGridConstructor] {summary}")
        return {
            "ui": {"images": ui_images(grid_paths, output_dir), "text": [summary]},
            "result": (stack_padded(grids), summary),
        }


NODE_CLASS_MAPPINGS = {
    "SweepGridConstructor": SweepGridConstructor,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SweepGridConstructor": "Sweep Grid",
}
