"""
SweepDimension — one axis of an SweepAllInOne sweep, as its own node.

Chain these like a LoRA-stacker: each instance takes an optional
`prev_dimensions` input and produces a `dimensions` output containing
everything upstream plus itself. Connect the last node in the chain into
SweepAllInOne's `dimensions` input. Leave `prev_dimensions` unconnected
on whichever node should be first.

This replaces the earlier design where a single mega-node dynamically grew
and shrank a block of dimN_type/values/label widgets in place. That
approach fought this ComfyUI frontend's widget rendering in ways that
turned out not to be reliably fixable from outside — toggling `.hidden`
on an already-built widget doesn't consistently make richer components
(multiline text boxes) actually rebuild themselves, and several rounds of
targeted patches each fixed one symptom while surfacing another. Making
each dimension its own ordinary node sidesteps the whole problem: adding,
removing, and resizing *nodes* is something ComfyUI already does
correctly and doesn't need any help with. The one piece of genuinely
dynamic JS that remains — spawning MODEL input sockets for a "model"-type
dimension — is scoped to a single node's own two widgets now instead of
juggling state across up to 8 dimensions on one shared node, and reuses
logic that was never the source of a reported bug across the mega-node's
several revisions.
"""

import uuid

import folder_paths

from .sweep_core import (
    DIM_TYPE_OPTIONS,
    MAX_MODEL_SOCKETS,
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
                            "seed, steps, cfg and model dimension each. 'text' fills the next "
                            "available {} in SweepAllInOne's positive_prompt, counting only "
                            "text-type dimensions in chain order (closest to the start of the "
                            "chain = 1st {}). 'lora_strength' sweeps the selected LoRA's strength; "
                            "several lora_strength dimensions stack, applied in chain order. "
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
                            "looks dimensions up by matching this EXACTLY, so give it a real value "
                            "if you're using those. Defaults to dim_type if left blank, which is "
                            "fine for the all-in-one SweepAllInOne node but will collide with "
                            "any other same-typed dimension's default in the modular pipeline "
                            "(two blank-dim_id 'cfg' dimensions can't both default to 'cfg' and "
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
                        "tooltip": "Chain from another SweepDimension node to add more axes. Leave unconnected if this is the first dimension in the chain.",
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

    def build(self, dim_type, dim_id, values, lora_name, prev_dimensions=None, values_pylist=None, **kwargs):
        prev = list(prev_dimensions) if prev_dimensions else []
        disp_id = dim_id or dim_type

        dim = {"type": dim_type, "dim_id": disp_id}

        # A connected values_pylist socket overrides the string widget
        # entirely — cast/validate its elements to match dim_type instead
        # of parsing a string. For dim_type='model' the dynamic MODEL-
        # socket mechanism further below is skipped entirely: values
        # arrive as whatever the PyList contains (typically MODEL objects
        # assembled via List-Utils' Create PyList), no per-slot socket
        # resolution needed.
        if values_pylist is not None:
            vals = cast_pylist_values(list(values_pylist), dim_type, disp_id)
            if dim_type == "lora_strength":
                dim["lora_name"] = lora_name
                if not lora_name:
                    print(
                        f"[SweepDimension] '{disp_id}' is type 'lora_strength' but no LoRA file is selected — this dimension will be skipped."
                    )
                    return (prev,)
        elif dim_type == "text":
            vals = parse_text_list(values)
        elif dim_type == "static":
            vals = parse_text_list(values)[:1] or ["static"]
        elif dim_type in ("seed", "steps", "int"):
            vals = parse_number_list(values, int, disp_id, allow_range=True)
        elif dim_type in ("cfg", "float"):
            vals = parse_number_list(values, float, disp_id)
        elif dim_type == "lora_strength":
            vals = parse_lora_strength_list(values, disp_id)
            dim["lora_name"] = lora_name
            if not lora_name:
                print(
                    f"[SweepDimension] '{disp_id}' is type 'lora_strength' but no LoRA file is selected — this dimension will be skipped."
                )
                return (prev,)
        elif dim_type == "model":
            labels = parse_text_list(values)
            if len(labels) > MAX_MODEL_SOCKETS:
                # web/sweepkit.js never creates more than MAX_MODEL_SOCKETS
                # sockets, so extra labels could only ever fall back to the
                # base model — drop them visibly instead.
                print(
                    f"[SweepDimension] '{disp_id}' has {len(labels)} model labels; only the first "
                    f"{MAX_MODEL_SOCKETS} get MODEL sockets, so the rest are ignored."
                )
                labels = labels[:MAX_MODEL_SOCKETS]
            vals = labels
            model_objs = []
            for j, lab in enumerate(labels, start=1):
                sock = kwargs.get(f"model_{j}")
                if sock is None:
                    print(
                        f"[SweepDimension] '{disp_id}' value '{lab}' (slot {j}) has no MODEL connected — SweepAllInOne will fall back to its base model input for this slot."
                    )
                model_objs.append(sock)
            dim["model_objs"] = model_objs
        else:
            vals = []

        if not vals:
            print(f"[SweepDimension] '{disp_id}' ({dim_type}) has no values — this dimension will be skipped.")
            return (prev,)

        dim["index"] = len(prev) + 1
        dim["values"] = vals
        # Stable identity for this dimension as it travels through branches:
        # lets SweepDimensionZip recognise the same upstream dimension arriving
        # via both of its inputs instead of counting it twice.
        dim["uid"] = uuid.uuid4().hex
        return (prev + [dim],)


NODE_CLASS_MAPPINGS = {
    "SweepDimension": SweepDimension,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SweepDimension": "Sweep Dimension",
}
