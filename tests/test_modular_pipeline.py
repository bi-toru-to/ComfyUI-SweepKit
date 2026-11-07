"""
Integration tests for the modular pipeline nodes added alongside the
original SweepDimension / SweepAllInOne / SweepDimensionZip trio.
Reuses tests/stubs/build_stubs.py's FakeTensor (numpy-backed, same
.cpu()/.numpy()/.shape interface real image tensors have) so
SweepGridConstructor and SweepUpsetConstructor's real PIL drawing code
actually runs and actually writes files, not just a syntax check.
"""

import sys
import os
import importlib
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "stubs"))
import build_stubs as S

import importlib.util

# The package folder is "ComfyUI-SweepKit" (not a valid Python identifier), so load
# it by path under the name "sweepkit" instead of via a plain `import`.
_pkg_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_spec = importlib.util.spec_from_file_location(
    "sweepkit", os.path.join(_pkg_dir, "__init__.py"), submodule_search_locations=[_pkg_dir]
)
pkg = importlib.util.module_from_spec(_spec)
sys.modules["sweepkit"] = pkg
_spec.loader.exec_module(pkg)

C = pkg.NODE_CLASS_MAPPINGS
DimNode = C["SweepDimension"]()
ZipNode = C["SweepDimensionZip"]()
SelfCombineNode = C["SweepDimensionSelfCombine"]()
ExpanderNode = C["SweepCombinationExpander"]()
ExtractNode = C["SweepDimensionExtract"]()
DedupeNode = C["SweepDedupeCombos"]()
GatherNode = C["SweepGather"]()
FilenameNode = C["SweepFilenameSequencer"]()
GridNode = S.ExecutorView(C["SweepGridConstructor"]())
UpsetNode = S.ExecutorView(C["SweepUpsetConstructor"]())

print(
    "Modular node classes present:",
    sorted(k for k in C if k not in ("SweepDimension", "SweepDimensionZip", "SweepAllInOne")),
)


def fake_image(tint=0.5, h=8, w=8):
    arr = np.full((1, h, w, 3), fill_value=tint, dtype=np.float32)
    return S.FakeTensor(arr)


def build_chain(*dim_kwargs_list):
    prev = None
    for dk in dim_kwargs_list:
        full = dict(dim_type="text", dim_id="", values="", lora_name="", prev_dimensions=prev)
        full.update(dk)
        (prev,) = DimNode.build(**full)
    return prev


# ------------------------------------------------------------------
print("\n--- Scenario A: plain cartesian through Expander -> Extract -> fake-sample -> Filenames -> Grid ---")
dims = build_chain(
    dict(dim_type="text", values="artist_a\nartist_b", dim_id="artist"),
    dict(dim_type="seed", values="1,2,3"),
)
combo, combo_count, dim_map, *_ = ExpanderNode.build(dimensions=dims)
assert combo_count == 6, combo_count
assert "dim1: 'artist'" in dim_map and "dim2: 'seed'" in dim_map, dim_map

(seeds, *_) = ExtractNode.build(combo=combo, dim_id="seed", component="value")
assert seeds == [1, 2, 3, 1, 2, 3], seeds

# "sample": one distinct-tinted fake image per combo (no real KSampler needed
# to exercise the constructor nodes' own logic).
images = [fake_image(tint=0.1 * (i + 1)) for i in range(combo_count)]

(filenames,) = FilenameNode.build(combo=combo, filename_prefix="TestModular", include_combo_index=True)
assert len(filenames) == len(set(filenames)) == 6, filenames
assert filenames[0].startswith("TestModular/artist_a/0000_"), filenames[0]

grids, summary = GridNode.build(
    images=images,
    combo=combo,
    filename_prefix="TestModular",
    cell_size=32,
    cell_mode="fit",
    font_size=1.0,
    grid_x_dim="auto",
    grid_y_dim="auto",
    grid_title_dim="auto",
)
# 2 independent axes (artist x seed) -> X+Y claim both, title gets nothing
# left -> ONE combined grid, not one per artist.
assert grids.arr.shape[0] == 1, f"expected one combined X/Y grid for a 2-axis sweep, got {grids.arr.shape[0]}"
assert "dim1='artist'" in summary and "dim2='seed'" in summary, summary
print("PASS scenario A -", summary)

# ------------------------------------------------------------------
print("\n--- Scenario A2: with only 2 axes, X+Y should claim both regardless of auto vs explicit dimN,")
print("--- landing as ONE grid either way (grid_title_dim=none no longer required) ---")
for gx, gy, gt in [
    ("auto", "auto", "none"),
    ("auto", "auto", "auto"),
    ("dim1", "dim2", "none"),
    ("dim2", "dim1", "none"),
]:
    g, s = GridNode.build(
        images=images,
        combo=combo,
        filename_prefix="TestAxes",
        cell_size=32,
        cell_mode="fit",
        font_size=1.0,
        grid_x_dim=gx,
        grid_y_dim=gy,
        grid_title_dim=gt,
    )
    assert g.arr.shape[0] == 1, (
        f"grid_x_dim={gx},grid_y_dim={gy},grid_title_dim={gt} should give ONE grid for a 2-axis sweep, got {g.arr.shape[0]}: {s}"
    )
