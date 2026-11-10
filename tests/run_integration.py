import sys
import os
import importlib

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

DimNode = pkg.NODE_CLASS_MAPPINGS["SweepDimension"]
MainNode = pkg.NODE_CLASS_MAPPINGS["SweepAllInOne"]
print("Package imported OK. Nodes:", list(pkg.NODE_CLASS_MAPPINGS.keys()))

# ---- sanity check INPUT_TYPES for both ----
dim_it = DimNode.INPUT_TYPES()
assert "dim_type" in dim_it["required"]
assert "values" in dim_it["required"]
assert "lora_name" in dim_it["required"]
assert "prev_dimensions" in dim_it["optional"]
print("SweepDimension INPUT_TYPES OK")

main_it = MainNode.INPUT_TYPES()
assert "num_dimensions" not in main_it["required"], "num_dimensions should be GONE from the main node"
assert "dim1_type" not in main_it["required"], "dimN_type widgets should be GONE from the main node"
assert "dimensions" in main_it["optional"]
print("SweepAllInOne INPUT_TYPES OK -", len(main_it["required"]), "required entries (down from 53)")

dim_node = DimNode()
main_node = S.ExecutorView(MainNode())


def base_kwargs(**overrides):
    d = dict(
        model=S.FAKE_MODEL,
        clip=S.FAKE_CLIP,
        vae=S.FAKE_VAE,
        positive_prompt="masterpiece, {}, 1girl, {}",
        negative_prompt="worst quality",
        latent_image=S.make_fake_latent(8, 8),
        text_mode="curly",
        text_regex=r"\{\}",
        fixed_seed=1,
        fixed_steps=20,
        fixed_cfg=5.0,
        sampler_name="euler",
        scheduler="normal",
        denoise=1.0,
        filename_prefix="TestXY",
        save_individuals=True,
        create_grids=True,
        cell_size=64,
        cell_mode="fit",
        grid_x_dim="auto",
        grid_y_dim="auto",
        grid_title_dim="auto",
    )
    d.update(overrides)
    return d


def build_chain(*dim_kwargs_list):
    """Chain N SweepDimension.build() calls the way the graph would."""
    prev = None
    for dk in dim_kwargs_list:
        full = dict(dim_type="text", dim_id="", values="", lora_name="", prev_dimensions=prev)
        full.update(dk)
        (prev,) = dim_node.build(**full)
    return prev


# ------------------------------------------------------------------
print("\n--- Scenario 1: no dimensions connected (degenerate single image) ---")
kw = base_kwargs(dimensions=None)
grids, summary = main_node.generate(**kw)
print(summary)
assert grids.arr.shape[0] == 1
print("PASS scenario 1")

# ------------------------------------------------------------------
print("\n--- Scenario 2: text x seed via two chained SweepDimension nodes ---")
dims = build_chain(
    dict(dim_type="text", values="style_a\nstyle_b", dim_id="style"),
    dict(dim_type="seed", values="1,2,3"),
)
assert len(dims) == 2 and dims[0]["index"] == 1 and dims[1]["index"] == 2
S.sample_counter["n"] = 0
kw = base_kwargs(dimensions=dims)
grids, summary = main_node.generate(**kw)
print(summary)
assert S.sample_counter["n"] == 6, S.sample_counter["n"]
# With exactly 2 independent axes (text x seed), X+Y now claim both and
# title is left with nothing -- ONE combined 2x3 grid, not one grid per
# style. (This is the fixed behavior: title used to auto-fill first and
# grab the text axis before X/Y got a turn, splitting a 2-axis sweep into
# multiple single-row grids by default.)
assert grids.arr.shape[0] == 1, f"expected one combined X/Y grid for a 2-axis sweep, got {grids.arr.shape[0]}"
print("PASS scenario 2 - sample() called", S.sample_counter["n"], "times, grids:", grids.arr.shape[0])

# ------------------------------------------------------------------
print("\n--- Scenario 3: skipped (empty) dimension in the middle renumbers cleanly ---")
dims = build_chain(
    dict(dim_type="text", values="a\nb", dim_id="style"),
    dict(dim_type="seed", values=""),  # empty -> skipped, doesn't consume an index
    dict(dim_type="cfg", values="4,7"),
)
assert len(dims) == 2, "the empty seed dimension should have been dropped, got %d dims" % len(dims)
assert dims[0]["type"] == "text" and dims[0]["index"] == 1
assert dims[1]["type"] == "cfg" and dims[1]["index"] == 2, (
    "cfg should renumber to index 2, not 3, got %d" % dims[1]["index"]
)
print("PASS scenario 3 - skipped dimension does not leave a gap:", [(d["type"], d["index"]) for d in dims])

# ------------------------------------------------------------------
print("\n--- Scenario 4: 'model' dimension via dynamically-named sockets on the DIMENSION node ---")
model_base = S.new_fake_model("Base")
model_turbo = S.new_fake_model("Turbo")
(single_model_dim,) = dim_node.build(
    dim_type="model",
    dim_id="checkpoint",
    values="Base\nTurbo\nUnwired",
    lora_name="",
    prev_dimensions=None,
    model_1=model_base,
    model_2=model_turbo,  # model_3 deliberately unconnected
)
assert len(single_model_dim) == 1
md = single_model_dim[0]
assert md["type"] == "model" and md["values"] == ["Base", "Turbo", "Unwired"]
assert md["model_objs"] == [model_base, model_turbo, None], (
    "unconnected slot must come through as None from SweepDimension, resolved later by the main node"
)
S.sample_counter["n"] = 0
kw = base_kwargs(dimensions=single_model_dim)
grids, summary = main_node.generate(**kw)
print(summary)
assert S.sample_counter["n"] == 3
print("PASS scenario 4 - main node resolved the unconnected 3rd slot to its own base model")

# ------------------------------------------------------------------
print("\n--- Scenario 5: lora_strength dimension ---")
dims = build_chain(
    dict(dim_type="lora_strength", values="0.0\n0.5\n1.0", dim_id="lora_str", lora_name="loraA.safetensors"),
)
S.sample_counter["n"] = 0
kw = base_kwargs(dimensions=dims)
grids, summary = main_node.generate(**kw)
print(summary)
assert S.sample_counter["n"] == 3
print("PASS scenario 5")

# ------------------------------------------------------------------
print("\n--- Scenario 6: caching sanity — model(outer) x lora_strength x seed(inner), chained across 3 nodes ---")
model_a = S.new_fake_model("A")
model_b = S.new_fake_model("B")
(after_model,) = dim_node.build(
    dim_type="model", dim_id="ckpt", values="A\nB", lora_name="", prev_dimensions=None, model_1=model_a, model_2=model_b
)
(after_lora,) = dim_node.build(
    dim_type="lora_strength",
    dim_id="lora_str",
    values="0.5,1.0",
    lora_name="loraA.safetensors",
    prev_dimensions=after_model,
)
(after_seed,) = dim_node.build(dim_type="seed", dim_id="", values="1,2,3", lora_name="", prev_dimensions=after_lora)
assert [d["index"] for d in after_seed] == [1, 2, 3]

