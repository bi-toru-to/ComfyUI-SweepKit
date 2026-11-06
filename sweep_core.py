"""
Shared constants and pure helper functions for the SweepKit node pack
(SweepDimension + SweepAllInOne). Deliberately import-light — no torch,
no comfy — so this module (and therefore the parsing/grid-axis logic that
matters most) can be unit tested with plain `python3 sweep_core.py`
style imports, without needing a ComfyUI/torch environment at all.
"""

import re
import os
import itertools

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


def safe_component(s):
    """Sanitize a string for use as a folder or filename component."""
    s = re.sub(r"[^\w\-. ]", "_", str(s)).strip().strip(".")
    s = s[:80]
    return s if s else "_"


def parse_text_list(raw):
    """One value per line — newline only. Unlike the numeric parsers
    below, commas are NOT treated as a separator here, since a single
    text value legitimately contains them (e.g. a comma-separated tag
    list meant to fill one {} as a whole: 'masterpiece, highres, 1girl').
    Splitting on commas would shred that into three separate values."""
    if raw is None or not str(raw).strip():
        return []
    return [line.strip() for line in str(raw).split("\n") if line.strip()]


def parse_number_list(raw, cast, dim_id, allow_range=False):
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
        if allow_range and re.fullmatch(r"-?\d+\s*-\s*-?\d+", line):
            a, b = line.split("-")
            a, b = int(a), int(b)
            step = 1 if b >= a else -1
            out.extend(range(a, b + step, step))
            continue
        try:
            out.append(cast(line))
        except ValueError:
            raise ValueError(f"[SweepKit] Dimension '{dim_id}': could not parse value '{line}' as {cast.__name__}.")
    return out


def parse_lora_strength_list(raw, dim_id):
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
                f"[SweepKit] Dimension '{dim_id}': could not parse "
                f"lora strength '{line}' (expected a number, or 'model:clip')."
            )
    return out or [(1.0, 1.0)]


def format_dim_value(d, vi):
    """Nicely format a single dimension's value at index vi. lora_strength
    stores (model_strength, clip_strength) tuples -- shown as one number
    if they're equal, 'model/clip' if not, rather than Python's raw tuple
    repr ('(0.5, 0.5)'), which is what grid axis labels used to show
    verbatim. Other float values (e.g. cfg) get the same trailing-zero
    trimming so '1' and '1.0' don't show up side by side inconsistently."""
    val = d["values"][vi]
    if d["type"] == "lora_strength":
        sm, sc = val
        return f"{sm:g}" if sm == sc else f"{sm:g}/{sc:g}"
    if isinstance(val, float):
        return f"{val:g}"
    return str(val)


def dim_group_members(d, active_dims):
    """Every dimension sharing d's group id (including d itself), or just
    [d] if it isn't grouped. Used so a zipped pair/triple's displayed
    value reflects ALL of what's actually varying together, not just
    whichever single member happened to be picked to represent the group
    for axis/title purposes."""
    gid = d.get("group")
    if not gid:
        return [d]
    return [o for o in active_dims if o.get("group") == gid]


def format_group_value(group, vi):
    """Combined display value for a (possibly multi-member) group at the
    shared index vi -- e.g. '0.5, 15, 2' for a zipped lora_strength+steps+
    cfg triple, matching the combined 'label1, label2, label3' the group
    already carries."""
    return ", ".join(format_dim_value(d, vi) for d in group)


def resize_dimension_values(dim, new_length):
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


def partition_into_groups(active_dims):
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


def group_cost_rank(group):
    """A group's cost is however expensive its most expensive member is —
    e.g. a lora_strength dimension zipped with a cfg dimension should
    still be treated as outer-loop-expensive, since changing the group's
    index changes the lora too, not just the cfg."""
    return min(COST_RANK.get(d["type"], 5) for d in group)


def sort_groups(groups):
    return sorted(groups, key=lambda g: (group_cost_rank(g), min(d["index"] for d in g)))


def resolve_group_index(d, full_idx, active_dims):
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


