// A small stand-in for LiteGraph's graph and nodes: just the parts SweepKit's
// frontend code touches (links, sockets, widgets, connect, add/remove output).

export class FakeNode {
    constructor(graph, spec) {
        this.graph = graph;
        this.id = null;
        this.comfyClass = spec.cls;
        this.type = spec.cls;
        this.pos = [0, 0];
        this.inputs = (spec.inputs || []).map((i) => ({ link: null, ...i }));
        this.outputs = (spec.outputs || []).map((o) => ({ links: [], ...o }));
        this.widgets = (spec.widgets || []).map((w) => ({ ...w }));
    }

    connect(slot, target, targetSlot) {
        if (slot < 0 || targetSlot < 0 || !this.outputs[slot] || !target.inputs[targetSlot]) return null;
        const g = this.graph;
        const input = target.inputs[targetSlot];
        if (input.link != null) {
            const old = g.links[input.link];
            const origin = g.getNodeById(old.origin_id);
            origin.outputs[old.origin_slot].links = origin.outputs[old.origin_slot].links.filter((l) => l !== input.link);
            delete g.links[input.link];
        }
        const link = { id: g.nextLink++, origin_id: this.id, origin_slot: slot, target_id: target.id, target_slot: targetSlot };
        g.links[link.id] = link;
        input.link = link.id;
        this.outputs[slot].links.push(link.id);
        return link;
    }

    addOutput(name, type, extra) {
        this.outputs.push({ name, type, links: [], ...(extra || {}) });
    }

    removeOutput(index) {
        this.outputs.splice(index, 1);
    }
}

const WIDGET_SOCKET = (w) => ({ name: w.name, type: w.type === "combo" ? "COMBO" : "INT", widget: { name: w.name } });

export const TEMPLATES = {
    SweepDimension: {
        cls: "SweepDimension",
        inputs: [{ name: "prev_dimensions", type: "SWEEP_DIMS" }, { name: "values_pylist", type: "PYLIST" }],
        outputs: [{ name: "dimensions", type: "SWEEP_DIMS" }],
        widgets: [
            { name: "dim_type", type: "combo", value: "text" },
            { name: "dim_id", type: "text", value: "" },
            { name: "values", type: "customtext", value: "" },
            { name: "lora_name", type: "combo", value: "" },
        ],
    },
    SweepCombinationExpander: {
        cls: "SweepCombinationExpander",
        inputs: [{ name: "dimensions", type: "SWEEP_DIMS" }],
        outputs: [
            { name: "combo", type: "SWEEP_COMBO" },
            { name: "combo_count", type: "INT" },
            { name: "dim_map", type: "STRING" },
            ...Array.from({ length: 8 }, (_, i) => ({ name: `axis_${i + 1}`, type: "*", shape: 6 })),
        ],
    },
    SweepCollect: {
        cls: "SweepCollect",
        inputs: [{ name: "images", type: "IMAGE" }, { name: "combo", type: "SWEEP_COMBO" }],
        outputs: [{ name: "grids", type: "IMAGE" }, { name: "summary", type: "STRING" }],
    },
    SweepZip: {
        cls: "SweepDimensionZip",
        inputs: [
            { name: "dimensions_a", type: "SWEEP_DIMS" },
            { name: "dimensions_b", type: "SWEEP_DIMS" },
        ],
        outputs: [{ name: "dimensions", type: "SWEEP_DIMS" }],
        widgets: [{ name: "mode", type: "combo", value: "shortest" }],
    },
    SweepSubsets: {
        cls: "SweepDimensionSelfCombine",
        inputs: [{ name: "dimensions", type: "SWEEP_DIMS" }],
        outputs: [{ name: "dimensions", type: "SWEEP_DIMS" }],
        widgets: [
            { name: "mode", type: "combo", value: "combinations" },
            { name: "min_size", type: "number", value: 1 },
            { name: "max_size", type: "number", value: 3 },
            { name: "joiner", type: "text", value: ", " },
        ],
    },
    VAEDecode: { cls: "VAEDecode", inputs: [], outputs: [{ name: "IMAGE", type: "IMAGE" }] },
    KSampler: (() => {
        const widgets = [
            { name: "seed", type: "number", value: 5, options: { precision: 0, min: 0 } },
            { name: "steps", type: "number", value: 20, options: { precision: 0, min: 1, max: 100 } },
            { name: "cfg", type: "number", value: 7, options: { precision: 1, min: 0, max: 100 } },
            { name: "denoise", type: "number", value: 1, options: { precision: 2, min: 0, max: 1 } },
            { name: "sampler_name", type: "combo", value: "heun", options: { values: ["euler", "heun", "dpmpp"] } },
        ];
        return { cls: "KSampler", widgets, inputs: widgets.map(WIDGET_SOCKET), outputs: [{ name: "LATENT", type: "LATENT" }] };
    })(),
};

export class FakeGraph {
    constructor() {
        this._nodes = [];
        this.links = {};
        this.nextLink = 1;
        this.nextId = 1;
        this.changes = { before: 0, after: 0 };
    }

    createNode(cls) {
        if (!TEMPLATES[cls]) throw new Error(`no template for ${cls}`);
        return new FakeNode(this, TEMPLATES[cls]);
    }

    add(node) {
        node.id = this.nextId++;
        node.graph = this;
        this._nodes.push(node);
    }

    getNodeById(id) {
        return this._nodes.find((n) => n.id === id) || null;
    }

    beforeChange() {
        this.changes.before++;
    }

    afterChange() {
        this.changes.after++;
    }

    setDirtyCanvas() {}

    make(cls, patch = {}) {
        const node = this.createNode(cls);
        this.add(node);
        for (const [name, value] of Object.entries(patch)) node.widgets.find((w) => w.name === name).value = value;
        return node;
    }
}

export function env(graph) {
    return { graph, createNode: (cls) => graph.createNode(cls) };
}
