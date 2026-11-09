#!/usr/bin/env python3
"""Run a SweepKit workflow on a ComfyUI server without opening the browser.

One request produces every image and grid of the sweep, because SweepKit does
its looping on the server. Export your workflow with File > Export (API) in
ComfyUI, then:

    python scripts/run_sweep_api.py workflow_api.json
    python scripts/run_sweep_api.py workflow_api.json --server http://127.0.0.1:8188 \\
        --set 12.values="1-8" --set 5.filename_prefix=overnight_run

--set NODE_ID.INPUT=VALUE changes one input before the run (VALUE is read as
JSON when it parses, otherwise used as text). NODE_ID is the number in the
exported file. Uses only the Python standard library.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

POLL_SECONDS = 1.0


def parse_override(text: str) -> tuple[str, str, object]:
    """'12.values=1-8' -> ('12', 'values', '1-8'); a value that is valid JSON
    (7, 0.5, true, "text", [1, 2]) is decoded, anything else stays text."""
    target, sep, raw = text.partition("=")
    node_id, dot, name = target.partition(".")
    if not (sep and dot and node_id and name):
        raise ValueError(f"expected NODE_ID.INPUT=VALUE, got {text!r}")
    try:
        value = json.loads(raw)
    except ValueError:
        value = raw
    return node_id, name, value


def apply_overrides(prompt: dict, overrides: list[tuple[str, str, object]]) -> dict:
    """The workflow with each (node id, input, value) applied. Unknown node
    ids are an error, so a typo can't silently run the unchanged workflow."""
    for node_id, name, value in overrides:
        if node_id not in prompt:
            raise KeyError(f"node {node_id!r} is not in the workflow (nodes: {', '.join(sorted(prompt))})")
        prompt[node_id].setdefault("inputs", {})[name] = value
    return prompt


def request(server: str, path: str, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(server.rstrip("/") + path, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as resp:
        return json.load(resp)


def run(server: str, prompt: dict, timeout: float) -> dict:
    """Queue the workflow, wait for it, and return its history entry."""
    try:
        queued = request(server, "/prompt", {"prompt": prompt})
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"The server refused the workflow ({exc.code}):\n{exc.read().decode()[:2000]}") from None
    prompt_id = queued["prompt_id"]
    print(f"Queued {prompt_id}", file=sys.stderr)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        entry = request(server, f"/history/{prompt_id}").get(prompt_id)
        if entry and entry["status"].get("status_str") in ("success", "error"):
            return entry
        time.sleep(POLL_SECONDS)
    raise SystemExit(f"Timed out after {timeout:.0f} s; the run may still be going on the server.")


def summarize(entry: dict) -> list[str]:
    """Lines to print: the status, any error, and each node's text and saved images."""
    status = entry["status"]
    lines = [f"status: {status.get('status_str')}"]
    for kind, data in status.get("messages", []):
        if kind == "execution_error":
            lines.append(f"error in node {data.get('node_id')}: {data.get('exception_message', '').strip()}")
    for node_id, out in entry.get("outputs", {}).items():
        lines.extend(f"[{node_id}] {text}" for text in out.get("text", []))
        for img in out.get("images", []):
            lines.append(f"[{node_id}] image: {img.get('subfolder', '')}/{img['filename']} ({img.get('type')})")
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("workflow", help="workflow exported with File > Export (API) in ComfyUI")
    parser.add_argument("--server", default="http://127.0.0.1:8188", help="ComfyUI address (default: %(default)s)")
    parser.add_argument(
        "--set", action="append", default=[], metavar="NODE_ID.INPUT=VALUE", help="change an input first"
    )
    parser.add_argument("--timeout", type=float, default=3600, help="seconds to wait (default: %(default)s)")
    args = parser.parse_args(argv)

    with open(args.workflow, encoding="utf-8") as fh:
        prompt = json.load(fh)
    try:
        prompt = apply_overrides(prompt, [parse_override(s) for s in args.set])
    except (ValueError, KeyError) as exc:
        parser.error(str(exc))
    entry = run(args.server, prompt, args.timeout)
    print("\n".join(summarize(entry)))
    return 0 if entry["status"].get("status_str") == "success" else 1


if __name__ == "__main__":
    sys.exit(main())
