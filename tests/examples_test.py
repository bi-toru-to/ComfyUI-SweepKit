"""Checks on the example workflows and the docs' links (no ComfyUI needed).

For every example_workflows/*.json:
  1. the file parses as a workflow;
  2. it has exactly one Note;
  3. every node is from SweepKit, a ComfyUI core node, or a ComfyUI-List-Utils
     node (GODMT_*), and when List-Utils nodes are used the Note names the pack;
  4. every filename_prefix starts with "SweepKit_" and is named in the Note.
     A filename_prefix fed by a link (e.g. from Sweep Filenames) is ignored by
     ComfyUI, but its leftover typed value must still be one of the example's
     own prefixes, so it can't mislead someone who disconnects it.

For every *.md file in the pack: each relative link `](path)` and `src="path"`
points to a file that exists, and each `#anchor` to a heading that exists.

KNOWN_GAPS lists problems the docs fix plan (Phase 2) still has to fix. They
are reported but don't fail the run. A gap that has been fixed but is still
listed does fail it, so the list can only shrink.
"""

import glob
import importlib.util
import json
import os
import re
import sys
import unicodedata

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
PKG_DIR = os.path.dirname(TESTS_DIR)
EXAMPLES = os.path.join(PKG_DIR, "example_workflows")

sys.path.insert(0, os.path.join(TESTS_DIR, "stubs"))
import build_stubs  # noqa: E402,F401  (fake torch/comfy so the node classes import)

_spec = importlib.util.spec_from_file_location(
    "sweepkit", os.path.join(PKG_DIR, "__init__.py"), submodule_search_locations=[PKG_DIR]
)
pkg = importlib.util.module_from_spec(_spec)
sys.modules["sweepkit"] = pkg
_spec.loader.exec_module(pkg)
SWEEPKIT_NODES = pkg.NODE_CLASS_MAPPINGS

# ComfyUI core nodes an example may use. Add to this list when an example needs another.
CORE_NODES = {
    "CheckpointLoaderSimple",
    "CLIPLoader",
    "CLIPTextEncode",
    "EmptyImage",
    "EmptyLatentImage",
    "ImageScale",
    "KSampler",
    "KSamplerAdvanced",
    "LoadImage",
    "LoraLoader",
    "LoraLoaderModelOnly",
    "MarkdownNote",
    "Note",
    "PreviewImage",
    "SaveImage",
    "StringConcatenate",
    "StringReplace",
    "UNETLoader",
    "VAEDecode",
    "VAEEncode",
    "VAELoader",
}
NOTE_TYPES = {"MarkdownNote", "Note"}
LIST_UTILS_PREFIX = "GODMT_"
LIST_UTILS_PACK = "ComfyUI-List-Utils"
PREFIX_START = "SweepKit_"

# Core nodes with a filename_prefix setting: its position among the node's settings.
CORE_PREFIX_INDEX = {"SaveImage": 0}

# (example file, check) pairs still open. Phase 2 of the docs fix plan removes them.
KNOWN_GAPS = {
    ("4_style_combinations_upset.json", "prefix SweepKit_styles not named in the Note"),
    ("5_dedupe_gather.json", "prefix SweepKit_dedupe not named in the Note"),
    ("6_model_list_pylist.json", "List-Utils nodes used but the Note doesn't name ComfyUI-List-Utils"),
    ("5_dedupe_gather.json", "leftover prefix ComfyUI on a connected input isn't one of the example's prefixes"),
    (
        "6_model_list_pylist.json",
        "leftover prefix SweepKit_lora_zip on a connected input isn't one of the example's prefixes",
    ),
    ("6_model_list_pylist.json", "prefix SweepKit_models not named in the Note"),
}

_WIDGET_TYPES = {"INT", "FLOAT", "STRING", "BOOLEAN", "COMBO"}


def settings_order(cls):
    """Names of a SweepKit node's settings, in the order a saved workflow stores
    their values (widgets_values): required then optional inputs that are settings,
    plus the frontend's extra "control after generate" value after a seed."""
    spec = cls.INPUT_TYPES()
    names = []
    for group in ("required", "optional"):
        for name, info in spec.get(group, {}).items():
            kind = info[0]
            opts = info[1] if len(info) > 1 and isinstance(info[1], dict) else {}
            if isinstance(kind, list) or kind in _WIDGET_TYPES:
                names.append(name)
                if kind == "INT" and (name in ("seed", "noise_seed") or opts.get("control_after_generate")):
                    names.append(f"{name}__control")
    return names


def prefix_linked(node):
    """True when the node's filename_prefix comes from a link, not the typed value."""
    return any(i.get("name") == "filename_prefix" and i.get("link") is not None for i in node.get("inputs") or [])


def prefix_values(node):
    """The node's typed filename_prefix value(s), if it has that setting."""
    values = node.get("widgets_values")
    if isinstance(values, dict):  # some frontends save settings by name
        return [values["filename_prefix"]] if "filename_prefix" in values else []
    values = values or []
    kind = node["type"]
    if kind in CORE_PREFIX_INDEX:
        index = CORE_PREFIX_INDEX[kind]
    elif kind in SWEEPKIT_NODES:
        order = settings_order(SWEEPKIT_NODES[kind])
        if "filename_prefix" not in order:
            return []
        index = order.index("filename_prefix")
    else:
        return []
    if index >= len(values) or not isinstance(values[index], str):
        raise AssertionError(f"node {node['id']} ({kind}): no text at filename_prefix's position {index}")
    return [values[index]]


