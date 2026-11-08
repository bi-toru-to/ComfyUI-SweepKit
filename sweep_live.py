"""
Live sweeps: when the browser runs a Plan-driven workflow one image at a time
(see web/sweepkit_live.js), Sweep Collect runs once per image. This module keeps
what it has gathered so far between those runs, keyed by a session id the
browser invents for each sweep, so Collect can show the grid so far after every
image and write the final grids and run list after the last one.

Sessions live in memory only. A sweep that is cancelled part-way leaves its
session behind until newer ones push it out (at most MAX_SESSIONS are kept).

A finished sweep's images are kept too (the last MAX_KEPT sweeps), so that when
only Sweep Collect's own settings change (grid axes, cell size...) the browser
can ask Collect to rebuild from them instead of sampling every image again.
ComfyUI's cache can't do that for a live sweep: each image is a separate run,
and by default it frees results of runs other than the latest.
"""

from __future__ import annotations

import os
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

import folder_paths

from .sweep_core import build_filenames, next_versioned_path
from .sweep_image import GridSpec, LiveGrid, resolve_axes, tensor_to_pil

MAX_SESSIONS = 4
MAX_KEPT = 2  # finished sweeps whose images stay in memory for a rebuild


@dataclass
class LiveSession:
    """Everything one live sweep has gathered so far."""

    dims_sorted: list
    records: list
    spec: GridSpec
    keep_images: bool  # keep full images (for the final grids), not just thumbnails
    filenames: list[str] | None  # relative save path of every image, or None when not saving
    preview: LiveGrid | None = None
    images: dict[tuple, Any] = field(default_factory=dict)
    by_cursor: dict[int, Any] = field(default_factory=dict)  # every image, for a later rebuild
    saved: dict[int, str] = field(default_factory=dict)
    prefix: str = ""
    seen: set[int] = field(default_factory=set)

    @classmethod
    def start(cls, dims_sorted, records, spec, prefix, keep_images, save_individuals):
        axes = resolve_axes(dims_sorted, spec) if dims_sorted else None
        return cls(
            dims_sorted=dims_sorted,
            records=records,
            spec=spec,
            keep_images=keep_images,
            filenames=build_filenames(dims_sorted, records, prefix, True) if save_individuals else None,
            preview=LiveGrid(dims_sorted, spec, axes) if axes else None,
            prefix=prefix,
        )

    @property
    def done(self) -> bool:
        return len(self.seen) >= len(self.records)

    def add(self, cursor: int, image: Any, output_dir: str) -> None:
        """Record image number `cursor`: keep it, save it, add it to the preview."""
        idx_by_dim = self.records[cursor]["idx_by_dim"]
        if self.preview is not None:
            self.preview.add(idx_by_dim, image)
        if self.keep_images:
            self.images[tuple(idx_by_dim[d["index"]] for d in self.dims_sorted)] = image
        self.by_cursor[cursor] = image
        if self.filenames is not None:
            directory, name = os.path.split(os.path.join(output_dir, self.filenames[cursor]))
            path = next_versioned_path(directory, name)
            tensor_to_pil(image).save(path)
            self.saved[cursor] = path
        self.seen.add(cursor)

    def saved_paths(self) -> list[str | None]:
        """The saved file of every image in order (None where nothing was saved)."""
        if self.filenames is None:
            return []
        return [self.saved.get(i) for i in range(len(self.records))]

    def preview_file(self, session_id: str) -> tuple[dict[str, str] | None, Any]:
        """Write the grid so far to ComfyUI's temp folder. Returns its entry for the
        node's `ui` and the image itself (both None before there is a grid)."""
        frame = self.preview.render() if self.preview is not None else None
        if frame is None:
            return None, None
        name = f"sweepkit_live_{''.join(c for c in session_id if c.isalnum())[:40] or 'x'}.png"
        frame.save(os.path.join(folder_paths.get_temp_directory(), name))
        return {"filename": name, "subfolder": "", "type": "temp"}, frame


_SESSIONS: OrderedDict[str, LiveSession] = OrderedDict()


def get_session(session_id: str, make) -> LiveSession:
    """The session with this id, created by `make()` on first use. The least
    recently used sessions beyond MAX_SESSIONS are dropped."""
    session = _SESSIONS.pop(session_id, None) or make()
    _SESSIONS[session_id] = session
    while len(_SESSIONS) > MAX_SESSIONS:
        _SESSIONS.popitem(last=False)
    return session


def finish_session(session_id: str) -> None:
    """Close a sweep whose last image has arrived, keeping its images for a rebuild."""
    session = _SESSIONS.pop(session_id, None)
    if session is None:
        return
    _KEPT.pop(session_id, None)
    _KEPT[session_id] = KeptSweep(
        images=[session.by_cursor[i] for i in range(len(session.records))],
        saved=session.saved_paths(),
        prefix=session.prefix,
        count=len(session.records),
    )
    while len(_KEPT) > MAX_KEPT:
        _KEPT.popitem(last=False)


@dataclass
class KeptSweep:
    """The images (in combination order) and saved files of a finished sweep."""

    images: list[Any]
    saved: list[str | None]
    prefix: str
    count: int


_KEPT: OrderedDict[str, KeptSweep] = OrderedDict()


def kept_sweep(session_id: str) -> KeptSweep | None:
    return _KEPT.get(session_id)


def session_key(session_id: str, node_id: Any) -> str:
    """Sessions are per Sweep Collect node, so two Collects reading one Plan keep apart."""
    return f"{session_id}#{node_id}" if node_id not in (None, "") else str(session_id)
