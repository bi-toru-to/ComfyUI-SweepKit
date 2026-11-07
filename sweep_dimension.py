"""
SweepDimension — one axis of an SweepAllInOne sweep, as its own node.

Chain these like a LoRA-stacker: each instance takes an optional
`prev_dimensions` input and produces a `dimensions` output containing
everything upstream plus itself. Connect the last node in the chain into
SweepAllInOne's `dimensions` input. Leave `prev_dimensions` unconnected
on whichever node should be first.

Each axis is its own ordinary node because adding, removing and resizing
nodes is something ComfyUI's frontend handles reliably, whereas growing
and hiding many widgets on one node did not (see DESIGN.md). The only
dynamic UI left is the MODEL sockets of a 'model'-type dimension
(web/sweepkit.js).
"""

import re
import uuid

import folder_paths

from .sweep_core import (
    DIM_TYPE_OPTIONS,
    MAX_MODEL_SOCKETS,
    PREVIEW_VALUES,
    format_dim_value,
    parse_text_list,
    parse_number_list,
    parse_lora_strength_list,
    cast_pylist_values,
)


class SweepDimension:
    @classmethod
    def INPUT_TYPES(cls):
        lora_options = [""] + folder_paths.get_filename_list("loras")
        return {
            "required": {
                "dim_type": (
                    DIM_TYPE_OPTIONS,
                    {
                        "default": "text",
                        "tooltip": (
                            "'int'/'float' are generic numeric axes with no special behavior "
                            "beyond casting — use these for anything that isn't literally the "
                            "sampler's own seed/steps/cfg (e.g. a LoRA strength you'll feed into "
                            "a stock LoraLoader). 'seed'/'steps'/'cfg' cast the same way as "
                            "'int'/'int'/'float' respectively, but are ALSO recognized by "
                            "SweepAllInOne's fixed_seed/fixed_steps/fixed_cfg fallback and by "
                            "grid_x_dim=auto's seed-preference — use these specifically when this "
                            "axis IS that sampler parameter; SweepAllInOne accepts at most one "
                            "seed, steps, cfg and model axis each. 'text' fills the next "
                            "available {} in SweepAllInOne's positive_prompt, counting only "
                            "text-type axes in chain order (closest to the start of the "
                            "chain = 1st {}). 'lora_strength' sweeps the selected LoRA's strength; "
                            "several lora_strength axes stack, applied in chain order. "
                            "'model' turns 'values' into a label list and spawns one MODEL "
                            "input socket per label (up to 24) instead of a value list. 'static' is a "
                            "fixed, non-swept single value (only the first line of 'values' is "
                            "kept) that still participates in grid titles/filenames/folders — "
                            "for tagging a whole sweep with something constant without wiring it "
                            "into the prompt at all."
                        ),
                    },
                ),
                "dim_id": (
                    "STRING",
                    {
                        "default": "",
                        "tooltip": (
                            "Identifies this axis — grid titles/filenames use it for display, and "
                            "the modular pipeline (SweepDimensionExtract, SweepUpsetConstructor) "
                            "looks axes up by matching this EXACTLY, so give it a real value "
                            "if you're using those. Defaults to dim_type if left blank, which is "
                            "fine for the all-in-one SweepAllInOne node but will collide with "
                            "any other same-typed axis's default in the modular pipeline "
                            "(two blank-dim_id 'cfg' axes can't both default to 'cfg' and "
                            "still be told apart)."
                        ),
                    },
                ),
                "values": (
                    "STRING",
                    {
                        "multiline": True,
                        "default": "",
                        "tooltip": (
                            "Values, one per line. Numeric types (seed/steps/cfg/int/float/"
                            "lora_strength) also split on commas; text/static/model values "
                            "split on newlines only, so a comma-separated tag list stays one "
                            "value. For seed/steps/int you can also write a range like '1-5' "
                            "or '-3-2'. For dim_type='model' "
                            "this is a list of socket labels instead — editing it "
                            "adds/removes MODEL input sockets below."
                        ),
                    },
                ),
                "lora_name": (
                    lora_options,
                    {
                        "default": "",
                        "tooltip": (
                            "Only used when dim_type = 'lora_strength' — which LoRA file's "
                            "strength 'values' sweeps. Only consumed by SweepAllInOne's own "
                            "internal LoRA application; the modular pipeline ignores this field "
                            "entirely (pick the LoRA file on the stock LoraLoader node's own "
                            "lora_name widget instead — this axis just supplies the numeric "
                            "strengths via SweepDimensionExtract's model_strength/clip_strength "
                            "component)."
                        ),
                    },
                ),
            },
            "optional": {
                "prev_dimensions": (
                    "SWEEP_DIMS",
                    {
                        "tooltip": "Chain from another SweepDimension node to add more axes. Leave unconnected if this is the first axis in the chain.",
                    },
                ),
                "values_pylist": (
                    "PYLIST",
                    {
                        "tooltip": (
                            "Connect a PyList (e.g. from List-Utils' Create PyList / Split String / "
                            "Create Linspace) to OVERRIDE the 'values' widget above. Elements are cast "
                            "to match dim_type, raising a clear error if they can't be. For dim_type="
                            "'model', elements are passed through untouched (e.g. MODEL objects "
                            "assembled via Create PyList from several checkpoint loaders) — this "
                            "replaces the dynamic MODEL-socket mechanism below entirely when connected."
                        ),
                    },
                ),
            },
        }

    RETURN_TYPES = ("SWEEP_DIMS",)
    RETURN_NAMES = ("dimensions",)
    FUNCTION = "build"
    CATEGORY = "SweepKit"
    DESCRIPTION = "One thing to vary in a sweep: seed, steps, cfg, prompt text, LoRA strength, a model, or any number or text list. Chain several Axis nodes (connect one's output to the next one's prev_dimensions) and SweepKit makes every combination."
    SEARCH_ALIASES = ["sweep dimension", "sweep axis", "x/y plot", "xy plot", "grid search", "parameter sweep"]

    def build(self, dim_type, dim_id, values, lora_name, prev_dimensions=None, values_pylist=None, **kwargs):
        prev = list(prev_dimensions) if prev_dimensions else []
        disp_id = dim_id or dim_type
        dim = {"type": dim_type, "dim_id": disp_id}
        if dim_type == "lora_strength":
            if not lora_name:
                print(
                    f"[SweepDimension] '{disp_id}' is type 'lora_strength' but no LoRA file is selected "
                    f"— this axis will be skipped."
                )
                return (prev,)
            dim["lora_name"] = lora_name

        if values_pylist is not None:
            # A connected PyList overrides the widget. For 'model' it carries
            # MODEL objects directly, so no per-slot sockets are involved.
            vals = cast_pylist_values(list(values_pylist), dim_type, disp_id)
        elif dim_type == "model":
            vals, dim["model_objs"] = model_slots(values, disp_id, kwargs)
        else:
            vals = parse_widget_values(dim_type, values, disp_id)

        if not vals:
            print(f"[SweepDimension] '{disp_id}' ({dim_type}) has no values — this axis will be skipped.")
            return (prev,)
        dim["index"] = len(prev) + 1
        dim["values"] = vals
        # Stable identity as the dimension travels through branches, so
        # SweepDimensionZip can recognise one arriving via both inputs.
        dim["uid"] = uuid.uuid4().hex
        return (prev + [dim],)