S.sample_counter["n"] = 0
S.lora_apply_counter["n"] = 0
S.encode_counter["n"] = 0
kw = base_kwargs(dimensions=after_seed, grid_x_dim="dim3", grid_y_dim="dim2", grid_title_dim="dim1")
grids, summary = main_node.generate(**kw)
print(summary)
assert S.sample_counter["n"] == 12, S.sample_counter["n"]
assert S.lora_apply_counter["n"] == 4, S.lora_apply_counter["n"]  # not 12
assert S.encode_counter["n"] == 8, S.encode_counter["n"]  # not 24
print(
    f"PASS scenario 6 - sample()={S.sample_counter['n']}, lora_apply={S.lora_apply_counter['n']} (not 12!), clip_encode={S.encode_counter['n']} (not 24!)"
)

# ------------------------------------------------------------------
print("\n--- Scenario 7: bad seed value raises a clear error (now right at the SweepDimension node itself) ---")
try:
    build_chain(dict(dim_type="seed", values="1,2,notanumber", dim_id="seed"))
    print("FAIL: expected ValueError")
    sys.exit(1)
except ValueError as e:
    assert "seed" in str(e) and "notanumber" in str(e)
    print("PASS scenario 7 - raised:", e)

# ------------------------------------------------------------------
print("\n--- Scenario 8: seed range syntax '1-5' ---")
dims = build_chain(dict(dim_type="seed", values="1-5", dim_id="seed"))
S.sample_counter["n"] = 0
main_node.generate(**base_kwargs(dimensions=dims))
assert S.sample_counter["n"] == 5
print("PASS scenario 8")

# ------------------------------------------------------------------
print("\n--- Scenario 9: unknown lora file raises a clear error ---")
dims = build_chain(
    dict(dim_type="lora_strength", values="1.0", dim_id="lora_str", lora_name="doesNotExist.safetensors")
)
try:
    main_node.generate(**base_kwargs(dimensions=dims))
    print("FAIL: expected ValueError")
    sys.exit(1)
except ValueError as e:
    assert "doesNotExist" in str(e)
    print("PASS scenario 9 - raised:", e)

# ------------------------------------------------------------------
print("\n--- Scenario 10: many chained dimensions (beyond the old 8-dimension cap) ---")
kwargs_list = [dict(dim_type="static", values=f"tag{i}", dim_id=f"d{i}") for i in range(1, 11)]  # 10 dims
dims = build_chain(*kwargs_list)
assert len(dims) == 10
S.sample_counter["n"] = 0
main_node.generate(**base_kwargs(dimensions=dims))
assert S.sample_counter["n"] == 1  # static dims each contribute exactly 1 value -> 1 combo total
print("PASS scenario 10 - 10 chained dimensions handled fine, no MAX_DIMENSIONS constraint anymore")

print("\nALL INTEGRATION SCENARIOS PASSED")

# ------------------------------------------------------------------
print("\n--- Scenario 11: fixed_seed pins the seed when no seed dimension is chained ---")
dims = build_chain(dict(dim_type="static", values="only", dim_id="d"))
kw = base_kwargs(dimensions=dims, fixed_seed=777, save_individuals=True)
main_node.generate(**kw)
saved = (
    os.listdir(S.OUTPUT_DIR + "/TestXY/only")
    if os.path.isdir(S.OUTPUT_DIR + "/TestXY/only")
    else os.listdir(S.OUTPUT_DIR + "/TestXY")
)
assert any("seed777" in f for f in saved), f"expected a file with seed777 in it, got {saved}"
print("PASS scenario 11 - fixed_seed=777 was actually used:", saved)

print("\nALL EXTRA SCENARIOS PASSED")

# ------------------------------------------------------------------
print("\n--- Scenario 12: encode() uses the complete conditioning path, not a hand-rolled partial one ---")
# Direct, explicit regression test for TWO conditioning bugs found in
# production, back to back:
#  v1: encode() returned a bare (cond, pooled) tuple -> crashed with
#      "IndexError: index 1 is out of bounds for dimension 0 with size 1"
#      inside real ComfyUI's conditioning-hooks code.
#  v2: fixed the *shape* by hand-wrapping as [[cond, {"pooled_output":...}]]
#      -> stopped the crash, but produced pure-noise output on a
#      FLOW-matching model with a custom text encoder, because a
#      hand-rolled dict can be missing extra keys that architecture
#      actually needs to modulate on.
# v3 (current) uses clip.encode_from_tokens_scheduled() -- the same method
# the real, stock CLIPTextEncode node uses -- so it picks up whatever
# extra fields a given CLIP implementation actually attaches, instead of
# guessing. FakeClip's encode_from_tokens_scheduled stands in for "a real
# CLIP that attaches something our hand-rolled dict wouldn't have known
# to include" via extra_field_real_clip_would_add.
result = main_node.encode(S.FAKE_CLIP, "a test prompt")
assert isinstance(result, list) and len(result) == 1, f"expected one conditioning entry, got {result!r}"
entry = result[0]
assert isinstance(entry, list) and len(entry) == 2, f"each entry must be [cond, extra_dict], got {entry!r}"
assert isinstance(entry[1], dict) and "pooled_output" in entry[1], (
    f"extra dict must carry pooled_output, got {entry[1]!r}"
)
assert entry[1].get("extra_field_real_clip_would_add") is True, (
    "encode() should be going through encode_from_tokens_scheduled() (which real ComfyUI's "
    "CLIPTextEncode uses) so architecture-specific extras survive -- got a dict missing that "
    "field, which means it silently fell back to the incomplete hand-rolled wrap instead."
)
print(
    "PASS scenario 12 - encode() goes through encode_from_tokens_scheduled(), preserving extras a hand-rolled dict would drop"
)

print("\n--- Scenario 13: encode() still falls back correctly for a CLIP without encode_from_tokens_scheduled ---")


class _OldStyleClip:
    def tokenize(self, text):
        return {"text": text}

    def encode_from_tokens(self, tokens, return_pooled=True):
        return (f"COND[{tokens['text']}]", {"pooled": True})


result = main_node.encode(_OldStyleClip(), "a test prompt")
assert isinstance(result, list) and len(result) == 1
assert isinstance(result[0], list) and len(result[0]) == 2
assert isinstance(result[0][1], dict) and "pooled_output" in result[0][1]
print(
    "PASS scenario 13 - falls back to a valid manually-wrapped shape when encode_from_tokens_scheduled isn't available"
)

