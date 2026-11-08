// "Sweep this setting": value suggestions, wiring and Plan outputs, exercised
// through the real functions from web/sweepkit_soft.js on a fake graph.
import {
    MAX_AXIS_OUTPUTS,
    axisChain,
    axisPickerNames,
    pickerSnapshot,
    syncAxisPickers,
    collectHere,
    hasImageOutput,
    planSnapshot,
    suggestValues,
    sweepCandidates,
    sweepWidget,
    sweepableWidget,
    syncPlanOutputs,
    widgetInfo,
} from "../web/sweepkit_soft.js";
import { FakeGraph, env } from "./stubs/fake_graph.mjs";

function assert(cond, msg) {
    if (!cond) throw new Error("FAIL: " + msg);
}
const eq = (a, b, msg) => assert(JSON.stringify(a) === JSON.stringify(b), `${msg}: got ${JSON.stringify(a)}, wanted ${JSON.stringify(b)}`);
const widget = (node, name) => node.widgets.find((w) => w.name === name);
const sock = (node, name) => node.inputs.find((i) => i.name === name);

// ---- describing settings ----
let g = new FakeGraph();
const ks = g.make("KSampler");
eq(widgetInfo(widget(ks, "seed")).dimType, "seed", "seed type");
eq(widgetInfo(widget(ks, "steps")).dimType, "steps", "steps type");
eq(widgetInfo(widget(ks, "cfg")).dimType, "cfg", "cfg type");
eq(widgetInfo(widget(ks, "denoise")).dimType, "float", "decimal number is float");
eq(widgetInfo({ name: "width", type: "number", value: 512, options: { precision: 0 } }).dimType, "int", "whole number is int");
eq(widgetInfo(widget(ks, "sampler_name")).kind, "combo", "combo kind");
eq(widgetInfo({ name: "go", type: "button" }), null, "buttons can't be swept");
eq(widgetInfo({ name: "x", type: "number", value: 1, hidden: true }), null, "hidden widgets can't be swept");
eq(widgetInfo({ name: "t", type: "customtext", value: "a cat" }).kind, "text", "text kind");
console.log("PASS test1: settings are described by kind and axis type");

// ---- suggested values ----
eq(suggestValues(widgetInfo(widget(ks, "seed"))), "5-7", "seed");
eq(suggestValues(widgetInfo(widget(ks, "steps"))), "20, 25, 30", "steps");
eq(suggestValues(widgetInfo(widget(ks, "cfg"))), "7, 8.8, 10.6", "cfg");
eq(suggestValues(widgetInfo(widget(ks, "denoise"))), "1", "denoise is clamped to its maximum and de-duplicated");
eq(suggestValues(widgetInfo(widget(ks, "sampler_name"))), "heun\ndpmpp\neuler", "combo starts at the current value and wraps");
eq(suggestValues(widgetInfo({ name: "p", type: "customtext", value: "a red car" })), "a red car", "text keeps its own text");
eq(suggestValues({ kind: "combo", value: "x", options: [] }), "x", "empty option list falls back to the value");
console.log("PASS test2: suggested values are sensible and within limits");

// ---- which settings can be swept ----
assert(sweepableWidget(ks, widget(ks, "cfg")), "plain widget with a socket is sweepable");
sock(ks, "steps").link = 99;
assert(sweepableWidget(ks, widget(ks, "steps")) === null, "an already wired setting is not offered again");
const plan0 = g.make("SweepCombinationExpander");
assert(sweepableWidget(plan0, { name: "dimensions", type: "number", value: 1 }) === null, "SweepKit's own nodes are not offered");
eq(sweepableWidget({ comfyClass: "Other", inputs: [], widgets: [] }, { name: "x", type: "number", value: 1 }), null, "widget without a socket");
console.log("PASS test3: only free settings on other nodes are offered");

