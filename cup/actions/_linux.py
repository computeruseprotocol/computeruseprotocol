"""Linux action handler — AT-SPI2-based action execution."""

from __future__ import annotations

from typing import Any

from cup.actions.executor import ActionResult
from cup.actions._handler import ActionHandler


class LinuxActionHandler(ActionHandler):
    """Execute CUP actions on Linux via AT-SPI2.

    Not yet implemented — contributions welcome.
    """

    def execute(
        self, native_ref: Any, action: str, params: dict[str, Any],
    ) -> ActionResult:
        return ActionResult(
            success=False, message="",
            error="Linux action execution is not yet implemented",
        )

    def press_keys(self, combo: str) -> ActionResult:
        return ActionResult(
            success=False, message="",
            error="Linux keyboard input is not yet implemented",
        )