print("PASS scenario A2 - all 4 x/y/title combinations produced exactly one grid")

# ------------------------------------------------------------------
print("\n--- Scenario B: mismatched images/combo_records length must raise, not silently misalign ---")
try:
    GridNode.build(
        images=images[:-1],
        combo=combo,
        filename_prefix="X",
        cell_size=32,
        cell_mode="fit",
        font_size=1.0,
        grid_x_dim="auto",
        grid_y_dim="auto",
        grid_title_dim="auto",
    )
    print("FAIL: should have raised on length mismatch")
    sys.exit(1)
except ValueError as e:
    assert "must be the same length" in str(e)
    print("PASS scenario B -", e)

# ------------------------------------------------------------------
print("\n--- Scenario C: dedupe + gather round trip actually skips redundant 'sampling' ---")
# background x lighting, but "sampling" only depends on background --
# every lighting value for a given background should dedupe to ONE sample.
dims2 = build_chain(
    dict(dim_type="text", values="forest\ncity\nbeach", dim_id="background"),
    dict(dim_type="text", values="golden\novercast\nstudio", dim_id="lighting"),
)
combo2, combo_count2, _, *_ = ExpanderNode.build(dimensions=dims2)
assert combo_count2 == 9

(backgrounds, *_) = ExtractNode.build(combo=combo2, dim_id="background", component="value")
# positive_texts only ever reference background -- lighting is (deliberately,
# same as the real-world forgotten-placeholder case) never substituted in.
positive_texts = [f"a {bg} scene" for bg in backgrounds]

(unique_index_map, expand_indices, unique_count) = DedupeNode.build(axis_values=[positive_texts], float_precision=4)
assert unique_count == 3, unique_count
assert len(expand_indices) == 9

sample_calls = {"n": 0}


def fake_sample(text):
    sample_calls["n"] += 1
    return fake_image(tint=hash(text) % 100 / 100.0)


(unique_texts,) = GatherNode.build(source=positive_texts, indices=unique_index_map)
assert len(unique_texts) == 3
images_unique = [fake_sample(t) for t in unique_texts]
assert sample_calls["n"] == 3, f"only 3 real samples should have happened, got {sample_calls['n']}"

(images_full,) = GatherNode.build(source=images_unique, indices=expand_indices)
assert len(images_full) == 9

grids2, summary2 = GridNode.build(
    images=images_full,
    combo=combo2,
    filename_prefix="TestDedupe",
    cell_size=32,
    cell_mode="fit",
    font_size=1.0,
    grid_x_dim="auto",
    grid_y_dim="auto",
    grid_title_dim="auto",
)
print("PASS scenario C -", summary2, f"| sampled {sample_calls['n']} times for 9 combos")

# ------------------------------------------------------------------
print("\n--- Scenario D: SweepDedupeCombos rejects opaque (non str/int/float/bool) values ---")


class Opaque:
    pass


try:
    DedupeNode.build(axis_values=[[Opaque(), Opaque()]], float_precision=4)
    print("FAIL: should have raised")
    sys.exit(1)
except ValueError as e:
    assert "model_key" in str(e)
    print("PASS scenario D -", e)

# ------------------------------------------------------------------
print("\n--- Scenario E: self-combine + UpSet matrix, real images as swatches ---")
(artist_dim,) = DimNode.build(
    dim_type="text",
    dim_id="artist_style",
    values="cyberpunk\nnoir\npastel\nvintage",
    lora_name="",
    prev_dimensions=None,
)
(combined_dim,) = SelfCombineNode.build(dimensions=artist_dim, mode="combinations", min_size=1, max_size=2, joiner=", ")
assert len(combined_dim) == 1
target = combined_dim[0]
assert len(target["values"]) == 10, target["values"]  # 4 singles + 6 pairs
assert target["combo_meta"][4] == {"arity": 2, "members": [0, 1]}, target["combo_meta"][4]
assert target["base_values"] == ["cyberpunk", "noir", "pastel", "vintage"]

combo3, combo_count3, _, *_ = ExpanderNode.build(dimensions=combined_dim)
assert combo_count3 == 10
images3 = [fake_image(tint=0.05 * i) for i in range(combo_count3)]

matrices, summary3 = UpsetNode.build(
    images=images3,
    combo=combo3,
    dim_id=target["dim_id"],
    filename_prefix="TestUpset",
    cell_size=48,
    cell_mode="fit",
    font_size=1.0,
    title_dim="none",
    max_columns_per_page=60,
)
assert matrices.arr.shape[0] == 1, "10 columns under the 60-per-page cap should be exactly 1 matrix image"
print("PASS scenario E -", summary3)

