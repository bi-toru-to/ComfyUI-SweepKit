# SweepKit — Design Notes (v3: split-node architecture)

## Why this changed shape

The first working version of this node pack was a single mega-node
(`SweepAllInOne`) that dynamically grew and shrank a block of up to 8
dimensions' worth of widgets — `num_dimensions` controlled how many
`dimN_type` / `dimN_values` / `dimN_label` / `dimN_lora_name` groups were
visible, hidden ones collapsed to zero height, and a "model"-type
dimension spawned MODEL input sockets on the fly.

That design fought the ComfyUI frontend's widget rendering across several
rounds of live testing:

1. Hiding a widget by swapping its `.type` broke Vue's ability to render
   it at all (its layout box shrank per one internal size calculation, but
   the widget still occupied a slot per the actual per-frame layout pass,
   which checks a different, `.hidden`-based visibility flag).
2. Fixed to use `.hidden` — better, but `num_dimensions` changes made
   through the UI don't reliably fire `widget.callback` on this frontend,
   so the resync that should follow (add/hide the right widgets, resize
   the node) sometimes never ran until something else forced a full
   relayout (e.g. undo/redo).
3. Fixed with a per-frame polling loop instead of relying on callbacks —
   solved the "doesn't expand" problem, but a newly *revealed* multiline
   text widget (going from hidden to visible for the first time) would
   sometimes render as a bare, unstyled label instead of an actual text
   box. Toggling `.hidden` on an already-constructed widget object
   doesn't reliably make a richer, DOM-backed component (a textarea, in
   this case) rebuild itself — simpler widgets like combos and plain
   strings seemed to tolerate it fine, but this never got fully solved
   from outside the frontend's own source.
4. A separate attempt to cap the default height of multiline text boxes
   (they were sizing themselves much taller than their content needed)
   made things actively worse — the computeSize()/DOM-style override
   didn't reliably control the box's real rendered size, producing
   overlapping widgets instead of the intended compact layout. That
   attempt was reverted rather than patched further.

At that point the pattern was clear: dynamically reshaping *one node's*
widget set in place was fighting internals that aren't fully predictable
or documented from outside, and each fix was trading one symptom for
another. There was a request to look for a fundamentally different
approach, so the node was restructured instead of patched a fifth time.

## The new shape

