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
    short_message,
    model_labels,
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
                            "What this axis changes. seed, steps, cfg: the sampler's own settings (Sweep All-in-One uses at most one of each). int, float: any other whole or decimal number. text: words for the prompt. lora_strength: a LoRA's strength. model: which model. static: one fixed label for the file names, not swept. See NODE_GUIDE for details."
                        ),
                    },
                ),
                "dim_id": (
                    "STRING",
                    {
                        "default": "",
                        "tooltip": (
                            "The axis name: shown in grid titles and file names, and used to pick this axis on other nodes. Give each axis its own name. Blank uses the type (seed, cfg...)."
                        ),
                    },
                ),
                "values": (
                    "STRING",
                    {
                        "multiline": True,
                        "default": "",
                        "tooltip": (
                            "The values to try. Numbers: separate with commas, like 4, 7, 10; seed, steps and int also take ranges like 1-5 or 10-1 (at most 10,000 values). LoRA strength: 0.8, or model:clip like 0.8:0.6. Text and model labels: one per line (commas stay in the text)."
                        ),
                    },
                ),
                "lora_name": (
                    lora_options,
                    {
                        "default": "",
                        "tooltip": (
                            "Only for lora_strength with Sweep All-in-One: the LoRA whose strength is swept. With Sweep Plan, pick the LoRA on your own Load LoRA node instead."
                        ),
                    },
                ),
            },
            "optional": {
                "prev_dimensions": (
                    "SWEEP_DIMS",
                    {
                        "tooltip": (
                            "Connect the previous Sweep Axis to add this axis to the sweep. Leave unconnected on the first axis."
                        ),
                    },
                ),
                "values_pylist": (
                    "PYLIST",
                    {
                        "tooltip": (
                            "Optional: connect a list from List-Utils (Create PyList, Split String...) to use instead of the values box. For a model axis, connect the models themselves (for example from several Load Checkpoint nodes)."
                        ),
                    },
                ),
            },
        }

    RETURN_TYPES = ("SWEEP_DIMS",)
    RETURN_NAMES = ("dimensions",)
    FUNCTION = "build"
    CATEGORY = "SweepKit"
    DESCRIPTION = "One thing to vary in a sweep: seed, steps, cfg, prompt text, LoRA strength, a model, or any number or text list. Connect several Sweep Axis nodes one after another and SweepKit makes every combination."
    SEARCH_ALIASES = ["sweep dimension", "sweep axis", "x/y plot", "xy plot", "grid search", "parameter sweep"]

    def build(self, dim_type, dim_id, values, lora_name, prev_dimensions=None, values_pylist=None, **kwargs):
        prev = list(prev_dimensions) if prev_dimensions else []
        disp_id = dim_id or dim_type
        dim = {"type": dim_type, "dim_id": disp_id}
        if dim_type == "lora_strength":
            if not lora_name:
                print(
                    f"[Sweep Axis] '{disp_id}' is type 'lora_strength' but no LoRA file is selected "
                    f"— this axis will be skipped."
                )
                return (prev,)
            dim["lora_name"] = lora_name

        if values_pylist is not None:
            # A connected PyList overrides the widget. For 'model' it carries
            # MODEL objects directly, so no per-slot sockets are involved: the
            # objects become model_objs and their file names the values.
            vals = cast_pylist_values(list(values_pylist), dim_type, disp_id)
            if dim_type == "model":
                dim["model_objs"] = vals
                dim["models_from_list"] = True  # Extract hands out the MODELs, not the labels
                vals = model_labels(vals, disp_id)
        elif dim_type == "model":
            vals, dim["model_objs"] = model_slots(values, disp_id, kwargs)
        else:
            vals = parse_widget_values(dim_type, values, disp_id)

        if not vals:
            print(f"[Sweep Axis] '{disp_id}' ({dim_type}) has no values — this axis will be skipped.")
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
        return {"ok": False, "error": short_message(exc)}
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
            f"[Sweep Axis] '{disp_id}' has {len(labels)} model labels; only the first "
            f"{MAX_MODEL_SOCKETS} get MODEL sockets, so the rest are ignored."
        )
        labels = labels[:MAX_MODEL_SOCKETS]
    model_objs = []
    for j, label in enumerate(labels, start=1):
        sock = sockets.get(f"model_{j}")
        if sock is None:
            print(
                f"[Sweep Axis] '{disp_id}' value '{label}' (slot {j}) has no MODEL connected "
                f"— Sweep All-in-One will use its own model input for this slot."
            )
        model_objs.append(sock)
    return labels, model_objs


NODE_CLASS_MAPPINGS = {
    "SweepDimension": SweepDimension,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SweepDimension": "Sweep Axis",
}