print("\nALL EXTRA SCENARIOS PASSED (v2)")

# ------------------------------------------------------------------
print("\n--- Scenario 14: SweepDimensionZip pairs values index-for-index instead of cross-producting ---")
ZipNode = pkg.NODE_CLASS_MAPPINGS["SweepDimensionZip"]
zip_node = ZipNode()

(lora_chain,) = dim_node.build(
    dim_type="lora_strength",
    dim_id="lora_strength",
    values="0.0\n1.0",
    lora_name="loraA.safetensors",
    prev_dimensions=None,
)
(cfg_chain,) = dim_node.build(dim_type="cfg", dim_id="cfg", values="4.5\n1.0", lora_name="", prev_dimensions=None)
(zipped,) = zip_node.build(dimensions_a=lora_chain, dimensions_b=cfg_chain, mode="shortest")

assert len(zipped) == 2, f"expected 2 dims after zipping 2 dims together, got {len(zipped)}"
assert zipped[0]["group"] == zipped[1]["group"] and zipped[0]["group"] is not None
# Each member keeps its OWN individual label (needed so
# SweepDimensionExtract can still tell them apart afterward) -- the
# combined "a, b" display string lives separately in group_label, used
# only where a single representative needs to show both values together
# (grid/page titles).
assert zipped[0]["dim_id"] == "lora_strength" and zipped[1]["dim_id"] == "cfg", (
    f"each member should keep its own label, got {zipped[0]['dim_id']!r} / {zipped[1]['dim_id']!r}"
)
assert zipped[0]["group_label"] == zipped[1]["group_label"] == "lora_strength, cfg", (
    f"group_label should be the comma-joined concatenation, got {zipped[0].get('group_label')!r} / {zipped[1].get('group_label')!r}"
)
assert [d["index"] for d in zipped] == [1, 2]

# chain an INDEPENDENT (non-zipped) seed dimension after the zip
(final_dims,) = dim_node.build(dim_type="seed", dim_id="", values="1,2", lora_name="", prev_dimensions=zipped)
assert len(final_dims) == 3

# capture what actually gets sampled, to verify pairing wasn't scrambled
calls = []
orig_sample = main_node.sample


def spy_sample(model, positive, negative, latent, seed, steps, cfg, sampler_name, scheduler, denoise):
    calls.append({"model_tag": getattr(model, "tag", None), "cfg": cfg, "seed": seed})
    return orig_sample(model, positive, negative, latent, seed, steps, cfg, sampler_name, scheduler, denoise)


main_node.sample = spy_sample

S.sample_counter["n"] = 0
kw = base_kwargs(dimensions=final_dims, grid_x_dim="dim3", grid_y_dim="none", grid_title_dim="dim1")
grids, summary = main_node.generate(**kw)
main_node.sample = orig_sample
print(summary)

# 2 (zipped pair length) x 2 (independent seed) = 4 -- NOT 2x2x2=8, which is
# what a broken (non-group-aware) implementation would produce.
assert S.sample_counter["n"] == 4, (
    f"expected 4 images (zip pairs x seed), got {S.sample_counter['n']} -- zip is being cross-produced instead of paired"
)
assert len(calls) == 4

# every call where lora strength was 0.0 (base model, untouched tag) must have cfg=4.5;
# every call where lora strength was 1.0 (tag contains the lora-applied marker) must have cfg=1.0.
# this is the actual correctness check -- confirms pairing, not just the count.
for c in calls:
    if c["model_tag"] == "base":
        assert c["cfg"] == 4.5, f"lora OFF (base model) must pair with cfg=4.5, got {c}"
    else:
        assert "1.0" in str(c["model_tag"]) and c["cfg"] == 1.0, f"lora strength 1.0 must pair with cfg=1.0, got {c}"
print(
    f"PASS scenario 14 - {S.sample_counter['n']} images (not 8), and every call's cfg correctly matches its paired lora strength:"
)
for c in calls:
    print("   ", c)

# ------------------------------------------------------------------
print("\n--- Scenario 15: three-way zip via chaining a zip's output into another zip ---")
(lora2,) = dim_node.build(
    dim_type="lora_strength", dim_id="lora", values="0.0\n1.0", lora_name="loraA.safetensors", prev_dimensions=None
)
(cfg2,) = dim_node.build(dim_type="cfg", dim_id="cfg", values="4.5\n1.0", lora_name="", prev_dimensions=None)
(zip1,) = zip_node.build(dimensions_a=lora2, dimensions_b=cfg2, mode="strict")
(steps2,) = dim_node.build(dim_type="steps", dim_id="steps", values="30\n8", lora_name="", prev_dimensions=None)
(zip2,) = zip_node.build(dimensions_a=zip1, dimensions_b=steps2, mode="strict")

assert len(zip2) == 3, f"expected all 3 (lora, cfg, steps) merged into one group, got {len(zip2)} dims"
gids = {d["group"] for d in zip2}
assert len(gids) == 1, f"all three should share ONE group id after chaining zips, got {gids}"
own_dim_ids = {d["dim_id"] for d in zip2}
assert own_dim_ids == {"lora", "cfg", "steps"}, f"each of the 3 should keep its own distinct label, got {own_dim_ids}"
group_labels = {d["group_label"] for d in zip2}
assert group_labels == {"lora, cfg, steps"}, f"expected a 3-way combined group_label, got {group_labels}"

S.sample_counter["n"] = 0
kw = base_kwargs(dimensions=zip2)
grids, summary = main_node.generate(**kw)
assert S.sample_counter["n"] == 2, (
    f"3-way zip of length-2 lists should give 2 images total, got {S.sample_counter['n']}"
)
print(
    f"PASS scenario 15 - chaining zips composes to a 3-way pairing ({S.sample_counter['n']} images, all three dims share one group)"
)

# ------------------------------------------------------------------
print("\n--- Scenario 16: zip modes -- shortest / longest / strict ---")
(a3,) = dim_node.build(dim_type="cfg", dim_id="a", values="1,2,3", lora_name="", prev_dimensions=None)
(b2,) = dim_node.build(dim_type="steps", dim_id="b", values="10,20", lora_name="", prev_dimensions=None)

(short_result,) = zip_node.build(
    dimensions_a=a3,
    dimensions_b=dim_node.build(dim_type="steps", dim_id="b", values="10,20", lora_name="", prev_dimensions=None)[0],
    mode="shortest",
)
assert len(short_result[0]["values"]) == 2 and len(short_result[1]["values"]) == 2, short_result
print("PASS scenario 16a - shortest mode truncates the longer list to match")