// ---- sweeping a setting wires everything ----
g = new FakeGraph();
const sampler = g.make("KSampler");
const msg1 = sweepWidget(env(g), sampler, widget(sampler, "seed"));
assert(msg1 && msg1.includes("seed"), "first sweep reports success");
const plans = g._nodes.filter((n) => n.comfyClass === "SweepCombinationExpander");
const axes = g._nodes.filter((n) => n.comfyClass === "SweepDimension");
assert(plans.length === 1 && axes.length === 1, "one Plan and one Axis were added");
const plan = plans[0];
eq([widget(axes[0], "dim_type").value, widget(axes[0], "dim_id").value, widget(axes[0], "values").value], ["seed", "seed", "5-7"], "axis settings");
assert(g.getNodeById(g.links[sock(plan, "dimensions").link].origin_id) === axes[0], "axis feeds the Plan");
const seedLink = g.links[sock(sampler, "seed").link];
assert(g.getNodeById(seedLink.origin_id) === plan && plan.outputs[seedLink.origin_slot].name === "axis_1", "Plan axis_1 feeds the seed setting");
assert(g.changes.before === 1 && g.changes.after === 1, "one undo step");
eq(plan.outputs.map((o) => o.name), ["combo", "combo_count", "dim_map", "axis_1"], "unused axis outputs are removed");
eq(plan.outputs[3].label, "seed", "output is labelled with the axis name");

// A second setting chains after the first and uses the same Plan.
const msg2 = sweepWidget(env(g), sampler, widget(sampler, "cfg"));
assert(msg2, "second sweep reports success");
assert(g._nodes.filter((n) => n.comfyClass === "SweepCombinationExpander").length === 1, "Plan is reused");
const axes2 = g._nodes.filter((n) => n.comfyClass === "SweepDimension");
assert(axes2.length === 2, "second axis added");
assert(g.getNodeById(g.links[sock(axes2[1], "prev_dimensions").link].origin_id) === axes2[0], "second axis chains after the first");
assert(g.getNodeById(g.links[sock(plan, "dimensions").link].origin_id) === axes2[1], "the Plan now reads from the last axis");
eq(plan.outputs.map((o) => o.label || o.name).slice(3), ["seed", "cfg"], "labels follow the chain");
const cfgLink = g.links[sock(sampler, "cfg").link];
assert(plan.outputs[cfgLink.origin_slot].name === "axis_2", "axis_2 feeds cfg");
assert(sweepWidget(env(g), sampler, widget(sampler, "cfg")) === null, "an already swept setting is refused");
// New nodes go above the user's own nodes, and axes line up in a row without overlapping.
const mine = g._nodes.filter((n) => !String(n.comfyClass).startsWith("Sweep"));
const top = Math.min(...mine.map((n) => n.pos[1]));
const added = g._nodes.filter((n) => n.comfyClass === "SweepCombinationExpander" || n.comfyClass === "SweepDimension");
assert(added.every((n) => n.pos[1] < top), "Plan and axes sit above the existing graph");
const xs = added.map((n) => n.pos[0]);
assert(new Set(xs).size === xs.length, "no two new nodes share a column");
const chainX = [...axes2, plan].map((n) => n.pos[0]);
assert(chainX.every((x, i) => i === 0 || x > chainX[i - 1]), "the row reads left to right in chain order, ending at the Plan");
console.log("PASS test4: sweeping settings adds axes, chains them and wires the Plan outputs");

// ---- collecting ----
const decode = g.make("VAEDecode");
assert(hasImageOutput(decode) && !hasImageOutput(plan), "image sources are offered, SweepKit's own nodes are not");
assert(collectHere(env(g), decode), "collect reports success");
const collect = g._nodes.find((n) => n.comfyClass === "SweepCollect");
assert(g.getNodeById(g.links[sock(collect, "images").link].origin_id) === decode, "image wired");
const comboLink = g.links[sock(collect, "combo").link];
assert(g.getNodeById(comboLink.origin_id) === plan && comboLink.origin_slot === 0, "combo wired from the Plan");
collectHere(env(g), decode);
assert(g._nodes.filter((n) => n.comfyClass === "SweepCollect").length === 1, "no second Collect");

