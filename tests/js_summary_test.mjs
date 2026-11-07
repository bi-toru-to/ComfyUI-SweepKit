// The summary line under an axis's values, exercised through the real
// functions from web/sweepkit_core.js (no copied logic).
import {
    SUMMARY_WIDGET,
    describeValues,
    ensureSummaryWidget,
    fitText,
    refreshSummary,
    getWidget,
} from "../web/sweepkit_core.js";

function assert(cond, msg) {
    if (!cond) throw new Error("FAIL: " + msg);
}

function makeNode(type, values, pylist = false) {
    return {
        inputs: pylist ? [{ name: "values_pylist", link: 7 }] : [],
        widgets: [
            { name: "dim_type", value: type },
            { name: "values", value: values },
        ],
        addCustomWidget(w) {
            this.widgets.push(w);
            return w;
        },
        setDirtyCanvas() {
            this.dirty = (this.dirty || 0) + 1;
        },
    };
}

// A scheduler that queues work until the test runs it, like setTimeout would.
function fakeTimers() {
    const queue = [];
    return {
        schedule: (fn, _ms) => queue.push({ fn, live: true }) - 1,
        cancel: (id) => {
            queue[id].live = false;
        },
        async flush() {
            for (const t of queue.splice(0)) if (t.live) await t.fn();
        },
    };
}

// describeValues
assert(describeValues({ ok: true, count: 3, labels: ["1", "2", "3"] }).text === "3 values: 1 · 2 · 3", "plural");
assert(describeValues({ ok: true, count: 1, labels: ["5"] }).text === "1 value: 5", "singular");
assert(describeValues({ ok: true, count: 20, labels: ["1", "2"] }).text.endsWith("…"), "more values than shown");
let d = describeValues({ ok: false, error: "could not parse value 'x' as int." });
assert(d.error && d.text.includes("could not parse"), "error text");
assert(describeValues({ ok: true, count: 0, labels: [] }).error === true, "empty is flagged");
assert(describeValues(null).text === "", "no answer, no text");
console.log("PASS test1: describeValues");

// fitText with a fake measure (6 px per character)
const ctx = { measureText: (t) => ({ width: t.length * 6 }) };
assert(fitText(ctx, "short", 100) === "short", "fits as is");
const cut = fitText(ctx, "a very long line of text that cannot fit", 60);
assert(cut.endsWith("…") && cut.length * 6 <= 66, `ellipsis fit, got ${cut}`);
console.log("PASS test2: fitText");

// The widget is created once and never serialized.
let node = makeNode("seed", "1-3");
const w = ensureSummaryWidget(node);
assert(w === ensureSummaryWidget(node) && node.widgets.filter((x) => x.name === SUMMARY_WIDGET).length === 1, "created once");
assert(w.serialize === false && w.options.serialize === false, "not saved with the workflow");
assert(ensureSummaryWidget({ widgets: [] }) === null, "node without custom widget support is skipped");
console.log("PASS test3: summary widget created once, not serialized");

// Typing is debounced and the answer lands on the widget.
async function run() {
    const calls = [];
    const post = async (path, body) => {
        calls.push([path, body]);
        return { ok: true, count: 3, labels: ["1", "2", "3"] };
    };
    const t = fakeTimers();
    node = makeNode("seed", "1");
    refreshSummary(node, { post, ...t });
    node.widgets[1].value = "1-";
    refreshSummary(node, { post, ...t });
    node.widgets[1].value = "1-3";
    refreshSummary(node, { post, ...t });
    await t.flush();
    assert(calls.length === 1, `three edits should send one request, got ${calls.length}`);
    assert(calls[0][0] === "/sweepkit/preview_values" && calls[0][1].values === "1-3" && calls[0][1].dim_type === "seed", "request body");
    assert(getWidget(node, SUMMARY_WIDGET).value === "3 values: 1 · 2 · 3", "text shown");
    console.log("PASS test4: edits are debounced into one request");

    // An answer that arrives after the text changed again is dropped.
    const t2 = fakeTimers();
    node = makeNode("seed", "1-3");
    let release;
    const slow = () => new Promise((resolve) => (release = () => resolve({ ok: true, count: 3, labels: ["1", "2", "3"] })));
    refreshSummary(node, { post: slow, ...t2 });
    const pending = t2.flush();
    node.widgets[1].value = "9";
    release();
    await pending;
    assert(getWidget(node, SUMMARY_WIDGET).value === "", "stale answer must not be shown");
    console.log("PASS test5: a stale answer is ignored");

    // A connected PyList replaces the values: no request, explanatory text.
    const t3 = fakeTimers();
    let sent = 0;
    node = makeNode("seed", "1", true);
    refreshSummary(node, { post: async () => (sent++, { ok: true, count: 1, labels: ["1"] }), ...t3 });
    await t3.flush();
    assert(sent === 0 && getWidget(node, SUMMARY_WIDGET).value.includes("connected list"), "pylist case");
    console.log("PASS test6: connected list needs no request");

    // The backend being unreachable leaves a blank line, never an exception.
    const t4 = fakeTimers();
    node = makeNode("seed", "1-3");
    refreshSummary(node, {
        post: async () => {
            throw new Error("offline");
        },
        ...t4,
    });
    await t4.flush();
    assert(getWidget(node, SUMMARY_WIDGET).value === "", "offline -> blank");
    console.log("PASS test7: unreachable backend is harmless");
}
await run();