(long_result,) = zip_node.build(
    dimensions_a=dim_node.build(dim_type="cfg", dim_id="a", values="1,2,3", lora_name="", prev_dimensions=None)[0],
    dimensions_b=dim_node.build(dim_type="steps", dim_id="b", values="10,20", lora_name="", prev_dimensions=None)[0],
    mode="longest",
)
assert long_result[0]["values"] == [1.0, 2.0, 3.0]
assert long_result[1]["values"] == [10, 20, 20], (
    f"shorter list should pad by repeating its last value, got {long_result[1]['values']}"
)
print("PASS scenario 16b - longest mode pads the shorter list by repeating its last value")

try:
    zip_node.build(
        dimensions_a=dim_node.build(dim_type="cfg", dim_id="a", values="1,2,3", lora_name="", prev_dimensions=None)[0],
        dimensions_b=dim_node.build(dim_type="steps", dim_id="b", values="10,20", lora_name="", prev_dimensions=None)[
            0
        ],
        mode="strict",
    )
    print("FAIL: strict mode should have raised on mismatched lengths")
    sys.exit(1)
except ValueError as e:
    assert "strict" in str(e) and "3" in str(e) and "2" in str(e)
    print("PASS scenario 16c - strict mode raises a clear error on mismatched lengths:", e)

# ------------------------------------------------------------------
print("\n--- Scenario 17: grid building with a zipped pair doesn't double-count or leave empty cells ---")
(lora3,) = dim_node.build(
    dim_type="lora_strength", dim_id="lora", values="0.0\n1.0", lora_name="loraA.safetensors", prev_dimensions=None
)
(cfg3,) = dim_node.build(dim_type="cfg", dim_id="cfg", values="4.5\n1.0", lora_name="", prev_dimensions=None)
(zip3,) = zip_node.build(dimensions_a=lora3, dimensions_b=cfg3, mode="strict")
(text3,) = dim_node.build(dim_type="text", dim_id="style", values="a\nb", lora_name="", prev_dimensions=zip3)

kw = base_kwargs(
    dimensions=text3,
    grid_x_dim="dim3",
    grid_y_dim="none",
    grid_title_dim="auto",
    positive_prompt="{}",
    negative_prompt="worst quality",
)
grids, summary = main_node.generate(**kw)
print(summary)
# grid X = dim3 (the zipped lora/cfg pair, picked explicitly), title = auto -> should
# pick the text dim (dim1... wait text is appended last, so it's dim3's *sibling* --
# just confirm no crash and a sane grid count: one grid per text value (2), each
# with 2 columns (the zip pair), no missing/empty cells expected since every
# combination was actually generated.
assert grids.arr.shape[0] == 2, f"expected 2 grids (one per style), got {grids.arr.shape[0]}"
print(f"PASS scenario 17 - grid built cleanly with a zipped axis as X, {grids.arr.shape[0]} grids, no crash")

print("\nALL ZIP SCENARIOS PASSED")

# ------------------------------------------------------------------
print("\n--- Scenario 18: cell_mode controls aspect-ratio handling for grid cells ---")
from sweepkit.sweep_image import cell_dims  # noqa: E402

# Portrait image matching the user's actual workflow (888 wide x 1184 tall)
portrait = S.FakeTensor(__import__("numpy").zeros((1, 1184, 888, 3), dtype="float32"))

w, h = cell_dims([portrait], cell_size=512, cell_mode="square")
assert (w, h) == (512, 512), f"square mode must force cell_size x cell_size regardless of source shape, got {(w, h)}"

w, h = cell_dims([portrait], cell_size=512, cell_mode="fit")
assert max(w, h) == 512, f"fit mode's larger dimension should equal cell_size, got {(w, h)}"
assert w < h, f"portrait source (888x1184) should stay portrait (w < h) in fit mode, got {(w, h)}"
assert abs(w / h - 888 / 1184) < 0.01, (
    f"fit mode must preserve the original aspect ratio, got {(w, h)} vs expected ratio {888 / 1184:.4f}"
)

w, h = cell_dims([portrait], cell_size=512, cell_mode="original")
assert (w, h) == (888, 1184), f"original mode should use the exact native size regardless of cell_size, got {(w, h)}"

print(
    f"PASS scenario 18 - square={cell_dims([portrait], 512, 'square')}, "
    f"fit={cell_dims([portrait], 512, 'fit')} (aspect preserved), "
    f"original={cell_dims([portrait], 512, 'original')} (native size, cell_size ignored)"
)

# ------------------------------------------------------------------
print("\n--- Scenario 19: grid title shows combined group values and X/Y axis captions, not raw tuples ---")
(lora4,) = dim_node.build(
    dim_type="lora_strength", dim_id="lora_str", values="0.5\n1.0", lora_name="loraA.safetensors", prev_dimensions=None
)
(steps4,) = dim_node.build(dim_type="steps", dim_id="ste", values="15\n8", lora_name="", prev_dimensions=None)
(zip4,) = zip_node.build(dimensions_a=lora4, dimensions_b=steps4, mode="shortest")

captured_titles = []
sweep_image_mod = sys.modules["sweepkit.sweep_image"]
orig_make_grid = sweep_image_mod.make_grid


def spy_make_grid(images, x_labels, y_labels, title, *args, **kwargs):
    if not kwargs.get("pending"):  # the on-node live preview draws grids too; only count saved ones
        captured_titles.append({"title": title, "x_labels": list(x_labels), "y_labels": list(y_labels)})
    return orig_make_grid(images, x_labels, y_labels, title, *args, **kwargs)


sweep_image_mod.make_grid = spy_make_grid
try:
    kw = base_kwargs(dimensions=zip4, grid_x_dim="dim1", grid_y_dim="none", grid_title_dim="none")
    main_node.generate(**kw)
finally:
    sweep_image_mod.make_grid = orig_make_grid

assert len(captured_titles) == 1
cap = captured_titles[0]
print("   title:", cap["title"])
print("   x_labels:", cap["x_labels"])
assert "(0.5" not in cap["title"] and "(0.5" not in str(cap["x_labels"]), (
    f"must not show Python's raw tuple repr anywhere, got title={cap['title']!r} x_labels={cap['x_labels']!r}"
)
assert "X: lora_str, ste" in cap["title"], (
    f"title must caption the X axis by its (combined) label even with grid_title_dim=none, got {cap['title']!r}"
)
assert cap["x_labels"] == ["0.5, 15", "1, 8"], (
    f"x_labels must show BOTH zipped members' values together, got {cap['x_labels']}"
)
print(
    "PASS scenario 19 - no raw tuples anywhere, X axis is captioned even with title_dim=none, and zipped values show both members together"
)

print("\nALL EXTRA SCENARIOS PASSED (v3)")

