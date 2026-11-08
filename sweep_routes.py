"""
HTTP routes the SweepKit frontend uses. They only read: nothing here
changes a workflow or touches the file system.

POST /sweepkit/preview_values  {"dim_type": ..., "values": ...}
    -> {"ok": true, "count": n, "labels": [...]} or {"ok": false, "error": "..."}

POST /sweepkit/preview_chain   {"root": id, "nodes": {id: {"kind": ...}, ...}}
    -> {"ok": true, "axes": [{"label", "count"}...], "groups": [counts], "total": n}
       or {"ok": false, "error": "...", "unknown": bool}
    Describes a chain of axis / pair / subset nodes the way the sweep itself
    would read it (axis names in axis_N order, how many images result), for
    chains the frontend can't work out alone.

Asking the backend means what a node shows always comes from the same code
that runs the sweep, so the two can't disagree.
"""

import contextlib
import io
import math
import re

from .sweep_core import partition_into_groups, sort_groups
from .sweep_dimension import SweepDimension, preview_values
from .sweep_dimension_selfcombine import SweepDimensionSelfCombine
from .sweep_dimension_zip import SweepDimensionZip

# Longest `values` text the route will parse; anything longer is refused.
MAX_VALUES_TEXT = 100_000
# Most nodes (and deepest nesting) a described chain may have.
MAX_CHAIN_NODES = 100


def preview_response(payload):
    """Route logic without the web framework, so tests can call it."""
    if not isinstance(payload, dict):
        return {"ok": False, "error": "expected a JSON object"}
    dim_type, values = str(payload.get("dim_type", "")), str(payload.get("values", ""))
    if len(values) > MAX_VALUES_TEXT:
        return {"ok": False, "error": f"values text is too long (over {MAX_VALUES_TEXT:,} characters)"}
    return preview_values(dim_type, values)


class UnknownChain(ValueError):
    """The chain can't be evaluated here (for example, values from a connected list)."""


def _build(nodes, node_id, cache, depth=0):
    """The dimension list a node produces, building each node once so a shared
    upstream axis keeps one identity (which is how Pair Axes recognises it)."""
    if node_id in cache:
        return cache[node_id]
    if depth > MAX_CHAIN_NODES:
        raise ValueError("the chain is too long, or loops back on itself")
    spec = nodes.get(node_id)
    if not isinstance(spec, dict):
        raise ValueError("the chain refers to a node that was not sent")

    def upstream(name):
        ref = spec.get(name)
        return None if ref is None else _build(nodes, str(ref), cache, depth + 1)

    kind = spec.get("kind")
    if kind == "axis":
        if spec.get("pylist"):
            raise UnknownChain("an axis gets its values from a connected list")
        dims = SweepDimension().build(
            str(spec.get("dim_type", "")),
            str(spec.get("dim_id", "")),
            str(spec.get("values", "")),
            str(spec.get("lora_name", "")),
            prev_dimensions=upstream("prev"),
        )[0]
    elif kind == "zip":
        dims = SweepDimensionZip().build(upstream("a"), upstream("b"), str(spec.get("mode", "shortest")))[0]
    elif kind == "selfcombine":
        dims = SweepDimensionSelfCombine().build(
            upstream("dims"),
            str(spec.get("mode", "combinations")),
            int(spec.get("min_size", 1)),
            int(spec.get("max_size", 0)),
            str(spec.get("joiner", ", ")),
        )[0]
    else:
        raise ValueError(f"unsupported node kind {kind!r}")
    cache[node_id] = dims
    return dims


def chain_response(payload):
    """Describe a chain: axis names in chain order, per-group value counts and the total."""
    nodes = payload.get("nodes") if isinstance(payload, dict) else None
    if not isinstance(nodes, dict) or len(nodes) > MAX_CHAIN_NODES or "root" not in payload:
        return {"ok": False, "error": "expected {root, nodes} with at most %d nodes" % MAX_CHAIN_NODES}
    try:
        with contextlib.redirect_stdout(io.StringIO()):  # the nodes log; a live preview shouldn't
            dims = _build(nodes, str(payload["root"]), {})
    except UnknownChain as exc:
        return {"ok": False, "unknown": True, "error": str(exc)}
    except (ValueError, KeyError, TypeError) as exc:
        return {"ok": False, "error": re.sub(r"^\[\w+\]\s*", "", str(exc)) or "could not read this chain"}
    dims = sorted(dims, key=lambda d: d["index"])
    groups = [len(g[0]["values"]) for g in sort_groups(partition_into_groups(dims))]
    return {
        "ok": True,
        "axes": [{"label": d["dim_id"], "count": len(d["values"])} for d in dims],
        "groups": groups,
        "total": math.prod(groups),
    }


def register_routes(server):
    """Add the routes to a running PromptServer (a no-op without one)."""
    if server is None:
        return
    from aiohttp import web

    async def read_json(request):
        try:
            return await request.json()
        except ValueError:
            return None

    @server.routes.post("/sweepkit/preview_values")
    async def _preview_values(request):
        return web.json_response(preview_response(await read_json(request)))

    @server.routes.post("/sweepkit/preview_chain")
    async def _preview_chain(request):
        return web.json_response(chain_response(await read_json(request)))
