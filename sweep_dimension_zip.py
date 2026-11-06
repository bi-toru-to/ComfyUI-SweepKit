"""
SweepDimensionZip — pair two dimensions so they vary together instead of
being cross-producted.

By default, every SweepDimension chained into SweepAllInOne is an
independent axis: N values on one dimension times M values on another
means N*M images. That's usually what you want, but not always — e.g. a
Turbo/Lightning/LCM LoRA typically wants far fewer steps and a much lower
cfg than the base model, and there's no way to express "use these
settings only when this specific value is active" with independent axes
without cross-producting a steps/cfg sweep across every OTHER value too.

SweepDimensionZip takes the LAST dimension appended to each of two
`SWEEP_DIMS` chains and pairs their values index-for-index — the same
job `zip()` does for two Python iterables. Connect its output onward like
any other dimension chain (into another SweepDimension's
`prev_dimensions`, into another SweepDimensionZip to pair in a third
dimension, or straight into SweepAllInOne's `dimensions` input).

Any OTHER dimensions earlier in either input chain pass through
unchanged, still independent, still cross-producted normally against
everything else — only the two tail dimensions actually get paired.

Each paired member keeps its own individual dim_id (so SweepDimensionExtract
can still pull just one of them out by dim_id later, e.g. lora_model_strength
separately from lora_clip_strength) — a combined "a, b" display string is
stored separately as group_label, used only where a grid/page title needs
to show one representative for the whole pair.
"""

import uuid

from .sweep_core import resize_dimension_values


class SweepDimensionZip:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "dimensions_a": (
                    "SWEEP_DIMS",
                    {
                        "tooltip": "A chain of SweepDimension nodes — the LAST dimension in this chain is the one that gets paired.",
                    },
                ),
                "dimensions_b": (
                    "SWEEP_DIMS",
                    {
                        "tooltip": "A second chain — its LAST dimension is paired index-for-index with dimensions_a's last dimension.",
                    },
                ),
                "mode": (
                    ["shortest", "longest", "strict"],
                    {
                        "default": "shortest",
                        "tooltip": (
                            "shortest: stop at the shorter list, like zip() (extra values on "
                            "the longer side are dropped, with a warning). "
                            "longest: like itertools.zip_longest() — the shorter list is padded "
                            "by repeating its own last value. "
                            "strict: raise an error if the two lists don't have the same length."
                        ),
                    },
                ),
            },
        }

    RETURN_TYPES = ("SWEEP_DIMS",)
    RETURN_NAMES = ("dimensions",)
    FUNCTION = "build"
    CATEGORY = "SweepKit"

    @staticmethod
    def _group_members(dims_list):
        """The dims_list's tail dimension, plus any earlier entries that
        already share its group (i.e. dims_list is itself the output of a
        previous zip) — so zipping a zip's output pairs in a THIRD
        dimension against the whole existing group, not just its tail,
        keeping every previously-paired member aligned to the new length.
        Returns (members, passthrough) — passthrough is everything in
        dims_list NOT part of that group."""
        tail = dims_list[-1]
        gid = tail.get("group")
        if not gid:
            return [tail], dims_list[:-1]
        members = [d for d in dims_list if d.get("group") == gid]
        passthrough = [d for d in dims_list if d.get("group") != gid]
        return members, passthrough

    def build(self, dimensions_a, dimensions_b, mode):
        list_a = list(dimensions_a) if dimensions_a else []
        list_b = list(dimensions_b) if dimensions_b else []
        if not list_a:
            raise ValueError(
                "[SweepDimensionZip] dimensions_a has no dimensions — connect a chain with at least one SweepDimension in it."
            )
        if not list_b:
            raise ValueError(
                "[SweepDimensionZip] dimensions_b has no dimensions — connect a chain with at least one SweepDimension in it."
            )

        group_a, passthrough_a = self._group_members(list_a)
        group_b, passthrough_b = self._group_members(list_b)
        group_a = [dict(d) for d in group_a]
        group_b = [dict(d) for d in group_b]
        passthrough = [dict(d) for d in passthrough_a] + [dict(d) for d in passthrough_b]

        len_a = len(group_a[0]["values"])
        len_b = len(group_b[0]["values"])
        # When chaining a zip's output into another zip (three-way+
        # pairing), group_a/group_b's members already carry a group_label
        # from the previous zip call ("lora, cfg") -- prefer that over just
        # the first member's own individual dim_id ("lora"), or a 3-way
        # chain would silently lose the middle name from the combined
        # display string ("lora, steps" instead of "lora, cfg, steps").
        label_a = group_a[0].get("group_label") or group_a[0]["dim_id"]
        label_b = group_b[0].get("group_label") or group_b[0]["dim_id"]

        if mode == "strict":
            if len_a != len_b:
                raise ValueError(
                    f"[SweepDimensionZip] strict mode: '{label_a}' has {len_a} value(s) but "
                    f"'{label_b}' has {len_b} — lengths must match exactly in strict mode. "
                    f"Use 'shortest' or 'longest' if that's expected."
                )
            target_len = len_a
        elif mode == "longest":
            target_len = max(len_a, len_b)
            if len_a != len_b:
                print(
                    f"[SweepDimensionZip] '{label_a}' ({len_a}) and '{label_b}' ({len_b}) "
                    f"differ in length — padding the shorter one by repeating its last value to {target_len}."
                )
        else:  # "shortest"
            target_len = min(len_a, len_b)
            if len_a != len_b:
                print(
                    f"[SweepDimensionZip] '{label_a}' ({len_a}) and '{label_b}' ({len_b}) "
                    f"differ in length — truncating both to {target_len} (shortest mode)."
                )

        for d in group_a:
            resize_dimension_values(d, target_len)
        for d in group_b:
            resize_dimension_values(d, target_len)

        final_group_id = group_a[0].get("group") or group_b[0].get("group") or f"zip_{uuid.uuid4().hex[:8]}"
        combined_label = f"{label_a}, {label_b}"
        for d in group_a + group_b:
            d["group"] = final_group_id
            # Each member keeps its OWN individual dim_id untouched — needed
            # so SweepDimensionExtract can still tell them apart afterward
            # (e.g. pulling just model_strength vs just clip_strength as
            # separate PyLists for a stock LoraLoader). group_label is a
            # separate field carrying the combined "a, b" display string,
            # used only where a single representative needs to show every
            # group member's value together (grid/page titles) -- it used
            # to overwrite `dim_id` directly, which silently made every
            # member of a zipped pair share one identical dim_id and broke
            # dim_id-based lookup.
            d["group_label"] = combined_label

        combined = passthrough + group_a + group_b
        for i, d in enumerate(combined, start=1):
            d["index"] = i

        return (combined,)


NODE_CLASS_MAPPINGS = {
    "SweepDimensionZip": SweepDimensionZip,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SweepDimensionZip": "Sweep Dimension Zip",
}
