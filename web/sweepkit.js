import { app } from "../../scripts/app.js";

/**
 * SweepDimension dynamic UI.
 *
 * This is deliberately the ONLY dynamic-widget behavior left anywhere in
 * the SweepKit node pack. An earlier version had a single mega-node
 * (SweepAllInOne) that dynamically grew/shrank a block of up to 8
 * dimensions' worth of widgets in place, toggling `widget.hidden` on
 * already-built widgets to show/hide them. That fought this ComfyUI
 * frontend's widget rendering in ways that weren't reliably fixable from
 * outside — richer components (multiline text boxes) didn't consistently
 * rebuild themselves just from a property flip, producing a string of
 * different-looking rendering bugs across several rounds of fixes.
 *
 * The node pair was restructured so each dimension is its own ordinary
 * node (SweepDimension), chained together and fed into SweepAllInOne
 * through an SWEEP_DIMS socket. Adding, removing, and resizing *nodes* is
 * something ComfyUI already does correctly on its own — no help needed.
 *
 * The one thing that's still genuinely dynamic: when dim_type is set to
 * "model", the `values` field is reinterpreted as a list of labels, and
 * we keep that many MODEL input sockets (model_1, model_2, ...) on THIS
 * node in sync with it. This logic is carried over unchanged from the
 * mega-node version — it was never the source of a reported bug there,
 * only the widget-hiding half was.
 *
 * Two smaller additions on top of that:
 *  - `lora_name` (a combo/dropdown, not a multiline text box) is hidden
 *    unless dim_type is "lora_strength". Combos and plain strings hid and
 *    showed correctly via `.hidden` throughout every round of the
 *    mega-node's issues — it was specifically multiline text boxes that
 *    didn't reliably rebuild themselves — so applying the same treatment
 *    to a single combo on this much simpler node carries little of the
 *    risk that motivated dropping it everywhere else.
 *  - The first time `values` is switched to "model" while still empty, we
 *    fill in a short example ("model_a, model_b") so it's obvious you
 *    need to type labels there to get sockets, rather than silently
 *    having zero sockets with no indication why. This only ever touches
 *    a widget's *value*, the same as a user typing would — not its type,
 *    size, or DOM styling — so it doesn't touch any of the mechanisms
 *    that caused trouble before. It only fires once per node instance.
 */

const NODE_NAME = "SweepDimension";
// Sane ceiling so a fat-fingered paste can't spawn hundreds of sockets.
// Must match MAX_MODEL_SOCKETS in sweep_core.py (Python ignores extra labels).
const MAX_SOCKETS = 24;

function getWidget(node, name) {
    return node.widgets ? node.widgets.find((w) => w.name === name) : null;
}

/** Record each widget's true original computeSize exactly once, before we
 * ever override it. Only ever applied to `lora_name`, a combo widget —
 * see the file-level comment for why that's a safe use of `.hidden` when
 * the earlier, much larger version of this trick on multiline text boxes
 * was not. */
function ensureBaseComputeSize(widget) {
    if (!widget.__sweepBaseComputeSize) {
        widget.__sweepBaseComputeSize = widget.computeSize
            ? widget.computeSize.bind(widget)
            : (w) => [w, 20];
    }
}

function setWidgetHidden(widget, hidden) {
    if (!widget) return;
    ensureBaseComputeSize(widget);
    widget.hidden = hidden;
    widget.computeSize = (w) => (widget.hidden ? [0, -4] : widget.__sweepBaseComputeSize(w));
}

const MODEL_VALUES_EXAMPLE = "model_a\nmodel_b";

function parseLabelList(raw) {
    // Newline only, deliberately — a label is free text and could
    // legitimately contain a comma (e.g. "SDXL 1.0, refined"). This
    // mirrors the same fix on the Python side for text/static dimension
    // values, which had the same problem with comma-separated tag lists.
    if (!raw) return [];
    return raw
        .split("\n")
        .map((s) => s.trim())
        .filter((s) => s.length > 0)
        .slice(0, MAX_SOCKETS);
}

