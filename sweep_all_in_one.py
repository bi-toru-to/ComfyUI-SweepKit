"""
SweepAllInOne — multi-dimensional batch generator / grid builder for ComfyUI.

Architecture (see DESIGN.md for the full write-up):

  * Dimensions are no longer configured on this node at all. Chain one or
    more SweepDimension nodes (each is one axis: text/seed/steps/cfg/
    lora_strength/model/static) and connect the end of the chain into this
    node's `dimensions` input. Leave it unconnected for a single
    fixed-parameter generation with no sweep.
  * A "model"-type SweepDimension spawns its own MODEL input sockets
    (handled by that node's JS, not this one) — a fully-resolved model per
    axis value arrives here already, no internal checkpoint loading.
  * Execution order is cost-sorted (expensive axes outermost): model swaps
    first, then lora application, then text re-encoding, then the
    essentially-free seed/steps/cfg axes innermost.
  * Grids generalize to N dimensions: grid_x_dim/grid_y_dim/grid_title_dim
    pick which dimension is which; anything left over becomes an extra
    grouping axis that produces additional grids in nested folders,
    instead of being silently discarded.
"""

import os
import re
import itertools
import torch
import numpy as np
from PIL import Image, ImageDraw

import folder_paths
import comfy.samplers
import comfy.utils
import comfy.model_management
from comfy.utils import load_torch_file
from comfy.sd import load_lora_for_models

from .sweep_core import (
    GRID_AXIS_OPTIONS,
    safe_component,
    resolve_grid_axes,
    resolve_group_index,
    partition_into_groups,
    sort_groups,
    dim_group_members,
    format_group_value,
    find_font,
    next_versioned_path,
)


