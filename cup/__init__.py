"""
CUP -- Computer Use Protocol.

Cross-platform accessibility tree capture in a unified format.

Quick start::

    import cup

    # Session is the primary API — capture + actions
    session = cup.Session()
    tree = session.capture(scope="overview")    # window list only
    tree = session.capture(scope="foreground")  # foreground tree + window header
    tree = session.capture(scope="desktop")     # desktop items
    result = session.execute("e14", "click")
    tree = session.capture(scope="foreground")  # re-capture after action

    # Convenience functions (use a default session internally)
    envelope = cup.get_tree()                   # full tree as CUP envelope dict
    envelope = cup.get_foreground_tree()        # foreground window only
    text = cup.get_compact()                    # compact text for LLM context
    text = cup.get_foreground_compact()         # foreground compact text
    text = cup.get_overview()                   # lightweight window list
"""

from __future__ import annotations

from typing import Any, Literal

from cup._router import detect_platform, get_adapter
from cup.actions import ActionExecutor, ActionResult
from cup.format import (
    Detail,
    build_envelope,
    prune_tree,
    serialize_compact,
    serialize_overview,
)

Scope = Literal["overview", "foreground", "desktop", "full"]

__all__ = [
    "get_tree",
    "get_foreground_tree",
    "get_compact",
    "get_foreground_compact",
    "get_overview",
    "Session",
    "Scope",
    "ActionResult",
    # Advanced / building blocks
    "get_adapter",
    "detect_platform",
    "build_envelope",
    "serialize_compact",
    "serialize_overview",
    "prune_tree",
]


# ---------------------------------------------------------------------------
# Default session — used by the convenience functions below
# ---------------------------------------------------------------------------

_default_session: Session | None = None


def _get_default_session() -> Session:
    global _default_session
    if _default_session is None:
        _default_session = Session()
    return _default_session


# ---------------------------------------------------------------------------
# Convenience functions (thin wrappers around Session)
# ---------------------------------------------------------------------------


def get_tree(*, max_depth: int = 999) -> dict:
    """Capture the full accessibility tree (all windows) as a CUP envelope dict."""
    return _get_default_session().capture(
        scope="full",
        max_depth=max_depth,
        compact=False,
    )


def get_foreground_tree(*, max_depth: int = 999) -> dict:
    """Capture the foreground window's tree as a CUP envelope dict."""
    return _get_default_session().capture(
        scope="foreground",
        max_depth=max_depth,
        compact=False,
    )


def get_compact(*, max_depth: int = 999) -> str:
    """Capture full tree and return CUP compact text (for LLM context)."""
    return _get_default_session().capture(
        scope="full",
        max_depth=max_depth,
        compact=True,
    )


def get_foreground_compact(*, max_depth: int = 999) -> str:
    """Capture foreground window and return CUP compact text (for LLM context)."""
    return _get_default_session().capture(
        scope="foreground",
        max_depth=max_depth,
        compact=True,
    )


def get_overview() -> str:
    """Get a compact window list (no tree walking). Near-instant."""
    return _get_default_session().capture(scope="overview", compact=True)


# ---------------------------------------------------------------------------
# Session — stateful tree capture with action execution
# ---------------------------------------------------------------------------


