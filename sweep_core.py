"""
Shared constants and pure helper functions for the SweepKit node pack
(SweepDimension + SweepAllInOne). Deliberately import-light — no torch,
no comfy — so this module (and therefore the parsing/grid-axis logic that
matters most) can be unit tested with plain `python3 sweep_core.py`
style imports, without needing a ComfyUI/torch environment at all.
"""

from __future__ import annotations

import csv
import itertools
import logging
import math
import os
import re
from typing import Any, Callable, Iterable, Sequence, TypedDict

log = logging.getLogger("SweepKit")


class SweepError(ValueError):
    """A ValueError that also carries a one-line 'problem: fix' form, for the
    summary lines under a node, which can't show a whole message."""

    def __init__(self, message: str, short: str | None = None) -> None:
        super().__init__(message)
        self.short = short


def short_message(exc: Exception) -> str:
    """The one-line form of an error: its short form, or the message without its [node] tag."""
    return getattr(exc, "short", None) or re.sub(r"^\[[^\]]+\]\s*('[^']*':\s*)?", "", str(exc))


class Dimension(TypedDict, total=False):
    """One sweep axis as it travels down a SWEEP_DIMS chain.

    Built by SweepDimension.build(); later nodes copy it with dict(d) and
    may add keys, never mutate an upstream node's copy."""

    type: str  # one of DIM_TYPE_OPTIONS
    dim_id: str  # user-facing name; defaults to the type
    index: int  # 1-based position among active dimensions in the chain
    values: list[Any]  # parsed values (lora_strength: (model, clip) tuples)
    uid: str  # stable identity across branches (SweepDimensionZip dedupe)
    lora_name: str  # lora_strength only: which LoRA file
    model_objs: list[Any]  # model only: MODEL per value (None = base model)
    models_from_list: bool  # model only: model_objs came from a PyList (values are their file names)
    group: str  # set by SweepDimensionZip: members share one value index
    group_label: str  # "label_a, label_b" display name of a zipped group
    combo_meta: list[dict]  # SweepDimensionSelfCombine: {"arity", "members"} per value
    base_values: list[Any]  # SweepDimensionSelfCombine: the original values


class ComboRecord(TypedDict):
    """One generated combination: which value index each dimension uses."""

    combo_index: int
    idx_by_dim: dict[int, int]  # Dimension["index"] -> index into its values


DIM_TYPE_OPTIONS = [
    "text",
    "int",
    "float",
    "seed",
    "steps",
    "cfg",
    "lora_strength",
    "model",
    "static",
]

# Lower number = switched less often (outer loop) in the generation node's
# execution order. Model swaps are the heaviest thing that can happen
# (VRAM residency churn across potentially large checkpoints), lora
# application is a real but smaller cost, text needs a CLIP re-encode, and
# seed/steps/cfg (and the generic int/float types, which cast the same way)
# are essentially free sampler parameters.
COST_RANK = {
    "model": 0,
    "lora_strength": 1,
    "text": 2,
    "static": 2,
    "seed": 3,
    "steps": 3,
    "cfg": 3,
    "int": 3,
    "float": 3,
}

# The grid_x_dim / grid_y_dim / grid_title_dim pickers. In the browser the
# list is replaced by the dim_ids of the axes actually connected (see
# web/sweepkit_soft.js, syncAxisPickers); these "dimN" (chain position)
# entries are what a node shows before that, and what older saved workflows
# hold. Either form works: resolve_axis_token accepts a dim_id or dimN, so
# the nodes skip ComfyUI's fixed-list check for these inputs (VALIDATE_INPUTS).
GRID_AXIS_PICKER_RANGE = 12
GRID_AXIS_OPTIONS = ["auto", "none"] + [f"dim{i}" for i in range(1, GRID_AXIS_PICKER_RANGE + 1)]
GRID_AXIS_INPUTS = ("grid_x_dim", "grid_y_dim", "grid_title_dim")


def validate_axis_picks(**picks: Any) -> bool | str:
    """VALIDATE_INPUTS body for the axis pickers: any text is accepted (a
    dim_id, dimN, auto or none); a pick that matches no axis falls back to
    auto at run time with a printed reason."""
    for name, value in picks.items():
        values = value if isinstance(value, list) else [value]
        if not all(isinstance(v, str) for v in values):
            return f"{name} must be text (an axis name, auto or none)"
    return True


def resolve_axis_token(dims: Sequence[Dimension], token: str) -> Dimension | None:
    """The axis a picker value names: a dim_id that only one axis has, or
    'dimN' (chain position, as older workflows saved it). None if neither."""
    named = [d for d in dims if d.get("dim_id") == token]
    if len(named) == 1:
        return named[0]
    return next((d for d in dims if f"dim{d['index']}" == token), None)


# Upper bound on a 'model' dimension's MODEL sockets. Must match MAX_SOCKETS
# in web/sweepkit.js, which never creates more sockets than this.
MAX_MODEL_SOCKETS = 24

