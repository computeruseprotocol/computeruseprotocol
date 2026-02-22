"""CUP action execution layer.

Provides cross-platform action dispatch using element references
captured during tree walks.
"""

from cup.actions.executor import ActionExecutor, ActionResult

__all__ = ["ActionExecutor", "ActionResult"]
