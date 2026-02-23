"""
CUP format utilities: envelope builder, compact text serializer, and overview.

Shared across platform-specific tree capture scripts.
"""

from __future__ import annotations

import copy
import time
from typing import Literal

Detail = Literal["standard", "minimal", "full"]


# ---------------------------------------------------------------------------
# CUP envelope
# ---------------------------------------------------------------------------


def build_envelope(
    tree_data: list[dict],
    *,
    platform: str,
    scope: str | None = None,
    screen_w: int,
    screen_h: int,
    screen_scale: float | None = None,
    app_name: str | None = None,
    app_pid: int | None = None,
    app_bundle_id: str | None = None,
    tools: list[dict] | None = None,
) -> dict:
    """Wrap tree nodes in the CUP envelope with metadata."""
    screen: dict = {"w": screen_w, "h": screen_h}
    if screen_scale is not None and screen_scale != 1.0:
        screen["scale"] = screen_scale

    envelope: dict = {
        "version": "0.1.0",
        "platform": platform,
        "timestamp": int(time.time() * 1000),
        "screen": screen,
    }
    if scope:
        envelope["scope"] = scope
    if app_name or app_pid is not None or app_bundle_id:
        app_info: dict = {}
        if app_name:
            app_info["name"] = app_name
        if app_pid is not None:
            app_info["pid"] = app_pid
        if app_bundle_id:
            app_info["bundleId"] = app_bundle_id
        envelope["app"] = app_info
    envelope["tree"] = tree_data
    if tools:
        envelope["tools"] = tools
    return envelope


# ---------------------------------------------------------------------------
# Overview serializer (window list only, no tree)
# ---------------------------------------------------------------------------


def serialize_overview(
    window_list: list[dict],
    *,
    platform: str,
    screen_w: int,
    screen_h: int,
) -> str:
    """Serialize a window list to compact overview text.

    No tree walking, no element IDs — just a list of open windows
    for situational awareness.
    """
    lines = [
        f"# CUP 0.1.0 | {platform} | {screen_w}x{screen_h}",
        f"# overview | {len(window_list)} windows",
        "",
    ]
    for win in window_list:
        title = win.get("title", "(untitled)")
        pid = win.get("pid")
        is_fg = win.get("foreground", False)
        bounds = win.get("bounds")

        prefix = "* " if is_fg else "  "
        marker = "[fg] " if is_fg else ""

        parts = [f"{prefix}{marker}{title}"]
        if pid is not None:
            parts.append(f"(pid:{pid})")
        if bounds:
            parts.append(f"@{bounds['x']},{bounds['y']} {bounds['w']}x{bounds['h']}")

        url = win.get("url")
        if url:
            truncated_url = url[:80] + ("..." if len(url) > 80 else "")
            parts.append(f"url:{truncated_url}")

        lines.append(" ".join(parts))

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Compact text serializer
# ---------------------------------------------------------------------------


def _count_nodes(nodes: list[dict]) -> int:
    """Count total nodes in a tree."""
    total = 0
    for node in nodes:
        total += 1
        total += _count_nodes(node.get("children", []))
    return total


_CHROME_ROLES = frozenset({"scrollbar", "separator", "titlebar", "tooltip", "status"})


def _should_skip(node: dict, parent: dict | None, siblings: int) -> bool:
    """Decide if a node should be pruned (entire subtree is dropped)."""
    role = node["role"]
    name = node.get("name", "")
    states = node.get("states", [])

    # Skip window chrome / decorative roles (and their entire subtrees).
    # Scrollbar: the parent container already has [scroll] — agents never
    #   click scrollbar thumbs/tracks.
    # Separator: pure visual decoration, no semantic content.
    # Titlebar: minimize/maximize/close — agents use press_keys instead.
    # Tooltip: transient flyouts, rarely actionable.
    # Status: read-only info (line numbers, encoding, git branch) — agents
    #   can still find these via find_element on the raw tree if needed.
    if role in _CHROME_ROLES:
        return True

    # Skip zero-size elements — invisible regardless of other properties
    bounds = node.get("bounds")
    if bounds and (bounds.get("w", 1) == 0 or bounds.get("h", 1) == 0):
        return True

    # Skip offscreen nodes that have no meaningful actions — they can't be
    # interacted with until scrolled into view and add no actionable info.
    # Offscreen buttons/links/inputs ARE kept so the LLM knows what's
    # available after scrolling.
    if "offscreen" in states:
        actions = node.get("actions", [])
        meaningful_actions = [a for a in actions if a != "focus"]
        if not meaningful_actions:
            return True

    # Skip unnamed decorative images
    if role == "img" and not name:
        return True

    # Skip empty-name text nodes
    if role == "text" and not name:
        return True

    # Skip text that is sole child of a named parent (redundant label)
    if role == "text" and parent and parent.get("name") and siblings == 1:
        return True

    return False


