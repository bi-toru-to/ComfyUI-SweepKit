"""Pure-logic tests for sweep_core.py — no torch/comfy needed at all."""

import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import sweep_core as core


def test_parse_text_list():
    # Newline is the ONLY separator now — a comma-separated tag list must
    # survive intact as one value, since that's exactly how tag-based
    # prompts are normally written.
    assert core.parse_text_list("masterpiece, highres, 1girl\nsecond value") == [
        "masterpiece, highres, 1girl",
        "second value",
    ]
    assert core.parse_text_list("a\nb\nc") == ["a", "b", "c"]
    assert core.parse_text_list("") == []
    print("OK test_parse_text_list (comma preserved as content, newline-only separator)")


def test_parse_number_range():
    assert core.parse_number_list("1-5", int, "seed", allow_range=True) == [1, 2, 3, 4, 5]
    assert core.parse_number_list("1,3,5-7", int, "seed", allow_range=True) == [1, 3, 5, 6, 7]
    try:
        core.parse_number_list("abc", int, "seed")
        assert False
    except ValueError as e:
        assert "seed" in str(e)
    print("OK test_parse_number_range")


def test_cost_sort_order():
    active = [
        {"index": 1, "type": "text"},
        {"index": 2, "type": "seed"},
        {"index": 3, "type": "model"},
        {"index": 4, "type": "lora_strength"},
        {"index": 5, "type": "cfg"},
    ]
    sorted_dims = sorted(active, key=lambda d: (core.COST_RANK.get(d["type"], 5), d["index"]))
    order = [d["type"] for d in sorted_dims]
    assert order == ["model", "lora_strength", "text", "seed", "cfg"], order
    print("OK test_cost_sort_order:", order)


def test_grid_axes_auto():
    active = [{"index": 1, "type": "text"}, {"index": 2, "type": "text"}, {"index": 3, "type": "seed"}]
    x, y, t, other = core.resolve_grid_axes(active, "auto", "auto", "auto")
    # X prefers seed; Y then prefers non-text but there's none left, so it
    # takes the first available (dim1); title runs LAST and gets whatever's
    # left (dim2) -- title deliberately no longer gets first pick.
    assert x["type"] == "seed" and y["index"] == 1 and t["index"] == 2 and other == [], (x, y, t, other)
    print("OK test_grid_axes_auto")


def test_grid_axes_two_independent_always_one_grid():
    # Regression for the reported bug: with exactly 2 independent axes,
    # auto/auto and every explicit dimN assignment of the same two axes
    # must all agree that NEITHER x nor y nor title is left over -- i.e.
    # other_dims is empty and title_dim is None in every case, so exactly
    # one grid results regardless of how the axes were picked.
    active = [{"index": 1, "type": "steps", "values": [10, 20]}, {"index": 2, "type": "cfg", "values": [4, 7, 10]}]
    for gx, gy, gt in [
        ("auto", "auto", "auto"),
        ("auto", "auto", "none"),
        ("dim1", "dim2", "none"),
        ("dim2", "dim1", "none"),
        ("dim1", "dim2", "auto"),
        ("dim2", "dim1", "auto"),
    ]:
        x, y, t, other = core.resolve_grid_axes(active, gx, gy, gt)
        assert x is not None and y is not None, f"gx={gx},gy={gy},gt={gt}: x/y must both resolve, got x={x},y={y}"
        assert t is None and other == [], (
            f"gx={gx},gy={gy},gt={gt}: title/other must be empty for a 2-axis sweep, got t={t}, other={other}"
        )
    print("OK test_grid_axes_two_independent_always_one_grid")