# ------------------------------------------------------------------
print("\n--- Scenario 20: _cell_dims reads H/W from the END of the shape, not fixed positions 1/2 ---")
# Regression test for a real production bug: a video-capable VAE (WanVAE)
# plausibly returns an extra leading "frames" dimension even for a single
# still image -- [batch, frames, H, W, C] instead of the plain
# [batch, H, W, C] this code originally assumed. Reading shape[1]/shape[2]
# on a 5D tensor silently grabs (frames, height) instead of (height,
# width) -- no crash, just badly wrong numbers, which is exactly what
# produced a near-zero-height grid instead of an error.
import numpy as np  # noqa: E402

plain_4d = S.FakeTensor(np.zeros((1, 1184, 888, 3), dtype=np.float32))  # normal image tensor
video_5d = S.FakeTensor(np.zeros((1, 1, 1184, 888, 3), dtype=np.float32))  # frames=1 leading dim

w4, h4 = cell_dims([plain_4d], cell_size=512, cell_mode="fit")
w5, h5 = cell_dims([video_5d], cell_size=512, cell_mode="fit")
assert (w4, h4) == (w5, h5), (
    f"a 4D [B,H,W,C] tensor and a 5D [B,F,H,W,C] tensor with the same actual "
    f"H/W must produce the SAME cell dimensions, got 4D={w4, h4} vs 5D={w5, h5}"
)
assert h4 > w4, f"1184x888 is portrait (taller than wide) -- fit mode must preserve that, got {(w4, h4)}"
assert min(w5, h5) > 10, f"5D tensor must not collapse to a near-zero dimension, got {(w5, h5)}"

w5o, h5o = cell_dims([video_5d], cell_size=512, cell_mode="original")
assert (w5o, h5o) == (888, 1184), (
    f"original mode on a 5D tensor must still recover the true native size, got {(w5o, h5o)}"
)

print(
    f"PASS scenario 20 - 4D and 5D (video-VAE-style) tensors of the same actual size produce identical, correct cell dims: {(w4, h4)}"
)

# ------------------------------------------------------------------
# Regression scenarios for wrong results and crashes fixed in 1.0.0
# (stacked LoRAs, duplicate axes, regex order, shared zips, socket cap,
# reserved names). Each one failed (or was silently wrong) before the fix.
# ------------------------------------------------------------------


def expect_error(fn, *needles):
    try:
        fn()
    except ValueError as e:
        msg = str(e)
        for n in needles:
            assert n in msg, (n, msg)
        return msg
    raise AssertionError(f"expected ValueError containing {needles}")


def run_with_sample_spy(kwargs):
    seen = []
    orig = main_node.sample

    def spy(model, positive, negative, latent, seed, steps, cfg, sampler_name, scheduler, denoise):
        seen.append({"model_tag": getattr(model, "tag", None), "seed": seed, "steps": steps, "cfg": cfg})
        return orig(model, positive, negative, latent, seed, steps, cfg, sampler_name, scheduler, denoise)

    main_node.sample = spy
    try:
        main_node.generate(**kwargs)
    finally:
        main_node.sample = orig
    return seen


print("\n--- Scenario 21: two lora_strength dimensions stack instead of the second being ignored ---")
dims = build_chain(
    dict(dim_type="lora_strength", dim_id="la", values="0.5\n1.0", lora_name="loraA.safetensors"),
    dict(dim_type="lora_strength", dim_id="lb", values="0.2\n0.4", lora_name="loraB.safetensors"),
)
seen = run_with_sample_spy(base_kwargs(dimensions=dims, save_individuals=False, create_grids=False))
tags = [c["model_tag"] for c in seen]
assert len(seen) == 4, len(seen)
assert all("loraA" in t and "loraB" in t for t in tags), tags
assert len(set(tags)) == 4, tags  # every (A strength, B strength) pair is distinct
assert all(t.index("loraA") < t.index("loraB") for t in tags), tags  # applied in chain order
print("PASS scenario 21 - both LoRAs applied, in chain order, for all 4 strength pairs")

print("\n--- Scenario 22: a duplicate seed/steps/cfg/model dimension is rejected before any sampling ---")
for dup_type, vals in [("cfg", ("3\n4", "7\n8")), ("seed", ("1", "2")), ("steps", ("10", "20"))]:
    dims = build_chain(
        dict(dim_type=dup_type, dim_id=f"{dup_type}A", values=vals[0]),
        dict(dim_type=dup_type, dim_id=f"{dup_type}B", values=vals[1]),
    )
    S.sample_counter["n"] = 0
    expect_error(
        lambda: main_node.generate(**base_kwargs(dimensions=dims, save_individuals=False)),
        "[Sweep All-in-One]",
        f"'{dup_type}'-type",
        f"'{dup_type}A'",
        f"'{dup_type}B'",
    )
    assert S.sample_counter["n"] == 0, "must fail before sampling anything"
print("PASS scenario 22 - duplicate cfg/seed/steps dimensions raise a clear error, nothing sampled")

print("\n--- Scenario 23: regex text_mode fills placeholders left to right, and a bad pattern is a clear error ---")
for mode in ("curly", "regex"):
    out = main_node.apply_text_replacements("A {} B {} C {}", ["x", "y"], mode, r"\{\}")
    assert out == "A x B y C {}", (mode, out)
assert main_node.apply_text_replacements("<a> <b>", ["1", "2", "3"], "regex", r"<\w>") == "1 2"
dims = build_chain(dict(dim_type="text", dim_id="t", values="cat"))
S.sample_counter["n"] = 0
expect_error(
    lambda: main_node.generate(**base_kwargs(dimensions=dims, text_mode="regex", text_regex="(")),
    "[Sweep All-in-One]",
    "text_regex",
)
assert S.sample_counter["n"] == 0
# An invalid text_regex is irrelevant (and must not error) in curly mode.
main_node.generate(**base_kwargs(dimensions=dims, text_mode="curly", text_regex="(", save_individuals=False))
print("PASS scenario 23 - left-to-right fill in both modes; invalid regex rejected before sampling")

print("\n--- Scenario 24: zipping two branches of a shared chain keeps the shared dimension once ---")
from sweepkit.sweep_core import build_combo_records  # noqa: E402

