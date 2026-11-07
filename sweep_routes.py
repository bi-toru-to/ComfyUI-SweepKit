"""
HTTP routes the SweepKit frontend uses. They only read: nothing here
changes a workflow or touches the file system.

POST /sweepkit/preview_values  {"dim_type": ..., "values": ...}
    -> {"ok": true, "count": n, "labels": [...]} or {"ok": false, "error": "..."}
Asking the backend means the count shown on a node always comes from the
same parser that runs the sweep, so the two can't disagree.
"""

from .sweep_dimension import preview_values

# Longest `values` text the route will parse; anything longer is refused.
MAX_VALUES_TEXT = 100_000


def preview_response(payload):
    """Route logic without the web framework, so tests can call it."""
    if not isinstance(payload, dict):
        return {"ok": False, "error": "expected a JSON object"}
    dim_type, values = str(payload.get("dim_type", "")), str(payload.get("values", ""))
    if len(values) > MAX_VALUES_TEXT:
        return {"ok": False, "error": f"values text is too long (over {MAX_VALUES_TEXT:,} characters)"}
    return preview_values(dim_type, values)


def register_routes(server):
    """Add the routes to a running PromptServer (a no-op without one)."""
    if server is None:
        return
    from aiohttp import web

    @server.routes.post("/sweepkit/preview_values")
    async def _preview_values(request):
        try:
            payload = await request.json()
        except ValueError:
            payload = None
        return web.json_response(preview_response(payload))
