// "Pick values from the list": the pure helpers behind the dialog, exercised
// through the real functions from web/sweepkit_pick.js.
import { MAX_STORED_OPTIONS, currentSelection, filterOptions, optionsToStore, pickedValuesText, storedOptions } from "../web/sweepkit_pick.js";

function assert(cond, msg) {
    if (!cond) throw new Error("FAIL: " + msg);
}
const eq = (a, b, msg) => assert(JSON.stringify(a) === JSON.stringify(b), `${msg}: got ${JSON.stringify(a)}, wanted ${JSON.stringify(b)}`);

const samplers = ["euler", "euler_ancestral", "heun", "dpmpp_2m", "dpmpp_sde", "ddim"];

// What is already listed in the axis stays ticked; unknown lines are ignored.
eq([...currentSelection("heun\n  ddim \nnot_a_sampler\n\n", samplers)], ["heun", "ddim"], "current selection");
eq([...currentSelection("", samplers)], [], "empty text");
console.log("PASS test1: existing values are pre-ticked");

// Filtering: every word must match, any case; empty shows everything.
eq(filterOptions(samplers, "DPMPP"), ["dpmpp_2m", "dpmpp_sde"], "case-insensitive substring");
eq(filterOptions(samplers, "euler anc"), ["euler_ancestral"], "all words must match");
eq(filterOptions(samplers, "  "), samplers, "blank query shows all");
eq(filterOptions(samplers, "zzz"), [], "no match");
console.log("PASS test2: filter");

// The result keeps the setting's own order, whatever order the ticks came in.
eq(pickedValuesText(samplers, new Set(["ddim", "euler", "heun"])), "euler\nheun\nddim", "ordered, one per line");
eq(pickedValuesText(samplers, new Set()), "", "nothing ticked");
console.log("PASS test3: picked values keep the setting's order");

// Stored options come back as strings; non-choice axes have none; huge lists are capped.
eq(storedOptions({ properties: { sweepOptions: ["a", 2] } }), ["a", "2"], "stored options");
eq(storedOptions({ properties: {} }), [], "no options");
eq(storedOptions(null), [], "no node");
assert(optionsToStore(Array.from({ length: MAX_STORED_OPTIONS + 50 }, (_, i) => `m${i}`)).length === MAX_STORED_OPTIONS, "cap");
console.log("PASS test4: options are stored as strings and capped");