# dim_type -> (cast, ranges like '1-5' allowed)
_NUMERIC_TYPES = {
    "seed": (int, True),
    "steps": (int, True),
    "int": (int, True),
    "cfg": (float, False),
    "float": (float, False),
}


def parse_widget_values(dim_type, values, disp_id):
    """Parse the 'values' text widget for every type except 'model'."""
    if dim_type == "text":
        return parse_text_list(values)
    if dim_type == "static":
        return parse_text_list(values)[:1] or ["static"]
    if dim_type == "lora_strength":
        return parse_lora_strength_list(values, disp_id)
    if dim_type in _NUMERIC_TYPES:
        cast, allow_range = _NUMERIC_TYPES[dim_type]
        return parse_number_list(values, cast, disp_id, allow_range=allow_range)
    return []


def preview_values(dim_type, values):
    """What a Sweep Axis's `values` text will parse to, for the summary line
    under the widget: {"ok": True, "count": n, "labels": [first few]} or
    {"ok": False, "error": plain-language reason}. Never raises."""
    try:
        vals = parse_text_list(values) if dim_type == "model" else parse_widget_values(dim_type, values, "axis")
    except ValueError as exc:
        return {"ok": False, "error": re.sub(r"^\[\w+\]\s*'[^']*':\s*", "", str(exc))}
    dim = {"type": dim_type, "values": vals}
    shown = [format_dim_value(dim, i) for i in range(min(len(vals), PREVIEW_VALUES))]
    return {"ok": True, "count": len(vals), "labels": shown}


def model_slots(values, disp_id, sockets):
    """Labels from the 'values' widget and the MODEL connected to each
    label's model_N socket (None = SweepAllInOne uses its base model)."""
    labels = parse_text_list(values)
    if len(labels) > MAX_MODEL_SOCKETS:
        # web/sweepkit.js never creates more sockets than this, so extra
        # labels could only ever fall back to the base model.
        print(
            f"[SweepDimension] '{disp_id}' has {len(labels)} model labels; only the first "
            f"{MAX_MODEL_SOCKETS} get MODEL sockets, so the rest are ignored."
        )
        labels = labels[:MAX_MODEL_SOCKETS]
    model_objs = []
    for j, label in enumerate(labels, start=1):
        sock = sockets.get(f"model_{j}")
        if sock is None:
            print(
                f"[SweepDimension] '{disp_id}' value '{label}' (slot {j}) has no MODEL connected "
                f"— SweepAllInOne will fall back to its base model input for this slot."
            )
        model_objs.append(sock)
    return labels, model_objs


NODE_CLASS_MAPPINGS = {
    "SweepDimension": SweepDimension,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SweepDimension": "Sweep Axis",
}