def check_example(path):
    """The problems found in one example, as short strings."""
    problems = []
    try:
        with open(path, encoding="utf-8") as fh:
            wf = json.load(fh)
        nodes = wf["nodes"]
        assert isinstance(nodes, list) and nodes
    except (ValueError, KeyError, AssertionError) as exc:
        return [f"doesn't parse as a workflow ({exc})"]

    notes = [n for n in nodes if n.get("type") in NOTE_TYPES]
    if len(notes) != 1:
        problems.append(f"has {len(notes)} Notes, expected 1")
    note = "\n".join(str(v) for n in notes for v in (n.get("widgets_values") or []))

    types = {n["type"] for n in nodes}
    unknown = sorted(
        t for t in types if t not in SWEEPKIT_NODES and t not in CORE_NODES and not t.startswith(LIST_UTILS_PREFIX)
    )
    if unknown:
        problems.append(f"uses nodes that are neither SweepKit, core nor List-Utils: {', '.join(unknown)}")
    if any(t.startswith(LIST_UTILS_PREFIX) for t in types) and LIST_UTILS_PACK not in note:
        problems.append(f"List-Utils nodes used but the Note doesn't name {LIST_UTILS_PACK}")

    prefixes = sorted({p for n in nodes if not prefix_linked(n) for p in prefix_values(n)})
    for p in prefixes:
        if not p.startswith(PREFIX_START):
            problems.append(f"prefix {p} doesn't start with {PREFIX_START}")
        if p not in note:
            problems.append(f"prefix {p} not named in the Note")
    leftovers = sorted({p for n in nodes if prefix_linked(n) for p in prefix_values(n)} - set(prefixes))
    problems += [f"leftover prefix {p} on a connected input isn't one of the example's prefixes" for p in leftovers]
    return problems


# ---------------------------------------------------------------- links

_LINK = re.compile(r"\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
_SRC = re.compile(r"""src=["']([^"']+)["']""")
_CODE_FENCE = re.compile(r"^(```|~~~).*?^\1", re.S | re.M)
_INLINE_CODE = re.compile(r"`[^`\n]*`")


def github_slug(heading):
    """The anchor GitHub gives a heading: lower case, punctuation dropped, spaces to '-'."""
    text = re.sub(r"<[^>]+>", "", heading)  # inline HTML
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)  # links keep their text
    text = text.replace("`", "").strip().lower()
    out = []
    for ch in text:
        if ch in (" ", "-"):
            out.append("-")
        elif ch == "_" or ch.isalnum() or unicodedata.category(ch).startswith("M"):
            out.append(ch)
    return "".join(out)


def anchors_of(path, cache={}):  # noqa: B006 (deliberate per-run cache)
    if path not in cache:
        with open(path, encoding="utf-8") as fh:
            text = _CODE_FENCE.sub("", fh.read())
        seen, found = {}, set()
        for line in text.splitlines():
            m = re.match(r"^#{1,6}\s+(.*?)\s*#*\s*$", line)
            if not m:
                continue
            slug = github_slug(m.group(1))
            n = seen.get(slug, 0)
            seen[slug] = n + 1
            found.add(slug if n == 0 else f"{slug}-{n}")
        found.update(re.findall(r"""<a\s+(?:name|id)=["']([^"']+)["']""", text))
        cache[path] = found
    return cache[path]


def markdown_files():
    skip = {".git", "node_modules", "__pycache__"}
    for root, dirs, files in os.walk(PKG_DIR):
        dirs[:] = [d for d in dirs if d not in skip]
        for f in files:
            if f.lower().endswith(".md"):
                yield os.path.join(root, f)


def check_links(md_path):
    """Broken relative links in one Markdown file, as short strings."""
    with open(md_path, encoding="utf-8") as fh:
        text = fh.read()
    text = _INLINE_CODE.sub("", _CODE_FENCE.sub("", text))
    problems = []
    for target in _LINK.findall(text) + _SRC.findall(text):
        if re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I) or target.startswith("//"):
            continue  # http:, https:, mailto: ... (external, not checked here)
        path_part, _, anchor = target.partition("#")
        dest = os.path.normpath(os.path.join(os.path.dirname(md_path), path_part)) if path_part else md_path
        if not os.path.exists(dest):
            problems.append(f"{target}: no such file")
        elif anchor and dest.lower().endswith(".md") and anchor.lower() not in anchors_of(dest):
            problems.append(f"{target}: no heading for #{anchor}")
    return problems


# ---------------------------------------------------------------- run


def main():
    failures, gaps_seen = [], set()

    paths = sorted(glob.glob(os.path.join(EXAMPLES, "*.json")))
    assert paths, "no example workflows found"
    for path in paths:
        name = os.path.basename(path)
        problems = check_example(path)
        for p in problems:
            if (name, p) in KNOWN_GAPS:
                gaps_seen.add((name, p))
                print(f"KNOWN GAP {name}: {p}")
            else:
                failures.append(f"{name}: {p}")
        if not problems:
            print(f"OK {name}")

    for name, p in sorted(KNOWN_GAPS - gaps_seen):
        failures.append(f"{name}: '{p}' is fixed; remove it from KNOWN_GAPS")

    md_files = sorted(markdown_files())
    links = 0
    for md in md_files:
        problems = check_links(md)
        rel = os.path.relpath(md, PKG_DIR)
        failures += [f"{rel}: {p}" for p in problems]
    for md in md_files:
        with open(md, encoding="utf-8") as fh:
            body = _INLINE_CODE.sub("", _CODE_FENCE.sub("", fh.read()))
        links += len(_LINK.findall(body)) + len(_SRC.findall(body))
    print(f"OK links: {links} links in {len(md_files)} Markdown files checked")

    if failures:
        print("\nFAILED:")
        for f in failures:
            print(f"  {f}")
        sys.exit(1)
    print(f"\nALL EXAMPLE AND LINK CHECKS PASSED ({len(gaps_seen)} known gaps left for Phase 2)")


if __name__ == "__main__":
    main()
