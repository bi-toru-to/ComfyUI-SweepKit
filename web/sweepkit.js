import { api } from "../../scripts/api.js";
import { app } from "../../scripts/app.js";
import { configureApi, startPolling, sweepSync } from "./sweepkit_core.js";
import { applyLook } from "./sweepkit_look.js";

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