# Console summaries list this many values per dimension, and warn when a
# sweep has more than LARGE_SWEEP_WARNING images.
PREVIEW_VALUES = 6
LARGE_SWEEP_WARNING = 500

# Generated relative paths longer than MAX_NAME_LEN are cut to
# TRUNCATED_NAME_LEN plus a unique suffix (Windows paths are limited).
MAX_NAME_LEN = 220
TRUNCATED_NAME_LEN = 200

# A lora_strength value is a (model_strength, clip_strength) pair.
STRENGTH_PAIR_LEN = 2

# SweepDimensionSelfCombine refuses to derive more values than this.
MAX_DERIVED_VALUES = 10_000

# How many per-axis list outputs Sweep Plan has. Must match MAX_AXIS_OUTPUTS
# in web/sweepkit_soft.js (the frontend hides the ones a chain doesn't use).
MAX_AXIS_OUTPUTS = 8


# Windows device names: a path component whose stem is one of these (e.g.
# "NUL", "con.png") refers to a device, not a file, and saving fails.
_WINDOWS_RESERVED = re.compile(r"(?i)^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\..*)?$")


def safe_component(s: Any) -> str:
    """Sanitize a string for use as a folder or filename component."""
    s = re.sub(r"[^\w\-. ]", "_", str(s)).strip().strip(".")
    s = s[:80].rstrip(" .")
    if _WINDOWS_RESERVED.match(s):
        s = "_" + s
    return s if s else "_"


def parse_text_list(raw: Any) -> list[str]:
    """One value per line — newline only. Unlike the numeric parsers
    below, commas are NOT treated as a separator here, since a single
    text value legitimately contains them (e.g. a comma-separated tag
    list meant to fill one {} as a whole: 'masterpiece, highres, 1girl').
    Splitting on commas would shred that into three separate values."""
    if raw is None or not str(raw).strip():
        return []
    return [line.strip() for line in str(raw).split("\n") if line.strip()]


def parse_number_list(raw: Any, cast: Callable[[str], Any], dim_id: str, allow_range: bool = False) -> list[Any]:
    """Parse a comma/newline separated list of numbers.

    Raises ValueError naming the offending dimension and value, instead of
    silently keeping unparsable entries as raw strings (which would only
    blow up much later, deep inside the sampler, with a confusing error).
    """
    if raw is None or not str(raw).strip():
        return []
    out = []
    for line in str(raw).replace(",", "\n").split("\n"):
        line = line.strip()
        if not line:
            continue
        range_match = re.fullmatch(r"(-?\d+)\s*-\s*(-?\d+)", line) if allow_range else None
        if range_match:
            a, b = int(range_match[1]), int(range_match[2])
            if abs(b - a) + 1 > MAX_DERIVED_VALUES:
                raise SweepError(
                    f"[Sweep Axis] '{dim_id}': the range '{line}' in values makes {abs(b - a) + 1:,} values, "
                    f"more than the limit of {MAX_DERIVED_VALUES:,}. Use a shorter range or fewer values.",
                    f"'{line}' makes {abs(b - a) + 1:,} values (limit {MAX_DERIVED_VALUES:,}): use a shorter range",
                )
            step = 1 if b >= a else -1
            out.extend(range(a, b + step, step))
            continue
        try:
            out.append(cast(line))
        except ValueError:
            kind, example = ("whole number", "1, 2, 3 or a range like 1-5") if cast is int else ("number", "4, 7.5, 10")
            if cast is int and not allow_range:
                example = "1, 2, 3"
            short_example = "1, 2, 3 or 1-5" if cast is int and allow_range else example
            raise SweepError(
                f"[Sweep Axis] '{dim_id}': '{line}' in values is not a {kind}. "
                f"Type {kind}s separated by commas, like {example}.",
                f"'{line}' is not a {kind}: type e.g. {short_example}",
            ) from None
    return out


def parse_lora_strength_list(raw: Any, dim_id: str) -> list[tuple[float, float]]:
    """Each line is either 'X' (applied to both model & clip) or
    'X:Y' (model strength : clip strength)."""
    if raw is None or not str(raw).strip():
        return [(1.0, 1.0)]
    out = []
    for line in str(raw).replace(",", "\n").split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            if ":" in line:
                sm, sc = line.split(":", 1)
                out.append((float(sm), float(sc)))
            else:
                v = float(line)
                out.append((v, v))
        except ValueError:
            raise SweepError(
                f"[Sweep Axis] '{dim_id}': '{line}' in values is not a LoRA strength. "
                f"Type a number like 0.8, or model:clip strengths like 0.8:0.6.",
                f"'{line}' is not a LoRA strength: type e.g. 0.8 or 0.8:0.6",
            ) from None
    return out or [(1.0, 1.0)]


