"""CUP MCP Server — Computer Use Protocol tools for AI agents.

Exposes tools for UI accessibility tree capture, element search,
action execution, batch workflows, keyboard shortcuts, and screenshots.
"""

from __future__ import annotations

import json
from typing import Literal

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.utilities.types import Image

import cup
from cup.format import _format_line

mcp = FastMCP(
    name="cup",
    instructions=(
        "CUP (Computer Use Protocol) gives you access to the UI accessibility "
        "tree of the user's computer. Use get_accessibility_tree to see what's "
        "on screen, then execute_action or press_keys to interact with elements. "
        "Element IDs (e.g., 'e14') are ephemeral — they are only valid for the "
        "most recent tree snapshot. After any action, call get_accessibility_tree "
        "again to get fresh IDs.\n\n"
        "IMPORTANT: Choose the smallest scope for your needs:\n"
        "- 'overview' for situational awareness (~5-15 lines, no tree)\n"
        "- 'foreground' (default) to interact with the active window (~60-210 lines)\n"
        "- 'desktop' for desktop icons and widgets (~10-50 lines)\n"
        "- 'full' only when you need multiple windows at once (~300-1000+ lines)\n\n"
        "Actions (execute_action, press_keys) do NOT return a tree. "
        "You decide when to re-capture and at what scope.\n\n"
        "Use find_element to search for specific elements by role, name, or state "
        "without parsing the full tree text.\n\n"
        "Use batch_actions to execute multiple actions in a single call "
        "without re-capturing the tree between each step.\n\n"
        "Use screenshot to capture a visual snapshot of the screen when you need "
        "to see colors, images, or layout details that the accessibility tree "
        "doesn't capture."
    ),
)

# ---------------------------------------------------------------------------
# Session state (one per MCP server process)
# ---------------------------------------------------------------------------

_session: cup.Session | None = None


def _get_session() -> cup.Session:
    global _session
    if _session is None:
        _session = cup.Session()
    return _session


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool()
def get_accessibility_tree(
    scope: Literal["overview", "foreground", "desktop", "full"] = "foreground",
    app: str | None = None,
    max_depth: int = 0,
    detail: Literal["standard", "minimal", "full"] = "standard",
) -> str:
    """Capture the UI accessibility tree of the user's screen.

    Returns a structured text representation where each UI element has an ID
    (e.g., 'e14') that can be used with execute_action. The format shows:

        [id] role "name" @x,y wxh {states} [actions] val="value"

    Indentation shows the element hierarchy.

    Element IDs are ephemeral — they are only valid for THIS snapshot.
    After executing any action, you MUST call this again for fresh IDs.

    Scopes (choose the smallest scope that serves your need):

        overview   — Window list only. NO tree, NO element IDs. Near-instant.
                     ~5-15 lines. Use to check what apps are open.
        foreground — (default) Foreground window tree + window list in header.
                     ~60-210 lines. Use when you need to interact with the
                     active app's UI elements.
        desktop    — Desktop surface only (icons, widgets).
                     ~10-50 lines. Use to see/launch desktop items.
        full       — All windows tree. ~300-1000+ lines.
                     Rarely needed. Use only for multi-window coordination.

    Detail levels (control pruning aggressiveness):

        standard — (default) Prune unnamed generics, decorative images,
                   empty text, offscreen noise. Good balance of detail
                   and token efficiency.
        minimal  — Keep only interactive elements (with actions) and their
                   ancestors. Dramatically reduces token count for large trees.
        full     — No pruning at all. Every node from the raw tree is included.
                   Use when you need complete structural information.

    Args:
        scope: Capture scope (see above).
        app: Filter windows by title (only used with scope="full").
        max_depth: Maximum tree depth (0 = unlimited).
        detail: Pruning level (see above).
    """
    session = _get_session()
    depth = max_depth if max_depth > 0 else 999
    return session.capture(
        scope=scope,
        app=app if scope == "full" else None,
        max_depth=depth,
        compact=True,
        detail=detail,
    )


@mcp.tool()
def execute_action(
    element_id: str,
    action: str,
    value: str | None = None,
    direction: str | None = None,
) -> str:
    """Execute an action on a UI element identified by its ID.

    Use element IDs from the most recent get_accessibility_tree call.
    Only use actions that appear in the element's [actions] list.

    After execution, call get_accessibility_tree to see the updated UI.

    Supported actions:
        click      — Click/invoke the element
        rightclick — Right-click to open context menu
        doubleclick— Double-click the element
        toggle     — Toggle a checkbox or switch
        type       — Type text into a text field (pass text in 'value')
        setvalue   — Set element value programmatically (pass in 'value')
        select     — Select an item in a list/tree/tab
        expand     — Expand a collapsed element
        collapse   — Collapse an expanded element
        scroll     — Scroll a container (pass direction: up/down/left/right)
        increment  — Increment a slider/spinbutton
        decrement  — Decrement a slider/spinbutton
        focus      — Move keyboard focus to the element

    Args:
        element_id: Element ID from the tree (e.g., "e14").
        action: The action to perform (must be in the element's [actions]).
        value: Text for 'type' or 'setvalue' actions.
        direction: Direction for 'scroll' action (up/down/left/right).
    """
    session = _get_session()

    # Build params dict from the optional arguments
    params: dict = {}
    if value is not None:
        params["value"] = value
    if direction is not None:
        params["direction"] = direction

    result = session.execute(element_id, action, **params)

    return json.dumps({
        "success": result.success,
        "message": result.message,
        "error": result.error,
    })


