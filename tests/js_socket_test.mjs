// MODEL-socket diffing, exercised through the real functions in
// web/sweepkit_core.js (no copied logic).
import { MAX_SOCKETS, parseLabelList, syncModelSockets } from "../web/sweepkit_core.js";

function makeMockNode() {
    return {
        inputs: [],
        disconnectCalls: [],
        addInput(name, type) { this.inputs.push({ name, type, link: null, label: null }); },
        removeInput(idx) { this.inputs.splice(idx, 1); },
        disconnectInput(idx) { this.disconnectCalls.push(idx); this.inputs[idx].link = null; },
    };
}

function assert(cond, msg) { if (!cond) throw new Error("FAIL: " + msg); }

let node = makeMockNode();
syncModelSockets(node, ["Base", "Turbo"]);
assert(node.inputs.length === 2 && node.inputs[0].name === "model_1" && node.inputs[1].name === "model_2", "basic add: " + JSON.stringify(node.inputs));
console.log("PASS test1: basic add, no dimension-index prefix needed anymore");

node.inputs[0].link = 999;
syncModelSockets(node, ["Base SDXL", "Turbo"]);
assert(node.inputs[0].link === 999, "relabel must preserve link");
assert(node.inputs[0].label === "Base SDXL", "label must update");
console.log("PASS test2: relabel preserves link");

node.inputs[1].link = 555;
syncModelSockets(node, ["Base SDXL"]);
assert(node.inputs.length === 1, "shrink should remove trailing socket");
assert(node.disconnectCalls.length === 1, "shrink should disconnect the removed linked socket");
console.log("PASS test3: shrink disconnects+removes trailing socket");

syncModelSockets(node, ["Base SDXL", "Lightning", "Hyper"]);
assert(node.inputs.length === 3 && node.inputs[0].link === 999, "grow should preserve earlier link and append new slots");
console.log("PASS test4: grow preserves earlier link, appends new slots");

assert(JSON.stringify(parseLabelList("a\nb\nc")) === JSON.stringify(["a", "b", "c"]), "newline-separated");
assert(JSON.stringify(parseLabelList("SDXL 1.0, refined\nTurbo")) === JSON.stringify(["SDXL 1.0, refined", "Turbo"]),
    "a comma WITHIN a label must be preserved, not split on -- only newlines separate labels");
assert(parseLabelList("").length === 0, "empty -> []");
console.log("PASS test5: parseLabelList (newline-only, commas preserved as label content)");

console.log("\nALL SOCKET SYNC TESTS PASSED (single-node scope)");
