# Changelog

## Unreleased

### Changed
- SweepKit is now in ComfyUI Manager's list. The README installs it from **Manager → Custom Nodes
  Manager** first; downloading the ZIP from GitHub stays as the route without Manager.

## 1.2.0 — 2026-11-10

**To upgrade:** nothing to do. Saved workflows keep loading.

### Added
- Each example has a thumbnail in ComfyUI's template browser.

### Changed
- The README starts with installing and the quick start; "How it works" and the examples follow. It
  also says how paired settings are counted and where the output folder is in other installs.
- Install from the GitHub page (Download ZIP, or `git clone`): SweepKit isn't in ComfyUI Manager's
  list yet. The steps say where the Code button is, how to unzip, and where `custom_nodes` is. ComfyUI-List-Utils, needed by examples 4–6, still installs from ComfyUI Manager.
- Clearer messages: a Sweep Pair Axes length mismatch in strict mode says "set Pair Axes to
  shortest", and an image-count mismatch after Sweep Skip Repeats says which output goes to which
  input of the second Sweep Gather.
- The Node Guide gives a rough time for each task, and example 1 names the folder the example file
  saves to (`SweepKit_quickstart`).
- The Quick start says what to do when your model comes as separate files (Flux and similar):
  use Load Diffusion Model, Load CLIP and Load VAE in place of Load Checkpoint.
- The text under Sweep All-in-One, Sweep Collect, Sweep Grid and Sweep UpSet Matrix after a run uses
  the node names shown in ComfyUI and plain counts ("9 images across 2 axes").

### Fixed
- Sweep All-in-One's live grid always shows its first preview. On a computer or container that had
  only just started, the first preview could be skipped.

## 1.1.0 — 2026-11-10

**To upgrade:** nothing to do. Saved workflows keep loading: node IDs, inputs, outputs and their order
are unchanged. Restart ComfyUI and reload the browser page after updating.

Some nodes have new names on screen: the old Sweep Expander is now **Sweep Plan**, and "dimension" is
now "axis" everywhere. Search still finds the nodes by their old names.

### Added
- **Sweep any setting of your own workflow.** Right-click a number, choice or text setting on any
  node and choose **Sweep "…"**: a Sweep Axis is added, filled in from the setting, and connected to
  it through Sweep Plan. It works with any sampler or node pack.
- **Sweep Plan** gives each axis out as a list (`axis_1` … `axis_8`) that you connect to any setting;
  ComfyUI runs that node once per image.
- **Sweep Collect** gathers a workflow's images, saves each one named after its values, and builds
  the grids, with no extra node packs. Right-click an image node and choose **Sweep: collect results
  here** to add it.