def format_dim_value(d: Dimension, vi: int) -> str:
    """Display text for a dimension's value at index vi: lora_strength
    pairs as '0.5' (equal) or '0.5/0.3' (model/clip), never a raw tuple;
    floats with trailing zeros trimmed so '1' and '1.0' look the same."""
    val = d["values"][vi]
    if d["type"] == "lora_strength":
        sm, sc = val
        return f"{sm:g}" if sm == sc else f"{sm:g}/{sc:g}"
    if isinstance(val, float):
        return f"{val:g}"
    if not isinstance(val, (str, int, bool)):
        return f"{d['dim_id']}{vi}"  # e.g. a MODEL object from a PyList: its position, as in file names
    return str(val)


def dim_group_members(d: Dimension, active_dims: Sequence[Dimension]) -> list[Dimension]:
    """Every dimension sharing d's group id (including d itself), or just
    [d] if it isn't grouped. Used so a zipped pair/triple's displayed
    value reflects ALL of what's actually varying together, not just
    whichever single member happened to be picked to represent the group
    for axis/title purposes."""
    gid = d.get("group")
    if not gid:
        return [d]
    return [o for o in active_dims if o.get("group") == gid]


def format_group_value(group: Sequence[Dimension], vi: int) -> str:
    """Combined display value for a (possibly multi-member) group at the
    shared index vi -- e.g. '0.5, 15, 2' for a zipped lora_strength+steps+
    cfg triple, matching the combined 'label1, label2, label3' the group
    already carries."""
    return ", ".join(format_dim_value(d, vi) for d in group)


def resize_dimension_values(dim: Dimension, new_length: int) -> None:
    """Truncate or pad (by repeating the last element) a dimension's
    values — and, for a 'model' dimension, its parallel model_objs list —
    to `new_length`. Used by SweepDimensionZip to align two dimensions'
    lengths before pairing them index-for-index."""
    values = dim["values"]
    if len(values) >= new_length:
        dim["values"] = values[:new_length]
    else:
        pad = values[-1] if values else None
        dim["values"] = values + [pad] * (new_length - len(values))

    if "model_objs" in dim:
        mo = dim["model_objs"]
        if len(mo) >= new_length:
            dim["model_objs"] = mo[:new_length]
        else:
            pad = mo[-1] if mo else None
            dim["model_objs"] = mo + [pad] * (new_length - len(mo))


def partition_into_groups(active_dims: Sequence[Dimension]) -> list[list[Dimension]]:
    """Group dimensions that share a 'group' id (set by SweepDimensionZip)
    so the generation loop can iterate them together with one shared
    index, instead of cross-producting them as independent axes.
    Ungrouped dimensions each form their own singleton group — unchanged
    from the pre-zip behavior."""
    groups = {}
    order = []
    for d in active_dims:
        gid = d.get("group")
        key = gid if gid else f"__solo_{d['index']}"
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(d)
    return [groups[k] for k in order]


def group_cost_rank(group: Sequence[Dimension]) -> int:
    """A group's cost is however expensive its most expensive member is —
    e.g. a lora_strength dimension zipped with a cfg dimension should
    still be treated as outer-loop-expensive, since changing the group's
    index changes the lora too, not just the cfg."""
    return min(COST_RANK.get(d["type"], 5) for d in group)


def sort_groups(groups: Sequence[list[Dimension]]) -> list[list[Dimension]]:
    return sorted(groups, key=lambda g: (group_cost_rank(g), min(d["index"] for d in g)))


def resolve_group_index(d: Dimension, full_idx: dict[int, int], active_dims: Sequence[Dimension]) -> int:
    """Look up the resolved value-index for dimension `d` within a grid
    cell's index map. If d's own index isn't a key in full_idx (it wasn't
    given an explicit X/Y/Title/grouping role because a groupmate was
    used to represent the group instead), fall back to whichever
    groupmate's index IS present — they share one index by construction,
    so this recovers the correct value without d needing its own role."""
    if d["index"] in full_idx:
        return full_idx[d["index"]]
    gid = d.get("group")
    if gid:
        for other in active_dims:
            if other.get("group") == gid and other["index"] in full_idx:
                return full_idx[other["index"]]
    return 0