def test_grid_axes_explicit_conflict_falls_back_like_auto():
    # An explicit-but-conflicting pick (the non-representative half of an
    # already-claimed zipped pair) must recover the same way 'auto' would,
    # not strand the role as permanently empty -- this was the actual
    # mechanism behind the two-separate-grids bug report.
    active = [
        {"index": 1, "type": "cfg", "values": [0.2, 0.6, 1.0], "group": "g1", "dim_id": "a"},
        {"index": 2, "type": "cfg", "values": [0.3, 0.7, 0.9], "group": "g1", "dim_id": "b"},
        {"index": 3, "type": "cfg", "values": [4, 7, 10], "dim_id": "cfg"},
    ]
    x, y, t, other = core.resolve_grid_axes(active, "dim1", "dim2", "none")
    assert x["index"] == 1, x
    assert y is not None and y["index"] == 3, f"y should recover to dim3 (cfg) instead of staying stranded, got {y}"
    assert t is None and other == [], (t, other)
    print("OK test_grid_axes_explicit_conflict_falls_back_like_auto")


def test_grid_axes_leftover():
    active = [
        {"index": 1, "type": "text"},
        {"index": 2, "type": "seed"},
        {"index": 3, "type": "cfg"},
        {"index": 4, "type": "model"},
    ]
    x, y, t, other = core.resolve_grid_axes(active, "dim2", "dim4", "dim1")
    assert x["index"] == 2 and y["index"] == 4 and t["index"] == 1
    assert [d["index"] for d in other] == [3]
    print("OK test_grid_axes_leftover")


def test_safe_component():
    assert core.safe_component("artist: alpha/beta") == "artist_ alpha_beta"
    assert core.safe_component("") == "_"
    print("OK test_safe_component")


def test_safe_component_windows_reserved_names():
    # Audit finding F2: a 'NUL' filename_prefix made every save fail with
    # FileNotFoundError on Windows. Reserved device stems get a '_' prefix.
    for raw, expected in [
        ("NUL", "_NUL"),
        ("con", "_con"),
        ("aux.txt", "_aux.txt"),
        ("COM1", "_COM1"),
        ("lpt9.png", "_lpt9.png"),
        ("console", "console"),  # only exact stems are reserved
        ("COM10", "COM10"),
        ("nullable", "nullable"),
    ]:
        assert core.safe_component(raw) == expected, (raw, core.safe_component(raw))
    # Truncation must not leave a trailing dot/space (also invalid on Windows).
    assert not core.safe_component("a" * 79 + ". tail").endswith((".", " "))
    print("OK test_safe_component_windows_reserved_names")


def test_parse_number_negative_ranges():
    # Audit finding F1: ranges with a negative start crashed with
    # 'too many values to unpack' instead of parsing.
    assert core.parse_number_list("-5--1", int, "seed", allow_range=True) == [-5, -4, -3, -2, -1]
    assert core.parse_number_list("-3-2", int, "seed", allow_range=True) == [-3, -2, -1, 0, 1, 2]
    assert core.parse_number_list("2--1", int, "seed", allow_range=True) == [2, 1, 0, -1]
    assert core.parse_number_list("1 - 3", int, "seed", allow_range=True) == [1, 2, 3]
    assert core.parse_number_list("-4", int, "seed", allow_range=True) == [-4]
    print("OK test_parse_number_negative_ranges")


def test_resize_dimension_values():
    d = {"values": [1, 2, 3, 4]}
    core.resize_dimension_values(d, 2)
    assert d["values"] == [1, 2], d
    d = {"values": [1, 2]}
    core.resize_dimension_values(d, 4)
    assert d["values"] == [1, 2, 2, 2], d
    d = {"values": ["A", "B"], "model_objs": ["ma", "mb"]}
    core.resize_dimension_values(d, 3)
    assert d["values"] == ["A", "B", "B"] and d["model_objs"] == ["ma", "mb", "mb"], d
    print("OK test_resize_dimension_values")


def test_partition_and_sort_groups():
    dims = [
        {"index": 1, "type": "text", "values": ["a", "b"]},
        {"index": 2, "type": "lora_strength", "values": [0.0, 1.0], "group": "g1"},
        {"index": 3, "type": "cfg", "values": [4.5, 1.0], "group": "g1"},
        {"index": 4, "type": "seed", "values": [1, 2, 3]},
    ]
    groups = core.partition_into_groups(dims)
    assert len(groups) == 3
    assert [d["index"] for d in groups[0]] == [1]
    assert [d["index"] for d in groups[1]] == [2, 3]
    assert [d["index"] for d in groups[2]] == [4]

    sorted_groups = core.sort_groups(groups)
    # the zipped group (lora_strength + cfg) must sort as if it were
    # lora_strength-expensive (rank 1), ahead of plain text (rank 2) and
    # seed (rank 3), even though cfg alone would be rank 3.
    assert [g[0]["type"] for g in sorted_groups] == ["lora_strength", "text", "seed"], [
        g[0]["type"] for g in sorted_groups
    ]
    print("OK test_partition_and_sort_groups")


