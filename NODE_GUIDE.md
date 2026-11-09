# SweepKit Node Guide

Every SweepKit node: what it does, what each input and setting means, and step-by-step versions of the
six example workflows. For a first sweep, start with the [README](README.md) Quick start.

Nodes are named as ComfyUI shows them ("Sweep Axis"). Where a section first names a node, its internal
ID follows in parentheses, for searching older workflows: Sweep Axis (`SweepDimension`). Words in
`code font` are the names of inputs, outputs and settings as they appear on the nodes.

## Contents

- [How do I sweep a setting of my own workflow?](#sweeping-a-setting-from-the-right-click-menu)
- [Which way should I use SweepKit? Do I need ComfyUI-List-Utils?](#which-way-to-use-sweepkit)
- [How do I type values: lists, ranges, LoRA strengths?](#typing-values)
- [What does each node do?](#node-reference)
- [Step-by-step examples](#workflow-examples)
- [Why does the grid appear only at the end?](#the-grid-only-appears-at-the-end-of-the-run)
- [Something went wrong](#troubleshooting)
- [Words used in this guide](#words-used-in-this-guide)

---

## Sweeping a setting from the right-click menu

Right-click a number, choice or text setting on any node and choose **Sweep "name"…**. This works on
any node except SweepKit's own, for a setting that has no wire connected yet.

For a text box that spans several lines, such as a prompt, right-click the node's title bar or its
edge instead. Inside the text box, the browser's own menu opens. The menu then lists every text box of
the node.

SweepKit then does three things, which one Undo reverts:

1. It adds a **Sweep Plan** in a row above your nodes. Later sweeps reuse it.
2. It adds a **Sweep Axis** filled in from the setting: its type (seed, steps, cfg, int, float or
   text), its name, and 3 starting values. For a number these are the current value and the next two
   steps up; for a choice setting, the current option and the next two in the list.
3. It connects the axis to the Plan, and the Plan's matching output to the setting.

Then edit the values on the new axis. For a choice setting (sampler, LoRA file, checkpoint),
right-click the axis and choose **Pick values from the list…** to tick what to compare, instead of
typing names.

To collect the results, right-click your final image node (for example VAE Decode) and choose
**Sweep: collect results here**. This adds **Sweep Collect**, connected to the image and to the Plan's
`combo` output (which values made each image).

### What happens when you press Run

Started from the browser, the sweep runs one image at a time. SweepKit queues your workflow once per
image, and the queue panel shows each one. **Sweep Collect shows the grid so far under the node after
each image.** Files are saved as they finish. The final grids and the run list are written after the
last image. ComfyUI reuses what hasn't changed, so your models are not loaded again for every image.

**Changing only Sweep Collect's settings doesn't make new images.** After a sweep has finished, change
Collect's grid axes, cell size, font size or `filename_prefix`, and queue again. SweepKit then queues
one short run that rebuilds the grids and the run list from the images it kept in memory:

- Images already saved under the same prefix aren't saved again. A new prefix saves them there.
- A Preview Image or Save Image connected after Collect gets the new grids. This works whether you run
  the whole workflow, the Preview node, or Collect itself.
- It works for the last two finished sweeps, until ComfyUI restarts.
- Change anything else (a prompt, steps, an axis) and the whole sweep runs again, as usual.

SweepKit has to keep the images itself because each image of a live sweep is its own run, and by
default ComfyUI forgets results from earlier runs. A sweep run in one go doesn't need this: ComfyUI
already reruns only Collect.

### Running a sweep in one go

Turn off `live_grid` on Sweep Plan to run everything in one go instead: one queue entry, with the grid
at the end. A sweep started from a script always runs in one go. A sweep also runs in one go when
Sweep Plan's `combo` output goes to any node other than Sweep Collect (Sweep Axis Value, Sweep Grid,
Sweep Filenames…).

### Notes

- Sweeping a model or LoRA *file* (a loader's `unet_name`, `ckpt_name` or `lora_name`) loads each file
  in turn, so it takes as long as loading them.
- A text axis becomes a folder per value in the saved file names, so a swept choice setting shows up as
  folders named after the options.
- You can build the same wiring by hand: connect a Sweep Plan output (`axis_1`, `axis_2`…) to any input
  of the matching type.

---

## Which way to use SweepKit

**Sweep All-in-One** (`SweepAllInOne`) does everything in one node: encoding the prompts, applying
LoRAs, sampling, saving and building grids. It is the fastest way to start, and its grid fills in on
the node while it runs. Its limits: it has its own built-in sampler, and changing any of its settings
(even the grid's cell size) runs the whole sweep again.

**Sweep Plan + Sweep Collect** sweep the settings of your *own* workflow. Sweep Plan turns your axes
into one list per setting. You connect each list to the setting it changes, or let the right-click
menu do it, and ComfyUI runs those nodes once per combination. Any sampler, ControlNet or LoRA stack
works, because SweepKit never touches them. No extra node packs are needed.

**The Advanced nodes** add more ways to vary things:

- **Sweep Pair Axes:** two axes move together, value by value.
- **Sweep Subsets of a List** with **Sweep UpSet Matrix:** which items of a list work well together.
- **Sweep Skip Repeats** with **Sweep Gather:** combinations that would make the same image are made
  only once.
- **Sweep Axis Value**, **Sweep Filenames** and **Sweep Grid:** the separate pieces of what Sweep
  Collect does, for wiring with the [ComfyUI-List-Utils](https://github.com/godmt/ComfyUI-List-Utils)
  node pack. Each piece is cached on its own, so changing a grid setting rebuilds only the grid.

All three ways use the same Sweep Axis nodes to describe *what* to vary; they differ in what happens to
that description afterwards.

**ComfyUI-List-Utils is needed only** for examples 4–6 (styles that work together, skipping repeats, a
list of models) and for wiring the separate pieces by hand. Sweep All-in-One and Sweep Plan + Sweep
Collect don't need it.

---

## Node reference

The first four nodes are all most sweeps need. The [Advanced nodes](#advanced-nodes) follow.

### Sweep Axis (`SweepDimension`)

One setting to vary, with the values to try. Connect several Sweep Axis nodes one after another (a
*chain*) to vary several settings; SweepKit makes every combination of their values.

#### Typing values

| To enter | Type | Works for |
|---|---|---|
| A list | `4, 7, 10`, or one value per line | every number type |
| A range | `1-5` (1 to 5), `10-1` (counting down), `-3-2` (negative start) | seed, steps, int |
| Text | one value per line; commas stay part of the text | text, static, model labels |
| A LoRA strength | `0.8` (model and clip the same), or `0.8:0.6` (model:clip) | lora_strength |
| The limit | at most 10,000 values from one range | seed, steps, int |

The line under the values box shows what SweepKit read, for example *"3 values: 4 · 7 · 10"*, or what
is wrong and how to fix it.

#### Inputs

| Input | Type | What to enter, and what it changes |
|---|---|---|
| `dim_type` | choice | What this axis changes. See the table below. |
| `dim_id` | text | The axis name: shown in grid titles and file names, and used to pick this axis on other nodes. Blank uses the type (`seed`, `cfg`…). |
| `values` | text | The values to try (see [Typing values](#typing-values)). For a `model` axis: one label per line, and each label gets a model input below. Not used when `values_pylist` is connected. |
| `lora_name` | choice | Only for `lora_strength` with Sweep All-in-One: the LoRA whose strength is swept. |
| `prev_dimensions` *(optional)* | axis chain | Connect the previous axis. Leave it unconnected on the first axis. |
| `values_pylist` *(optional)* | PyList | A list from ComfyUI-List-Utils (**Create PyList**, **Split String**, **Create Linspace**, **List Dir**…), used instead of `values`. For a `model` axis, connect the models themselves. |

#### `dim_type` options

| Type | Values are | Use it for |
|---|---|---|
| `text` | text | Words for the prompt. With Sweep All-in-One, each text axis fills the next `{}` in the prompt. |
| `int` | whole numbers (ranges allowed) | Any whole number that isn't the sampler's seed or steps, such as width. |
| `float` | decimal numbers | Any decimal number that isn't the sampler's cfg, such as a LoRA strength or denoise. |
| `seed` | whole numbers (ranges allowed) | The sampler's seed. |
| `steps` | whole numbers (ranges allowed) | The sampler's steps. |
| `cfg` | decimal numbers | The sampler's cfg. |
| `lora_strength` | LoRA strengths | A LoRA's strength, with Sweep All-in-One. |
| `model` | models | Which model to use. |
| `static` | one fixed label | A label for the file names and grid titles that doesn't vary. |

#### Outputs

| Output | Type | Meaning |
|---|---|---|
| `dimensions` | axis chain | This axis plus every axis before it. Connect it to the next axis, or to Sweep Plan or Sweep All-in-One. |

#### Notes

- `seed`, `steps` and `cfg` read values the same way as `int` and `float`. Sweep All-in-One also
  recognizes them: it uses such an axis instead of its own `fixed_seed`, `fixed_steps` or `fixed_cfg`,
  and its grid prefers a seed axis across the columns. With Sweep Plan, any number type works for any
  setting.
- **Axis names matter on Sweep Plan's other nodes.** Sweep Axis Value and Sweep UpSet Matrix find an
  axis by its exact `dim_id`. Two axes left blank with the same type get the same name (`cfg`), and
  then can't be told apart: give each axis its own name.
- **`text` with Sweep All-in-One:** text axes fill the `{}` marks in the prompt in chain order; the
  first text axis fills the first `{}`. A `static` axis never fills one. With Sweep Plan, connect the
  axis's output to a prompt's text, or to a text-replace node.
- **`static`:** only the first line of `values` is kept, so it never adds images. Use it to label a
  whole sweep, for example with a session name.
- **`lora_strength`** is for Sweep All-in-One, which loads the LoRA named in `lora_name`. Several
  `lora_strength` axes stack, applied in chain order. With Sweep Plan, use a `float` axis per strength
  and your own Load LoRA node instead (see [example 3](#3-pair-two-lora-strengths)).
- **`model`** without `values_pylist`: each line of `values` adds a model input below the node (at most
  24; extra lines are ignored, with a message in the console). Connect one model to each.
- **`model`** with `values_pylist`: connect a list of models. Each model is then named after its file
  in file names, grid labels and the run list (for example `my_model` for `my_model.safetensors`). ComfyUI's Load
  Checkpoint and Load Diffusion Model nodes record the file; the same file twice gets ` (2)`. A model
  from a loader that records no file is named by position (`checkpoint0`, `checkpoint1`…).
- An axis with no values is skipped, with a message in the console; the rest of the chain still works.

---

### Sweep Plan (`SweepCombinationExpander`)

Turns your axes into every combination. Each axis comes out as a list that you connect to the setting
it should change; ComfyUI then runs that node once per image. The node shows how many images the sweep
will make, for example *"12 images: 2 × 3 × 2"*. It makes no images itself.

#### Inputs

| Input | Type | What to enter, and what it changes |
|---|---|---|
| `dimensions` | axis chain | Connect the last node of your chain. |
| `live_grid` | on/off (default on) | On: started from the browser, the sweep runs one image at a time, and Sweep Collect shows the grid as images finish. Off: everything runs in one go. |

#### Outputs

| Output | Type | Meaning |
|---|---|---|
| `combo` | combinations | Which values made each image. Connect it to Sweep Collect, or to the Advanced nodes that ask for `combo`. |
| `combo_count` | whole number | How many images the sweep makes. |
| `dim_map` | text | One line per axis: its position, name, type and first values. |
| `axis_1` … `axis_8` | list | The values of each axis, one per image, in order. Connect one to a setting (seed, cfg, prompt text, a model or LoRA file name…). |

#### Notes

- **Labels:** the editor shows only as many `axis_N` outputs as there are axes, labelled with the axes'
  names. When the chain goes through Sweep Pair Axes or Sweep Subsets of a List, all eight stay
  visible, in chain order.
- **Which output is which:** `axis_N` is the N-th axis of the chain; axes with no values don't count.
- **Special axis types:** a `lora_strength` axis gives its model strength (use Sweep Axis Value for the
  clip strength). A `model` axis gives the models.
- **One Plan per sweep:** the `axis_N` lists, the images Sweep Collect receives, and `combo` must all
  come from the same Plan.
- **Order of combinations:** the images are ordered so that slow changes, such as a different model,
  happen as rarely as possible, while quick ones, such as the seed, change from image to image.
- **Very large sweeps:** above 500 images, a warning appears on the node and in the console.
- **Older workflows:** the first three outputs keep their positions, so workflows saved before the
  `axis_N` outputs existed still load.

---

### Sweep Collect (`SweepCollect`)

The end of a Sweep Plan workflow. Receives the image from every run, saves each one under a name made
from the values used, builds the grids, and writes a run list. Needs no extra node packs.

#### Inputs

| Input | Type | What to enter, and what it changes |
|---|---|---|
| `images` | image | Your workflow's final image (for example VAE Decode's output). Keep `batch_size` at 1, so each run makes one image. |
| `combo` | combinations | Connect Sweep Plan's `combo` output. |
| `filename_prefix` | text (default `SweepKit`) | Folder inside ComfyUI's output folder for the images, grids and run list. Blank uses `SweepKit`. |
| `save_individuals` | on/off (default on) | Save every image as `<prefix>/<text values as folders>/<run number>_<values>_NNNNN.png`. Turn off if a Save Image node saves them. |
| `create_grids` | on/off (default on) | Build labelled grids. |
| `cell_size`, `cell_mode`, `font_size` | — | As on [Sweep Grid](#sweep-grid-sweepgridconstructor). |
| `grid_x_dim`, `grid_y_dim`, `grid_title_dim` | — | As on [Sweep Grid](#sweep-grid-sweepgridconstructor). |

#### Outputs

| Output | Type | Meaning |
|---|---|---|
| `grids` | image | All grids, as one batch. During a live sweep: the grid so far, so a Preview Image connected here fills in too. |
| `summary` | text | How many images, and where the files, grids and run list went. |

The saved grids and the summary also show on the node.

#### Notes

- **Run list:** every run that saves files also writes `sweep_manifest_NNNNN.csv` into the prefix
  folder. It has one row per image: its run number, its file (as a path inside the prefix folder) and
  the value of every axis. Open it in a spreadsheet, or read it in a script.
- **Files never replace earlier ones:** a five-digit number such as `_00001` is added to every name.
- **The wrong number of images** stops the node with a message saying what to connect.
- **Live sweeps:** when Sweep Plan runs the sweep live, this node runs once per image. Cells still to
  come show as plain tiles. After the last image it writes the grids and the run list. A sweep you
  cancel part-way keeps its saved images, but writes no grids.
- **Settings-only changes:** after a sweep finishes, changing only this node's settings rebuilds the
  grids without making new images (see [What happens when you press Run](#what-happens-when-you-press-run)).

---

### Sweep All-in-One (`SweepAllInOne`)

A whole sweep in one node, with its own sampler. While it runs, the grid so far appears on the node,
and a line under it shows how many images the connected axes will make. A run list
(`sweep_manifest_NNNNN.csv`) is written beside the images. Everything below applies to this node only.

#### Inputs

| Input | Type | What to enter, and what it changes |
|---|---|---|
| `model`, `clip`, `vae` | model | Your checkpoint's outputs. `model` is used unless a `model` axis picks another. |
| `positive_prompt` | text | The upper text box (ComfyUI doesn't label text boxes). Each `{}` is replaced by the value of a text axis, in chain order. Extra `{}` marks stay as they are. |
| `negative_prompt` | text | The lower text box. The same for every image. |
| `latent_image` | latent | Connect an Empty Latent Image; it sets the image size. |
| `text_mode` | choice | `curly`: each `{}` is replaced by the next text axis's value. `regex`: advanced; the places to fill are found with the search pattern in `text_regex`. |
| `text_regex` | text (default `\{\}`) | Only for `text_mode` regex: the search pattern. A pattern that isn't valid stops the run before any image is made. |
| `fixed_seed` | whole number (default 1) | Seed for every image, when no `seed` axis is connected. |
| `fixed_steps` | whole number (default 35) | Steps for every image, when no `steps` axis is connected. |
| `fixed_cfg` | decimal number (default 4.5) | cfg for every image, when no `cfg` axis is connected. |
| `sampler_name`, `scheduler`, `denoise` | — | As on KSampler; the same for every image. |
| `filename_prefix` | text (default `SweepKit`) | Folder inside ComfyUI's output folder for the images, grids and run list. |
| `save_individuals` | on/off (default on) | Save every image on its own, as well as the grids. |
| `create_grids` | on/off (default on) | Build and save grids. |
| `cell_size`, `cell_mode` | — | As on [Sweep Grid](#sweep-grid-sweepgridconstructor). |
| `grid_x_dim`, `grid_y_dim`, `grid_title_dim` | — | As on [Sweep Grid](#sweep-grid-sweepgridconstructor). |
| `dimensions` *(optional)* | axis chain | Connect the last axis of your chain. Leave it unconnected to make one image with the fixed settings. |

#### Outputs

| Output | Type | Meaning |
|---|---|---|
| `grids` | image | All grids, as one batch (or the image itself when `create_grids` is off). |
| `summary` | text | How many images were made, and where everything was saved. |

#### Notes

- **One of each:** connect at most one `seed`, `steps`, `cfg` and `model` axis. Each image can use only
  one value of each, so a second one stops the run with a message before any image is made. Use an
  `int` or `float` axis for other numbers.
- **LoRAs:** any number of `lora_strength` axes can be connected; they stack, each applying its own
  LoRA in chain order.
- **Memory:** building grids keeps every image in memory until the end, about 12.6 MB per
  1024 × 1024 image (about 6 GB for 500 images). For very large sweeps, turn off `create_grids`, or use
  Sweep Plan + Sweep Collect.
- **File names:** characters other than letters, digits, `-`, `_`, `.` and spaces become `_`. Windows
  device names (`CON`, `NUL`, `AUX`, `COM1`…) get a leading `_`; for example `filename_prefix` `NUL`
  saves under `_NUL`.

---

### Advanced nodes

These nodes work on lists in ways the four nodes above don't. Several of them exchange
ComfyUI-List-Utils *PyLists*; see [For the Advanced nodes: how lists move between
nodes](#for-the-advanced-nodes-how-lists-move-between-nodes).

### Sweep Pair Axes (`SweepDimensionZip`)

Makes the last axis of two chains move together, value by value (pairing), instead of trying every
mix. Use it when two settings belong together. For example, a speed-up LoRA needs fewer steps and a
lower cfg: you want *(LoRA 0, 30 steps, cfg 4.5)* and *(LoRA 1, 8 steps, cfg 1)*, not all 8 mixes.

#### Inputs

| Input | Type | What to enter, and what it changes |
|---|---|---|
| `dimensions_a` | axis chain | Connect the first axis to pair. The last axis of this chain is used. |
| `dimensions_b` | axis chain | Connect the second axis to pair; its values are matched one by one with the first axis's values. |
| `mode` | choice | `shortest`: stop at the shorter list (extra values are dropped, with a message in the console). `longest`: repeat the shorter list's last value. `strict`: stop with an error if the lists differ in length. |

#### Outputs

| Output | Type | Meaning |
|---|---|---|
| `dimensions` | axis chain | Both paired axes, plus every other axis from both chains. Connect it onward: to another axis, to a second Pair Axes to pair a third axis, or to Sweep Plan. |

#### Notes

- **Names:** each paired axis keeps its own name, so Sweep Axis Value can still take each one out
  separately. Grid titles show the two names together.
- **A third axis:** pairing the output with a third axis works; all three then move together.
- **Other axes:** axes earlier in either chain stay independent and are combined with everything as
  usual. If both inputs branch off one shared chain (`style → cfg` and `style → steps`), the shared
  axis is kept once.
- **One chain twice:** connecting the same chain to both inputs is an error.

---

### Sweep Subsets of a List (`SweepDimensionSelfCombine`)

Turns one axis's list into every subset of it: every single item, pair, triple and so on, from
`min_size` up to `max_size` items. Use it for "which of these styles work well together?" or "which of
these LoRAs combine well?". See [example 4](#4-style-combinations-and-an-upset-matrix).

#### Inputs

| Input | Type | What to enter, and what it changes |
|---|---|---|
| `dimensions` | axis chain | Connect the axis holding the list. The last axis of the chain is used. |
| `mode` | choice | `combinations`: order doesn't matter (*cyberpunk, noir* but not also *noir, cyberpunk*). `permutations`: every order too; use it if word order changes your images. |
| `min_size` | whole number (default 1) | Fewest items in a subset. 1 also includes every item on its own. |
| `max_size` | whole number (default 0) | Most items in a subset. 0 = all of them. |
| `joiner` | text (default `, `) | Text placed between the items of a subset. |

#### Outputs

| Output | Type | Meaning |
|---|---|---|
| `dimensions` | axis chain | The chain, with the list's axis replaced by its subsets. |

#### Notes

- **The new name:** the axis's name becomes `<name> (<mode>)`, for example `style (combinations)`.
  Use that name on Sweep Axis Value and Sweep UpSet Matrix.
- **Counts grow fast:** 8 items at sizes 1–3 make 8 + 28 + 56 = 92 combinations, or
  8 + 56 + 336 = 400 permutations. Check the count on Sweep Plan before you run.
- **The limit:** more than 10,000 subsets is refused, with the largest `max_size` that fits.
- **With Pair Axes:** make the subsets first, then pair them. An axis that is already paired can't be
  split into subsets.

---

### Sweep Axis Value (`SweepDimensionExtract`)

Takes one axis's values out of Sweep Plan's combinations, one value per image, for a node that should
change. Use one per axis you need.

#### Inputs

| Input | Type | What to enter, and what it changes |
|---|---|---|
| `combo` | combinations | Connect Sweep Plan's `combo` output. |
| `dim_id` | text | The name of the axis whose values you want. |
| `component` | choice | Only for a `lora_strength` axis: `model_strength` or `clip_strength` gives that strength alone, for a Load LoRA node's two strength settings. Otherwise leave it on `value`. |

#### Outputs

| Output | Type | Meaning |
|---|---|---|
| `values` | PyList | One value per image, in order, as one PyList. For ComfyUI-List-Utils nodes. |
| `list` | list | The same values as a list: connect it to any setting, and that node runs once per value. Needs no extra node packs. |

#### Notes

- It finds the axis by name, not by position, so adding or moving axes upstream doesn't change which
  axis it reads. Two axes with the same name cause an error instead of a guess.

---

### Sweep Skip Repeats (`SweepDedupeCombos`)

Finds combinations that would make the same image (for example a `lighting` axis whose word isn't in
the prompt, so every lighting value gives the same prompt) and keeps each different one once. Used with
two Sweep Gather nodes; see [example 5](#5-skip-repeated-images).

#### Inputs

| Input | Type | What to enter, and what it changes |
|---|---|---|
| `axis_values` | PyList | The values that decide what each image looks like, one list per axis (for example the prompt texts). Put the lists together with ComfyUI-List-Utils' **Create PyList**. |
| `float_precision` | whole number (default 4) | Decimal places compared for numbers: at 4, 7.5 and 7.5000001 count as the same. |

#### Outputs

| Output | Type | Meaning |
|---|---|---|
| `unique_index_map` | PyList | For each different setting, the position of its first combination. Give it to the first Sweep Gather, to keep only the images worth making. |
| `expand_indices` | PyList | For every combination, which made image it uses. Give it to the second Sweep Gather, to put the images back in every place. |
| `unique_count` | whole number | How many images will actually be made. |

#### Notes

- **Exact matches only:** it compares the values you connect, exactly. It can't know that two
  differently written settings mean the same thing (for example `lora_name` *none* and a LoRA at
  strength 0).
- **Models and LoRAs:** these can't be compared directly. Pair a text axis holding the file names with
  that axis (Sweep Pair Axes), and connect the text axis's values instead.

---

### Sweep Gather (`SweepGather`)

Takes items from a list by position, in any order and with repeats. In a skip-repeats workflow it is
used twice: first to keep only the prompts worth making, then to put the made images back into every
place.

#### Inputs

| Input | Type | What to enter, and what it changes |
|---|---|---|
| `source` | PyList | The list to take items from (images or values). |
| `indices` | PyList | Which items to take, by position (0 = first). Connect Sweep Skip Repeats' `unique_index_map` or `expand_indices`. A position that doesn't exist stops the run with an error. |

#### Outputs

| Output | Type | Meaning |
|---|---|---|
| `result` | PyList | The items, one per position in `indices`. |

---

### Sweep Filenames (`SweepFilenameSequencer`)

Makes one file name per combination from the values used, for ComfyUI's own Save Image node.

#### Inputs

| Input | Type | What to enter, and what it changes |
|---|---|---|
| `combo` | combinations | Connect Sweep Plan's `combo` output. |
| `filename_prefix` | text (default `SweepKit`) | The top folder for the file names. Blank uses `SweepKit`. |
| `include_combo_index` | on/off (default on) | Start each name with a running number, so every name is different. |

#### Outputs

| Output | Type | Meaning |
|---|---|---|
| `filenames` | PyList | One file name per combination: the prefix, then each text value as a folder, then the values. Connect it through ComfyUI-List-Utils' **PyList To List** to Save Image's `filename_prefix`. |

#### Notes

- **One name per combination:** it always makes as many names as there are combinations, even when
  Sweep Skip Repeats made fewer images. Skipping repeats saves time, not files.
- **Subsets:** an axis made by Sweep Subsets of a List doesn't become a folder: each of its values is
  used only once, so every image would get its own folder. It is still part of the file name.

---

### Sweep Grid (`SweepGridConstructor`)

Builds labelled grids from all the images of a sweep. Sweep Collect and Sweep All-in-One build their
grids the same way; this node is the separate piece, so changing a grid setting doesn't make the images
again.

#### Inputs

| Input | Type | What to enter, and what it changes |
|---|---|---|
| `images` | PyList | Every image of the sweep, in order. Turn your image output into one PyList with ComfyUI-List-Utils' **List To PyList**, then connect it here. |
| `combo` | combinations | Connect Sweep Plan's `combo` output. |
| `filename_prefix` | text (default `SweepKit`) | Folder inside ComfyUI's output folder for the grids; they go in its `_grids` folder. |
| `cell_size` | whole number (default 512) | Size of each grid cell in pixels: the longer side for `fit`, both sides for `square`. Ignored by `original`. |
| `cell_mode` | choice | `fit`: scale each image to `cell_size`, keeping its shape (recommended). `square`: stretch it to a square. `original`: keep each image's own size (the grid can get very large). |
| `font_size` | decimal number (default 0.4) | Label size compared with the cell width: 1.0 fits about 16 characters across a cell. |
| `grid_x_dim` | choice | Axis for the columns. `auto` prefers a seed axis; `none` makes one column. |
| `grid_y_dim` | choice | Axis for the rows. `auto` prefers a number axis; `none` makes one row. |
| `grid_title_dim` | choice | Axis named in each grid's title; every value gets its own grid and folder. `auto` takes what the columns and rows left; `none` = no title axis. |

#### Outputs

| Output | Type | Meaning |
|---|---|---|
| `grids` | image | All grids, as one batch. Grids of different sizes are padded with the background colour, never stretched. |
| `summary` | text | How many grids were built, where they were saved, and each axis's position. |

The saved grids also show on the node.

#### How the columns, rows and title are chosen

- **Order:** columns first, then rows, then the title, which takes only an axis nothing else needed.
  So **a sweep of two axes always makes one grid**, whether the choices are on `auto` or set by hand.
  Two paired axes count as one.
- **Preferences:** columns prefer a seed axis. Columns and rows both prefer number axes to text axes,
  so a text axis tends to become the title. They still take a text axis rather than stay empty.
- **Unusable choices:** an axis that can't take its role, such as the second axis of a pair already
  used for the columns, is replaced the same way as `auto` would choose. Only `none` leaves a role
  empty.
- **Every axis appears:** an axis not used for the columns, rows or title makes extra grids, in their
  own folders.

#### Notes

- **Axis lists:** `grid_x_dim`, `grid_y_dim` and `grid_title_dim` list the connected axes by name, and
  update as you add, remove or rename axes. An axis you picked and then renamed stays selected under
  its old name; the run then uses `auto`, with a message in the console. Two axes with the same name
  are listed by position instead (`dim1`, `dim2`…).
- **Older workflows** store positions such as `dim2`. They still work, and in the browser they turn
  into the axis name when the workflow opens. From a script, send either form.
- **Size limit:** one grid image can have at most 100 megapixels. Above that, the node stops and
  suggests `cell_mode` `fit`, a smaller `cell_size`, or another title axis to split it into smaller
  grids. The same limit applies to Sweep All-in-One, Sweep Collect and each page of Sweep UpSet Matrix.
- **Images as a PyList:** `images` must be a PyList, not one batch of images, because the images of a
  sweep don't always share one size.
- **Files never replace earlier ones:** every saved grid gets a five-digit number
  (`grid_00001.png`, `grid_00002.png`…), as Save Image does.

---

### Sweep UpSet Matrix (`SweepUpsetConstructor`)

Draws the subsets made by Sweep Subsets of a List as an UpSet matrix: one column per subset, with its
image on top and dots below marking which items it uses. A line joins each column's dots, and a thin
line runs along each row so a wide matrix is easy to follow. See
[example 4](#4-style-combinations-and-an-upset-matrix).

#### Inputs

| Input | Type | What to enter, and what it changes |
|---|---|---|
| `images` | PyList | Every image of the sweep, in order, through ComfyUI-List-Utils' **List To PyList**. |
| `combo` | combinations | Connect Sweep Plan's `combo` output. |
| `dim_id` | text | The name of the axis that goes through Sweep Subsets of a List, for example `style (combinations)`. |
| `filename_prefix` | text (default `SweepKit`) | Folder inside ComfyUI's output folder; the matrices go in its `_upset` folder. |
| `cell_size` | whole number (default 120) | Size of each image in the matrix, in pixels (see `cell_mode`). |
| `cell_mode` | choice | As on Sweep Grid: `fit` (recommended), `square` or `original`. |
| `font_size` | decimal number (default 1.0) | Label size compared with the image width: 1.0 fits about 16 characters across an image. |
| `title_dim` | choice | Another axis to name first in each matrix's title and folder. `auto` prefers a text axis; `none` keeps the chain's order. |
| `max_columns_per_page` | whole number (default 60) | Most columns in one matrix image; more columns continue in numbered files. |

#### Outputs

| Output | Type | Meaning |
|---|---|---|
| `matrices` | image | All matrix images, as one batch. A shorter last page is padded, not stretched. |
| `summary` | text | How many matrix images were built, for how many subsets and items, and where. |

The saved matrices also show on the node.

#### Notes

- **Other axes:** any other axis (cfg swept alongside the styles, say) splits the output into one
  matrix per value, as on Sweep Grid. `title_dim` only changes which axis is named first.
- **Wrong axis:** a `dim_id` that doesn't go through Sweep Subsets of a List stops the node with a
  message, instead of drawing an empty matrix.
- **Long labels:** column labels wrap onto several lines within their column. Row labels are as wide
  as the longest label, up to about 1.5 times a cell; only a longer label is cut, with "…".
- **Files never replace earlier ones:** every saved matrix gets a five-digit number
  (`matrix_00001.png`…), as Save Image does.

---

## Workflow examples

Ready-made versions of all six are in the `example_workflows` folder inside the installed SweepKit
folder. They also appear in ComfyUI's template browser: open the main menu, choose **Browse
Templates**, then under **Extensions** choose **ComfyUI-SweepKit**.

Each example uses a **Load Checkpoint** set to `model.safetensors`. Pick your own checkpoint before
you run it, and your LoRA too in example 3. Examples 4–6 need ComfyUI-List-Utils; 1–3 need no extra
node packs.

In the steps, "add" means drag a new node onto the canvas (or double-click the canvas and search for
its name), and "connect" means drag from an output to an input.

### 1. Quickest start: the all-in-one node

A first sweep: 3 seeds × 3 cfg values = 9 images and one grid. No extra node packs.
(`1_quickstart_all_in_one.json`)

1. Add a **Load Checkpoint**.
   - Pick your checkpoint in it.
2. Add a **Sweep All-in-One**.
   - Connect Load Checkpoint's `MODEL`, `CLIP` and `VAE` to its `model`, `clip` and `vae`.
   - Type your prompt in its upper text box.
   - Type the negative prompt in its lower text box.
3. Add an **Empty Latent Image**.
   - Connect its `LATENT` to Sweep All-in-One's `latent_image`.
4. Add a **Sweep Axis** for the seed.
   - Set `dim_type` to `seed`.
   - Set `values` to `1, 2, 3`.
5. Add a second **Sweep Axis** for cfg.
   - Set `dim_type` to `cfg`.
   - Set `values` to `4, 7, 10`.
   - Connect the first axis's `dimensions` to this axis's `prev_dimensions`.
   - Connect this axis's `dimensions` to Sweep All-in-One's `dimensions`. The node now reads
     *"9 images: 3 × 3"*.
6. Press **Run**. You get 9 images and one 3 × 3 grid (seed across, cfg down) in ComfyUI's output
   folder, under `SweepKit` (the default `filename_prefix`).

To sweep prompt text too: put `{}` in the prompt where the words go, and add a Sweep Axis of type
`text` to the chain.

### 2. Sweep any setting of your own workflow

Seed, cfg and the prompt of an ordinary text-to-image workflow: 2 seeds × 3 cfg values × 2 prompt
versions = 12 images, with one grid per prompt. Nothing from SweepKit touches the sampler.
(`2_sweep_any_setting.json`)

1. Open or build an ordinary workflow: **Load Checkpoint**, two **CLIP Text Encode**, **Empty Latent
   Image**, **KSampler** and **VAE Decode**.
2. Right-click the KSampler's `seed` and choose **Sweep "seed"…**. A Sweep Plan and a Sweep Axis
   appear above your nodes, and the Plan's `seed` output is connected to the KSampler's `seed`.
   - On the new axis, set `values` to `1-2`.
3. Right-click the KSampler's `cfg` and choose **Sweep "cfg"…**.
   - On the new axis, set `values` to `4, 7, 10`.
4. Right-click the title bar of the positive prompt's CLIP Text Encode and choose **Sweep "text"…**.
   - On the new axis, type one prompt version per line.
   - Set its `dim_id` to `prompt`.
5. Right-click **VAE Decode** and choose **Sweep: collect results here**. This adds Sweep Collect,
   connected to the image and to the Plan's `combo`.
   - On Sweep Collect, set `filename_prefix`. The Plan now reads *"12 images: 2 × 3 × 2"*.
6. Press **Run**. The KSampler runs 12 times. Sweep Collect saves 12 named images, one grid per
   prompt, and a run list.

To do the same by hand, connect the Plan's `axis_1`, `axis_2` and `axis_3` outputs to the settings;
they follow the axes in chain order. Other settings can be swept the same way, such as denoise, width
and height, or a LoRA's strength or file name. For the sampler, use **Pick values from the list…**.

### 3. Pair two LoRA strengths

5 paired LoRA strengths (model and clip), each tried with 3 cfg values: 15 images, not 75. Uses a real
Load LoRA node. (`3_pair_lora_strengths.json`)

1. Build the workflow of example 2.
2. Add a **Load LoRA**.
   - Pick your LoRA in it.
   - Connect Load Checkpoint's `MODEL` and `CLIP` to its `model` and `clip`.
   - Connect its `MODEL` to the KSampler's `model`.
   - Connect its `CLIP` to both CLIP Text Encode nodes.
3. Add a **Sweep Axis** for the model strength.
   - Set `dim_type` to `float` (not `cfg`: this number isn't the sampler's cfg).
   - Set `dim_id` to `lora_model`.
   - Set `values` to `0.2, 0.4, 0.6, 0.8, 1.0`.
4. Add a second **Sweep Axis** for the clip strength. Don't connect it to the first axis.
   - Set `dim_type` to `float`.
   - Set `dim_id` to `lora_clip`.
   - Set `values` to `0.3, 0.5, 0.6, 0.7, 0.9`.
5. Add a **Sweep Pair Axes**.
   - Connect the first axis to `dimensions_a`.
   - Connect the second axis to `dimensions_b`.
   - Leave `mode` on `shortest`.
6. Add a third **Sweep Axis** for cfg.
   - Set `dim_type` and `dim_id` to `cfg`, and `values` to `4, 7, 10`.
   - Connect Sweep Pair Axes' `dimensions` to its `prev_dimensions`.
7. Add a **Sweep Plan**.
   - Connect the third axis to it. It should read *"15 images"* (5 pairs × 3 cfg); 75 would mean the
     strengths aren't paired.
   - Connect its `axis_1` to Load LoRA's `strength_model`.
   - Connect its `axis_2` to Load LoRA's `strength_clip`.
   - Connect its `axis_3` to the KSampler's `cfg`. (Because the chain goes through Pair Axes, all
     eight `axis_N` outputs show; the three axes are `axis_1` to `axis_3`, in chain order.)
8. Add a **Sweep Collect**.
   - Connect VAE Decode's image to `images`.
   - Connect the Plan's `combo` to `combo`.
9. Press **Run**. Load LoRA and the KSampler each run 15 times. One grid comes out (the paired
   strengths are one axis, cfg the other), with the named images and the run list.

### 4. Style combinations and an UpSet matrix

Every single style, pair and triple from a list of 4 styles (14 subsets), shown as an UpSet matrix.
Needs ComfyUI-List-Utils. (`4_style_combinations_upset.json`)

1. Add a **Load Checkpoint**, **Empty Latent Image**, **KSampler** and **VAE Decode**, connected as
   usual.
2. Add a **CLIP Text Encode** for the negative prompt.
   - Connect its output to the KSampler's `negative`.
3. Add a **Sweep Axis** for the styles.
   - Set `dim_type` to `text` and `dim_id` to `style`.
   - In `values`, type one style per line:
     ```
     cyberpunk
     noir
     pastel
     vintage
     ```
4. Add a **Sweep Subsets of a List**.
   - Connect the axis to its `dimensions`.
   - Set `mode` to `combinations`, `min_size` to 1, `max_size` to 3 and `joiner` to `, `.
5. Add a **Sweep Plan**.
   - Connect Sweep Subsets' `dimensions` to it. It should read *"14 images"* (4 + 6 + 4).
6. Add a **Sweep Axis Value**.
   - Connect the Plan's `combo` to it.
   - Set `dim_id` to `style (combinations)`: Sweep Subsets added `(combinations)` to the name.
7. Add a ComfyUI-List-Utils **PyList To List**.
   - Connect Sweep Axis Value's `values` to it.
8. Add ComfyUI's **Replace Text** node.
   - Set its `string` to a prompt with a marker, such as `masterpiece, a lighthouse at sunset,
     __style__`.
   - Set its `find` to `__style__`.
   - Connect PyList To List's output to its `replace`. Replace Text now runs once per subset.
9. Add a **CLIP Text Encode** for the positive prompt.
   - Connect Replace Text's output to its `text`.
   - Connect its output to the KSampler's `positive`.
10. Add a ComfyUI-List-Utils **List To PyList**.
    - Connect VAE Decode's `IMAGE` to it. This turns the 14 images into one list.
11. Add a **Sweep UpSet Matrix**.
    - Connect List To PyList's output to `images`.
    - Connect the Plan's `combo` to `combo`.
    - Set `dim_id` to `style (combinations)`.
    - Set `filename_prefix` to a folder name.
12. Press **Run**. You get one matrix image of 14 columns, in groups of 1, 2 and 3 styles, each with its
    image on top and dots marking its styles.

To also save the 14 images with names:

1. Add a **Sweep Filenames**.
   - Connect the Plan's `combo` to it.
2. Add a **PyList To List** after it.
3. Add a **Save Image**.
   - Connect VAE Decode's image to its `images`.
   - Connect the PyList To List output to its `filename_prefix`.

For a plain grid as well, add a **Sweep Grid**, with List To PyList's output as `images` and the Plan's
`combo` as `combo`.

For every order of the styles as well, set Sweep Subsets' `mode` to `permutations`; nothing else
changes. The count grows: the same 4 styles at sizes 1–3 make 4 + 12 + 24 = 40 images.

If you also sweep another axis (say cfg), each of its values makes its own matrix. Sweep UpSet
Matrix's `title_dim` only changes which axis is named first in the title.

### 5. Skip repeated images

When one axis doesn't change the image for some combinations. Here the axes are `background` ×
`lighting`, but the prompt only uses `__background__`, so every lighting value would make the same
image again. Needs ComfyUI-List-Utils. (`5_dedupe_gather.json`)

1. Build the workflow of example 4 up to step 5, with one change: instead of the style axis and Sweep
   Subsets, use two **Sweep Axis** nodes of type `text`, connected one after the other.
   - `background`: `beach`, `forest`, `city street`
   - `lighting`: `dawn`, `noon`, `dusk`

   Don't pair them: you want all 3 × 3 combinations.
2. Add two **Sweep Axis Value** nodes.
   - Connect the Plan's `combo` to both.
   - Set one's `dim_id` to `background` and the other's to `lighting`.
   - Give each a **PyList To List** after it.
3. Add a **Replace Text** for the background.
   - Set its `string` to your prompt and its `find` to `__background__`.
   - Connect the background values to its `replace`.
4. Add a second **Replace Text** for the lighting.
   - Connect the first Replace Text's output to its `string`.
   - Set its `find` to `__lighting__`.
   - Connect the lighting values to its `replace`.
5. Add a **List To PyList**.
   - Connect the second Replace Text's output to it. This is the list of 9 prompts.
6. Add a ComfyUI-List-Utils **Create PyList**.
   - Connect the list of prompts to its first input. (To also compare other values, such as cfg,
     connect their Sweep Axis Value lists to further inputs.)
7. Add a **Sweep Skip Repeats**.
   - Connect Create PyList's output to `axis_values`.
8. Add a **Sweep Gather** to keep only the different prompts.
   - Connect the list of prompts to `source`.
   - Connect Skip Repeats' `unique_index_map` to `indices`.
9. Add a **PyList To List** after that Sweep Gather.
   - Connect its output to the positive CLIP Text Encode's `text`. The KSampler and VAE Decode now run
     only once per different prompt.
10. Add a **List To PyList** after VAE Decode, to gather the made images into one list.
11. Add a second **Sweep Gather** to put the images back in every place.
    - Connect that image list to `source`.
    - Connect Skip Repeats' `expand_indices` to `indices`. Its result has one image for every
      combination again.
12. Connect that result to a **Sweep Grid** (with the Plan's `combo`), and save the images as at the
    end of example 4. These nodes don't need to know that repeats were skipped.

What the example makes: **only 3 images are generated** (one per background), but the grid is still
the full **3 × 3, 9 cells**, and 9 files are saved. Each image appears in the 3 lighting cells of its
background, so those cells look the same. That is expected: the grid shows which combinations shared
one image. Add `__lighting__` to the prompt, and all 9 cells become different images.

### 6. A list of models without model inputs

Sweep 3 checkpoints by putting them into one list with ComfyUI-List-Utils, instead of using the Sweep
Axis's own model inputs. Needs ComfyUI-List-Utils. (`6_model_list_pylist.json`)

1. Add three **Load Checkpoint** nodes.
   - Pick a different checkpoint in each.
2. Add a ComfyUI-List-Utils **Create PyList**.
   - Connect each Load Checkpoint's `MODEL` to one of its inputs (it adds an input each time you fill
     the last one).
3. Add a **Sweep Axis** for the models.
   - Set `dim_type` to `model` and `dim_id` to `checkpoint`. Leave `values` empty.
   - Connect Create PyList's output to its `values_pylist`.
4. Add a second **Sweep Axis** for the seed.
   - Set `dim_type` to `seed` and `values` to `1, 2`.
   - Connect the first axis's `dimensions` to its `prev_dimensions`.
5. Add a **Sweep Plan**.
   - Connect the seed axis to it.
6. Add a **Sweep Axis Value** for the models.
   - Connect the Plan's `combo` to it, and set `dim_id` to `checkpoint`. Its output is the models, one
     per image.
   - Connect its `values` through a **PyList To List** to the KSampler's `model` (or a Load LoRA's, if
     you also sweep LoRAs).
7. Add a **Sweep Axis Value** for the seed.
   - Connect the Plan's `combo` to it, and set `dim_id` to `seed`.
   - Connect its `values` through a **PyList To List** to the KSampler's `seed`.
8. Save the images and build the grid as at the end of example 4.

File names, grid labels and the run list name each model after its file (for example
`my_model`). For models that come as separate files (Flux and similar), use **Load
Diffusion Model** nodes instead of Load Checkpoint.

---

## For the Advanced nodes: how lists move between nodes

Skip this unless you use the Advanced nodes. Sweep All-in-One and Sweep Plan + Sweep Collect handle all
of it for you.

### The axis chain

Every sweep starts as a chain of Sweep Axis nodes, each describing one axis. Each axis takes the
previous axis's output as its `prev_dimensions` input, and passes all of them plus itself on as its
`dimensions` output, like a LoRA stacker. The last axis of the chain is what you connect onward: to
Sweep All-in-One, or to Sweep Plan. The type of these connections is `SWEEP_DIMS`.

### PyLists and lists

ComfyUI-List-Utils and several Advanced nodes pass a **PyList**: a whole list held as one item. That
lets a node see the whole list at once, which building a grid needs.

ComfyUI's own **list** works differently: it holds one item at a time, and ComfyUI runs the next node
once per item. This is how a stock KSampler makes an image for every combination when it receives a
list of seeds, with nothing special in the KSampler.

You convert between the two with ComfyUI-List-Utils:

- **PyList → list:** use **PyList To List** right before an input of an ordinary node that should get
  one value per combination (a KSampler's `seed`, Load LoRA's `strength_model`, Save Image's
  `filename_prefix`…).
- **list → PyList:** use **List To PyList** after VAE Decode, because Sweep Grid and Sweep UpSet Matrix
  need all the images at once.

An input of type `PYLIST` wants a PyList. If you connect a list to it instead, the wire connects, but
ComfyUI then runs that node once per item, which is not what you want. Keep PyLists between SweepKit
nodes, and convert to a list only right before an ordinary node.

### `combo`: which values made each image

Sweep Plan's `combo` output carries two things together: the axes, and one record per combination
saying which value of each axis it uses. Every node after the Plan (Sweep Collect, Sweep Axis Value,
Sweep Filenames, Sweep Grid, Sweep UpSet Matrix) takes this one `combo` input. Because the two parts
travel together, they can't be mixed up between two Plans. You never need to open or build a `combo`:
pass it on.

---

## Troubleshooting

**Red or missing nodes when I open example 4, 5 or 6** — Those examples use the ComfyUI-List-Utils
node pack, which isn't installed. In ComfyUI, open **Manager → Custom Nodes Manager**, search for
*ComfyUI-List-Utils*, install it, restart ComfyUI, and reload the page.

**"model.safetensors is missing", or "Value not in list: ckpt_name: 'model.safetensors'"** — The
examples ship with a placeholder checkpoint name. In every **Load Checkpoint** (three in example 6),
pick one of your own checkpoints, and pick your LoRA in example 3's **Load LoRA**.

**"… the range '1-20000' in values makes 20,000 values, more than the limit of 10,000"** (on the axis:
*"'1-20000' is over 10,000 values: shorten it"*) — One range may give at most 10,000 values. Use a
shorter range, or fewer values. The limit protects you from a sweep far larger than intended.

**There is no "Sweep …" item when I right-click a setting** — Only a number, choice or text setting
with no wire connected, on a node that isn't SweepKit's own, gets the item. Right-click the setting
itself, not the node's title (except for a text box that spans several lines). Reload the page after
installing or updating SweepKit.

**"[Sweep Collect] got N images for M combinations from Sweep Plan"** (also on Sweep Grid or Sweep
UpSet Matrix) — The workflow made a different number of images than the Plan planned.

- With Sweep Collect: check that every `axis_N` output you connected comes from this Plan, that the
  final image goes to Collect, and that `batch_size` is 1.
- With Sweep Grid or Sweep UpSet Matrix after Sweep Skip Repeats: check that the images go through the
  second Sweep Gather (with `expand_indices`), so every combination gets its image back.

**A setting I connected to the Plan runs only once** — The Plan's output must reach the node that makes
the image, directly or through other nodes. A connection that ends at a node nothing depends on never
runs.

### The grid only appears at the end of the run

Check three things:

- `live_grid` is on for Sweep Plan;
- you started the run from the browser (a script runs the sweep in one go);
- Sweep Plan's `combo` goes only to Sweep Collect (any other node reading it makes the sweep run in one
  go).

Then the grid shows under Sweep Collect after each image. Sweep All-in-One always shows its grid on the
node as it fills.

**"dim_id is 'X', but no axis has that name"** — A Sweep Axis Value or Sweep UpSet Matrix asks for an
axis name that no axis has. Check for typos; the message lists the names that exist. Remember that
Sweep Subsets of a List adds ` (combinations)` or ` (permutations)` to the name.

**"dim_id is 'X', but 2 axes have that name"** — Two Sweep Axis nodes have the same `dim_id`, or both
are blank with the same type. Give each its own name.

**"list N in axis_values holds models or other objects, which can't be compared directly"** — You
connected a model or LoRA axis's values to Sweep Skip Repeats. Pair a text axis holding the file
names with that axis (Sweep Pair Axes), and connect the text axis's values instead.

**A sweep of two axes comes out as more than one grid** — Check whether `grid_title_dim` names an axis
instead of `auto` or `none`. A title axis you pick is used even if that splits the sweep into several
grids. Leave it on `auto` (or `none`) to get one grid.

**The grid uses the "wrong" axis for the columns or rows** — Check the console. A choice that names no
connected axis (one you renamed or removed since) falls back to `auto`, with a message. Pick the axis
again from the list. Two axes with the same name can't be told apart by name: rename one, or pick it
by position (`dim1`, `dim2`…, as `dim_map` lists them).

**Running Sweep Collect on its own (its Run button) doesn't update the Preview Image after it** —
Since 1.1, SweepKit also runs the Preview and Save nodes connected after Collect. Reload the page if
you still see it.

**Nothing happens when I connect ComfyUI-List-Utils' Split String to `values_pylist`** — Check which of
its two outputs you used. `values_pylist` needs the `PYLIST` output, not the `STRING` list one. The list
output makes ComfyUI run the Sweep Axis once per line, instead of giving it the whole list.

---

## Words used in this guide

| Word | Meaning |
|---|---|
| **axis** | One setting to vary, with the list of values to try. |
| **chain** | Axis nodes connected one after another; together they describe the sweep. |
| **combination** | One value from each axis; together they make one image. |
| **sweep** | A batch of images made by trying every combination of axis values. |
| **axis name** (`dim_id`) | The name you give an axis; it labels grids, files and outputs. |
| **setting** | A value on a node that you type or choose, such as cfg. |
| **Sweep Plan** | The node that turns your axes into the list of combinations. |
| **Sweep Collect** | The node that receives every image, saves it, and builds the grids. |
| **run list** | A spreadsheet file listing each image, its file name and its values. |
| **live grid** | The grid shown on the node, filling in as each image finishes. |
| **pair** | Moving two axes together, value by value, instead of trying every mix. |
| **subsets** | Every single item, pair, triple and so on from one list. |
| **skip repeats** | Making each different image only once, even when combinations would repeat it. |
| **gather** | Taking items from a list by position, to put images back in order. |
| **UpSet matrix** | A chart with one column per subset; dots show which items it uses. |
| **PyList** | A list passed between nodes as one item, used by ComfyUI-List-Utils. |
| **placeholder** | A mark in the prompt, such as `{}` or `__style__`, that a value replaces. |
| **regex** | A search pattern language; only needed for Sweep All-in-One's `text_mode` regex. |
| **template browser** | ComfyUI's list of ready-made workflows, opened from ComfyUI's main menu. |
| **output folder** | The folder where ComfyUI saves images, normally `ComfyUI/output`. |

---

This guide covers SweepKit 1.1.0, last checked 2026-11-10.

Problems or questions? Open an issue: ISSUES_URL <!-- RELEASE: issues URL -->