**`SweepDimension`** — one axis of the sweep, as its own ordinary node.
Has four widgets (`dim_type`, `dim_id`, `values`, `lora_name` — none of
them resized programmatically; only the `lora_name` combo is hidden, when
`dim_type` isn't `lora_strength`, see the notes further down) and two sockets:
`prev_dimensions` (optional input) and `dimensions` (output), both of
type `SWEEP_DIMS`. Chain them like a LoRA-stacker:

```
[SweepDimension #1] --dimensions--> [SweepDimension #2] --dimensions--> [SweepDimension #3] --dimensions--> [SweepAllInOne.dimensions]
   (prev_dimensions                    (prev_dimensions
    left unconnected                    connected to #1's
    = first in chain)                   output)
```

Each node just appends itself to the list it received and passes it
along — `SweepDimension.build()` is a few lines of pure Python, no
dynamic UI needed for that part at all.

**`SweepAllInOne`** — the generator/grid-builder. Lost `num_dimensions`
and all 32 `dimN_*` widgets; gained one optional `dimensions` input
socket. Every other widget (prompts, sampler settings, output settings,
grid axis pickers) is unchanged and was never part of the dynamic-widget
problem in the first place.

### What's left of the dynamic JS

Exactly one thing: when an `SweepDimension`'s `dim_type` is `model`, its
`values` field is reinterpreted as a list of labels and that many `MODEL`
input sockets are kept in sync on that node (`model_1`, `model_2`, ...).
This is the same add/remove/relabel-by-diff logic from the original
design, now scoped to a single node's own two widgets instead of
juggling state across up to 8 dimensions on one shared node. It was never
the source of a reported rendering bug across any round — only the
widget-*hiding* logic was — so it carried over essentially unchanged,
just with a simpler socket name (`model_N` instead of `dimN_model_N`,
since there's only ever one dimension's worth of these sockets per node
now).

`SweepAllInOne` itself needs no JS at all anymore.

### Why sockets don't need Python-side declaration

Same fact as before, still true: ComfyUI resolves a **linked** input
purely from the graph — it does not require the input's name to appear in
`INPUT_TYPES`. Only literal *widget values* need to be pre-declared. So
`SweepDimension.build()` accepts `**kwargs` and pulls `model_1`,
`model_2`, ... out of it directly; the JS side is free to create however
many sockets it wants.

### Chain indexing

Each `SweepDimension.build()` call computes its own position as
`len(prev_dimensions) + 1` — but only for dimensions that actually have
values. An empty/skipped dimension (e.g. a `lora_strength` node with no
LoRA selected, or a text node with no values typed) is dropped from the
list entirely rather than being kept as an inert placeholder, so
downstream dimensions renumber cleanly instead of leaving gaps. This
means the "dimN" tokens used by `grid_x_dim` / `grid_y_dim` /
`grid_title_dim` on the main node always refer to *chain position among
active dimensions*, not "the Nth node you happen to have placed."

### No more 8-dimension ceiling

The old cap existed only because widget values must be pre-declared in
`INPUT_TYPES` up to some fixed maximum. Since dimensions now arrive as a
plain Python list through a socket, there's no equivalent constraint —
chain as many `SweepDimension` nodes as you want. The `grid_x_dim` /
`grid_y_dim` / `grid_title_dim` dropdowns still only list `dim1`..`dim12`
as directly-pickable options (that's just the size of a combo widget's
option list, not a generation-time limit), but dimensions beyond that
still work fine — they just can't be explicitly hand-picked as X/Y/Title
and become automatic grouping axes instead (or you can leave those
pickers on `auto`, which needs no fixed range at all).

## Everything else is unchanged from the v2 write-up

The execution model (cost-sorted axes, LoRA applied to both model and
CLIP, cached CLIP encoding, generalized N-dimension grids with explicit
X/Y/Title + automatic grouping for the rest, clean output folder
structure) is the same engine as before — only how dimensions get
*specified* changed.

### Module layout

| Module | Holds | Imports torch/comfy? |
|---|---|---|
| `sweep_core.py` | The `Dimension`/`ComboRecord` types, value parsing, cost ranking, combo generation, grid-axis resolution, filename building, dedupe/gather/self-combine | No — unit tested with a plain interpreter |
| `sweep_draw.py` | Fonts, text wrapping/truncation, canvas-size limit, padding | No (PIL only) |
| `sweep_image.py` | Tensor↔PIL conversion, cell sizing, the single grid renderer (`make_grid`) and `build_grids`, used by both `SweepAllInOne` and `SweepGridConstructor` | Yes |
| `sweep_*.py` (one per node) | The node classes: inputs, validation, and calls into the modules above | Yes |
| `web/sweepkit_core.js` | Frontend logic for `SweepDimension`: MODEL-socket sync, `lora_name` visibility, 10 Hz change polling. No `app` import, so `tests/*.mjs` import it directly | — |
| `sweep_collect.py` | `SweepCollect`: native-list image input, named files, grids, run list | Yes |
| `sweep_routes.py` | `POST /sweepkit/preview_values`, the read-only route behind the summary line under each axis | No (registered only inside ComfyUI) |
| `web/sweepkit.js` | Registers the extensions (role colours, summary line, Plan outputs, run count, right-click menu) and hooks the core functions into node create/configure/remove | — |
| `web/sweepkit_look.js` | Role colours | — |
| `web/sweepkit_soft.js` | "Sweep this setting": describing a setting, suggesting values, adding and wiring the axis, Plan outputs, collect, image count. Takes the graph and node factory as arguments | — |
| `web/sweepkit_pick.js` | "Pick values from the list": the pure helpers plus a small dialog | — |
| `scripts/run_sweep_api.py`, `scripts/make_diagrams.py` | Run a sweep without the browser; redraw `docs/img/*.svg` | No (stdlib only) |

Grid building lives in exactly one place, so `SweepAllInOne` and
`SweepGridConstructor` can't drift apart; `SweepAllInOne` only differs in
using fixed 16 px labels where the constructor scales text with the cell
size (`font_size`).

## Pairing dimensions instead of cross-producting them: SweepDimensionZip

By default every chained `SweepDimension` is an independent axis — N
values on one times M on another means N×M images. That's usually right,
but not when two axes are genuinely *correlated* rather than
independent: the classic case is a Turbo/Lightning/LCM LoRA, which
typically wants far fewer steps and a much lower cfg than the base
model. There was no way to express "use these settings only when this
LoRA is active" without cross-producting a steps/cfg sweep across every
*other* value too, which defeats the point.

`SweepDimensionZip` takes the **last** dimension appended to each of two
`SWEEP_DIMS` chains and pairs their values index-for-index — the same
job `zip()` does for two Python iterables:

```
[lora_strength: 0.0, 1.0] --dimensions_a--\
                                            [SweepDimensionZip] --dimensions--> ...
[cfg:           4.5, 1.0] --dimensions_b--/
```

produces one 2-long paired axis — `(0.0, 4.5)` and `(1.0, 1.0)` — instead
of a 2×2 cross product. Any *other* dimensions earlier in either input
chain pass through unchanged, still independent.

**Three modes**, mirroring Python's own zip functions: `shortest` (stop
at the shorter list, extra values on the longer side dropped with a
warning — like `zip()`), `longest` (the shorter list is padded by
repeating its own last value — like `itertools.zip_longest()`, but
without needing an explicit fill value), and `strict` (raise a clear
error if the two lengths don't match).

**Composable by chaining**: feeding one `SweepDimensionZip`'s output into
another `SweepDimensionZip`'s `dimensions_a`/`dimensions_b` pairs in a
*third* dimension against the whole existing pair, not just the tail —
detected by checking whether the tail dimension already carries a
`group` id from a previous zip, and if so, gathering and resizing every
existing member of that group (not just the immediate one) to the new
target length. This is how `zip(zip(lora_strength, cfg), steps)` ends up
with all three dimensions sharing one group and moving together, from
two 2-way zip nodes rather than needing a dedicated N-way node.

**Label**: both paired dimensions' `label` is overwritten to
`"{label_a}, {label_b}"` (the two just-zipped labels, comma-separated) —
this is what shows up in grid titles/filenames for whichever one ends up
representing the pair, so it's clear at a glance that two things are
moving together rather than one.

### How the main node became "group-aware"

Internally, each dimension can now carry an optional `group` id. The
generation loop partitions active dimensions into groups (`partition_
into_groups`) — every ungrouped dimension is still its own singleton
group, so nothing changes for a workflow that never uses
`SweepDimensionZip`. Groups, not individual dimensions, are what gets
cost-sorted (`sort_groups` — a group's cost is however expensive its
priciest member is, so a lora_strength+cfg pair still sorts as
outer-loop material) and Cartesian-multiplied via `itertools.product`;
every member of a group receives the *same* shared index each iteration
instead of an independent one.

Grid building needed the same awareness in two places: `resolve_grid_axes`
now dedupes by group when assigning X/Y/Title/grouping roles (picking one
member of a pair excludes its groupmate from also being picked, and an
explicit attempt to assign both members of a pair to two different roles
is rejected rather than silently producing a grid that's mostly empty
cells off the forced diagonal), and the per-cell image lookup uses
`resolve_group_index`, which falls back to a groupmate's resolved index
for any dimension that wasn't itself given a role — without that, an
unrepresented zip partner would default to index 0 regardless of which
value was actually generated for that cell.

## Known limitations of the split-node design

- A "model"-type dimension no longer supports an optional per-slot CLIP
  override (the mega-node version did). Every slot uses the main node's
  own `clip` input. This was dropped for simplicity in the restructuring;
  it's a small, self-contained addition to bring back if it's actually
  needed (`SweepDimension` would gain optional `clip_N` sockets alongside
  `model_N`, using the exact same sync logic).
- `SweepDimension`'s `lora_name` is a combo/dropdown, not a multiline text
  box — unlike the multiline `dimN_values` widgets in the old mega-node
  (which never reliably hid/showed on this frontend), combos and plain
  strings hid and showed correctly in every round of that node's issues.
  So `lora_name` IS conditionally hidden (only visible when `dim_type =
  lora_strength`), on the theory that this specific, narrow case carries
  little of the risk that motivated leaving everything else alone.
- Model-type sockets are still matched to labels by *position* — deleting
  a label from the middle of the list shifts which existing connection
  maps to which remaining label, same caveat as before.
- `SweepDimension` doesn't validate a `lora_strength` dimension's LoRA
  filename at build time (only `dim_type`/`values` are validated there);
  an unknown filename is caught later, when `SweepAllInOne` actually
  tries to load it. Seed/steps/cfg parsing errors, by contrast, surface
  immediately at the `SweepDimension` node itself, which is arguably the
  more useful place for them to appear.

## Three fixes from real-world use: delimiters, aspect ratio, grid labels

**Comma delimiter clobbering tag lists.** `parse_text_list` used to split
on both commas and newlines, so a single value meant to be a whole
comma-separated tag list (`masterpiece, highres, 1girl`) got shredded
into three separate values instead of staying one — exactly backwards
for anyone using tag-based prompts. Fixed to newline-only for anything
free-text (`text`/`static` dimension values, and — since it's the same
function — a `model` dimension's socket labels; the JS-side label parser
for the same field was fixed to match). Numeric dimensions (seed/steps/
cfg/lora_strength) still accept commas as a convenience, since a number
can't contain one ambiguously the way a tag list can.

**Grid cells forcing a square, distorting non-square images.** `make_grid`
always resized every image to `cell_size × cell_size`, regardless of the
actual output resolution (e.g. an 888×1184 portrait latent got stretched
into a square). Added a `cell_mode` widget: `fit` (new default — scales
preserving aspect ratio, bounded by `cell_size`), `square` (the original
behavior, kept for anyone who wants it), `original` (native resolution,
no resizing at all). `fit`/`original` both letterbox-center each image
within its cell rather than stretching, so nothing gets distorted even if
resolutions aren't perfectly uniform across the sweep (unusual, but
possible with a `model` dimension mixing resolutions).

