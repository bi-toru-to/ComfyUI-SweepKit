"""
SweepCollect — the end of an ordinary workflow that Sweep Plan drives: it
gathers the image each run produced, saves each one under a name made from
the values used, and builds the labelled grids.

Wire Sweep Plan's axis outputs into whichever settings should change, run
the workflow as usual (ComfyUI runs those nodes once per combination), then
connect the final image and the Plan's `combo` output here. Needs no extra
node packs: ComfyUI hands the images over as a native list.
"""

import os

import folder_paths

from .sweep_core import GRID_AXIS_OPTIONS, build_filenames, next_versioned_path, safe_component, ui_images
from .sweep_image import GridSpec, build_grids, images_by_combo, stack_padded, tensor_to_pil, unpack_combo

TAG = "SweepCollect"


def flatten_images(images):
    """One tensor per image: a batch of several images in one entry is split."""
    out = []
    for img in images:
        out.extend(img[i : i + 1] for i in range(img.shape[0]))
    return out


class SweepCollect:
    # ComfyUI hands every input over as a list (images arrive one per run);
    # collect() unwraps the single-value inputs.
    INPUT_IS_LIST = True

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": (
                    "IMAGE",
                    {"tooltip": "The final image of your workflow, one per run (batch_size 1)."},
                ),
                "combo": (
                    "SWEEP_COMBO",
                    {"tooltip": "Connect Sweep Plan's 'combo' output: it says which values made each image."},
                ),
                "filename_prefix": (
                    "STRING",
                    {
                        "default": "SweepKit",
                        "tooltip": (
                            "Output folder for this node's files (one folder name; blank = 'SweepKit'). Files never "
                            "overwrite earlier runs: a _00001, _00002... counter is added. Grids go in <prefix>/_grids/."
                        ),
                    },
                ),
                "save_individuals": (
                    "BOOLEAN",
                    {
                        "default": True,
                        "tooltip": "Save every image under a name made from the values used. Turn off if a Save Image node does that.",
                    },
                ),
                "create_grids": (
                    "BOOLEAN",
                    {"default": True, "tooltip": "Build labelled X/Y grids (one per extra axis value)."},
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
                        "tooltip": "Label size as a fraction of the cell width; 1.0 is about 16 characters per cell.",
                    },
                ),
                "grid_x_dim": (
                    GRID_AXIS_OPTIONS,
                    {
                        "default": "auto",
                        "tooltip": "Axis for the columns, by chain position (dim1, dim2, ...). auto prefers a seed, then any non-text axis; none = one column.",
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
                        "tooltip": "Axis shown in the title; each value gets its own grid. auto takes what X and Y left over; none = no title axis. Any remaining axes still split into extra grids.",
                    },
                ),
            },
        }

    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("grids", "summary")
    FUNCTION = "collect"
    OUTPUT_NODE = True
    CATEGORY = "SweepKit"
    DESCRIPTION = (
        "Gathers the image from every run of a sweep, saves each one named after the values used, and builds "
        "labelled grids. Connect your workflow's final image and Sweep Plan's combo output."
    )
    SEARCH_ALIASES = ["sweep collect", "collect results", "xy plot", "x/y grid", "sweep output"]

    def collect(
        self,
        images,
        combo,
        filename_prefix,
        save_individuals,
        create_grids,
        cell_size,
        cell_mode,
        font_size,
        grid_x_dim,
        grid_y_dim,
        grid_title_dim,
    ):
        dims_sorted, images, records = unpack_combo(flatten_images(images), combo[0], TAG, hint=self.WIRING_HINT)
        output_dir = folder_paths.get_output_directory()
        prefix = filename_prefix[0]
        folder = safe_component(prefix) if str(prefix).strip() else "SweepKit"

        saved = self.save_each(images, dims_sorted, records, prefix, output_dir) if save_individuals[0] else []
        grids, grid_paths = [], []
        if create_grids[0] and dims_sorted:
            spec = GridSpec(
                grid_x_dim=grid_x_dim[0],
                grid_y_dim=grid_y_dim[0],
                grid_title_dim=grid_title_dim[0],
                cell_size=cell_size[0],
                cell_mode=cell_mode[0],
                prefix_folder=folder,
                output_dir=output_dir,
                node_tag=TAG,
                font_size=font_size[0],
            )
            grids, grid_paths = build_grids(images_by_combo(records, images, dims_sorted), dims_sorted, spec)

        summary = self.summary(len(images), dims_sorted, saved, grid_paths, output_dir, folder)
        print(f"[{TAG}] {summary}")
        return {
            "ui": {"images": ui_images(grid_paths, output_dir), "text": [summary]},
            "result": (stack_padded(grids), summary),
        }

    WIRING_HINT = (
        "Connect Sweep Plan's axis outputs to the settings that should change, the final image to this node, "
        "and keep batch_size at 1 so each run makes one image."
    )

    @staticmethod
    def save_each(images, dims_sorted, records, prefix, output_dir):
        """Save every image as <prefix>/<folders>/<number>_<values>_NNNNN.png."""
        saved = []
        for rel, image in zip(build_filenames(dims_sorted, records, prefix, True), images, strict=True):
            directory, name = os.path.split(os.path.join(output_dir, rel))
            path = next_versioned_path(directory, name)
            tensor_to_pil(image).save(path)
            saved.append(path)
        return saved

    @staticmethod
    def summary(count, dims_sorted, saved, grid_paths, output_dir, folder):
        lines = [f"{TAG}: {count} image(s) across {len(dims_sorted)} axis(es)."]
        if saved:
            lines.append(f"Saved {len(saved)} image(s) under {os.path.join(output_dir, folder)}")
        if grid_paths:
            lines.append(f"Saved {len(grid_paths)} grid(s) under {os.path.join(output_dir, folder, '_grids')}")
        lines.append("; ".join(f"dim{d['index']}='{d['dim_id']}'" for d in dims_sorted) or "(no axes)")
        return "\n".join(lines)


NODE_CLASS_MAPPINGS = {"SweepCollect": SweepCollect}
NODE_DISPLAY_NAME_MAPPINGS = {"SweepCollect": "Sweep Collect"}