def resolve_grid_axes(
    active_dims: Sequence[Dimension],
    grid_x_dim: str,
    grid_y_dim: str,
    grid_title_dim: str,
    node_tag: str = "Sweep All-in-One",
) -> tuple[Dimension | None, Dimension | None, Dimension | None, list[Dimension]]:
    """Turn the grid_x_dim / grid_y_dim / grid_title_dim picks ('auto',
    'none' or 'dimN') into dimensions. Returns (x, y, title, others); every
    combination of `others` becomes its own grid, so no axis is dropped.

    - Zip groups move in lockstep, so at most one member of a group gets a
      role; giving a second member another role would only add empty
      off-diagonal cells.
    - Auto-fill runs X, then Y, then title last, so a 2-axis sweep always
      lands on one X/Y grid. X prefers a seed, then any non-text
      dimension; Y prefers non-text, so text tends to end up as the title.
    - An explicit pick that can't be honoured (unknown, or its zip group
      is taken) falls back to auto-fill with a printed reason, unless the
      role is 'none'.
    """
    claims = _AxisClaims(active_dims, node_tag)
    x_dim = claims.explicit(grid_x_dim, "x")
    y_dim = claims.explicit(grid_y_dim, "y")
    title_dim = claims.explicit(grid_title_dim, "title")

    def non_text(d: Dimension) -> bool:
        return d["type"] not in ("text", "static")

    if grid_x_dim != "none" and x_dim is None:
        x_dim = claims.auto_pick(lambda d: d["type"] == "seed", non_text, lambda d: True)
    if grid_y_dim != "none" and y_dim is None:
        y_dim = claims.auto_pick(non_text, lambda d: True)
    if grid_title_dim != "none" and title_dim is None:
        title_dim = claims.auto_pick(lambda d: True)

    other_dims = one_per_group(d for d in active_dims if claims.available(d))
    return x_dim, y_dim, title_dim, other_dims


class _AxisClaims:
    """Tracks which dimensions (and zip groups) already have a grid role."""

    def __init__(self, active_dims: Sequence[Dimension], node_tag: str) -> None:
        self.active_dims = active_dims
        self.node_tag = node_tag
        self.used_indices = set()
        self.used_groups = set()

    def available(self, d: Dimension) -> bool:
        group = d.get("group")
        return d["index"] not in self.used_indices and not (group and group in self.used_groups)

    def claim(self, d: Dimension) -> Dimension:
        self.used_indices.add(d["index"])
        if d.get("group"):
            self.used_groups.add(d["group"])
        return d

    def explicit(self, token: str, role: str) -> Dimension | None:
        """The axis an explicit pick (a dim_id or 'dimN') names, if it can
        take this role; None (with a printed reason) if it can't."""
        if token in ("auto", "none"):
            return None
        d = resolve_axis_token(self.active_dims, token)
        if d is None:
            reason = "doesn't match any active axis"
        elif not self.available(d):
            in_group = d.get("group") in self.used_groups
            reason = f"('{d['dim_id']}') can't be used here — " + (
                "its group is already used by another grid axis"
                if in_group
                else "it's already used by another grid axis"
            )
        else:
            return self.claim(d)
        print(f"[{self.node_tag}] grid_{role}_dim '{token}' {reason}. Falling back to auto-selection for {role}.")
        return None

    def auto_pick(self, *preferences: Callable[[Dimension], bool]) -> Dimension | None:
        """Claim the first available dimension matching the first
        preference that matches anything; None if nothing is left."""
        for prefer in preferences:
            d = next((d for d in self.active_dims if prefer(d) and self.available(d)), None)
            if d is not None:
                return self.claim(d)
        return None


def one_per_group(dims: Iterable[Dimension]) -> list[Dimension]:
    """Keep ungrouped dimensions plus the first member of each zip group,
    so a correlated pair is never treated as two independent axes."""
    out, seen = [], set()
    for d in dims:
        gid = d.get("group")
        if gid:
            if gid in seen:
                continue
            seen.add(gid)
        out.append(d)
    return out


_PYLIST_KINDS = {
    "seed": "whole number",
    "steps": "whole number",
    "int": "whole number",
    "cfg": "number",
    "float": "number",
    "lora_strength": "LoRA strength",
}


def cast_pylist_values(raw_list: Sequence[Any], dim_type: str, dim_id: str) -> list[Any]:
    """Cast/validate a raw Python list (from a connected PYLIST socket) to
    match dim_type — the same job the string-widget parsers above do for
    typed text, just operating on already-Python-typed elements instead of
    splitting a string. Raises a clear, dimension-labeled ValueError on the
    first element that can't be cast, instead of letting a bad element
    surface as a confusing failure deep inside the sampler.

    'model' values are passed through untouched — they're expected to be
    opaque MODEL objects (e.g. assembled via List-Utils' Create PyList from
    several checkpoint loaders), not something this function can validate.
    """
    out = []
    for i, raw in enumerate(raw_list):
        try:
            if dim_type in ("text", "static"):
                out.append(str(raw))
            elif dim_type in ("seed", "steps"):
                out.append(int(raw))
            elif dim_type == "cfg":
                out.append(float(raw))
            elif dim_type == "lora_strength":
                if isinstance(raw, (list, tuple)) and len(raw) == STRENGTH_PAIR_LEN:
                    out.append((float(raw[0]), float(raw[1])))
                else:
                    v = float(raw)
                    out.append((v, v))
            elif dim_type == "model":
                out.append(raw)
            else:
                out.append(raw)
        except (ValueError, TypeError) as e:
            log.info("values_pylist item %d %r -> %s: %s", i, raw, dim_type, e)
            kind = _PYLIST_KINDS.get(dim_type, dim_type)
            raise ValueError(
                f"[Sweep Axis] '{dim_id}': item {i + 1} of the list connected to values_pylist ({raw!r}) "
                f"is not a {kind}. Connect a list of {kind}s, or disconnect values_pylist and type the values."
            ) from e
    return out


