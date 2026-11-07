/**
 * "Sweep this setting" support: pick any number, choice or text setting on any
 * node and SweepKit adds an axis for it, already wired in.
 *
 * It works through nodes the pack already has, so the sweep stays visible in
 * the graph and runs without the browser:
 *
 *   Sweep Axis (one per setting) -> Sweep Plan -> axis_N list output
 *        -> the setting's own input socket    (ComfyUI then runs that node
 *                                              once per combination)
 *   final image + Plan's combo -> Sweep Collect (names files, builds grids)
 *
 * This module has no dependency on the ComfyUI app object, so
 * tests/js_soft_test.mjs can import and exercise this exact code. The app
 * object, graph and node factory are passed in by web/sweepkit.js.
 */

import { getWidget } from "./sweepkit_core.js";

// Must match MAX_AXIS_OUTPUTS in sweep_core.py.
export const MAX_AXIS_OUTPUTS = 8;
export const PLAN_CLASS = "SweepCombinationExpander";
export const AXIS_CLASS = "SweepDimension";
export const COLLECT_CLASS = "SweepCollect";

const OUTPUT_PREFIX = "axis_";
// Placeholder text of the values widget left by a "model" axis etc. is never produced here.
const SUGGESTED_VALUES = 3;

const classOf = (node) => (node ? node.comfyClass || node.type : null);

// ---- finding things in the graph ----

function linkOf(graph, linkId) {
    if (linkId == null || !graph || !graph.links) return null;
    // graph.links is a plain object in some frontends and a Map in others.
    return typeof graph.links.get === "function" ? graph.links.get(linkId) || null : graph.links[linkId] || null;
}

/** The node feeding input `name` of `node`, or null. */
export function upstreamOf(graph, node, name) {
    const input = (node.inputs || []).find((i) => i.name === name);
    const link = input ? linkOf(graph, input.link) : null;
    return link ? graph.getNodeById(link.origin_id) : null;
}

export function allNodes(graph) {
    return (graph && (graph._nodes || graph.nodes)) || [];
}

export function findNodesOfClass(graph, cls) {
    return allNodes(graph).filter((n) => classOf(n) === cls);
}

/** An axis the backend will actually use: SweepDimension skips an axis with no values
 * (and a lora_strength axis with no LoRA), so the Plan has no output for it. */
export function isActiveAxis(node) {
    const summary = getWidget(node, "sweepkit_summary");
    if (summary && summary.count === 0) return false;
    const type = getWidget(node, "dim_type");
    const lora = getWidget(node, "lora_name");
    return !(type && type.value === "lora_strength" && lora && !lora.value);
}

/** The axes feeding a Plan, first to last, by following `dimensions` and each
 * axis's `prev_dimensions`. `complete` is false when the chain passes through
 * something else (Zip, Self-Combine...), whose axes this can't list. */
export function axisChain(graph, plan) {
    const axes = [];
    let complete = true;
    let node = upstreamOf(graph, plan, "dimensions");
    const seen = new Set();
    while (node && !seen.has(node.id)) {
        seen.add(node.id);
        if (classOf(node) !== AXIS_CLASS) {
            complete = false;
            break;
        }
        if (isActiveAxis(node)) axes.unshift(node);
        node = upstreamOf(graph, node, "prev_dimensions");
    }
    return { axes, complete };
}

export function axisLabel(axisNode, position) {
    const id = getWidget(axisNode, "dim_id");
    const type = getWidget(axisNode, "dim_type");
    return (id && id.value) || (type && type.value) || `axis ${position}`;
}

// ---- Plan outputs ----

function axisOutputNumber(output) {
    return output.name.startsWith(OUTPUT_PREFIX) ? parseInt(output.name.slice(OUTPUT_PREFIX.length), 10) : NaN;
}

/** Show one axis_N output per axis in the chain, labelled with the axis name.
 * Trailing outputs nobody uses are removed (axis_1 always stays); one with a
 * link is always kept. When the chain can't be read (Zip and friends), all
 * outputs stay. A Plan saved before these outputs existed is left alone
 * (opening an old workflow must not change it) unless `upgrade` is set, as
 * it is when the user adds an axis to it. */
