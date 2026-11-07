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

/** Bring sockets and widget visibility in line with the current widget
 * values. `scheduleResize` (default: next animation frame) runs the resize
 * after the frontend has laid out the change; pass null to skip it. */
export function sweepSync(node, scheduleResize = globalThis.requestAnimationFrame) {
    const typeW = getWidget(node, "dim_type");
    const valuesW = getWidget(node, "values");
    if (!typeW) return;

    setWidgetHidden(getWidget(node, "lora_name"), typeW.value !== "lora_strength");

    if (typeW.value === "model") {
        if (valuesW && !valuesW.value.trim() && !node.__sweepModelHintShown) {
            valuesW.value = MODEL_VALUES_EXAMPLE;
            node.__sweepModelHintShown = true;
        }
        syncModelSockets(node, parseLabelList(valuesW ? valuesW.value : ""));
    } else {
        removeAllModelSockets(node);
    }

    if (scheduleResize) scheduleResize(() => fitNodeSize(node));
}

/** The values polling compares between ticks. */
export function snapshot(node) {
    const typeW = getWidget(node, "dim_type");
    const valuesW = getWidget(node, "values");
    return (typeW ? typeW.value : "") + "\u0001" + (valuesW ? valuesW.value : "");
}

/** Re-sync whenever dim_type or values changes, checking every
 * POLL_INTERVAL_MS until the node is removed (node.__sweepRemoved). Calling
 * it again for the same node does nothing. */
export function startPolling(
    node,
    { sync = sweepSync, schedule = (fn) => setTimeout(fn, POLL_INTERVAL_MS) } = {},
) {
    if (node.__sweepPolling) return;
    node.__sweepPolling = true;
    node.__sweepLastSnapshot = null;
    const tick = () => {
        if (node.__sweepRemoved) return;
        const snap = snapshot(node);
        if (snap !== node.__sweepLastSnapshot) {
            node.__sweepLastSnapshot = snap;
            sync(node);
        }
        schedule(tick);
    };
    schedule(tick);
}