**Grid axis labels not actually identifying what they're labeling.** Two
separate bugs here. First, `lora_strength` values are stored as
`(model_strength, clip_strength)` tuples, and axis tick labels were
showing Python's raw tuple repr (`(0.5, 0.5)`) instead of a formatted
string — the grid *title* had special-case formatting for this, but the
X/Y tick labels never did. Second, and more fundamentally: when an
`SweepDimensionZip`-paired group was used as a grid axis, only *one*
representative member's value was ever shown, even though the group's
label already said all of them (e.g. label "lora_str, ste, cfgg" sitting
next to a value that was only ever lora_strength's own number) — and
with `grid_title_dim` set to `none`, there was nothing anywhere on the
grid identifying what a bare value even represented.

Fixed with three additions to `sweep_core.py` — `format_dim_value`
(consistent formatting for every value type, not just lora_strength: `1`
and `1.0` don't show up side by side inconsistently anymore either),
`dim_group_members` (every dimension sharing a group id), and
`format_group_value` (the combined display value for a whole group,
e.g. `"0.5, 15, 4.5"` for a zipped lora_strength+steps+cfg triple) — used
for X/Y tick labels and for the title's grouping-axis values alike. On
top of that, the title now always gets an "X: `<label>` Y: `<label>`"
caption appended, regardless of whether `grid_title_dim` is set, so an
axis is never unlabeled even in a `title_dim=none` configuration.
`resolve_grid_axes` also now prints a clear reason whenever an explicit
`grid_x_dim`/`grid_y_dim`/`grid_title_dim` pick gets silently dropped
(most commonly: it conflicts with another axis's already-claimed zip
group) — previously this just failed silently, which is exactly what
happened in the report that surfaced this (`grid_y_dim` set to a
dimension that was already part of the X axis's zip group).

## How fixed_seed / fixed_steps / fixed_cfg relate to dimensions

`fixed_seed` / `fixed_steps` / `fixed_cfg` on `SweepAllInOne` are
**defaults, used only when no chained SweepDimension of the matching type
exists**. If you chain in a `cfg`-type dimension, its values are used for
every image and `fixed_cfg` is ignored entirely for that run — it's not
"redundant", it's just not consulted while a sweep over that axis is
active. This is exactly the same pattern as A1111-style XYZ plots: pick
one axis to sweep, hold the rest at a fixed value.

Two things worth being explicit about, since they're easy to assume
incorrectly:

- `sampler_name`, `scheduler`, and `denoise` have **no** matching
  dimension type — there's no way to sweep them at all right now, they're
  always fixed for the whole run regardless of what's chained in. Adding
  a `sampler`/`scheduler` dimension type is a small, contained change if
  wanted (a new entry in `DIM_TYPE_OPTIONS`, a parsing branch in
  `SweepDimension.build()`, and a lookup in the main node's per-image loop
  — the same shape as every other axis) — just hasn't been asked for yet.
- Seed used to have no "fixed" option at all — with no seed dimension
  chained in, every image silently used the literal constant `1`. Now
  there's a `fixed_seed` widget so you can pin a specific seed while
  sweeping something else, instead of being stuck with `1`.

## Why text_mode / text_regex live on the main node, not on SweepDimension

These control how `{}` (or a custom regex) is found in `positive_prompt`
— but there's only ever one prompt string being scanned, shared by every
`text`-type dimension in the chain (the 1st one fills the 1st match, the
2nd fills the 2nd, and so on). It's a property of the prompt, not of any
individual dimension, so it has to live wherever the prompt itself lives
— which is the main node, since that's also where CLIP encoding happens
(after substitution, per combination). There isn't a sensible way to
split it across dimension nodes without duplicating "which regex" onto
every single one and hoping they agree.

## A real bug found via the "square works, fit/original don't" clue

`_cell_dims` (now `sweep_image.cell_dims`) read an image tensor's height/width from fixed positions
`shape[1]`/`shape[2]`, assuming a plain `[batch, H, W, channels]` tensor.
A live report showed grid images collapsing to a near-zero height
(147px total — exactly `title_h + label_h + pad` with the cell
contributing ~1px) specifically with `cell_mode` set to `fit` or
`original`, while `square` worked fine. That's a meaningful clue on its
own: `square` never inspects `.shape` at all (it just returns
`cell_size, cell_size` directly), so the bug had to be in how height/
width were being read, not in the aspect-ratio math itself.

The user's earlier logs mentioned `WanVAE` — Wan is a video-capable model
family, and its VAE plausibly returns an extra leading "frames"
dimension even for a single still image: `[batch, frames, H, W,
channels]` instead of the plain 4D shape assumed. Reading `shape[1]`
against a 5D tensor silently grabs the frame count (1) instead of
height — no crash, just a badly wrong number, which is exactly what
turns into a ~1px-tall cell rather than an error anyone would notice
immediately.

Fixed by reading from the **end** of the shape instead of a fixed
absolute position — `shape[-3]`, `shape[-2]` — since ComfyUI's
channels-last convention (`..., H, W, C`) is stable regardless of how
many leading batch/frame dimensions exist. `tensor_to_pil` was already
robust to this by accident (`.squeeze()` drops any size-1 leading dims
before conversion), which is why the actual generated *images* always
looked fine — only the cell-sizing computation, which read shape
positions directly rather than going through squeeze, was affected.

`tests/run_integration.py` scenario 20 constructs both a plain 4D tensor
and a 5D one with an extra leading frames dimension but the same actual
H/W, and asserts they produce identical, correct cell dimensions — and
running the *old* code against the 5D case directly reproduces the
reported bug exactly: `(512, 1)`, an effectively-zero-height cell.

## Testing performed

Run everything with `python tests/run_all.py` (see README.md).

- `tests/logic_test.py` — pure `sweep_core.py` functions (parsing,
  cost ranking, grid-axis auto-resolution, dimension-value resizing,
  group partitioning/sorting, and group-aware grid-axis dedup for
  zipped dimensions), no ComfyUI/torch dependency.
- `tests/run_integration.py` — the real `sweep_dimension.py` +
  `sweep_dimension_zip.py` + `sweep_all_in_one.py`, chained exactly as
  the graph would, against a mocked torch/comfy/folder_paths/nodes
  environment. Covers: no dimensions connected, a two-node text×seed
  chain, an empty dimension in the middle of a chain renumbering cleanly
  instead of leaving a gap, a `model` dimension's socket resolution
  (including a deliberately unconnected slot), a `lora_strength`
  dimension, a 3-node model×lora×seed chain confirming LoRA reapplication
  (4, not 12) and CLIP encoding (8, not 24) stay minimized across
  cost-sorted execution, malformed seed input raising an immediate error
  at the dimension node, an unknown LoRA filename raising a clear error
  at generation time, a 10-dimension chain confirming there's no cap
  anymore, `fixed_seed` actually being used (via the saved filename) when
  no seed dimension is chained in, `encode()` going through the complete
  `encode_from_tokens_scheduled()` path (and falling back correctly when
  a CLIP doesn't implement it), zipping two dimensions producing paired
  (not cross-produced) images with a spy on `sample()` confirming *which*
  cfg value landed with *which* lora strength (not just the count — the
  actual pairing), chaining two zips into a 3-way pairing sharing one
  group, all three zip modes (shortest truncates, longest pads by
  repeating the last value, strict raises a clear error on mismatched
  lengths), and grid building with a zipped pair as an axis producing the
  expected grid count with no crash,
  cell_mode's three sizing modes against a portrait (888×1184) image
  confirming 'square' forces cell_size regardless of source shape, 'fit'
  preserves the exact aspect ratio while capping the larger dimension at
  cell_size, and 'original' uses the exact native size ignoring cell_size
  entirely, a spy on make_grid() confirming the actual title/x_labels
  passed to it contain no raw tuple reprs, do show an "X: <label>"
  caption even with grid_title_dim=none, and do show every zipped
  member's value together rather than just one, and _cell_dims producing
  identical, correct results for a plain 4D image tensor and a 5D one
  with an extra leading frames dimension (the video-VAE-style shape that
  caused a real production bug — reading height/width from fixed
  positions instead of the end of the shape silently collapsed grid cells
  to ~1px tall without ever raising an error).
- `tests/js_socket_test.mjs` — the MODEL-socket diffing logic against a
  mocked node, confirming relabeling never touches a link, shrinking
  disconnects+removes only the trailing sockets that were dropped, and
  growing appends new sockets without disturbing earlier ones.
- `tests/js_polling_test.mjs` — confirms the change-detection loop catches
  a widget value changing with *no callback firing at all* (the exact
  failure mode reported against the old mega-node) within one frame, and
  stops cleanly when the node is removed.
- `tests/js_hidelora_test.mjs` — confirms `lora_name` hides/shows
  correctly based on `dim_type`, and that the one-time "model_a, model_b"
  example fill for an empty `values` field on switching to `model` fires
  exactly once, never re-fires after a deliberate later edit, and never
  touches a field that already had real content.

As always: this validates the control-flow logic against concrete
inputs/outputs, not actual Litegraph/Vue rendering — load it in a real
ComfyUI instance before trusting it on a big batch.

## A real, pre-existing correctness bug: malformed conditioning shape

A live run surfaced `IndexError: index 1 is out of bounds for dimension
0 with size 1`, deep inside ComfyUI's own sampler
(`comfy.sampler_helpers.cond_has_hooks`, via `cfg_guider.set_conds`).

Root cause: `encode()` returned `clip.encode_from_tokens(tokens,
return_pooled=True)` directly — a bare `(cond_tensor, pooled)` 2-tuple —
instead of ComfyUI's actual conditioning format, a **list** of `[cond,
extra_dict]` pairs (`[[cond_tensor, {"pooled_output": pooled}]]`). Most
of the sampling path just forwards `positive`/`negative` around without
inspecting their shape, so this went unnoticed through every earlier
round and even generated correct-looking images most of the time. It
only broke visibly once a code path that actually iterates conditioning
expecting `[cond, dict]` pairs got hit — iterating over the bare 2-tuple
gives the raw conditioning tensor as the first "entry", and indexing
`tensor[1]` on a batch-size-1 tensor is exactly this IndexError. This is
the same bug the original pre-existing node (the one this whole node
pack was built from) already had — carried forward unnoticed across
every rewrite.

**First fix attempt** wrapped the shape by hand:

```python
cond, pooled = clip.encode_from_tokens(tokens, return_pooled=True)
return [[cond, {"pooled_output": pooled}]]
```

This stopped the crash — but on a FLOW-matching model with a custom
text encoder, it produced pure-noise output instead of a
crash. The shape was valid enough to iterate without erroring, but a
hand-built dict containing only `pooled_output` can still be missing
whatever *other* extra keys that specific architecture's conditioning
needs to actually modulate on — DiT/FLOW-style models lean on
conditioning much more heavily than classic UNet diffusion, so
incomplete-but-validly-shaped conditioning can fail silently (30/30
steps, no error, just noise) rather than obviously.

**Actual fix**: use `clip.encode_from_tokens_scheduled(tokens)` — the
same method the real, stock `CLIPTextEncode` node uses — instead of
manually reconstructing the conditioning dict. It returns the correctly
shaped list *and* includes whatever extra fields a given CLIP/model
implementation actually attaches (attention masks, hook data,
architecture-specific extras), rather than a hand-rolled guess at what's
required:

```python
def encode(self, clip, text):
    tokens = clip.tokenize(text)
    if hasattr(clip, "encode_from_tokens_scheduled"):
        return clip.encode_from_tokens_scheduled(tokens)
    cond, pooled = clip.encode_from_tokens(tokens, return_pooled=True)
    return [[cond, {"pooled_output": pooled}]]
```

The fallback only fires for a CLIP object that doesn't implement the
newer method at all.

The real gap both of these exposed: none of the mocked tests modeled
ComfyUI's conditioning shape *or content* — `FakeClip.encode_from_tokens`
returned a plausible-looking tuple and the fake `common_ksampler` never
inspected `positive`/`negative` at all, so a shape bug like the first one
couldn't be caught by tests that only check "did generate() run without
throwing and produce the right number of images," and a *content*
completeness bug like the second one couldn't be caught by a shape check
alone. Two things fixed on the test side:

- The stub's `common_ksampler` now validates that `positive`/`negative`
  are lists of `[cond, dict]` pairs before doing anything else —
  mirroring what real ComfyUI's hooks code expects closely enough to
  catch the shape class of bug.
- `FakeClip` now has a separate `encode_from_tokens_scheduled` that
  returns conditioning carrying a field the hand-rolled dict wouldn't
  know to include, and `tests/run_integration.py` scenarios 12–13 assert
  `encode()` actually goes through that path (not a shape-valid-but-
  incomplete fallback) whenever it's available, and still falls back
  correctly when it isn't.

None of this *proves* image output is correct — the mocks still can't
validate actual pixel content, only that the right method gets called
with the right shape. If output still isn't right after this fix, the
next thing worth checking is whether a plain stock ComfyUI workflow
(CLIPTextEncode → KSampler → VAEDecode, same model/clip/vae) produces a
correct image with this specific checkpoint — that isolates whether
there's still something specific to this node's encoding path, versus
something in the environment or model setup unrelated to it (e.g., the
CLIPLoader `type` value not matching the actual text encoder
architecture).

## Version 1.1: sweeping any setting, live grid, plain names

This round added three things, each chosen after trying the alternatives
against a real ComfyUI.

### A live grid on All-in-One, backend only

ComfyUI's progress bar can carry a preview image
(`ProgressBar.update_absolute(value, total, ("JPEG", image, max_size))`).
`LiveGrid` (in `sweep_image.py`) keeps small thumbnails of the finished
images, draws the labelled grid so far (cells not done yet are quiet "pending"
tiles; with extra axes it shows the page of the newest image), and sends one
frame per image, at most every 0.3 s. It reuses `make_grid` and the same
resolved axes (`GridAxes`) as the saved grids, so the preview and the result
can't disagree. A preview failure turns the preview off and the sweep carries
on.

That preview is for a node that does its own looping. In the Plan + Collect path
ComfyUI's executor runs each node over *all* list items before the next node
starts, so Collect can't see an image until the sampler has finished every run.
So the Plan path gets its live grid a different way (next section): the browser
queues the workflow once per image.

### A live grid on Plan + Collect: one queue entry per image

`web/sweepkit_live.js` wraps `api.queuePrompt`. For a prompt whose single Plan has
`live_grid` on, whose `combo` goes only to Sweep Collect, and whose image count is
known, it queues the same prompt once per image, each copy telling the Plan which
combination to hand out (hidden inputs `sweep_cursor` and `sweep_session`; the Plan
then returns only that entry of every axis list). Sweep Collect receives one image
per run, keeps a `LiveSession` between runs (`sweep_live.py`, keyed by the session
id, at most four unfinished sessions), shows the grid so far through its normal
`ui` images (a temp file rewritten each run), saves each image as it finishes, and
after the last writes the grids and the run list.

Why this shape: it is the same trick quick XY-plot nodes use, but kept optional.
The cursor is just an input, so a prompt posted to the API without it still
runs everything in one go, and a user can switch `live_grid` off. Wrapping
`api.queuePrompt` (the call that sends an already-built prompt) rather than
`app.queuePrompt` means nothing is patched before the prompt exists, and ComfyUI's
own caching re-runs only what a changed combination affects. Costs: a sweep shows
as several queue entries, and cancelling stops only the current one (the rest can
be cleared from the queue).

### Sweeping any setting through native lists

Three facts, each checked live, make this possible without intercepting the
frontend's queueing:

- An output declared `OUTPUT_IS_LIST` with type `"*"` can be wired into any
  widget socket (INT, FLOAT and COMBO were tested), and ComfyUI's validation
  accepts it (`validate_node_input` treats `*` as any type).
- Two such outputs wired into one node are walked in step (aligned lists), so
  one list per axis, each expanded to the full product, gives every combination
  exactly once.
- A node with `INPUT_IS_LIST` receives the whole set of images at the end
  (`SweepCollect`), no List-Utils needed. (In a live run it receives one.)

So `SweepCombinationExpander` (the Plan) keeps its three original outputs in
slots 0-2 (saved workflows link by position) and gains eight list outputs
`axis_1`..`axis_8` after them, one per axis in chain order
(`axis_output_lists` in `sweep_core.py`). The frontend shows one per axis in the
chain, trimmed from the end and never removing a wired one. When the chain runs
through Pair Axes or Subsets it can't read the axes, so it leaves all eight.

The sweep stays visible in the graph (axis nodes, a Plan, wires) rather than in
hidden node state, so it can be read, copied, diffed and run through the API.
The right-click menu only automates what a user would otherwise wire by hand;
it uses the frontend's `getNodeMenuItems` hook and `node.getWidgetOnPos`, and
changes nothing at queue time.

Known rough edges: a choice setting becomes a `text` axis, so each value is a
folder in the saved file names; a loader's file-name sweep loads each file in
turn; a text box needs the node's title bar for its right-click (inside the
text box the browser's own menu opens).

### Summary lines come from the backend

The count and values shown under an axis ("3 values: 1 · 2 · 3", or what is
wrong with the text) are asked of `POST /sweepkit/preview_values`, which runs
the same parser as the sweep (`preview_values` in `sweep_dimension.py`), so the
two can't disagree and there is no second implementation to keep in step. The
"12 images: 2 × 3 × 2" line multiplies those counts. Ranges above 10,000 values
are refused rather than expanded.
