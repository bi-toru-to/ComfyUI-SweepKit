"""
SweepDimensionExtract — pull one axis's flattened, per-combo values out of
combo, as a PYLIST ready for List-Utils' "PyList To List" and then
straight into whichever stock node actually needs it (KSampler.seed,
LoraLoader.strength_model, CLIPTextEncode.text after substitution, ...).

One instance per axis you need downstream. Matches by exact dimension
dim_id (content-addressed — survives reordering upstream), not by chain
position, so inserting or reordering SweepDimension nodes upstream doesn't
silently repoint an extractor at the wrong axis the way a positional
"dim3" token would.
"""

from .sweep_core import extract_values


class SweepDimensionExtract:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
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
                        "tooltip": "Exact dim_id of the axis to extract (the 'dim_id' field you gave its SweepDimension node, or its dim_type if left blank there).",
                    },
                ),
                "component": (
                    ["value", "model_strength", "clip_strength"],
                    {
                        "default": "value",
                        "tooltip": "Only meaningful for a lora_strength-type axis, whose values are (model_strength, clip_strength) tuples — pick which half to pull out as a scalar.",
                    },
                ),
            },
        }

    # Slot 0 is the original PyList output (saved workflows link to it). Slot 1
    # is the same values as a native list, for connecting straight to a setting.
    RETURN_TYPES = ("PYLIST", "*")
    RETURN_NAMES = ("values", "list")
    OUTPUT_IS_LIST = (False, True)
    OUTPUT_TOOLTIPS = (
        "The values as a PyList, for List-Utils nodes.",
        "The values as a list: connect it to any setting and that node runs once per value.",
    )
    FUNCTION = "build"
    CATEGORY = "SweepKit/Advanced"
    DESCRIPTION = (
        "Pulls one axis's value out of every combination, as the list a KSampler, LoRA or text node should use."
    )
    SEARCH_ALIASES = ["extract dimension", "axis value"]

    def build(self, combo, dim_id, component):
        values = extract_values(combo["dimensions"], combo["combo_records"], dim_id, component)
        return (values, values)


NODE_CLASS_MAPPINGS = {
    "SweepDimensionExtract": SweepDimensionExtract,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SweepDimensionExtract": "Sweep Axis Value (Extract)",
}
