/**
 * Live grid for Plan-driven sweeps.
 *
 * ComfyUI runs each node over every list item before the next node starts, so a
 * sweep run in one go can't show its grid until the end. To show images as they
 * finish, the browser can instead queue the workflow once per image, telling
 * Sweep Plan which combination to hand out (its hidden `sweep_cursor` input) and
 * telling Sweep Collect which sweep this is (its hidden `sweep_session`). Collect
 * keeps the images between runs, shows the grid so far, and writes the final files
 * after the last. The session id goes to Collect, not the Plan, so that a rerun
 * with the same axes gives the Plan (and everything after it) the same inputs:
 * ComfyUI's cache can then reuse what the Plan and the axis chain produced.
 *
 * Changing only Sweep Collect's own settings (grid axes, cell size...) shouldn't
 * sample every image again, but ComfyUI's cache can't help there: each image was
 * its own run, and by default it frees results of runs other than the latest. So
 * the browser remembers the last live sweep, and when the next queued prompt
 * differs from it only in Collect's settings (and the server still holds that
 * sweep's images), it queues one small run that has Collect rebuild from them.
 *
 * It only happens for a run started in the browser, with the Plan's `live_grid`
 * switch on, a Sweep Collect fed by the Plan, and nothing else reading the Plan's
 * `combo`. Anything else (including the API) runs everything in one go, as before.
 *
 * No dependency on the ComfyUI app object, so tests/js_live_test.mjs can import
 * this exact code. web/sweepkit.js wraps api.queuePrompt with queueLive().
 */

export const PLAN_CLASS = "SweepCombinationExpander";
export const COLLECT_CLASS = "SweepCollect";

const isLink = (v) => Array.isArray(v) && v.length === 2;

/** The id of the one Plan in a queued prompt (API format) that should run live, or null. */
export function findLivePlan(output) {
    const plans = Object.entries(output || {}).filter(
        ([, node]) => node && node.class_type === PLAN_CLASS && node.inputs && node.inputs.live_grid === true,
    );
    if (plans.length !== 1) return null; // none, or several: keep it simple and run in one go
    const [planId] = plans[0];
    const readers = [];
    for (const [id, node] of Object.entries(output)) {
        for (const value of Object.values((node && node.inputs) || {})) {
            if (isLink(value) && String(value[0]) === planId && value[1] === 0) readers.push(node);
        }
    }
    // The Plan's combo must go to a Sweep Collect and nowhere else: other nodes
    // expect every combination at once.
    const ok = readers.length > 0 && readers.every((node) => node.class_type === COLLECT_CLASS);
    return ok ? planId : null;
}

/** The prompt for image number `cursor` of a live sweep: the same prompt, with the
 * Plan told which combination to hand out and each Sweep Collect reading it told
 * which sweep this is. Does not change `output`. */
export function liveOutput(output, planId, cursor, session) {
    const copy = JSON.parse(JSON.stringify(output));
    copy[planId].inputs.sweep_cursor = cursor;
    for (const node of Object.values(copy)) {
        const combo = node && node.class_type === COLLECT_CLASS && node.inputs && node.inputs.combo;
        if (isLink(combo) && String(combo[0]) === planId) node.inputs.sweep_session = session;
    }
    return copy;
}

const collectsOf = (output, planId) =>
    Object.entries(output).filter(([, node]) => {
        const combo = node && node.class_type === COLLECT_CLASS && node.inputs && node.inputs.combo;
        return isLink(combo) && String(combo[0]) === planId;
    });

/** What a live sweep is, apart from Sweep Collect's own settings: two prompts with
 * the same key make the same images. */
export function sweepKey(output, planId) {
    const copy = JSON.parse(JSON.stringify(output));
    for (const [id, node] of collectsOf(copy, planId)) {
        copy[id] = { class_type: node.class_type, inputs: { images: node.inputs.images, combo: node.inputs.combo } };
    }
    return JSON.stringify(copy);
}

/** A run that has each Sweep Collect rebuild from the kept images of sweep `session`.
 * Everything that depends on the Plan other than through a Collect (the sampler
 * and so on) is left out, so nothing is sampled. What comes after a Collect (a
 * Preview Image on its grids) stays and gets the new grids, and the rest stays
 * unchanged, so ComfyUI keeps it cached (loaded models, for one) without running
 * it. Collect's `images` input is required, so it gets a tiny stand-in image,
 * which it ignores. */
