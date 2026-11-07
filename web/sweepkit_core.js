/**
 * SweepDimension UI logic, independent of the ComfyUI app object so the
 * tests in tests/*.mjs can import and exercise this exact code.
 * web/sweepkit.js only wires these functions into the node's lifecycle.
 *
 * What it does for a SweepDimension node:
 *  - dim_type "model": keeps one MODEL input socket (model_1, model_2, ...)
 *    per line of `values`, relabelled from the text. Only the difference is
 *    applied, so links on unchanged sockets survive every keystroke.
 *  - dim_type "model" with empty `values`: fills in a two-line example
 *    once, so it's clear labels are needed to get sockets.
 *  - Neither happens while `values_pylist` is connected: the connected
 *    list supplies the models itself and replaces the sockets.
 *  - A one-line summary under `values` ("3 values: 1 · 2 · 3", or what is
 *    wrong with the text), asked of the backend's own parser so the count
 *    can never disagree with what the sweep will do.
 *  - `lora_name` (a combo) is shown only for dim_type "lora_strength".
 *    Hiding is limited to this one combo widget: hiding multiline text
 *    widgets proved unreliable in this frontend (see DESIGN.md).
 *
 * Changes are detected by polling rather than widget callbacks, because
 * this frontend doesn't reliably fire a callback for every way a value
 * changes (e.g. undo, paste, workflow load).
 */

// Ceiling so a fat-fingered paste can't spawn hundreds of sockets.
// Must match MAX_MODEL_SOCKETS in sweep_core.py (Python ignores extra labels).
export const MAX_SOCKETS = 24;

// How often each SweepDimension node checks its widgets for changes.
// 10 Hz is immediate to a person typing, at a fraction of per-frame cost.
export const POLL_INTERVAL_MS = 100;

export const MODEL_VALUES_EXAMPLE = "model_a\nmodel_b";

const SOCKET_PREFIX = "model_";

export function getWidget(node, name) {
    return node.widgets ? node.widgets.find((w) => w.name === name) : null;
}

/** Record a widget's original computeSize once, before overriding it. */
export function ensureBaseComputeSize(widget) {
    if (!widget.__sweepBaseComputeSize) {
        widget.__sweepBaseComputeSize = widget.computeSize ? widget.computeSize.bind(widget) : (w) => [w, 20];
    }
}

/** Hide/show a (combo) widget: hidden widgets take no vertical space. */
export function setWidgetHidden(widget, hidden) {
    if (!widget) return;
    ensureBaseComputeSize(widget);
    widget.hidden = hidden;
    widget.computeSize = (w) => (widget.hidden ? [0, -4] : widget.__sweepBaseComputeSize(w));
}

/** Socket labels: one per line (a label may contain commas), capped. */
export function parseLabelList(raw) {
    if (!raw) return [];
    return raw
        .split("\n")
        .map((s) => s.trim())
        .filter((s) => s.length > 0)
        .slice(0, MAX_SOCKETS);
}

/** Add/remove/relabel model_N sockets to match `labels`, touching only the
 * difference so existing links to unchanged slots survive. */
export function syncModelSockets(node, labels) {
    const desiredCount = labels.length;
    for (let idx = node.inputs ? node.inputs.length - 1 : -1; idx >= 0; idx--) {
        const inp = node.inputs[idx];
        if (!inp || !inp.name.startsWith(SOCKET_PREFIX)) continue;
        const n = parseInt(inp.name.slice(SOCKET_PREFIX.length), 10);
        if (Number.isNaN(n) || n > desiredCount) {
            if (inp.link != null) node.disconnectInput(idx);
            node.removeInput(idx);
        }
    }
    for (let i = 1; i <= desiredCount; i++) {
        const name = `${SOCKET_PREFIX}${i}`;
        let inp = node.inputs ? node.inputs.find((x) => x.name === name) : null;
        if (!inp) {
            node.addInput(name, "MODEL");
            inp = node.inputs[node.inputs.length - 1];
        }
        inp.label = labels[i - 1];
    }
}

export function removeAllModelSockets(node) {
    syncModelSockets(node, []);
}

/** Resize the node to fit its (possibly changed) widgets and sockets. */
export function fitNodeSize(node) {
    const newSize = node.computeSize();
    const targetSize = [Math.max(node.size[0], newSize[0]), newSize[1]];
    if (node.onResize) {
        node.onResize(targetSize);
    } else {
        node.setSize(targetSize);
    }
    node.setDirtyCanvas(true, true);
}

/** True when a PyList is connected to values_pylist (it overrides `values`). */
export function pylistConnected(node) {
    return Boolean(node.inputs && node.inputs.some((i) => i.name === "values_pylist" && i.link != null));
}

// ---- summary line under `values` ----

export const SUMMARY_WIDGET = "sweepkit_summary";
export const SUMMARY_DEBOUNCE_MS = 250;
const SUMMARY_COLOR = "#9aa5b1";
const SUMMARY_ERROR_COLOR = "#f0a050";

/** Text and error flag for the summary line, from the backend's answer
 * ({ok, count, labels} or {ok: false, error}). */
export function describeValues(res) {
    if (!res) return { text: "", error: false };
    if (!res.ok) return { text: `⚠ ${res.error}`, error: true };
    if (res.count === 0) return { text: "no values: this axis is skipped", error: true };
    const more = res.count > res.labels.length ? " …" : "";
    const noun = res.count === 1 ? "value" : "values";
    return { text: `${res.count} ${noun}: ${res.labels.join(" · ")}${more}`, error: false };
}

