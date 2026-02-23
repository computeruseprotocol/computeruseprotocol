"""
Web platform adapter for CUP via Chrome DevTools Protocol (CDP).

Connects to a Chromium browser running with --remote-debugging-port,
captures the accessibility tree via Accessibility.getFullAXTree(),
and optionally discovers WebMCP tools from the page context.

Usage:
    # Launch Chrome with debugging enabled:
    chrome --remote-debugging-port=9222

    # Capture via CLI:
    python -m cup --platform web --compact

    # Or via API:
    import cup
    envelope = cup.get_tree(platform="web")

Dependencies:
    pip install websocket-client
"""

from __future__ import annotations

import http.client
import itertools
import json
import os
import threading
from typing import Any

import websocket  # websocket-client

from cup._base import PlatformAdapter

# ---------------------------------------------------------------------------
# CDP Transport
# ---------------------------------------------------------------------------

_msg_id_lock = threading.Lock()
_msg_id_counter = itertools.count(1)


def _cdp_get_targets(host: str, port: int) -> list[dict]:
    """Fetch the list of CDP targets (browser tabs) via HTTP."""
    conn = http.client.HTTPConnection(host, port, timeout=5)
    try:
        conn.request("GET", "/json")
        resp = conn.getresponse()
        data = resp.read().decode("utf-8")
        return json.loads(data)
    finally:
        conn.close()


def _cdp_connect(ws_url: str, host: str | None = None) -> websocket.WebSocket:
    """Open a synchronous websocket connection to a CDP target.

    If *host* is given, the hostname in *ws_url* is replaced so that
    we always connect via the same address used for target discovery
    (avoids slow ``localhost`` DNS lookups on some systems).
    """
    if host:
        # ws://localhost:9222/devtools/... → ws://127.0.0.1:9222/devtools/...
        from urllib.parse import urlparse, urlunparse

        parts = urlparse(ws_url)
        ws_url = urlunparse(parts._replace(netloc=f"{host}:{parts.port}"))
    ws = websocket.WebSocket()
    ws.settimeout(30)
    ws.connect(ws_url)
    return ws


def _cdp_send(
    ws: websocket.WebSocket,
    method: str,
    params: dict | None = None,
    timeout: float = 30.0,
) -> dict:
    """Send a CDP command and wait for the matching response.

    Discards interleaved CDP event messages while waiting.
    """
    with _msg_id_lock:
        msg_id = next(_msg_id_counter)

    message: dict[str, Any] = {"id": msg_id, "method": method}
    if params:
        message["params"] = params

    old_timeout = ws.gettimeout()
    ws.settimeout(timeout)
    try:
        ws.send(json.dumps(message))
        while True:
            raw = ws.recv()
            resp = json.loads(raw)
            if resp.get("id") == msg_id:
                if "error" in resp:
                    err = resp["error"]
                    raise RuntimeError(f"CDP error {err.get('code')}: {err.get('message')}")
                return resp
            # else: event notification — discard and keep waiting
    finally:
        ws.settimeout(old_timeout)


def _cdp_close(ws: websocket.WebSocket) -> None:
    """Close a CDP websocket connection."""
    try:
        ws.close()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# CDP AX Role → CUP Role mapping
# ---------------------------------------------------------------------------

# Roles that should be skipped entirely (internal browser nodes)
_SKIP_ROLES = frozenset(
    {
        "InlineTextBox",
        "LineBreak",
        "IframePresentational",
        "none",
        "Ignored",
        "IgnoredRole",
    }
)

