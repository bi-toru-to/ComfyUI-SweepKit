"""
SweepDimensionSelfCombine — recombine ONE dimension's own values against
themselves, at every size from min_size to max_size (not just one fixed
r) — e.g. 4 styles at sizes 1-3 becomes a 14-value derived
dimension: 4 singles, 6 pairs, 4 triples.

Operates on the LAST dimension in the incoming chain (same convention as
SweepDimensionZip taking each input's tail) and REPLACES it in place —
this transforms one axis into a derived one, it doesn't add a new axis.

The derived dimension carries two extra fields the plain cartesian path
never needs: 'combo_meta' (per-value {"arity", "members"} — which of the
ORIGINAL base values each derived value is built from) and 'base_values'
(the original list itself, for row labels). SweepUpsetConstructor reads
both to build the membership dot-matrix; nothing else needs them and
they're otherwise inert extra dict keys.
"""

from .sweep_core import self_combine


class SweepDimensionSelfCombine:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "dimensions": (
                    "SWEEP_DIMS",
                    {
                        "tooltip": "A chain of SweepDimension nodes — the LAST axis in this chain is the one that gets recombined against itself.",
                    },
                ),
                "mode": (
                    ["combinations", "permutations"],
                    {
                        "default": "combinations",
                        "tooltip": (
                            "combinations: order doesn't matter, no repeats within a combo "
                            "('cyberpunk, noir' only, not also 'noir, cyberpunk'). "
                            "permutations: order matters too — use this if word order actually "
                            "changes your output (it often does for prompts), at the cost of a "
                            "much faster-growing result count."
                        ),
                    },
                ),
                "min_size": (
                    "INT",
                    {
                        "default": 1,
                        "min": 1,
                        "max": 20,
                        "tooltip": "Smallest combo size to include (1 = also emit every base value on its own).",
                    },
                ),
                "max_size": (
                    "INT",
                    {
                        "default": 0,
                        "min": 0,
                        "max": 20,
                        "tooltip": "Largest combo size to include. 0 = use every base value (the full-size combo). Settings producing more than 10,000 derived values are refused with a hint.",
                    },
                ),
                "joiner": (
                    "STRING",
                    {"default": ", ", "tooltip": "String used to join a combo's member values into one derived value."},
                ),
            },
        }

    RETURN_TYPES = ("SWEEP_DIMS",)
    RETURN_NAMES = ("dimensions",)
    FUNCTION = "build"
    CATEGORY = "SweepKit/Advanced"
    DESCRIPTION = "Turns one list into every subset of it (singles, pairs, triples...), for example to test which styles work well together. Pair it with Sweep UpSet Matrix."
    SEARCH_ALIASES = ["self combine", "subsets", "combinations of a list", "upset"]

    def build(self, dimensions, mode, min_size, max_size, joiner):
        dims = [dict(d) for d in dimensions] if dimensions else []
        if not dims:
            raise ValueError("[SweepDimensionSelfCombine] no axes connected — chain at least one SweepDimension first.")

        target = dims[-1]
        if target.get("group"):
            raise ValueError(
                f"[SweepDimensionSelfCombine] '{target['dim_id']}' is already zipped (group "
                f"'{target['group']}') — self-combine before zipping, not after; which values "
                f"a zipped pair's shared index should recombine against is ambiguous."
            )

        base_values = list(target["values"])
        combo_values, combo_meta = self_combine(base_values, mode, min_size, max_size, joiner)
        if not combo_values:
            raise ValueError(
                f"[SweepDimensionSelfCombine] '{target['dim_id']}': min_size/max_size produced "
                f"zero combinations from {len(base_values)} base value(s)."
            )

        new_dim = dict(target)
        new_dim["values"] = combo_values
        new_dim["combo_meta"] = combo_meta
        new_dim["base_values"] = base_values
        new_dim["dim_id"] = f"{target['dim_id']} ({mode})"

        dims[-1] = new_dim
        print(
            f"[SweepDimensionSelfCombine] '{target['dim_id']}': {len(base_values)} base value(s) "
            f"-> {len(combo_values)} {mode} (sizes {min_size}-{max_size or len(base_values)})"
        )
        return (dims,)


NODE_CLASS_MAPPINGS = {
    "SweepDimensionSelfCombine": SweepDimensionSelfCombine,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SweepDimensionSelfCombine": "Sweep Subsets of a List (Self-Combine)",
}