zip_node = pkg.NODE_CLASS_MAPPINGS["SweepDimensionZip"]()
(base,) = dim_node.build(dim_type="text", dim_id="style", values="a\nb", lora_name="", prev_dimensions=None)
(branch_a,) = dim_node.build(dim_type="cfg", dim_id="cfg", values="4\n5", lora_name="", prev_dimensions=base)
(branch_b,) = dim_node.build(dim_type="steps", dim_id="steps", values="10\n20", lora_name="", prev_dimensions=base)
(zipped,) = zip_node.build(branch_a, branch_b, "strict")
assert [d["dim_id"] for d in zipped] == ["style", "cfg", "steps"], [d["dim_id"] for d in zipped]
records, _, _ = build_combo_records(zipped)
assert len(records) == 4, len(records)  # 2 styles x 2 zipped (cfg, steps) pairs
# b chained straight on top of a: a's tail must not reappear as pass-through either
(on_top,) = dim_node.build(dim_type="steps", dim_id="steps", values="10\n20", lora_name="", prev_dimensions=branch_a)
(zipped2,) = zip_node.build(branch_a, on_top, "strict")
assert [d["dim_id"] for d in zipped2] == ["style", "cfg", "steps"], [d["dim_id"] for d in zipped2]
expect_error(lambda: zip_node.build(branch_a, branch_a, "strict"), "[Sweep Pair Axes]", "same axis")
print("PASS scenario 24 - shared upstream dimension kept once (4 combos, not 8); self-zip rejected")

print("\n--- Scenario 25: model labels beyond the frontend's 24-socket cap are dropped visibly ---")
from sweepkit.sweep_core import MAX_MODEL_SOCKETS  # noqa: E402

labels = "\n".join(f"m{i}" for i in range(1, 31))
(dims,) = dim_node.build(dim_type="model", dim_id="ckpt", values=labels, lora_name="", prev_dimensions=None)
assert len(dims[0]["values"]) == MAX_MODEL_SOCKETS == 24, len(dims[0]["values"])
assert len(dims[0]["model_objs"]) == MAX_MODEL_SOCKETS
js_src = open(os.path.join(_pkg_dir, "web", "sweepkit_core.js"), encoding="utf-8").read()
assert f"export const MAX_SOCKETS = {MAX_MODEL_SOCKETS};" in js_src, "JS and Python socket caps must match"
print("PASS scenario 25 - 30 labels truncated to 24, matching web/sweepkit_core.js")

print("\n--- Scenario 26: Windows reserved names as filename_prefix / text values save normally ---")
dims = build_chain(dict(dim_type="text", dim_id="t", values="CON\naux"), dict(dim_type="seed", values="1"))
_, summary = main_node.generate(**base_kwargs(dimensions=dims, filename_prefix="NUL"))
saved = []
for dp, _, fs in os.walk(os.path.join(S.OUTPUT_DIR, "_NUL")):
    saved += [os.path.join(dp, f) for f in fs]
assert any(os.sep + "_CON" + os.sep in p for p in saved) and any(os.sep + "_aux" + os.sep in p for p in saved), saved
print(f"PASS scenario 26 - prefix 'NUL' saved under '_NUL' ({len(saved)} files)")

# ------------------------------------------------------------------
# Regression scenarios for memory use and on-node output, fixed in 1.0.0.
# ------------------------------------------------------------------
import gc  # noqa: E402
import weakref  # noqa: E402

print("\n--- Scenario 27: decoded images are not kept in memory when create_grids is off ---")


def peak_live_images(create_grids):
    """Run an 8-image sweep and return the most decoded images that were
    still alive at the start of any sampling call."""
    refs, peak = [], [0]
    real_decode = S.FAKE_VAE.decode

    def tracking_decode(samples):
        img = real_decode(samples)
        refs.append(weakref.ref(img))
        return img

    orig = main_node.sample

    def counting_sample(*args):
        gc.collect()
        peak[0] = max(peak[0], sum(r() is not None for r in refs))
        return orig(*args)

    S.FAKE_VAE.decode = tracking_decode
    main_node.sample = counting_sample
    try:
        dims = build_chain(dict(dim_type="seed", values="1-8"))
        main_node.generate(**base_kwargs(dimensions=dims, save_individuals=False, create_grids=create_grids))
    finally:
        main_node.sample = orig
        del S.FAKE_VAE.decode
    return peak[0]


no_grid_peak = peak_live_images(create_grids=False)
grid_peak = peak_live_images(create_grids=True)
assert no_grid_peak <= 1, f"create_grids=False kept {no_grid_peak} decoded images alive"
assert grid_peak == 7, f"create_grids=True should still keep earlier images for the grid ({grid_peak})"
print(f"PASS scenario 27 - live decoded images: {no_grid_peak} without grids (was all of them), {grid_peak} with grids")

print("\n--- Scenario 28: SweepAllInOne shows its saved grids and summary in the UI ---")
dims = build_chain(dict(dim_type="text", dim_id="t", values="a\nb"), dict(dim_type="seed", values="1,2"))
grids, summary = main_node.generate(**base_kwargs(dimensions=dims, filename_prefix="TestUI"))
ui = main_node.last_ui
assert ui["text"] == [summary], ui
assert ui["images"] and all(i["type"] == "output" for i in ui["images"]), ui
for entry in ui["images"]:
    assert os.path.isfile(os.path.join(S.OUTPUT_DIR, entry["subfolder"], entry["filename"])), entry
    assert entry["subfolder"].startswith("TestUI"), entry
print(f"PASS scenario 28 - ui lists {len(ui['images'])} saved grid(s) plus the summary text")

print("\n--- Scenario 29: the grid so far is previewed on the node while sampling ---")
PB = sys.modules["comfy.utils"].ProgressBar
sweep_image_mod = sys.modules["sweepkit.sweep_image"]


def live_frames(dims, **kw):
    PB.previews.clear()
    main_node.generate(**base_kwargs(dimensions=dims, **kw))
    return [f[1] for f in PB.previews]