def test_resolve_group_index():
    dim_a = {"index": 2, "type": "lora_strength", "values": [0.0, 1.0], "group": "g1"}
    dim_b = {"index": 3, "type": "cfg", "values": [4.5, 1.0], "group": "g1"}
    all_dims = [
        {"index": 1, "type": "text", "values": ["x", "y"]},
        dim_a,
        dim_b,
        {"index": 4, "type": "seed", "values": [1, 2]},
    ]
    full_idx = {2: 1}  # only dim_a's index is present
    assert core.resolve_group_index(dim_b, full_idx, all_dims) == 1, "should fall back to groupmate dim_a's index"
    assert core.resolve_group_index(dim_a, full_idx, all_dims) == 1, "own index present -> use directly"
    assert core.resolve_group_index(all_dims[3], full_idx, all_dims) == 0, "ungrouped + unresolved -> 0"
    print("OK test_resolve_group_index")


def test_grid_axes_group_aware():
    active = [
        {"index": 1, "type": "text", "values": ["a", "b"]},
        {"index": 2, "type": "lora_strength", "values": [0.0, 1.0], "group": "g1", "dim_id": "lora_strength, cfg"},
        {"index": 3, "type": "cfg", "values": [4.5, 1.0], "group": "g1", "dim_id": "lora_strength, cfg"},
        {"index": 4, "type": "seed", "values": [1, 2, 3]},
    ]
    # auto mode: a zipped groupmate must never independently appear in other_dims
    x, y, t, other = core.resolve_grid_axes(active, "auto", "auto", "auto")
    assert t["index"] == 1 and x["index"] == 4 and y["index"] == 2
    assert other == [], f"groupmate of y must be excluded from other_dims, got {other}"

    # explicit conflicting picks (both members of the same group for x AND y)
    # must recover the same way 'auto' would -- y falls back to the next
    # available dimension (dim4, seed) instead of staying stranded, which
    # is what used to force dim4 into other_dims and produce an extra grid.
    x, y, t, other = core.resolve_grid_axes(active, "dim2", "dim3", "auto")
    assert x["index"] == 2
    assert y is not None and y["index"] == 4, f"y should recover to dim4 instead of staying stranded, got {y}"

    # explicit pick of one member excludes its groupmate from other_dims too
    x, y, t, other = core.resolve_grid_axes(active, "dim4", "none", "dim2")
    assert x["index"] == 4 and t["index"] == 2
    assert [d["index"] for d in other] == [1], other
    print("OK test_grid_axes_group_aware")


def test_format_dim_value():
    lora_dim = {"type": "lora_strength", "values": [(0.5, 0.5), (0.7, 0.3)]}
    # equal model/clip strength -> single number, not a raw tuple repr
    assert core.format_dim_value(lora_dim, 0) == "0.5", core.format_dim_value(lora_dim, 0)
    # different model/clip strength -> "model/clip"
    assert core.format_dim_value(lora_dim, 1) == "0.7/0.3", core.format_dim_value(lora_dim, 1)
    seed_dim = {"type": "seed", "values": [1, 2]}
    assert core.format_dim_value(seed_dim, 0) == "1"
    print("OK test_format_dim_value (lora_strength shows '0.5', not the raw tuple '(0.5, 0.5)')")


