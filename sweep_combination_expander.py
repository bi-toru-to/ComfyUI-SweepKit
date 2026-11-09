"""
SweepCombinationExpander — turns a chain of SweepDimension nodes into a
flattened combo list, without sampling anything itself.

This is the spine of the modular pipeline: every other new node
(SweepDimensionExtract, SweepDedupeCombos, SweepFilenameSequencer,
SweepGridConstructor, SweepUpsetConstructor) takes its `combo` output —
dimensions and combo_records bundled into one socket, since every
consumer needs both together and never one without the other; splitting
them was pure wiring clutter and one extra way to mismatch a graph (e.g.
connecting combo_records from a different SweepCombinationExpander
instance than dimensions).

Deliberately does NOT emit hardcoded per-axis outputs (seeds/steps/cfgs/
...) — that would need a fixed output for every dimension dim_id anyone
might ever use, including ones this node pack doesn't know about (e.g. a
custom lora_model_strength dim_id). Use SweepDimensionExtract once per
axis you actually need instead — one generic mechanism, works for any
dim_id including future ones.
"""

from .sweep_core import (
    LARGE_SWEEP_WARNING,
    MAX_AXIS_OUTPUTS,
    PREVIEW_VALUES,
    axis_output_lists,
    build_combo_records,
    live_slice,
)


class SweepCombinationExpander:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "dimensions": (
                    "SWEEP_DIMS",
                    {
                        "tooltip": "Connect the end of a chain of SweepDimension (and optionally SweepDimensionZip / SweepDimensionSelfCombine) nodes.",
                    },
                ),
            },
            "optional": {
                "live_grid": (
                    "BOOLEAN",
                    {
                        "default": True,
                        "tooltip": (
                            "Run in the browser one combination at a time, so the grid fills in on Sweep Collect as "
                            "images finish. Turn off to run everything in one go. (Running from a script or the API "
                            "always runs everything in one go.)"
                        ),
                    },
                ),
            },
            # Filled in by the browser while it runs a live grid (see web/sweepkit_live.js): which
            # combination this run is. The sweep's id goes to Sweep Collect instead, so a rerun with
            # the same axes gives the Plan the same inputs and ComfyUI can reuse its cached results.
            # sweep_session stays accepted (and ignored) for browser code from before that change.
            "hidden": {"sweep_cursor": ("INT", {"default": -1}), "sweep_session": ("STRING", {"default": ""})},
        }

    # Slots 0-2 are the original outputs (saved workflows link to them by
    # position). The per-axis list outputs come after, one per axis in chain
    # order; the frontend hides the ones a chain doesn't use.
    RETURN_TYPES = ("SWEEP_COMBO", "INT", "STRING") + ("*",) * MAX_AXIS_OUTPUTS
    RETURN_NAMES = ("combo", "combo_count", "dim_map") + tuple(f"axis_{i}" for i in range(1, MAX_AXIS_OUTPUTS + 1))
    OUTPUT_IS_LIST = (False, False, False) + (True,) * MAX_AXIS_OUTPUTS
    OUTPUT_TOOLTIPS = (
        "Every combination, for Sweep Collect and the other Advanced nodes.",
        "How many images the sweep will make.",
        "One line per axis: its name, type and first values.",
    ) + tuple(
        f"The value of axis {i} for each image, in order. Connect it to a setting (seed, cfg, prompt text, a "
        "model or LoRA name...) and that node runs once per image."
        for i in range(1, MAX_AXIS_OUTPUTS + 1)
    )
    FUNCTION = "build"
    DESCRIPTION = (
        "Plans the sweep: turns the chained axes into every combination. Each axis comes out as a list you can "
        "connect to any setting (seed, cfg, prompt text, model or LoRA name...), so that node runs once per image."
    )
    SEARCH_ALIASES = ["sweep expander", "combination expander", "sweep plan"]
    CATEGORY = "SweepKit"

    def build(self, dimensions, live_grid=True, sweep_cursor=-1, sweep_session=""):
        active_dims = [dict(d) for d in dimensions] if dimensions else []
        combo_records, active_dims_sorted, sorted_groups = build_combo_records(active_dims)
        total = len(combo_records)
        live = sweep_cursor >= 0  # the browser is running the sweep one image at a time
        if live and sweep_cursor >= total:
            raise ValueError(
                f"[Sweep Plan] live run {sweep_cursor + 1} of a {total}-image sweep: the axes changed "
                f"while it was running. Queue the sweep again."
            )

        dim_map_lines = self.describe(active_dims_sorted)
        if sweep_cursor <= 0:  # a live sweep builds the plan once per image; say it once
            self.announce(dim_map_lines, len(active_dims_sorted), len(sorted_groups), total)

        combo = {"dimensions": active_dims_sorted, "combo_records": combo_records}
        axis_lists = axis_output_lists(active_dims_sorted, combo_records)
        if live:
            combo["live"] = {"cursor": sweep_cursor}
            if sweep_session:  # browser code from before the session moved to Sweep Collect
                combo["live"]["session"] = str(sweep_session)
            axis_lists = live_slice(axis_lists, sweep_cursor)
        dim_map = "\n".join(dim_map_lines) if dim_map_lines else "(no active axes)"
        return (combo, total, dim_map, *axis_lists)

    @staticmethod
    def describe(dims_sorted):
        """One line per axis: its position, name, type and first values."""
        lines = []
        for d in dims_sorted:
            preview = d["values"][:PREVIEW_VALUES]
            group_note = f" (zipped with group '{d['group']}')" if d.get("group") else ""
            more = " ..." if len(d["values"]) > PREVIEW_VALUES else ""
            lines.append(f"dim{d['index']}: '{d['dim_id']}' [{d['type']}]{group_note} = {preview}{more}")
        return lines

    @staticmethod
    def announce(lines, n_axes, n_groups, total):
        print("=" * 60)
        print(f"[Sweep Plan] {n_axes} active axis(es) in {n_groups} group(s), {total} combination(s) total")
        for line in lines:
            print(f"   {line}")
        if total > LARGE_SWEEP_WARNING:
            print(
                f"[Sweep Plan] WARNING: {total} combinations is a lot — "
                f"double check this is intended before it reaches your sampler."
            )
        print("=" * 60)


NODE_CLASS_MAPPINGS = {
    "SweepCombinationExpander": SweepCombinationExpander,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SweepCombinationExpander": "Sweep Plan",
}