const bare = new FakeGraph();
const dec2 = bare.make("VAEDecode");
collectHere(env(bare), dec2);
assert(bare._nodes.some((n) => n.comfyClass === "SweepCombinationExpander"), "a Plan is created when there is none");
console.log("PASS test5: Collect is wired to the image and the Plan, once");

// ---- Plan outputs follow the chain ----
g = new FakeGraph();
const p = g.make("SweepCombinationExpander");
const a1 = g.make("SweepDimension", { dim_type: "seed", values: "1-3" });
const a2 = g.make("SweepDimension", { dim_type: "cfg", dim_id: "guidance", values: "4,7" });
a1.connect(0, a2, 0);
a2.connect(0, p, 0);
syncPlanOutputs(g, p);
eq(p.outputs.map((o) => o.label || o.name).slice(3), ["seed", "guidance"], "outputs trimmed to the chain");
const before = planSnapshot(g, p);
widget(a2, "dim_id").value = "scale";
assert(planSnapshot(g, p) !== before, "snapshot changes when an axis is renamed");

// A linked output is never removed, even when the chain no longer reaches it.
const k = g.make("KSampler");
p.connect(p.outputs.findIndex((o) => o.name === "axis_2"), k, 2);
a2.outputs[0].links = [];
delete g.links[sock(p, "dimensions").link];
sock(p, "dimensions").link = null;
a1.connect(0, p, 0);
syncPlanOutputs(g, p);
assert(p.outputs.some((o) => o.name === "axis_2"), "a wired output survives");
assert(!p.outputs.some((o) => o.name === "axis_3"), "unused trailing outputs go");

// An axis with no values is skipped by the backend, so it gets no output.
const skipped = g.make("SweepDimension", { dim_type: "int", values: "" });
skipped.widgets.push({ name: "sweepkit_summary", value: "no values", count: 0 });
skipped.connect(0, p, 0);
a1.outputs[0].links = [];
a1.connect(0, skipped, 0);
eq(axisChain(g, p).axes.map((n) => n.id), [a1.id], "an empty axis is not counted");

// Something the chain can't be read through (Zip) keeps every output.
g = new FakeGraph();
const p2 = g.make("SweepCombinationExpander");
const z = g.make("SweepZip");
z.connect(0, p2, 0);
syncPlanOutputs(g, p2);
assert(p2.outputs.filter((o) => o.name.startsWith("axis_")).length === MAX_AXIS_OUTPUTS, "all outputs kept for an unreadable chain");

// A loop in the links can't hang the walk.
const l1 = g.make("SweepDimension", { dim_type: "seed", values: "1" });
const l2 = g.make("SweepDimension", { dim_type: "seed", values: "2" });
l1.connect(0, l2, 0);
l2.connect(0, l1, 0);
l2.connect(0, p2, 0);
assert(axisChain(g, p2).axes.length === 2, "cycle is cut");
// A fresh Plan with no axes keeps axis_1, so there is always an output to grow from.
g = new FakeGraph();
const fresh = g.make("SweepCombinationExpander");
syncPlanOutputs(g, fresh);
eq(fresh.outputs.map((o) => o.name).slice(3), ["axis_1"], "empty chain keeps axis_1");

// A Plan saved before the axis outputs existed is left untouched on load, and upgraded when an axis is added.
g = new FakeGraph();
const legacy = g.make("SweepCombinationExpander");
legacy.outputs = legacy.outputs.slice(0, 3);
const la = g.make("SweepDimension", { dim_type: "seed", values: "1-3" });
la.connect(0, legacy, 0);
syncPlanOutputs(g, legacy);
eq(legacy.outputs.map((o) => o.name), ["combo", "combo_count", "dim_map"], "old Plan unchanged by sync");
const tgt = g.make("KSampler");
assert(sweepWidget(env(g), tgt, widget(tgt, "cfg")), "sweeping a setting works through an old Plan");
assert(legacy.outputs.some((o) => o.name === "axis_2"), "old Plan got its axis outputs once an axis was added");
console.log("PASS test6: Plan outputs follow the chain and never lose a wired output");

