"""
SweepDedupeCombos — find combos whose sampling-relevant settings are
identical (e.g. a 'lighting' axis whose placeholder isn't actually
referenced in the prompt template, so every lighting value resolves to
byte-identical text) so they only get sampled once.

Takes ONE 'axis_values' PYLIST-of-PYLISTs input rather than a fixed set of
named sockets — bundle however many axis PYLISTs matter (seeds, cfgs,
positive_texts, a model_key string companion, ...) with List-Utils' own
"Create PyList" node first. This reuses List-Utils' existing dynamic-socket
infrastructure instead of this pack growing its own dynamic-socket JS for
the same job.

Doesn't touch combo_records or images itself — just produces the index
bookkeeping (unique_index_map, expand_indices) that SweepGather consumes,
twice: once to shrink each axis list down to the unique combos worth
sampling, once more to re-expand the sampled image list back out to the
original length.
"""

from .sweep_core import build_dedupe_keys, counted, dedupe_indices


class SweepDedupeCombos:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "axis_values": (
                    "PYLIST",
                    {
                        "forceInput": True,
                        "tooltip": (
                            "The values that decide what each image looks like, one list per axis (for example the prompt texts from Sweep Axis Value). Put the lists together with List-Utils' Create PyList."
                        ),
                    },
                ),
                "float_precision": (
                    "INT",
                    {
                        "default": 4,
                        "min": 0,
                        "max": 15,
                        "tooltip": (
                            "Decimal places compared for numbers: 7.5 and 7.5000001 count as the same at the default."
                        ),
                    },
                ),
            },
        }

    RETURN_TYPES = ("PYLIST", "PYLIST", "INT")
    RETURN_NAMES = ("unique_index_map", "expand_indices", "unique_count")
    FUNCTION = "build"
    CATEGORY = "SweepKit/Advanced"
    DESCRIPTION = "Finds combinations that would make an identical image and keeps each distinct one once, so it is sampled once. Pair with Sweep Gather."
    SEARCH_ALIASES = ["dedupe", "skip repeats", "unique combinations"]

    def build(self, axis_values, float_precision):
        keys = build_dedupe_keys(list(axis_values), float_precision)
        unique_index_map, expand_indices = dedupe_indices(keys)
        n, m = len(keys), len(unique_index_map)
        if m < n:
            print(
                f"[Sweep Skip Repeats] {counted(n, 'combination')} -> {counted(m, 'different setting')} "
                f"({counted(n - m, 'repeat')} will reuse an image instead of making a new one)."
            )
        else:
            print(f"[Sweep Skip Repeats] {counted(n, 'combination')}, no repeats found.")
        return (unique_index_map, expand_indices, m)


NODE_CLASS_MAPPINGS = {
    "SweepDedupeCombos": SweepDedupeCombos,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SweepDedupeCombos": "Sweep Skip Repeats (Dedupe)",
}
