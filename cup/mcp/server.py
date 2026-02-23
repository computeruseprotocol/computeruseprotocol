"""CUP MCP Server — Computer Use Protocol tools for AI agents.

Exposes simple, focused tools for UI tree capture, element search,
action execution, and screenshots.
"""

from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.utilities.types import Image

import cup
from cup.format import _format_line

mcp = FastMCP(
    name="cup",
    instructions=(
        "CUP (Computer Use Protocol) gives you access to the UI accessibility "
        "tree of the user's computer.\n\n"
        "WORKFLOW — follow this pattern:\n"
        "1. get_foreground to capture the active window's UI\n"
        "2. find_element to locate specific elements (PREFERRED over re-capturing)\n"
        "3. execute_action to interact (click, type, press_keys, etc.)\n"
        "4. Re-capture ONLY after actions change the UI\n\n"
        "TOOLS:\n"
        "- get_foreground() — active window tree + window list (most common)\n"
        "- get_tree(app) — specific app by title (when not in foreground)\n"
        "- get_overview() — just the window list, near-instant\n"
        "- get_desktop() — desktop icons and widgets\n"
        "- find_element(role/name/state) — search last tree without re-capturing\n"
        "- execute_action(action, ...) — interact with elements or press keys\n"
        "- launch_app(name) — launch an app by name with fuzzy matching\n"
        "- screenshot(region) — visual context when tree isn't enough\n\n"
        "IMPORTANT — minimize token usage:\n"
        "- Use find_element(name=...) to locate elements — NOT repeated tree captures\n"
        "- Use get_overview() to discover what apps are open\n"
        "- Use get_tree(app='...') to target a specific app\n"
        "- get_foreground() is your default starting point\n\n"
        "Element IDs (e.g., 'e14') are ephemeral — only valid for the most "
        "recent tree snapshot. After any action, re-capture before using IDs.\n\n"
        "Use execute_action(action='press_keys', keys='ctrl+s') for keyboard shortcuts.\n\n"
        "Use screenshot when you need visual context (colors, images, layout)."
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
# Tree capture tools
# ---------------------------------------------------------------------------


@mcp.tool()
def get_foreground() -> str:
    """Capture the foreground (active) window's accessibility tree.

    Returns a structured text representation where each UI element has an ID
    (e.g., 'e14') that can be used with execute_action. The format shows:

        [id] role "name" @x,y wxh {states} [actions] val="value"

    Indentation shows the element hierarchy.

    Also includes a window list in the header showing all open apps.
    This is the primary tool for interacting with the current app's UI.

    Element IDs are ephemeral — they are only valid for THIS snapshot.
    After executing any action, you MUST call this again for fresh IDs.
    """
    session = _get_session()
    return session.capture(
        scope="foreground",
        max_depth=999,
        compact=True,
        detail="standard",
    )


@mcp.tool()
def get_tree(app: str) -> str:
    """Capture a specific app's window accessibility tree by title.

    Use this when you need to interact with a window that is NOT in the
    foreground, or when you know the exact app you want by name.

    The 'app' parameter is a case-insensitive substring match against
    window titles (e.g., "Spotify", "Firefox", "VS Code").

    Returns the same compact format as get_foreground, with element IDs
    that can be used with execute_action.

    Element IDs are ephemeral — only valid for THIS snapshot.

    Args:
        app: Target app by window title (case-insensitive substring match).
    """
    session = _get_session()
    return session.capture(
        scope="full",
        app=app,
        max_depth=999,
        compact=True,
        detail="standard",
    )


@mcp.tool()
def get_desktop() -> str:
    """Capture the desktop surface (icons, widgets, shortcuts).

    Use this to see and interact with desktop items. Falls back to a
    window overview if the platform has no desktop concept.

    Returns the same compact format with element IDs for execute_action.

    Element IDs are ephemeral — only valid for THIS snapshot.
    """
    session = _get_session()
    return session.capture(
        scope="desktop",
        max_depth=999,
        compact=True,
        detail="standard",
    )


@mcp.tool()
def get_overview() -> str:
    """List all open windows. Near-instant, no tree walking.

    Returns a lightweight window list showing app names, PIDs, and bounds.
    No element IDs are returned (no tree walking is performed).

    Use this to quickly discover what apps are open before targeting
    a specific one with get_tree(app='...').
    """
    session = _get_session()
    return session.capture(scope="overview", compact=True)


# ---------------------------------------------------------------------------
# Action tools
# ---------------------------------------------------------------------------


@mcp.tool()
def execute_action(
    action: str,
    element_id: str | None = None,
    value: str | None = None,
    direction: str | None = None,
    keys: str | None = None,
) -> str:
    """Execute an action on a UI element or send a keyboard shortcut.

    IMPORTANT: Element IDs are only valid from the most recent tree capture
    (get_foreground, get_tree, etc.). After executing any action, re-capture
    for fresh IDs.

    Element actions (require element_id):
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

    Keyboard shortcut (no element_id needed):
        press_keys — Send a keyboard shortcut (pass combo in 'keys')
                     Examples: "enter", "ctrl+s", "ctrl+shift+p", "alt+f4"

    Args:
        action: The action to perform.
        element_id: Element ID from the tree (e.g., "e14"). Required for
                    all actions except press_keys.
        value: Text for 'type' or 'setvalue' actions.
        direction: Direction for 'scroll' action (up/down/left/right).
        keys: Key combination for 'press_keys' action (e.g., "ctrl+s").
    """
    session = _get_session()

    # Handle press_keys action
    if action == "press_keys":
        if not keys:
            return json.dumps(
                {
                    "success": False,
                    "message": "",
                    "error": "press_keys action requires the 'keys' parameter "
                    "(e.g., keys='ctrl+s').",
                }
            )
        result = session.press_keys(keys)
        return json.dumps(
            {
                "success": result.success,
                "message": result.message,
                "error": result.error,
            }
        )

    # All other actions require element_id
    if not element_id:
        return json.dumps(
            {
                "success": False,
                "message": "",
                "error": f"Action '{action}' requires the 'element_id' parameter.",
            }
        )

    # Build params dict from the optional arguments
    params: dict = {}
    if value is not None:
        params["value"] = value
    if direction is not None:
        params["direction"] = direction

    result = session.execute(element_id, action, **params)

    return json.dumps(
        {
            "success": result.success,
            "message": result.message,
            "error": result.error,
        }
    )


# ---------------------------------------------------------------------------
# Launch app tool
# ---------------------------------------------------------------------------


@mcp.tool()
def launch_app(name: str) -> str:
    """Launch an application by name.

    Fuzzy-matches the name against installed apps on the system.
    Examples: "chrome" → Google Chrome, "code" → Visual Studio Code,
    "notepad" → Notepad, "slack" → Slack.

    Waits for the app window to appear before returning success.

    After launching, use get_foreground() to capture the new app's UI tree.

    Args:
        name: Application name to launch (fuzzy matched against installed apps).
    """
    session = _get_session()
    result = session.launch_app(name)
    return json.dumps(
        {
            "success": result.success,
            "message": result.message,
            "error": result.error,
        }
    )


# ---------------------------------------------------------------------------
# Search tool
# ---------------------------------------------------------------------------


@mcp.tool()
def find_element(
    query: str | None = None,
    role: str | None = None,
    name: str | None = None,
    state: str | None = None,
) -> str:
    """Search the last captured tree for elements matching criteria.

    Searches the FULL tree (including elements not shown in compact output)
    with semantic matching and relevance ranking. Results are sorted by
    relevance — best matches first.

    If no tree has been captured yet in this session, auto-captures the
    foreground window.

    QUERY MODE (recommended):
        Pass a freeform ``query`` describing what you're looking for.
        The query is automatically parsed into role and name signals.

        Examples:
            query="the play button"     -> finds buttons with "play" in the name
            query="search input"        -> finds textbox/combobox/searchbox elements
            query="volume slider"       -> finds sliders with "volume" in the name
            query="Submit"              -> finds elements named "Submit"

    STRUCTURED MODE (backward compatible):
        Pass explicit role, name, and/or state filters.

        role  — CUP role or natural language (e.g., "button", "search bar", "input")
        name  — Fuzzy name match (token overlap, not just substring)
        state — Exact state match (e.g., "focused", "disabled", "checked")

    Both modes can be combined: query + state="focused" narrows to focused elements.

    Args:
        query: Freeform semantic query (e.g., "play button", "search input").
        role: Filter by role (exact CUP role or natural language synonym).
        name: Filter by name (fuzzy token matching).
        state: Filter by state (exact match).
    """
    if query is None and role is None and name is None and state is None:
        return json.dumps(
            {
                "success": False,
                "message": "",
                "error": "At least one search parameter (query, role, name, or state) must be provided.",
            }
        )

    session = _get_session()
    matches = session.find_elements(query=query, role=role, name=name, state=state)

    if not matches:
        return json.dumps(
            {
                "success": True,
                "message": "No matching elements found.",
                "matches": 0,
            }
        )

    lines = [_format_line(node) for node in matches]
    return (
        "\n".join(
            [
                f"# {len(matches)} match{'es' if len(matches) != 1 else ''} found",
                "",
            ]
            + lines
        )
        + "\n"
    )


# ---------------------------------------------------------------------------
# Screenshot
# ---------------------------------------------------------------------------


@mcp.tool()
def screenshot(
    region_x: int | None = None,
    region_y: int | None = None,
    region_w: int | None = None,
    region_h: int | None = None,
) -> Image:
    """Capture a screenshot of the screen and return it as a PNG image.

    By default captures the full primary monitor. Optionally specify a
    region to capture only part of the screen.

    Use this alongside tree capture tools when you need visual context
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
        return json.dumps(
            {
                "success": False,
                "message": "",
                "error": "All region parameters (region_x, region_y, region_w, region_h) "
                "must be provided together, or none at all.",
            }
        )

    region = None
    if has_all:
        region = {"x": region_x, "y": region_y, "w": region_w, "h": region_h}

    session = _get_session()
    try:
        png_bytes = session.screenshot(region=region)
    except ImportError:
        return json.dumps(
            {
                "success": False,
                "message": "",
                "error": "Screenshot support requires the 'mss' package. "
                "Install with: pip install cup[screenshot]",
            }
        )

    return Image(data=png_bytes, format="png")