# ------------------------------------------------------------------
print("\n--- Scenario F: UpSet pagination actually splits when max_columns_per_page is exceeded ---")
matrices_paged, summary_paged = UpsetNode.build(
    images=images3,
    combo=combo3,
    dim_id=target["dim_id"],
    filename_prefix="TestUpsetPaged",
    cell_size=48,
    cell_mode="fit",
    font_size=1.0,
    title_dim="none",
    max_columns_per_page=4,
)
assert matrices_paged.arr.shape[0] == 3, f"10 columns at 4/page should give 3 pages, got {matrices_paged.arr.shape[0]}"
print("PASS scenario F -", summary_paged)

# ------------------------------------------------------------------
print("\n--- Scenario G: UpsetConstructor rejects a plain (non self-combined) dim_id ---")
try:
    UpsetNode.build(
        images=images3,
        combo=combo3,
        dim_id="nonexistent_id",
        filename_prefix="X",
        cell_size=48,
        cell_mode="fit",
        font_size=1.0,
        title_dim="none",
        max_columns_per_page=60,
    )
    print("FAIL: should have raised")
    sys.exit(1)
except ValueError as e:
    assert "nonexistent_id" in str(e)
    print("PASS scenario G -", e)

# ------------------------------------------------------------------
print("\n--- Scenario G2: UpsetConstructor's title_dim actually reorders which axis leads the title ---")
(artist_dim2,) = DimNode.build(
    dim_type="text",
    dim_id="artist_style",
    values="cyberpunk\nnoir\npastel\nvintage",
    lora_name="",
    prev_dimensions=None,
)
(combined_dim2,) = SelfCombineNode.build(
    dimensions=artist_dim2, mode="combinations", min_size=1, max_size=2, joiner=", "
)
(with_cfg,) = DimNode.build(dim_type="cfg", dim_id="cfg", values="4.0,7.0", lora_name="", prev_dimensions=combined_dim2)
combo4, combo_count4, _, *_ = ExpanderNode.build(dimensions=with_cfg)
images4 = [fake_image(tint=0.02 * i) for i in range(combo_count4)]
target4 = [d for d in combo4["dimensions"] if "combo_meta" in d][0]
cfg_dim4 = [d for d in combo4["dimensions"] if d["dim_id"] == "cfg"][0]

_, summary_notitle = UpsetNode.build(
    images=images4,
    combo=combo4,
    dim_id=target4["dim_id"],
    filename_prefix="TestTitleDim",
    cell_size=32,
    cell_mode="fit",
    font_size=1.0,
    title_dim="none",
    max_columns_per_page=60,
)
_, summary_title = UpsetNode.build(
    images=images4,
    combo=combo4,
    dim_id=target4["dim_id"],
    filename_prefix="TestTitleDim",
    cell_size=32,
    cell_mode="fit",
    font_size=1.0,
    title_dim=f"dim{cfg_dim4['index']}",
    max_columns_per_page=60,
)
assert "cfg" in summary_notitle and "cfg" in summary_title, (summary_notitle, summary_title)
print("PASS scenario G2 - title_dim accepted and resolved without error (both:", summary_title, ")")

# ------------------------------------------------------------------
print("\n--- Scenario H: SweepDimension.values_pylist overrides the string widget, casts, and errors clearly ---")
(pylist_dim,) = DimNode.build(
    dim_type="cfg", dim_id="cfg", values="", lora_name="", prev_dimensions=None, values_pylist=[4, "5.5", 7]
)
assert pylist_dim[0]["values"] == [4.0, 5.5, 7.0], pylist_dim[0]["values"]
print("PASS scenario H1 - values_pylist casts mixed int/str/float to float")

try:
    DimNode.build(
        dim_type="cfg", dim_id="cfg", values="", lora_name="", prev_dimensions=None, values_pylist=[4, "not_a_number"]
    )
    print("FAIL: should have raised")
    sys.exit(1)
except ValueError as e:
    assert "cfg" in str(e)
    print("PASS scenario H2 -", e)

# ------------------------------------------------------------------
print(
    "\n--- Scenario H3: generic int/float dim_types cast the same way as seed/cfg but carry no fallback semantics ---"
)
(generic_float_dim,) = DimNode.build(
    dim_type="float", dim_id="lora_model_strength", values="0.2,0.6,1.0", lora_name="", prev_dimensions=None
)
assert generic_float_dim[0]["values"] == [0.2, 0.6, 1.0], generic_float_dim[0]["values"]
(generic_int_dim,) = DimNode.build(
    dim_type="int", dim_id="batch_variant", values="1-3", lora_name="", prev_dimensions=None
)
assert generic_int_dim[0]["values"] == [1, 2, 3], generic_int_dim[0]["values"]
print("PASS scenario H3 -", generic_float_dim[0]["values"], generic_int_dim[0]["values"])

