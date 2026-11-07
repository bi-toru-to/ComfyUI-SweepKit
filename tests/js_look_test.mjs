// Role colours, exercised through the real applyLook() from web/sweepkit_look.js.
import { LOOK_COLORS, NODE_ROLES, applyLook, roleOf } from "../web/sweepkit_look.js";

function assert(cond, msg) {
    if (!cond) throw new Error("FAIL: " + msg);
}

// Every role used by a node has a colour pair.
for (const [cls, role] of Object.entries(NODE_ROLES)) {
    assert(LOOK_COLORS[role] && LOOK_COLORS[role].color && LOOK_COLORS[role].bgcolor, `${cls}: role ${role} has no colours`);
}
console.log("PASS test1: every node role has a colour pair");

// A new SweepKit node gets its role colour.
let node = { comfyClass: "SweepDimension" };
assert(applyLook(node) === true, "new axis node should be coloured");
assert(node.color === LOOK_COLORS.axis.color && node.bgcolor === LOOK_COLORS.axis.bgcolor, "axis colour");
node = { comfyClass: "SweepAllInOne" };
applyLook(node);
assert(node.bgcolor === LOOK_COLORS.generator.bgcolor, "generator colour");
console.log("PASS test2: new nodes are coloured by role");

// A node that already has a colour (the user's, or from a saved workflow) is not touched.
node = { comfyClass: "SweepDimension", color: "#123456" };
assert(applyLook(node) === false && node.color === "#123456" && node.bgcolor === undefined, "existing colour kept");
node = { comfyClass: "SweepDimension", bgcolor: "#654321" };
assert(applyLook(node) === false && node.bgcolor === "#654321" && node.color === undefined, "existing bgcolor kept");
console.log("PASS test3: existing colours are kept");

// Other packs' nodes are never coloured; falls back to node.type when comfyClass is missing.
node = { comfyClass: "KSampler" };
assert(applyLook(node) === false && node.color === undefined, "foreign node untouched");
assert(roleOf("SweepGather") === "plumbing" && roleOf(undefined) === null, "roleOf");
node = { type: "SweepGridConstructor" };
assert(applyLook(node) && node.bgcolor === LOOK_COLORS.output.bgcolor, "falls back to node.type");
console.log("PASS test4: only SweepKit nodes are coloured");
