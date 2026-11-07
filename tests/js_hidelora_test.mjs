// lora_name visibility and the one-time model example, exercised through the
// real sweepSync() from web/sweepkit_core.js (no copied logic).
import { MODEL_VALUES_EXAMPLE, getWidget, sweepSync } from "../web/sweepkit_core.js";

function assert(cond, msg) {
    if (!cond) throw new Error("FAIL: " + msg);
}

function makeNode(type, valuesVal) {
    return {
        inputs: [],
        widgets: [
            { name: "dim_type", value: type },
            { name: "values", value: valuesVal, computeSize: (w) => [w, 60] },
            { name: "lora_name", value: "", computeSize: (w) => [w, 20] },
        ],
        addInput(name, type) {
            this.inputs.push({ name, type, link: null, label: null });
        },
        removeInput(idx) {
            this.inputs.splice(idx, 1);
        },
        disconnectInput() {},
    };
}

const sync = (node) => sweepSync(node, null); // no resize in these tests

// Test 1: lora_name hidden for non-lora_strength types, and takes no space
let node = makeNode("text", "");
sync(node);
const lora = getWidget(node, "lora_name");
assert(lora.hidden === true, "lora_name should be hidden for dim_type=text");
assert(JSON.stringify(lora.computeSize(100)) === JSON.stringify([0, -4]), "hidden widget must collapse");
console.log("PASS test1: lora_name hidden (and collapsed) for text");

// Test 2: lora_name visible for lora_strength, original size restored
node = makeNode("lora_strength", "1.0");
sync(node);
assert(getWidget(node, "lora_name").hidden === false, "lora_name should be visible for dim_type=lora_strength");
assert(JSON.stringify(getWidget(node, "lora_name").computeSize(100)) === JSON.stringify([100, 20]), "size restored");
console.log("PASS test2: lora_name visible for lora_strength");

// Test 3: switching to "model" with empty values fills in an example exactly once
node = makeNode("model", "");
sync(node);
assert(getWidget(node, "values").value === MODEL_VALUES_EXAMPLE, "empty values should be auto-filled on first switch to model");
assert(node.__sweepModelHintShown === true, "hint-shown flag should be set");
assert(node.inputs.map((i) => i.label).join("|") === "model_a|model_b", "example labels create two sockets");
getWidget(node, "values").value = ""; // user clears it deliberately -> must NOT be re-filled
sync(node);
assert(getWidget(node, "values").value === "", "deliberately cleared values must not be re-filled a second time");
assert(node.inputs.length === 0, "clearing the labels removes the sockets");
console.log("PASS test3: model-type auto-fill fires once, never overwrites a deliberate later edit");

// Test 4: switching to "model" when values already has real content -> untouched
node = makeNode("model", "Base, Turbo");
sync(node);
assert(getWidget(node, "values").value === "Base, Turbo", "existing content must never be overwritten");
assert(node.inputs.length === 1 && node.inputs[0].label === "Base, Turbo", "one label (commas don't split)");
console.log("PASS test4: pre-filled values on switch to model are left alone");

// Test 5: leaving "model" removes every model_N socket
node.widgets[0].value = "seed";
sync(node);
assert(node.inputs.length === 0, "switching away from model removes its sockets");
console.log("PASS test5: switching away from model removes the sockets");

// Test 6: the resize is scheduled (not run inline) when a scheduler is given
let scheduled = null;
node = Object.assign(makeNode("text", ""), {
    size: [200, 100],
    computeSize: () => [180, 140],
    setSize(s) {
        this.size = s;
    },
    setDirtyCanvas() {},
});
sweepSync(node, (fn) => {
    scheduled = fn;
});
assert(typeof scheduled === "function" && node.size[1] === 100, "resize waits for the scheduler");
scheduled();
assert(JSON.stringify(node.size) === JSON.stringify([200, 140]), "resize keeps width, fits height: " + node.size);
console.log("PASS test6: resize is deferred and keeps the user's width");

console.log("\nALL LORA-HIDE / MODEL-HINT TESTS PASSED");