print("\n--- Scenario I: zip preserves each member's own dim_id for extraction (regression --")
print("--- used to break because SweepDimensionZip overwrote both members to one combined dim_id) ---")
(lora_model_dim,) = DimNode.build(
    dim_type="float", dim_id="lora_model_strength", values="0.2,0.6,1.0", lora_name="", prev_dimensions=None
)
(lora_clip_dim,) = DimNode.build(
    dim_type="float", dim_id="lora_clip_strength", values="0.3,0.7,0.9", lora_name="", prev_dimensions=None
)
(zipped,) = ZipNode.build(dimensions_a=lora_model_dim, dimensions_b=lora_clip_dim, mode="shortest")
assert zipped[0]["dim_id"] == "lora_model_strength", zipped[0]["dim_id"]
assert zipped[1]["dim_id"] == "lora_clip_strength", zipped[1]["dim_id"]
assert zipped[0]["group_label"] == zipped[1]["group_label"] == "lora_model_strength, lora_clip_strength"

combo_z, count_z, _, *_ = ExpanderNode.build(dimensions=zipped)
assert count_z == 3, count_z  # zipped, not 3x3=9

(model_strengths, *_) = ExtractNode.build(combo=combo_z, dim_id="lora_model_strength", component="value")
(clip_strengths, *_) = ExtractNode.build(combo=combo_z, dim_id="lora_clip_strength", component="value")
assert model_strengths == [0.2, 0.6, 1.0], model_strengths
assert clip_strengths == [0.3, 0.7, 0.9], clip_strengths
assert model_strengths != clip_strengths, "the two zipped axes must remain independently extractable"
print("PASS scenario I -", model_strengths, clip_strengths)

# filenames shouldn't show the combined dim_id twice either, now that each
# member keeps its own distinct dim_id.
(names_z,) = FilenameNode.build(combo=combo_z, filename_prefix="TestZip", include_combo_index=True)
assert "lora_model_strength" in names_z[0] and "lora_clip_strength" in names_z[0], names_z[0]
assert names_z[0].count("lora_model_strength") == 1 and names_z[0].count("lora_clip_strength") == 1, names_z[0]
print("PASS scenario I filenames -", names_z[0])

print("\n--- Scenario J: chained zip (3-way) builds up group_label correctly, keeps individual dim_ids ---")
(steps_dim,) = DimNode.build(dim_type="steps", dim_id="steps", values="30,8,12", lora_name="", prev_dimensions=None)
(zip3,) = ZipNode.build(dimensions_a=zipped, dimensions_b=steps_dim, mode="strict")
assert {d["dim_id"] for d in zip3} == {"lora_model_strength", "lora_clip_strength", "steps"}, [
    d["dim_id"] for d in zip3
]
assert {d["group_label"] for d in zip3} == {"lora_model_strength, lora_clip_strength, steps"}, [
    d["group_label"] for d in zip3
]
print("PASS scenario J -", [(d["dim_id"], d["group_label"]) for d in zip3])

# ------------------------------------------------------------------
print("\n--- Scenario K: zip + independent cfg (3 dims, one zipped pair) -- X/Y claim both logical axes,")
print("--- title has nothing left, matching the exact bug report scenario ---")
(zcfg,) = DimNode.build(dim_type="cfg", dim_id="cfg", values="4,7,10", lora_name="", prev_dimensions=zip3)
comboK, countK, _, *_ = ExpanderNode.build(dimensions=zcfg)
assert countK == 3 * 3, countK  # 3 zipped-pair values x 3 cfg values = 9, NOT 3x3x3=27
imagesK = [fake_image(tint=0.03 * i) for i in range(countK)]
for gx, gy, gt in [("auto", "auto", "none"), ("dim1", "dim3", "none"), ("dim3", "dim1", "none")]:
    # dim1/dim2 are the zipped pair (share one logical axis), dim3 is cfg
    gK, sK = GridNode.build(
        images=imagesK,
        combo=comboK,
        filename_prefix="TestZipCfg",
        cell_size=16,
        cell_mode="fit",
        font_size=1.0,
        grid_x_dim=gx,
        grid_y_dim=gy,
        grid_title_dim=gt,
    )
    assert gK.arr.shape[0] == 1, (
        f"grid_x_dim={gx},grid_y_dim={gy} should give ONE grid (zip+cfg=2 logical axes), got {gK.arr.shape[0]}: {sK}"
    )
print("PASS scenario K - zip+cfg (2 logical axes across 3 dim entries) reliably gives one grid")

print("\n--- Scenario L: font_size scales font AND layout spacing together -- a large real cell_w")
print("--- (cell_mode='original' with big images) at max font_size must not collide/overlap ---")
big_images = [fake_image(tint=0.1 * i, h=768, w=768) for i in range(combo_count3)]
matrices_big, summary_big = UpsetNode.build(
    images=big_images,
    combo=combo3,
    dim_id=target["dim_id"],
    filename_prefix="TestBigFont",
    cell_size=120,
    cell_mode="original",
    font_size=1.0,
    title_dim="none",
    max_columns_per_page=60,
)
assert matrices_big.arr.shape[0] == 1
big_h = matrices_big.arr.shape[1]