def _should_hoist(node: dict) -> bool:
    """Decide if a node's children should be hoisted (node itself skipped)."""
    role = node["role"]
    name = node.get("name", "")

    # Unnamed generic nodes are structural wrappers -- hoist children
    if role == "generic" and not name:
        return True

    # Unnamed region nodes — very common in Electron/Chromium apps where
    # nested <div> wrappers get exposed as UIA regions.  Pure noise.
    if role == "region" and not name:
        return True

    # Unnamed group nodes without meaningful actions are structural wrappers.
    # On Windows, these map to Pane->generic and get hoisted above.
    # On macOS, AXGroup is used for both semantic and structural containers,
    # so we hoist only when there's no name and no actions (pure wrapper).
    if role == "group" and not name:
        actions = node.get("actions", [])
        meaningful = [a for a in actions if a != "focus"]
        if not meaningful:
            return True

    return False


# ---------------------------------------------------------------------------
# Viewport clipping helpers
# ---------------------------------------------------------------------------


def _is_outside_viewport(child_bounds: dict, viewport: dict) -> bool:
    """Return True if child_bounds falls entirely outside the viewport rect."""
    return (
        child_bounds["x"] + child_bounds["w"] <= viewport["x"]  # fully left
        or child_bounds["x"] >= viewport["x"] + viewport["w"]  # fully right
        or child_bounds["y"] + child_bounds["h"] <= viewport["y"]  # fully above
        or child_bounds["y"] >= viewport["y"] + viewport["h"]  # fully below
    )


def _clip_direction(child_bounds: dict, viewport: dict) -> str:
    """Return 'above', 'below', 'left', or 'right' for a clipped child."""
    if child_bounds["y"] + child_bounds["h"] <= viewport["y"]:
        return "above"
    if child_bounds["y"] >= viewport["y"] + viewport["h"]:
        return "below"
    if child_bounds["x"] + child_bounds["w"] <= viewport["x"]:
        return "left"
    return "right"


def _is_scrollable(node: dict) -> bool:
    """Check if a node is a scrollable container."""
    return "scroll" in node.get("actions", [])


def _intersect_viewports(bounds: dict, viewport: dict | None) -> dict:
    """Intersect a scrollable container's bounds with its parent viewport.

    A scrollable child may report bounds larger than its visible area (e.g. a
    grid reporting 1888px height inside a 398px list). Intersecting ensures
    the effective viewport is never larger than the parent's visible region.
    """
    if viewport is None:
        return bounds
    x1 = max(bounds["x"], viewport["x"])
    y1 = max(bounds["y"], viewport["y"])
    x2 = min(bounds["x"] + bounds["w"], viewport["x"] + viewport["w"])
    y2 = min(bounds["y"] + bounds["h"], viewport["y"] + viewport["h"])
    return {"x": x1, "y": y1, "w": max(0, x2 - x1), "h": max(0, y2 - y1)}


# ---------------------------------------------------------------------------
# JSON tree pruning
# ---------------------------------------------------------------------------


def _prune_node(
    node: dict,
    parent: dict | None,
    siblings: int,
    viewport: dict | None = None,
) -> list[dict]:
    """Prune a single node, returning 0 or more nodes to replace it.

    - Hoisted nodes are removed and their (pruned) children returned in place.
    - Skipped nodes are dropped entirely (with descendants).
    - Viewport-clipped nodes are dropped with a count tracked on the
      scrollable ancestor (emitted as a hint in compact output).
    - Normal nodes are kept with their children recursively pruned.

    Args:
        viewport: Bounds rect of the nearest scrollable ancestor, or None.
    """
    children = node.get("children", [])

    if _should_hoist(node):
        result = []
        for child in children:
            result.extend(_prune_node(child, parent, len(children), viewport))
        return result

    if _should_skip(node, parent, siblings):
        return []

    # Determine the viewport for this node's children: if this node is a
    # scrollable container with bounds, its bounds become the viewport.
    # Intersect with the inherited viewport so a scrollable child can't
    # expand beyond its parent's visible region (e.g. a grid that reports
    # 1888px height inside a 398px-tall list).
    child_viewport = viewport
    if _is_scrollable(node) and node.get("bounds"):
        child_viewport = _intersect_viewports(node["bounds"], viewport)

    # Keep this node — prune its children recursively, clipping those
    # that fall entirely outside the active viewport.
    pruned_children = []
    clipped = {"above": 0, "below": 0, "left": 0, "right": 0}
    has_clipped = False

    for child in children:
        child_bounds = child.get("bounds")
        # Clip children outside the viewport of a scrollable container
        if child_viewport and child_bounds and _is_outside_viewport(child_bounds, child_viewport):
            direction = _clip_direction(child_bounds, child_viewport)
            clipped[direction] += _count_nodes([child])
            has_clipped = True
            continue
        pruned_children.extend(_prune_node(child, node, len(children), child_viewport))

    # Single-child structural collapse: unnamed structural containers that
    # ended up wrapping a single child after pruning (and carry no actions
    # of their own) are pure wrappers — replace them with the child.
    if (
        len(pruned_children) == 1
        and node["role"] in _COLLAPSIBLE_ROLES
        and not node.get("name")
        and not _has_meaningful_actions(node)
    ):
        return pruned_children

    pruned = {k: v for k, v in node.items() if k != "children"}
    if pruned_children:
        pruned["children"] = pruned_children
    if has_clipped:
        pruned["_clipped"] = clipped
    return [pruned]


