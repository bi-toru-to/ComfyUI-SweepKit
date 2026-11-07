/**
 * Colours that tell SweepKit's node roles apart at a glance, independent of
 * the ComfyUI app object so tests/js_look_test.mjs can import this exact code.
 *
 *   axis       blue    what to vary (Sweep Axis, Pair Axes, Subsets)
 *   generator  green   makes the images (All-in-One)
 *   output     purple  builds grids and matrices
 *   plumbing   grey    list plumbing for the modular pipeline
 *
 * The values are ComfyUI's own node colour presets, so every colour theme
 * (dark, light, custom) already knows how to adapt them.
 */

export const LOOK_COLORS = {
    axis: { color: "#223", bgcolor: "#335" },
    generator: { color: "#232", bgcolor: "#353" },
    output: { color: "#323", bgcolor: "#535" },
    plumbing: { color: "#2a363b", bgcolor: "#3f5159" },
};

export const NODE_ROLES = {
    SweepDimension: "axis",
    SweepDimensionZip: "axis",
    SweepDimensionSelfCombine: "axis",
    SweepAllInOne: "generator",
    SweepGridConstructor: "output",
    SweepUpsetConstructor: "output",
    SweepCombinationExpander: "plumbing",
    SweepDimensionExtract: "plumbing",
    SweepDedupeCombos: "plumbing",
    SweepGather: "plumbing",
    SweepFilenameSequencer: "plumbing",
};

/** The role of a node class, or null for nodes that aren't SweepKit's. */
export function roleOf(comfyClass) {
    return NODE_ROLES[comfyClass] || null;
}

/** Colour a newly created node by role. A node that already carries a colour
 * (one the user chose, or one restored from a saved workflow) is left alone. */
export function applyLook(node) {
    const role = roleOf(node.comfyClass || node.type);
    if (!role || node.color || node.bgcolor) return false;
    Object.assign(node, LOOK_COLORS[role]);
    return true;
}