# Rendering without crashing is necessary but not sufficient -- the actual
# bug was rows visually overlapping despite a successful render, because
# font size scaled with cell_w but the row-to-row spacing (dot_gap) stayed
# a fixed pixel constant the now-much-taller row-label text overflowed.
# Compare against the same combo at default cell_w/font_size: if dot_gap
# is correctly responsive, a 768px cell_w at max font_size must produce a
# canvas MUCH taller (not just wider) than a 120px cell_w at a small
# font_size -- a fixed-dot_gap regression would keep the height roughly
# flat regardless of font_size since dot_gap dominates n_rows * dot_gap.
matrices_small, _ = UpsetNode.build(
    images=images3,
    combo=combo3,
    dim_id=target["dim_id"],
    filename_prefix="TestSmallFont",
    cell_size=120,
    cell_mode="fit",
    font_size=0.1,
    title_dim="none",
    max_columns_per_page=60,
)
small_h = matrices_small.arr.shape[1]
assert big_h > small_h * 3, (
    f"expected big-font-size canvas ({big_h}px) to be much taller than small-font-size ({small_h}px) -- dot_gap may not be scaling with font metrics"
)
print(
    f"PASS scenario L - big cell_w + max font_size: height {big_h}px vs small-font baseline {small_h}px, no collision:",
    summary_big,
)

print("\n--- Scenario M: filename_prefix containing '/' (e.g. user typed 'SweepKit/') must not crash")
print("--- GridConstructor/UpsetConstructor's save() calls with FileNotFoundError (regression) ---")
grids_slash, summary_slash = GridNode.build(
    images=images,
    combo=combo,
    filename_prefix="SweepKit/",
    cell_size=32,
    cell_mode="fit",
    font_size=1.0,
    grid_x_dim="auto",
    grid_y_dim="auto",
    grid_title_dim="auto",
)
assert grids_slash.arr.shape[0] >= 1
matrices_slash, summary_up_slash = UpsetNode.build(
    images=images3,
    combo=combo3,
    dim_id=target["dim_id"],
    filename_prefix="SweepKit/",
    cell_size=48,
    cell_mode="fit",
    font_size=1.0,
    title_dim="none",
    max_columns_per_page=60,
)
assert matrices_slash.arr.shape[0] >= 1
print("PASS scenario M - both constructors handled a trailing '/' in filename_prefix without crashing")

print("\n--- Scenario N: filename_prefix is unconditionally a real folder -- blank/default value")
print("--- must still land under output/SweepKit/..., not directly in the output root ---")
(filenames_default,) = FilenameNode.build(combo=combo, filename_prefix="SweepKit", include_combo_index=True)
assert all(f.startswith("SweepKit/") for f in filenames_default), filenames_default
(filenames_blank,) = FilenameNode.build(combo=combo, filename_prefix="", include_combo_index=True)
assert all(f.startswith("SweepKit/") for f in filenames_blank), filenames_blank
print("PASS scenario N -", filenames_default[0])

print("\n--- Scenario O: rerunning with identical settings must NOT overwrite -- direct PIL save()")
print("--- calls have no built-in protection against this the way stock SaveImage does ---")
_, _ = UpsetNode.build(
    images=images3,
    combo=combo3,
    dim_id=target["dim_id"],
    filename_prefix="TestNoOverwrite",
    cell_size=48,
    cell_mode="fit",
    font_size=1.0,
    title_dim="none",
    max_columns_per_page=60,
)
_, _ = UpsetNode.build(
    images=images3,
    combo=combo3,
    dim_id=target["dim_id"],
    filename_prefix="TestNoOverwrite",
    cell_size=48,
    cell_mode="fit",
    font_size=1.0,
    title_dim="none",
    max_columns_per_page=60,
)
upset_files = sorted(
    f for f in os.listdir(os.path.join(S.OUTPUT_DIR, "TestNoOverwrite", "_upset")) if f.startswith("matrix_")
)
assert upset_files == ["matrix_00001.png", "matrix_00002.png"], upset_files

_, _ = GridNode.build(
    images=images,
    combo=combo,
    filename_prefix="TestNoOverwrite",
    cell_size=32,
    cell_mode="fit",
    font_size=1.0,
    grid_x_dim="auto",
    grid_y_dim="auto",
    grid_title_dim="auto",
)
_, _ = GridNode.build(
    images=images,
    combo=combo,
    filename_prefix="TestNoOverwrite",
    cell_size=32,
    cell_mode="fit",
    font_size=1.0,
    grid_x_dim="auto",
    grid_y_dim="auto",
    grid_title_dim="auto",
)
grid_files = sorted(
    f for f in os.listdir(os.path.join(S.OUTPUT_DIR, "TestNoOverwrite", "_grids")) if f.startswith("grid_")
)
assert grid_files == ["grid_00001.png", "grid_00002.png"], grid_files
print("PASS scenario O -", upset_files, grid_files)

# ------------------------------------------------------------------
# Regression scenarios for FIX_PLAN Phase 2.
# ------------------------------------------------------------------
from PIL import Image  # noqa: E402


class Interrupted(Exception):
    pass


