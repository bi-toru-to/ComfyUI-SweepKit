# SweepKit — Node Guide

A reference for every node in this pack: what it does, what each socket and
setting means, and step-by-step wiring for common workflows.

For *why* the pack is built this way, see `DESIGN.md`. This document is
the "how do I actually use it" companion.

## Two ways to use this pack

**The all-in-one node (`SweepAllInOne`)** does everything in one place —
sampling, encoding, LoRA application, grid building, and saving. It's the
fastest way to get a sweep running, but any tweak (even just the grid's
`cell_size`) reruns the entire sweep from scratch, since it's all one
Python function.

**The modular pipeline** (`SweepCombinationExpander`,
`SweepDimensionExtract`, and friends) spreads the same job across several
small nodes wired up to *stock* ComfyUI nodes (`KSampler`, `LoraLoader`,
`CLIPTextEncode`, `SaveImage`) and to
[godmt/ComfyUI-List-Utils](https://github.com/godmt/ComfyUI-List-Utils).
It takes more nodes to set up, but each piece caches independently — tweak
a grid setting and only the grid rebuilds, sampling stays cached — and any
step can be swapped for a different extension's node (a different
LoRA-stack node, a different text-replace node, etc.) without touching the
rest.

Both share the same `SweepDimension` / `SweepDimensionZip` /
`SweepDimensionSelfCombine` nodes for describing *what* to sweep — they
just differ in what consumes that description afterward.

