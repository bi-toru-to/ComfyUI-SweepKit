"""
SweepFilenameSequencer — one filename per combo, ready to pair against a
stock SaveImage node fed with a matching-length IMAGE List: connect this
node's `filenames` output through List-Utils' "PyList To List" into
SaveImage's filename_prefix, and connect VAEDecode's IMAGE List output
directly into SaveImage's images (no PyList conversion needed there — it's
already a native per-item List) — since neither has INPUT_IS_LIST,
ComfyUI's executor loops SaveImage once per index, saving each image
under its own correctly-paired name.

Always produces exactly len(combo_records) filenames, even when
SweepDedupeCombos + SweepGather means several of them point at
byte-identical images — dedup saves sampling time, not file count; every
combo you asked for still gets its own named file.
"""

from .sweep_core import build_filenames


class SweepFilenameSequencer:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "combo": (
                    "SWEEP_COMBO",
                    {
                        "tooltip": "Connect SweepCombinationExpander's 'combo' output.",
                    },
                ),
                "filename_prefix": (
                    "STRING",
                    {
                        "default": "SweepKit",
                        "tooltip": "Top folder of every generated path (sanitized; blank = SweepKit). Feed the output through PyList To List into SaveImage's filename_prefix.",
                    },
                ),
                "include_combo_index": (
                    "BOOLEAN",
                    {
                        "default": True,
                        "tooltip": "Prefix a zero-padded running number — guarantees every filename is unique regardless of which dimensions are active.",
                    },
                ),
            },
        }

    RETURN_TYPES = ("PYLIST",)
    RETURN_NAMES = ("filenames",)
    FUNCTION = "build"
    CATEGORY = "SweepKit/Modular"

    def build(self, combo, filename_prefix, include_combo_index):
        return (build_filenames(combo["dimensions"], combo["combo_records"], filename_prefix, include_combo_index),)


NODE_CLASS_MAPPINGS = {
    "SweepFilenameSequencer": SweepFilenameSequencer,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SweepFilenameSequencer": "Sweep Filename Sequencer",
}
