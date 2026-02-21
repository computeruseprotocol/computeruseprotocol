"""Platform auto-detection and adapter dispatch."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cup._base import PlatformAdapter

_adapter_instance: PlatformAdapter | None = None


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
    """Return the appropriate platform adapter, creating it if needed.

    Args:
        platform: Force a specific platform ('windows', 'macos', 'web').
                  If None, auto-detects from sys.platform.

    Raises:
        RuntimeError: If the platform is unsupported or dependencies are missing.
    """
    global _adapter_instance

    if platform is None:
        platform = detect_platform()

    # Return cached instance if it matches
    if _adapter_instance is not None and _adapter_instance.platform_name == platform:
        return _adapter_instance

    if platform == "windows":
        from cup.platforms.windows import WindowsAdapter
        _adapter_instance = WindowsAdapter()
    elif platform == "macos":
        from cup.platforms.macos import MacosAdapter
        _adapter_instance = MacosAdapter()
    elif platform == "linux":
        from cup.platforms.linux import LinuxAdapter
        _adapter_instance = LinuxAdapter()
    elif platform == "web":
        from cup.platforms.web import WebAdapter
        _adapter_instance = WebAdapter()
    else:
        raise RuntimeError(
            f"No adapter available for platform '{platform}'. "
            f"Currently supported: windows, macos, linux, web."
        )

    _adapter_instance.initialize()
    return _adapter_instance
