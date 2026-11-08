"""
SweepCollect — the end of an ordinary workflow that Sweep Plan drives: it
gathers the image each run produced, saves each one under a name made from
the values used, and builds the labelled grids.

Wire Sweep Plan's axis outputs into whichever settings should change, run
the workflow as usual (ComfyUI runs those nodes once per combination), then
connect the final image and the Plan's `combo` output here. Needs no extra
node packs: ComfyUI hands the images over as a native list.

When the browser runs the sweep one image at a time (the Plan's live_grid switch), this node
runs once per image: it shows the grid so far after each one and writes the final grids and
run list after the last (see sweep_live.py).
"""

import os
from dataclasses import dataclass

import folder_paths

from .sweep_core import (
    GRID_AXIS_OPTIONS,
    build_filenames,
    next_versioned_path,
    safe_component,
    ui_images,
    validate_axis_picks,
    write_manifest,
)
from .sweep_image import (
    GridSpec,
    build_grids,
    images_by_combo,
    pil_to_tensor,
    stack_padded,
    tensor_to_pil,
    unpack_combo,
)
from .sweep_live import LiveSession, finish_session, get_session, kept_sweep, session_key

TAG = "SweepCollect"


def flatten_images(images):
    """One tensor per image: a batch of several images in one entry is split."""
    out = []
    for img in images:
        out.extend(img[i : i + 1] for i in range(img.shape[0]))
    return out


