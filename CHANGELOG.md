# Changelog

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