@mcp.tool()
def press_keys(keys: str) -> str:
    """Send a keyboard shortcut to the currently focused window.

    After execution, call get_accessibility_tree to see the updated UI.

    Key format: modifier keys joined with '+'. Examples:
        "enter", "escape", "tab", "space"
        "ctrl+s", "ctrl+shift+p", "alt+f4"
        "f1", "f5", "delete", "backspace"
        Single characters: "a", "1", "/"

    Args:
        keys: Key combination string (e.g., "ctrl+s").
    """
    session = _get_session()
    result = session.press_keys(keys)

    return json.dumps({
        "success": result.success,
        "message": result.message,
        "error": result.error,
    })


@mcp.tool()
def find_element(
    role: str | None = None,
    name: str | None = None,
    state: str | None = None,
) -> str:
    """Search the last captured tree for elements matching criteria.

    Searches the pruned tree (same elements you see from
    get_accessibility_tree). If no tree has been captured yet,
    auto-captures the foreground window.

    All criteria are optional but at least one should be provided.
    When multiple criteria are given, ALL must match (AND logic).

    Match behavior:
        role  — Exact match (e.g., "button", "textbox", "link")
        name  — Case-insensitive substring (e.g., "Save" matches "Save As...")
        state — Exact match on a state (e.g., "focused", "disabled", "checked")

    Returns matching elements in compact format with their element IDs.
    Use these IDs with execute_action.

    Args:
        role: Filter by role (exact match).
        name: Filter by name (case-insensitive substring).
        state: Filter by state (exact match).
    """
    if role is None and name is None and state is None:
        return json.dumps({
            "success": False,
            "message": "",
            "error": "At least one search criterion (role, name, or state) must be provided.",
        })

    session = _get_session()
    matches = session.find_elements(role=role, name=name, state=state)

    if not matches:
        return json.dumps({
            "success": True,
            "message": "No matching elements found.",
            "matches": 0,
        })

    lines = [_format_line(node) for node in matches]
    return "\n".join([
        f"# {len(matches)} match{'es' if len(matches) != 1 else ''} found",
        "",
    ] + lines) + "\n"


@mcp.tool()
def batch_actions(
    actions: list[dict],
) -> str:
    """Execute a sequence of actions, stopping on first failure.

    Each action in the list is a dict with:

    Element actions (use element IDs from the last get_accessibility_tree):
        {"element_id": "e14", "action": "click"}
        {"element_id": "e5", "action": "type", "value": "hello"}
        {"element_id": "e3", "action": "scroll", "direction": "down"}

    Keyboard shortcuts (no element_id needed):
        {"action": "press_keys", "keys": "ctrl+s"}
        {"action": "press_keys", "keys": "enter"}

    Executes actions in order. If any action fails, execution stops
    and the results up to that point are returned.

    After execution, call get_accessibility_tree to see the updated UI.

    Args:
        actions: List of action spec dicts to execute in order.
    """
    if not actions:
        return json.dumps({
            "success": False,
            "message": "",
            "error": "No actions provided.",
        })

    session = _get_session()
    results = session.batch_execute(actions)

    summary = []
    all_success = True
    for i, result in enumerate(results):
        entry: dict = {
            "step": i + 1,
            "success": result.success,
            "message": result.message,
        }
        if result.error:
            entry["error"] = result.error
        summary.append(entry)
        if not result.success:
            all_success = False

    return json.dumps({
        "success": all_success,
        "executed": len(results),
        "total": len(actions),
        "results": summary,
    })


@mcp.tool()
def screenshot(
    region_x: int | None = None,
    region_y: int | None = None,
    region_w: int | None = None,
    region_h: int | None = None,
) -> Image | str:
    """Capture a screenshot of the screen and return it as a PNG image.

    By default captures the full primary monitor. Optionally specify a
    region to capture only part of the screen.

    Use this alongside get_accessibility_tree when you need visual context
    (e.g., to see colors, images, or layout that the tree doesn't capture).

    Args:
        region_x: Left edge of capture region in pixels.
        region_y: Top edge of capture region in pixels.
        region_w: Width of capture region in pixels.
        region_h: Height of capture region in pixels.
    """
    region_params = [region_x, region_y, region_w, region_h]
    has_any = any(v is not None for v in region_params)
    has_all = all(v is not None for v in region_params)

    if has_any and not has_all:
        return json.dumps({
            "success": False,
            "message": "",
            "error": "All region parameters (region_x, region_y, region_w, region_h) "
                     "must be provided together, or none at all.",
        })

    region = None
    if has_all:
        region = {"x": region_x, "y": region_y, "w": region_w, "h": region_h}

    session = _get_session()
    try:
        png_bytes = session.screenshot(region=region)
    except ImportError:
        return json.dumps({
            "success": False,
            "message": "",
            "error": "Screenshot support requires the 'mss' package. "
                     "Install with: pip install cup[screenshot]",
        })

    return Image(data=png_bytes, format="png")