**This pack requires [godmt/ComfyUI-List-Utils](https://github.com/godmt/ComfyUI-List-Utils)
for the modular pipeline** — install it the same way you installed this
pack (ComfyUI Manager, or clone into `custom_nodes/`). The all-in-one node
doesn't need it.

---

## Before you start: three concepts used everywhere

### The dimension chain (`SWEEP_DIMS`)

Every sweep starts as a chain of `SweepDimension` nodes, each describing
one axis (seed, steps, cfg, a text substitution, a LoRA strength, a model
choice...). Each node takes the previous node's output as its
`prev_dimensions` input and passes everything-plus-itself onward as its
`dimensions` output — the same daisy-chain pattern as a LoRA-stacker node.
The *last* node in the chain is what you connect onward, whether that's
into `SweepAllInOne` directly or into `SweepCombinationExpander` for the
modular path.

### `PYLIST` vs. a native ComfyUI `List`

Every modular node in this pack that isn't building the dimension chain
itself works with List-Utils' `PYLIST` type — one socket holding one whole
Python list, passed around as a single value, with random access. This is
different from ComfyUI's own list-processing (`OUTPUT_IS_LIST`), where a
socket holds *one item at a time* and the executor automatically re-runs
the downstream node once per item (this is what makes a stock `KSampler`
sample every combination when you feed it a list of seeds, with zero
special handling on `KSampler`'s part).

You'll cross this boundary constantly:

- **`PYLIST` → `List`**: use List-Utils' **PyList To List** node, right
  before a socket on a *stock* node (`KSampler.seed`, `LoraLoader.strength_model`,
  `SaveImage.filename_prefix`, ...) that needs to receive one value per
  combination.
- **`List` → `PYLIST`**: use List-Utils' **List To PyList** node — you'll
  need this after `VAEDecode`, since `SweepGridConstructor` and
  `SweepUpsetConstructor` need the *whole* image list at once (to build a
  grid/matrix), not one image at a time.

If a socket in this pack is typed `PYLIST` (grey/generic-looking), it
wants a `PYLIST`, not a raw `List` — connecting a `List` output directly
usually still "connects" in the graph but silently multiplies execution
in a way you don't want, since ComfyUI would try to map-execute the
receiving node once per list item. When in doubt: `PYLIST` in, `PYLIST`
out, and only convert to `List` right at a stock node's doorstep.

### `combo` — the tracking object

`SweepCombinationExpander` turns your dimension chain into a flat list of
generated combinations, bundled with the map back from "which generated
image" to "which dimension values produced it" — one `combo` object,
carrying both the resolved dimension chain and one record per
combination. Every node downstream of the expander
(`SweepDimensionExtract`, `SweepFilenameSequencer`, `SweepGridConstructor`,
`SweepUpsetConstructor`) takes this one `combo` socket, rather than the
dimensions and the per-combo records separately — they're always needed
together, so there's nothing to gain from wiring two connections instead
of one, and a mismatched pair (e.g. accidentally connecting `combo` from
a different `SweepCombinationExpander` instance than the images actually
came from) isn't something that can happen if there's only one socket to
begin with. You never need to open it up or construct one yourself — just
pass it along.

---

## Node reference

### SweepDimension

One axis of a sweep. Chain several of these together to build up a
sweep with multiple axes.

**Inputs**

| Socket | Type | Meaning |
|---|---|---|
| `dim_type` | dropdown | What this axis varies and how `values` gets parsed. See the dim_type table below. |
| `dim_id` | STRING | Identifies this axis — grid titles/filenames use it for display, and the modular pipeline (`SweepDimensionExtract`, `SweepUpsetConstructor`) looks dimensions up by matching this *exactly*. **Give it a real value if you're using the modular pipeline** — it defaults to `dim_type` if left blank, which is fine for the all-in-one node but will collide with any other same-typed dimension's default in the modular pipeline (two blank-`dim_id` `cfg` dimensions can't both default to `"cfg"` and still be told apart — you'd get an "ambiguous, matches 2 dimensions" error the moment something tries to extract by that name). |
| `values` | STRING (multiline) | The values for this axis, one per line. Numeric types (`seed`/`steps`/`cfg`/`int`/`float`/`lora_strength`) also split on commas; `text`/`static`/`model` split on newlines only, so a comma-separated tag list stays one value. For `seed`/`steps`/`int` you can also write a range like `1-5` (negative bounds work too: `-3-2`, `-5--1`). For `dim_type = model`, this is a list of *socket labels* instead of values — editing it adds/removes MODEL input sockets below (see Notes). Ignored if `values_pylist` is connected. |
| `lora_name` | dropdown | Only used when `dim_type = lora_strength` — which LoRA file's strength `values` sweeps over. **Only consumed by `SweepAllInOne`'s own internal LoRA application** — the modular pipeline ignores this field entirely; pick the LoRA file on the stock `LoraLoader` node's own `lora_name` widget instead (this axis just supplies the numeric strengths via `SweepDimensionExtract`'s `model_strength`/`clip_strength` component, see the LoRA-stacking workflow below). |
| `prev_dimensions` *(optional)* | SWEEP_DIMS | Connect the previous `SweepDimension` (or `SweepDimensionZip`/`SweepDimensionSelfCombine`) in the chain. Leave unconnected if this is the first axis. |
| `values_pylist` *(optional)* | PYLIST | Connect a PyList (e.g. from List-Utils' **Create PyList**, **Split String**, **Create Linspace**, or **List Dir**) to override the `values` widget entirely. Elements are cast to match `dim_type`, raising a clear error if they can't be (e.g. a non-numeric string into a `cfg`/`float` axis). For `dim_type = model`, elements are passed through untouched — this is how you feed real `MODEL` objects in directly, see the model-list workflow below. |

**`dim_type` options**

| Value | Casts as | Notes |
|---|---|---|
| `text` | string | Fills the next `{}` in `SweepAllInOne`'s `positive_prompt`, counting only `text`-type dimensions in chain order (`static` dimensions never fill a placeholder). In the modular pipeline, feed it into a text-replace node instead. |
| `int` | int (range like `1-5` OK) | Generic integer axis, no special behavior beyond casting. Use this for anything numeric that isn't literally the sampler's own seed/steps (e.g. a batch-variant index). |
| `float` | float | Generic float axis, no special behavior beyond casting. Use this for anything numeric that isn't literally the sampler's own cfg — e.g. a LoRA strength, so you're not selecting an option literally called "cfg" for an axis that has nothing to do with cfg. |
| `seed` | int (range OK) | Casts identically to `int`, but is *also* recognized by `SweepAllInOne`'s `fixed_seed` fallback and by `grid_x_dim=auto`'s seed-preference. Use this specifically when the axis IS the sampler's seed. |
| `steps` | int (range OK) | Casts identically to `int`, also recognized by `SweepAllInOne`'s `fixed_steps` fallback. Use when the axis IS the sampler's steps. |
| `cfg` | float | Casts identically to `float`, also recognized by `SweepAllInOne`'s `fixed_cfg` fallback. Use when the axis IS the sampler's cfg. |
| `lora_strength` | (model_strength, clip_strength) pair | Paired tuple, tied to the `lora_name` widget — see the note above about this only mattering for `SweepAllInOne`. Chain several to sweep several LoRAs at once: `SweepAllInOne` stacks them, applying each in chain order. In the modular pipeline, workflow 3 below uses two independent `float` dimensions zipped together instead, which avoids this dim_type's unused `lora_name` field entirely. |
| `model` | passthrough (or dynamic MODEL sockets) | Turns `values` into a label list and spawns one MODEL input socket per label (at most 24; extra labels are ignored with a console warning) — unless `values_pylist` is connected, in which case elements are used as-is (real MODEL objects) and the dynamic sockets are skipped. |
| `static` | string, truncated to 1 value | A fixed, non-swept single value — only the *first* line of `values` is kept no matter how many you type. Still participates in grid titles/filenames/folders exactly like `text` does, but does **not** fill a `{}` placeholder in `SweepAllInOne`'s prompt. Use this to tag a whole sweep with something constant (e.g. a batch/session label) without wiring it into the prompt at all, and without it ever multiplying your combination count. |

**Outputs**

| Socket | Type | Meaning |
|---|---|---|
| `dimensions` | SWEEP_DIMS | This axis plus everything upstream of it. Connect onward. |

**Notes**

- If `dim_type = model` and `values_pylist` is *not* connected, editing
  `values` (one socket-label per line) dynamically adds/removes `MODEL`
  input sockets below the node — connect one checkpoint/model per line.
  This is the original mechanism from before the modular pipeline existed;
  it still works for the all-in-one node.
- If `values` (or `values_pylist`) ends up empty, this axis is silently
  skipped (with a console warning) rather than breaking the chain.

---

### SweepDimensionZip

Pairs the **last** dimension of two chains so they vary together
index-for-index, instead of being cross-produced. Use this when two axes
are correlated — e.g. a Turbo/Lightning LoRA wants far fewer steps and a
much lower cfg than the base model, and you want `(lora=0.0, steps=30,
cfg=4.5)` and `(lora=1.0, steps=8, cfg=1.0)`, not all four combinations of
lora × steps × cfg.

**Inputs**

| Socket | Type | Meaning |
|---|---|---|
| `dimensions_a` | SWEEP_DIMS | A chain — its **last** dimension is the one that gets paired. |
| `dimensions_b` | SWEEP_DIMS | A second chain — its **last** dimension is paired index-for-index with `dimensions_a`'s last dimension. |
| `mode` | dropdown | `shortest`: stop at the shorter list (extra values on the longer side are dropped, with a console warning) — like Python's `zip()`. `longest`: pad the shorter list by repeating its own last value — like `itertools.zip_longest()`. `strict`: raise an error if the two lists don't have the same length. |

**Outputs**

| Socket | Type | Meaning |
|---|---|---|
| `dimensions` | SWEEP_DIMS | Both paired dimensions plus everything else from both input chains, ready to continue chaining (into another `SweepDimension`, into a second `SweepDimensionZip` to pair in a third axis, or straight into the next node). |

**Notes**

- Each paired dimension **keeps its own individual `dim_id`** — so
  `SweepDimensionExtract` can still pull `lora_model_strength` and
  `lora_clip_strength` out separately afterward. A combined display
  string (`"lora_model_strength, lora_clip_strength"`) is generated
  automatically for grid/page titles, but that's a separate internal
  field, not something that overwrites either axis's own identity.
- Zipping a zip's output into a third dimension composes correctly — all
  three end up sharing one group and one combined title string, while
  each keeps pulling its own values independently.
- Any *other* dimensions earlier in either input chain pass through
  unchanged and stay independent (still cross-producted normally against
  everything else) — only the two tail dimensions actually get paired.
  If both inputs branch off the same upstream chain (e.g. `artist → cfg`
  and `artist → steps`), the shared `artist` dimension is kept once, not
  twice. Connecting the same chain to both inputs is an error.

---

### SweepDimensionSelfCombine

Recombines **one dimension's own values** against themselves — every
combination (or permutation) from `min_size` up to `max_size` elements at
once, not just one fixed size. This is the node for "try every pairing of
these style tags," "try every subset of these LoRAs," etc. — see the
combinations workflow below for the full walkthrough.

**Inputs**

| Socket | Type | Meaning |
|---|---|---|
| `dimensions` | SWEEP_DIMS | A chain — its **last** dimension is the one that gets recombined against itself and replaced by the derived result. |
| `mode` | dropdown | `combinations`: order doesn't matter, no repeats within a combo (`"cyberpunk, noir"` only, never also `"noir, cyberpunk"`). `permutations`: order matters too — use this if word order actually changes your output (it often does for prompts, since early tokens carry more weight), at the cost of a much faster-growing result count. |
| `min_size` | INT (default 1) | Smallest combo size to include. `1` also emits every base value on its own. |
| `max_size` | INT (default 0) | Largest combo size to include. `0` means "use every base value" (the full-size combo). |
| `joiner` | STRING (default `", "`) | String used to join a combo's member values into one derived value. |

**Outputs**

| Socket | Type | Meaning |
|---|---|---|
| `dimensions` | SWEEP_DIMS | The chain with its last dimension replaced by the derived, recombined one. |

**Notes**

- Can't be used on a dimension that's already zipped (`SweepDimensionZip`)
  — self-combine *before* zipping, not after, since which values a zipped
  pair's shared index should recombine against would be ambiguous.
- The derived dimension's `dim_id` becomes `"<original dim_id> (<mode>)"`
  — use *that* value (not the original) when extracting or selecting it
  later, e.g. in `SweepUpsetConstructor`'s `dim_id`.
- Growth is fast: 8 base values at sizes 1–3 is 8+28+56 = 92 combinations
  under `combinations` mode, or 8+56+336 = 400 under `permutations` mode.
  Check `combo_count` from `SweepCombinationExpander` before sampling a
  large sweep.

---

### SweepCombinationExpander

The spine of the modular pipeline. Turns a finished dimension chain into
the flattened combination list and the tracking object every other
modular node consumes. Doesn't sample anything itself.

**Inputs**

| Socket | Type | Meaning |
|---|---|---|
| `dimensions` | SWEEP_DIMS | The end of your dimension chain. |

**Outputs**

| Socket | Type | Meaning |
|---|---|---|
| `combo` | SWEEP_COMBO | Dimensions (sorted into execution order — cost-sorted, expensive axes like model swaps outermost, cheap ones like seed innermost) plus one record per combination, bundled together. Pass this to every other modular node that asks for `combo`. |
| `combo_count` | INT | Total number of combinations. Prints a console warning past 500. |
| `dim_map` | STRING | Human-readable `dim1='...', dim2='...', ...` listing, matching what's printed to console — wire into a text-preview node if you want to see which chain position each dimension landed at without checking console output (needed for `SweepGridConstructor`'s `grid_x_dim`/`grid_y_dim`/`grid_title_dim` pickers, which select by position). |

**Notes**

- Deliberately does *not* output per-axis values (no `seeds`, `steps`,
  `cfgs` sockets) — that would need a fixed output for every dim_id anyone
  might ever use. Use `SweepDimensionExtract` once per axis you actually
  need instead.

---

### SweepDimensionExtract

Pulls one axis's flattened, per-combination values out of `combo` — the
generic building block for feeding a specific sampler/loader parameter.
Use one instance per axis you need downstream.

**Inputs**

| Socket | Type | Meaning |
|---|---|---|
| `combo` | SWEEP_COMBO | Connect `SweepCombinationExpander`'s `combo` output. |
| `dim_id` | STRING | Exact `dim_id` of the dimension to extract. Must match exactly one dimension. |
| `component` | dropdown | Only meaningful for a `lora_strength`-type dimension, whose values are `(model_strength, clip_strength)` pairs: `value` (the raw pair), `model_strength`, or `clip_strength` to pull out just that half as a plain number. Leave on `value` for every other `dim_type`. |

**Outputs**

| Socket | Type | Meaning |
|---|---|---|
| `values` | PYLIST | One value per combination, in the same order as `combo`'s records. Feed through List-Utils' **PyList To List** before connecting to a stock node's per-item input. |

**Notes**

- Matches by exact `dim_id`, not by chain position — reordering or
  inserting `SweepDimension` nodes upstream won't silently repoint an
  extractor at the wrong axis, but two dimensions accidentally sharing one
  `dim_id` will raise an "ambiguous" error instead of guessing.

---

### SweepDedupeCombos

Finds combinations whose sampling-relevant settings are identical (a
`lighting` axis whose placeholder isn't actually referenced in the
prompt template, say, so every value resolves to the same text) so they
only get sampled once. See the dedup workflow below for the full pattern.

**Inputs**

| Socket | Type | Meaning |
|---|---|---|
| `axis_values` | PYLIST | A PyList of PyLists — one entry per axis you want to dedupe on, each itself a length-N list of `str`/`int`/`float`/`bool` values. Bundle them with List-Utils' **Create PyList** node (connect each axis's `SweepDimensionExtract` output, or a `positive_texts` PyList, into its own dynamic input slot). |
| `float_precision` | INT (default 4) | Floats are rounded to this many decimal places before comparing, so `7.5` and `7.5000000001` count as the same setting. |

