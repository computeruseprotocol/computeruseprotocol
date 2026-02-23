"""Platform auto-detection and adapter dispatch."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cup._base import PlatformAdapter


def detect_platform() -> str:
    """Return the current platform identifier."""
    if sys.platform == "win32":
        return "windows"
    elif sys.platform == "darwin":
        return "macos"
    elif sys.platform.startswith("linux"):
        return "linux"
    else:
        raise RuntimeError(f"Unsupported platform: {sys.platform}")


def get_adapter(platform: str | None = None) -> PlatformAdapter:
    """Return a fresh platform adapter instance.

    Each call creates and initializes a new adapter. Callers (e.g., Session)
    are responsible for holding onto the instance for reuse.

    Args:
        platform: Force a specific platform ('windows', 'macos', 'web').
                  If None, auto-detects from sys.platform.

    Raises:
        RuntimeError: If the platform is unsupported or dependencies are missing.
    """
    if platform is None:
        platform = detect_platform()

    if platform == "windows":
        from cup.platforms.windows import WindowsAdapter

        adapter = WindowsAdapter()
    elif platform == "macos":
        from cup.platforms.macos import MacosAdapter

        adapter = MacosAdapter()
    elif platform == "linux":
        from cup.platforms.linux import LinuxAdapter

        adapter = LinuxAdapter()
    elif platform == "web":
        from cup.platforms.web import WebAdapter

        adapter = WebAdapter()
    else:
        raise RuntimeError(
            f"No adapter available for platform '{platform}'. "
            f"Currently supported: windows, macos, linux, web."
        )

    adapter.initialize()
    return adapter
