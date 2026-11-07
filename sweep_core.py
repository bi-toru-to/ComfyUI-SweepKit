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
import math
import os
import re
from typing import Any, Callable, Iterable, Sequence, TypedDict


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

# How many "dimN" tokens the main node's grid_x_dim/grid_y_dim/grid_title_dim
# pickers offer. This is just the size of that dropdown's option list — it
# does NOT cap how many SweepDimension nodes you can actually chain (that's
# unlimited now that dimensions arrive as a plain list through a socket
# instead of being pre-declared widget slots). Dimensions beyond this count
# still work fine; they just can't be explicitly hand-picked as X/Y/Title
# and fall back to being automatic grouping axes (or covered by "auto").
GRID_AXIS_PICKER_RANGE = 12
GRID_AXIS_OPTIONS = ["auto", "none"] + [f"dim{i}" for i in range(1, GRID_AXIS_PICKER_RANGE + 1)]

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
                raise ValueError(
                    f"[SweepDimension] '{dim_id}': range '{line}' has {abs(b - a) + 1:,} values, "
                    f"over the limit of {MAX_DERIVED_VALUES:,}."
                )
            step = 1 if b >= a else -1
            out.extend(range(a, b + step, step))
            continue
        try:
            out.append(cast(line))
        except ValueError:
            raise ValueError(
                f"[SweepDimension] '{dim_id}': could not parse value '{line}' as {cast.__name__}."
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
            raise ValueError(
                f"[SweepDimension] '{dim_id}': could not parse "
                f"lora strength '{line}' (expected a number, or 'model:clip')."
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
    node_tag: str = "SweepAllInOne",
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
        self.by_token = {f"dim{d['index']}": d for d in active_dims}
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
        """The dimension an explicit 'dimN' token names, if it can take
        this role; None (with a printed reason) if it can't."""
        if token in ("auto", "none"):
            return None
        d = self.by_token.get(token)
        if d is None:
            reason = "doesn't match any active dimension"
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
            raise ValueError(
                f"[SweepDimension] '{dim_id}': values_pylist element {i} ({raw!r}) can't be cast to {dim_type} — {e}"
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
        raise ValueError(f"no dimension with dim_id '{dim_id}' — available dim_ids: {available}")
    if len(candidates) > 1:
        raise ValueError(
            f"'{dim_id}' matches {len(candidates)} dimensions — dim_ids must be unique to look up by dim_id."
        )
    return candidates[0]


def axis_value(d: Dimension, vi: int) -> Any:
    """The value a downstream node receives for axis `d` at value index vi:
    the plain value; for lora_strength the model strength (use
    SweepDimensionExtract for the clip strength); for model the connected
    MODEL object (None where no MODEL was connected)."""
    if d["type"] == "lora_strength":
        return d["values"][vi][0]
    if d["type"] == "model":
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
        raise ValueError(f"[SweepDimensionExtract] {e}") from None

    if component != "value" and d["type"] != "lora_strength":
        raise ValueError(
            f"[SweepDimensionExtract] component='{component}' only applies to a "
            f"lora_strength-type dimension — '{dim_id}' is '{d['type']}'."
        )

    out = []
    for rec in combo_records:
        vi = rec["idx_by_dim"].get(d["index"])
        if vi is None:
            raise KeyError(
                f"[SweepDimensionExtract] combo_index {rec['combo_index']} has no resolved "
                f"index for dimension '{dim_id}' — combo_records looks malformed/from a "
                f"mismatched SweepCombinationExpander run."
            )
        val = d["values"][vi]
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
    fixed r) — e.g. 4 artist styles at sizes 1-3 gives every single,
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
        raise ValueError(
            f"[SweepDimensionSelfCombine] min_size ({min_size}) > effective max_size "
            f"({max_size}) for {n} base value(s)."
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
        hint = f" max_size={fitting[-1]} fits." if fitting else " Use fewer base values."
        raise ValueError(
            f"[SweepDimensionSelfCombine] {n} base value(s) as {mode} of sizes {min_size}-{max_size} would "
            f"produce {total:,} derived values, over the limit of {MAX_DERIVED_VALUES:,}.{hint}"
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
        raise ValueError("[SweepDedupeCombos] no axes connected — nothing to dedupe on.")
    n = len(axis_value_lists[0])
    for ai, axis in enumerate(axis_value_lists):
        if len(axis) != n:
            raise ValueError(
                f"[SweepDedupeCombos] axis {ai} has length {len(axis)}, expected {n} "
                f"(every connected axis must be the same length as combo_records)."
            )
    keys = []
    for i in range(n):
        parts = []
        for axis in axis_value_lists:
            v = axis[i]
            if not isinstance(v, _DEDUPE_KEY_TYPES):
                raise ValueError(
                    f"[SweepDedupeCombos] value at index {i} ({v!r}, type {type(v).__name__}) "
                    f"isn't a plain str/int/float/bool — dedup can't hash arbitrary objects "
                    f"like MODEL/CLIP reliably. Zip a string-key companion dimension (e.g. "
                    f"'model_key') alongside it and connect that instead."
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
        if isinstance(i, bool) or not isinstance(i, int) or i < 0 or i >= n:
            raise ValueError(
                f"[SweepGather] index {i!r} out of range for source of length {n} (valid range 0..{n - 1})."
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