# Explicit mapping for CDP roles that don't match CUP names directly.
# CDP roles not listed here fall through to the lowercase identity check.
CDP_ROLE_MAP: dict[str, str] = {
    # Document roots
    "RootWebArea": "document",
    "WebArea": "document",
    # Structural / generic
    "GenericContainer": "generic",
    "Iframe": "generic",
    "Div": "generic",
    "Span": "generic",
    "Paragraph": "generic",
    "Pre": "generic",
    "Mark": "generic",
    "Abbr": "generic",
    "Ruby": "generic",
    "Time": "generic",
    "Subscript": "generic",
    "Superscript": "generic",
    "LabelText": "generic",
    "Legend": "generic",
    # Text
    "StaticText": "text",
    # Groups
    "Blockquote": "group",
    "Figcaption": "group",
    "DescriptionListDetail": "group",
    "Details": "group",
    # Lists
    "DescriptionList": "list",
    "DescriptionListTerm": "listitem",
    # CamelCase → lowercase ARIA
    "progressIndicator": "progressbar",
    "spinButton": "spinbutton",
    "tabList": "tablist",
    "tabPanel": "tabpanel",
    "menuItem": "menuitem",
    "menuItemCheckBox": "menuitemcheckbox",
    "menuItemRadio": "menuitemradio",
    "menuBar": "menubar",
    "listItem": "listitem",
    "treeItem": "treeitem",
    "columnHeader": "columnheader",
    "rowHeader": "rowheader",
    "comboBoxGrouping": "combobox",
    "comboBoxMenuButton": "combobox",
    "comboBoxSelect": "combobox",
    "alertDialog": "alertdialog",
    "contentInfo": "contentinfo",
    "radioButton": "radio",
    "scrollBar": "scrollbar",
    # Semantic overrides
    "Summary": "button",
    "Meter": "progressbar",
    "Output": "status",
    "Figure": "figure",
    "Canvas": "img",
    "Video": "generic",
    "Audio": "generic",
    "Section": "generic",  # refined to "region" if named
}

# Valid CUP roles (for the identity-check fallback)
_CUP_ROLES = frozenset(
    {
        "alert",
        "alertdialog",
        "application",
        "article",
        "banner",
        "button",
        "cell",
        "checkbox",
        "columnheader",
        "combobox",
        "complementary",
        "contentinfo",
        "definition",
        "dialog",
        "directory",
        "document",
        "feed",
        "figure",
        "form",
        "generic",
        "grid",
        "gridcell",
        "group",
        "heading",
        "img",
        "link",
        "list",
        "listbox",
        "listitem",
        "log",
        "main",
        "marquee",
        "math",
        "menu",
        "menubar",
        "menuitem",
        "menuitemcheckbox",
        "menuitemradio",
        "meter",
        "navigation",
        "none",
        "note",
        "option",
        "pane",
        "presentation",
        "progressbar",
        "radio",
        "radiogroup",
        "region",
        "row",
        "rowgroup",
        "rowheader",
        "scrollbar",
        "search",
        "searchbox",
        "separator",
        "slider",
        "spinbutton",
        "status",
        "switch",
        "tab",
        "table",
        "tablist",
        "tabpanel",
        "term",
        "text",
        "textbox",
        "timer",
        "toolbar",
        "tooltip",
        "tree",
        "treegrid",
        "treeitem",
        "window",
    }
)

# Roles where text input is expected
_TEXT_INPUT_ROLES = frozenset(
    {
        "textbox",
        "searchbox",
        "combobox",
        "spinbutton",
    }
)

# Roles that are inherently clickable
_CLICKABLE_ROLES = frozenset(
    {
        "button",
        "link",
        "menuitem",
        "menuitemcheckbox",
        "menuitemradio",
        "option",
        "tab",
    }
)

# Roles that support selection
_SELECTABLE_ROLES = frozenset(
    {
        "option",
        "tab",
        "treeitem",
        "listitem",
        "row",
        "cell",
        "gridcell",
    }
)

# Roles that are toggle-like
_TOGGLE_ROLES = frozenset(
    {
        "checkbox",
        "switch",
        "menuitemcheckbox",
    }
)

# Roles that are range widgets
_RANGE_ROLES = frozenset(
    {
        "slider",
        "spinbutton",
        "progressbar",
        "scrollbar",
        "meter",
    }
)


def _map_cdp_role(cdp_role: str, name: str) -> str | None:
    """Map a CDP AX role string to a CUP role, or None to skip."""
    if cdp_role in _SKIP_ROLES:
        return None

    # Explicit mapping
    cup_role = CDP_ROLE_MAP.get(cdp_role)
    if cup_role is not None:
        # Section with a name becomes "region"
        if cdp_role == "Section" and name:
            return "region"
        return cup_role

    # Identity check: CDP role lowercased might already be a valid CUP role
    lower = cdp_role.lower()
    if lower in _CUP_ROLES:
        return lower

    return "generic"


# ---------------------------------------------------------------------------
# State extraction
# ---------------------------------------------------------------------------