// ---- how many images ----
{
    const { LARGE_SWEEP, RUNS_WIDGET, describeRuns, estimateRuns, refreshRuns } = await import("../web/sweepkit_soft.js");
    const gr = new FakeGraph();
    const rp = gr.make("SweepCombinationExpander");
    const r1 = gr.make("SweepDimension", { dim_type: "seed", values: "1-3" });
    const r2 = gr.make("SweepDimension", { dim_type: "cfg", values: "4,7" });
    for (const [node, count] of [[r1, 3], [r2, 2]]) node.widgets.push({ name: "sweepkit_summary", value: "", count });
    r1.connect(0, r2, 0);
    r2.connect(0, rp, 0);
    eq(estimateRuns(gr, rp), { counts: [3, 2], total: 6 }, "product of the axes' value counts");
    eq(describeRuns(estimateRuns(gr, rp)), { text: "6 images: 3 \u00d7 2", error: false }, "text");
    eq(describeRuns({ counts: [1], total: 1 }), { text: "1 image", error: false }, "singular, no breakdown for one axis");
    const big = describeRuns({ counts: [30, 30], total: 900 });
    assert(big.error && big.text.includes("900") && big.text.includes("a lot") && LARGE_SWEEP === 500, "large sweeps are flagged");
    refreshRuns(gr, rp);
    assert(widget(rp, RUNS_WIDGET) === undefined, "a node without custom widget support is skipped quietly");
    rp.addCustomWidget = (w) => (rp.widgets.push(w), w);
    rp.setDirtyCanvas = () => {};
    refreshRuns(gr, rp);
    eq(widget(rp, RUNS_WIDGET).value, "6 images: 3 \u00d7 2", "line written on the node");
    // Not knowable yet: no count, then no axes at all.
    delete r2.widgets.find((w) => w.name === "sweepkit_summary").count;
    assert(estimateRuns(gr, rp) === null, "unknown count -> no estimate");
    refreshRuns(gr, rp);
    eq(widget(rp, RUNS_WIDGET).value, "", "line cleared when unknown");
    assert(estimateRuns(gr, gr.make("SweepCombinationExpander")) === null, "no axes -> no estimate");
    // The snapshot changes when a count changes, so polling notices.
    const before = planSnapshot(gr, rp);
    r2.widgets.find((w) => w.name === "sweepkit_summary").count = 5;
    assert(planSnapshot(gr, rp) !== before, "snapshot includes the counts");
    console.log("PASS test7: the image count follows the axes feeding a node");
}

// A choice setting leaves its options on the axis for "Pick values from the list"; other settings don't.
{
    const gp = new FakeGraph();
    const k2 = gp.make("KSampler");
    sweepWidget(env(gp), k2, widget(k2, "sampler_name"));
    sweepWidget(env(gp), k2, widget(k2, "steps"));
    const [comboAxis, numberAxis] = gp._nodes.filter((n) => n.comfyClass === "SweepDimension");
    eq(comboAxis.properties.sweepOptions, ["euler", "heun", "dpmpp"], "options kept for a choice setting");
    assert(!numberAxis.properties || !numberAxis.properties.sweepOptions, "no options for a number setting");
    console.log("PASS test8: choice settings keep their options for the picker");
}

// Menu candidates: the setting under the pointer, plus text boxes (a right-click inside one opens the browser's menu).
{
    const gc = new FakeGraph();
    const k3 = gc.make("KSampler");
    k3.widgets.push({ name: "text", type: "customtext", value: "a cat" });
    k3.inputs.push({ name: "text", type: "STRING", widget: { name: "text" } });
    eq(sweepCandidates(k3, widget(k3, "cfg")).map((w) => w.name), ["cfg", "text"], "pointer widget first, then text boxes");
    eq(sweepCandidates(k3, null).map((w) => w.name), ["text"], "no pointer: only text boxes");
    eq(sweepCandidates(k3, widget(k3, "text")).map((w) => w.name), ["text"], "a text box under the pointer is not listed twice");
    sweepWidget(env(gc), k3, widget(k3, "text"));
    eq(sweepCandidates(k3, null).map((w) => w.name), [], "an already swept text box is not offered again");
    eq(sweepCandidates({ comfyClass: "SweepDimension", widgets: [{ name: "values", type: "customtext" }], inputs: [] }, null), [], "SweepKit's own nodes: none");
    console.log("PASS test9: the menu offers the pointer's setting and text boxes");
}