**Outputs**

| Socket | Type | Meaning |
|---|---|---|
| `unique_index_map` | PYLIST[int] | Length M (≤ N) — for each distinct setting, the first original combo index that had it. These are the *only* combos worth actually sampling. |
| `expand_indices` | PYLIST[int] | Length N — for each original combo, which slot `0..M-1` of a length-M sampled result to read from. Feed straight into `SweepGather` to re-expand back to the full length. |
| `unique_count` | INT | M — how many combos actually need sampling. |

**Notes**

- Only catches *exact* duplication of the values you connect — it has no
  way to know two differently-worded settings mean the same thing (e.g.
  `lora_name="none"` vs. a real LoRA at strength `0.0`). Normalize
  upstream if that matters to you.
- Rejects anything that isn't a plain `str`/`int`/`float`/`bool` with a
  clear error, rather than silently hashing an arbitrary object's Python
  identity (which would never actually dedupe anything, without telling
  you why). If you need to dedupe on a `model`/`lora` axis, zip a plain
  string "key" companion dimension alongside it and connect that instead
  of the object itself.

---

### SweepGather

`result[i] = source[indices[i]]` — reads a whole new list's worth of
elements out of `source`, in whatever order (including repeats)
`indices` specifies. Used twice in a dedup workflow: once to shrink an
axis list down to just the unique combos worth sampling, once more to
re-expand a sampled result list back out to the original length.

