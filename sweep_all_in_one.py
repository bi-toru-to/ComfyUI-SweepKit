"""
SweepAllInOne — multi-dimensional batch generator / grid builder for ComfyUI.

Architecture (see DESIGN.md for the full write-up):

  * Dimensions are not configured on this node. Chain one or
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

import comfy.model_management
import comfy.samplers
import comfy.utils
import folder_paths
from comfy.sd import load_lora_for_models
from comfy.utils import load_torch_file

from .sweep_core import (
    GRID_AXIS_OPTIONS,
    LARGE_SWEEP_WARNING,
    MAX_NAME_LEN,
    PREVIEW_VALUES,
    TRUNCATED_NAME_LEN,
    build_combo_records,
    next_versioned_path,
    safe_component,
    ui_images,
)
from .sweep_image import GridSpec, build_grids, stack_padded, tensor_to_pil

LORA_OFF = 0.0001  # strengths at or below this skip loading the LoRA
GRID_LABEL_PX = 16  # fixed label size for this node's grids (title is 1.6x)


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
        # Unequal on purpose: surplus placeholders (or values) are left alone.
        pairs = list(zip(pattern.finditer(prompt), replacements, strict=False))
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
        """Conditioning in ComfyUI's format: a list of [cond, extras] pairs.

        Uses encode_from_tokens_scheduled(), like the stock CLIPTextEncode,
        because it fills in whatever extras a given text encoder needs
        (attention masks, hooks, model-specific keys). A hand-built
        {"pooled_output": ...} dict has the right shape but produced pure
        noise on FLOW/DiT models; see DESIGN.md, "A real, pre-existing
        correctness bug". The manual wrap is only a fallback for CLIP
        objects that lack the newer method."""
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
        if not lora_name or (abs(strength_model) <= LORA_OFF and abs(strength_clip) <= LORA_OFF):
            return model, clip
        sd = self.load_lora_sd(lora_name, lora_cache)
        new_model, new_clip = load_lora_for_models(model, clip, sd, strength_model, strength_clip)
        return new_model, new_clip

    def sample(self, model, positive, negative, latent, seed, steps, cfg, sampler_name, scheduler, denoise):
        from nodes import common_ksampler

        return common_ksampler(
            model, seed, steps, cfg, sampler_name, scheduler, positive, negative, latent, denoise=denoise
        )[0]

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
        if len(filename_base) > MAX_NAME_LEN:
            filename_base = filename_base[:TRUNCATED_NAME_LEN] + f"_seed{seed}"
        # next_versioned_path appends a 5-digit auto-incrementing counter
        # (matching stock SaveImage's own convention, and also creates
        # `folder` if needed) so rerunning this node never silently
        # overwrites a previous run's images -- a direct PIL save() call
        # has no such protection unless given one explicitly.
        path = next_versioned_path(folder, filename_base)
        tensor_to_pil(image).save(path)
        return path

    # ------------------------------------------------------------------
    # Main
    # ------------------------------------------------------------------

    @staticmethod
    def prepare_dims(dimensions, model, clip):
        """Copy the incoming chain and pair each 'model' dimension's MODEL
        sockets with this node's CLIP (SweepDimension has no CLIP to pair
        them with); an unconnected slot falls back to the base model."""
        dims = [dict(d) for d in dimensions] if dimensions else []
        for d in dims:
            if d["type"] == "model":
                d["model_objs"] = [(m if m is not None else model, clip) for m in d.get("model_objs", [])]
        return dims

    @staticmethod
    def announce(dims_sorted, groups, total):
        print("=" * 60)
        print(
            f"[SweepAllInOne] {len(dims_sorted)} active dimension(s) in {len(groups)} group(s), {total} image(s) total"
        )
        for d in dims_sorted:
            group_note = f" (zipped with group '{d['group']}')" if d.get("group") else ""
            more = " ..." if len(d["values"]) > PREVIEW_VALUES else ""
            print(f"   dim{d['index']} [{d['type']}] '{d['dim_id']}'{group_note}: {d['values'][:PREVIEW_VALUES]}{more}")
        if total > LARGE_SWEEP_WARNING:
            print(
                f"[SweepAllInOne] WARNING: {total} images is a lot — double check this is intended before walking away."
            )
        print("=" * 60)

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
        dims = self.prepare_dims(dimensions, model, clip)
        # Fail before loading or sampling anything.
        self.check_single_sampler_dims(dims)
        text_pattern = self.compile_text_regex(text_regex) if text_mode == "regex" else None

        # Cost-sorted, zip-aware combinations: expensive axes (model, LoRA)
        # vary least often so the caches below are reused.
        records, dims_sorted, groups = build_combo_records(dims)
        self.announce(dims_sorted, groups, len(records))
        roles = _Roles(dims_sorted)
        sampler = _SweepSampler(
            self,
            vae,
            latent_image,
            (sampler_name, scheduler, denoise),
            {"seed": fixed_seed, "steps": fixed_steps, "cfg": fixed_cfg},
            roles,
            _ModelResolver(self, model, clip, roles.lora),
            _PromptEncoder(self, positive_prompt, negative_prompt, text_mode, text_pattern, roles.text),
        )
        save_to = (filename_prefix, output_dir) if save_individuals else None
        all_images, saved_paths = sampler.run(records, dims_sorted, keep_images=create_grids, save_to=save_to)

        safe_prefix = safe_component(filename_prefix) if str(filename_prefix).strip() else "SweepKit"
        axes = (grid_x_dim, grid_y_dim, grid_title_dim)
        grids, grid_paths = self.grids(all_images, dims_sorted, axes, cell_size, cell_mode, safe_prefix, output_dir)
        summary = self.summarize(len(records), dims_sorted, saved_paths, grid_paths, output_dir, safe_prefix)
        print(f"[SweepAllInOne] Done. {summary}")
        return {
            "ui": {"images": ui_images(grid_paths, output_dir), "text": [summary]},
            "result": (stack_padded(grids), summary),
        }

    @staticmethod
    def grids(all_images, dims_sorted, axes, cell_size, cell_mode, safe_prefix, output_dir):
        """Grids for this node: same renderer as SweepGridConstructor, with
        fixed-size labels. None when grids are off or nothing was swept."""
        if not all_images or not dims_sorted:
            return [], []
        spec = GridSpec(
            grid_x_dim=axes[0],
            grid_y_dim=axes[1],
            grid_title_dim=axes[2],
            cell_size=cell_size,
            cell_mode=cell_mode,
            prefix_folder=safe_prefix,
            output_dir=output_dir,
            node_tag="SweepAllInOne",
            base_px=GRID_LABEL_PX,
        )
        return build_grids(all_images, dims_sorted, spec)

    @staticmethod
    def summarize(count, dims_sorted, saved_paths, grid_paths, output_dir, safe_prefix):
        lines = [f"SweepAllInOne: {count} image(s) generated across {len(dims_sorted)} dimension(s)."]
        if saved_paths:
            lines.append(f"Saved {len(saved_paths)} individual file(s) under {os.path.join(output_dir, safe_prefix)}")
        if grid_paths:
            lines.append(f"Saved {len(grid_paths)} grid(s) under {os.path.join(output_dir, safe_prefix, '_grids')}")
        return "\n".join(lines)


class _SweepSampler:
    """Samples, decodes and (optionally) saves every combination in order,
    checking for interrupts and reporting progress per image."""

    def __init__(self, node, vae, latent_image, sampler_args, fixed, roles, models, prompts):
        self.node, self.vae, self.latent_image = node, vae, latent_image
        self.sampler_name, self.scheduler, self.denoise = sampler_args
        self.fixed, self.roles, self.models, self.prompts = fixed, roles, models, prompts

    def sample_one(self, idx):
        cur_model, cur_clip = self.models.for_combo(self.roles.model, idx)
        positive, negative = self.prompts.for_combo(cur_clip, idx)
        seed, steps, cfg = (self.roles.value(t, idx, self.fixed[t]) for t in ("seed", "steps", "cfg"))
        latent = self.node.sample(
            cur_model,
            positive,
            negative,
            self.latent_image,
            seed,
            steps,
            cfg,
            self.sampler_name,
            self.scheduler,
            self.denoise,
        )
        return self.vae.decode(latent["samples"]), seed

    def run(self, records, dims_sorted, keep_images, save_to):
        """Returns ({value-index tuple: image}, saved paths). Images are kept
        only when keep_images is set (for grids), so RAM doesn't grow with
        the sweep otherwise; save_to = (filename_prefix, output_dir) saves
        each image as it is made."""
        pbar = comfy.utils.ProgressBar(len(records))
        all_images, saved_paths = {}, []
        for rec in records:
            comfy.model_management.throw_exception_if_processing_interrupted()
            idx = rec["idx_by_dim"]
            image, seed = self.sample_one(idx)
            if keep_images:
                all_images[tuple(idx[d["index"]] for d in dims_sorted)] = image
            if save_to:
                prefix, output_dir = save_to
                saved_paths.append(self.node.save_individual(image, prefix, dims_sorted, idx, seed, output_dir))
            pbar.update(1)
        return all_images, saved_paths


class _Roles:
    """Which chained dimension plays which part in sampling. At most one
    model/seed/steps/cfg dimension exists (checked earlier); LoRA and text
    dimensions can be several, kept in chain order."""

    def __init__(self, dims_sorted):
        def first(dim_type):
            return next((d for d in dims_sorted if d["type"] == dim_type), None)

        self.model = first("model")
        self.by_type = {t: first(t) for t in ("seed", "steps", "cfg")}
        self.lora = [d for d in dims_sorted if d["type"] == "lora_strength"]
        self.text = [d for d in dims_sorted if d["type"] == "text"]

    def value(self, dim_type, idx, default):
        d = self.by_type[dim_type]
        return d["values"][idx[d["index"]]] if d else default


class _ModelResolver:
    """Model/CLIP for each combination, with the model dimension's choice
    and every LoRA dimension applied. LoRAs are re-applied only when the
    model or any strength actually changes."""

    def __init__(self, node, model, clip, lora_dims):
        self.node, self.model, self.clip, self.lora_dims = node, model, clip, lora_dims
        self.lora_cache = {}
        self.state = None
        self.result = (None, None)

    def for_combo(self, model_dim, idx):
        if model_dim:
            cur_model, cur_clip = model_dim["model_objs"][idx[model_dim["index"]]]
        else:
            cur_model, cur_clip = self.model, self.clip
        if not self.lora_dims:
            return cur_model, cur_clip
        settings = tuple((d["lora_name"], *d["values"][idx[d["index"]]]) for d in self.lora_dims)
        state = (id(cur_model), id(cur_clip), settings)
        if state != self.state:
            for lora_name, sm, sc in settings:
                cur_model, cur_clip = self.node.apply_lora_both(cur_model, cur_clip, lora_name, sm, sc, self.lora_cache)
            self.state, self.result = state, (cur_model, cur_clip)
        return self.result


class _PromptEncoder:
    """Positive/negative conditioning per combination, encoding each
    distinct (CLIP, prompt) pair only once."""

    def __init__(self, node, positive_prompt, negative_prompt, text_mode, text_pattern, text_dims):
        self.node = node
        self.positive_prompt, self.negative_prompt = positive_prompt, negative_prompt
        self.text_mode, self.text_pattern, self.text_dims = text_mode, text_pattern, text_dims
        self.cache = {}

    def _encode(self, clip, text):
        key = (id(clip), text)
        if key not in self.cache:
            self.cache[key] = self.node.encode(clip, text)
        return self.cache[key]

    def for_combo(self, clip, idx):
        replacements = [d["values"][idx[d["index"]]] for d in self.text_dims]
        prompt = self.node.apply_text_replacements(
            self.positive_prompt, replacements, self.text_mode, self.text_pattern
        )
        return self._encode(clip, prompt), self._encode(clip, self.negative_prompt)


NODE_CLASS_MAPPINGS = {"SweepAllInOne": SweepAllInOne}

NODE_DISPLAY_NAME_MAPPINGS = {"SweepAllInOne": "Sweep All-in-One (Modular Text Injection)"}