def build_combo_records(
    active_dims: Sequence[Dimension],
) -> tuple[list[ComboRecord], list[Dimension], list[list[Dimension]]]:
    """The cost-sorted cartesian product used by SweepAllInOne and
    SweepCombinationExpander. Returns (combo_records,
    active_dims_sorted, sorted_groups):

      * active_dims_sorted: active_dims sorted by chain index.
      * sorted_groups: partition_into_groups() + sort_groups() — the same
        group-aware, cost-ordered structure that is iterated.
      * combo_records: one dict per generated combination —
        {"combo_index": n, "idx_by_dim": {dim_index: value_index, ...}} —
        with EVERY active dimension's index present (zipped groupmates all
        resolve to the one shared index), in generation order. This is the
        flattened list + dimension-combination tracking object: every other
        new node (extractor, dedupe, filenames, grid/upset constructors)
        takes this as its map from "which generated image" to "which
        dimension values produced it".
    """
    active_dims_sorted = sorted(active_dims, key=lambda d: d["index"])
    groups = partition_into_groups(active_dims_sorted)
    sorted_groups = sort_groups(groups)

    combos = itertools.product(*[range(len(g[0]["values"])) for g in sorted_groups]) if sorted_groups else [()]

    combo_records = []
    for n, combo in enumerate(combos):
        idx_by_dim = {}
        for group, group_vi in zip(sorted_groups, combo, strict=True):
            for d in group:
                idx_by_dim[d["index"]] = group_vi
        combo_records.append({"combo_index": n, "idx_by_dim": idx_by_dim})

    return combo_records, active_dims_sorted, sorted_groups


def find_dim_by_id(dimensions: Sequence[Dimension], dim_id: str) -> Dimension:
    """Exact dim_id lookup shared by anything that needs to grab one
    specific dimension out of a chain by its user-facing identifier (not
    chain position) — raises a clear, available-ids-listing error on a
    miss or an ambiguous multi-match."""
    candidates = [d for d in dimensions if d["dim_id"] == dim_id]
    if not candidates:
        available = ", ".join(sorted({d["dim_id"] for d in dimensions})) or "(none)"
        raise ValueError(
            f"dim_id is '{dim_id}', but no axis has that name. Axis names in this sweep: {available}. "
            f"Set dim_id to one of them, or change the Sweep Axis's dim_id to match."
        )
    if len(candidates) > 1:
        raise ValueError(
            f"dim_id is '{dim_id}', but {len(candidates)} axes have that name. "
            f"Give each Sweep Axis its own dim_id, then set this one."
        )
    return candidates[0]


def model_file_label(model: Any) -> str | None:
    """The file name (without extension) a MODEL was loaded from, or None.
    ComfyUI's loaders (Load Checkpoint, Load Diffusion Model) record how to
    reload a model in `cached_patcher_init`, whose first argument is the
    file's path; clones (e.g. after a LoRA) keep it."""
    init = getattr(model, "cached_patcher_init", None)
    args = init[1] if isinstance(init, tuple) and len(init) > 1 else None
    path = args[0] if isinstance(args, (tuple, list)) and args else None
    if not isinstance(path, str) or not path:
        return None
    return os.path.splitext(os.path.basename(path))[0] or None


def model_labels(models: Sequence[Any], dim_id: str) -> list[str]:
    """Labels for MODEL objects: each one's file name, or dim_id + position
    (checkpoint0, checkpoint1...) when the file isn't known. The same file
    twice gets ' (2)', ' (3)'... so every value stays distinct."""
    labels: list[str] = []
    for i, m in enumerate(models):
        base = model_file_label(m) or f"{dim_id}{i}"
        label, n = base, 2
        while label in labels:
            label, n = f"{base} ({n})", n + 1
        labels.append(label)
    return labels


def axis_value(d: Dimension, vi: int) -> Any:
    """The value a downstream node receives for axis `d` at value index vi:
    the plain value; for lora_strength the model strength (use
    SweepDimensionExtract for the clip strength); for model the connected
    MODEL object (None where no MODEL was connected). A model axis fed by a
    PyList has its MODEL objects as its values."""
    if d["type"] == "lora_strength":
        return d["values"][vi][0]
    if d["type"] == "model" and "model_objs" in d:
        return d["model_objs"][vi]
    return d["values"][vi]


def axis_output_lists(
    dims_sorted: Sequence[Dimension], combo_records: Sequence[ComboRecord], count: int = MAX_AXIS_OUTPUTS
) -> list[list[Any]]:
    """One list per axis, in chain order, each with one entry per combination
    (same order as combo_records), padded with empty lists up to `count`.
    Wired into any widget socket, ComfyUI runs that node once per entry."""
    lists = [[axis_value(d, rec["idx_by_dim"][d["index"]]) for rec in combo_records] for d in dims_sorted[:count]]
    return lists + [[] for _ in range(count - len(lists))]