def _extract_states(
    props: dict[str, Any],
    role: str,
    bounds: dict | None,
    viewport_w: int,
    viewport_h: int,
) -> list[str]:
    """Derive CUP states from CDP AX properties."""
    states: list[str] = []

    if props.get("disabled"):
        states.append("disabled")
    if props.get("focused"):
        states.append("focused")

    # Expanded / collapsed
    expanded = props.get("expanded")
    if expanded is True:
        states.append("expanded")
    elif expanded is False:
        states.append("collapsed")

    if props.get("selected"):
        states.append("selected")

    # Checked (can be boolean or string "true"/"mixed")
    checked = props.get("checked")
    if checked is True or checked == "true":
        states.append("checked")
    elif checked == "mixed":
        states.append("mixed")

    # Pressed (toggle buttons)
    pressed = props.get("pressed")
    if pressed is True or pressed == "true":
        states.append("pressed")
    elif pressed == "mixed":
        states.append("mixed")

    if props.get("busy"):
        states.append("busy")
    if props.get("modal"):
        states.append("modal")
    if props.get("required"):
        states.append("required")

    readonly = props.get("readonly")
    if readonly:
        states.append("readonly")

    # Editable: text-input role that is not readonly
    if role in _TEXT_INPUT_ROLES and not readonly:
        states.append("editable")

    # Offscreen detection from bounds vs viewport
    if bounds:
        bx, by = bounds["x"], bounds["y"]
        bw, bh = bounds["w"], bounds["h"]
        if (
            bw <= 0
            or bh <= 0
            or bx + bw <= 0
            or by + bh <= 0
            or bx >= viewport_w
            or by >= viewport_h
        ):
            states.append("offscreen")

    return states


# ---------------------------------------------------------------------------
# Action derivation
# ---------------------------------------------------------------------------


def _derive_actions(
    role: str,
    props: dict[str, Any],
    states: list[str],
) -> list[str]:
    """Derive CUP actions from node role and properties."""
    actions: list[str] = []

    if "disabled" in states:
        return actions

    if role in _CLICKABLE_ROLES:
        actions.append("click")
        actions.append("rightclick")
        actions.append("doubleclick")

    if role in _TOGGLE_ROLES:
        actions.append("toggle")

    if role in _SELECTABLE_ROLES and "select" not in actions:
        actions.append("select")

    if "expanded" in states or "collapsed" in states:
        if "expand" not in actions:
            actions.append("expand")
            actions.append("collapse")

    if role in _TEXT_INPUT_ROLES and "readonly" not in states:
        actions.append("type")
        actions.append("setvalue")

    if role in ("slider", "spinbutton"):
        actions.append("increment")
        actions.append("decrement")

    if role == "scrollbar":
        actions.append("scroll")

    # Focusable fallback
    if not actions and props.get("focusable"):
        actions.append("focus")

    return actions


# ---------------------------------------------------------------------------
# Attribute extraction
# ---------------------------------------------------------------------------


def _extract_attributes(
    props: dict[str, Any],
    role: str,
    ax_node: dict,
) -> dict[str, Any]:
    """Extract optional CUP attributes from CDP AX properties."""
    attrs: dict[str, Any] = {}

    level = props.get("level")
    if level is not None:
        attrs["level"] = int(level)

    placeholder = props.get("placeholder")
    if placeholder:
        attrs["placeholder"] = str(placeholder)[:200]

    orientation = props.get("orientation")
    if orientation:
        attrs["orientation"] = str(orientation)

    # Range values
    if role in _RANGE_ROLES:
        vmin = props.get("valuemin")
        if vmin is not None:
            attrs["valueMin"] = float(vmin)
        vmax = props.get("valuemax")
        if vmax is not None:
            attrs["valueMax"] = float(vmax)
        vnow = props.get("valuetext") or props.get("valuenow")
        if vnow is not None:
            try:
                attrs["valueNow"] = float(vnow)
            except (ValueError, TypeError):
                pass

    # URL for links
    if role == "link":
        url = props.get("url")
        if url:
            attrs["url"] = str(url)[:500]

    # Autocomplete
    autocomplete = props.get("autocomplete")
    if autocomplete and autocomplete != "none":
        attrs["autocomplete"] = str(autocomplete)

    return attrs


# ---------------------------------------------------------------------------
# CUP node builder
# ---------------------------------------------------------------------------


def _ax_value(field: Any) -> Any:
    """Unpack a CDP AXValue object to its plain value."""
    if isinstance(field, dict):
        return field.get("value")
    return field