def test_format_group_value():
    dim_a = {"index": 1, "type": "lora_strength", "values": [(0.5, 0.5), (1.0, 1.0)], "group": "g1"}
    dim_b = {"index": 2, "type": "steps", "values": [15, 8], "group": "g1"}
    dim_c = {"index": 3, "type": "cfg", "values": [4.5, 1.0], "group": "g1"}
    active = [dim_a, dim_b, dim_c]

    members = core.dim_group_members(dim_a, active)
    assert members == [dim_a, dim_b, dim_c], "should gather every member sharing the group id"
    assert core.format_group_value(members, 0) == "0.5, 15, 4.5"
    assert core.format_group_value(members, 1) == "1, 8, 1"

    ungrouped = {"index": 4, "type": "text", "values": ["x", "y"]}
    assert core.dim_group_members(ungrouped, active + [ungrouped]) == [ungrouped]
    print("OK test_format_group_value (all zipped members shown together, e.g. '0.5, 15, 4.5', not just one)")


def test_build_combo_records():
    dims = [
        {"index": 1, "type": "text", "dim_id": "style", "values": ["a", "b"]},
        {"index": 2, "type": "seed", "dim_id": "seed", "values": [1, 2, 3]},
    ]
    records, sorted_dims, groups = core.build_combo_records(dims)
    assert len(records) == 6, len(records)
    assert records[0]["idx_by_dim"] == {1: 0, 2: 0}
    assert records[-1]["idx_by_dim"] == {1: 1, 2: 2}
    assert [r["combo_index"] for r in records] == list(range(6))
    print("OK test_build_combo_records")


def test_build_combo_records_zipped():
    # A zipped pair must resolve to ONE shared index per combo, not be
    # cross-producted as if independent.
    dims = [
        {"index": 1, "type": "lora_strength", "dim_id": "l,c", "values": [(0.0, 0.0), (1.0, 1.0)], "group": "g1"},
        {"index": 2, "type": "cfg", "dim_id": "l,c", "values": [4.5, 1.0], "group": "g1"},
        {"index": 3, "type": "seed", "dim_id": "seed", "values": [1, 2]},
    ]
    records, sorted_dims, groups = core.build_combo_records(dims)
    assert len(records) == 4, len(records)  # 2 (zipped pair) x 2 (seed), not 2x2x2
    for r in records:
        assert r["idx_by_dim"][1] == r["idx_by_dim"][2], "zipped pair must share one index"
    print("OK test_build_combo_records_zipped")


def test_extract_values():
    dims = [
        {"index": 1, "type": "text", "dim_id": "style", "values": ["a", "b"]},
        {"index": 2, "type": "seed", "dim_id": "seed", "values": [1, 2, 3]},
    ]
    records, sorted_dims, groups = core.build_combo_records(dims)
    vals = core.extract_values(dims, records, "seed")
    assert vals == [1, 2, 3, 1, 2, 3], vals

    try:
        core.extract_values(dims, records, "nope")
        assert False
    except ValueError as e:
        assert "nope" in str(e) and "style" in str(e)

    dup = dims + [{"index": 3, "type": "text", "dim_id": "style", "values": ["x", "y"]}]
    try:
        core.extract_values(dup, records, "style")
        assert False
    except ValueError as e:
        assert "matches 2 dimensions" in str(e)
    print("OK test_extract_values")


def test_extract_values_lora_component():
    dims = [{"index": 1, "type": "lora_strength", "dim_id": "lora", "values": [(0.5, 0.8), (1.0, 1.0)]}]
    records, sorted_dims, groups = core.build_combo_records(dims)
    assert core.extract_values(dims, records, "lora", "model_strength") == [0.5, 1.0]
    assert core.extract_values(dims, records, "lora", "clip_strength") == [0.8, 1.0]
    try:
        bad_dims = [{"index": 1, "type": "cfg", "dim_id": "cfg", "values": [4.5]}]
        bad_records, _, _ = core.build_combo_records(bad_dims)
        core.extract_values(bad_dims, bad_records, "cfg", "model_strength")
        assert False
    except ValueError as e:
        assert "only applies to" in str(e)
    print("OK test_extract_values_lora_component")


def test_self_combine_combinations():
    vals, meta = core.self_combine(["A", "B", "C"], "combinations", 1, 2, ", ")
    assert vals == ["A", "B", "C", "A, B", "A, C", "B, C"], vals
    assert meta[3] == {"arity": 2, "members": [0, 1]}
    assert meta[0] == {"arity": 1, "members": [0]}
    print("OK test_self_combine_combinations")