// ---- chains through Pair Axes and Subsets: described by the backend ----
{
    const { chainSpec, chainView, describeRuns, estimateRuns, refreshChain } = await import("../web/sweepkit_soft.js");
    const gz = new FakeGraph();
    const plan = gz.make("SweepCombinationExpander");
    const base = gz.make("SweepDimension", { dim_type: "text", dim_id: "style", values: "a\nb" });
    const c = gz.make("SweepDimension", { dim_type: "cfg", dim_id: "cfg", values: "4, 7" });
    const st = gz.make("SweepDimension", { dim_type: "steps", dim_id: "steps", values: "10, 20" });
    base.connect(0, c, 0);
    base.connect(0, st, 0);
    const zip = gz.make("SweepZip");
    c.connect(0, zip, 0);
    st.connect(0, zip, 1);
    zip.connect(0, plan, 0);

    // The spec lists each node once, even though `style` is reached through both branches.
    const spec = chainSpec(gz, plan);
    eq(Object.keys(spec.nodes).length, 4, "four nodes, the shared axis once");
    eq(spec.nodes[spec.root], { kind: "zip", mode: "shortest", a: String(c.id), b: String(st.id) }, "zip node");
    eq(spec.nodes[String(c.id)].prev, String(base.id), "cfg reads from style");
    eq(spec.nodes[String(base.id)].values, "a\nb", "axis values travel with the spec");
    assert(chainSpec(gz, plan) !== null && chainSpec(gz, gz.make("VAEDecode")) === null, "nothing upstream, no spec");

    // Before the backend has answered, nothing is known (all outputs stay, no count).
    assert(chainView(gz, plan).known === false && estimateRuns(gz, plan) === null, "unknown until answered");

    // Ask once per distinct chain, after a pause; the answer is used.
    const timers = [];
    const calls = [];
    const deps = {
        post: async (path, body) => {
            calls.push([path, body]);
            return { ok: true, axes: [{ label: "style", count: 2 }, { label: "cfg", count: 2 }, { label: "steps", count: 2 }], groups: [2, 2], total: 4 };
        },
        schedule: (fn) => timers.push(fn) - 1,
        cancel: (id) => (timers[id] = null),
    };
    refreshChain(gz, plan, deps);
    refreshChain(gz, plan, deps); // same chain again: no second request
    widget(c, "values").value = "4, 7, 9";
    refreshChain(gz, plan, deps); // an edit: asks again, and the first pending request is cancelled
    for (const fn of timers) if (fn) await fn();
    assert(calls.length === 1 && calls[0][0] === "/sweepkit/preview_chain", `one request for the latest chain, got ${calls.length}`);
    eq(calls[0][1].nodes[String(c.id)].values, "4, 7, 9", "the latest values were sent");

    const view = chainView(gz, plan);
    eq([view.known, view.labels, view.groups, view.total], [true, ["style", "cfg", "steps"], [2, 2], 4], "the backend's answer");
    syncPlanOutputs(gz, plan);
    eq(plan.outputs.map((o) => o.label || o.name).slice(3), ["style", "cfg", "steps"], "outputs are named, one per axis");
    eq(describeRuns(estimateRuns(gz, plan)), { text: "4 images: 2 \u00d7 2", error: false }, "count uses the pair-aware groups");

    // A problem the backend reports is shown instead of a count.
    widget(zip, "mode").value = "strict";
    const failing = { ...deps, post: async () => ({ ok: false, error: "strict mode: 'cfg' has 3 values but 'steps' has 2" }) };
    const timers2 = [];
    refreshChain(gz, plan, { ...failing, schedule: (fn) => timers2.push(fn) - 1 });
    for (const fn of timers2) await fn();
    assert(estimateRuns(gz, plan).error.includes("strict"), "error reported");
    assert(describeRuns(estimateRuns(gz, plan)).error === true, "error flagged");

    // "Values from a connected list" can't be read: no error, just no count.
    const listed = gz.make("SweepDimension", { dim_type: "seed" });
    listed.inputs.find((i) => i.name === "values_pylist").link = 99;
    const gp = new FakeGraph();
    const p2 = gp.make("SweepCombinationExpander");
    const z2 = gp.make("SweepZip");
    const l1 = gp.make("SweepDimension", { dim_type: "seed" });
    l1.inputs.find((i) => i.name === "values_pylist").link = 99;
    l1.connect(0, z2, 0);
    z2.connect(0, p2, 0);
    const timers3 = [];
    refreshChain(gp, p2, { post: async () => ({ ok: false, unknown: true, error: "an axis gets its values from a connected list" }), schedule: (fn) => timers3.push(fn) - 1, cancel() {} });
    for (const fn of timers3) await fn();
    assert(chainView(gp, p2).error === null && estimateRuns(gp, p2) === null, "unknown is quiet");

    // A plain chain never calls the backend.
    const gq = new FakeGraph();
    const p3 = gq.make("SweepCombinationExpander");
    const a1 = gq.make("SweepDimension", { dim_type: "seed", values: "1-3" });
    a1.connect(0, p3, 0);
    let asked = 0;
    refreshChain(gq, p3, { post: async () => (asked++, {}), schedule: (fn) => fn(), cancel() {} });
    assert(asked === 0 && p3.__chainInfo === null, "plain chains are read locally");

    // The polling snapshot changes when the zip setting or the answer changes.
    const before = planSnapshot(gz, plan);
    widget(zip, "mode").value = "longest";
    assert(planSnapshot(gz, plan) !== before, "snapshot sees a Pair Axes edit");
    console.log("PASS test10: chains through Pair Axes and Subsets are described by the backend");
}