class Session:
    """A CUP session that captures trees with element references for action execution.

    Element IDs (e.g., "e14") are ephemeral — they are only valid for the
    most recent tree capture.  After executing any action, re-capture the
    tree to get fresh IDs.

    Example::

        session = cup.Session()
        overview = session.capture(scope="overview")    # what's running?
        tree = session.capture(scope="foreground")      # interact with app
        result = session.execute("e7", "click")
        tree = session.capture(scope="foreground")      # fresh IDs after action
    """

    def __init__(self, *, platform: str | None = None) -> None:
        self._adapter = get_adapter(platform)
        self._executor = ActionExecutor(self._adapter)
        self._last_tree: list[dict] | None = None
        self._last_raw_tree: list[dict] | None = None

    def capture(
        self,
        *,
        scope: Scope = "foreground",
        app: str | None = None,
        max_depth: int = 999,
        compact: bool = True,
        detail: Detail = "standard",
    ) -> str | dict:
        """Capture the accessibility tree.

        Args:
            scope: Capture scope:
                "overview"   — Window list only (no tree walking, near-instant)
                "foreground" — Foreground window tree + window list in header
                "desktop"    — Desktop surface tree only
                "full"       — All windows tree
            app: Filter windows by title (only for scope="full").
            max_depth: Maximum tree depth.
            compact: If True, return compact LLM text; if False, return
                     the full CUP envelope dict.
            detail: Pruning level ("standard", "minimal", or "full").

        Returns:
            Compact text string or CUP envelope dict.
        """
        sw, sh, scale = self._adapter.get_screen_info()

        # --- overview scope: no tree walking ---
        if scope == "overview":
            window_list = self._adapter.get_window_list()
            if compact:
                return serialize_overview(
                    window_list,
                    platform=self._adapter.platform_name,
                    screen_w=sw,
                    screen_h=sh,
                )
            return {
                "version": "0.1.0",
                "platform": self._adapter.platform_name,
                "screen": {"w": sw, "h": sh},
                "scope": "overview",
                "tree": [],
                "windows": window_list,
            }

        # --- scopes that require tree walking ---
        window_list = None

        if scope == "foreground":
            win = self._adapter.get_foreground_window()
            windows = [win]
            app_name = win["title"]
            app_pid = win["pid"]
            app_bundle_id = win.get("bundle_id")
            # Get window list for header awareness
            window_list = self._adapter.get_window_list()
        elif scope == "desktop":
            desktop_win = self._adapter.get_desktop_window()
            if desktop_win is None:
                # Fallback: return overview for platforms without desktop
                window_list = self._adapter.get_window_list()
                if compact:
                    return serialize_overview(
                        window_list,
                        platform=self._adapter.platform_name,
                        screen_w=sw,
                        screen_h=sh,
                    )
                return {
                    "version": "0.1.0",
                    "platform": self._adapter.platform_name,
                    "screen": {"w": sw, "h": sh},
                    "scope": "overview",
                    "tree": [],
                    "windows": window_list,
                }
            windows = [desktop_win]
            app_name = "Desktop"
            app_pid = desktop_win.get("pid")
            app_bundle_id = desktop_win.get("bundle_id")
        else:  # "full"
            windows = self._adapter.get_all_windows()
            if app:
                app_lower = app.lower()
                windows = [w for w in windows if app_lower in (w.get("title") or "").lower()]
            app_name = None
            app_pid = None
            app_bundle_id = None

        tree, stats, refs = self._adapter.capture_tree(
            windows,
            max_depth=max_depth,
        )
        self._executor.set_refs(refs)

        tools = None
        if hasattr(self._adapter, "get_last_tools"):
            tools = self._adapter.get_last_tools() or None

        envelope = build_envelope(
            tree,
            platform=self._adapter.platform_name,
            scope=scope,
            screen_w=sw,
            screen_h=sh,
            screen_scale=scale,
            app_name=app_name,
            app_pid=app_pid,
            app_bundle_id=app_bundle_id,
            tools=tools,
        )

        # Store raw tree for semantic search + pruned tree for compact output
        self._last_raw_tree = envelope["tree"]
        self._last_tree = prune_tree(envelope["tree"], detail=detail)

        if compact:
            return serialize_compact(
                envelope,
                window_list=window_list,
                detail=detail,
            )
        return envelope

    def execute(
        self,
        element_id: str,
        action: str,
        **params: Any,
    ) -> ActionResult:
        """Execute an action on an element from the last capture.

        Args:
            element_id: Element ID from the tree (e.g., "e14").
            action: CUP canonical action (click, type, toggle, etc.).
            **params: Action parameters (value, direction, etc.).
        """
        return self._executor.execute(element_id, action, params)

    def press_keys(self, combo: str) -> ActionResult:
        """Send a keyboard shortcut to the focused window.

        Args:
            combo: Key combination (e.g., "ctrl+s", "enter", "alt+f4").
        """
        return self._executor.press_keys(combo)

    def launch_app(self, name: str) -> ActionResult:
        """Launch an application by name.

        Fuzzy-matches against installed apps (e.g., "chrome" matches
        "Google Chrome", "code" matches "Visual Studio Code").
        Waits for the app window to appear before returning.

        Args:
            name: Application name (fuzzy matched).
        """
        return self._executor.launch_app(name)

    # -- find_elements -----------------------------------------------------

    def find_elements(
        self,
        *,
        query: str | None = None,
        role: str | None = None,
        name: str | None = None,
        state: str | None = None,
        limit: int = 5,
    ) -> list[dict]:
        """Search the last captured tree for matching elements.

        Searches the full unpruned tree with semantic role matching,
        fuzzy name matching, and relevance ranking.

        Args:
            query: Freeform semantic query (e.g., "play button", "search input").
            role: Role filter — exact CUP role or synonym (e.g., "search bar").
            name: Name filter — fuzzy token matching.
            state: State filter — exact match (e.g., "focused", "disabled").
            limit: Maximum results to return (default 5).

        Returns:
            List of matching CUP node dicts (without children), ranked by relevance.
        """
        if self._last_raw_tree is None:
            self.capture(scope="foreground", compact=True)

        from cup.search import search_tree

        results = search_tree(
            self._last_raw_tree,
            query=query,
            role=role,
            name=name,
            state=state,
            limit=limit,
        )
        return [r.node for r in results]

    # -- batch_execute -----------------------------------------------------

    def batch_execute(
        self,
        actions: list[dict[str, Any]],
    ) -> list[ActionResult]:
        """Execute a sequence of actions, stopping on first failure.

        Each action spec is a dict with either:
            {"element_id": "e14", "action": "click"}
            {"element_id": "e5", "action": "type", "value": "hello"}
            {"action": "press_keys", "keys": "ctrl+s"}
            {"action": "wait", "ms": 500}

        Returns:
            List of ActionResults — one per executed action.
            If an action fails, the list stops at that failure.
        """
        import time

        results: list[ActionResult] = []
        for spec in actions:
            action = spec.get("action", "")

            if action == "wait":
                ms = max(50, min(int(spec.get("ms", 500)), 5000))
                time.sleep(ms / 1000)
                result = ActionResult(success=True, message=f"Waited {ms}ms")
            elif action == "press_keys":
                keys = spec.get("keys", "")
                if not keys:
                    results.append(
                        ActionResult(
                            success=False,
                            message="",
                            error="press_keys action requires 'keys' parameter",
                        )
                    )
                    break
                result = self.press_keys(keys)
            else:
                element_id = spec.get("element_id", "")
                if not element_id:
                    results.append(
                        ActionResult(
                            success=False,
                            message="",
                            error=f"Element action '{action}' requires 'element_id' parameter",
                        )
                    )
                    break
                params = {k: v for k, v in spec.items() if k not in ("element_id", "action")}
                result = self.execute(element_id, action, **params)

            results.append(result)
            if not result.success:
                break

        return results

    # -- screenshot --------------------------------------------------------

    def screenshot(
        self,
        *,
        region: dict[str, int] | None = None,
    ) -> bytes:
        """Capture a screenshot and return PNG bytes.

        Requires the ``mss`` package: ``pip install cup[screenshot]``

        Args:
            region: Optional capture region {"x", "y", "w", "h"} in pixels.
                    If None, captures the full primary monitor.

        Returns:
            PNG image bytes.
        """
        try:
            import mss
            import mss.tools
        except ImportError:
            raise ImportError(
                "Screenshot support requires the 'mss' package. "
                "Install it with: pip install cup[screenshot]"
            ) from None

        with mss.mss() as sct:
            if region is not None:
                monitor = {
                    "left": region["x"],
                    "top": region["y"],
                    "width": region["w"],
                    "height": region["h"],
                }
            else:
                monitor = sct.monitors[1]  # primary monitor

            img = sct.grab(monitor)
            return mss.tools.to_png(img.rgb, img.size)