def test_self_combine_permutations():
    vals, meta = core.self_combine(["A", "B"], "permutations", 2, 2, ",")
    assert vals == ["A,B", "B,A"], vals
    assert meta[0]["members"] == [0, 1] and meta[1]["members"] == [1, 0]
    print("OK test_self_combine_permutations")


def test_self_combine_max_size_zero_means_full():
    vals, meta = core.self_combine(["A", "B", "C"], "combinations", 1, 0, ",")
    assert meta[-1] == {"arity": 3, "members": [0, 1, 2]}
    print("OK test_self_combine_max_size_zero_means_full")


def test_self_combine_bad_range_raises():
    try:
        core.self_combine(["A", "B"], "combinations", 3, 2, ",")
        assert False
    except ValueError as e:
        assert "min_size" in str(e)
    print("OK test_self_combine_bad_range_raises")


def test_dedupe_indices():
    keys = ["x", "y", "x", "z", "y"]
    uim, exp = core.dedupe_indices(keys)
    assert uim == [0, 1, 3], uim
    assert exp == [0, 1, 0, 2, 1], exp
    # round trip: gather(gather(source, uim)-sampled, exp) reconstructs order
    source_full = ["s0", "s1", "s2", "s3", "s4"]
    unique_only = core.gather(source_full, uim)
    reexpanded = core.gather(unique_only, exp)
    assert reexpanded == ["s0", "s1", "s0", "s3", "s1"], reexpanded
    print("OK test_dedupe_indices (round trip through gather)")


def test_gather():
    src = ["p", "q", "r"]
    assert core.gather(src, [0, 2, 2, 1]) == ["p", "r", "r", "q"]
    try:
        core.gather(src, [5])
        assert False
    except ValueError as e:
        assert "out of range" in str(e)
    try:
        core.gather(src, [-1])
        assert False
    except ValueError:
        pass
    print("OK test_gather")


def test_cast_pylist_values():
    assert core.cast_pylist_values(["4", 5.0, 6], "seed", "seed") == [4, 5, 6]
    assert core.cast_pylist_values([1, "2.5"], "cfg", "cfg") == [1.0, 2.5]
    assert core.cast_pylist_values([1, 2], "text", "t") == ["1", "2"]
    assert core.cast_pylist_values([0.7, (0.5, 0.3)], "lora_strength", "l") == [(0.7, 0.7), (0.5, 0.3)]
    try:
        core.cast_pylist_values(["not_a_number"], "cfg", "cfg")
        assert False
    except ValueError as e:
        assert "cfg" in str(e)
    print("OK test_cast_pylist_values")


def test_build_dedupe_keys():
    keys = core.build_dedupe_keys([[1.00000001, 2.0], ["a", "b"]], float_precision=3)
    assert keys[0] != keys[1]
    keys_close = core.build_dedupe_keys([[7.5, 7.50000001]], float_precision=4)
    assert keys_close[0] == keys_close[1], "values within float_precision must hash identically"

    class Opaque:
        pass

    try:
        core.build_dedupe_keys([[1, 2], [Opaque(), 3]])
        assert False
    except ValueError as e:
        assert "model_key" in str(e)

    try:
        core.build_dedupe_keys([])
        assert False
    except ValueError:
        pass

    try:
        core.build_dedupe_keys([[1, 2], [1]])
        assert False
    except ValueError as e:
        assert "length" in str(e)
    print("OK test_build_dedupe_keys")


