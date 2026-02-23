"""Action executor — dispatches CUP actions to platform-specific handlers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from cup._base import PlatformAdapter
    from cup.actions._handler import ActionHandler


VALID_ACTIONS = frozenset(
    {
        "click",
        "collapse",
        "decrement",
        "dismiss",
        "doubleclick",
        "expand",
        "focus",
        "increment",
        "longpress",
        "press_keys",
        "rightclick",
        "scroll",
        "select",
        "setvalue",
        "toggle",
        "type",
    }
)


@dataclass
class ActionResult:
    """Result of an action execution."""

    success: bool
    message: str
    error: str | None = None


def _get_action_handler(platform_name: str) -> ActionHandler:
    """Lazily import and instantiate the action handler for the given platform."""
    if platform_name == "windows":
        from cup.actions._windows import WindowsActionHandler

        return WindowsActionHandler()
    elif platform_name == "macos":
        from cup.actions._macos import MacosActionHandler

        return MacosActionHandler()
    elif platform_name == "linux":
        from cup.actions._linux import LinuxActionHandler

        return LinuxActionHandler()
    elif platform_name == "web":
        from cup.actions._web import WebActionHandler

        return WebActionHandler()
    else:
        raise RuntimeError(
            f"No action handler for platform '{platform_name}'. "
            f"Supported: windows, macos, linux, web"
        )


class ActionExecutor:
    """Cross-platform action executor using element references from tree capture.

    Usage::

        executor = ActionExecutor(adapter)
        tree, stats, refs = adapter.capture_tree(windows)
        executor.set_refs(refs)
        result = executor.execute("e14", "click")
    """

    def __init__(self, adapter: PlatformAdapter) -> None:
        self._adapter = adapter
        self._refs: dict[str, Any] = {}
        self._handler: ActionHandler = _get_action_handler(adapter.platform_name)

    def set_refs(self, refs: dict[str, Any]) -> None:
        """Replace element references with a fresh set from capture_tree()."""
        self._refs = refs

    def execute(
        self,
        element_id: str,
        action: str,
        params: dict[str, Any] | None = None,
    ) -> ActionResult:
        """Execute a CUP action on an element by its ID.

        Args:
            element_id: Element ID from the tree (e.g., "e14").
            action: CUP canonical action name.
            params: Optional parameters (value, direction, etc.).
        """
        if action not in VALID_ACTIONS:
            return ActionResult(
                success=False,
                message="",
                error=f"Unknown action '{action}'. Valid: {sorted(VALID_ACTIONS)}",
            )

        # press_keys does not require an element reference
        if action == "press_keys":
            keys = (params or {}).get("keys", "")
            if not keys:
                return ActionResult(
                    success=False,
                    message="",
                    error="Action 'press_keys' requires a 'keys' parameter",
                )
            return self.press_keys(keys)

        if element_id not in self._refs:
            return ActionResult(
                success=False,
                message="",
                error=f"Element '{element_id}' not found in current tree snapshot",
            )

        # Validate required parameters
        if action in ("type", "setvalue") and "value" not in (params or {}):
            return ActionResult(
                success=False,
                message="",
                error=f"Action '{action}' requires a 'value' parameter",
            )
        if action == "scroll":
            direction = (params or {}).get("direction")
            if direction not in ("up", "down", "left", "right"):
                return ActionResult(
                    success=False,
                    message="",
                    error=f"Action 'scroll' requires 'direction' "
                    f"(up/down/left/right), got: {direction!r}",
                )

        native_ref = self._refs[element_id]
        try:
            return self._handler.execute(native_ref, action, params or {})
        except Exception as exc:
            return ActionResult(success=False, message="", error=str(exc))

    def press_keys(self, combo: str) -> ActionResult:
        """Send a keyboard shortcut (e.g., 'ctrl+s', 'enter')."""
        try:
            return self._handler.press_keys(combo)
        except Exception as exc:
            return ActionResult(success=False, message="", error=str(exc))

    def launch_app(self, name: str) -> ActionResult:
        """Launch an application by name with fuzzy matching."""
        try:
            return self._handler.launch_app(name)
        except Exception as exc:
            return ActionResult(success=False, message="", error=str(exc))
