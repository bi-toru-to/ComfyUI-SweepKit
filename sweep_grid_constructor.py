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

from .sweep_core import GRID_AXIS_OPTIONS, safe_component, ui_images, validate_axis_picks
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
                "filename_prefix": (
                    "STRING",
                    {
                        "default": "SweepKit",
                        "tooltip": (
                            "Folder (inside ComfyUI's output folder) for the grids. Leave blank for SweepKit. Files never replace earlier ones: a number like _00001 is added; grids go in _grids."
                        ),
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
                            "Label size compared with the cell width: 1.0 fits about 16 characters across a cell. Titles stay larger than labels."
                        ),
                    },
                ),
                "grid_x_dim": (
                    GRID_AXIS_OPTIONS,
                    {
                        "default": "auto",
                        "tooltip": (
                            "Axis for the grid's columns. auto prefers a seed, then any number axis; none makes one column. The list shows your axes by their names (dim_id)."
                        ),
                    },
                ),
                "grid_y_dim": (
                    GRID_AXIS_OPTIONS,
                    {
                        "default": "auto",
                        "tooltip": "Axis for the rows. auto prefers a non-text axis not used for X; none = one row.",
                    },
                ),
                "grid_title_dim": (
                    GRID_AXIS_OPTIONS,
                    {
                        "default": "auto",
                        "tooltip": "Axis shown in the title and used as the top folder; each value gets its own grid. auto takes whatever X and Y left over; none = no title axis. Any remaining axes still split into extra grids.",
                    },
                ),
            },
        }

    @classmethod
    def VALIDATE_INPUTS(cls, grid_x_dim, grid_y_dim, grid_title_dim):
        # The pickers list the connected axes' dim_ids, which ComfyUI's fixed-list check doesn't know.
        return validate_axis_picks(grid_x_dim=grid_x_dim, grid_y_dim=grid_y_dim, grid_title_dim=grid_title_dim)

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
        dims_sorted, images, combo_records = unpack_combo(images, combo, "Sweep Grid")
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
            node_tag="Sweep Grid",
            font_size=font_size,
        )
        grids, grid_paths = build_grids(images_by_combo(combo_records, images, dims_sorted), dims_sorted, spec)

        dim_map = "; ".join(f"dim{d['index']}='{d['dim_id']}'" for d in dims_sorted) or "(no active axes)"
        summary = (
            f"Sweep Grid: {len(grid_paths)} grid(s) built from {len(images)} image(s) "
            f"under {os.path.join(output_dir, prefix_folder, '_grids')} | {dim_map}"
        )
        print(f"[Sweep Grid] {summary}")
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
