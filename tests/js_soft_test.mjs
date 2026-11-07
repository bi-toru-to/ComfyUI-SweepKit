// "Sweep this setting": value suggestions, wiring and Plan outputs, exercised
// through the real functions from web/sweepkit_soft.js on a fake graph.
import {
    MAX_AXIS_OUTPUTS,
    axisChain,
    collectHere,
    hasImageOutput,
    planSnapshot,
    suggestValues,
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
