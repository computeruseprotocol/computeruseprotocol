"""
CUP -- Computer Use Protocol.

Cross-platform accessibility tree capture in a unified format.

Quick start::

    import cup

    # Get the full tree as a CUP envelope (dict)
    envelope = cup.get_tree()

    # Get just the foreground window
    envelope = cup.get_foreground_tree()

    # Get compact text for LLM consumption
    text = cup.get_compact()

    # Get compact text for foreground only
    text = cup.get_foreground_compact()
"""

from __future__ import annotations

from cup.format import build_envelope, serialize_compact, prune_tree
from cup._router import get_adapter, detect_platform

__all__ = [
    "get_tree",
    "get_foreground_tree",
    "get_compact",
    "get_foreground_compact",
    # Advanced / building blocks
    "get_adapter",
    "detect_platform",
    "build_envelope",
    "serialize_compact",
    "prune_tree",
]


def _capture(foreground: bool, max_depth: int = 999) -> dict:
    """Internal: capture tree and wrap in CUP envelope."""
    adapter = get_adapter()
    sw, sh, scale = adapter.get_screen_info()

    if foreground:
        win = adapter.get_foreground_window()
        windows = [win]
        app_name = win["title"]
        app_pid = win["pid"]
        app_bundle_id = win.get("bundle_id")
    else:
        windows = adapter.get_all_windows()
        app_name = None
        app_pid = None
        app_bundle_id = None

    tree, stats = adapter.capture_tree(windows, max_depth=max_depth)

    envelope = build_envelope(
        tree,
        platform=adapter.platform_name,
        screen_w=sw,
        screen_h=sh,
        screen_scale=scale,
        app_name=app_name,
        app_pid=app_pid,
        app_bundle_id=app_bundle_id,
    )
    return envelope


def get_tree(*, max_depth: int = 999) -> dict:
    """Capture the full accessibility tree (all windows) as a CUP envelope dict."""
    return _capture(foreground=False, max_depth=max_depth)


def get_foreground_tree(*, max_depth: int = 999) -> dict:
    """Capture the foreground window's tree as a CUP envelope dict."""
    return _capture(foreground=True, max_depth=max_depth)


def get_compact(*, max_depth: int = 999) -> str:
    """Capture full tree and return CUP compact text (for LLM context)."""
    envelope = _capture(foreground=False, max_depth=max_depth)
    return serialize_compact(envelope)


def get_foreground_compact(*, max_depth: int = 999) -> str:
    """Capture foreground window and return CUP compact text (for LLM context)."""
    envelope = _capture(foreground=True, max_depth=max_depth)
    return serialize_compact(envelope)