# Structural container roles eligible for single-child collapse.
# When an unnamed node with one of these roles ends up with exactly one
# child after pruning (and has no actions of its own), it's a pure wrapper
# and the child is hoisted in its place.
_COLLAPSIBLE_ROLES = frozenset(
    {
        "region",
        "document",
        "main",
        "complementary",
        "navigation",
        "search",
        "banner",
        "contentinfo",
        "form",
    }
)


def _has_meaningful_actions(node: dict) -> bool:
    """Check if a node has actions beyond just 'focus'."""
    actions = node.get("actions", [])
    return any(a != "focus" for a in actions)


def _prune_minimal_node(node: dict) -> dict | None:
    """Minimal pruning: keep only nodes with meaningful actions + ancestors.

    Returns a pruned copy of the node if it or any descendant has meaningful
    actions, or None if the entire subtree can be dropped.
    """
    children = node.get("children", [])

    # Recursively prune children first
    kept_children = []
    for child in children:
        pruned_child = _prune_minimal_node(child)
        if pruned_child is not None:
            kept_children.append(pruned_child)

    # Keep this node if it has meaningful actions OR if any child was kept
    if _has_meaningful_actions(node) or kept_children:
        pruned = {k: v for k, v in node.items() if k != "children"}
        if kept_children:
            pruned["children"] = kept_children
        return pruned

    return None


def prune_tree(
    tree: list[dict],
    *,
    detail: Detail = "standard",
    screen: dict | None = None,
) -> list[dict]:
    """Apply pruning to a CUP tree, returning a new pruned tree.

    Args:
        tree: List of root CUP node dicts.
        detail: Pruning level:
            "standard" — Remove unnamed generics, decorative images, empty
                         text, offscreen noise, etc. (default)
            "minimal"  — Keep only nodes with meaningful actions (not just
                         focus) and their ancestors. Dramatically reduces
                         token count.
            "full"     — No pruning; return every node from the raw tree.
        screen: Screen dimensions dict with "w" and "h" keys. When provided,
                elements entirely outside the screen bounds are clipped even
                if no scrollable ancestor is present.
    """
    if detail == "full":
        return copy.deepcopy(tree)

    if detail == "minimal":
        result = []
        for root in tree:
            pruned = _prune_minimal_node(root)
            if pruned is not None:
                result.append(pruned)
        return result

    # "standard" — use screen as baseline viewport so elements far offscreen
    # (e.g. in web-based apps with virtual scroll) are clipped even when no
    # ancestor exposes the "scroll" action.
    screen_viewport = None
    if screen:
        screen_viewport = {"x": 0, "y": 0, "w": screen["w"], "h": screen["h"]}
    result = []
    for root in tree:
        result.extend(_prune_node(root, None, len(tree), viewport=screen_viewport))
    return result


def _format_line(node: dict) -> str:
    """Format a single CUP node as a compact one-liner."""
    parts = [f"[{node['id']}]", node["role"]]

    name = node.get("name", "")
    if name:
        truncated = name[:80] + ("..." if len(name) > 80 else "")
        # Escape quotes and newlines in name
        truncated = truncated.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
        parts.append(f'"{truncated}"')

    bounds = node.get("bounds")
    if bounds:
        parts.append(f"@{bounds['x']},{bounds['y']} {bounds['w']}x{bounds['h']}")

    states = node.get("states", [])
    if states:
        parts.append("{" + ",".join(states) + "}")

    # Actions (drop "focus" -- it's noise)
    actions = [a for a in node.get("actions", []) if a != "focus"]
    if actions:
        parts.append("[" + ",".join(actions) + "]")

    # Value for input-type elements
    value = node.get("value", "")
    if value and node["role"] in ("textbox", "searchbox", "combobox", "spinbutton", "slider"):
        truncated_val = value[:120] + ("..." if len(value) > 120 else "")
        truncated_val = truncated_val.replace('"', '\\"').replace("\n", " ")
        parts.append(f'val="{truncated_val}"')

    # Compact attributes (only the most useful ones for LLM context)
    attrs = node.get("attributes", {})
    if attrs:
        attr_parts = []
        if "level" in attrs:
            attr_parts.append(f"L{attrs['level']}")
        if "placeholder" in attrs:
            ph = attrs["placeholder"][:30]
            ph = ph.replace('"', '\\"').replace("\n", " ")
            attr_parts.append(f'ph="{ph}"')
        if "orientation" in attrs:
            attr_parts.append(attrs["orientation"][:1])  # "h" or "v"
        if "valueMin" in attrs or "valueMax" in attrs:
            vmin = attrs.get("valueMin", "")
            vmax = attrs.get("valueMax", "")
            attr_parts.append(f"range={vmin}..{vmax}")
        if attr_parts:
            parts.append("(" + " ".join(attr_parts) + ")")

    return " ".join(parts)


