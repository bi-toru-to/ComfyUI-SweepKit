"""
Minimal fake ComfyUI/torch environment so we can actually import and
exercise sweep_all_in_one.py's real control flow (dimension parsing,
cost ordering, lora/model socket resolution, grid building) without
needing torch or a real ComfyUI install. Numpy stands in for torch.
"""
import sys, types, os
import numpy as np

# ---------------- fake torch ----------------
class FakeTensor:
    def __init__(self, arr):
        self.arr = np.asarray(arr)
    def cpu(self):
        return self
    def numpy(self):
        return self.arr
    def unsqueeze(self, dim):
        return FakeTensor(np.expand_dims(self.arr, dim))
    def __getitem__(self, idx):
        # Real torch tensors support indexing (e.g. grids[0] to drop the
        # batch dim); the stub needs this too now that grid-reconciliation
        # code (mismatched-shape resizing) is actually being exercised by
        # tests with differently-sized pages/grids, not just same-shaped ones.
        return FakeTensor(self.arr[idx])
    @property
    def shape(self):
        return self.arr.shape
    def __repr__(self):
        return f"FakeTensor{self.arr.shape}"

torch_mod = types.ModuleType("torch")
def _zeros(*shape):
    return FakeTensor(np.zeros(shape, dtype=np.float32))
def _cat(tensors, dim=0):
    return FakeTensor(np.concatenate([t.arr for t in tensors], axis=dim))
def _from_numpy(arr):
    return FakeTensor(arr)
torch_mod.zeros = _zeros
torch_mod.cat = _cat
torch_mod.from_numpy = _from_numpy
sys.modules["torch"] = torch_mod

# ---------------- fake folder_paths ----------------
folder_paths_mod = types.ModuleType("folder_paths")
_OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fake_output")
os.makedirs(_OUTPUT_DIR, exist_ok=True)
_FAKE_LORAS = ["loraA.safetensors", "loraB.safetensors"]
def _get_output_directory():
    return _OUTPUT_DIR
def _get_filename_list(kind):
    if kind == "loras":
        return list(_FAKE_LORAS)
    return []
def _get_full_path(kind, name):
    if kind == "loras" and name in _FAKE_LORAS:
        return f"/home/claude/test/fake_loras/{name}"
    return None
folder_paths_mod.get_output_directory = _get_output_directory
folder_paths_mod.get_filename_list = _get_filename_list
folder_paths_mod.get_full_path = _get_full_path
sys.modules["folder_paths"] = folder_paths_mod

# ---------------- fake comfy package ----------------
comfy_mod = types.ModuleType("comfy")
comfy_mod.__path__ = []
sys.modules["comfy"] = comfy_mod

samplers_mod = types.ModuleType("comfy.samplers")
class _KSampler:
    SAMPLERS = ["euler", "dpmpp_2m", "er_sde"]
    SCHEDULERS = ["normal", "karras", "simple"]
samplers_mod.KSampler = _KSampler
sys.modules["comfy.samplers"] = samplers_mod
comfy_mod.samplers = samplers_mod

utils_mod = types.ModuleType("comfy.utils")
class _ProgressBar:
    def __init__(self, total):
        self.total = total
        self.n = 0
    def update(self, n):
        self.n += n
def _load_torch_file(path, safe_load=True):
    return {"fake_state_dict_for": path}
utils_mod.ProgressBar = _ProgressBar
utils_mod.load_torch_file = _load_torch_file
sys.modules["comfy.utils"] = utils_mod
comfy_mod.utils = utils_mod

mm_mod = types.ModuleType("comfy.model_management")
def _throw_if_interrupted():
    pass
mm_mod.throw_exception_if_processing_interrupted = _throw_if_interrupted
sys.modules["comfy.model_management"] = mm_mod
comfy_mod.model_management = mm_mod

sd_mod = types.ModuleType("comfy.sd")
_lora_apply_counter = {"n": 0}
class _FakeModel:
    def __init__(self, tag="model"):
        self.tag = tag
    def __repr__(self):
        return f"<Model {self.tag}>"
class _FakeClip:
    _encode_counter = {"n": 0}
    def __init__(self, tag="clip"):
        self.tag = tag
    def tokenize(self, text):
        return {"text": text}
    def encode_from_tokens(self, tokens, return_pooled=True):
        _FakeClip._encode_counter["n"] += 1
        return (f"COND[{tokens['text']}]", {"pooled": True})
    def encode_from_tokens_scheduled(self, tokens):
        # Mirrors the real API: already returns the fully-shaped
        # conditioning list, including whatever extra keys a given
        # architecture needs -- unlike a hand-rolled {"pooled_output":...}
        # dict, this stands in for "the complete, correct set of extras",
        # so a test can tell the difference between merely valid-shaped
        # and actually complete conditioning if it ever needs to.
        _FakeClip._encode_counter["n"] += 1
        return [[f"COND[{tokens['text']}]", {"pooled_output": {"pooled": True}, "extra_field_real_clip_would_add": True}]]
    def __repr__(self):
        return f"<Clip {self.tag}>"
