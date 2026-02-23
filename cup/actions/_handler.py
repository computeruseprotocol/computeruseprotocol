"""Abstract base for platform-specific action handlers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from cup.actions.executor import ActionResult


class ActionHandler(ABC):
    """Interface for platform-specific action execution.

    Each platform implements this to translate CUP canonical actions
    (click, type, toggle, etc.) into native API calls.
    """

    @abstractmethod
    def execute(
        self,
        native_ref: Any,
        action: str,
        params: dict[str, Any],
    ) -> ActionResult:
        """Execute a CUP action using the native element reference.

        Args:
            native_ref: Platform-specific element reference from ref_map.
            action: CUP canonical action name (click, type, toggle, etc.).
            params: Action parameters (e.g., value for type, direction for scroll).

        Returns:
            ActionResult with success status and message.
        """
        ...

    @abstractmethod
    def press_keys(self, combo: str) -> ActionResult:
        """Send a keyboard combination to the focused window.

        Args:
            combo: Key combination string (e.g., "ctrl+s", "enter", "alt+f4").

        Returns:
            ActionResult with success status and message.
        """
        ...

    @abstractmethod
    def launch_app(self, name: str) -> ActionResult:
        """Launch an application by name.

        Implementations should discover installed apps, fuzzy-match the
        name, launch the best match, and confirm the window appeared.

        Args:
            name: Application name to launch (fuzzy matched).

        Returns:
            ActionResult with success status and message.
        """
        ...