**Inputs**

| Socket | Type | Meaning |
|---|---|---|
| `source` | PYLIST | The list to read from. |
| `indices` | PYLIST | Integer indices into `source`. Out-of-range indices raise an error immediately, rather than clamping or wrapping silently. |

**Outputs**

| Socket | Type | Meaning |
|---|---|---|
| `result` | PYLIST | Length = `len(indices)`. `result[i] = source[indices[i]]`. |

---

### SweepFilenameSequencer

Builds one filename per combination, ready to pair against a stock
`SaveImage` node.

**Inputs**

| Socket | Type | Meaning |
|---|---|---|
| `combo` | SWEEP_COMBO | Connect `SweepCombinationExpander`'s `combo` output. |
| `filename_prefix` | STRING (default `SweepKit`) | Top-level output folder for every saved file — always a real folder, unconditionally (blank falls back to `SweepKit` rather than saving loose in the output root). |
| `include_combo_index` | BOOLEAN (default True) | Prefixes a zero-padded running number. This is what guarantees every filename is unique regardless of which dimensions are active — turn it off only if you're building filenames some other way and know they'll already be unique. |

**Outputs**

| Socket | Type | Meaning |
|---|---|---|
| `filenames` | PYLIST[str] | One filename per combination (relative path, no extension, forward-slash separated — `filename_prefix` is the first path segment, then text/static dimensions become further subfolders). Feed through List-Utils' **PyList To List**, then into a stock `SaveImage` node's `filename_prefix` — paired index-for-index against your also-Listed `images`. |

**Notes**

- Always produces exactly as many filenames as there are combination
  records, even if `SweepDedupeCombos` + `SweepGather` means several point
  at byte-identical images — dedup saves sampling time, not file count.
- A dimension produced by `SweepDimensionSelfCombine` does **not** become
  a subfolder, even though it's still `dim_type=text` — its values are
  unique per combination by construction (no two combinations ever share
  one), so folder-per-value would put every single image in its own
  folder instead of grouping anything. It still contributes to the
  filename itself.
- A dimension whose values aren't plain `str`/`int`/`float`/`bool` (an
  opaque `MODEL` object from a `values_pylist`-fed `model` dimension, say)
  falls back to a stable positional tag (`checkpoint0`, `checkpoint1`,
  ...) rather than trying to stringify the object, which would bake a
  memory address into the filename and change on every run.

---

### SweepGridConstructor

Builds X/Y/Title grids from an already-sampled image list. This is the
modular pipeline's equivalent of the all-in-one node's built-in grid
building, decoupled from sampling so tweaking a grid setting doesn't
rerun the sampler.

**Inputs**

| Socket | Type | Meaning |
|---|---|---|
| `images` | PYLIST | One image tensor per combination, same order as `combo`'s records. Connect via List-Utils' **List To PyList**, fed from `VAEDecode`'s `IMAGE` List output. |
| `combo` | SWEEP_COMBO | Connect `SweepCombinationExpander`'s `combo` output. |
| `filename_prefix` | STRING (default `SweepKit`) | Top-level output folder for every saved grid file — always a real folder, unconditionally (blank falls back to `SweepKit`). |
| `cell_size` | INT (default 512) | Meaning depends on `cell_mode` (see below). |
| `cell_mode` | dropdown | `fit`: scale each image to `cell_size` preserving aspect ratio (recommended). `square`: stretch to a `cell_size`×`cell_size` square (may distort non-square images). `original`: no resizing at all (sharpest, but the grid can get very large). |
| `font_size` | FLOAT (default 0.4) | Text size as a fraction of the *actual rendered* cell width, not the `cell_size` widget — `1.0` means one character is about 1/16 of a cell's width. Sized off the real cell width specifically so `cell_mode='original'` (whose real size can differ a lot from `cell_size`) doesn't end up with text that's disproportionately tiny or huge next to the images. Matches `SweepUpsetConstructor`'s font hierarchy: title stays the most prominent, X-axis (column) labels sit at the base size, Y-axis (row) labels get a slight emphasis over the base — all four (title/X/Y/spacing) scale together so the relative proportions and the gaps between them stay consistent at every setting. Long labels word-wrap to fit their own column/row rather than overflowing into the image or a neighboring label. |
| `grid_x_dim` | dropdown (`auto`/`none`/`dim1`...`dim12`) | Which dimension (by chain position) is the grid's X axis. `auto` prefers a `seed`-type dimension. `none` = single column. |
| `grid_y_dim` | dropdown | Which dimension is the Y axis. `auto` prefers a non-text/static dimension. `none` = single row. |
| `grid_title_dim` | dropdown | Which dimension's value becomes the grid's title and top output folder. `auto` takes whatever's left after X and Y. **Any dimension not assigned to X/Y/Title still produces its own set of extra grids** in nested folders — nothing is silently dropped. |

**Outputs**

| Socket | Type | Meaning |
|---|---|---|
| `grids` | IMAGE | All built grid images, batched. |
| `summary` | STRING | How many grids were built, where they were saved, and a `dim1='...', dim2='...'` position map (see Notes). |