old_interval = sweep_image_mod.PREVIEW_MIN_INTERVAL
sweep_image_mod.PREVIEW_MIN_INTERVAL = 0.0  # one frame per image, so the test is deterministic
try:
    dims = build_chain(dict(dim_type="seed", values="1,2"), dict(dim_type="cfg", values="3,6"))
    frames = live_frames(dims, create_grids=False, save_individuals=False)
    assert len(frames) == 4, f"expected one frame per image, got {len(frames)}"
    assert all(max(f.size) <= sweep_image_mod.PREVIEW_MAX_SIDE for f in frames), [f.size for f in frames]
    assert all(f[0] == "JPEG" and f[2] == sweep_image_mod.PREVIEW_MAX_SIDE for f in PB.previews)
    # Cells fill in as images finish, so the last frame differs from the first.
    assert frames[0].tobytes() != frames[-1].tobytes()

    # Rate limit: with a long interval only the first and the final frame go out.
    # The clock is pinned near zero, as on a machine that booted moments ago
    # (time.monotonic() counts from boot on Linux): the first frame must still go out.
    sweep_image_mod.PREVIEW_MIN_INTERVAL = 3600.0
    real_monotonic = sweep_image_mod.time.monotonic
    sweep_image_mod.time.monotonic = lambda: 5.0
    try:
        frames = live_frames(dims, create_grids=False, save_individuals=False)
    finally:
        sweep_image_mod.time.monotonic = real_monotonic
    assert len(frames) == 2, f"rate limit should leave first + final frames, got {len(frames)}"
    sweep_image_mod.PREVIEW_MIN_INTERVAL = 0.0

    # Several pages (3 dimensions): one frame per image, each a normal image.
    dims3 = build_chain(
        dict(dim_type="text", dim_id="t", values="a\nb"),
        dict(dim_type="seed", values="1,2"),
        dict(dim_type="cfg", values="3,6"),
    )
    frames = live_frames(dims3, create_grids=True, save_individuals=False)
    assert len(frames) == 8 and frames[-1].size[0] > 0

    # A preview failure must not stop the sweep: it is switched off, results are unchanged.
    orig_render = sweep_image_mod.LiveGrid.render

    def broken_render(self):
        raise RuntimeError("boom")

    sweep_image_mod.LiveGrid.render = broken_render
    try:
        PB.previews.clear()
        _, summary = main_node.generate(**base_kwargs(dimensions=dims, create_grids=True))
    finally:
        sweep_image_mod.LiveGrid.render = orig_render
    assert "4 image(s) generated" in summary and "grid(s)" in summary and not PB.previews
finally:
    sweep_image_mod.PREVIEW_MIN_INTERVAL = old_interval
print("PASS scenario 29 - live frames per image, rate-limited, and a preview failure is harmless")

print("\n--- Scenario 30: the summary under an axis comes from the real parser ---")
from sweepkit.sweep_dimension import preview_values  # noqa: E402
from sweepkit.sweep_routes import MAX_VALUES_TEXT, preview_response  # noqa: E402

r = preview_values("seed", "1-3, 7")
assert r == {"ok": True, "count": 4, "labels": ["1", "2", "3", "7"]}, r
r = preview_values("cfg", "4\n7.0\n10")
assert r["ok"] and r["count"] == 3 and r["labels"] == ["4", "7", "10"], r
r = preview_values("text", "a cat, a dog\nbird")  # text values are one per line; commas stay in the text
assert r["ok"] and r["count"] == 2 and r["labels"][0] == "a cat, a dog", r
r = preview_values("lora_strength", "0.5, 0.8:0.4")
assert r["ok"] and r["labels"] == ["0.5", "0.8/0.4"], r
r = preview_values("seed", "1-100")
assert r["count"] == 100 and len(r["labels"]) == 6, r  # only the first few labels are sent
r = preview_values("model", "a\nb")
assert r == {"ok": True, "count": 2, "labels": ["a", "b"]}, r
r = preview_values("int", "1, two")
assert r == {"ok": False, "error": "'two' is not a whole number: type e.g. 1, 2, 3 or 1-5"}, r  # short: problem and fix
r = preview_values("seed", "1-99999999999")
assert r["ok"] is False and "over 10,000 values: shorten it" in r["error"], r  # refused, not expanded
r = preview_values("cfg", "4, x")
assert r == {"ok": False, "error": "'x' is not a number: type e.g. 4, 7.5, 10"}, r
r = preview_values("lora_strength", "0.8;0.5")
assert r == {"ok": False, "error": "'0.8;0.5' is not a LoRA strength: type e.g. 0.8 or 0.8:0.6"}, r
r = preview_values("text", "")
assert r == {"ok": True, "count": 0, "labels": []}, r
assert preview_response([1, 2])["ok"] is False
assert preview_response({"dim_type": "seed", "values": "x" * (MAX_VALUES_TEXT + 1)})["ok"] is False
assert preview_response({"dim_type": "nonsense", "values": "1"}) == {"ok": True, "count": 0, "labels": []}
print("PASS scenario 30 - preview_values: counts, labels, plain errors, range and size limits")

print("\n--- Scenario 31: every sweep writes a run list (CSV) beside its images ---")
import csv  # noqa: E402
import glob  # noqa: E402

dims = build_chain(dict(dim_type="text", dim_id="mood", values="calm\nwild"), dict(dim_type="seed", values="1,2"))
_, summary = main_node.generate(**base_kwargs(dimensions=dims, filename_prefix="TestManifest"))
files = glob.glob(os.path.join(S.OUTPUT_DIR, "TestManifest", "sweep_manifest_*.csv"))
assert len(files) == 1 and files[0] in summary, (files, summary)
with open(files[0], newline="", encoding="utf-8") as fh:
    rows = list(csv.reader(fh))
assert rows[0] == ["run", "file", "mood", "seed"], rows[0]
assert len(rows) == 5 and [r[0] for r in rows[1:]] == ["1", "2", "3", "4"], rows
assert {(r[2], r[3]) for r in rows[1:]} == {("calm", "1"), ("calm", "2"), ("wild", "1"), ("wild", "2")}
for r in rows[1:]:
    assert r[1].endswith(".png") and os.path.isfile(os.path.join(S.OUTPUT_DIR, "TestManifest", r[1])), (
        r
    )  # relative path

# A second run adds a second manifest instead of replacing the first.
main_node.generate(**base_kwargs(dimensions=dims, filename_prefix="TestManifest"))
assert len(glob.glob(os.path.join(S.OUTPUT_DIR, "TestManifest", "sweep_manifest_*.csv"))) == 2

# No saved files and no grids: nothing to list, nothing written.
main_node.generate(
    **base_kwargs(dimensions=dims, filename_prefix="TestNoManifest", save_individuals=False, create_grids=False)
)
assert not glob.glob(os.path.join(S.OUTPUT_DIR, "TestNoManifest", "sweep_manifest_*.csv"))

# Two axes with the same name keep distinguishable columns.
from sweepkit.sweep_core import write_manifest  # noqa: E402

dd = build_chain(dict(dim_type="seed", dim_id="x", values="1,2"), dict(dim_type="cfg", dim_id="x", values="3"))
from sweepkit.sweep_core import build_combo_records  # noqa: E402

recs, dsorted, _ = build_combo_records([dict(d) for d in dd])
path = write_manifest(os.path.join(S.OUTPUT_DIR, "TestManifestDup"), dsorted, recs, [None] * len(recs))
with open(path, newline="", encoding="utf-8") as fh:
    head = next(csv.reader(fh))
assert head == ["run", "file", "x", "x_2"], head
print("PASS scenario 31 - run list CSV: one row per run, relative file names, never overwritten, unique headers")


print("\n--- Scenario 32: a very long prompt can't stretch a grid or matrix ---")
from PIL import Image as _PILImage  # noqa: E402

LONG = "a lighthouse on a cliff at sunset, dramatic sky, highly detailed, " * 30  # ~2,000 characters
NO_SPACES = "x" * 3000  # one huge word


