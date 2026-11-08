# Changelog

## 1.1.0

Node IDs, input and output positions, and custom types are unchanged, so
workflows saved with 1.0.0 keep loading. The old Sweep Expander is now called
Sweep Plan, and "dimension" is now "axis" in names and text.

### Added
- After a live sweep, changing only Sweep Collect's settings (grid axes, cell size, prefix...) and queueing
  again rebuilds the grids from the kept images in one short run instead of sampling every image again.
- A `model` axis fed by a PyList is labelled with each model's file name (e.g. `my_model`) in file names,
  grids and the run list.
- The grid axis dropdowns (`grid_x_dim`, `grid_y_dim`, `grid_title_dim`, and the UpSet node's `title_dim`)
  list the connected axes by name (`dim_id`) instead of `dim1`, `dim2`... Saved workflows with `dimN` values keep
  working, and scripts can send either form.
- **Sweep any setting of your own workflow.** Right-click a number, choice or
  text setting on any node and choose Sweep "...": a Sweep Axis is added,
  filled in from the setting and wired to it through Sweep Plan. Works with any
  sampler or node pack, and without the browser.
- **Sweep Plan** gives each axis out as a list (`axis_1` ... `axis_8`) to
  connect to any setting; ComfyUI runs those nodes once per combination.
- **Sweep Collect** gathers a workflow's images, saves each named after its
  values, builds the grids, and needs no extra node packs.
- Right-click on an image node: "Sweep: collect results here".
- A **live grid**. Sweep All-in-One shows the grid so far on the node while it samples. Sweep
  Plan + Sweep Collect run image by image when started from the browser (Plan's
  `live_grid` switch, on by default), so Collect shows the grid as images finish and saves each one as
  it is made; scripts and the API still run everything in one go.
- A **run list** (`sweep_manifest_NNNNN.csv`) beside the images of Sweep
  All-in-One and Sweep Collect: one row per image with its file and every value.
- A summary line under each axis ("3 values: 1 . 2 . 3", or what is wrong),
  and "12 images: 2 x 3 x 2" on Sweep Plan and Sweep All-in-One.
- **Pick values from the list...** on axes made from choice settings (samplers,
  LoRA files, checkpoints).
- Role colours: blue axes, green generators, purple grid builders, grey plumbing.
- `scripts/run_sweep_api.py`: run a sweep from a script, with `--set` overrides.
- Sweep Axis Value (Extract) has a native list output after its PyList one.
- Flowcharts in the README (`docs/img/`, redrawn by `scripts/make_diagrams.py`).

### Fixed
- A `model` axis fed by a PyList (example 6) no longer stops Sweep Plan with `KeyError: 'model_objs'`, and works
  on Sweep All-in-One; grid labels and the run list show such models as `checkpoint0`, `checkpoint1`... rather than
  an object description.
- Example workflows: nodes are sized so titles and labels fit, and none overlap; example 5's note explains
  that 3 images are generated while the grid still has all 9 cells.
- A very long prompt in a grid or matrix title no longer makes the image very wide: titles wrap to at most
  three lines within the grid's own width, with the axis names on a line of their own, and long labels end in an
  ellipsis. Cutting a very long word is no longer slow.
- Sweep Plan names its outputs and shows the image count when its chain passes through Sweep Pair Axes or Sweep
  Subsets (read by the backend, so it matches what the sweep does).

### Changed
- Examples and text say "style" instead of "artist"; example 4 is now `4_style_combinations_upset.json`.
- Easy nodes stay in **SweepKit**; the rest are under **SweepKit/Advanced**.
  Every node has a description and search aliases (the old names still find
  them).
- Example workflows 2 and 3 are rebuilt on Sweep Plan and Sweep Collect (12 and
  14 nodes instead of 19 and 24, no List-Utils). Examples 4-6 are unchanged.
- Number ranges above 10,000 values are refused instead of expanded.
- A Sweep Plan saved before the `axis_N` outputs existed keeps its three
  outputs until an axis is added to it.

## 1.0.0 — 2026-11-08

First versioned release, after a quality audit. Node names, inputs and
outputs are unchanged, so existing workflows keep loading.

### Fixed
- Several `lora_strength` dimensions now stack (applied in chain order);
  previously only the first was used.
- A second `seed`, `steps`, `cfg` or `model` dimension on Sweep All-in-One
  now stops the run with a clear error instead of being silently ignored.
- `text_mode = regex` fills placeholders left to right, like `{}` mode;
  an invalid `text_regex` gives a clear error before sampling.
- Sweep Dimension Zip keeps a dimension shared by both inputs once
  instead of cross-producting it with itself.
- Ranges with negative bounds (`-5--1`, `-3-2`) parse instead of crashing.
- Windows device names (`NUL`, `CON`, `AUX`, `COM1`...) as prefixes or
  values are saved as `_NUL` etc. instead of failing.
- Model labels beyond the 24 MODEL sockets are dropped with a warning.
- Batched grids/pages are padded instead of stretched to one size.
- Sweep Gather rejects `True`/`False` as indices.
- A folder-listing error can no longer restart file numbering at `_00001`
  and overwrite an earlier file.
- Sweep Upset Constructor's `title_dim = auto` now works (it was ignored).
- A `model`-type dimension fed through `values_pylist` no longer shows
  example labels and unused MODEL sockets.

### Changed
- Sweep All-in-One keeps decoded images in memory only when
  `create_grids` is on.
- Grid and UpSet nodes stop between grids/pages when interrupted, report
  progress, and show their saved images and summary on the node.
- Sweep Dimension Self-Combine refuses settings that would produce more
  than 10,000 values, suggesting a `max_size` that fits.
- Grids and matrices larger than 100 megapixels stop with advice instead
  of exhausting memory.
- Sweep All-in-One and Sweep Grid Constructor share one grid renderer;
  All-in-One grids now wrap long labels.
- The frontend checks for changes 10 times a second instead of every
  animation frame.
- Every input has a tooltip.

### Added
- Six example workflows in `example_workflows/`.
- README, MIT license, `pyproject.toml`, test runner (`tests/run_all.py`)
  and CI.