def resolve_grid_axes(active_dims, grid_x_dim, grid_y_dim, grid_title_dim):
    """Map the user's grid_x_dim / grid_y_dim / grid_title_dim widget
    selections (tokens like 'auto', 'none', 'dim3') onto actual dimension
    dicts, filling in sensible defaults for anything left unresolved.

    Returns (x_dim, y_dim, title_dim, other_dims) where other_dims is every
    remaining active dimension — each combination of THOSE produces its own
    separate grid image, so no data from a 3rd/4th/... dimension is ever
    silently dropped.

    Group-aware: dimensions zipped together by SweepDimensionZip share a
    'group' id and always move in lockstep, so at most ONE member of a
    group is ever picked to represent it — as X, Y, Title, or a grouping
    axis. Picking a second member for a different role would just repeat
    the same pairing as an independent axis and produce a grid full of
    empty cells off the (forced) diagonal, so it's avoided by construction
    rather than left as a trap.

    Auto-fill order is X, then Y, then TITLE LAST -- title only ever takes
    a dimension nothing else needed. This maximizes the chance a 2-axis
    sweep lands as one single-image XY grid: with exactly 2 independent
    axes, X and Y between them claim both, and title finds nothing left
    to take regardless of whether it was left on 'auto' or explicitly set
    to 'none'. X and Y both defer text/static-type dimensions where a
    non-text alternative exists (falling back to text/static only if
    that's genuinely all that's left), so a 3+-axis sweep still tends to
    land a text dimension on the title instead of accidentally landing it
    on Y just because title used to run first.

    Auto-fill triggers whenever a role is still unresolved and the user
    didn't explicitly ask for 'none' -- this deliberately includes an
    EXPLICIT-but-conflicting token (e.g. picking the non-representative
    half of an already-claimed zipped pair for Y), not just a bare 'auto'.
    Otherwise a conflicting explicit pick would strand that role
    permanently empty and force its dimension into other_dims (silently
    multiplying the grid count) even in cases where 'auto' would have
    happily recovered by picking something else instead -- the two should
    behave the same when the specific pick didn't pan out.
    """
    by_token = {f"dim{d['index']}": d for d in active_dims}
    used_indices = set()
    used_groups = set()

    def claim(d):
        used_indices.add(d["index"])
        if d.get("group"):
            used_groups.add(d["group"])

    def available(d):
        if d["index"] in used_indices:
            return False
        if d.get("group") and d["group"] in used_groups:
            return False
        return True

    def explicit(token, role_name):
        if token in ("auto", "none"):
            return None
        d = by_token.get(token)
        if d is None:
            print(
                f"[SweepAllInOne] grid_{role_name}_dim '{token}' doesn't match any active dimension — falling back to auto-selection for {role_name}."
            )
            return None
        if not available(d):
            reason = (
                "its group is already used by another grid axis"
                if d.get("group") in used_groups
                else "it's already used by another grid axis"
            )
            print(
                f"[SweepAllInOne] grid_{role_name}_dim '{token}' ('{d['dim_id']}') can't be used here — {reason}. Falling back to auto-selection for {role_name}."
            )
            return None
        claim(d)
        return d

    x_dim = explicit(grid_x_dim, "x")
    y_dim = explicit(grid_y_dim, "y")
    title_dim = explicit(grid_title_dim, "title")

    if grid_x_dim != "none" and x_dim is None:
        x_dim = next((d for d in active_dims if d["type"] == "seed" and available(d)), None)
        if x_dim is None:
            x_dim = next((d for d in active_dims if d["type"] not in ("text", "static") and available(d)), None)
        if x_dim is None:
            x_dim = next((d for d in active_dims if available(d)), None)
        if x_dim:
            claim(x_dim)

    if grid_y_dim != "none" and y_dim is None:
        y_dim = next((d for d in active_dims if d["type"] not in ("text", "static") and available(d)), None)
        if y_dim is None:
            y_dim = next((d for d in active_dims if available(d)), None)
        if y_dim:
            claim(y_dim)

    if grid_title_dim != "none" and title_dim is None:
        title_dim = next((d for d in active_dims if available(d)), None)
        if title_dim:
            claim(title_dim)

    other_dims = []
    seen_other_groups = set()
    for d in active_dims:
        if not available(d):
            continue
        gid = d.get("group")
        if gid:
            if gid in seen_other_groups:
                continue
            seen_other_groups.add(gid)
        other_dims.append(d)

    return x_dim, y_dim, title_dim, other_dims


