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
                        "tooltip": "A chain of SweepDimension nodes — the LAST axis in this chain is the one that gets paired.",
                    },
                ),
                "dimensions_b": (
                    "SWEEP_DIMS",
                    {
                        "tooltip": "A second chain — its LAST axis is paired index-for-index with dimensions_a's last axis.",
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
    CATEGORY = "SweepKit/Advanced"
    DESCRIPTION = "Pairs two axes value-for-value instead of crossing them, e.g. LoRA strength 0.5 with cfg 4 and strength 1.0 with cfg 7."
    SEARCH_ALIASES = ["sweep zip", "pair axes", "link axes"]

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
        for name, chain in (("dimensions_a", dimensions_a), ("dimensions_b", dimensions_b)):
            if not chain:
                raise ValueError(
                    f"[Sweep Pair Axes] {name} has no axes — connect a chain with at least one SweepDimension in it."
                )
        group_a, passthrough_a = self._group_members(list(dimensions_a))
        group_b, passthrough_b = self._group_members(list(dimensions_b))
        group_a, group_b = [dict(d) for d in group_a], [dict(d) for d in group_b]
        passthrough = merge_passthrough(group_a, group_b, passthrough_a + passthrough_b)

        # A zip of a zip already carries a combined group_label ("lora, cfg");
        # use it so a 3-way pairing reads "lora, cfg, steps", not "lora, steps".
        label_a = group_a[0].get("group_label") or group_a[0]["dim_id"]
        label_b = group_b[0].get("group_label") or group_b[0]["dim_id"]
        target_len = zip_length(mode, len(group_a[0]["values"]), len(group_b[0]["values"]), label_a, label_b)
        for d in group_a + group_b:
            resize_dimension_values(d, target_len)

        group_id = group_a[0].get("group") or group_b[0].get("group") or f"zip_{uuid.uuid4().hex[:8]}"
        for d in group_a + group_b:
            d["group"] = group_id
            # Members keep their own dim_id (SweepDimensionExtract looks them
            # up individually); the combined name is display-only.
            d["group_label"] = f"{label_a}, {label_b}"

        combined = passthrough + group_a + group_b
        for i, d in enumerate(combined, start=1):
            d["index"] = i
        return (combined,)


def merge_passthrough(group_a, group_b, passthrough):
    """Upstream dimensions of both inputs, each kept once.

    Both inputs often branch off one shared chain (style -> cfg and
    style -> steps); matching by uid stops the shared dimension being
    cross-producted with itself."""
    seen = {d["uid"] for d in group_a if d.get("uid")}
    uids_b = {d["uid"] for d in group_b if d.get("uid")}
    if seen & uids_b:
        raise ValueError(
            "[Sweep Pair Axes] dimensions_a and dimensions_b end in the same axis — "
            "connect two different SweepDimension chains to pair them."
        )
    seen |= uids_b
    kept = []
    for d in passthrough:
        uid = d.get("uid")
        if uid and uid in seen:
            continue
        if uid:
            seen.add(uid)
        kept.append(dict(d))
    return kept


def zip_length(mode, len_a, len_b, label_a, label_b):
    """Paired length for 'shortest' (truncate), 'longest' (pad by repeating
    the last value) or 'strict' (lengths must match)."""
    if len_a == len_b:
        return len_a
    if mode == "strict":
        raise ValueError(
            f"[Sweep Pair Axes] strict mode: '{label_a}' has {len_a} value(s) but "
            f"'{label_b}' has {len_b} — lengths must match exactly in strict mode. "
            f"Use 'shortest' or 'longest' if that's expected."
        )
    if mode == "longest":
        target = max(len_a, len_b)
        action = f"padding the shorter one by repeating its last value to {target}"
    else:
        target = min(len_a, len_b)
        action = f"truncating both to {target} (shortest mode)"
    print(f"[Sweep Pair Axes] '{label_a}' ({len_a}) and '{label_b}' ({len_b}) differ in length — {action}.")
    return target


NODE_CLASS_MAPPINGS = {
    "SweepDimensionZip": SweepDimensionZip,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SweepDimensionZip": "Sweep Pair Axes (Zip)",
}
