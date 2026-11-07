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

from .sweep_core import LARGE_SWEEP_WARNING, PREVIEW_VALUES, build_combo_records


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
        }

    RETURN_TYPES = ("SWEEP_COMBO", "INT", "STRING")
    RETURN_NAMES = ("combo", "combo_count", "dim_map")
    FUNCTION = "build"
    CATEGORY = "SweepKit/Modular"

    def build(self, dimensions):
        active_dims = [dict(d) for d in dimensions] if dimensions else []
        combo_records, active_dims_sorted, sorted_groups = build_combo_records(active_dims)
        total = len(combo_records)

        dim_map_lines = []
        print("=" * 60)
        print(
            f"[SweepCombinationExpander] {len(active_dims_sorted)} active dimension(s) "
            f"in {len(sorted_groups)} group(s), {total} combination(s) total"
        )
        for d in active_dims_sorted:
            preview = d["values"][:PREVIEW_VALUES]
            group_note = f" (zipped with group '{d['group']}')" if d.get("group") else ""
            line = (
                f"dim{d['index']}: '{d['dim_id']}' [{d['type']}]{group_note} = {preview}"
                f"{' ...' if len(d['values']) > PREVIEW_VALUES else ''}"
            )
            print(f"   {line}")
            dim_map_lines.append(line)
        if total > LARGE_SWEEP_WARNING:
            print(
                f"[SweepCombinationExpander] WARNING: {total} combinations is a lot — "
                f"double check this is intended before it reaches your sampler."
            )
        print("=" * 60)

        combo = {"dimensions": active_dims_sorted, "combo_records": combo_records}
        dim_map = "\n".join(dim_map_lines) if dim_map_lines else "(no active dimensions)"
        return (combo, total, dim_map)


NODE_CLASS_MAPPINGS = {
    "SweepCombinationExpander": SweepCombinationExpander,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SweepCombinationExpander": "Sweep Combination Expander",
}
