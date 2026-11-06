function getWidget(node, name) { return node.widgets ? node.widgets.find((w) => w.name === name) : null; }
function snapshot(node) {
    const typeW = getWidget(node, "dim_type");
    const valuesW = getWidget(node, "values");
    return (typeW ? typeW.value : "") + "\u0001" + (valuesW ? valuesW.value : "");
}
function startPolling(node, sweepSyncFn) {
    if (node.__sweepPolling) return;
    node.__sweepPolling = true;
    node.__sweepLastSnapshot = null;
    const tick = () => {
        if (node.__sweepRemoved) return;
        const snap = snapshot(node);
        if (snap !== node.__sweepLastSnapshot) {
            node.__sweepLastSnapshot = snap;
            sweepSyncFn(node);
        }
        requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
}

let rafQueue = [];
globalThis.requestAnimationFrame = (fn) => { rafQueue.push(fn); return rafQueue.length; };
function pumpOneFrame() { const q = rafQueue; rafQueue = []; for (const fn of q) fn(); }

function assert(cond, msg) { if (!cond) throw new Error("FAIL: " + msg); }

const node = { widgets: [{ name: "dim_type", value: "text" }, { name: "values", value: "a\nb" }] };
let calls = 0;
startPolling(node, () => { calls += 1; });

pumpOneFrame();
assert(calls === 1, "first frame should sync once, got " + calls);
pumpOneFrame();
assert(calls === 1, "no change -> no extra sync, got " + calls);

// simulate switching to "model" type without any callback firing
getWidget(node, "dim_type").value = "model";
getWidget(node, "values").value = "Base,Turbo";
pumpOneFrame();
assert(calls === 2, "type+values change should be caught within one frame even with no callback, got " + calls);

node.__sweepRemoved = true;
getWidget(node, "values").value = "Base,Turbo,Lightning";
pumpOneFrame();
assert(calls === 2, "no sync after node removal, got " + calls);
assert(rafQueue.length === 0, "removed node must not reschedule another frame");

console.log("PASS: single-node polling catches changes without relying on any callback, and stops on removal");
