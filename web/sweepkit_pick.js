/**
 * "Pick values from the list": tick the choices to sweep (samplers, LoRA
 * files, checkpoints...) instead of typing their exact names.
 *
 * An axis made from a choice setting remembers that setting's options in
 * node.properties.sweepOptions. The pure helpers below turn ticks into the
 * axis's `values` text (one option per line) and are tested in
 * tests/js_pick_test.mjs; openPicker() is the small dialog around them.
 */

export const MAX_STORED_OPTIONS = 5000;
const MAX_SHOWN = 300;

/** The options an axis can offer, or [] for an axis not made from a choice setting. */
export function storedOptions(node) {
    const list = node && node.properties && node.properties.sweepOptions;
    return Array.isArray(list) ? list.map(String) : [];
}

/** Options to remember for a choice setting (capped so a huge list can't bloat the workflow). */
export function optionsToStore(options) {
    return options.slice(0, MAX_STORED_OPTIONS);
}

/** The options already listed in a `values` text (one per line). */
export function currentSelection(valuesText, options) {
    const wanted = new Set(String(valuesText || "").split("\n").map((s) => s.trim()).filter(Boolean));
    return new Set(options.filter((o) => wanted.has(o)));
}

/** Options containing every word of `query` (any case); all of them for an empty query. */
export function filterOptions(options, query) {
    const words = String(query || "").toLowerCase().split(/\s+/).filter(Boolean);
    return words.length ? options.filter((o) => words.every((w) => o.toLowerCase().includes(w))) : options;
}

/** The `values` text for the ticked options, in the settings's own order. */
export function pickedValuesText(options, selected) {
    return options.filter((o) => selected.has(o)).join("\n");
}

/** Open the dialog. `onApply(text)` gets the new `values` text when the user confirms. */
export function openPicker({ title, options, selected, onApply }, doc = globalThis.document) {
    const chosen = new Set(selected);
    const el = (tag, css, text) => {
        const node = doc.createElement(tag);
        if (css) node.style.cssText = css;
        if (text) node.textContent = text;
        return node;
    };
    const back = el("div", "position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:100000;display:flex;align-items:center;justify-content:center;");
    const box = el("div", "background:#1d1d1d;border:1px solid #556;border-radius:8px;padding:14px 16px;width:420px;max-width:92vw;max-height:80vh;display:flex;flex-direction:column;gap:8px;color:#ddd;font:13px sans-serif;");
    const search = el("input", "padding:6px 8px;border-radius:4px;border:1px solid #445;background:#111;color:#eee;");
    search.placeholder = "Filter…";
    const list = el("div", "overflow:auto;flex:1;min-height:120px;border:1px solid #333;border-radius:4px;padding:4px;");
    const status = el("div", "color:#9aa5b1;font-size:12px;");
    const buttons = el("div", "display:flex;gap:8px;justify-content:flex-end;");

    const close = () => back.remove();
    const button = (label, primary, onClick) => {
        const b = el("button", `padding:5px 12px;border-radius:4px;border:1px solid #667;background:${primary ? "#3a5a9a" : "transparent"};color:#fff;cursor:pointer;`, label);
        b.onclick = onClick;
        return b;
    };
    const render = () => {
        const shown = filterOptions(options, search.value);
        list.replaceChildren();
        for (const option of shown.slice(0, MAX_SHOWN)) {
            const row = el("label", "display:flex;gap:8px;align-items:center;padding:5px 6px;min-height:24px;cursor:pointer;");
            const box = el("input");
            box.type = "checkbox";
            box.checked = chosen.has(option);
            box.onchange = () => {
                if (box.checked) chosen.add(option);
                else chosen.delete(option);
                status.textContent = `${chosen.size} selected`;
            };
            row.append(box, el("span", "overflow-wrap:anywhere;", option));
            list.append(row);
        }
        status.textContent = `${chosen.size} selected` + (shown.length > MAX_SHOWN ? ` — showing the first ${MAX_SHOWN} of ${shown.length}; filter to narrow` : "");
    };
    search.oninput = render;
    buttons.append(
        button("All shown", false, () => {
            filterOptions(options, search.value).slice(0, MAX_SHOWN).forEach((o) => chosen.add(o));
            render();
        }),
        button("None", false, () => {
            chosen.clear();
            render();
        }),
        button("Cancel", false, close),
        button("Use these", true, () => {
            onApply(pickedValuesText(options, chosen));
            close();
        }),
    );
    box.append(el("div", "font-weight:600;", title), search, list, status, buttons);
    back.append(box);
    back.addEventListener("mousedown", (e) => e.target === back && close());
    doc.body.append(back);
    render();
    search.focus();
    return { close };
}