export function syncPlanOutputs(graph, plan, { upgrade = false } = {}) {
    if (!upgrade && !(plan.outputs || []).some((o) => o.name.startsWith(OUTPUT_PREFIX))) return;
    const { axes, complete } = axisChain(graph, plan);
    const wanted = complete ? Math.max(1, axes.length) : MAX_AXIS_OUTPUTS;
    const outputs = plan.outputs || [];
    for (let i = outputs.length - 1; i >= 0; i--) {
        const n = axisOutputNumber(outputs[i]);
        const linked = outputs[i].links && outputs[i].links.length > 0;
        if (!Number.isNaN(n) && n > wanted && !linked) plan.removeOutput(i);
    }
    const template = outputs.find((o) => o.name.startsWith(OUTPUT_PREFIX));
    for (let n = 1; n <= wanted; n++) {
        if (!plan.outputs.some((o) => o.name === `${OUTPUT_PREFIX}${n}`)) {
            plan.addOutput(`${OUTPUT_PREFIX}${n}`, "*", template ? { shape: template.shape } : undefined);
        }
    }
    for (const out of plan.outputs) {
        const n = axisOutputNumber(out);
        if (!Number.isNaN(n)) out.label = complete && n <= axes.length ? axisLabel(axes[n - 1], n) : out.name;
    }
}

/** What a Plan's polling compares between ticks. */
export function planSnapshot(graph, plan) {
    const { axes, complete } = axisChain(graph, plan);
    return [complete, ...axes.map((a, i) => `${a.id}:${axisLabel(a, i + 1)}`)].join("\u0001");
}

// ---- describing a setting, and suggesting values for it ----

/** What the Axis node needs to know about a setting (a widget), or null when
 * the setting can't be swept (buttons, switches, hidden or SweepKit's own). */
export function widgetInfo(widget) {
    if (!widget || widget.hidden || widget.disabled || !widget.name) return null;
    const opts = widget.options || {};
    const name = String(widget.name);
    if (widget.type === "number" || widget.type === "slider") {
        const precision = typeof opts.precision === "number" ? opts.precision : Number.isInteger(widget.value) ? 0 : 2;
        const dimType = ["seed", "noise_seed"].includes(name)
            ? "seed"
            : name === "steps"
              ? "steps"
              : name === "cfg"
                ? "cfg"
                : precision === 0
                  ? "int"
                  : "float";
        return { name, kind: "number", dimType, value: widget.value, precision, min: opts.min, max: opts.max };
    }
    if (widget.type === "combo") {
        const raw = opts.values;
        const options = (typeof raw === "function" ? raw() : raw) || [];
        return { name, kind: "combo", dimType: "text", value: widget.value, options: options.map(String) };
    }
    if (["text", "customtext", "string"].includes(widget.type)) {
        return { name, kind: "text", dimType: "text", value: String(widget.value ?? "") };
    }
    return null;
}

const roundTo = (x, precision) => Number(x.toFixed(precision));

/** A starting `values` text for the new axis: the setting's current value plus a
 * couple of neighbours, so there is something to sweep straight away. */
export function suggestValues(info) {
    if (info.kind === "text") return info.value;
    if (info.kind === "combo") {
        const opts = info.options;
        const start = Math.max(0, opts.indexOf(String(info.value)));
        const picked = [];
        for (let i = 0; i < Math.min(SUGGESTED_VALUES, opts.length); i++) picked.push(opts[(start + i) % opts.length]);
        return (picked.length ? picked : [String(info.value)]).join("\n");
    }
    const v = Number(info.value);
    if (info.dimType === "seed") return `${v}-${v + SUGGESTED_VALUES - 1}`;
    const unit = Math.pow(10, -info.precision);
    const step = Math.max(unit, roundTo(Math.abs(v) / 4, info.precision));
    const out = [];
    for (let i = 0; i < SUGGESTED_VALUES; i++) {
        let x = roundTo(v + i * step, info.precision);
        if (typeof info.max === "number") x = Math.min(x, info.max);
        if (typeof info.min === "number") x = Math.max(x, info.min);
        if (!out.includes(x)) out.push(x);
    }
    return out.join(", ");
}

/** Can this widget get an axis? Not one of SweepKit's own, not one already wired. */
export function sweepableWidget(node, widget) {
    if (!node || !widget || String(classOf(node)).startsWith("Sweep")) return null;
    const info = widgetInfo(widget);
    const socket = (node.inputs || []).find((i) => i.widget && i.widget.name === widget.name);
    if (!info || !socket || socket.link != null) return null;
    return info;
}

