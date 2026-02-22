"""macOS action handler — AXUIElement-based action execution."""

from __future__ import annotations

from typing import Any

from cup.actions.executor import ActionResult
from cup.actions._handler import ActionHandler


class MacosActionHandler(ActionHandler):
    """Execute CUP actions on macOS via AXUIElement API.

    Not yet implemented — contributions welcome.
    """

    def execute(
        self, native_ref: Any, action: str, params: dict[str, Any],
    ) -> ActionResult:
        return ActionResult(
            success=False, message="",
            error="macOS action execution is not yet implemented",
        )

    def press_keys(self, combo: str) -> ActionResult:
        return ActionResult(
            success=False, message="",
            error="macOS keyboard input is not yet implemented",
        )