/** Add/remove/relabel model_* MODEL input sockets to match `labels`,
 * touching only the delta so existing links to unchanged slots survive
 * every keystroke in the values textbox. */
function syncModelSockets(node, labels) {
    const prefix = "model_";
    const desiredCount = labels.length;

    for (let idx = node.inputs ? node.inputs.length - 1 : -1; idx >= 0; idx--) {
        const inp = node.inputs[idx];
        if (!inp || !inp.name.startsWith(prefix)) continue;
        const n = parseInt(inp.name.slice(prefix.length), 10);
        if (Number.isNaN(n) || n > desiredCount) {
            if (inp.link != null) node.disconnectInput(idx);
            node.removeInput(idx);
        }
    }

    for (let i = 1; i <= desiredCount; i++) {
        const name = `${prefix}${i}`;
        const labelText = labels[i - 1];
        let inp = node.inputs ? node.inputs.find((x) => x.name === name) : null;
        if (!inp) {
            node.addInput(name, "MODEL");
            inp = node.inputs[node.inputs.length - 1];
        }
        inp.label = labelText;
    }
}

function removeAllModelSockets(node) {
    const prefix = "model_";
    for (let idx = node.inputs ? node.inputs.length - 1 : -1; idx >= 0; idx--) {
        const inp = node.inputs[idx];
        if (inp && inp.name.startsWith(prefix)) {
            if (inp.link != null) node.disconnectInput(idx);
            node.removeInput(idx);
        }
    }
}

function sweepSync(node) {
    const typeW = getWidget(node, "dim_type");
    const valuesW = getWidget(node, "values");
    const loraNameW = getWidget(node, "lora_name");
    if (!typeW) return;

    setWidgetHidden(loraNameW, typeW.value !== "lora_strength");

    if (typeW.value === "model") {
        if (valuesW && !valuesW.value.trim() && !node.__sweepModelHintShown) {
            valuesW.value = MODEL_VALUES_EXAMPLE;
            node.__sweepModelHintShown = true;
        }
        syncModelSockets(node, parseLabelList(valuesW ? valuesW.value : ""));
    } else {
        removeAllModelSockets(node);
    }

    requestAnimationFrame(() => {
        const newSize = node.computeSize();
        const targetSize = [Math.max(node.size[0], newSize[0]), newSize[1]];
        if (node.onResize) {
            node.onResize(targetSize);
        } else {
            node.setSize(targetSize);
        }
        node.setDirtyCanvas(true, true);
    });
}

function snapshot(node) {
    const typeW = getWidget(node, "dim_type");
    const valuesW = getWidget(node, "values");
    return (typeW ? typeW.value : "") + "\u0001" + (valuesW ? valuesW.value : "");
}

function startPolling(node) {
    if (node.__sweepPolling) return;
    node.__sweepPolling = true;
    node.__sweepLastSnapshot = null;

    const tick = () => {
        if (node.__sweepRemoved) return;
        const snap = snapshot(node);
        if (snap !== node.__sweepLastSnapshot) {
            node.__sweepLastSnapshot = snap;
            sweepSync(node);
        }
        requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
}

function sweepSetup(node) {
    if (!getWidget(node, "dim_type")) return;
    sweepSync(node);
    startPolling(node);
}

app.registerExtension({
    name: "SweepKit.Dimension",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_NAME) return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const r = onNodeCreated ? onNodeCreated.apply(this, arguments) : undefined;
            sweepSetup(this);
            return r;
        };

        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function (info) {
            const r = onConfigure ? onConfigure.apply(this, arguments) : undefined;
            sweepSync(this);
            startPolling(this);
            return r;
        };

        const onRemoved = nodeType.prototype.onRemoved;
        nodeType.prototype.onRemoved = function () {
            this.__sweepRemoved = true;
            return onRemoved ? onRemoved.apply(this, arguments) : undefined;
        };
    },
});