def _build_cup_node(
    ax_node: dict,
    id_gen: itertools.count,
    stats: dict,
    viewport_w: int,
    viewport_h: int,
) -> dict | None:
    """Convert a single CDP AX node to a CUP node dict."""
    # Role
    cdp_role = _ax_value(ax_node.get("role")) or "generic"
    name = _ax_value(ax_node.get("name")) or ""
    role = _map_cdp_role(cdp_role, name)
    if role is None:
        return None

    stats["nodes"] += 1
    stats["roles"][cdp_role] = stats["roles"].get(cdp_role, 0) + 1

    # Name and description
    name = str(name)[:200] if name else ""
    description = str(_ax_value(ax_node.get("description")) or "")[:200]

    # Value
    raw_value = _ax_value(ax_node.get("value"))
    value_str = str(raw_value)[:200] if raw_value is not None else ""

    # Properties into a flat dict for easier lookup
    props: dict[str, Any] = {}
    for prop in ax_node.get("properties", []):
        prop_name = prop.get("name", "")
        props[prop_name] = _ax_value(prop.get("value"))

    # Bounds (from CDP "boundingBox" field if present)
    bounds = None
    bb = ax_node.get("boundingBox")
    if bb:
        bounds = {
            "x": int(bb.get("x", 0)),
            "y": int(bb.get("y", 0)),
            "w": int(bb.get("width", 0)),
            "h": int(bb.get("height", 0)),
        }

    # States
    states = _extract_states(props, role, bounds, viewport_w, viewport_h)

    # Actions
    actions = _derive_actions(role, props, states)

    # Attributes
    attrs = _extract_attributes(props, role, ax_node)

    # Assemble CUP node
    node: dict[str, Any] = {
        "id": f"e{next(id_gen)}",
        "role": role,
        "name": name,
    }
    if description:
        node["description"] = description
    if value_str and role in (
        "textbox",
        "searchbox",
        "combobox",
        "spinbutton",
        "slider",
        "progressbar",
        "meter",
        "document",
    ):
        node["value"] = value_str
    if bounds:
        node["bounds"] = bounds
    if states:
        node["states"] = states
    if actions:
        node["actions"] = actions
    if attrs:
        node["attributes"] = attrs

    # Platform extension
    platform_ext: dict[str, Any] = {"cdpRole": cdp_role}
    backend_id = ax_node.get("backendDOMNodeId")
    if backend_id is not None:
        platform_ext["backendDOMNodeId"] = backend_id
    node_id = ax_node.get("nodeId")
    if node_id:
        platform_ext["cdpNodeId"] = node_id
    node["platform"] = {"web": platform_ext}

    return node


# ---------------------------------------------------------------------------
# Tree reconstruction from flat CDP AX node list
# ---------------------------------------------------------------------------


def _build_tree_from_flat(
    ax_nodes: list[dict],
    id_gen: itertools.count,
    stats: dict,
    max_depth: int,
    viewport_w: int,
    viewport_h: int,
    refs: dict,
    ws_url: str | None = None,
) -> list[dict]:
    """Convert the flat CDP AX node list into a nested CUP tree.

    CDP returns nodes with nodeId + childIds references.  We build a
    lookup table, then walk from the root to construct the nested structure.
    """
    if not ax_nodes:
        return []

    # Build nodeId → ax_node lookup
    node_map: dict[str, dict] = {}
    for ax_node in ax_nodes:
        nid = ax_node.get("nodeId", "")
        if nid:
            node_map[nid] = ax_node

    cup_cache: dict[str, dict | None] = {}

    def _convert(node_id: str, depth: int) -> dict | None:
        if depth > max_depth:
            return None
        if node_id in cup_cache:
            return cup_cache[node_id]

        ax_node = node_map.get(node_id)
        if ax_node is None:
            return None

        # Check if this node should be skipped before building
        cdp_role = _ax_value(ax_node.get("role")) or "generic"
        if cdp_role in _SKIP_ROLES:
            cup_cache[node_id] = None
            # But still convert children — they may promote up
            child_ids = ax_node.get("childIds", [])
            promoted: list[dict] = []
            if child_ids and depth < max_depth:
                for cid in child_ids:
                    child = _convert(str(cid), depth)
                    if child is None:
                        continue
                    if "_promoted" in child:
                        promoted.extend(child["_promoted"])
                    else:
                        promoted.append(child)
            # Return promoted children via a sentinel (handled below)
            if promoted:
                cup_cache[node_id] = {"_promoted": promoted}
            return cup_cache[node_id]

        cup_node = _build_cup_node(ax_node, id_gen, stats, viewport_w, viewport_h)
        if cup_node is None:
            cup_cache[node_id] = None
            return None

        if ws_url is not None:
            backend_id = ax_node.get("backendDOMNodeId")
            if backend_id is not None:
                refs[cup_node["id"]] = (ws_url, backend_id)

        stats["max_depth"] = max(stats["max_depth"], depth)

        # Recurse into children
        child_ids = ax_node.get("childIds", [])
        if child_ids and depth < max_depth:
            children: list[dict] = []
            for cid in child_ids:
                child_result = _convert(str(cid), depth + 1)
                if child_result is None:
                    continue
                # Handle promoted children from skipped nodes
                if "_promoted" in child_result:
                    children.extend(child_result["_promoted"])
                else:
                    children.append(child_result)
            if children:
                cup_node["children"] = children

        cup_cache[node_id] = cup_node
        return cup_node

    # Root is the first node (typically RootWebArea)
    root_id = ax_nodes[0].get("nodeId", "")
    root = _convert(root_id, 0)
    if root is None:
        return []
    if "_promoted" in root:
        return root["_promoted"]
    return [root]


