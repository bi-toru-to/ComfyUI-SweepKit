import { api } from "../../scripts/api.js";
import { app } from "../../scripts/app.js";
import { configureApi, startPolling, sweepSync } from "./sweepkit_core.js";
import { applyLook } from "./sweepkit_look.js";
import { currentSelection, openPicker, storedOptions } from "./sweepkit_pick.js";
import {
    PLAN_CLASS,
    collectHere,
    hasImageOutput,
    planSnapshot,
    refreshRuns,
    sweepWidget,
    sweepableWidget,
    syncPlanOutputs,
} from "./sweepkit_soft.js";

/**
 * SweepDimension dynamic UI: MODEL sockets for dim_type "model" and the
 * conditional lora_name widget. The logic lives in sweepkit_core.js (so the
 * tests can import it); this file only hooks it into the node lifecycle.
 */

const NODE_NAME = "SweepDimension";

configureApi((path, init) => api.fetchApi(path, init));

/** Wrap a prototype hook so the original (if any) still runs first. */
function chain(proto, hook, extra) {
    const original = proto[hook];
    proto[hook] = function (...args) {
        const result = original ? original.apply(this, args) : undefined;
        extra(this);
        return result;
    };
}

app.registerExtension({
    name: "SweepKit.Dimension",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_NAME) return;
        const proto = nodeType.prototype;
        // New node, or one restored from a saved workflow: sync now, then
        // keep watching for changes.
        chain(proto, "onNodeCreated", (node) => {
            sweepSync(node);
            startPolling(node);
        });
        chain(proto, "onConfigure", (node) => {
            sweepSync(node);
            startPolling(node);
        });
        // Stops this node's polling loop.
        chain(proto, "onRemoved", (node) => {
            node.__sweepRemoved = true;
        });
    },
});

/** Role colours for every SweepKit node (see sweepkit_look.js). */
app.registerExtension({
    name: "SweepKit.Look",
    nodeCreated(node) {
        applyLook(node);
    },
});

/** Sweep Plan shows one output per axis in the chain feeding it. */
app.registerExtension({
    name: "SweepKit.Plan",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== PLAN_CLASS) return;
        const proto = nodeType.prototype;
        const watch = (node) =>
            startPolling(node, {
                sync: (n) => {
                    if (!n.graph) return;
                    syncPlanOutputs(n.graph, n);
                    refreshRuns(n.graph, n);
                },
                snapshotFn: (n) => (n.graph ? planSnapshot(n.graph, n) : ""),
            });
        chain(proto, "onNodeCreated", watch);
        chain(proto, "onConfigure", watch);
        chain(proto, "onRemoved", (node) => {
            node.__sweepRemoved = true;
        });
    },
});

function tell(summary, detail) {
    const toast = app.extensionManager && app.extensionManager.toast;
    if (toast) toast.add({ severity: "info", summary, detail, life: 6000 });
}

/** Right-click menu: sweep the setting under the pointer, or collect results here. */
app.registerExtension({
    name: "SweepKit.SweepThis",
    getNodeMenuItems(node) {
        const items = [];
        const env = { graph: node.graph, createNode: (cls) => LiteGraph.createNode(cls) };
        const pointer = app.canvas && app.canvas.graph_mouse;
        const widget = pointer && node.getWidgetOnPos ? node.getWidgetOnPos(pointer[0], pointer[1], true) : null;
        if (widget && sweepableWidget(node, widget)) {
            items.push({
                content: `Sweep "${widget.label || widget.name}"…`,
                callback: () => {
                    const message = sweepWidget(env, node, widget);
                    if (message) tell("SweepKit", message);
                },
            });
        }
        const options = storedOptions(node);
        const valuesWidget = node.widgets && node.widgets.find((w) => w.name === "values");
        if (options.length && valuesWidget) {
            items.push({
                content: "Pick values from the list…",
                callback: () =>
                    openPicker({
                        title: `Values for "${(node.widgets.find((w) => w.name === "dim_id") || {}).value || "this axis"}"`,
                        options,
                        selected: currentSelection(valuesWidget.value, options),
                        onApply: (text) => {
                            valuesWidget.value = text;
                            node.setDirtyCanvas(true, true);
                        },
                    }),
            });
        }
        if (hasImageOutput(node)) {
            items.push({
                content: "Sweep: collect results here",
                callback: () => {
                    const message = collectHere(env, node);
                    if (message) tell("SweepKit", message);
                },
            });
        }
        return items.length ? [null, ...items] : [];
    },
});

/** Sweep All-in-One shows how many images the axes feeding it will make. */
app.registerExtension({
    name: "SweepKit.RunCount",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== "SweepAllInOne") return;
        const proto = nodeType.prototype;
        const watch = (node) =>
            startPolling(node, {
                sync: (n) => n.graph && refreshRuns(n.graph, n),
                snapshotFn: (n) => (n.graph ? planSnapshot(n.graph, n) : ""),
            });
        chain(proto, "onNodeCreated", watch);
        chain(proto, "onConfigure", watch);
        chain(proto, "onRemoved", (node) => {
            node.__sweepRemoved = true;
        });
    },
});
