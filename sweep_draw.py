"""
Text and canvas helpers for drawing grids and UpSet matrices.

Pure PIL: no torch or comfy imports, so the pure-logic tests can cover
them. Used by sweep_image.py and sweep_upset_constructor.py.
"""

from __future__ import annotations

from typing import Any, Sequence

# Largest grid/matrix canvas any node will build (100 megapixels is about
# 300 MB as RGB plus 1.2 GB as the float32 IMAGE output).
MAX_CANVAS_PIXELS = 100_000_000


def truncate_text_to_width(text: Any, font: Any, max_width: int, draw: Any) -> str:
    """Pixel-width-aware truncation (with ellipsis), as opposed to a fixed
    character count — the available space for a label is generous and
    content-dependent (see the grid/matrix constructors), so a fixed char
    count would either waste the extra room or still overflow it
    depending on content and font_size. Shared by SweepGridConstructor and
    SweepUpsetConstructor so their label handling can't drift apart."""
    text = str(text)
    if max_width <= 0:
        return ""
    if draw.textbbox((0, 0), text, font=font)[2] <= max_width:
        return text
    # Binary search for the longest prefix that fits with the ellipsis: the width
    # only grows with length, and trimming one character at a time took 15 s on a
    # 3,000-character word.
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if draw.textbbox((0, 0), text[:mid] + "…", font=font)[2] <= max_width:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo] + "…"


def wrap_text_to_width(text: Any, font: Any, max_width: int, draw: Any, max_lines: int = 4) -> list[str]:
    """Word-wrap text onto multiple lines, each fitting within max_width
    (measured in real pixels via draw.textbbox, not a fixed character
    count), truncating the last line with an ellipsis if it still doesn't
    fit within max_lines. Shared by SweepGridConstructor and
    SweepUpsetConstructor so their label handling can't drift apart."""
    words = str(text).split(" ")
    lines, cur = [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if draw.textbbox((0, 0), trial, font=font)[2] <= max_width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        # Always mark the cut, even when the last kept line itself fits.
        lines[-1] = truncate_text_to_width(lines[-1] + "…", font, max_width, draw)
    return lines


# A grid or matrix title (often a whole prompt) wraps onto at most this many
# lines, and never makes the image wider than its own content (or this width,
# for a very narrow grid).
TITLE_MAX_LINES = 3
MIN_TITLE_WIDTH = 480


def wrap_title(text: Any, font: Any, max_width: int, draw: Any, max_lines: int = TITLE_MAX_LINES) -> list[str]:
    """Title lines that each fit max_width. The first paragraph (before a
    newline) gets up to max_lines; later paragraphs, such as the short
    'X: seed   Y: cfg' caption, get one line each. Overlong lines end in an
    ellipsis, so a 2,000-character prompt can't stretch the image."""
    lines: list[str] = []
    for n, paragraph in enumerate(str(text).split("\n")):
        for line in wrap_text_to_width(paragraph, font, max_width, draw, max_lines=max_lines if n == 0 else 1):
            lines.append(truncate_text_to_width(line, font, max_width, draw))
    return lines


def check_canvas_size(width: int, height: int, node_tag: str) -> None:
    """Refuse to allocate a grid/matrix canvas above MAX_CANVAS_PIXELS.
    Called before Image.new so an oversized grid fails with advice instead
    of exhausting RAM (the canvas is held as RGB, then again as a float32
    tensor for the node's IMAGE output: ~15 bytes per pixel in total)."""
    pixels = width * height
    if pixels > MAX_CANVAS_PIXELS:
        raise ValueError(
            f"[{node_tag}] grid image would be {width}x{height} ({pixels / 1e6:.0f} MP), over the "
            f"{MAX_CANVAS_PIXELS / 1e6:.0f} MP limit. Use cell_mode='fit' with a smaller cell_size, "
            f"or set another dimension as grid_title_dim so it splits into more, smaller grids."
        )


def padded_batch_size(sizes: Sequence[tuple[int, int]]) -> tuple[int, int]:
    """(width, height) that every image in a batch must be padded to so they
    can be stacked into one IMAGE tensor without stretching any of them."""
    return max(w for w, _ in sizes), max(h for _, h in sizes)


def pad_image(pil_img: Any, width: int, height: int, background: tuple[int, int, int] = (16, 16, 16)) -> Any:
    """Place pil_img at the top-left of a width x height canvas filled with
    the grid background colour (no resizing, so nothing is distorted)."""
    from PIL import Image

    if pil_img.size == (width, height):
        return pil_img
    canvas = Image.new("RGB", (width, height), background)
    canvas.paste(pil_img, (0, 0))
    return canvas


def font_size_for_char_width(target_char_width_px: float, sample_px: int = 200) -> int:
    """Given a target average-character pixel width, return the find_font()
    pixel size that achieves it -- measured against whatever font
    find_font() actually resolves to (rather than assuming a fixed
    width/size ratio), so the mapping stays correct across whatever font
    is actually available in a given environment. Used to size grid/matrix
    text relative to the ACTUAL rendered cell width rather than a fixed
    pixel count, so cell_mode='original' (whose real cell size can differ
    wildly from the nominal cell_size widget) doesn't end up with text
    that's disproportionately tiny or huge next to the images.
    """
    from PIL import Image, ImageDraw

    sample_font = find_font(sample_px)
    scratch = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    sample_text = "AaMg0Wx1"
    w = scratch.textbbox((0, 0), sample_text, font=sample_font)[2]
    ratio = (w / len(sample_text)) / sample_px if w > 0 else 0.6
    if ratio <= 0:
        ratio = 0.6
    return max(6, round(target_char_width_px / ratio))


def find_font(size: int) -> Any:
    from PIL import ImageFont

    candidates = [
        "arial.ttf",
        "Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "C:\\Windows\\Fonts\\arial.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()