export function reuseOutput(output, planId, session) {
    const collects = new Set(collectsOf(output, planId).map(([id]) => id));
    const dependsOnPlan = new Set([planId]);
    for (let grew = true; grew; ) {
        grew = false;
        for (const [id, node] of Object.entries(output)) {
            if (dependsOnPlan.has(id) || collects.has(id)) continue;
            const inputs = Object.values((node && node.inputs) || {});
            if (inputs.some((v) => isLink(v) && dependsOnPlan.has(String(v[0])))) {
                dependsOnPlan.add(id);
                grew = true;
            }
        }
    }
    const out = {};
    for (const [id, node] of Object.entries(output)) {
        if (id === planId || !dependsOnPlan.has(id)) out[id] = JSON.parse(JSON.stringify(node));
    }
    const stub = "sweepkit_stand_in";
    out[stub] = { class_type: "EmptyImage", inputs: { width: 8, height: 8, batch_size: 1, color: 0 } };
    for (const [id, node] of collectsOf(output, planId)) {
        const copy = JSON.parse(JSON.stringify(node));
        Object.assign(copy.inputs, { images: [stub, 0], sweep_reuse: session });
        out[id] = copy;
    }
    return out;
}

/** Running Sweep Collect on its own (its Run button) also runs the output nodes
 * after it, such as a Preview Image on its grids: ComfyUI only runs the chosen
 * nodes and what feeds them, so they would keep showing the old grids. Returns
 * the new target list, or `targets` unchanged when no Collect is among them. */
export function withCollectOutputs(output, targets, isOutputNode) {
    if (!Array.isArray(targets) || !targets.length || !output) return targets;
    const start = targets.map(String).filter((id) => output[id] && output[id].class_type === COLLECT_CLASS);
    if (!start.length) return targets;
    const after = new Set(start);
    for (let grew = true; grew; ) {
        grew = false;
        for (const [id, node] of Object.entries(output)) {
            if (after.has(id)) continue;
            const inputs = Object.values((node && node.inputs) || {});
            if (inputs.some((v) => isLink(v) && after.has(String(v[0])))) {
                after.add(id);
                grew = true;
            }
        }
    }
    const extra = [...after].filter((id) => !start.includes(id) && isOutputNode(output[id].class_type));
    const result = [...targets];
    for (const id of extra) if (!result.map(String).includes(id)) result.push(id);
    return result;
}

/** The last live sweep queued from this page: its key and session. */
export const liveMemory = { last: null };

/** A session id that is different for every sweep. */
export function newSession(now = Date.now(), random = Math.random) {
    return `sw${now.toString(36)}${Math.floor(random() * 1e6).toString(36)}`;
}

/**
 * Queue a prompt, image by image when it should run live. `queue(number, data,
 * options)` is the real api.queuePrompt; `totalFor(planId)` resolves to how many
 * images the Plan makes (or null when unknown, which runs in one go);
 * `isKept(session, collectIds)` resolves to whether the server still holds that
 * sweep's images. Returns what the last queue call returned.
 */
export async function queueLive({
    queue,
    number,
    data,
    options,
    totalFor,
    isKept = async () => false,
    isOutputNode = () => false,
    memory = liveMemory,
    session = newSession(),
}) {
    if (options && options.partialExecutionTargets) {
        const targets = withCollectOutputs(data && data.output, options.partialExecutionTargets, isOutputNode);
        if (targets !== options.partialExecutionTargets) options = { ...options, partialExecutionTargets: targets };
    }
    const planId = findLivePlan(data && data.output);
    if (planId !== null) {
        const key = sweepKey(data.output, planId);
        const last = memory.last;
        if (last && last.key === key) {
            let kept = false;
            try {
                kept = await isKept(last.session, collectsOf(data.output, planId).map(([id]) => id));
            } catch (_err) {
                kept = false;
            }
            const output = kept ? reuseOutput(data.output, planId, last.session) : null;
            // A run of chosen nodes only (a node's own Run button) must find them all in the rebuild.
            const targets = (options && options.partialExecutionTargets) || [];
            if (output && targets.every((id) => String(id) in output)) {
                return queue(number, { ...data, output }, options);
            }
        }
    }
    let total = null;
    if (planId !== null) {
        try {
            total = await totalFor(planId);
        } catch (_err) {
            total = null;
        }
    }
    if (planId === null || !Number.isInteger(total) || total < 2) {
        memory.last = null;
        return queue(number, data, options);
    }
    memory.last = { key: sweepKey(data.output, planId), session };
    // "Queue at the front" (-1) puts each one before the others, so go backwards to keep the order.
    const order = Array.from({ length: total }, (_, i) => i);
    if (number === -1) order.reverse();
    let last;
    for (const cursor of order) {
        last = await queue(number, { ...data, output: liveOutput(data.output, planId, cursor, session) }, options);
    }
    return last;
}