def grid_size(prefix, text_value):
    # Six seed columns make the grid wider than the title's minimum width.
    dims = build_chain(dict(dim_type="text", dim_id="prompt", values=text_value), dict(dim_type="seed", values="1-6"))
    # The prompt is the title axis, seed the columns.
    kw = dict(grid_title_dim="dim1", grid_x_dim="dim2", grid_y_dim="none", save_individuals=False)
    main_node.generate(**base_kwargs(dimensions=dims, filename_prefix=prefix, **kw))
    entry = main_node.last_ui["images"][0]
    with _PILImage.open(os.path.join(S.OUTPUT_DIR, entry["subfolder"], entry["filename"])) as im:
        return im.size


short_w, short_h = grid_size("TestTitleShort", "a cat")
long_w, long_h = grid_size("TestTitleLong", LONG)
word_w, word_h = grid_size("TestTitleWord", NO_SPACES)
# The width follows the grid, not the prompt; the height grows by at most the extra title lines.
assert long_w == short_w and word_w == short_w, (short_w, long_w, word_w)
assert short_h < long_h <= short_h + 200 and word_h <= short_h + 200, (short_h, long_h, word_h)

# A single column is narrow, so the title gets a minimum width instead of the grid's.
dims1 = build_chain(dict(dim_type="text", dim_id="prompt", values=LONG))
main_node.generate(
    **base_kwargs(
        dimensions=dims1,
        filename_prefix="TestTitleOneCol",
        grid_title_dim="dim1",
        grid_x_dim="none",
        grid_y_dim="none",
        save_individuals=False,
    )
)
e1 = main_node.last_ui["images"][0]
with _PILImage.open(os.path.join(S.OUTPUT_DIR, e1["subfolder"], e1["filename"])) as im:
    assert im.size[0] <= 700, im.size  # not thousands of pixels

# The axis caption stays visible on its own line even when the prompt is long.
from sweepkit.sweep_image import grid_title  # noqa: E402

t = grid_title([{"dim_id": "prompt"}], [LONG], "X: seed   Y: cfg", "fallback")
assert t.endswith("\nX: seed   Y: cfg"), t[-40:]
print(f"PASS scenario 32 - widths {short_w} / {long_w} / {word_w} px for short / 2,000-char / 3,000-char-word prompts")


print("\n--- Scenario 33: the backend reads chains that pass through Pair Axes and Subsets ---")
from sweepkit.sweep_routes import chain_response  # noqa: E402


def axis_spec(dim_type, dim_id, values, prev=None, **extra):
    return {
        "kind": "axis",
        "dim_type": dim_type,
        "dim_id": dim_id,
        "values": values,
        "lora_name": "",
        "prev": prev,
        **extra,
    }


# A plain chain: names in chain order, counts, product.
r = chain_response(
    {"root": "2", "nodes": {"1": axis_spec("seed", "seed", "1-3"), "2": axis_spec("cfg", "cfg", "4, 7", "1")}}
)
assert r["ok"] and [a["label"] for a in r["axes"]] == ["seed", "cfg"] and r["groups"] == [3, 2] and r["total"] == 6, r

# Pair Axes: two axes move together, so they count once; cfg crosses the pairs.
nodes = {
    "a": axis_spec("float", "lora_model", "0.2, 0.4, 0.6, 0.8, 1.0"),
    "b": axis_spec("float", "lora_clip", "0.3, 0.5, 0.6, 0.7, 0.9"),
    "z": {"kind": "zip", "a": "a", "b": "b", "mode": "shortest"},
    "c": axis_spec("cfg", "cfg", "4, 7, 10", "z"),
}
r = chain_response({"root": "c", "nodes": nodes})
assert r["ok"] and [a["label"] for a in r["axes"]] == ["lora_model", "lora_clip", "cfg"], r
assert sorted(r["groups"]) == [3, 5] and r["total"] == 15, r  # 5 pairs x 3 cfg, not 45

# Two branches sharing one upstream axis (style -> cfg and style -> steps) keep it once.
nodes = {
    "s": axis_spec("text", "style", "a\nb"),
    "c": axis_spec("cfg", "cfg", "4, 7", "s"),
    "t": axis_spec("steps", "steps", "10, 20", "s"),
    "z": {"kind": "zip", "a": "c", "b": "t", "mode": "shortest"},
}
r = chain_response({"root": "z", "nodes": nodes})
assert r["ok"] and [a["label"] for a in r["axes"]] == ["style", "cfg", "steps"] and r["total"] == 4, r

# Subsets: 4 values at sizes 1-3 give 14 combinations; the axis is renamed like the node does.
nodes = {
    "s": axis_spec("text", "style", "cyberpunk\nnoir\npastel\nvintage"),
    "sc": {"kind": "selfcombine", "dims": "s", "mode": "combinations", "min_size": 1, "max_size": 3, "joiner": ", "},
    "c": axis_spec("cfg", "cfg", "4, 7", "sc"),
}
r = chain_response({"root": "c", "nodes": nodes})
assert (
    r["ok"] and r["axes"][0]["label"] == "style (combinations)" and r["axes"][0]["count"] == 14 and r["total"] == 28
), r

# Problems come back as plain messages, not tracebacks.
nodes = {
    "a": axis_spec("float", "x", "1, 2, 3"),
    "b": axis_spec("float", "y", "1, 2"),
    "z": {"kind": "zip", "a": "a", "b": "b", "mode": "strict"},
}
r = chain_response({"root": "z", "nodes": nodes})
assert r["ok"] is False and "use mode shortest" in r["error"] and "[Sweep" not in r["error"], r
r = chain_response({"root": "a", "nodes": {"a": axis_spec("int", "n", "1, x")}})
assert r["ok"] is False and "x" in r["error"], r
r = chain_response({"root": "a", "nodes": {"a": axis_spec("seed", "seed", "", pylist=True)}})
assert r["ok"] is False and r["unknown"] is True, r  # values from a connected list can't be read here
r = chain_response({"root": "a", "nodes": {"a": axis_spec("int", "n", "1", "a")}})
assert r["ok"] is False and "loops" in r["error"], r  # a loop can't hang it
assert chain_response({"root": "q", "nodes": {}})["ok"] is False
assert chain_response({"root": "a", "nodes": {"a": {"kind": "nonsense"}}})["ok"] is False
assert chain_response(None)["ok"] is False
assert chain_response({"root": "1", "nodes": {str(i): {} for i in range(101)}})["ok"] is False  # too many nodes
print("PASS scenario 33 - chain_response: names, per-group counts, pair/subset/shared-axis totals, plain errors")


print("\nALL EXTRA SCENARIOS PASSED (v4)")