def live_slice(lists: Sequence[Sequence[Any]], cursor: int) -> list[list[Any]]:
    """Only combination number `cursor` of every axis list (empty lists stay
    empty): what Sweep Plan hands out while the browser runs a live sweep one
    image at a time."""
    return [[values[cursor]] if values else [] for values in lists]


def extract_values(
    dimensions: Sequence[Dimension], combo_records: Sequence[ComboRecord], dim_id: str, component: str = "value"
) -> list[Any]:
    """Pull one axis's flattened, per-combo values out of combo_records —
    the generic replacement for SweepCombinationExpander hardcoding a
    seeds/steps/cfgs/... output per axis. Matches by exact dimension
    DIM_ID (content-addressed — survives upstream reordering), not by
    chain position.

    component is only meaningful for a lora_strength-type dimension, whose
    values are (model_strength, clip_strength) tuples: 'model_strength' or
    'clip_strength' pulls out just that half, since a stock LoraLoader
    needs two separate scalar Lists, not one tuple List.
    """
    try:
        d = find_dim_by_id(dimensions, dim_id)
    except ValueError as e:
        raise ValueError(f"[Sweep Axis Value] {e}") from None

    if component != "value" and d["type"] != "lora_strength":
        raise ValueError(
            f"[Sweep Axis Value] component is '{component}', but '{dim_id}' is a {d['type']} axis: "
            f"model_strength and clip_strength only apply to a lora_strength axis. Set component to value."
        )

    out = []
    for rec in combo_records:
        vi = rec["idx_by_dim"].get(d["index"])
        if vi is None:
            log.info("combo_index %s has no index for axis %r (index %s)", rec["combo_index"], dim_id, d["index"])
            raise ValueError(
                f"[Sweep Axis Value] the combinations connected to combo don't include the axis '{dim_id}'. "
                f"Connect combo to the Sweep Plan that this axis feeds, then queue again."
            )
        val = d["model_objs"][vi] if d.get("models_from_list") else d["values"][vi]
        if component == "model_strength":
            val = val[0]
        elif component == "clip_strength":
            val = val[1]
        out.append(val)
    return out


def self_combine(
    values: Sequence[Any], mode: str, min_size: int, max_size: int | None, joiner: str
) -> tuple[list[str], list[dict]]:
    """itertools.combinations/permutations of one dimension's OWN values,
    across every size from min_size to max_size inclusive (not just one
    fixed r) — e.g. 4 styles at sizes 1-3 gives every single,
    every pair, and every triple, 14 derived values total. Returns
    (joined_values, combo_meta) where combo_meta[i] = {"arity": r,
    "members": [index,...]} — the indices are into the ORIGINAL `values`
    list, which is what the UpSet matrix constructor needs to know which
    rows to fill for each derived column.
    """
    n = len(values)
    if n == 0:
        return [], []
    max_size = n if max_size in (0, None) else min(max_size, n)
    min_size = max(1, min_size)
    if min_size > max_size:
        capped = f"; the list has only {n} values" if max_size == n else ""
        raise SweepError(
            f"[Sweep Subsets] min_size ({min_size}) is larger than max_size ({max_size}{capped}). "
            f"Set min_size to {max_size} or less.",
            f"Subsets: min_size is above max_size ({max_size}): lower min_size",
        )
    count_fn = math.perm if mode == "permutations" else math.comb
    total = sum(count_fn(n, r) for r in range(min_size, max_size + 1))
    if total > MAX_DERIVED_VALUES:
        # Counted before generating anything: 12 values as permutations is
        # ~1.3 billion strings, which would exhaust memory long before the
        # downstream >500-image warning could fire.
        fitting = [
            r
            for r in range(min_size, max_size + 1)
            if sum(count_fn(n, k) for k in range(min_size, r + 1)) <= MAX_DERIVED_VALUES
        ]
        hint = f"Set max_size to {fitting[-1]} or less." if fitting else "Use fewer values in the list."
        raise SweepError(
            f"[Sweep Subsets] {n} values as {mode} of {min_size} to {max_size} items make {total:,} subsets, "
            f"more than the limit of {MAX_DERIVED_VALUES:,}. {hint}",
            f"Subsets: {total:,} subsets (limit {MAX_DERIVED_VALUES:,}): {hint[0].lower()}{hint[1:].rstrip('.')}",
        )
    iterator_fn = itertools.permutations if mode == "permutations" else itertools.combinations

    out_values, combo_meta = [], []
    for r in range(min_size, max_size + 1):
        for idx_tuple in iterator_fn(range(n), r):
            out_values.append(joiner.join(str(values[i]) for i in idx_tuple))
            combo_meta.append({"arity": r, "members": list(idx_tuple)})
    return out_values, combo_meta