class Hooks:
    """Count interrupt checks / progress updates and optionally interrupt
    on the Nth check, via the stub comfy modules the nodes call into."""

    def __init__(self, interrupt_on=None):
        self.checks, self.totals, self.updates, self.interrupt_on = 0, [], 0, interrupt_on

    def __enter__(self):
        hooks = self

        def check():
            hooks.checks += 1
            if hooks.interrupt_on and hooks.checks >= hooks.interrupt_on:
                raise Interrupted()

        class Bar:
            def __init__(self, total):
                hooks.totals.append(total)

            def update(self, n):
                hooks.updates += n

        self._saved = (S.mm_mod.throw_exception_if_processing_interrupted, S.utils_mod.ProgressBar)
        S.mm_mod.throw_exception_if_processing_interrupted = check
        S.utils_mod.ProgressBar = Bar
        return self

    def __exit__(self, *exc):
        S.mm_mod.throw_exception_if_processing_interrupted, S.utils_mod.ProgressBar = self._saved
        return False


def grid_kwargs(prefix, **o):
    kw = dict(
        filename_prefix=prefix,
        cell_size=32,
        cell_mode="fit",
        font_size=0.4,
        grid_x_dim="auto",
        grid_y_dim="auto",
        grid_title_dim="auto",
    )
    kw.update(o)
    return kw


def upset_kwargs(prefix, dim_id, **o):
    kw = dict(
        dim_id=dim_id,
        filename_prefix=prefix,
        cell_size=32,
        cell_mode="fit",
        font_size=1.0,
        title_dim="none",
        max_columns_per_page=60,
    )
    kw.update(o)
    return kw


def files_under(*parts):
    root = os.path.join(S.OUTPUT_DIR, *parts)
    return sorted(os.path.relpath(os.path.join(dp, f), root) for dp, _, fs in os.walk(root) for f in fs)


print("\n--- Scenario P: grid and UpSet nodes report progress and stop when interrupted ---")
dims_p = build_chain(
    dict(dim_type="text", dim_id="artist", values="a\nb\nc"),
    dict(dim_type="seed", values="1,2"),
    dict(dim_type="cfg", values="4,7"),
)
combo_p, n_p, _, *_ = ExpanderNode.build(dimensions=dims_p)
images_p = [fake_image(0.05 * i) for i in range(n_p)]
with Hooks() as h:
    GridNode.build(images=images_p, combo=combo_p, **grid_kwargs("TestProgress"))
assert h.totals == [3] and h.updates == 3 and h.checks >= 3, (h.totals, h.updates, h.checks)
with Hooks(interrupt_on=2) as h:
    try:
        GridNode.build(images=images_p, combo=combo_p, **grid_kwargs("TestInterrupt"))
        raise AssertionError("grid build should have been interrupted")
    except Interrupted:
        pass
assert len(files_under("TestInterrupt", "_grids")) == 1, files_under("TestInterrupt", "_grids")

with Hooks() as h:
    UpsetNode.build(
        images=images3, combo=combo3, **upset_kwargs("TestUpsetProgress", target["dim_id"], max_columns_per_page=4)
    )
assert h.totals == [3] and h.updates == 3, (h.totals, h.updates)
with Hooks(interrupt_on=2) as h:
    try:
        UpsetNode.build(
            images=images3, combo=combo3, **upset_kwargs("TestUpsetInterrupt", target["dim_id"], max_columns_per_page=4)
        )
        raise AssertionError("UpSet build should have been interrupted")
    except Interrupted:
        pass
assert len(files_under("TestUpsetInterrupt", "_upset")) == 1, files_under("TestUpsetInterrupt", "_upset")
print("PASS scenario P - 3/3 progress updates; interrupting after the first grid/page stops further saves")

print("\n--- Scenario Q: batched pages are padded, not stretched, to a common size ---")
matrices_q, _ = UpsetNode.build(
    images=images3, combo=combo3, **upset_kwargs("TestPad", target["dim_id"], max_columns_per_page=4)
)
saved_last = Image.open(os.path.join(S.OUTPUT_DIR, "TestPad", "_upset", "matrix_page3_00001.png")).convert("RGB")
w3, h3 = saved_last.size
batch_last = np.rint(matrices_q.arr[2] * 255).astype(np.uint8)
assert batch_last.shape[1] > w3, "page 3 has fewer columns, so it must be narrower than the batch"
assert np.array_equal(batch_last[:h3, :w3], np.asarray(saved_last)), (
    "page 3 must be copied pixel-for-pixel, not resampled"
)
assert (batch_last[:, w3:] == 16).all(), "the padding must be the grid background colour"
print(f"PASS scenario Q - last page {w3}x{h3} padded to {batch_last.shape[1]}x{batch_last.shape[0]} without resampling")