class SweepAllInOne:
    @classmethod
    def INPUT_TYPES(cls):
        required = {
            "model": ("MODEL",),
            "clip": ("CLIP",),
            "vae": ("VAE",),
            # Note for anyone looking for a "positive/negative CONDITIONING
            # socket": there isn't one, on purpose. These are plain text
            # widgets (like the two boxes on any CLIPTextEncode node) —
            # this node encodes them itself, internally, AFTER substituting
            # {} placeholders per-combination, since that substitution has
            # to happen before encoding. ComfyUI doesn't render a name
            # label above multiline text widgets (same as CLIPTextEncode),
            # so the only way to tell them apart in the node body is
            # position: this one (positive) comes first, negative_prompt
            # is the box directly below it. The tooltips below show on
            # hover as a workaround for that missing label.
            "positive_prompt": (
                "STRING",
                {
                    "multiline": True,
                    "default": "masterpiece, best quality, {}, 1girl, {}, looking at viewer",
                    "tooltip": (
                        "POSITIVE prompt (this is the first of the two text boxes; "
                        "negative_prompt is the box right below it — ComfyUI doesn't "
                        "label multiline boxes, same as CLIPTextEncode). "
                        "Each {} is filled in, left to right, by your 'text'-type "
                        "SweepDimension nodes in chain order — the first one fills "
                        "the 1st {}, the next fills the 2nd {}, and so on. "
                        "Non-text dimensions in between are skipped when counting."
                    ),
                },
            ),
            "negative_prompt": (
                "STRING",
                {
                    "multiline": True,
                    "default": "worst quality, low quality",
                    "tooltip": "NEGATIVE prompt (the box below positive_prompt). Fixed — does not vary across the sweep.",
                },
            ),
            "latent_image": ("LATENT",),
            "text_mode": (["curly", "regex"],),
            "text_regex": ("STRING", {"default": r"\{\}"}),
            "fixed_seed": (
                "INT",
                {
                    "default": 1,
                    "min": 0,
                    "max": 0xFFFFFFFFFFFFFFFF,
                    "tooltip": "Used when no SweepDimension of type 'seed' is chained in — pins every image in the sweep to this one seed instead of always defaulting to 1.",
                },
            ),
            "fixed_steps": (
                "INT",
                {
                    "default": 35,
                    "min": 1,
                    "max": 10000,
                    "tooltip": "Used when no SweepDimension of type 'steps' is chained in.",
                },
            ),
            "fixed_cfg": (
                "FLOAT",
                {
                    "default": 4.5,
                    "min": 0.0,
                    "max": 100.0,
                    "step": 0.05,
                    "tooltip": "Used when no SweepDimension of type 'cfg' is chained in.",
                },
            ),
            "sampler_name": (comfy.samplers.KSampler.SAMPLERS, {"default": comfy.samplers.KSampler.SAMPLERS[0]}),
            "scheduler": (comfy.samplers.KSampler.SCHEDULERS, {"default": comfy.samplers.KSampler.SCHEDULERS[0]}),
            "denoise": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 1.0, "step": 0.01}),
            "filename_prefix": ("STRING", {"default": "SweepKit"}),
            "save_individuals": ("BOOLEAN", {"default": True}),
            "create_grids": ("BOOLEAN", {"default": True}),
            "cell_size": (
                "INT",
                {
                    "default": 512,
                    "min": 64,
                    "max": 4096,
                    "step": 64,
                    "tooltip": "Meaning depends on cell_mode: the fixed width/height for 'square', the larger dimension's target size for 'fit'. Ignored by 'original'.",
                },
            ),
            "cell_mode": (
                ["fit", "square", "original"],
                {
                    "default": "fit",
                    "tooltip": (
                        "How each image is placed into its grid cell. 'fit' scales to cell_size "
                        "preserving aspect ratio (recommended — no distortion, bounded grid size). "
                        "'square' stretches to a cell_size×cell_size square (may distort non-square "
                        "images — this was the only behavior before). 'original' uses each image's "
                        "native resolution with no resizing at all (sharpest, but the grid image can "
                        "get very large)."
                    ),
                },
            ),
            "grid_x_dim": (
                GRID_AXIS_OPTIONS,
                {
                    "default": "auto",
                    "tooltip": "Which chained dimension (by chain position, dim1..dimN) is the grid's X axis. 'auto' prefers a seed-type dimension; 'none' = single column.",
                },
            ),
            "grid_y_dim": (
                GRID_AXIS_OPTIONS,
                {
                    "default": "auto",
                    "tooltip": "Which dimension is the grid's Y axis. 'auto' picks whatever's left after X/Title; 'none' = single row.",
                },
            ),
            "grid_title_dim": (
                GRID_AXIS_OPTIONS,
                {
                    "default": "auto",
                    "tooltip": "Which dimension's value becomes the grid's title + top output folder. 'auto' prefers the first text/static dimension. Any dimension not used for X/Y/Title still produces its own set of extra grids — chain more than the picker lists and they'll still work, just as automatic grouping axes.",
                },
            ),
        }

        optional = {
            "dimensions": (
                "SWEEP_DIMS",
                {
                    "tooltip": "Connect the end of a chain of SweepDimension nodes here. Leave unconnected for a single fixed-parameter generation with no sweep.",
                },
            ),
        }

        return {"required": required, "optional": optional}

    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("grids", "summary")
    FUNCTION = "generate"
    CATEGORY = "SweepKit"
    OUTPUT_NODE = True

    # ------------------------------------------------------------------
    # Small stateless helpers that DO need torch/comfy (image conversion,
    # sampling, encoding, lora application).
    # ------------------------------------------------------------------

    def tensor_to_pil(self, tensor):
        i = 255.0 * tensor.cpu().numpy()
        return Image.fromarray(np.clip(i.squeeze(), 0, 255).astype(np.uint8))

    def pil_to_tensor(self, pil_img):
        arr = np.array(pil_img).astype(np.float32) / 255.0
        return torch.from_numpy(arr).unsqueeze(0)

    @staticmethod
    def compile_text_regex(text_regex):
        """Compile the user's text_regex once, turning a bad pattern into a
        clear node-tagged error instead of a raw re.PatternError mid-run."""
        try:
            return re.compile(text_regex)
        except re.error as e:
            raise ValueError(
                f"[SweepAllInOne] text_regex {text_regex!r} is not a valid regular expression: {e}. "
                f"Use text_mode='curly' for plain {{}} placeholders."
            ) from e

    def apply_text_replacements(self, prompt, replacements, mode, regex_pat):
        """Fill placeholders left to right: the 1st text dimension fills the
        1st placeholder, the 2nd fills the 2nd, and so on, in both modes.
        Placeholders beyond the number of text dimensions are left as-is."""
        if mode == "curly":
            result = prompt
            for rep in replacements:
                result = result.replace("{}", str(rep), 1)
            return result
        pattern = regex_pat if isinstance(regex_pat, re.Pattern) else self.compile_text_regex(regex_pat)
        pairs = list(zip(pattern.finditer(prompt), replacements))
        result = prompt
        # Splice right-to-left so earlier match offsets stay valid.
        for match, rep in reversed(pairs):
            result = result[: match.start()] + str(rep) + result[match.end() :]
        return result

    @staticmethod
    def check_single_sampler_dims(active_dims):
        """Each combination can only use one model, seed, step count and cfg,
        so more than one dimension of those types can't be honoured.
        (lora_strength dimensions are different: several are stacked.)"""
        for dim_type in ("model", "seed", "steps", "cfg"):
            same = [d for d in active_dims if d["type"] == dim_type]
            if len(same) > 1:
                ids = ", ".join(f"'{d['dim_id']}'" for d in same)
                raise ValueError(
                    f"[SweepAllInOne] {len(same)} '{dim_type}'-type dimensions are chained ({ids}), but each "
                    f"image can only use one {dim_type}. Remove the extra one, merge their values into a single "
                    f"dimension, or use a generic 'int'/'float' dimension for anything that isn't this node's "
                    f"own {dim_type}."
                )

    def encode(self, clip, text):
        """Return conditioning in the shape ComfyUI's sampler actually
        expects: a list of [cond_tensor, extra_dict] pairs.

        History here, because it's been wrong twice in a row and it's
        worth being explicit about why:

        v1 returned `clip.encode_from_tokens(tokens, return_pooled=True)`
        directly — a bare (cond_tensor, pooled) 2-tuple, not wrapped in
        the outer list ComfyUI's conditioning format requires. Went
        unnoticed for a long time because most of the sampling path
        doesn't actually validate conditioning shape; it only surfaced
        as a crash once execution hit code that genuinely iterates
        conds expecting [cond, dict] pairs.

        v2 (the actual bug this comment used to describe) fixed the
        *shape* by manually wrapping it as `[[cond, {"pooled_output":
        pooled}]]` — that stopped the crash, but produced pure-noise
        output on a FLOW-matching model with a custom text encoder. The crash is gone because the shape is now valid
        enough to iterate without erroring, but a hand-built dict
        containing only "pooled_output" can still be missing whatever
        *other* extra keys that specific architecture's conditioning
        actually needs to modulate on (attention masks, hook data,
        model-specific extras) — FLOW/DiT-style models lean on that
        conditioning much more heavily than classic UNet diffusion, so
        incomplete conditioning there can fail silently (no crash, no
        denoising) rather than just looking slightly off.

        v3 (this version) uses `clip.encode_from_tokens_scheduled()` —
        the same method the real, stock CLIPTextEncode node uses — which
        builds the correctly-shaped list AND includes whatever extra
        fields the specific CLIP/model implementation actually needs,
        instead of a hand-rolled guess at what's required. Falls back to
        the v2 manual wrap only if a given CLIP object doesn't implement
        the newer method at all.
        """
        tokens = clip.tokenize(text)
        if hasattr(clip, "encode_from_tokens_scheduled"):
            return clip.encode_from_tokens_scheduled(tokens)
        cond, pooled = clip.encode_from_tokens(tokens, return_pooled=True)
        return [[cond, {"pooled_output": pooled}]]

    def load_lora_sd(self, lora_name, lora_cache):
        if lora_name in lora_cache:
            return lora_cache[lora_name]
        path = folder_paths.get_full_path("loras", lora_name)
        if path is None:
            available = ", ".join(folder_paths.get_filename_list("loras")) or "(none found)"
            raise ValueError(f"[SweepAllInOne] LoRA '{lora_name}' was not found. Available LoRAs: {available}")
        sd = load_torch_file(path, safe_load=True)
        lora_cache[lora_name] = sd
        return sd

    def apply_lora_both(self, model, clip, lora_name, strength_model, strength_clip, lora_cache):
        """Apply a LoRA to BOTH the model and the CLIP."""
        if not lora_name or (abs(strength_model) <= 0.0001 and abs(strength_clip) <= 0.0001):
            return model, clip
        sd = self.load_lora_sd(lora_name, lora_cache)
        new_model, new_clip = load_lora_for_models(model, clip, sd, strength_model, strength_clip)
        return new_model, new_clip

    def sample(self, model, positive, negative, latent, seed, steps, cfg, sampler_name, scheduler, denoise):
        from nodes import common_ksampler

        return common_ksampler(
            model, seed, steps, cfg, sampler_name, scheduler, positive, negative, latent, denoise=denoise
        )[0]

    def _hw_from_tensor(self, img):
        """(height, width) from an image tensor, read from the END of its
        shape rather than fixed positions 1/2. ComfyUI's channels-last
        convention (..., H, W, C) is stable regardless of how many
        leading dimensions exist — a plain [batch, H, W, C] tensor and a
        video-capable VAE's [batch, frames, H, W, C] output (frames=1 for
        a still image) both have H, W as the two dims right before
        channels, just at different absolute positions. Reading from a
        fixed shape[1]/shape[2] silently grabbed the wrong axis for the
        latter case — not a crash, just badly wrong numbers, which is
        exactly what produced a near-zero cell height instead of an
        error: shape[1] became the frame count (1) rather than height."""
        shape = img.shape
        return shape[-3], shape[-2]

    def _cell_dims(self, images, cell_size, cell_mode):
        """Determine (cell_w, cell_h) for every grid cell, from the actual
        images being placed and the chosen sizing mode."""
        real = [img for img in images if img is not None]
        if not real:
            return cell_size, cell_size
        h0, w0 = self._hw_from_tensor(real[0])

        if cell_mode == "original":
            # Use the max native size across all images, in case they
            # differ (unusual, but possible with a 'model' dimension
            # mixing resolutions) — nothing gets cropped either way.
            hws = [self._hw_from_tensor(img) for img in real]
            return max(w for h, w in hws), max(h for h, w in hws)
        elif cell_mode == "fit":
            scale = cell_size / max(h0, w0)
            return max(1, round(w0 * scale)), max(1, round(h0 * scale))
        else:  # "square" — the original behavior: force a square, may distort
            return cell_size, cell_size

    def _paste_into_cell(self, grid, pil_img, x, y, cell_w, cell_h, cell_mode):
        """Place one image into its cell. For 'fit'/'original', resize
        preserving THIS image's own aspect ratio and center it
        (letterboxing with the grid background if its ratio doesn't
        exactly match the cell) — this guarantees no image is ever
        stretched, even if resolutions aren't perfectly uniform across the
        sweep. 'square' keeps the original behavior of stretching directly
        to fill the cell."""
        if cell_mode == "square":
            resized = pil_img.resize((cell_w, cell_h), Image.LANCZOS)
            grid.paste(resized, (x, y))
            return
        iw, ih = pil_img.size
        scale = min(cell_w / iw, cell_h / ih)
        new_w, new_h = max(1, round(iw * scale)), max(1, round(ih * scale))
        resized = pil_img.resize((new_w, new_h), Image.LANCZOS)
        off_x = x + (cell_w - new_w) // 2
        off_y = y + (cell_h - new_h) // 2
        grid.paste(resized, (off_x, off_y))

    def make_grid(self, images, x_labels, y_labels, title, cell_size=512, cell_mode="fit"):
        cols = max(len(x_labels), 1)
        rows = max(len(y_labels), 1)
        pad, title_h, label_h, label_w = 40, 70, 36, 140

        cell_w, cell_h = self._cell_dims(images, cell_size, cell_mode)

        font_title = find_font(26)
        font_label = find_font(16)

        # Canvas width must accommodate the title text too -- a narrow grid
        # (few columns) paired with a long combined title (e.g. several
        # zipped dimensions' values joined together) would otherwise get
        # clipped at both edges, since width used to be computed only from
        # cols * cell_w, never from the title string's own rendered width.
        scratch = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        title_w = scratch.textbbox((0, 0), str(title), font=font_title)[2] + 40

        W = max(cols * cell_w + label_w + pad, title_w)
        H = rows * cell_h + title_h + label_h + pad
        grid = Image.new("RGB", (W, H), (16, 16, 16))
        draw = ImageDraw.Draw(grid)

        draw.text((W // 2, 16), str(title), fill=(255, 255, 255), font=font_title, anchor="mt")

        for i, lab in enumerate(x_labels):
            x = label_w + i * cell_w + cell_w // 2
            draw.text((x, title_h + 6), str(lab), fill=(210, 210, 210), font=font_label, anchor="mt")

        idx = 0
        for r, ylab in enumerate(y_labels):
            y = title_h + label_h + r * cell_h
            draw.text((10, y + cell_h // 2), str(ylab), fill=(210, 210, 210), font=font_label, anchor="lm")
            for c in range(cols):
                img = images[idx] if idx < len(images) else None
                cell_x = label_w + c * cell_w
                if img is not None:
                    pil = self.tensor_to_pil(img)
                    self._paste_into_cell(grid, pil, cell_x, y, cell_w, cell_h, cell_mode)
                else:
                    box = [cell_x, y, cell_x + cell_w, y + cell_h]
                    draw.rectangle(box, outline=(90, 30, 30), width=3)
                    draw.text(
                        ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2),
                        "missing",
                        fill=(200, 120, 120),
                        font=font_label,
                        anchor="mm",
                    )
                idx += 1
        return grid

    def save_individual(self, image, prefix, active_dims_sorted, idx_by_dim_index, seed, output_dir):
        """Save one image. Only 'text' and 'static' dimensions become
        folder levels; every other axis (seed/steps/cfg/lora_strength/
        model) is encoded into the filename only."""
        # Sanitized for use in the FILENAME specifically -- os.path.join
        # below already handles prefix safely as a folder component even
        # if it contains '/', but embedding an un-sanitized prefix
        # directly into a filename string (rather than a real path
        # component) means an embedded '/' implies a subdirectory that
        # was never created via makedirs, and the save() call below fails
        # with FileNotFoundError.
        safe_prefix = safe_component(prefix) if str(prefix).strip() else "SweepKit"
        folder_parts = []
        name_parts = []
        has_seed_dim = False
        for d in active_dims_sorted:
            vi = idx_by_dim_index[d["index"]]
            dtype = d["type"]
            if dtype in ("text", "static"):
                val = d["values"][vi]
                comp = safe_component(val)
                if "combo_meta" not in d:
                    # A self-combined dimension's values are unique per
                    # combo by construction -- treating it as a folder
                    # level would put every image in its own folder.
                    folder_parts.append(comp)
                name_parts.append(comp)
            elif dtype == "model":
                val = d["values"][vi]
                name_parts.append(f"{safe_component(d['dim_id'])}-{safe_component(val)}")
            elif dtype == "lora_strength":
                sm, sc = d["values"][vi]
                name_parts.append(f"{safe_component(d['dim_id'])}{sm:g}")
            else:  # seed, steps, cfg
                val = d["values"][vi]
                name_parts.append(f"{dtype}{val}")
                if dtype == "seed":
                    has_seed_dim = True

        folder = (
            os.path.join(output_dir, safe_prefix, *folder_parts)
            if folder_parts
            else os.path.join(output_dir, safe_prefix)
        )
        base = "_".join(name_parts) if name_parts else "image"
        filename_base = f"{safe_prefix}_{base}" if has_seed_dim else f"{safe_prefix}_{base}_seed{seed}"
        if len(filename_base) > 220:
            filename_base = filename_base[:200] + f"_seed{seed}"
        # next_versioned_path appends a 5-digit auto-incrementing counter
        # (matching stock SaveImage's own convention, and also creates
        # `folder` if needed) so rerunning this node never silently
        # overwrites a previous run's images -- a direct PIL save() call
        # has no such protection unless given one explicitly.
        path = next_versioned_path(folder, filename_base)
        self.tensor_to_pil(image).save(path)
        return path

    # ------------------------------------------------------------------
    # Main
    # ------------------------------------------------------------------

    def generate(
        self,
        model,
        clip,
        vae,
        positive_prompt,
        negative_prompt,
        latent_image,
        text_mode,
        text_regex,
        fixed_seed,
        fixed_steps,
        fixed_cfg,
        sampler_name,
        scheduler,
        denoise,
        filename_prefix,
        save_individuals,
        create_grids,
        cell_size,
        cell_mode,
        grid_x_dim,
        grid_y_dim,
        grid_title_dim,
        dimensions=None,
        **kwargs,
    ):

        output_dir = folder_paths.get_output_directory()

        # ---------- Dimensions arrive pre-built from the SweepDimension
        # chain. Just resolve "model"-type dims' raw MODEL sockets (which
        # SweepDimension couldn't pair with a CLIP itself, since CLIP lives
        # on this node) into (model, clip) tuples, falling back to this
        # node's own base model/clip for any unconnected slot. ----------
        active_dims = [dict(d) for d in dimensions] if dimensions else []
        for d in active_dims:
            if d["type"] == "model":
                d["model_objs"] = [(m if m is not None else model, clip) for m in d.get("model_objs", [])]

        active_dims_sorted = sorted(active_dims, key=lambda d: d["index"])

        # Fail before loading or sampling anything.
        self.check_single_sampler_dims(active_dims)
        text_pattern = self.compile_text_regex(text_regex) if text_mode == "regex" else None

        # ---------- Group-aware, cost-based execution ordering ----------
        # Dimensions zipped together by SweepDimensionZip share a 'group'
        # id and must vary in lockstep — grouped together here so the
        # combo-generation loop below gives them exactly one shared index
        # each iteration instead of cross-producting them independently.
        # Ungrouped dimensions are unaffected (each is its own singleton
        # group, same as before zip existed).
        #
        # Sort so the most expensive-to-switch GROUPS vary LEAST often —
        # a group's cost is however expensive its priciest member is (e.g.
        # a lora_strength dimension zipped with cfg is still outer-loop
        # material, since the lora changes too whenever that group's index
        # does). itertools.product() varies the last-listed iterable
        # fastest, so listing expensive groups first and cheap ones last
        # gives exactly the nesting we want.
        groups = partition_into_groups(active_dims)
        sorted_groups = sort_groups(groups)

        total_images = 1
        for g in groups:
            total_images *= len(g[0]["values"])
        if not active_dims:
            total_images = 1

        print("=" * 60)
        print(
            f"[SweepAllInOne] {len(active_dims)} active dimension(s) in {len(groups)} group(s), {total_images} image(s) total"
        )
        for d in active_dims_sorted:
            preview = d["values"][:6]
            group_note = f" (zipped with group '{d['group']}')" if d.get("group") else ""
            print(
                f"   dim{d['index']} [{d['type']}] '{d['dim_id']}'{group_note}: {preview}{' ...' if len(d['values']) > 6 else ''}"
            )
        if total_images > 500:
            print(
                f"[SweepAllInOne] WARNING: {total_images} images is a lot — double check this is intended before walking away."
            )
        print("=" * 60)

        pbar = comfy.utils.ProgressBar(max(total_images, 1))

        # ---------- Caches (avoid redundant CLIP-encodes / LoRA loads) ----------
        encode_cache = {}
        negative_cache = {}
        lora_cache = {}
        current_lora_state = None
        current_lora_result = (None, None)

        all_images = {}
        saved_paths = []
        count = 0

        combos = itertools.product(*[range(len(g[0]["values"])) for g in sorted_groups]) if sorted_groups else [()]

        # At most one of each (enforced above); LoRA dims stack in chain order.
        model_dim = next((d for d in active_dims if d["type"] == "model"), None)
        seed_dim = next((d for d in active_dims if d["type"] == "seed"), None)
        steps_dim = next((d for d in active_dims if d["type"] == "steps"), None)
        cfg_dim = next((d for d in active_dims if d["type"] == "cfg"), None)
        lora_dims = [d for d in active_dims_sorted if d["type"] == "lora_strength"]
        text_dims = [d for d in active_dims_sorted if d["type"] == "text"]

        for combo in combos:
            comfy.model_management.throw_exception_if_processing_interrupted()

            idx_by_dim_index = {}
            for group, group_vi in zip(sorted_groups, combo):
                for d in group:
                    idx_by_dim_index[d["index"]] = group_vi

            # ---- resolve model/clip for this combination ----
            cur_model, cur_clip = model, clip
            if model_dim is not None:
                vi = idx_by_dim_index[model_dim["index"]]
                cur_model, cur_clip = model_dim["model_objs"][vi]

            if lora_dims:
                lora_settings = tuple((d["lora_name"], *d["values"][idx_by_dim_index[d["index"]]]) for d in lora_dims)
                state_key = (id(cur_model), id(cur_clip), lora_settings)
                if state_key != current_lora_state:
                    for lora_name, sm, sc in lora_settings:
                        cur_model, cur_clip = self.apply_lora_both(cur_model, cur_clip, lora_name, sm, sc, lora_cache)
                    current_lora_state = state_key
                    current_lora_result = (cur_model, cur_clip)
                else:
                    cur_model, cur_clip = current_lora_result

            # ---- build + encode the prompt ----
            replacements = [d["values"][idx_by_dim_index[d["index"]]] for d in text_dims]
            prompt_text = self.apply_text_replacements(positive_prompt, replacements, text_mode, text_pattern)

            enc_key = (id(cur_clip), prompt_text)
            if enc_key not in encode_cache:
                encode_cache[enc_key] = self.encode(cur_clip, prompt_text)
            positive = encode_cache[enc_key]

            neg_key = id(cur_clip)
            if neg_key not in negative_cache:
                negative_cache[neg_key] = self.encode(cur_clip, negative_prompt)
            negative = negative_cache[neg_key]

            # ---- seed / steps / cfg ----
            seed = seed_dim["values"][idx_by_dim_index[seed_dim["index"]]] if seed_dim else fixed_seed
            steps = steps_dim["values"][idx_by_dim_index[steps_dim["index"]]] if steps_dim else fixed_steps
            cfg = cfg_dim["values"][idx_by_dim_index[cfg_dim["index"]]] if cfg_dim else fixed_cfg

            latent = self.sample(
                cur_model, positive, negative, latent_image, seed, steps, cfg, sampler_name, scheduler, denoise
            )
            image = vae.decode(latent["samples"])

            key = tuple(idx_by_dim_index[d["index"]] for d in active_dims_sorted)
            all_images[key] = image

            if save_individuals:
                p = self.save_individual(image, filename_prefix, active_dims_sorted, idx_by_dim_index, seed, output_dir)
                saved_paths.append(p)

            count += 1
            pbar.update(1)

        # ---------- Build grids ----------
        grids = []
        grid_paths = []
        # Sanitized once here for the same reason as save_individual's
        # safe_prefix -- used below as a bare filename component, where an
        # un-sanitized value containing '/' would imply an un-created
        # subdirectory and make the save() call fail with
        # FileNotFoundError.
        safe_prefix = safe_component(filename_prefix) if str(filename_prefix).strip() else "SweepKit"
        if create_grids and active_dims:
            x_dim, y_dim, title_dim, other_dims = resolve_grid_axes(
                active_dims_sorted, grid_x_dim, grid_y_dim, grid_title_dim
            )
            # Renamed to axis_* to avoid confusion with SweepDimensionZip's
            # "group" concept (dimensions paired to share one index) — this
            # is a different kind of grouping: the leftover axes that each
            # get their own separate grid image.
            axis_grouping_dims = ([title_dim] if title_dim else []) + other_dims
            axis_grouping_ranges = [range(len(d["values"])) for d in axis_grouping_dims]
            x_range = list(range(len(x_dim["values"]))) if x_dim else [0]
            y_range = list(range(len(y_dim["values"]))) if y_dim else [0]

            total_grids = 1
            for r in axis_grouping_ranges:
                total_grids *= len(r)
            print(
                f"[SweepAllInOne] Building {total_grids} grid(s) "
                f"(x={x_dim['dim_id'] if x_dim else '—'}, y={y_dim['dim_id'] if y_dim else '—'}"
                f"{', title=' + title_dim['dim_id'] if title_dim else ''})"
            )

            # X/Y axis names shown once, near the top of the grid, rather
            # than repeated on every column/row — same convention as a
            # normal chart's axis title. This is what was actually missing
            # in the "no labels" report: individual tick values (e.g. a
            # zipped pair's "0.5, 15, 2") were being drawn, but nothing on
            # the grid said what axis or dimension(s) they belonged to,
            # especially with grid_title_dim set to "none".
            axis_caption_bits = []
            if x_dim:
                axis_caption_bits.append(f"X: {x_dim.get('group_label', x_dim['dim_id'])}")
            if y_dim:
                axis_caption_bits.append(f"Y: {y_dim.get('group_label', y_dim['dim_id'])}")
            axis_caption = "   ".join(axis_caption_bits)

            for axis_group_combo in itertools.product(*axis_grouping_ranges) if axis_grouping_dims else [()]:
                axis_group_idx = {d["index"]: vi for d, vi in zip(axis_grouping_dims, axis_group_combo)}

                images = []
                for yi in y_range:
                    for xi in x_range:
                        full_idx = dict(axis_group_idx)
                        if x_dim:
                            full_idx[x_dim["index"]] = xi
                        if y_dim:
                            full_idx[y_dim["index"]] = yi
                        # resolve_group_index falls back to a zip-groupmate's
                        # resolved index for any dim that wasn't itself given
                        # an X/Y/Title/grouping role (its groupmate was used
                        # to represent the pair instead) — without this, an
                        # unrepresented zip partner would default to index 0
                        # regardless of which value was actually generated.
                        key = tuple(resolve_group_index(d, full_idx, active_dims_sorted) for d in active_dims_sorted)
                        images.append(all_images.get(key))

                # format_group_value shows every dimension that's actually
                # zipped together at this axis, not just whichever single
                # member happened to represent the group (and formats
                # lora_strength as "0.5" / "0.5/0.3" instead of Python's
                # raw tuple repr "(0.5, 0.5)").
                x_labels = (
                    [format_group_value(dim_group_members(x_dim, active_dims_sorted), xi) for xi in x_range]
                    if x_dim
                    else [""]
                )
                y_labels = (
                    [format_group_value(dim_group_members(y_dim, active_dims_sorted), yi) for yi in y_range]
                    if y_dim
                    else [""]
                )

                title_bits = []
                folder_parts = []
                for d, vi in zip(axis_grouping_dims, axis_group_combo):
                    members = dim_group_members(d, active_dims_sorted)
                    disp = format_group_value(members, vi)
                    title_bits.append(f"{d.get('group_label', d['dim_id'])}: {disp}")
                    folder_parts.append(safe_component(disp))
                title_text = " | ".join(title_bits) if title_bits else safe_prefix
                if axis_caption:
                    title_text = f"{title_text}   •   {axis_caption}" if title_bits else axis_caption

                grid_pil = self.make_grid(images, x_labels, y_labels, title_text, cell_size, cell_mode)

                grid_dir = (
                    os.path.join(output_dir, safe_prefix, "_grids", *folder_parts[:-1])
                    if len(folder_parts) > 1
                    else os.path.join(output_dir, safe_prefix, "_grids")
                )
                # next_versioned_path appends a 5-digit auto-incrementing
                # counter (matching stock SaveImage's own convention, and
                # also creates grid_dir if needed) so rerunning this node
                # never silently overwrites a previous grid.
                tail = folder_parts[-1] if folder_parts else "grid"
                path = next_versioned_path(grid_dir, tail)
                grid_pil.save(path)
                grid_paths.append(path)
                grids.append(self.pil_to_tensor(grid_pil))

        if not grids:
            grids = [torch.zeros(1, 512, 512, 3)]

        if len(grids) > 1:
            target_shape = grids[0].shape
            fixed = []
            for g in grids:
                if g.shape != target_shape:
                    pil = self.tensor_to_pil(g[0]).resize((target_shape[2], target_shape[1]), Image.LANCZOS)
                    g = self.pil_to_tensor(pil)
                fixed.append(g)
            grids = fixed

        summary_lines = [
            f"SweepAllInOne: {count} image(s) generated across {len(active_dims)} dimension(s).",
        ]
        if save_individuals:
            summary_lines.append(
                f"Saved {len(saved_paths)} individual file(s) under {os.path.join(output_dir, safe_prefix)}"
            )
        if create_grids and grid_paths:
            summary_lines.append(
                f"Saved {len(grid_paths)} grid(s) under {os.path.join(output_dir, safe_prefix, '_grids')}"
            )
        summary = "\n".join(summary_lines)
        print(f"[SweepAllInOne] Done. {summary}")

        return (torch.cat(grids, dim=0), summary)


NODE_CLASS_MAPPINGS = {"SweepAllInOne": SweepAllInOne}

NODE_DISPLAY_NAME_MAPPINGS = {"SweepAllInOne": "Sweep All-in-One (Modular Text Injection)"}
