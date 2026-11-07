# SweepKit for ComfyUI

Multi-dimensional parameter sweeps for ComfyUI: chain one node per axis
(seed, steps, cfg, prompt text, LoRA strength, model, ...), and SweepKit
generates every combination, names the files after the values used, and
builds labelled X/Y grids.

- **All-in-one:** `Sweep All-in-One` samples, saves and builds grids in
  one node. Fastest way to start.
- **Modular:** feed stock `KSampler` / `LoraLoader` / `SaveImage` with
  per-combination lists, so changing only the grid settings doesn't
  resample anything.
- **Pair or recombine axes:** `Sweep Dimension Zip` pairs two axes value
  for value (e.g. LoRA strength with cfg); `Sweep Dimension Self-Combine`
  tries every single, pair, triple... of a list, shown as an UpSet matrix.
- **Skip duplicate work:** `Sweep Dedupe Combos` + `Sweep Gather` sample
  each distinct setting once.

## Install

Either:

- **ComfyUI Manager:** search for *SweepKit* and install, or
- **Manually:**
  ```bash
  cd ComfyUI/custom_nodes
  git clone <this repository's URL> ComfyUI-SweepKit
  ```

Then restart ComfyUI.

**Requirements**

- ComfyUI (tested with 0.31.0, frontend 1.48.7). No extra pip packages:
  torch, numpy and Pillow come with ComfyUI.
- The modular pipeline (example workflows 2–6) also needs
  [ComfyUI-List-Utils](https://github.com/godmt/ComfyUI-List-Utils) for
  its `PyList To List` / `List To PyList` / `Create PyList` nodes. The
  all-in-one node doesn't.

## Quick start

1. Load **`example_workflows/1_quickstart_all_in_one.json`** (or open it
   from ComfyUI's template browser).
2. Pick your checkpoint in **Load Checkpoint**.
3. Queue. You get 9 images (seed 1–3 × cfg 4/7/10) and one 3×3 grid in
   `output/SweepKit_quickstart/`.

To sweep something else, change a **Sweep Dimension** node's `dim_type`
and `values`, or chain another one onto it.

## Documentation

- **[NODE_GUIDE.md](NODE_GUIDE.md):** every node, input and output, plus
  step-by-step versions of the six example workflows.
- **[DESIGN.md](DESIGN.md):** why the pack is built this way, module
  layout, and the history of notable bugs.
- **[CHANGELOG.md](CHANGELOG.md):** what changed between versions.

## Development

```bash
python tests/run_all.py     # all Python and JS test suites (needs numpy, Pillow, node)
ruff check . && ruff format --check .
```

The tests run without ComfyUI or torch: `tests/stubs/build_stubs.py`
provides lightweight stand-ins.

## License

[MIT](LICENSE)
