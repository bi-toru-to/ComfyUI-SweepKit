/**
 * Live grid for Plan-driven sweeps.
 *
 * ComfyUI runs each node over every list item before the next node starts, so a
 * sweep run in one go can't show its grid until the end. To show images as they
 * finish, the browser can instead queue the workflow once per image, telling
 * Sweep Plan which combination to hand out (its hidden `sweep_cursor` input) and
 * which sweep this is (`sweep_session`). Sweep Collect then keeps the images
 * between runs, shows the grid so far, and writes the final files after the last.
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
 * Plan told which combination to hand out. Does not change `output`. */
export function liveOutput(output, planId, cursor, session) {
    const copy = JSON.parse(JSON.stringify(output));
    Object.assign(copy[planId].inputs, { sweep_cursor: cursor, sweep_session: session });
    return copy;
}

/** A session id that is different for every sweep. */
export function newSession(now = Date.now(), random = Math.random) {
    return `sw${now.toString(36)}${Math.floor(random() * 1e6).toString(36)}`;
}

/**
 * Queue a prompt, image by image when it should run live. `queue(number, data,
 * options)` is the real api.queuePrompt; `totalFor(planId)` resolves to how many
 * images the Plan makes (or null when unknown, which runs in one go). Returns
 * what the last queue call returned.
 */
export async function queueLive({ queue, number, data, options, totalFor, session = newSession() }) {
    const planId = findLivePlan(data && data.output);
    let total = null;
    if (planId !== null) {
        try {
            total = await totalFor(planId);
        } catch (_err) {
            total = null;
        }
    }
    if (planId === null || !Number.isInteger(total) || total < 2) return queue(number, data, options);
    // "Queue at the front" (-1) puts each one before the others, so go backwards to keep the order.
    const order = Array.from({ length: total }, (_, i) => i);
    if (number === -1) order.reverse();
    let last;
    for (const cursor of order) {
        last = await queue(number, { ...data, output: liveOutput(data.output, planId, cursor, session) }, options);
    }
    return last;
}