def _emit_compact(node: dict, depth: int, lines: list[str], counter: list[int]) -> None:
    """Recursively emit compact lines for an already-pruned node."""
    counter[0] += 1
    indent = "  " * depth
    lines.append(f"{indent}{_format_line(node)}")

    for child in node.get("children", []):
        _emit_compact(child, depth + 1, lines, counter)

    # Emit hint for viewport-clipped children
    clipped = node.get("_clipped")
    if clipped:
        above = clipped.get("above", 0)
        below = clipped.get("below", 0)
        left = clipped.get("left", 0)
        right = clipped.get("right", 0)
        v_total = above + below
        h_total = left + right
        total = v_total + h_total
        if total > 0:
            directions = []
            if above > 0:
                directions.append("up")
            if below > 0:
                directions.append("down")
            if left > 0:
                directions.append("left")
            if right > 0:
                directions.append("right")
            hint_indent = "  " * (depth + 1)
            lines.append(
                f"{hint_indent}# {total} more items — scroll {'/'.join(directions)} to see"
            )


# Maximum output size in characters. Prevents token-limit explosions when
# agents accidentally request very large trees. Kept well under typical
# MCP host limits (~100K) to leave room for JSON wrapping and other context.
MAX_OUTPUT_CHARS = 40_000


def serialize_compact(
    envelope: dict,
    *,
    window_list: list[dict] | None = None,
    detail: Detail = "standard",
    max_chars: int = MAX_OUTPUT_CHARS,
) -> str:
    """Serialize a CUP envelope to compact LLM-friendly text.

    Applies pruning to remove structural noise while preserving all
    semantically meaningful and interactive elements. Node IDs are
    preserved from the full tree so agents can reference them in actions.

    Args:
        envelope: CUP envelope dict with tree data.
        window_list: Optional list of open windows to include in header
                     for situational awareness (used by foreground scope).
        detail: Pruning level ("standard", "minimal", or "full").
        max_chars: Hard character limit for output. When exceeded, the
                   output is truncated with a diagnostic message.
    """
    total_before = _count_nodes(envelope["tree"])
    pruned = prune_tree(envelope["tree"], detail=detail, screen=envelope.get("screen"))

    lines: list[str] = []
    counter = [0]

    for root in pruned:
        _emit_compact(root, 0, lines, counter)

    # Build header
    header_lines = [
        f"# CUP {envelope['version']} | {envelope['platform']} | {envelope['screen']['w']}x{envelope['screen']['h']}",
    ]
    if envelope.get("app"):
        header_lines.append(f"# app: {envelope['app'].get('name', '')}")
    header_lines.append(f"# {counter[0]} nodes ({total_before} before pruning)")
    if envelope.get("tools"):
        n = len(envelope["tools"])
        header_lines.append(f"# {n} WebMCP tool{'s' if n != 1 else ''} available")

    # Window list in header (for foreground scope awareness)
    if window_list:
        header_lines.append(f"# --- {len(window_list)} open windows ---")
        for win in window_list:
            title = win.get("title", "(untitled)")[:50]
            is_fg = win.get("foreground", False)
            marker = " [fg]" if is_fg else ""
            header_lines.append(f"#   {title}{marker}")

    header_lines.append("")

    output = "\n".join(header_lines + lines) + "\n"

    # Hard truncation safety net
    if max_chars > 0 and len(output) > max_chars:
        truncated = output[:max_chars]
        # Cut at last newline to avoid partial lines
        last_nl = truncated.rfind("\n")
        if last_nl > 0:
            truncated = truncated[:last_nl]
        truncated += (
            "\n\n# OUTPUT TRUNCATED — exceeded character limit.\n"
            "# Use find_element(name=...) to locate specific elements instead.\n"
            "# Or use get_tree(app='<title>') to target a specific window.\n"
        )
        return truncated

    return output
