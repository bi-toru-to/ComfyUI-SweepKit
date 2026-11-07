# Changelog

## 1.1.0

Node IDs, input and output positions, and custom types are unchanged, so
workflows saved with 1.0.0 keep loading. The old Sweep Expander is now called
Sweep Plan, and "dimension" is now "axis" in names and text.

### Added
- **Sweep any setting of your own workflow.** Right-click a number, choice or
  text setting on any node and choose Sweep "...": a Sweep Axis is added,
  filled in from the setting and wired to it through Sweep Plan. Works with any
  sampler or node pack, and without the browser.
- **Sweep Plan** gives each axis out as a list (`axis_1` ... `axis_8`) to
  connect to any setting; ComfyUI runs those nodes once per combination.
- **Sweep Collect** gathers a workflow's images, saves each named after its
  values, builds the grids, and needs no extra node packs.
- Right-click on an image node: "Sweep: collect results here".
- A **live grid** on Sweep All-in-One: the grid so far appears on the node while
  it samples.
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

### Changed
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