@dataclass
class Settings:
    """The node's settings, unwrapped from the one-element lists INPUT_IS_LIST passes."""

    prefix: str
    folder: str
    save_individuals: bool
    create_grids: bool
    cell_size: int
    cell_mode: str
    font_size: float
    axes: tuple[str, str, str]

    @classmethod
    def from_lists(cls, kw):
        one = {name: value[0] for name, value in kw.items()}
        prefix = one["filename_prefix"]
        return cls(
            prefix=prefix,
            folder=safe_component(prefix) if str(prefix).strip() else "SweepKit",
            save_individuals=one["save_individuals"],
            create_grids=one["create_grids"],
            cell_size=one["cell_size"],
            cell_mode=one["cell_mode"],
            font_size=one["font_size"],
            axes=(one["grid_x_dim"], one["grid_y_dim"], one["grid_title_dim"]),
        )

    def grid_spec(self, output_dir):
        return GridSpec(
            grid_x_dim=self.axes[0],
            grid_y_dim=self.axes[1],
            grid_title_dim=self.axes[2],
            cell_size=self.cell_size,
            cell_mode=self.cell_mode,
            prefix_folder=self.folder,
            output_dir=output_dir,
            node_tag=TAG,
            font_size=self.font_size,
        )


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
                        "tooltip": "Axis for the columns. auto prefers a seed, then any non-text axis; none = one column. The list shows the connected axes by name (their dim_id); older workflows' dim1, dim2... (chain position) still work.",
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
            # Which live sweep this run belongs to, set by the browser (web/sweepkit_live.js).
            # It sits here rather than on Sweep Plan so that the Plan and everything after it
            # keep the same inputs from one sweep to the next, and ComfyUI's cache can reuse
            # every image when only this node's settings change.
            # sweep_reuse: rebuild from a finished live sweep's kept images (the browser
            # sends this when only this node's settings changed; `images` is then a stand-in).
            "hidden": {
                "sweep_session": ("STRING", {"default": ""}),
                "sweep_reuse": ("STRING", {"default": ""}),
                "unique_id": "UNIQUE_ID",
            },
        }

    @classmethod
    def VALIDATE_INPUTS(cls, grid_x_dim, grid_y_dim, grid_title_dim):
        # The pickers list the connected axes' dim_ids, which ComfyUI's fixed-list check doesn't know.
        return validate_axis_picks(grid_x_dim=grid_x_dim, grid_y_dim=grid_y_dim, grid_title_dim=grid_title_dim)

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

    def collect(self, images, combo, sweep_session=None, sweep_reuse=None, unique_id=None, **settings):
        cfg = Settings.from_lists(settings)
        combo = combo[0]
        node_id = (unique_id or [""])[0]
        reuse = (sweep_reuse or [""])[0]
        if reuse:
            return self.collect_kept(combo, cfg, session_key(reuse, node_id))
        if combo.get("live"):
            # Older browser code put the session on the Plan; it now comes with this node.
            session_id = (sweep_session or [""])[0] or combo["live"].get("session", "")
            if not session_id:
                raise ValueError(f"[{TAG}] live run without a session id. Reload the page and queue the sweep again.")
            return self.collect_live(flatten_images(images), combo, cfg, session_key(session_id, node_id))
        dims_sorted, images, records = unpack_combo(flatten_images(images), combo, TAG, hint=self.WIRING_HINT)
        output_dir = folder_paths.get_output_directory()
        saved = self.save_each(images, dims_sorted, records, cfg.prefix, output_dir) if cfg.save_individuals else []
        image_map = images_by_combo(records, images, dims_sorted)
        return self.finish(cfg, dims_sorted, records, image_map, saved, len(images))

    def collect_live(self, images, combo, cfg, session_id):
        """One image of a sweep the browser is running image by image: show the grid
        so far, and after the last image write the grids and run list."""
        live = combo["live"]
        cursor = live["cursor"]
        dims_sorted = sorted([dict(d) for d in combo["dimensions"]], key=lambda d: d["index"])
        records = list(combo["combo_records"])
        if len(images) != 1:
            raise ValueError(
                f"[{TAG}] live run got {len(images)} images, expected 1. {self.WIRING_HINT} "
                f"(Or turn off live_grid on Sweep Plan.)"
            )
        output_dir = folder_paths.get_output_directory()
        session = get_session(
            session_id,
            lambda: LiveSession.start(
                dims_sorted,
                records,
                cfg.grid_spec(output_dir),
                cfg.prefix,
                cfg.create_grids,
                cfg.save_individuals,
            ),
        )
        session.add(cursor, images[0], output_dir)
        if session.done:
            finish_session(session_id)
            return self.finish(cfg, dims_sorted, records, session.images, session.saved_paths(), len(records))
        return self.progress(session, session_id, images[0])

    def collect_kept(self, combo, cfg, key):
        """Rebuild grids and run list from a finished live sweep's kept images, after
        only this node's settings changed. Images already saved under the same
        prefix aren't saved again."""
        kept = kept_sweep(key)
        dims_sorted = sorted([dict(d) for d in combo["dimensions"]], key=lambda d: d["index"])
        records = list(combo["combo_records"])
        if kept is None or kept.count != len(records):
            raise ValueError(
                f"[{TAG}] the images of the previous sweep are no longer in memory (ComfyUI restarted, or newer "
                f"sweeps replaced them). Queue the workflow again to run the whole sweep."
            )
        output_dir = folder_paths.get_output_directory()
        if not cfg.save_individuals:
            saved = []
        elif kept.prefix == cfg.prefix and all(kept.saved):
            saved = kept.saved
        else:
            saved = self.save_each(kept.images, dims_sorted, records, cfg.prefix, output_dir)
        image_map = images_by_combo(records, kept.images, dims_sorted)
        print(f"[{TAG}] rebuilding from the {len(records)} images of the previous sweep (no sampling).")
        return self.finish(cfg, dims_sorted, records, image_map, saved, len(records))

    @staticmethod
    def progress(session, session_id, image):
        """The node's output while a live sweep is part-way: the grid so far, both on
        the node and on its `grids` output (so a Preview Image there fills in too).
        Without a grid (create_grids off, no axes) the output is the latest image."""
        text = f"{TAG}: {len(session.seen)} of {len(session.records)} images"
        shown, frame = session.preview_file(session_id)
        if frame is None:
            frame = tensor_to_pil(image)
        return {
            "ui": {"images": [shown] if shown else [], "text": [text]},
            "result": (pil_to_tensor(frame), text),
        }

    def finish(self, cfg, dims_sorted, records, image_map, saved, count):
        """Build the grids, write the run list and report. `image_map` maps each
        combination's value indices to its image."""
        output_dir = folder_paths.get_output_directory()
        grids, grid_paths = [], []
        if cfg.create_grids and dims_sorted:
            grids, grid_paths = build_grids(image_map, dims_sorted, cfg.grid_spec(output_dir))
        manifest = None
        if saved or grid_paths:
            files = saved or [None] * len(records)
            manifest = write_manifest(os.path.join(output_dir, cfg.folder), dims_sorted, records, files)
        summary = self.summary(
            count, dims_sorted, [p for p in saved if p], grid_paths, output_dir, cfg.folder, manifest
        )
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
    def summary(count, dims_sorted, saved, grid_paths, output_dir, folder, manifest=None):
        lines = [f"{TAG}: {count} image(s) across {len(dims_sorted)} axis(es)."]
        if saved:
            lines.append(f"Saved {len(saved)} image(s) under {os.path.join(output_dir, folder)}")
        if grid_paths:
            lines.append(f"Saved {len(grid_paths)} grid(s) under {os.path.join(output_dir, folder, '_grids')}")
        if manifest:
            lines.append(f"Run list (CSV): {manifest}")
        lines.append("; ".join(f"dim{d['index']}='{d['dim_id']}'" for d in dims_sorted) or "(no axes)")
        return "\n".join(lines)


NODE_CLASS_MAPPINGS = {"SweepCollect": SweepCollect}
NODE_DISPLAY_NAME_MAPPINGS = {"SweepCollect": "Sweep Collect"}