# ---------------------------------------------------------------------------
# WebMCP tool discovery
# ---------------------------------------------------------------------------

_WEBMCP_JS = """\
(() => {
    try {
        const mc = navigator.modelContext;
        if (!mc) return JSON.stringify([]);
        let tools = [];
        if (typeof mc.getTools === 'function') {
            tools = mc.getTools();
        } else if (mc.tools) {
            tools = Array.from(mc.tools);
        } else if (mc._tools) {
            tools = Array.from(mc._tools);
        }
        return JSON.stringify(
            tools.map(t => ({
                name: t.name || '',
                description: t.description || '',
                inputSchema: t.inputSchema || null,
                annotations: t.annotations || null,
            })).filter(t => t.name)
        );
    } catch (e) {
        return JSON.stringify([]);
    }
})()
"""


def _extract_webmcp_tools(ws: websocket.WebSocket) -> list[dict]:
    """Extract WebMCP tools from the page via Runtime.evaluate.

    Returns a list of tool descriptors, or [] if WebMCP is not available.
    Never raises.
    """
    try:
        resp = _cdp_send(
            ws,
            "Runtime.evaluate",
            {
                "expression": _WEBMCP_JS,
                "returnByValue": True,
                "awaitPromise": False,
            },
            timeout=5.0,
        )

        remote_obj = resp.get("result", {}).get("result", {})
        raw = remote_obj.get("value", "[]")
        tools = json.loads(raw) if isinstance(raw, str) else []
        # Validate structure
        return [t for t in tools if isinstance(t, dict) and t.get("name")]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Viewport info
# ---------------------------------------------------------------------------


def _get_viewport_info(ws: websocket.WebSocket) -> tuple[int, int, float]:
    """Get viewport width, height, and device pixel ratio."""
    try:
        resp = _cdp_send(
            ws,
            "Runtime.evaluate",
            {
                "expression": (
                    "JSON.stringify({"
                    "w:window.innerWidth,"
                    "h:window.innerHeight,"
                    "s:window.devicePixelRatio})"
                ),
                "returnByValue": True,
            },
            timeout=5.0,
        )

        raw = resp.get("result", {}).get("result", {}).get("value", "{}")
        info = json.loads(raw)
        return (
            int(info.get("w", 1920)),
            int(info.get("h", 1080)),
            float(info.get("s", 1.0)),
        )
    except Exception:
        return (1920, 1080, 1.0)


# ---------------------------------------------------------------------------
# WebAdapter
# ---------------------------------------------------------------------------


