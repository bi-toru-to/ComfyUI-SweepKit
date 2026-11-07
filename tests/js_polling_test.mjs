// Change detection, exercised through the real startPolling() from
// web/sweepkit_core.js: once with an injected scheduler (deterministic
// ticks), once with the real ~10 Hz timer.
import { POLL_INTERVAL_MS, getWidget, startPolling } from "../web/sweepkit_core.js";

function assert(cond, msg) {
    if (!cond) throw new Error("FAIL: " + msg);
}

// --- deterministic: drive ticks by hand ---
let queue = [];
const schedule = (fn) => queue.push(fn);
const tickOnce = () => {
    const q = queue;
    queue = [];
    q.forEach((fn) => fn());
};

const node = { widgets: [{ name: "dim_type", value: "text" }, { name: "values", value: "a\nb" }] };
let calls = 0;
startPolling(node, { sync: () => (calls += 1), schedule });
startPolling(node, { sync: () => (calls += 100), schedule }); // second call is a no-op

tickOnce();
assert(calls === 1, "first tick should sync once, got " + calls);
tickOnce();
assert(calls === 1, "no change -> no extra sync, got " + calls);

// switch to "model" without any widget callback firing
getWidget(node, "dim_type").value = "model";
getWidget(node, "values").value = "Base\nTurbo";
tickOnce();
assert(calls === 2, "a change must be caught on the next tick even with no callback, got " + calls);

node.__sweepRemoved = true;
getWidget(node, "values").value = "Base\nTurbo\nLightning";
tickOnce();
assert(calls === 2, "no sync after node removal, got " + calls);
assert(queue.length === 0, "a removed node must not schedule another tick");
console.log("PASS test1: polling catches changes without callbacks, ignores repeats, stops on removal");

// --- real timer: default interval is ~10 Hz, not every frame ---
assert(POLL_INTERVAL_MS === 100, "poll interval should be 100 ms, got " + POLL_INTERVAL_MS);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function waitFor(cond, timeoutMs = 2000) {
    const t0 = Date.now();
    while (!cond()) {
        if (Date.now() - t0 > timeoutMs) return false;
        await sleep(5);
    }
    return true;
}

const live = { widgets: [{ name: "dim_type", value: "text" }, { name: "values", value: "" }] };
let liveCalls = 0;
const started = Date.now();
startPolling(live, { sync: () => (liveCalls += 1) });
assert(await waitFor(() => liveCalls === 1), "first sync never happened");
const firstAfter = Date.now() - started;
assert(firstAfter >= POLL_INTERVAL_MS - 10, `first sync waits one interval (~${POLL_INTERVAL_MS} ms), took ${firstAfter} ms`);
live.widgets[1].value = "x";
assert(await waitFor(() => liveCalls === 2), "a change must be picked up by the timer");
live.__sweepRemoved = true;
live.widgets[1].value = "y";
await sleep(3 * POLL_INTERVAL_MS);
assert(liveCalls === 2, "stopped after removal, got " + liveCalls);
console.log(`PASS test2: real timer polls every ${POLL_INTERVAL_MS} ms (first sync at ${firstAfter} ms) and stops on removal`);