/** `text` shortened with an ellipsis until it fits `maxWidth` (measured with `ctx`). */
export function fitText(ctx, text, maxWidth) {
    if (ctx.measureText(text).width <= maxWidth) return text;
    let cut = text;
    while (cut.length > 1 && ctx.measureText(`${cut}…`).width > maxWidth) cut = cut.slice(0, -1);
    return `${cut}…`;
}

/** Ask the backend how `values` parses. Resolves to null if it can't be reached. */
export async function fetchValuesSummary(dimType, values, post = defaultPost) {
    try {
        return await post("/sweepkit/preview_values", { dim_type: dimType, values });
    } catch (_err) {
        return null;
    }
}

let apiFetch = null;

/** Use ComfyUI's own fetch (api.fetchApi) for backend calls, so a base path
 * or auth header configured for the server is honoured. */
export function configureApi(fetchApi) {
    apiFetch = fetchApi;
}

async function defaultPost(path, body) {
    const init = { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
    const resp = await (apiFetch ? apiFetch(path, init) : fetch(path, init));
    return resp.json();
}

/** The summary widget of a node, creating it (drawn on the canvas, never
 * saved with the workflow) on first use. Null when the node can't take custom widgets. */
export function ensureSummaryWidget(node) {
    const existing = getWidget(node, SUMMARY_WIDGET);
    if (existing || typeof node.addCustomWidget !== "function") return existing || null;
    const widget = {
        name: SUMMARY_WIDGET,
        type: "sweepkit_summary",
        value: "",
        error: false,
        serialize: false,
        options: { serialize: false },
        computeSize: (width) => [width, 22],
        draw(ctx, _node, width, y, height) {
            if (!this.value) return;
            ctx.save();
            ctx.font = "12px sans-serif";
            ctx.fillStyle = this.error ? SUMMARY_ERROR_COLOR : SUMMARY_COLOR;
            ctx.textAlign = "left";
            ctx.textBaseline = "middle";
            ctx.fillText(fitText(ctx, this.value, width - 30), 15, y + height / 2);
            ctx.restore();
        },
    };
    node.addCustomWidget(widget);
    return widget;
}

/** Update the summary line, after a short pause so typing doesn't send a
 * request per keystroke. `schedule`/`cancel` are injectable for tests. */
export function refreshSummary(
    node,
    { post = defaultPost, schedule = (fn, ms) => setTimeout(fn, ms), cancel = (id) => clearTimeout(id) } = {},
) {
    const widget = ensureSummaryWidget(node);
    if (!widget) return;
    if (node.__sweepSummaryTimer != null) cancel(node.__sweepSummaryTimer);
    if (pylistConnected(node)) {
        Object.assign(widget, { value: "values come from the connected list", error: false });
        node.setDirtyCanvas(true, true);
        return;
    }
    const typeW = getWidget(node, "dim_type");
    const valuesW = getWidget(node, "values");
    const type = typeW ? typeW.value : "";
    const values = valuesW ? valuesW.value : "";
    node.__sweepSummaryTimer = schedule(async () => {
        node.__sweepSummaryTimer = null;
        const res = await fetchValuesSummary(type, values, post);
        // Ignore an answer that arrives after the text has changed again.
        if (node.__sweepRemoved || !typeW || typeW.value !== type || !valuesW || valuesW.value !== values) return;
        const { text, error } = describeValues(res);
        Object.assign(widget, { value: text, error, count: res && res.ok ? res.count : undefined });
        node.setDirtyCanvas(true, true);
    }, SUMMARY_DEBOUNCE_MS);
}

/** Bring sockets and widget visibility in line with the current widget
 * values. `scheduleResize` (default: next animation frame) runs the resize
 * after the frontend has laid out the change; pass null to skip it. */
export function sweepSync(node, scheduleResize = globalThis.requestAnimationFrame) {
    const typeW = getWidget(node, "dim_type");
    const valuesW = getWidget(node, "values");
    if (!typeW) return;

    setWidgetHidden(getWidget(node, "lora_name"), typeW.value !== "lora_strength");

    if (typeW.value === "model" && !pylistConnected(node)) {
        if (valuesW && !valuesW.value.trim() && !node.__sweepModelHintShown) {
            valuesW.value = MODEL_VALUES_EXAMPLE;
            node.__sweepModelHintShown = true;
        }
        syncModelSockets(node, parseLabelList(valuesW ? valuesW.value : ""));
    } else {
        removeAllModelSockets(node);
    }

    if (typeof node.addCustomWidget === "function") refreshSummary(node);

    if (scheduleResize) scheduleResize(() => fitNodeSize(node));
}

/** The state polling compares between ticks (including whether a PyList
 * is connected, since that switches the sockets off and on). */
export function snapshot(node) {
    const typeW = getWidget(node, "dim_type");
    const valuesW = getWidget(node, "values");
    return [typeW ? typeW.value : "", valuesW ? valuesW.value : "", pylistConnected(node) ? "1" : "0"].join("\u0001");
}

/** Re-sync whenever the node's snapshot (dim_type and values by default) changes, checking every
 * POLL_INTERVAL_MS until the node is removed (node.__sweepRemoved). Calling
 * it again for the same node does nothing. */
export function startPolling(
    node,
    { sync = sweepSync, schedule = (fn) => setTimeout(fn, POLL_INTERVAL_MS), snapshotFn = snapshot } = {},
) {
    if (node.__sweepPolling) return;
    node.__sweepPolling = true;
    node.__sweepLastSnapshot = null;
    const tick = () => {
        if (node.__sweepRemoved) return;
        const snap = snapshotFn(node);
        if (snap !== node.__sweepLastSnapshot) {
            node.__sweepLastSnapshot = snap;
            sync(node);
        }
        schedule(tick);
    };
    schedule(tick);
}