def test_build_filenames_uniqueness_and_folders():
    dims = [
        {"index": 1, "type": "text", "dim_id": "style", "values": ["a", "b"]},
        {"index": 2, "type": "seed", "dim_id": "seed", "values": [1, 2, 3]},
    ]
    records, sorted_dims, groups = core.build_combo_records(dims)
    names = core.build_filenames(sorted_dims, records, "SweepKit", True)
    assert len(names) == len(set(names)) == 6, "every filename must be unique"
    # filename_prefix is ALWAYS the leading folder component now (not just
    # when the caller manually adds a trailing '/'), and is no longer also
    # re-embedded into the per-file basename -- SaveImage reliably creates
    # output/<filename_prefix>/... by default with no widget gymnastics.
    assert names[0] == "SweepKit/a/0000_a_seed1", names[0]
    assert names[0].split("/")[0] == "SweepKit"
    assert names[0].split("/")[1] == "a" and names[3].split("/")[1] == "b"

    names_noidx = core.build_filenames(sorted_dims, records, "SweepKit", False)
    assert names_noidx[0] == names_noidx[3] == "SweepKit/a/a_seed1" or names_noidx[0] != names_noidx[3]
    # (seed differs between combo 0 and combo 3's *seed value* only if seed
    # dim resets per style -- here seed cycles 1,2,3,1,2,3 so combo0 and
    # combo3 DO collide once combo_index is dropped; that's expected and
    # exactly why include_combo_index defaults to True.)
    assert names_noidx[0] == "SweepKit/a/a_seed1" and names_noidx[3] == "SweepKit/b/b_seed1"
    print("OK test_build_filenames_uniqueness_and_folders")


def test_build_filenames_blank_prefix_defaults_and_self_combine_no_folder():
    dims = [
        {
            "index": 1,
            "type": "text",
            "dim_id": "artist (combinations)",
            "values": ["a", "b", "a, b"],
            "combo_meta": [{"arity": 1, "members": [0]}, {"arity": 1, "members": [1]}, {"arity": 2, "members": [0, 1]}],
        },
    ]
    records, sorted_dims, groups = core.build_combo_records(dims)

    # blank filename_prefix falls back to "SweepKit" rather than producing
    # a malformed/empty leading path component.
    names = core.build_filenames(sorted_dims, records, "", True)
    assert all(n.startswith("SweepKit/") for n in names), names
    # A self-combine-produced dimension does NOT create a folder per value
    # (every value is unique per combo by construction, so folder-per-
    # value would put every single image in its own folder) -- it still
    # contributes to the filename itself.
    assert names[0] == "SweepKit/0000_a", names[0]
    assert names[2].startswith("SweepKit/0002_a") and "b" in names[2], names[2]
    print("OK test_build_filenames_blank_prefix_defaults_and_self_combine_no_folder")


def test_build_filenames_opaque_model_value():
    class FakeModelObj:
        pass

    dims = [{"index": 1, "type": "model", "dim_id": "ckpt", "values": [FakeModelObj(), FakeModelObj()]}]
    records, sorted_dims, groups = core.build_combo_records(dims)
    names = core.build_filenames(sorted_dims, records, "SweepKit", True)
    assert "ckpt0" in names[0] and "ckpt1" in names[1], names
    assert "0x" not in names[0], "must not leak a Python object repr/memory address into the filename"
    print("OK test_build_filenames_opaque_model_value (stable positional tag, not str(obj))")


def test_find_dim_by_id():
    dims = [{"index": 1, "type": "text", "dim_id": "style", "values": ["a"]}]
    d = core.find_dim_by_id(dims, "style")
    assert d["type"] == "text"
    try:
        core.find_dim_by_id(dims, "missing")
        assert False
    except ValueError as e:
        assert "style" in str(e)
    print("OK test_find_dim_by_id")


def expect_value_error(fn, *needles):
    try:
        fn()
    except ValueError as e:
        for n in needles:
            assert n in str(e), (n, str(e))
        return str(e)
    raise AssertionError(f"expected ValueError containing {needles}")


def test_self_combine_cap():
    # Audit finding F6: 12 values as permutations (~1.3 billion) used to be
    # materialized with no guard. Now counted first and rejected.
    msg = expect_value_error(
        lambda: core.self_combine(list(range(12)), "permutations", 1, 0, ", "),
        "[SweepDimensionSelfCombine]",
        "1,302,061,344",
        f"{core.MAX_DERIVED_VALUES:,}",
    )
    assert "max_size=" in msg, msg  # tells the user which max_size would fit
    # At/below the cap still works, and the cap applies to the requested sizes only.
    vals, _ = core.self_combine(list(range(12)), "permutations", 1, 3, ", ")
    assert len(vals) == 12 + 132 + 1320
    vals, _ = core.self_combine(list(range(13)), "combinations", 1, 0, ", ")
    assert len(vals) == 2**13 - 1  # 8191 <= 10,000
    print("OK test_self_combine_cap")


