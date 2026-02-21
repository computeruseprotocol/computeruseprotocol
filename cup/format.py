"""
CUP format utilities: envelope builder and compact text serializer.

Shared across platform-specific tree capture scripts.
"""

from __future__ import annotations

import time


# ---------------------------------------------------------------------------
# CUP envelope
# ---------------------------------------------------------------------------

def build_envelope(
    tree_data: list[dict],
    *,
    platform: str,
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
# Compact text serializer
# ---------------------------------------------------------------------------

def _count_nodes(nodes: list[dict]) -> int:
    """Count total nodes in a tree."""
    total = 0
    for node in nodes:
        total += 1
        total += _count_nodes(node.get("children", []))
    return total


def _should_skip(node: dict, parent: dict | None, siblings: int) -> bool:
    """Decide if a node should be pruned."""
    role = node["role"]
    name = node.get("name", "")
    states = node.get("states", [])

    # Skip offscreen nodes only if they have no name and no actions
    # (scrolled-away content like chat messages should be kept)
    if "offscreen" in states and not name:
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
# JSON tree pruning
# ---------------------------------------------------------------------------

def _prune_node(node: dict, parent: dict | None, siblings: int) -> list[dict]:
    """Prune a single node, returning 0 or more nodes to replace it.

    - Hoisted nodes are removed and their (pruned) children returned in place.
    - Skipped nodes are dropped entirely (with descendants).
    - Normal nodes are kept with their children recursively pruned.
    """
    children = node.get("children", [])

    if _should_hoist(node):
        result = []
        for child in children:
            result.extend(_prune_node(child, parent, len(children)))
        return result

    if _should_skip(node, parent, siblings):
        return []

    # Keep this node — prune its children recursively
    pruned_children = []
    for child in children:
        pruned_children.extend(_prune_node(child, node, len(children)))

    pruned = {k: v for k, v in node.items() if k != "children"}
    if pruned_children:
        pruned["children"] = pruned_children
    return [pruned]


def prune_tree(tree: list[dict]) -> list[dict]:
    """Apply skip/hoist pruning to a CUP tree, returning a new pruned tree.

    Same rules as the compact serializer: removes unnamed generics,
    decorative images, empty text, offscreen noise, etc.
    """
    result = []
    for root in tree:
        result.extend(_prune_node(root, None, len(tree)))
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
        truncated_val = value[:40] + ("..." if len(value) > 40 else "")
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


def _emit_compact(node: dict, depth: int, lines: list[str],
                  counter: list[int]) -> None:
    """Recursively emit compact lines for an already-pruned node."""
    counter[0] += 1
    indent = "  " * depth
    lines.append(f"{indent}{_format_line(node)}")

    for child in node.get("children", []):
        _emit_compact(child, depth + 1, lines, counter)


def serialize_compact(envelope: dict) -> str:
    """Serialize a CUP envelope to compact LLM-friendly text.

    Applies pruning to remove structural noise while preserving all
    semantically meaningful and interactive elements. Node IDs are
    preserved from the full tree so agents can reference them in actions.
    """
    total_before = _count_nodes(envelope["tree"])
    pruned = prune_tree(envelope["tree"])

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
    header_lines.append("")

    return "\n".join(header_lines + lines) + "\n"
