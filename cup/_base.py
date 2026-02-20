"""Abstract base for platform adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class PlatformAdapter(ABC):
    """Interface that each platform tree-capture backend must implement.

    Subclasses handle all platform-specific initialization, window
    enumeration, tree walking, and CUP node construction.  The router
    calls only the methods defined here.
    """

    # ---- identity --------------------------------------------------------

    @property
    @abstractmethod
    def platform_name(self) -> str:
        """Return the platform identifier used in CUP envelopes.

        Must be one of: 'windows', 'macos', 'linux', 'web', 'android', 'ios'.
        """
        ...

    # ---- lifecycle -------------------------------------------------------

    @abstractmethod
    def initialize(self) -> None:
        """Perform any one-time setup (COM init, pyobjc bootstrap, etc.).

        Called once before the first capture.  Implementations should be
        idempotent (safe to call multiple times).
        """
        ...

    # ---- screen ----------------------------------------------------------

    @abstractmethod
    def get_screen_info(self) -> tuple[int, int, float]:
        """Return (width, height, scale_factor) of the primary display."""
        ...

    # ---- window enumeration ----------------------------------------------

    @abstractmethod
    def get_foreground_window(self) -> dict[str, Any]:
        """Return metadata about the foreground/focused window.

        Must return a dict with at least:
            {
                "handle": <platform-specific window handle/ref>,
                "title": str,
                "pid": int | None,
                "bundle_id": str | None,
            }
        """
        ...

    @abstractmethod
    def get_all_windows(self) -> list[dict[str, Any]]:
        """Return metadata dicts for all visible top-level windows.

        Same dict shape as get_foreground_window().
        """
        ...

    # ---- tree capture ----------------------------------------------------

    @abstractmethod
    def capture_tree(
        self,
        windows: list[dict[str, Any]],
        *,
        max_depth: int = 999,
    ) -> tuple[list[dict], dict]:
        """Walk the accessibility tree for the given windows.

        Args:
            windows: List of window metadata dicts (from get_foreground_window
                     or get_all_windows).
            max_depth: Maximum tree depth to walk.

        Returns:
            (tree_roots, stats) where:
                tree_roots: list of CUP node dicts (the "tree" field of the envelope)
                stats: dict with at least {"nodes": int, "max_depth": int}
        """
        ...