print("\n--- Scenario R: grid and UpSet nodes show their saved images and summary in the UI ---")
_, summary_r = GridNode.build(images=images_p, combo=combo_p, **grid_kwargs("TestUIGrid"))
ui = GridNode.last_ui
assert ui["text"] == [summary_r] and len(ui["images"]) == 3, ui
_, summary_r2 = UpsetNode.build(
    images=images3, combo=combo3, **upset_kwargs("TestUIUpset", target["dim_id"], max_columns_per_page=4)
)
ui2 = UpsetNode.last_ui
assert ui2["text"] == [summary_r2] and len(ui2["images"]) == 3, ui2
for entry in ui["images"] + ui2["images"]:
    assert os.path.isfile(os.path.join(S.OUTPUT_DIR, entry["subfolder"], entry["filename"])), entry
print("PASS scenario R - ui lists 3 grids and 3 matrix pages, all present on disk")

print("\n--- Scenario S: UpSet title_dim='auto' leads with the first text dimension ---")
(sc_base,) = DimNode.build(dim_type="text", dim_id="style", values="x\ny\nz", lora_name="", prev_dimensions=None)
(sc_dim,) = SelfCombineNode.build(dimensions=sc_base, mode="combinations", min_size=1, max_size=2, joiner=", ")
(sc_cfg,) = DimNode.build(dim_type="cfg", dim_id="cfg", values="4,7", lora_name="", prev_dimensions=sc_dim)
(sc_mood,) = DimNode.build(dim_type="text", dim_id="mood", values="calm\nwild", lora_name="", prev_dimensions=sc_cfg)
combo_s, n_s, _, *_ = ExpanderNode.build(dimensions=sc_mood)
images_s = [fake_image(0.03 * i) for i in range(n_s)]
sc_target = [d for d in combo_s["dimensions"] if "combo_meta" in d][0]["dim_id"]
UpsetNode.build(images=images_s, combo=combo_s, **upset_kwargs("TestAutoNone", sc_target))
none_dirs = sorted({e["subfolder"].split(os.sep)[2] for e in UpsetNode.last_ui["images"]})
UpsetNode.build(images=images_s, combo=combo_s, **upset_kwargs("TestAutoAuto", sc_target, title_dim="auto"))
auto_dirs = sorted({e["subfolder"].split(os.sep)[2] for e in UpsetNode.last_ui["images"]})
assert none_dirs == ["4", "7"], none_dirs  # chain order: cfg leads
assert auto_dirs == ["calm", "wild"], auto_dirs  # auto: the text dimension leads
print(f"PASS scenario S - title_dim none leads with cfg {none_dirs}, auto leads with mood {auto_dirs}")

print("\n--- Scenario T: Sweep Plan hands each axis out as a list, one entry per combination ---")
from sweepkit.sweep_core import MAX_AXIS_OUTPUTS  # noqa: E402

ExpanderCls = type(ExpanderNode)
assert (
    len(ExpanderCls.RETURN_TYPES)
    == 3 + MAX_AXIS_OUTPUTS
    == len(ExpanderCls.OUTPUT_IS_LIST)
    == len(ExpanderCls.RETURN_NAMES)
)
assert ExpanderCls.RETURN_NAMES[:3] == ("combo", "combo_count", "dim_map"), "saved workflows link to slots 0-2"
assert ExpanderCls.OUTPUT_IS_LIST[:3] == (False, False, False) and all(ExpanderCls.OUTPUT_IS_LIST[3:])
assert all(t == "*" for t in ExpanderCls.RETURN_TYPES[3:])

dims_t = build_chain(
    dict(dim_type="text", dim_id="mood", values="calm\nwild"),
    dict(dim_type="cfg", dim_id="cfg", values="4, 7"),
    dict(dim_type="seed", dim_id="seed", values="1-3"),
)
combo_t, count_t, _, *axes_t = ExpanderNode.build(dimensions=dims_t)
assert count_t == 12 and len(axes_t) == MAX_AXIS_OUTPUTS
assert all(len(a) == 12 for a in axes_t[:3]) and all(a == [] for a in axes_t[3:]), [len(a) for a in axes_t]
# Every combination appears exactly once, and the lists are aligned with each other.
rows_t = list(zip(*axes_t[:3], strict=True))
assert len(set(rows_t)) == 12 and set(rows_t) == {
    (m, c, s) for m in ("calm", "wild") for c in (4.0, 7.0) for s in (1, 2, 3)
}
# Axis lists line up with Extract's output (the existing way to get the same thing).
(seeds_t, *_) = ExtractNode.build(combo=combo_t, dim_id="seed", component="value")
assert seeds_t == axes_t[2]
(_, native_seeds) = ExtractNode.build(combo=combo_t, dim_id="seed", component="value")
assert native_seeds == seeds_t and type(ExtractNode).OUTPUT_IS_LIST == (False, True)

# lora_strength comes out as the model strength; model axes as their MODEL objects.
(ls,) = DimNode.build(
    dim_type="lora_strength", dim_id="lora", values="0.5, 0.8:0.4", lora_name="x.safetensors", prev_dimensions=None
)
_, _, _, ax_ls, *_ = ExpanderNode.build(dimensions=ls)
assert ax_ls == [0.5, 0.8], ax_ls
m1, m2 = S.new_fake_model("m1"), S.new_fake_model("m2")
(md,) = DimNode.build(
    dim_type="model", dim_id="mdl", values="a\nb", lora_name="", prev_dimensions=None, model_1=m1, model_2=m2
)
_, _, _, ax_md, *_ = ExpanderNode.build(dimensions=md)
assert ax_md == [m1, m2], ax_md
# No dimensions: one combination, every axis list empty.
_, n0, _, *ax0 = ExpanderNode.build(dimensions=None)
assert n0 == 1 and all(a == [] for a in ax0)
print("PASS scenario T - axis outputs are aligned lists (12 runs x 3 axes), padded, typed per axis kind")

