// Live grid for Plan-driven sweeps: when the browser queues one run per image,
// exercised through the real functions from web/sweepkit_live.js.
import { findLivePlan, liveOutput, newSession, queueLive } from "../web/sweepkit_live.js";

function assert(cond, msg) {
    if (!cond) throw new Error("FAIL: " + msg);
}
const eq = (a, b, msg) => assert(JSON.stringify(a) === JSON.stringify(b), `${msg}: got ${JSON.stringify(a)}, wanted ${JSON.stringify(b)}`);

// An API-format prompt: Plan -> KSampler (axis outputs) and Plan.combo -> Collect.
const prompt = (planInputs = {}, extra = {}) => ({
    "1": { class_type: "SweepDimension", inputs: { dim_type: "seed", values: "1-4" } },
    "2": { class_type: "SweepCombinationExpander", inputs: { dimensions: ["1", 0], live_grid: true, ...planInputs } },
    "3": { class_type: "KSampler", inputs: { seed: ["2", 3], cfg: 7 } },
    "4": { class_type: "SweepCollect", inputs: { images: ["3", 0], combo: ["2", 0] } },
    ...extra,
});

// ---- when a run is live ----
eq(findLivePlan(prompt()), "2", "the usual layout is live");
eq(findLivePlan(prompt({ live_grid: false })), null, "live_grid off: one go");
eq(findLivePlan({ "1": { class_type: "KSampler", inputs: {} } }), null, "no Plan: nothing to do");
eq(findLivePlan(null), null, "no prompt");

// The Plan's combo must reach a Collect and nothing else.
eq(findLivePlan(prompt({}, { "5": { class_type: "SweepGridConstructor", inputs: { combo: ["2", 0] } } })), null, "another node reads combo");
eq(findLivePlan(prompt({}, { "5": { class_type: "SweepDimensionExtract", inputs: { combo: ["2", 0] } } })), null, "Extract reads combo");
eq(findLivePlan(prompt({}, { "5": { class_type: "ShowText", inputs: { text: ["2", 2] } } })), "2", "dim_map or count readers don't matter");
const noCollect = prompt();
delete noCollect["4"];
eq(findLivePlan(noCollect), null, "no Collect: nothing to show the grid on");
const twoPlans = prompt({}, { "6": { class_type: "SweepCombinationExpander", inputs: { dimensions: ["1", 0], live_grid: true } } });
eq(findLivePlan(twoPlans), null, "two live Plans: one go");
console.log("PASS test1: a run is live only for a Plan feeding just Sweep Collect");

// ---- the per-image prompt ----
const base = prompt();
const snapshot = JSON.stringify(base);
const run3 = liveOutput(base, "2", 3, "swX");
eq([run3["2"].inputs.sweep_cursor, run3["2"].inputs.sweep_session], [3, "swX"], "cursor and session set on the Plan");
eq(run3["3"], base["3"], "everything else is untouched");
assert(JSON.stringify(base) === snapshot, "the original prompt is not changed");
assert(newSession(1700000000000, () => 0.5) !== newSession(1700000000001, () => 0.5) && /^sw[0-9a-z]+$/.test(newSession()), "sessions differ");
console.log("PASS test2: each image gets its own copy of the prompt");

// ---- queueing ----
async function run(number, data, totalFor) {
    const calls = [];
    const queue = async (n, d, o) => (calls.push({ n, d, o }), { prompt_id: `p${calls.length}` });
    const result = await queueLive({ queue, number, data, options: { x: 1 }, totalFor, session: "swT" });
    return { calls, result };
}
const data = { output: prompt(), workflow: { nodes: [] } };

let r = await run(0, data, async () => 4);
eq(r.calls.map((c) => c.d.output["2"].inputs.sweep_cursor), [0, 1, 2, 3], "one queue entry per image, in order");
assert(r.calls.every((c) => c.n === 0 && c.o.x === 1 && c.d.output["2"].inputs.sweep_session === "swT" && c.d.workflow === data.workflow), "number, options, workflow pass through; one session");
eq(r.result, { prompt_id: "p4" }, "returns the last queue result");

r = await run(-1, data, async () => 3);
eq(r.calls.map((c) => c.d.output["2"].inputs.sweep_cursor), [2, 1, 0], "queue-at-front goes backwards so the order holds");

// Not live: one request, unchanged.
for (const [name, totalFor] of [["unknown total", async () => null], ["one image", async () => 1], ["lookup fails", async () => { throw new Error("offline"); }]]) {
    r = await run(0, data, totalFor);
    assert(r.calls.length === 1 && r.calls[0].d === data, `${name}: runs in one go`);
}
const plain = { output: { "1": { class_type: "KSampler", inputs: {} } } };
r = await run(0, plain, async () => 4);
assert(r.calls.length === 1 && r.calls[0].d === plain, "a workflow without a live Plan is passed straight through");
console.log("PASS test3: one queue entry per image, order kept, falls back to one go");