// ---- building the nodes ----

function slotIndex(list, name) {
    return (list || []).findIndex((s) => s.name === name);
}

/** Make a node and place it; `place` = [x, y]. */
function addNode(env, cls, place) {
    const node = env.createNode(cls);
    node.pos = [place[0], place[1]];
    env.graph.add(node);
    return node;
}

// Where new nodes go: in a row just above everything else in the graph, so
// they never land on top of the user's own nodes.
const AXIS_SPACING = 420;
const ROW_GAP = 340;

function topOfGraph(graph, exclude) {
    const ys = allNodes(graph)
        .filter((n) => !exclude.includes(n) && !String(classOf(n)).startsWith("Sweep"))
        .map((n) => n.pos[1]);
    return ys.length ? Math.min(...ys) : 0;
}

function ensurePlan(env, near) {
    const found = findNodesOfClass(env.graph, PLAN_CLASS)[0];
    return found || addNode(env, PLAN_CLASS, [near.pos[0], topOfGraph(env.graph, [near]) - ROW_GAP]);
}

/** Add an axis for `widget` of `target` and wire it all the way in. Returns a
 * short message for the user, or null when it could not be done. `env` =
 * {graph, createNode(cls)}. */
export function sweepWidget(env, target, widget) {
    const info = sweepableWidget(target, widget);
    if (!info) return null;
    const { graph } = env;
    graph.beforeChange && graph.beforeChange();
    try {
        const plan = ensurePlan(env, target);
        const before = axisChain(graph, plan);
        const last = before.axes[before.axes.length - 1];
        // Each new axis goes left of the previous one (the first one left of the Plan).
        const axis = addNode(env, AXIS_CLASS, [(last || plan).pos[0] - AXIS_SPACING, plan.pos[1]]);
        getWidget(axis, "dim_type").value = info.dimType;
        getWidget(axis, "dim_id").value = info.name;
        getWidget(axis, "values").value = suggestValues(info);

        // Chain: previous last axis -> this axis -> Plan (replacing the old link).
        if (last) last.connect(0, axis, slotIndex(axis.inputs, "prev_dimensions"));
        axis.connect(0, plan, slotIndex(plan.inputs, "dimensions"));

        syncPlanOutputs(graph, plan, { upgrade: true });
        const position = axisChain(graph, plan).axes.indexOf(axis) + 1;
        const out = slotIndex(plan.outputs, `${OUTPUT_PREFIX}${position}`);
        const socket = (target.inputs || []).findIndex((i) => i.widget && i.widget.name === widget.name);
        if (position < 1 || out < 0 || !plan.connect(out, target, socket)) {
            return `Could not connect the new axis to "${info.name}".`;
        }
        graph.setDirtyCanvas && graph.setDirtyCanvas(true, true);
        return `Sweeping "${info.name}": edit the values on the new Sweep Axis node.`;
    } finally {
        graph.afterChange && graph.afterChange();
    }
}

/** Can this node hand its image to Sweep Collect? */
export function hasImageOutput(node) {
    return !String(classOf(node)).startsWith("Sweep") && (node.outputs || []).some((o) => o.type === "IMAGE");
}

/** Add Sweep Collect next to `source` (a node with an IMAGE output), wired to
 * its image and to the Plan's combo output. Returns a message, or null. */
export function collectHere(env, source) {
    if (!hasImageOutput(source)) return null;
    const { graph } = env;
    graph.beforeChange && graph.beforeChange();
    try {
        const plan = ensurePlan(env, source);
        const collect =
            findNodesOfClass(graph, COLLECT_CLASS)[0] ||
            addNode(env, COLLECT_CLASS, [source.pos[0] + ((source.size && source.size[0]) || 300) + 60, source.pos[1]]);
        const image = slotIndex(source.outputs, "IMAGE") >= 0 ? slotIndex(source.outputs, "IMAGE") : source.outputs.findIndex((o) => o.type === "IMAGE");
        source.connect(image, collect, slotIndex(collect.inputs, "images"));
        plan.connect(slotIndex(plan.outputs, "combo"), collect, slotIndex(collect.inputs, "combo"));
        graph.setDirtyCanvas && graph.setDirtyCanvas(true, true);
        return "Sweep Collect added. Right-click a setting (seed, cfg, prompt...) and choose Sweep to add an axis for it.";
    } finally {
        graph.afterChange && graph.afterChange();
    }
}