def dedupe_indices(keys: Sequence[Any]) -> tuple[list[int], list[int]]:
    """Given N hashable keys, return (unique_index_map, expand_indices):

      * unique_index_map[j] = the first original index i whose key was the
        j-th distinct key encountered (length M <= N) — these are the
        combo indices actually worth sampling.
      * expand_indices[i] = which slot 0..M-1 in a length-M result list to
        read from for original index i — feed this straight into
        SweepGather to re-expand a length-M sampled-image list back out to
        length N.

    Pure index bookkeeping — no notion of what a "key" means, so it works
    identically whether the caller built keys from sampler settings,
    filenames, or anything else hashable.
    """
    first_seen = {}
    unique_index_map = []
    expand_indices = []
    for i, k in enumerate(keys):
        if k not in first_seen:
            first_seen[k] = len(unique_index_map)
            unique_index_map.append(i)
        expand_indices.append(first_seen[k])
    return unique_index_map, expand_indices


_DEDUPE_KEY_TYPES = (str, int, float, bool)


def build_dedupe_keys(axis_value_lists: Sequence[Sequence[Any]], float_precision: int = 4) -> list[str]:
    """Build one hashable key per combo from however many axis PYLISTs are
    connected (all must be the same length). Floats are rounded to
    float_precision first so e.g. 7.5 and 7.5000000001 hash the same.

    Deliberately rejects anything that isn't a plain str/int/float/bool:
    repr()-ing an arbitrary object (a MODEL, say) would "work" without
    erroring, but silently bakes in something like a memory address —
    every key comes out unique, dedup finds nothing, and nothing tells you
    why. Raising here turns that silent-corruption risk into an immediate,
    actionable error pointing at exactly which value needs a string-key
    companion dimension instead.
    """
    if not axis_value_lists:
        raise ValueError(
            "[Sweep Skip Repeats] axis_values is empty. Connect a Create PyList that holds the lists "
            "deciding each image (for example the prompt texts, from Sweep Axis Value)."
        )
    n = len(axis_value_lists[0])
    for ai, axis in enumerate(axis_value_lists):
        if len(axis) != n:
            raise ValueError(
                f"[Sweep Skip Repeats] the lists in axis_values have different lengths: list {ai + 1} has "
                f"{len(axis)} item{'' if len(axis) == 1 else 's'}, list 1 has {n}. Connect lists with one item per combination "
                f"(straight from Sweep Axis Value), not lists that were already shortened."
            )
    keys = []
    for i in range(n):
        parts = []
        for ai, axis in enumerate(axis_value_lists):
            v = axis[i]
            if not isinstance(v, _DEDUPE_KEY_TYPES):
                log.info("axis_values list %d item %d is a %s, not str/int/float/bool", ai + 1, i, type(v).__name__)
                raise ValueError(
                    f"[Sweep Skip Repeats] list {ai + 1} in axis_values holds models or other objects, which "
                    f"can't be compared directly. Pair a text axis holding the file names with that axis "
                    f"(Sweep Pair Axes), and connect the text axis's values instead."
                )
            if isinstance(v, float):
                v = round(v, float_precision)
            parts.append(repr(v))
        keys.append("|".join(parts))
    return keys


def gather(source: Sequence[Any], indices: Sequence[Any]) -> list[Any]:
    """result[i] = source[indices[i]] — generic enough to be useful well
    beyond this node pack (it's the piece List-Utils itself doesn't have).
    Used twice in a dedup workflow: once to shrink a full axis list down to
    just the unique combos worth sampling, once more to re-expand the
    sampled results back out to the original length."""
    n = len(source)
    out = []
    for i in indices:
        # bool is a subclass of int (True == 1), so check it explicitly.
        if isinstance(i, bool) or not isinstance(i, int):
            raise ValueError(
                f"[Sweep Gather] indices must hold positions (whole numbers), but it holds {i!r}. "
                f"Connect Sweep Skip Repeats' unique_index_map or expand_indices to indices."
            )
        if i < 0 or i >= n:
            have = f"only {n} items (positions 0 to {n - 1})" if n else "no items"
            raise ValueError(
                f"[Sweep Gather] indices asks for position {i}, but source has {have}. Connect indices "
                f"from the Sweep Skip Repeats that worked on this same list."
            )
        out.append(source[i])
    return out