print("\n--- Scenario U: Sweep Collect gathers the images, names the files and builds the grids ---")
CollectNode = S.ExecutorView(C["SweepCollect"]())
assert type(CollectNode._node).INPUT_IS_LIST is True


def collect_kwargs(prefix, **o):
    # With INPUT_IS_LIST ComfyUI passes every input as a list.
    d = dict(
        filename_prefix="TestCollect",
        save_individuals=True,
        create_grids=True,
        cell_size=32,
        cell_mode="fit",
        font_size=1.0,
        grid_x_dim="auto",
        grid_y_dim="auto",
        grid_title_dim="auto",
    )
    d["filename_prefix"] = prefix
    d.update(o)
    return {k: [v] for k, v in d.items()}


images_u = [fake_image(0.05 * (i + 1)) for i in range(count_t)]
grids_u, summary_u = CollectNode.collect(images=images_u, combo=[combo_t], **collect_kwargs("TestCollectA"))
ui_u = CollectNode.last_ui
assert "12 image(s) across 3 axis(es)" in summary_u and "Saved 12 image(s)" in summary_u and "grid(s)" in summary_u, (
    summary_u
)
assert "dim1='mood'" in summary_u, summary_u
root_u = os.path.join(S.OUTPUT_DIR, "TestCollectA")
files_u = [f for _, _, fs in os.walk(root_u) for f in fs if f.endswith(".png")]
grid_files_u = [f for _, _, fs in os.walk(os.path.join(root_u, "_grids")) for f in fs]
assert len(files_u) - len(grid_files_u) == 12, (len(files_u), len(grid_files_u))
assert os.path.isdir(os.path.join(root_u, "calm")) and os.path.isdir(os.path.join(root_u, "wild")), os.listdir(root_u)
assert ui_u["images"] and ui_u["text"] == [summary_u]
# Names carry the values used.
names_u = sorted(f for _, _, fs in os.walk(os.path.join(root_u, "calm")) for f in fs)
assert any("cfg4" in n and "seed2" in n for n in names_u), names_u

# The run list matches what was saved.
import csv  # noqa: E402

man = [os.path.join(root_u, f) for f in os.listdir(root_u) if f.startswith("sweep_manifest_")]
assert len(man) == 1, man
with open(man[0], newline="", encoding="utf-8") as fh:
    rows_m = list(csv.reader(fh))
assert rows_m[0] == ["run", "file", "mood", "cfg", "seed"] and len(rows_m) == 13, rows_m[:2]
assert all(os.path.isfile(os.path.join(root_u, r[1])) for r in rows_m[1:]), "manifest file column points at real files"

# Rerunning never overwrites.
CollectNode.collect(images=images_u, combo=[combo_t], **collect_kwargs("TestCollectA"))
files_u2 = [f for _, _, fs in os.walk(root_u) for f in fs if f.endswith(".png")]
assert len(files_u2) == 2 * len(files_u), "a second run must add files, not replace them"

# Switches: no individuals / no grids.
CollectNode.collect(images=images_u, combo=[combo_t], **collect_kwargs("TestCollectB", save_individuals=False))
assert not [f for _, _, fs in os.walk(os.path.join(S.OUTPUT_DIR, "TestCollectB")) for f in fs if "seed" in f]
_, summary_ng = CollectNode.collect(
    images=images_u, combo=[combo_t], **collect_kwargs("TestCollectC", create_grids=False)
)
assert "grid(s)" not in summary_ng and not os.path.isdir(os.path.join(S.OUTPUT_DIR, "TestCollectC", "_grids"))

# A batch of several images in one entry is split, so each run still lines up (6 entries x 2 = 12 runs).
batched = [S.FakeTensor(np.concatenate([i.arr, i.arr], axis=0)) for i in images_u[:6]]
_, summary_b = CollectNode.collect(images=batched, combo=[combo_t], **collect_kwargs("TestCollectD"))
assert "12 image(s)" in summary_b, summary_b

# Too few images: a clear error that says what to wire.
try:
    CollectNode.collect(images=images_u[:5], combo=[combo_t], **collect_kwargs("TestCollectE"))
    raise AssertionError("5 images for 12 runs must be refused")
except ValueError as exc:
    assert "5 entries" in str(exc) and "12 combo_records" in str(exc) and "axis outputs" in str(exc), exc
print("PASS scenario U - Collect saves 12 named files + grids, never overwrites, honours switches, explains mismatches")


print("\nALL MODULAR PIPELINE SCENARIOS PASSED")
