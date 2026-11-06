function ensureBaseComputeSize(widget) {
    if (!widget.__sweepBaseComputeSize) {
        widget.__sweepBaseComputeSize = widget.computeSize ? widget.computeSize.bind(widget) : (w) => [w, 20];
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
    if (!raw) return [];
    return raw.split("\n").map((s) => s.trim()).filter((s) => s.length > 0);
}

function getWidget(node, name) { return node.widgets.find((w) => w.name === name); }

// Simplified sweepSync core logic under test (lora hide + model hint only)
function syncCore(node) {
    const typeW = getWidget(node, "dim_type");
    const valuesW = getWidget(node, "values");
    const loraNameW = getWidget(node, "lora_name");

    setWidgetHidden(loraNameW, typeW.value !== "lora_strength");

    if (typeW.value === "model") {
        if (valuesW && !valuesW.value.trim() && !node.__sweepModelHintShown) {
            valuesW.value = MODEL_VALUES_EXAMPLE;
            node.__sweepModelHintShown = true;
        }
    }
}

function assert(cond, msg) { if (!cond) throw new Error("FAIL: " + msg); }

function makeNode(type, valuesVal) {
    return {
        widgets: [
            { name: "dim_type", value: type },
            { name: "values", value: valuesVal, computeSize: (w) => [w, 60] },
            { name: "lora_name", value: "", computeSize: (w) => [w, 20] },
        ],
    };
}

// Test 1: lora_name hidden for non-lora_strength types
let node = makeNode("text", "");
syncCore(node);
assert(getWidget(node, "lora_name").hidden === true, "lora_name should be hidden for dim_type=text");
console.log("PASS test1: lora_name hidden for text");

// Test 2: lora_name visible for lora_strength
node = makeNode("lora_strength", "1.0");
syncCore(node);
assert(getWidget(node, "lora_name").hidden === false, "lora_name should be visible for dim_type=lora_strength");
console.log("PASS test2: lora_name visible for lora_strength");

// Test 3: switching to "model" with empty values fills in an example, exactly once
node = makeNode("model", "");
syncCore(node);
assert(getWidget(node, "values").value === MODEL_VALUES_EXAMPLE, "empty values should be auto-filled on first switch to model");
assert(node.__sweepModelHintShown === true, "hint-shown flag should be set");

// user clears it back out deliberately -> must NOT be re-filled
getWidget(node, "values").value = "";
syncCore(node);
assert(getWidget(node, "values").value === "", "deliberately cleared values must not be re-filled a second time");
console.log("PASS test3: model-type auto-fill fires once, never overwrites a deliberate later edit");

// Test 4: switching to "model" when values already has real content -> untouched
node = makeNode("model", "Base, Turbo");
syncCore(node);
assert(getWidget(node, "values").value === "Base, Turbo", "existing content must never be overwritten");
console.log("PASS test4: pre-filled values on switch to model are left alone");

console.log("\nALL LORA-HIDE / MODEL-HINT TESTS PASSED");