**How X/Y/Title get picked (read this if a sweep doesn't grid the way you expect)**

Auto-fill order is **X, then Y, then Title last** — title only ever takes
a dimension nothing else needed. With exactly 2 independent axes, X and Y
between them always claim both, and title is left with nothing to take —
so **a 2-axis sweep reliably lands as one single-image grid**, regardless
of whether X/Y are left on `auto` or set to explicit `dimN` tokens, and
regardless of how many literal `SweepDimension` entries those 2 logical
axes span (a zipped pair still counts as *one* logical axis). X prefers a
`seed`-type dimension; both X and Y prefer to skip text/static-type
dimensions where a non-text alternative exists, deferring text for a
likely title claim, but will take a text/static dimension rather than
stay empty if that's genuinely all that's left.

This auto-fill also runs whenever a role ends up unresolved for *any*
reason short of you explicitly setting it to `none` — including picking
the non-representative half of an already-zipped pair for a role. If you
set `grid_y_dim` to the *other* member of a pair already claimed by X, Y
doesn't just stay empty; it falls back to whatever else is available,
the same as if it had been left on `auto`.

**Notes**

- `images` must be a `PYLIST`, not a single batched `IMAGE` tensor —
  per-combination images aren't guaranteed to share one resolution the
  way a real batch tensor requires.
- `grid_x_dim`/`grid_y_dim`/`grid_title_dim` pick dimensions by chain
  **position** (`dim1`, `dim2`, ...), not by `dim_id` — this is a
  different lookup convention from `SweepDimensionExtract`'s exact-match
  one, intentionally: it's a dropdown picker, so a fixed positional list
  is simpler than requiring exact-string matches. Check
  `SweepCombinationExpander`'s `dim_map` output (or this node's own
  `summary` output, which includes the same mapping) to see which
  position each dimension landed at.
- A zipped pair only ever fills *one* of X/Y/Title/grouping-axis role —
  picking the second member for a different role would just repeat the
  same pairing as if it were independent, so it's avoided by construction
  (with the auto-recovery described above, rather than left broken).
