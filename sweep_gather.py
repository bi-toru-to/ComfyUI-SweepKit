"""
SweepGather — result[i] = source[indices[i]]. The one primitive
List-Utils itself doesn't have (Get By Index reads a single element;
this reads a whole new list's worth of them, in whatever order you ask
for, including repeats). Generic enough that it's worth a look as a
List-Utils PR rather than staying pack-specific — nothing here is
specific to any model.
"""

from .sweep_core import gather


class SweepGather:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "source": (
                    "PYLIST",
                    {
                        "forceInput": True,
                        "tooltip": "The list to read from.",
                    },
                ),
                "indices": (
                    "PYLIST",
                    {
                        "forceInput": True,
                        "tooltip": "Integer indices into source — result[i] = source[indices[i]]. Out-of-range indices raise immediately.",
                    },
                ),
            },
        }

    RETURN_TYPES = ("PYLIST",)
    RETURN_NAMES = ("result",)
    FUNCTION = "build"
    CATEGORY = "SweepKit/Modular"

    def build(self, source, indices):
        return (gather(list(source), list(indices)),)


NODE_CLASS_MAPPINGS = {
    "SweepGather": SweepGather,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SweepGather": "Sweep Gather",
}