// ---- grid axis pickers list the axes by name ----
{
    const gp = new FakeGraph();
    const plan = gp.make("SweepCombinationExpander");
    const a1 = gp.make("SweepDimension", { dim_type: "seed", dim_id: "seed", values: "1,2" });
    const a2 = gp.make("SweepDimension", { dim_type: "text", dim_id: "style", values: "a, b\nc" });
    a1.connect(0, a2, 0);
    a2.connect(0, plan, 0);
    const collect = gp.make("SweepCollect");
    const pick = (name) => collect.widgets.find((w) => w.name === name);
    pick("grid_x_dim").value = "dim2"; // as an older workflow saved it
    pick("grid_title_dim").value = "gone"; // a name no axis has any more

    const before = pickerSnapshot(gp, collect);
    syncAxisPickers(gp, collect);
    eq(pick("grid_y_dim").options.values, ["auto", "none", "dim1", "dim2", "dim3"], "no Plan connected: untouched");
    plan.connect(0, collect, 1);
    assert(pickerSnapshot(gp, collect) !== before, "snapshot sees the Plan being connected");
    syncAxisPickers(gp, collect);
    eq(pick("grid_y_dim").options.values, ["auto", "none", "seed", "style"], "names of the connected axes");
    eq(pick("grid_x_dim").value, "style", "dimN becomes the axis name");
    eq(pick("grid_title_dim").options.values, ["auto", "none", "seed", "style", "gone"], "a stale name stays selectable");

    eq(axisPickerNames(["seed", "seed", "cfg", "auto"]), ["dim1", "dim2", "cfg", "dim4"], "shared or reserved names use positions");
    widget(a2, "dim_id").value = "prompt";
    syncAxisPickers(gp, collect);
    eq(pick("grid_y_dim").options.values, ["auto", "none", "seed", "prompt"], "follows a renamed axis");
    console.log("PASS test11: grid axis pickers list the connected axes by name");
}