- Every saved grid gets a 5-digit auto-incrementing counter appended
  (`grid_00001.png`, `grid_00002.png`, ...), matching stock `SaveImage`'s
  own convention — rerunning this node never overwrites a previous grid.
  This node saves files directly (it isn't going through `SaveImage`), so
  it has to provide that guarantee itself rather than getting it for free.

---

### SweepUpsetConstructor

Visualizes one `SweepDimensionSelfCombine` axis as an UpSet-style
membership matrix: one column per combination, the actual generated image
as that column's swatch, and a dot-matrix below marking which base
elements the combination contains, with a connecting line joining them,
plus a thin horizontal guide line per row to make a wide matrix easy to
trace by eye. See the combinations workflow below for the full walkthrough
and what this actually looks like.

**Inputs**

| Socket | Type | Meaning |
|---|---|---|
| `images` | PYLIST | One image tensor per combination, same order as `combo`'s records. Connect via List-Utils' **List To PyList**. |
| `combo` | SWEEP_COMBO | Connect `SweepCombinationExpander`'s `combo` output. |
| `dim_id` | STRING | `dim_id` of the `SweepDimensionSelfCombine`-produced dimension to visualize — remember it became `"<original dim_id> (<mode>)"` after self-combining. |
| `filename_prefix` | STRING (default `SweepKit`) | Top-level output folder for every saved matrix file — always a real folder, unconditionally (blank falls back to `SweepKit`). |
| `cell_size` | INT (default 120) | Target swatch size per column — exact meaning depends on `cell_mode`. |
| `cell_mode` | dropdown | Same meaning as `SweepGridConstructor`'s: `fit` (recommended), `square`, or `original`. |
| `font_size` | FLOAT (default 1.0) | Same meaning as `SweepGridConstructor`'s — a fraction of the *actual rendered* swatch width, `1.0` ≈ one character per 1/16 of a swatch's width. Title, row-label, and column-label sizes stay proportionally distinct from each other at every setting; row-to-row and title/header spacing all scale along with the text so nothing collides at large font sizes or large `cell_mode='original'` images. |
| `title_dim` | dropdown (`none`/`dim1`...`dim12`) | Which OTHER (non-target) dimension's value leads the matrix title, if set. Every other non-target dimension still page-splits normally regardless of this setting — it only reorders which one reads first in the title text. |
| `max_columns_per_page` | INT (default 60) | Safety valve for very large combo counts — splits into multiple numbered matrix files past this many columns, rather than one enormous image. |

**Outputs**

| Socket | Type | Meaning |
|---|---|---|
| `matrices` | IMAGE | All built matrix images, batched. |
| `summary` | STRING | How many matrix images were built, for how many combinations/base values, where, and a `dim1='...', dim2='...'` position map (for `title_dim`'s picker). |

**Notes**

- Scoped to exactly one self-combine axis's own structure. Any *other*
  independent dimension in the graph (sweeping `cfg` alongside artist
  combos, say) is handled the same way `SweepGridConstructor` handles
  leftover axes — as a page split, producing one matrix per combination
  of the other axes, never crammed into the same matrix.
- Rejects a `dim_id` that doesn't point at an `SweepDimensionSelfCombine`-
  produced dimension with a clear error (rather than silently drawing an
  empty/wrong matrix).
- Column labels wrap onto multiple horizontal lines, constrained to each
  column's own width — long combo text (`"cyberpunk, noir, pastel"`)
  breaks onto a second/third line instead of overflowing into the next
  column.
- Row labels are left-aligned and sized to the actual longest label,
  capped at roughly 1.5× a cell's width — most realistic labels display
  in full; only something that would still exceed that generous cap gets
  an ellipsis, measured in real pixels rather than a fixed character
  count.
- Every saved matrix gets a 5-digit auto-incrementing counter appended
  (`matrix_00001.png`, `matrix_00002.png`, ...), matching stock
  `SaveImage`'s own convention — rerunning this node never overwrites a
  previous matrix. This node saves files directly (it isn't going through
  `SaveImage`), so it has to provide that guarantee itself rather than
  getting it for free.

---

### SweepAllInOne (all-in-one)

The original single-node sweep generator. Everything below is unique to
this node — none of it applies to the modular pipeline.

**Inputs**

| Socket | Type | Meaning |
|---|---|---|
| `model` | MODEL | Base model. Used for any combination that doesn't have a `model`-type dimension active. |
| `clip` | CLIP | Base CLIP. |
| `vae` | VAE | For decoding sampled latents to images. |
| `positive_prompt` | STRING (multiline) | The first of two unlabeled text boxes (ComfyUI doesn't title multiline widgets — same as `CLIPTextEncode`). Each `{}` (or regex match, see `text_mode`) is filled left to right by your `text`-type `SweepDimension` nodes, in chain order: the 1st text dimension fills the leftmost placeholder. Placeholders beyond the number of text dimensions are left unchanged. |
| `negative_prompt` | STRING (multiline) | The second text box, directly below positive. Fixed — does not vary across the sweep. |
| `latent_image` | LATENT | Starting latent for every sample. |
| `text_mode` | dropdown (`curly`/`regex`) | `curly`: substitute `{}` placeholders in order. `regex`: substitute matches of `text_regex` instead, also left to right. |
| `text_regex` | STRING (default `\{\}`) | Only used when `text_mode = regex`. An invalid pattern stops the run with a clear error before anything is sampled. |
| `fixed_seed` | INT (default 1) | Used only when no `seed`-type `SweepDimension` is chained in. |
| `fixed_steps` | INT (default 35) | Used only when no `steps`-type `SweepDimension` is chained in. |
| `fixed_cfg` | FLOAT (default 4.5) | Used only when no `cfg`-type `SweepDimension` is chained in. |
| `sampler_name` / `scheduler` / `denoise` | — | Standard KSampler settings, fixed across the whole sweep. |
| `filename_prefix` | STRING (default `SweepKit`) | Top-level output folder for every saved file — always a real folder, unconditionally (blank falls back to `SweepKit`). |
| `save_individuals` | BOOLEAN (default True) | Save each sampled image individually, in addition to any grids. |
| `create_grids` | BOOLEAN (default True) | Build and save X/Y/Title grids. |
| `cell_size` / `cell_mode` | — | Same meaning as `SweepGridConstructor`'s, above. |
| `grid_x_dim` / `grid_y_dim` / `grid_title_dim` | — | Same meaning as `SweepGridConstructor`'s, above — including the same X→Y→Title auto-fill order and 2-axis-sweep single-grid guarantee. |
| `dimensions` *(optional)* | SWEEP_DIMS | Connect the end of an `SweepDimension` chain. Leave unconnected for a single fixed-parameter generation with no sweep at all. |

**Outputs**

| Socket | Type | Meaning |
|---|---|---|
| `grids` | IMAGE | All built grid images, batched (or one plain image if `create_grids` is off). |
| `summary` | STRING | How many images were generated and where everything was saved. |

**Notes**

- Chain at most **one** `seed`, `steps`, `cfg` and `model` dimension each:
  every image can only use one value of each, so a second one stops the run
  with a clear error before anything is sampled. Use a generic `int`/`float`
  dimension for numbers that aren't this node's own sampler settings.
- Any number of `lora_strength` dimensions can be chained; they stack, each
  applying its own LoRA in chain order.
- Folder and file names are sanitized: characters other than letters,
  digits, `-`, `_`, `.` and spaces become `_`, and Windows device names
  (`CON`, `NUL`, `AUX`, `COM1`…) get a leading `_` (e.g. `filename_prefix =
  NUL` saves under `_NUL/`).

---

## Workflow examples

Each example gives the exact node-by-node setup. "Add" means drag a new
node onto the canvas (search its name); "connect" means drag from an
output socket to the matching input socket.

### 1. Quickest start — the all-in-one node

Good for a first sweep or anything simple. No List-Utils needed.

1. Add a **Load Checkpoint**, connect `MODEL`/`CLIP`/`VAE` to a new
   **SweepAllInOne** node's `model`/`clip`/`vae` inputs.
2. Add an **Empty Latent Image**, connect its `LATENT` output to
   `latent_image`.
3. On `SweepAllInOne`, type your prompt into `positive_prompt` with one
   `{}` per thing you want to sweep as text, and fill in `negative_prompt`.
4. Add an **SweepDimension** node. Set `dim_type` to `seed`, `values` to
   `1,2,3`. Leave `prev_dimensions` unconnected (it's first).
5. Add a second **SweepDimension**. Set `dim_type` to `cfg`, `values` to
   `4,7,10`. Connect the *first* `SweepDimension`'s `dimensions` output
   into this one's `prev_dimensions` input.
6. Connect the second `SweepDimension`'s `dimensions` output into
   `SweepAllInOne`'s `dimensions` input.
7. Queue the prompt. You'll get 9 images (3 seeds × 3 cfgs) and one 3×3
   grid (seed × cfg — 2 independent axes reliably land as one grid),
   saved under `output/SweepKit/`.

### 2. Modular basics — cartesian sweep through stock KSampler + SaveImage

The same 3×3 seed/cfg sweep as above, but wired through stock nodes so
each step caches independently.

1. Add **Load Checkpoint**, **CLIPTextEncode** ×2 (positive/negative, wire
   up normally), **Empty Latent Image**, **KSampler**, **VAEDecode** — a
   completely ordinary base workflow, not yet touching anything from this
   pack.
2. Add an **SweepDimension**: `dim_type=seed`, `dim_id=seed`,
   `values=1,2,3`.
3. Add a second **SweepDimension**: `dim_type=cfg`, `dim_id=cfg`,
   `values=4,7,10`. Connect the first node's `dimensions` output into this
   one's `prev_dimensions`.
4. Add an **SweepCombinationExpander**. Connect the second
   `SweepDimension`'s `dimensions` output into its `dimensions` input.
5. Add two **SweepDimensionExtract** nodes. On both, connect
   `SweepCombinationExpander`'s `combo` output to `combo`. On the first,
   set `dim_id` to `seed`; on the second, set `dim_id` to `cfg`.
6. Add two **PyList To List** nodes (List-Utils). Connect each
   `SweepDimensionExtract`'s `values` output into one.
7. Connect the seed `PyList To List`'s output into `KSampler`'s `seed`
   input, and the cfg one into `KSampler`'s `cfg` input. Connect
   `KSampler`'s other inputs (`model`, `positive`, `negative`,
   `latent_image`) normally, from your base workflow.
8. Connect `KSampler`'s `LATENT` output into `VAEDecode` as usual.
9. Add an **SweepFilenameSequencer**. Connect `SweepCombinationExpander`'s
   `combo` output to its `combo` input. Set `filename_prefix`.
10. Add a **PyList To List** node, connect `SweepFilenameSequencer`'s
    `filenames` output into it.
11. Add a stock **SaveImage** node. Connect `VAEDecode`'s `IMAGE` output
    **directly** into `SaveImage`'s `images` — it's already a native
    per-item `List` (the list-ness propagated from `KSampler`'s `LATENT`
    List all the way through `VAEDecode`), the same length as your
    filenames list, so no `List To PyList`/`PyList To List` conversion is
    needed for this connection at all. Connect the `PyList To List` node
    from step 10 into `SaveImage`'s `filename_prefix`.
12. (Optional, for a grid too) Add a **List To PyList** node and connect
    `VAEDecode`'s `IMAGE` output into it as well — one output socket can
    feed both `SaveImage` and this conversion node. Add an
    **SweepGridConstructor**, connect this new `List To PyList` node's
    output to its `images`, and `SweepCombinationExpander`'s `combo`
    output to its `combo` input. Set `grid_x_dim`/`grid_y_dim` or leave on
    `auto` — with just these 2 axes it'll come out as one grid either way.
13. Queue the prompt. `KSampler` runs 9 times automatically (ComfyUI's
    executor loops it once per list item since it received `List`-typed
    seed/cfg inputs) — nothing in this pack tells it to.

### 3. Zipping two axes for LoRA stacking through a stock LoraLoader

Sweep 5 paired `(model_strength, clip_strength)` values through a real
`LoraLoader`, crossed against 3 independent cfg values (15 images, not
25).

1. Build the same base workflow as example 2, but insert a stock
   **LoraLoader** between `Load Checkpoint` and `CLIPTextEncode`/`KSampler`
   (its `model`/`clip` outputs feed those instead of the checkpoint's
   directly). Pick a `lora_name` on it as usual.
2. Add an **SweepDimension**: `dim_type=float`, `dim_id=lora_model_strength`,
   `values=0.2,0.4,0.6,0.8,1.0`. (`float`, not `cfg` — this axis isn't
   actually cfg, it just needs the same numeric casting; `cfg` specifically
   means "this is the sampler's own cfg parameter", which would be
   misleading to pick here.)
3. Add a second **SweepDimension**: `dim_type=float`,
   `dim_id=lora_clip_strength`, `values=0.3,0.5,0.6,0.7,0.9`. Leave
   `prev_dimensions` unconnected on this one too (don't chain it to the
   first — it goes into the zip node separately).
4. Add an **SweepDimensionZip**. Connect the first `SweepDimension`'s
   `dimensions` output to `dimensions_a`, the second's to `dimensions_b`.
   Set `mode` to `shortest` (both lists are already length 5, so it won't
   matter here).
5. Add a third **SweepDimension**: `dim_type=cfg`, `dim_id=cfg`,
   `values=4,7,10` — this one really is the sampler's cfg, so `cfg` is the
   right dim_type here. Connect `SweepDimensionZip`'s `dimensions` output
   into this one's `prev_dimensions`.
6. Add an **SweepCombinationExpander**, connect the third
   `SweepDimension`'s `dimensions` output into it. Its `combo_count`
   should read 15 (5 zipped pairs × 3 independent cfgs) — if it reads 45,
   something upstream got connected as independent instead of zipped.
7. Add two **SweepDimensionExtract** nodes (`dim_id=lora_model_strength`
   and `dim_id=lora_clip_strength`) plus **PyList To List** nodes, same
   pattern as example 2. Connect their outputs into `LoraLoader`'s
   `strength_model` and `strength_clip` respectively.
8. Add a third **SweepDimensionExtract** (`dim_id=cfg`) → **PyList To
   List** → `KSampler.cfg`.
9. Wire seed/sampling/saving the same way as example 2 (seed can stay a
   plain fixed widget on `KSampler` if you don't need it swept too). With
   2 logical axes (the zipped pair counts as one, cfg is the other) across
   3 `SweepDimension` entries, `SweepGridConstructor` on default `auto`
   settings still comes out as one grid.
10. Queue the prompt. `LoraLoader` runs once per combination just like
    `KSampler` does — nothing in this pack applies the LoRA itself.

### 4. Artist-style combinations + UpSet matrix

Try every single style, every pair, and every triple from a list of 4
artist styles (14 combinations total), see the result as an UpSet matrix.

1. Add a **CLIPTextEncode**, `KSampler`, `VAEDecode` base workflow as in
   example 2 (positive text will come from a substitution step instead of
   being typed directly into `CLIPTextEncode`).
2. Add an **SweepDimension**: `dim_type=text`, `dim_id=artist_style`,
   `values` = one style per line, e.g.:
   ```
   cyberpunk
   noir
   pastel
   vintage
   ```
3. Add an **SweepDimensionSelfCombine**. Connect the `SweepDimension`'s
   `dimensions` output into it. Set `mode=combinations`, `min_size=1`,
   `max_size=3`, `joiner=", "`.
4. Add an **SweepCombinationExpander**, connect the self-combine node's
   `dimensions` output into it. `combo_count` should read 14 (4 + 6 + 4).
5. Add an **SweepDimensionExtract**. Connect `combo` from the expander.
   Set `dim_id` to `artist_style (combinations)` — note the suffix
   self-combine added to the original `dim_id`.
6. Add a text find-and-replace node (any generic one — e.g.
   "Text Find & Replace" from another node pack; List-Utils doesn't ship
   its own). Connect step 5's `values` through a **PyList To List** node
   into its "find/replace value" input. Set it to replace a marker like
   `__artist__` in a template string, e.g.
   `"masterpiece, __artist__ style, 4k"`.
7. Connect that node's output into `CLIPTextEncode`'s `text` input.
8. Wire `KSampler` → `VAEDecode` → **List To PyList** as in example 2.
9. Add an **SweepUpsetConstructor**. Connect the step-8 `List To PyList`
   output to `images`, the expander's `combo` output to `combo`, and set
   `dim_id` to `artist_style (combinations)` (same value as step 5). Leave
   `cell_size`/`cell_mode`/`title_dim`/`max_columns_per_page` on their
   defaults.
10. Queue the prompt. You'll get one matrix image: 14 columns (grouped
    into "Arity 1 (4)" / "Arity 2 (6)" / "Arity 3 (4)" bands), each
    column's real generated image as its swatch, and a dot-matrix below
    showing exactly which artist styles that column combines, with a
    guide line per row so a wide matrix stays easy to trace by eye.
11. (Optional) Add an **SweepFilenameSequencer** + **SweepGridConstructor**
    the same way as example 2/3 if you also want the 14 images saved
    individually and/or as a plain grid alongside the matrix.

For `permutations` instead (order-sensitive — useful if word order
changes your output), just change `mode` on `SweepDimensionSelfCombine`
to `permutations`; nothing else in the graph needs to change. Watch the
count: the same 4 styles at sizes 1–3 grow from 14 combinations to 4 + 12
+ 24 = 40 permutations.

If you're also sweeping something else alongside the combinations (say
`cfg`), `SweepUpsetConstructor`'s `title_dim` lets you pick which extra
axis's value leads the matrix title — it doesn't change how many matrix
images you get (every other axis still page-splits regardless), just
which one reads first.

### 5. Saving compute with Dedupe + Gather

For when one axis doesn't actually affect the output for some combinations
— e.g. sweeping `background` × `lighting`, but your prompt template only
ever references `__background__`, so every `lighting` value for a given
background would otherwise resample an identical image.

1. Build dimensions/expander/extraction/text-substitution as in example 4
   (two independent `text`-type dimensions, `background` and `lighting`,
   *not* zipped — you want the full 3×3 cross product of combinations,
   the dedup step is what avoids wasting samples on the ones that turn
   out identical).
2. After building your `positive_texts` PyList (from the text-substitute
   step), add a List-Utils **Create PyList** node. Connect
   `positive_texts` into its first dynamic input slot (add more slots if
   you're deduping on more than one axis — e.g. also connect a `cfg`
   `SweepDimensionExtract` output into a second slot).
3. Add an **SweepDedupeCombos**. Connect the **Create PyList** node's
   output into `axis_values`. Leave `float_precision` on its default.
4. Add an **SweepGather**. Connect `positive_texts` into `source`, and
   `SweepDedupeCombos`'s `unique_index_map` into `indices`. This shrinks
   your text list down to just the unique prompts worth sampling.
5. Feed this shrunk list through **PyList To List** into `CLIPTextEncode`
   as normal — `KSampler`/`VAEDecode` now only run `unique_count` times
   instead of the full combination count.
6. Add a **List To PyList** node after `VAEDecode` (as in example 2) to
   collect the smaller sampled-image list back into one PyList.
7. Add a second **SweepGather**. Connect the step-6 output into `source`,
   and `SweepDedupeCombos`'s `expand_indices` into `indices`. This
   re-expands the smaller sampled set back out to the full combination
   count — duplicate combos now point at the same already-sampled image.
8. Feed this re-expanded, full-length image list into
   `SweepFilenameSequencer`/`SweepGridConstructor` exactly as in example
   2 — they don't need to know dedup happened at all.

### 6. Assembling a model list without dynamic sockets

Sweep across 3 checkpoints using List-Utils' own list-building node
instead of `SweepDimension`'s dynamic MODEL-socket mechanism.

1. Add three **Load Checkpoint** nodes, one per model you want to sweep.
2. Add a List-Utils **Create PyList** node. Connect each checkpoint's
   `MODEL` output into one of its dynamic input slots (it grows a new
   slot each time you fill the last one).
3. Add an **SweepDimension**: `dim_type=model`, `dim_id=checkpoint`. Leave
   `values` blank. Connect the **Create PyList** node's output into this
   node's `values_pylist` input.
4. Continue the chain/expander/extraction as usual — an
   **SweepDimensionExtract** with `dim_id=checkpoint` gives you a `PYLIST`
   of real `MODEL` objects, one per combination, ready for **PyList To
   List** straight into `KSampler`'s `model` input (or a `LoraLoader`'s,
   if you're also sweeping LoRAs).
5. If you're also building filenames for this sweep,
   `SweepFilenameSequencer` can't put a real `MODEL` object's contents
   into a filename (there's nothing meaningful to show) — it falls back
   to a stable `checkpoint0`/`checkpoint1`/`checkpoint2`-style positional
   tag automatically, so filenames stay unique without needing anything
   extra from you.

---

## Troubleshooting

**"no dimension with dim_id 'X' — available dim_ids: ..."** — An
`SweepDimensionExtract` or `SweepUpsetConstructor`'s `dim_id` doesn't
exactly match any dimension's `dim_id`. Check for typos, and remember
`SweepDimensionSelfCombine` appends `" (mode)"` to the `dim_id` it
consumes.

**"'X' matches N dimensions — dim_ids must be unique..."** — Two or more
`SweepDimension` nodes have the same `dim_id`. Give them distinct values.

**"images has N entries but combo has M combo_records..."** — Something
between `SweepCombinationExpander` and `SweepGridConstructor`/
`SweepUpsetConstructor` changed the image list's length without keeping
`combo` in sync (usually a dedup/gather step wired up only partway —
check that both `SweepGather` calls, shrink and re-expand, are actually
in the graph if you're using dedup).

**"dedup can't hash arbitrary objects like MODEL/CLIP reliably"** — You
connected a `model`/`lora`/other opaque-object axis directly into
`SweepDedupeCombos`. Zip a plain string "key" dimension alongside it
(e.g. the checkpoint filename as text) and connect that instead.

**A 2-axis sweep is coming out as more than one grid** — Check whether
`grid_title_dim` is set to an explicit `dimN` token rather than `auto` or
`none` — an explicit title pick is honored even when it means splitting a
2-axis sweep into multiple grids, since you asked for that dimension
specifically. Leave `grid_title_dim` on `auto` (or set it to `none`) if
you want the "2 independent axes always come out as one grid" default.

**A grid's title text looks fine but the grid picked the "wrong" X/Y
axis** — `grid_x_dim`/`grid_y_dim`/`grid_title_dim` pick by chain
position (`dim1`, `dim2`, ...), not by `dim_id`. Check
`SweepCombinationExpander`'s `dim_map` output (or the constructor node's
own `summary` output) to see each dimension's position.

**Nothing happens when I connect a List-Utils "Split String" output
straight into `SweepDimension`'s `values_pylist`** — Check which of its
two outputs you used. `values_pylist` wants the `PYLIST` output, not the
`STRING` (List) one — connecting the `List` output would make ComfyUI try
to re-run `SweepDimension` once per line instead of treating the whole
list as one dimension's values.