def test_gather_rejects_bool_indices():
    # bool is an int subclass: [True] used to silently read source[1].
    expect_value_error(lambda: core.gather(["a", "b"], [True]), "[SweepGather]")
    expect_value_error(lambda: core.gather(["a", "b"], [False]), "[SweepGather]")
    assert core.gather(["a", "b"], [1, 0]) == ["b", "a"]
    print("OK test_gather_rejects_bool_indices")


def test_next_versioned_path_does_not_swallow_listing_errors():
    # Audit finding F8: a failing os.listdir was swallowed and the counter
    # restarted at _00001, which could overwrite an existing file.
    import tempfile

    d = tempfile.mkdtemp()
    open(os.path.join(d, "grid_00001.png"), "wb").close()
    assert core.next_versioned_path(d, "grid").endswith("grid_00002.png")
    real_listdir = core.os.listdir

    def broken_listdir(path):
        raise PermissionError("simulated listing failure")

    core.os.listdir = broken_listdir
    try:
        core.next_versioned_path(d, "grid")
        raise AssertionError("listing failure must propagate")
    except PermissionError:
        pass
    finally:
        core.os.listdir = real_listdir
    print("OK test_next_versioned_path_does_not_swallow_listing_errors")


def test_canvas_and_batch_helpers():
    core.check_canvas_size(10_000, 10_000, "X")  # exactly 100 MP: allowed
    expect_value_error(
        lambda: core.check_canvas_size(10_001, 10_000, "SweepGridConstructor"), "[SweepGridConstructor]", "cell_mode"
    )
    assert core.padded_batch_size([(10, 20), (30, 5)]) == (30, 20)
    from PIL import Image

    small = Image.new("RGB", (2, 2), (255, 0, 0))
    padded = core.pad_image(small, 4, 3)
    assert padded.size == (4, 3)
    assert padded.getpixel((1, 1)) == (255, 0, 0) and padded.getpixel((3, 2)) == (16, 16, 16)
    assert core.pad_image(small, 2, 2) is small
    out = os.path.join("C:\\" if os.name == "nt" else "/", "out")
    ui = core.ui_images([os.path.join(out, "P", "_grids", "g_00001.png")], out)
    assert ui == [{"filename": "g_00001.png", "subfolder": os.path.join("P", "_grids"), "type": "output"}], ui
    print("OK test_canvas_and_batch_helpers")


test_parse_text_list()
test_parse_number_range()
test_cost_sort_order()
test_grid_axes_auto()
test_grid_axes_two_independent_always_one_grid()
test_grid_axes_explicit_conflict_falls_back_like_auto()
test_grid_axes_leftover()
test_safe_component()
test_safe_component_windows_reserved_names()
test_parse_number_negative_ranges()
test_resize_dimension_values()
test_partition_and_sort_groups()
test_resolve_group_index()
test_grid_axes_group_aware()
test_format_dim_value()
test_format_group_value()
test_build_combo_records()
test_build_combo_records_zipped()
test_extract_values()
test_extract_values_lora_component()
test_self_combine_combinations()
test_self_combine_permutations()
test_self_combine_max_size_zero_means_full()
test_self_combine_bad_range_raises()
test_dedupe_indices()
test_gather()
test_cast_pylist_values()
test_build_dedupe_keys()
test_build_filenames_uniqueness_and_folders()
test_build_filenames_blank_prefix_defaults_and_self_combine_no_folder()
test_build_filenames_opaque_model_value()
test_find_dim_by_id()
test_self_combine_cap()
test_gather_rejects_bool_indices()
test_next_versioned_path_does_not_swallow_listing_errors()
test_canvas_and_batch_helpers()

print("\nALL LOGIC TESTS PASSED")