class WebAdapter(PlatformAdapter):
    """CUP adapter for web pages via Chrome DevTools Protocol (CDP).

    Connects to a Chromium-based browser running with
    ``--remote-debugging-port``.  Browser tabs map to CUP's
    "window" concept.
    """

    def __init__(
        self,
        cdp_host: str | None = None,
        cdp_port: int | None = None,
    ) -> None:
        self._host = cdp_host or os.environ.get("CUP_CDP_HOST", "127.0.0.1")
        self._port = int(cdp_port or os.environ.get("CUP_CDP_PORT", "9222"))
        self._initialized = False
        self._last_tools: list[dict] = []

    # -- identity ----------------------------------------------------------

    @property
    def platform_name(self) -> str:
        return "web"

    # -- lifecycle ---------------------------------------------------------

    def initialize(self) -> None:
        if self._initialized:
            return
        try:
            targets = _cdp_get_targets(self._host, self._port)
        except Exception as exc:
            raise RuntimeError(
                f"Cannot connect to CDP at {self._host}:{self._port}. "
                f"Launch Chrome with: chrome --remote-debugging-port={self._port}\n"
                f"  Error: {exc}"
            ) from exc
        page_targets = [t for t in targets if t.get("type") == "page"]
        if not page_targets:
            raise RuntimeError(
                f"CDP endpoint at {self._host}:{self._port} has no page targets. "
                f"Open at least one tab in the browser."
            )
        self._initialized = True

    # -- screen ------------------------------------------------------------

    def get_screen_info(self) -> tuple[int, int, float]:
        """Return viewport dimensions from the active tab."""
        targets = _cdp_get_targets(self._host, self._port)
        page_targets = [t for t in targets if t.get("type") == "page"]
        if not page_targets:
            return (1920, 1080, 1.0)

        ws = _cdp_connect(page_targets[0]["webSocketDebuggerUrl"], self._host)
        try:
            return _get_viewport_info(ws)
        finally:
            _cdp_close(ws)

    # -- window enumeration ------------------------------------------------

    def _page_targets(self) -> list[dict]:
        targets = _cdp_get_targets(self._host, self._port)
        return [t for t in targets if t.get("type") == "page"]

    def get_foreground_window(self) -> dict[str, Any]:
        page_targets = self._page_targets()
        if not page_targets:
            raise RuntimeError("No browser tabs found")
        t = page_targets[0]
        return {
            "handle": t["webSocketDebuggerUrl"],
            "title": t.get("title", ""),
            "pid": None,
            "bundle_id": None,
            "url": t.get("url", ""),
        }

    def get_all_windows(self) -> list[dict[str, Any]]:
        return [
            {
                "handle": t["webSocketDebuggerUrl"],
                "title": t.get("title", ""),
                "pid": None,
                "bundle_id": None,
                "url": t.get("url", ""),
            }
            for t in self._page_targets()
        ]

    # -- window overview ---------------------------------------------------

    def get_window_list(self) -> list[dict[str, Any]]:
        targets = self._page_targets()
        results = []
        for i, t in enumerate(targets):
            results.append(
                {
                    "title": t.get("title", ""),
                    "pid": None,
                    "bundle_id": None,
                    "foreground": i == 0,
                    "bounds": None,
                    "url": t.get("url", ""),
                }
            )
        return results

    def get_desktop_window(self) -> dict[str, Any] | None:
        return None  # web platform has no desktop concept

    # -- tree capture ------------------------------------------------------

    def capture_tree(
        self,
        windows: list[dict[str, Any]],
        *,
        max_depth: int = 999,
    ) -> tuple[list[dict], dict, dict[str, Any]]:
        self.initialize()
        id_gen = itertools.count()
        stats: dict[str, Any] = {"nodes": 0, "max_depth": 0, "roles": {}}
        refs: dict[str, Any] = {}
        tree: list[dict] = []
        all_tools: list[dict] = []

        for win in windows:
            ws_url = win["handle"]
            ws = _cdp_connect(ws_url, self._host)
            try:
                # Enable required CDP domains
                _cdp_send(ws, "Accessibility.enable")
                _cdp_send(ws, "Runtime.enable")

                # Get viewport for offscreen detection
                vw, vh, _ = _get_viewport_info(ws)

                # Get the full AX tree
                result = _cdp_send(ws, "Accessibility.getFullAXTree")
                ax_nodes = result.get("result", {}).get("nodes", [])

                roots = _build_tree_from_flat(
                    ax_nodes,
                    id_gen,
                    stats,
                    max_depth,
                    vw,
                    vh,
                    refs,
                    ws_url,
                )
                tree.extend(roots)

                # Discover WebMCP tools
                tools = _extract_webmcp_tools(ws)
                all_tools.extend(tools)
            except Exception:
                continue
            finally:
                _cdp_close(ws)

        self._last_tools = all_tools
        return tree, stats, refs

    # -- WebMCP tools ------------------------------------------------------

    def get_last_tools(self) -> list[dict]:
        """Return WebMCP tools discovered during the last capture_tree() call."""
        return self._last_tools
