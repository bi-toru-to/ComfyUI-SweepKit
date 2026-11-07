# SweepKit for ComfyUI

**Try every combination of your settings, from one Run.** Seeds, cfg, prompts, LoRA strengths,
samplers, models: pick what to vary, and SweepKit makes every combination, saves each image under a
name made from the values used, builds labelled grids, and writes a run list you can open in a
spreadsheet.

<p align="center">
  <img src="docs/img/example_grid.jpg" width="460" alt="A labelled grid: seed across, cfg down, one prompt">
  <br><sub>One grid out of a sweep: seed across, cfg down. The prompt is on the title line.</sub>
</p>

## What can I do with it?

| I want to know... | Sweep this | You get |
|---|---|---|
| Which **cfg or steps** looks best | `cfg` 4, 7, 10 × `steps` 15, 25, 35 | one grid, every pairing |
| How strong my **LoRA** should be | LoRA strength 0.2 … 1.0 (model and clip paired) | a row per strength |
| Which **sampler or checkpoint** suits a prompt | tick them from the list | one image each, same seed |
| How **prompt wording** changes the result | several prompt versions | one grid per prompt |
| Which **artist names work together** | every pair and triple of a list | an UpSet-style matrix |

## How it works

You list the values to try for each setting (an **axis**). SweepKit multiplies the axes, runs every
combination, and collects the results.

<p align="center"><img src="docs/img/flow_quickstart.svg" alt="Two Sweep Axis nodes feed Sweep All-in-One, which produces 9 images, a grid and a run list"></p>

**Use your own workflow?** Right-click any number, choice or text setting on any node (for a prompt box,
right-click the node's title bar) and choose **Sweep "…"**. SweepKit adds the axis and wires it in. Your nodes (any sampler, ControlNet, LoRA
stack…) stay yours.

<p align="center"><img src="docs/img/flow_any_setting.svg" alt="Sweep Axis nodes feed Sweep Plan, whose outputs drive the seed, cfg and prompt of an ordinary workflow; Sweep Collect gathers the images"></p>

The blue nodes say what to vary, the green node makes or collects the images. Each node shows
what it will do before you press Run: *"3 values: 1 · 2 · 3"* under every axis, *"12 images: 2 × 3 × 2"*
on the Plan.

## Two ways to start

| | **Sweep All-in-One** | **Sweep Plan + Sweep Collect** |
|---|---|---|
| Good for | the fastest start; a standard text-to-image sweep | your existing workflow, any nodes |
| Nodes to add | Axis nodes + 1 | Axis nodes + 2 (the right-click menu adds them) |
| Live grid | yes, the grid fills in on the node while it runs | grid appears when the run finishes |
| Extra node packs | none | none |
| Example | `1_quickstart_all_in_one.json` | `2_sweep_any_setting.json` |

## Install

Either:

- **ComfyUI Manager:** search for *SweepKit* and install, or
- **Manually:**
  ```bash
  cd ComfyUI/custom_nodes
  git clone <this repository's URL> ComfyUI-SweepKit
  ```

Then restart ComfyUI and reload the page.

**Requirements**

- ComfyUI (tested with 0.31.0, frontend 1.48.7). No extra pip packages: torch, numpy and Pillow
  come with ComfyUI.
- Right-click sweeping needs a frontend where every setting has an input socket (current ComfyUI
  frontends do).
- Only examples 4–6 (UpSet matrix, skip repeats, a model list) need
  [ComfyUI-List-Utils](https://github.com/godmt/ComfyUI-List-Utils).

## Quick start

1. Open **`example_workflows/1_quickstart_all_in_one.json`** (or find it in ComfyUI's template browser).
2. Pick your checkpoint in **Load Checkpoint**.
3. Queue. You get 9 images (seed 1–3 × cfg 4/7/10), a 3×3 grid and a run list in
   `output/SweepKit_quickstart/`.

To sweep something else, change an axis's type and values, or chain another **Sweep Axis** onto it.

**On your own workflow:** open `example_workflows/2_sweep_any_setting.json` to see one, or just
right-click a setting in your workflow and choose **Sweep "…"**. Edit the values on the new axis, then
right-click your VAE Decode and choose **Sweep: collect results here**.

## Beyond a plain grid

<p align="center"><img src="docs/img/flow_cross_vs_pair.svg" alt="Crossed axes make every combination; paired axes move together"></p>

- **Pair settings:** `Sweep Pair Axes` moves two axes together (a LoRA's model strength with its clip
  strength). Example: `3_pair_lora_strengths.json`.
- **Try subsets of a list:** `Sweep Subsets` makes every single, pair, triple… of a list; `Sweep UpSet
  Matrix` shows which combinations work. Example: `4_artist_combinations_upset.json`.
- **Skip repeats:** `Sweep Skip Repeats` + `Sweep Gather` sample each distinct setting once.
  Example: `5_dedupe_gather.json`.
- **Pick from a list:** for a choice setting (sampler, LoRA, checkpoint), right-click the axis and choose
  **Pick values from the list…** to tick what to compare.

## Run it without the browser

SweepKit does its looping on the server, so one request produces every image. Export your workflow with
**Save (API Format)**, then:

```bash
python scripts/run_sweep_api.py workflow_api.json --server http://127.0.0.1:8188 --set 12.values="1-8"
```

`--set NODE_ID.INPUT=VALUE` changes an input first. Useful for overnight runs, servers and scripts.

## SweepKit and quick XY-plot nodes

Quick XY-plot nodes (for example [XY Plot Pixaroma](https://workflows.pixaroma.com/help/nodes/xy-plot/))
are great for a fast two-setting comparison. SweepKit is for when the question is bigger. The
comparison below is based on that node's public documentation.

| | Quick XY-plot nodes | SweepKit |
|---|---|---|
| Settings varied | two (X and Y) | any number; extra axes become extra grids |
| Pairing, subsets, skipping repeats | no | yes |
| How the run is driven | the browser tab queues each cell | the server does it, so scripts, the API and unattended runs work |
| Live grid | yes, cell by cell | All-in-One: yes. Plan + Collect: when the run finishes |
| Files | the grid, optionally each cell | every image named by its values, the grids, and a CSV run list |
| The sweep in your workflow | inside one node | visible as axis nodes you can read, copy and share |

## Documentation

- **[NODE_GUIDE.md](NODE_GUIDE.md):** every node, input and output, plus step-by-step versions of the example workflows.
- **[DESIGN.md](DESIGN.md):** why the pack is built this way, module layout, and the history of notable bugs.
- **[CHANGELOG.md](CHANGELOG.md):** what changed between versions.

<p align="center"><img src="docs/img/flow_which_path.svg" alt="Which path fits: All-in-One for the fastest start, Plan and Collect for your own workflow, plus pair, subsets, skip repeats and the API script"></p>

## Development

```bash
python tests/run_all.py     # all Python and JS test suites (needs numpy, Pillow, node)
ruff check . && ruff format --check .
python scripts/make_diagrams.py   # redraw docs/img/*.svg
```

The tests run without ComfyUI or torch: `tests/stubs/build_stubs.py` provides lightweight stand-ins.

## License

[MIT](LICENSE)
