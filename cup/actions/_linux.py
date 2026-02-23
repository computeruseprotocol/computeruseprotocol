"""Linux action handler — AT-SPI2-based action execution."""

from __future__ import annotations

from typing import Any

from cup.actions.executor import ActionResult
from cup.actions._handler import ActionHandler


class LinuxActionHandler(ActionHandler):
    """Execute CUP actions on Linux via AT-SPI2.

    Not yet implemented — contributions welcome:
    https://github.com/k4cper-g/computer-use-protocol
    """

    def execute(
        self, native_ref: Any, action: str, params: dict[str, Any],
    ) -> ActionResult:
        return ActionResult(
            success=False, message="",
            error=f"Linux action '{action}' is not yet implemented",
        )

    def press_keys(self, combo: str) -> ActionResult:
        return ActionResult(
            success=False, message="",
            error=f"Linux press_keys '{combo}' is not yet implemented",
        )

    def launch_app(self, name: str) -> ActionResult:
        return ActionResult(
            success=False, message="",
            error=f"Linux launch_app '{name}' is not yet implemented",
        )