def _load_lora_for_models(model, clip, sd, strength_model, strength_clip):
    _lora_apply_counter["n"] += 1
    new_model = _FakeModel(f"{getattr(model,'tag','model')}+lora({sd.get('fake_state_dict_for','?')},{strength_model})")
    new_clip = _FakeClip(f"{getattr(clip,'tag','clip')}+lora(clip={strength_clip})") if clip is not None else None
    return new_model, new_clip
sd_mod.load_lora_for_models = _load_lora_for_models
sys.modules["comfy.sd"] = sd_mod
comfy_mod.sd = sd_mod
lora_apply_counter = _lora_apply_counter
encode_counter = _FakeClip._encode_counter

# ---------------- fake nodes.common_ksampler ----------------
def _validate_conditioning(conds, label):
    """Mimic what real ComfyUI's conditioning-hooks code (cond_has_hooks /
    inner_set_conds) actually expects: a LIST of [cond_tensor, extra_dict]
    pairs. This is precisely what the real bug violated -- SweepAllInOne's
    encode() used to return clip.encode_from_tokens(tokens, return_pooled=True)
    directly, a bare (cond, pooled) 2-tuple, not wrapped in the required
    outer list. That shape mismatch is invisible to most of the sampling
    path (which mostly just forwards conds around without inspecting it),
    but real ComfyUI's hooks-checking code iterates conds expecting
    [cond, dict] pairs and indexes into what it assumes is the dict at
    position 1 -- given a bare (cond_tensor, pooled_tensor) tuple instead,
    that indexes into the *tensor* and raises "IndexError: index 1 is out
    of bounds for dimension 0 with size 1" for any batch-size-1 encode.
    Validating the shape here means this integration test actually catches
    that class of bug via the normal generate() code path, instead of only
    surfacing in a live ComfyUI run."""
    assert isinstance(conds, (list, tuple)), (
        f"{label}: conditioning must be a list of [cond, extra_dict] pairs, got {type(conds)}"
    )
    for entry in conds:
        assert isinstance(entry, (list, tuple)) and len(entry) >= 2, (
            f"{label}: each conditioning entry must be [cond, extra_dict], got {entry!r} -- "
            f"this is exactly the shape of the real IndexError bug (encode() returning a "
            f"bare (cond, pooled) tuple instead of [[cond, {{'pooled_output': pooled}}]])"
        )
        assert isinstance(entry[1], dict), (
            f"{label}: conditioning entry's second element must be a dict (extra info), got {type(entry[1])}"
        )


nodes_mod = types.ModuleType("nodes")
_sample_counter = {"n": 0}
def _common_ksampler(model, seed, steps, cfg, sampler_name, scheduler, positive, negative, latent, denoise=1.0):
    _validate_conditioning(positive, "positive")
    _validate_conditioning(negative, "negative")
    _sample_counter["n"] += 1
    h, w = latent["samples"].shape[1], latent["samples"].shape[2]
    arr = np.full((1, h, w, 4), fill_value=(seed % 97) / 97.0, dtype=np.float32)
    return ({"samples": FakeTensor(arr)},)
nodes_mod.common_ksampler = _common_ksampler
sys.modules["nodes"] = nodes_mod

FAKE_MODEL = _FakeModel("base")
FAKE_CLIP = _FakeClip("base")

class _FakeVAE:
    def decode(self, samples):
        h, w = samples.shape[1], samples.shape[2]
        arr = np.random.rand(1, h, w, 3).astype(np.float32)
        return FakeTensor(arr)

FAKE_VAE = _FakeVAE()

def make_fake_latent(h=8, w=8):
    return {"samples": FakeTensor(np.zeros((1, h, w, 4), dtype=np.float32))}

def new_fake_model(tag):
    return _FakeModel(tag)

def new_fake_clip(tag):
    return _FakeClip(tag)

sample_counter = _sample_counter
OUTPUT_DIR = _OUTPUT_DIR

EXPORTS = dict(
    FakeTensor=FakeTensor, FAKE_MODEL=FAKE_MODEL, FAKE_CLIP=FAKE_CLIP, FAKE_VAE=FAKE_VAE,
    make_fake_latent=make_fake_latent, new_fake_model=new_fake_model, new_fake_clip=new_fake_clip,
    OUTPUT_DIR=_OUTPUT_DIR, sample_counter=_sample_counter,
)
