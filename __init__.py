from .sweep_all_in_one import (
    NODE_CLASS_MAPPINGS as _MAIN_CLASSES,
    NODE_DISPLAY_NAME_MAPPINGS as _MAIN_NAMES,
)
from .sweep_dimension import (
    NODE_CLASS_MAPPINGS as _DIM_CLASSES,
    NODE_DISPLAY_NAME_MAPPINGS as _DIM_NAMES,
)
from .sweep_dimension_zip import (
    NODE_CLASS_MAPPINGS as _ZIP_CLASSES,
    NODE_DISPLAY_NAME_MAPPINGS as _ZIP_NAMES,
)
from .sweep_dimension_selfcombine import (
    NODE_CLASS_MAPPINGS as _SELFCOMBINE_CLASSES,
    NODE_DISPLAY_NAME_MAPPINGS as _SELFCOMBINE_NAMES,
)
from .sweep_combination_expander import (
    NODE_CLASS_MAPPINGS as _EXPANDER_CLASSES,
    NODE_DISPLAY_NAME_MAPPINGS as _EXPANDER_NAMES,
)
from .sweep_dimension_extract import (
    NODE_CLASS_MAPPINGS as _EXTRACT_CLASSES,
    NODE_DISPLAY_NAME_MAPPINGS as _EXTRACT_NAMES,
)
from .sweep_dedupe_combos import (
    NODE_CLASS_MAPPINGS as _DEDUPE_CLASSES,
    NODE_DISPLAY_NAME_MAPPINGS as _DEDUPE_NAMES,
)
from .sweep_gather import (
    NODE_CLASS_MAPPINGS as _GATHER_CLASSES,
    NODE_DISPLAY_NAME_MAPPINGS as _GATHER_NAMES,
)
from .sweep_filename_sequencer import (
    NODE_CLASS_MAPPINGS as _FILENAME_CLASSES,
    NODE_DISPLAY_NAME_MAPPINGS as _FILENAME_NAMES,
)
from .sweep_grid_constructor import (
    NODE_CLASS_MAPPINGS as _GRIDCTOR_CLASSES,
    NODE_DISPLAY_NAME_MAPPINGS as _GRIDCTOR_NAMES,
)
from .sweep_upset_constructor import (
    NODE_CLASS_MAPPINGS as _UPSET_CLASSES,
    NODE_DISPLAY_NAME_MAPPINGS as _UPSET_NAMES,
)

NODE_CLASS_MAPPINGS = {
    **_MAIN_CLASSES,
    **_DIM_CLASSES,
    **_ZIP_CLASSES,
    **_SELFCOMBINE_CLASSES,
    **_EXPANDER_CLASSES,
    **_EXTRACT_CLASSES,
    **_DEDUPE_CLASSES,
    **_GATHER_CLASSES,
    **_FILENAME_CLASSES,
    **_GRIDCTOR_CLASSES,
    **_UPSET_CLASSES,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    **_MAIN_NAMES,
    **_DIM_NAMES,
    **_ZIP_NAMES,
    **_SELFCOMBINE_NAMES,
    **_EXPANDER_NAMES,
    **_EXTRACT_NAMES,
    **_DEDUPE_NAMES,
    **_GATHER_NAMES,
    **_FILENAME_NAMES,
    **_GRIDCTOR_NAMES,
    **_UPSET_NAMES,
}

# Tells ComfyUI to serve everything under ./web/ so the frontend extension
# (dynamic MODEL sockets on SweepDimension nodes) actually loads.
WEB_DIRECTORY = "web"

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