def build_filenames(
    active_dims: Sequence[Dimension],
    combo_records: Sequence[ComboRecord],
    filename_prefix: str,
    include_combo_index: bool,
) -> list[str]:
    """One relative path per combo (forward slashes, no extension), for a
    stock SaveImage's filename_prefix List, paired index-for-index with
    the images.

    - filename_prefix is always the top folder (sanitized), so SaveImage
      writes under <output>/<prefix>/ without needing a trailing '/'.
    - text/static values become subfolders, except a self-combined
      dimension (has 'combo_meta'): its values are unique per combo, so a
      folder each would group nothing. Other values go into the filename.
    - Values that aren't str/int/float/bool (e.g. MODEL objects) appear as
      label + value index, never str(obj), which would embed a memory
      address that changes every run.
    - include_combo_index prefixes a zero-padded running number, which
      keeps every filename unique whatever dimensions are present.
    """
    n = len(combo_records)
    idx_width = max(4, len(str(max(n - 1, 0))))
    prefix_folder = safe_component(filename_prefix) if str(filename_prefix).strip() else "SweepKit"
    out = []
    for rec in combo_records:
        idx_by_dim = rec["idx_by_dim"]
        folder_parts, name_parts = [], []
        for d in active_dims:
            vi = idx_by_dim.get(d["index"])
            if vi is None:
                continue
            val = d["values"][vi]
            dtype = d["type"]
            if dtype in ("text", "static"):
                comp = safe_component(val)
                if "combo_meta" not in d:
                    folder_parts.append(comp)
                name_parts.append(comp)
            elif isinstance(val, (str, int, float, bool)):
                shown = f"{val:g}" if isinstance(val, float) else str(val)
                name_parts.append(f"{safe_component(d['dim_id'])}{shown}")
            elif isinstance(val, (list, tuple)) and len(val) == STRENGTH_PAIR_LEN:
                # lora_strength-style (model_strength, clip_strength)
                sm = val[0]
                name_parts.append(f"{safe_component(d['dim_id'])}{sm:g}")
            else:
                name_parts.append(f"{safe_component(d['dim_id'])}{vi}")
        base = "_".join(name_parts) if name_parts else "image"
        if include_combo_index:
            base = f"{str(rec['combo_index']).zfill(idx_width)}_{base}"
        rel = os.path.join(prefix_folder, *folder_parts, base)
        if len(rel) > MAX_NAME_LEN:
            rel = rel[:TRUNCATED_NAME_LEN] + f"_{rec['combo_index']}"
        out.append(rel.replace(os.sep, "/"))
    return out


def next_versioned_path(directory: str, base_filename: str, ext: str = ".png") -> str:
    """Find the next available 5-digit auto-incrementing path for
    base_filename in directory — {base}_00001{ext}, {base}_00002{ext},
    ... — matching stock SaveImage's own counter convention, so reruns of
    SweepGridConstructor/SweepUpsetConstructor (which save files directly
    rather than delegating to SaveImage) never silently overwrite a
    previous grid/matrix the way a fixed filename would. Scans the
    directory once for existing files matching base_filename and takes
    max+1, rather than probing candidate paths one at a time, so this
    stays fast even after many prior runs.
    """
    os.makedirs(directory, exist_ok=True)
    pattern = re.compile(r"^" + re.escape(base_filename) + r"_(\d+)" + re.escape(ext) + r"$")
    max_counter = 0
    # No try/except: if the directory can't be listed, restarting the
    # counter at _00001 could silently overwrite an earlier file.
    for fname in os.listdir(directory):
        m = pattern.match(fname)
        if m:
            max_counter = max(max_counter, int(m.group(1)))
    return os.path.join(directory, f"{base_filename}_{max_counter + 1:05d}{ext}")


def write_manifest(
    directory: str,
    dims_sorted: Sequence[Dimension],
    combo_records: Sequence[ComboRecord],
    files: Sequence[str | None],
) -> str:
    """Write sweep_manifest_NNNNN.csv into `directory`: one row per run with
    its number, the saved file (relative to `directory`, blank if none) and
    the value of every axis. Makes a sweep easy to reproduce and to load into
    a spreadsheet or script. Never overwrites an earlier manifest."""
    headers: list[str] = []
    for d in dims_sorted:
        name, n = d["dim_id"], 2
        while name in headers:  # two axes with the same name stay distinguishable
            name, n = f"{d['dim_id']}_{n}", n + 1
        headers.append(name)
    path = next_versioned_path(directory, "sweep_manifest", ".csv")
    with open(path, "w", newline="", encoding="utf-8") as fh:
        out = csv.writer(fh)
        out.writerow(["run", "file", *headers])
        for rec, file in zip(combo_records, files, strict=True):
            rel = os.path.relpath(file, directory).replace(os.sep, "/") if file else ""
            values = [format_dim_value(d, rec["idx_by_dim"][d["index"]]) for d in dims_sorted]
            out.writerow([rec["combo_index"] + 1, rel, *values])
    return path


def ui_images(paths: Sequence[str], output_dir: str) -> list[dict[str, str]]:
    """ComfyUI 'ui' image entries for files saved under output_dir, so the
    node shows its saved grids/matrices the way SaveImage does."""
    out = []
    root = os.path.abspath(output_dir)
    for p in paths:
        rel = os.path.relpath(os.path.abspath(p), root)
        out.append({"filename": os.path.basename(rel), "subfolder": os.path.dirname(rel), "type": "output"})
    return out