def cast_pylist_values(raw_list, dim_type, dim_id):
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
                if isinstance(raw, (list, tuple)) and len(raw) == 2:
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
            )
    return out


def build_combo_records(active_dims):
    """The cost-sorted cartesian product, extracted from what used to be
    inline in SweepAllInOne.generate(). Returns (combo_records,
    active_dims_sorted, sorted_groups):

      * active_dims_sorted: active_dims sorted by chain index.
      * sorted_groups: partition_into_groups() + sort_groups() — the same
        group-aware, cost-ordered structure the old inline loop iterated.
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
        for group, group_vi in zip(sorted_groups, combo):
            for d in group:
                idx_by_dim[d["index"]] = group_vi
        combo_records.append({"combo_index": n, "idx_by_dim": idx_by_dim})

    return combo_records, active_dims_sorted, sorted_groups


def find_dim_by_id(dimensions, dim_id):
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


def extract_values(dimensions, combo_records, dim_id, component="value"):
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
        raise ValueError(f"[SweepDimensionExtract] {e}")

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


def self_combine(values, mode, min_size, max_size, joiner):
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
    iterator_fn = itertools.permutations if mode == "permutations" else itertools.combinations

    out_values, combo_meta = [], []
    for r in range(min_size, max_size + 1):
        for idx_tuple in iterator_fn(range(n), r):
            out_values.append(joiner.join(str(values[i]) for i in idx_tuple))
            combo_meta.append({"arity": r, "members": list(idx_tuple)})
    return out_values, combo_meta


def dedupe_indices(keys):
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


def build_dedupe_keys(axis_value_lists, float_precision=4):
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


def gather(source, indices):
    """result[i] = source[indices[i]] — generic enough to be useful well
    beyond this node pack (it's the piece List-Utils itself doesn't have).
    Used twice in a dedup workflow: once to shrink a full axis list down to
    just the unique combos worth sampling, once more to re-expand the
    sampled results back out to the original length."""
    n = len(source)
    out = []
    for i in indices:
        if not isinstance(i, int) or i < 0 or i >= n:
            raise ValueError(
                f"[SweepGather] index {i!r} out of range for source of length {n} (valid range 0..{n - 1})."
            )
        out.append(source[i])
    return out


def build_filenames(active_dims, combo_records, filename_prefix, include_combo_index):
    """One filename (relative path, no extension, forward-slash separated)
    per combo record — feeds a stock SaveImage's filename_prefix as a List,
    paired index-for-index against the also-Listed images. Text/static
    dimensions become subfolders; everything else becomes a filename
    suffix component.

    filename_prefix is ALWAYS the leading folder component of the
    returned path (sanitized via safe_component, so a value containing
    '/' or other unsafe characters can't produce a malformed path) — it
    used to only take effect as a folder if the caller manually typed a
    trailing '/' into the widget, and even then got concatenated straight
    into what was supposed to be a bare filename, producing a stray
    leading underscore. Making it unconditionally a real path component
    fixes both: SaveImage now reliably creates an <output>/<filename_prefix>/
    folder by default, with no widget gymnastics required.

    A dimension produced by SweepDimensionSelfCombine (flagged by the
    'combo_meta' key SweepDimensionSelfCombine attaches) does NOT become a
    subfolder even though its dim_type is still 'text' — every one of its
    derived values is unique per combo by construction (no two combos
    ever share one), so folder-per-value would put every single image in
    its own folder instead of grouping anything. It still contributes to
    the filename itself, same as before.

    Values that aren't a plain str/int/float/bool (an opaque MODEL object
    from a values_pylist-fed 'model' dimension, say) fall back to a stable
    POSITIONAL tag (label + value-index) rather than str()-ing the object,
    which would bake a memory address into the filename and change on
    every run.

    include_combo_index prefixes a zero-padded running number, which is
    what guarantees every filename is unique — this replaces the old
    save_individual's special-cased "no seed dimension -> append _seedN"
    hack with one mechanism that works regardless of which dimensions are
    actually present.
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
            elif isinstance(val, (list, tuple)) and len(val) == 2:
                # lora_strength-style (model_strength, clip_strength)
                sm = val[0]
                name_parts.append(f"{safe_component(d['dim_id'])}{sm:g}")
            else:
                name_parts.append(f"{safe_component(d['dim_id'])}{vi}")
        base = "_".join(name_parts) if name_parts else "image"
        if include_combo_index:
            base = f"{str(rec['combo_index']).zfill(idx_width)}_{base}"
        rel = os.path.join(prefix_folder, *folder_parts, base)
        if len(rel) > 220:
            rel = rel[:200] + f"_{rec['combo_index']}"
        out.append(rel.replace(os.sep, "/"))
    return out