- **A live grid.** Sweep All-in-One shows the grid so far on the node while it runs. Sweep Plan +
  Sweep Collect, started from the browser, run one image at a time, so the grid fills in on Sweep
  Collect as images finish (Sweep Plan's `live_grid`, on by default). A sweep started from a script
  still runs in one go.
- **Changing only Sweep Collect's settings** (grid axes, cell size, folder…) after a live sweep
  rebuilds the grids from the images already made, in one short run, instead of making every image
  again.
- **A run list** (`sweep_manifest_NNNNN.csv`) beside the images of Sweep All-in-One and Sweep
  Collect: one row per image with its file and every value. Open it in a spreadsheet.
- **A line under each axis** shows what it read ("3 values: 1 · 2 · 3") or what is wrong and how to
  fix it. Sweep Plan and Sweep All-in-One show how many images the sweep makes ("12 images: 2 × 3 × 2").
- **Pick values from the list…** on axes made from choice settings (samplers, LoRA files,
  checkpoints).
- **Grid axis lists show your axis names** (`grid_x_dim`, `grid_y_dim`, `grid_title_dim`, and Sweep
  UpSet Matrix's `title_dim`) instead of `dim1`, `dim2`…. Workflows that hold `dim1`, `dim2`… keep
  working.
- **Models in a list are named after their files.** A `model` axis fed by a list of models (example
  6) labels each one with its file name (for example `my_model` for `my_model.safetensors`) in file names, grid labels and
  the run list.
- Nodes are coloured by role: blue for the axes and Sweep Plan, green for the nodes that make or
  collect images, purple for the grid builders, grey for the other Advanced nodes.
- `scripts/run_sweep_api.py` runs a sweep from a script, without the browser, and can change inputs
  first (`--set`).
- Sweep Axis Value has a second output, `list`, that connects straight to any setting without
  ComfyUI-List-Utils.
- Flowcharts in the README.

### Fixed
- **A Preview Image after Sweep Collect** now shows the grid so far during a live sweep (it showed a
  black image), and gets the rebuilt grids after a settings-only change (the run failed with "Prompt
  has no outputs"). Running Sweep Collect on its own also updates the Preview and Save nodes after it.
- **Example 6 with a list of models** stopped Sweep Plan with an error, and Sweep All-in-One could not
  use such a list. Both work now.
- **A very long prompt** in a grid or matrix title no longer makes the image very wide. Titles wrap to
  at most three lines within the grid's own width, with the axis names on a line of their own; long
  labels end in "…".
- **Sweep Plan with Sweep Pair Axes or Sweep Subsets** now names its outputs and shows the image count.
- **Example workflows:** nodes are sized so titles and labels fit, and none overlap.

### Changed
- **Error messages** name the node as ComfyUI shows it ("[Sweep Subsets]", not a code name), say which
  setting was wrong, and say what to do next.
- **Tooltips** say what to enter and what it changes, in plain words, without code names.
- **The line under each axis** is easier to read on every node colour.
- **The example Notes** each say what the example shows, what to set first, what it makes and where,
  and which node packs it needs.
- **README and Node Guide** rewritten for first-time users: a Quick start that shows where to find the
  example and the results, how long a sweep takes, how to stop one, a "Typing values" table, a
  contents list and a glossary.
- Examples and text say "style" instead of "artist"; example 4 is now `4_style_combinations_upset.json`.
- The everyday nodes are in **SweepKit**; the rest are in **SweepKit/Advanced**. Every node has a
  description.
- Examples 2 and 3 are rebuilt on Sweep Plan and Sweep Collect (12 and 14 nodes instead of 19 and 24,
  with no ComfyUI-List-Utils). Examples 4–6 still use it.
- A range of more than 10,000 values is refused, instead of making that many images.
- A Sweep Plan saved before the `axis_N` outputs existed keeps its three outputs until you add an axis.

## 1.0.0 — 2026-11-08

**To upgrade:** nothing to do. Node names, inputs and outputs are unchanged, so existing workflows
keep loading.

First versioned release, after a quality review.

### Fixed
- Several `lora_strength` axes on Sweep All-in-One now stack, applied in chain order; before, only the
  first was used.
- A second `seed`, `steps`, `cfg` or `model` axis on Sweep All-in-One now stops the run with a clear
  message, instead of being ignored.
- `text_mode` regex fills the prompt from left to right, like `{}`; a search pattern that isn't valid
  stops the run with a clear message before any image is made.
- Sweep Pair Axes keeps an axis that both its inputs share once, instead of combining it with itself.
- Ranges with negative numbers (`-5--1`, `-3-2`) work instead of failing.
- Windows device names (`NUL`, `CON`, `AUX`, `COM1`…) used as a folder or value are saved as `_NUL`
  and so on, instead of failing.
- Model labels beyond the 24 model inputs are dropped, with a message in the console.
- When several grids or pages are output together, smaller ones are padded instead of stretched.
- Sweep Gather refuses `True` and `False` as positions.
- A folder that can't be read no longer restarts file numbering at `_00001` and replaces an earlier
  file.
- Sweep UpSet Matrix's `title_dim` set to `auto` now works (it was ignored).
- A `model` axis fed by a list no longer shows example labels and unused model inputs.

### Changed
- Sweep All-in-One keeps the images in memory only when `create_grids` is on.
- Sweep Grid and Sweep UpSet Matrix stop between grids when you cancel, show their progress, and show
  their saved images and summary on the node.
- Sweep Subsets refuses settings that would make more than 10,000 subsets, and suggests a `max_size`
  that fits.
- A grid or matrix larger than 100 megapixels stops with advice, instead of using up the memory.
- Sweep All-in-One and Sweep Grid build grids the same way; All-in-One grids now wrap long labels.
- The browser checks the nodes for changes 10 times a second instead of on every frame.
- Every input has a tooltip.

### Added
- Six example workflows in `example_workflows`.
- README, MIT license, package metadata, a test runner (`tests/run_all.py`) and automatic tests.