def truncate_text_to_width(text, font, max_width, draw):
    """Pixel-width-aware truncation (with ellipsis), as opposed to a fixed
    character count — the available space for a label is generous and
    content-dependent (see the grid/matrix constructors), so a fixed char
    count would either waste the extra room or still overflow it
    depending on content and font_size. Shared by SweepGridConstructor and
    SweepUpsetConstructor so their label handling can't drift apart."""
    text = str(text)
    if max_width <= 0:
        return ""
    if draw.textbbox((0, 0), text, font=font)[2] <= max_width:
        return text
    while text and draw.textbbox((0, 0), text + "…", font=font)[2] > max_width:
        text = text[:-1]
    return (text + "…") if text else "…"


def wrap_text_to_width(text, font, max_width, draw, max_lines=4):
    """Word-wrap text onto multiple lines, each fitting within max_width
    (measured in real pixels via draw.textbbox, not a fixed character
    count), truncating the last line with an ellipsis if it still doesn't
    fit within max_lines. Shared by SweepGridConstructor and
    SweepUpsetConstructor so their label handling can't drift apart."""
    words = str(text).split(" ")
    lines, cur = [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if draw.textbbox((0, 0), trial, font=font)[2] <= max_width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = truncate_text_to_width(lines[-1], font, max_width, draw)
    return lines


def next_versioned_path(directory, base_filename, ext=".png"):
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
    try:
        for fname in os.listdir(directory):
            m = pattern.match(fname)
            if m:
                max_counter = max(max_counter, int(m.group(1)))
    except OSError:
        pass
    return os.path.join(directory, f"{base_filename}_{max_counter + 1:05d}{ext}")


def font_size_for_char_width(target_char_width_px, sample_px=200):
    """Given a target average-character pixel width, return the find_font()
    pixel size that achieves it -- measured against whatever font
    find_font() actually resolves to (rather than assuming a fixed
    width/size ratio), so the mapping stays correct across whatever font
    is actually available in a given environment. Used to size grid/matrix
    text relative to the ACTUAL rendered cell width rather than a fixed
    pixel count, so cell_mode='original' (whose real cell size can differ
    wildly from the nominal cell_size widget) doesn't end up with text
    that's disproportionately tiny or huge next to the images.
    """
    from PIL import Image, ImageDraw

    sample_font = find_font(sample_px)
    scratch = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    sample_text = "AaMg0Wx1"
    w = scratch.textbbox((0, 0), sample_text, font=sample_font)[2]
    ratio = (w / len(sample_text)) / sample_px if w > 0 else 0.6
    if ratio <= 0:
        ratio = 0.6
    return max(6, round(target_char_width_px / ratio))


def find_font(size):
    from PIL import ImageFont

    candidates = [
        "arial.ttf",
        "Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "C:\\Windows\\Fonts\\arial.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()
