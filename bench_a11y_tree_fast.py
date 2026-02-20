"""
Optimised benchmark: Windows UIA accessibility tree -> CUP format via raw COM.

Outputs trees in Computer Use Protocol (CUP) schema — canonical roles, states,
actions, and platform metadata — ready for AI agent consumption.

Key optimisations over the pywinauto version:
  1. Direct UIA COM via comtypes — no wrapper overhead
  2. CacheRequest batches 21 properties (core + states + patterns) in one call
  3. Win32 EnumWindows for instant HWND list (skips slow UIA root enumeration)
  4. ElementFromHandleBuildCache to get UIA elements from HWNDs
  5. FindAllBuildCache collapses entire subtree into ONE cross-process call
  6. TreeWalker with BuildCache for structured tree (one call per node, all props)

Usage:
    python bench_a11y_tree_fast.py                # full tree, all windows
    python bench_a11y_tree_fast.py --foreground    # full tree, foreground window only
    python bench_a11y_tree_fast.py --depth 5       # cap depth at 5
    python bench_a11y_tree_fast.py --app Notepad   # filter by window title
    python bench_a11y_tree_fast.py --flat           # flat list (no hierarchy)
    python bench_a11y_tree_fast.py --json-out tree.json
    python bench_a11y_tree_fast.py --foreground --compact-out tree.cup
    python bench_a11y_tree_fast.py --foreground --json-out full.json --compact-out compact.cup
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes
import itertools
import json
import time
import comtypes
import comtypes.client

# ---------------------------------------------------------------------------
# UIA COM property IDs
# ---------------------------------------------------------------------------

# Core
UIA_BoundingRectanglePropertyId = 30001
UIA_ControlTypePropertyId = 30003
UIA_NamePropertyId = 30005

# State / identification
UIA_HasKeyboardFocusPropertyId = 30008
UIA_IsEnabledPropertyId = 30010
UIA_AutomationIdPropertyId = 30011
UIA_ClassNamePropertyId = 30012
UIA_HelpTextPropertyId = 30013
UIA_NativeWindowHandlePropertyId = 30020
UIA_IsOffscreenPropertyId = 30022

# Pattern availability
UIA_IsInvokePatternAvailablePropertyId = 30031
UIA_IsRangeValuePatternAvailablePropertyId = 30033
UIA_IsSelectionItemPatternAvailablePropertyId = 30036
UIA_IsScrollPatternAvailablePropertyId = 30037
UIA_IsTogglePatternAvailablePropertyId = 30041
UIA_IsExpandCollapsePatternAvailablePropertyId = 30042
UIA_IsValuePatternAvailablePropertyId = 30043

# Pattern state values
UIA_ValueValuePropertyId = 30045
UIA_ValueIsReadOnlyPropertyId = 30046
UIA_ExpandCollapseExpandCollapseStatePropertyId = 30070
UIA_SelectionItemIsSelectedPropertyId = 30079
UIA_ToggleToggleStatePropertyId = 30086

# Tree scope / element mode
TreeScope_Element = 1
TreeScope_Children = 2
TreeScope_Subtree = 7

AutomationElementMode_None = 0
AutomationElementMode_Full = 1

# All properties to cache in a single COM call
PROP_IDS = [
    # Core (3)
    UIA_NamePropertyId, UIA_ControlTypePropertyId, UIA_BoundingRectanglePropertyId,
    # State / identification (5)
    UIA_IsEnabledPropertyId, UIA_HasKeyboardFocusPropertyId, UIA_IsOffscreenPropertyId,
    UIA_AutomationIdPropertyId, UIA_ClassNamePropertyId, UIA_HelpTextPropertyId,
    # Pattern availability (7)
    UIA_IsInvokePatternAvailablePropertyId, UIA_IsTogglePatternAvailablePropertyId,
    UIA_IsExpandCollapsePatternAvailablePropertyId, UIA_IsValuePatternAvailablePropertyId,
    UIA_IsSelectionItemPatternAvailablePropertyId, UIA_IsScrollPatternAvailablePropertyId,
    UIA_IsRangeValuePatternAvailablePropertyId,
    # Pattern state values (5)
    UIA_ToggleToggleStatePropertyId, UIA_ExpandCollapseExpandCollapseStatePropertyId,
    UIA_SelectionItemIsSelectedPropertyId, UIA_ValueIsReadOnlyPropertyId,
    UIA_ValueValuePropertyId,
]


# ---------------------------------------------------------------------------
# UIA ControlType display names (for benchmark stats)
# ---------------------------------------------------------------------------

CONTROL_TYPES = {
    50000: "Button", 50001: "Calendar", 50002: "CheckBox",
    50003: "ComboBox", 50004: "Edit", 50005: "Hyperlink",
    50006: "Image", 50007: "ListItem", 50008: "List",
    50009: "Menu", 50010: "MenuBar", 50011: "MenuItem",
    50012: "ProgressBar", 50013: "RadioButton", 50014: "ScrollBar",
    50015: "Slider", 50016: "Spinner", 50017: "StatusBar",
    50018: "Tab", 50019: "TabItem", 50020: "Text",
    50021: "ToolBar", 50022: "ToolTip", 50023: "Tree",
    50024: "TreeItem", 50025: "Custom", 50026: "Group",
    50027: "Thumb", 50028: "DataGrid", 50029: "DataItem",
    50030: "Document", 50031: "SplitButton", 50032: "Window",
    50033: "Pane", 50034: "Header", 50035: "HeaderItem",
    50036: "Table", 50037: "TitleBar", 50038: "Separator",
    50039: "SemanticZoom", 50040: "AppBar",
}


# ---------------------------------------------------------------------------
# CUP role mapping: UIA ControlType ID -> canonical CUP role
# ---------------------------------------------------------------------------

CUP_ROLES = {
    50000: "button",        # Button
    50001: "grid",          # Calendar
    50002: "checkbox",      # CheckBox
    50003: "combobox",      # ComboBox
    50004: "textbox",       # Edit
    50005: "link",          # Hyperlink
    50006: "img",           # Image
    50007: "listitem",      # ListItem
    50008: "list",          # List
    50009: "menu",          # Menu
    50010: "menubar",       # MenuBar
    50011: "menuitem",      # MenuItem
    50012: "progressbar",   # ProgressBar
    50013: "radio",         # RadioButton
    50014: "scrollbar",     # ScrollBar
    50015: "slider",        # Slider
    50016: "spinbutton",    # Spinner
    50017: "status",        # StatusBar
    50018: "tablist",       # Tab (the container)
    50019: "tab",           # TabItem
    50020: "text",          # Text
    50021: "toolbar",       # ToolBar
    50022: "tooltip",       # ToolTip
    50023: "tree",          # Tree
    50024: "treeitem",      # TreeItem
    50025: "generic",       # Custom
    50026: "group",         # Group
    50027: "generic",       # Thumb
    50028: "grid",          # DataGrid
    50029: "row",           # DataItem
    50030: "document",      # Document
    50031: "button",        # SplitButton
    50032: "window",        # Window
    50033: "generic",       # Pane — context-dependent, refined below
    50034: "group",         # Header
    50035: "columnheader",  # HeaderItem
    50036: "table",         # Table
    50037: "titlebar",      # TitleBar
    50038: "separator",     # Separator
    50039: "generic",       # SemanticZoom
    50040: "toolbar",       # AppBar
}

# Roles that accept text input (for adding "type" action)
TEXT_INPUT_ROLES = {"textbox", "searchbox", "combobox", "document"}


# ---------------------------------------------------------------------------
# Win32: fast window enumeration via EnumWindows
# ---------------------------------------------------------------------------

user32 = ctypes.windll.user32
WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.wintypes.BOOL, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)


def enum_top_level_windows(*, visible_only: bool = True) -> list[tuple[int, str]]:
    """Use Win32 EnumWindows to get (hwnd, title) for top-level windows. Near-instant."""
    results: list[tuple[int, str]] = []
    buf = ctypes.create_unicode_buffer(512)

    @WNDENUMPROC
    def callback(hwnd, _lparam):
        if visible_only and not user32.IsWindowVisible(hwnd):
            return True  # skip hidden
        length = user32.GetWindowTextW(hwnd, buf, 512)
        title = buf.value if length > 0 else ""
        results.append((hwnd, title))
        return True

    user32.EnumWindows(callback, 0)
    return results


def get_foreground_window() -> tuple[int, str]:
    """Return (hwnd, title) of the current foreground window."""
    hwnd = user32.GetForegroundWindow()
    buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, buf, 512)
    return (hwnd, buf.value)


def get_screen_size() -> tuple[int, int]:
    """Return (width, height) of the primary monitor in pixels."""
    return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)


# Re-export from cup_format for envelope + compact serialization
from cup_format import build_envelope, serialize_compact, prune_tree  # noqa: E402


# ---------------------------------------------------------------------------
# UIA COM bootstrap
# ---------------------------------------------------------------------------

def init_uia():
    """Initialise the IUIAutomation COM interface."""
    comtypes.client.GetModule("UIAutomationCore.dll")
    from comtypes.gen.UIAutomationClient import CUIAutomation, IUIAutomation

    return comtypes.CoCreateInstance(
        CUIAutomation._reg_clsid_,
        interface=IUIAutomation,
        clsctx=comtypes.CLSCTX_INPROC_SERVER,
    )


def make_cache_request(uia, *, element_mode=AutomationElementMode_Full, tree_scope=TreeScope_Element):
    cr = uia.CreateCacheRequest()
    for pid in PROP_IDS:
        cr.AddProperty(pid)
    cr.TreeScope = tree_scope
    cr.AutomationElementMode = element_mode
    return cr


# ---------------------------------------------------------------------------
# Cached property helpers
# ---------------------------------------------------------------------------

def _cached_bool(el, pid, default=False):
    """Read a cached boolean UIA property."""
    try:
        v = el.GetCachedPropertyValue(pid)
        if v is None:
            return default
        return bool(v)
    except Exception:
        return default


def _cached_int(el, pid, default=0):
    """Read a cached integer UIA property."""
    try:
        v = el.GetCachedPropertyValue(pid)
        if v is None:
            return default
        return int(v)
    except Exception:
        return default


def _cached_str(el, pid, default=""):
    """Read a cached string UIA property."""
    try:
        v = el.GetCachedPropertyValue(pid)
        return str(v) if v else default
    except Exception:
        return default


def is_valid_element(el) -> bool:
    """Check if a UIA COM element is a live (non-NULL) pointer."""
    try:
        el.CachedControlType
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# CUP node builder
# ---------------------------------------------------------------------------

def build_cup_node(el, id_gen, stats) -> dict:
    """Build a CUP-formatted node dict from a cached UIA element.

    Reads all 21 cached properties and maps them to canonical CUP fields:
    role, states, actions, value, description, and platform metadata.
    """
    stats["nodes"] += 1

    # ── Core properties ──
    try:
        name = el.CachedName or ""
    except Exception:
        name = ""
    try:
        ct = el.CachedControlType
    except Exception:
        ct = 0
    # BoundingRectangle: use GetCachedPropertyValue which returns a (x, y, w, h)
    # float tuple. The dedicated CachedBoundingRectangle accessor returns a
    # ctypes RECT struct that doesn't support indexing.
    try:
        rect = el.GetCachedPropertyValue(UIA_BoundingRectanglePropertyId)
        if rect and len(rect) == 4:
            bounds = {"x": int(rect[0]), "y": int(rect[1]),
                      "w": int(rect[2]), "h": int(rect[3])}
        else:
            bounds = None
    except Exception:
        bounds = None

    # Stats tracking (uses UIA names for the benchmark report)
    ct_name = CONTROL_TYPES.get(ct, f"Unknown({ct})")
    stats["roles"][ct_name] = stats["roles"].get(ct_name, 0) + 1

    # ── State properties ──
    is_enabled   = _cached_bool(el, UIA_IsEnabledPropertyId, True)
    has_focus    = _cached_bool(el, UIA_HasKeyboardFocusPropertyId, False)
    is_offscreen = _cached_bool(el, UIA_IsOffscreenPropertyId, False)

    # ── Pattern availability ──
    has_invoke   = _cached_bool(el, UIA_IsInvokePatternAvailablePropertyId, False)
    has_toggle   = _cached_bool(el, UIA_IsTogglePatternAvailablePropertyId, False)
    has_expand   = _cached_bool(el, UIA_IsExpandCollapsePatternAvailablePropertyId, False)
    has_value    = _cached_bool(el, UIA_IsValuePatternAvailablePropertyId, False)
    has_sel_item = _cached_bool(el, UIA_IsSelectionItemPatternAvailablePropertyId, False)
    has_scroll   = _cached_bool(el, UIA_IsScrollPatternAvailablePropertyId, False)
    has_range    = _cached_bool(el, UIA_IsRangeValuePatternAvailablePropertyId, False)

    # ── Pattern state values ──
    toggle_state = _cached_int(el, UIA_ToggleToggleStatePropertyId, -1)
    expand_state = _cached_int(el, UIA_ExpandCollapseExpandCollapseStatePropertyId, -1)
    is_selected  = _cached_bool(el, UIA_SelectionItemIsSelectedPropertyId, False)
    val_readonly = _cached_bool(el, UIA_ValueIsReadOnlyPropertyId, False) if has_value else False
    val_str      = _cached_str(el, UIA_ValueValuePropertyId) if has_value else ""

    # ── Identification ──
    automation_id = _cached_str(el, UIA_AutomationIdPropertyId)
    class_name    = _cached_str(el, UIA_ClassNamePropertyId)
    help_text     = _cached_str(el, UIA_HelpTextPropertyId)

    # ── Role (ARIA-mapped) ──
    role = CUP_ROLES.get(ct, "generic")
    if ct == 50033 and name:   # Pane with name -> region
        role = "region"

    # ── States ──
    states = []
    if not is_enabled:
        states.append("disabled")
    if has_focus:
        states.append("focused")
    if is_offscreen:
        states.append("offscreen")
    if has_toggle:
        if toggle_state == 1:
            states.append("checked")
        elif toggle_state == 2:
            states.append("mixed")
    if has_expand:
        if expand_state == 0:
            states.append("collapsed")
        elif expand_state in (1, 2):
            states.append("expanded")
    if is_selected:
        states.append("selected")
    if has_value and val_readonly:
        states.append("readonly")
    if has_value and not val_readonly and role in TEXT_INPUT_ROLES:
        states.append("editable")

    # ── Actions (derived from supported UIA patterns) ──
    actions = []
    if has_invoke:
        actions.append("click")
    if has_toggle:
        actions.append("toggle")
    if has_expand and expand_state != 3:  # 3 = LeafNode
        actions.append("expand")
        actions.append("collapse")
    if has_value and not val_readonly:
        actions.append("setvalue")
        if role in TEXT_INPUT_ROLES:
            actions.append("type")
    if has_sel_item:
        actions.append("select")
    if has_scroll:
        actions.append("scroll")
    if has_range:
        actions.append("increment")
        actions.append("decrement")
    if not actions and is_enabled:
        actions.append("focus")

    # ── Assemble CUP node ──
    node = {
        "id": f"e{next(id_gen)}",
        "role": role,
        "name": name[:200],
    }

    # Optional fields — omit when empty to keep payload compact
    if help_text:
        node["description"] = help_text[:200]
    if val_str:
        node["value"] = val_str[:200]
    if bounds:
        node["bounds"] = bounds
    if states:
        node["states"] = states
    if actions:
        node["actions"] = actions

    # ── Platform extension (windows-specific raw data) ──
    patterns = []
    if has_invoke:   patterns.append("Invoke")
    if has_toggle:   patterns.append("Toggle")
    if has_expand:   patterns.append("ExpandCollapse")
    if has_value:    patterns.append("Value")
    if has_sel_item: patterns.append("SelectionItem")
    if has_scroll:   patterns.append("Scroll")
    if has_range:    patterns.append("RangeValue")

    pw = {"controlType": ct}
    if automation_id:
        pw["automationId"] = automation_id
    if class_name:
        pw["className"] = class_name
    if patterns:
        pw["patterns"] = patterns
    node["platform"] = {"windows": pw}

    return node


# ---------------------------------------------------------------------------
# CUP envelope
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Approach A: flat snapshot via FindAllBuildCache
# ---------------------------------------------------------------------------

def flat_snapshot(uia, root, cache_req, max_depth: int, id_gen, stats) -> list[dict]:
    """Breadth-first, depth-limited snapshot using FindAll(Children) per level.

    Returns a flat list of CUP nodes (no children nesting).
    """
    true_cond = uia.CreateTrueCondition()
    all_nodes: list[dict] = []

    root_node = build_cup_node(root, id_gen, stats)
    all_nodes.append(root_node)

    current_level = [root]

    for depth in range(1, max_depth + 1):
        stats["max_depth"] = depth
        next_level = []
        for parent in current_level:
            try:
                arr = parent.FindAllBuildCache(TreeScope_Children, true_cond, cache_req)
            except comtypes.COMError:
                continue
            if arr is None:
                continue
            for i in range(arr.Length):
                el = arr.GetElement(i)
                node = build_cup_node(el, id_gen, stats)
                all_nodes.append(node)
                next_level.append(el)
        current_level = next_level
        if not current_level:
            break

    return all_nodes


# ---------------------------------------------------------------------------
# Approach B: structured tree via TreeWalker + BuildCache
# ---------------------------------------------------------------------------

def walk_tree(walker, element, cache_req, depth: int, max_depth: int,
              id_gen, stats) -> dict | None:
    if depth > max_depth:
        return None

    node = build_cup_node(element, id_gen, stats)
    stats["max_depth"] = max(stats["max_depth"], depth)

    if depth < max_depth:
        children = []
        try:
            child = walker.GetFirstChildElementBuildCache(element, cache_req)
        except comtypes.COMError:
            child = None

        while child is not None and is_valid_element(child):
            child_node = walk_tree(walker, child, cache_req, depth + 1, max_depth,
                                   id_gen, stats)
            if child_node is not None:
                children.append(child_node)
            try:
                child = walker.GetNextSiblingElementBuildCache(child, cache_req)
            except comtypes.COMError:
                break

        if children:
            node["children"] = children

    return node


# ---------------------------------------------------------------------------
# Approach C: pre-cached subtree via CacheRequest(TreeScope_Subtree)
# ---------------------------------------------------------------------------

def walk_cached_tree(element, depth: int, max_depth: int,
                     id_gen, stats) -> dict | None:
    """Walk a subtree that was fully pre-cached in a single COM call.

    Uses CachedChildren (in-process memory reads) instead of
    GetFirstChild/GetNextSibling (cross-process COM calls per node).
    """
    if depth > max_depth:
        return None

    node = build_cup_node(element, id_gen, stats)
    stats["max_depth"] = max(stats["max_depth"], depth)

    if depth < max_depth:
        children = []
        try:
            cached_children = element.GetCachedChildren()
            if cached_children is not None:
                for i in range(cached_children.Length):
                    child = cached_children.GetElement(i)
                    child_node = walk_cached_tree(child, depth + 1, max_depth,
                                                  id_gen, stats)
                    if child_node is not None:
                        children.append(child_node)
        except (comtypes.COMError, Exception):
            pass

        if children:
            node["children"] = children

    return node


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fast Windows a11y tree benchmark -> CUP format (raw UIA COM)")
    parser.add_argument("--depth", type=int, default=0,
                        help="Max tree depth (0 = unlimited, default: unlimited)")
    parser.add_argument("--app", type=str, default=None,
                        help="Filter to window title containing this string")
    parser.add_argument("--foreground", action="store_true",
                        help="Only walk the foreground window")
    parser.add_argument("--flat", action="store_true",
                        help="Use flat FindAll (no hierarchy)")
    parser.add_argument("--legacy", action="store_true",
                        help="Use old TreeWalker (one COM call per node)")
    parser.add_argument("--json-out", type=str, default=None,
                        help="Write pruned CUP JSON to file")
    parser.add_argument("--full-json-out", type=str, default=None,
                        help="Write full (unpruned) CUP JSON to file")
    parser.add_argument("--compact-out", type=str, default=None,
                        help="Write compact LLM-friendly text to file")
    args = parser.parse_args()

    max_depth = args.depth if args.depth > 0 else 999
    if args.flat:
        mode = "flat FindAll"
    elif args.legacy:
        mode = "TreeWalker (legacy)"
    else:
        mode = "CachedSubtree (one-shot)"
    scope = "foreground" if args.foreground else (f"app={args.app}" if args.app else "all windows")

    print("=== Windows A11y Tree -> CUP Benchmark (raw UIA COM) ===")
    print(f"Max depth : {'unlimited' if args.depth == 0 else args.depth}")
    print(f"Scope     : {scope}")
    print(f"Mode      : {mode}")
    print(f"CUP props : {len(PROP_IDS)} cached per element")
    print()

    # -- Step 1: init UIA COM -------------------------------------------
    t0 = time.perf_counter()
    uia = init_uia()
    live_cr = make_cache_request(uia, element_mode=AutomationElementMode_Full)
    subtree_cr = make_cache_request(uia, element_mode=AutomationElementMode_Full,
                                    tree_scope=TreeScope_Subtree)

    t_init = time.perf_counter() - t0
    print(f"[1] {'Init UIA COM + CacheRequests':33s} : {t_init*1000:8.1f} ms")

    # -- Step 2: enumerate windows via Win32 ----------------------------
    t0 = time.perf_counter()
    app_name = None
    if args.foreground:
        fg = get_foreground_window()
        win_list = [fg]
        app_name = fg[1]
        t_enum = time.perf_counter() - t0
        print(f"[2] GetForegroundWindow (Win32)    : {t_enum*1000:8.1f} ms  (\"{fg[1].encode('ascii', 'replace').decode()}\")")
    else:
        win_list = enum_top_level_windows(visible_only=True)
        t_enum = time.perf_counter() - t0
        print(f"[2] EnumWindows (Win32)           : {t_enum*1000:8.1f} ms  ({len(win_list)} visible windows)")

        # filter by app title
        if args.app:
            win_list = [(h, t) for h, t in win_list if args.app.lower() in t.lower()]
            if not win_list:
                print(f"  No window found matching '{args.app}'")
                return
            print(f"  Matched {len(win_list)} window(s)")
            app_name = win_list[0][1] if len(win_list) == 1 else None

    # -- Step 3: resolve + walk -----------------------------------------
    t0 = time.perf_counter()
    id_gen = itertools.count()
    total_nodes = 0
    all_roles: dict[str, int] = {}
    max_depth_seen = 0

    # Pick cache request: subtree (one-shot) vs element-only (per-node walk)
    use_subtree = not args.flat and not args.legacy
    cr = subtree_cr if use_subtree else live_cr

    roots = []
    for hwnd, title in win_list:
        try:
            el = uia.ElementFromHandleBuildCache(hwnd, cr)
            roots.append((hwnd, title, el))
        except comtypes.COMError:
            pass

    if args.flat:
        all_nodes = []
        for _, _, el in roots:
            stats = {"nodes": 0, "max_depth": 0, "roles": {}}
            nodes = flat_snapshot(uia, el, live_cr, max_depth, id_gen, stats)
            all_nodes.extend(nodes)
            total_nodes += stats["nodes"]
            max_depth_seen = max(max_depth_seen, stats["max_depth"])
            for r, c in stats["roles"].items():
                all_roles[r] = all_roles.get(r, 0) + c
        tree_or_flat = all_nodes
    elif args.legacy:
        walker = uia.ControlViewWalker
        stats = {"nodes": 0, "max_depth": 0, "roles": {}}
        tree = []
        for _, _, el in roots:
            node = walk_tree(walker, el, live_cr, 0, max_depth, id_gen, stats)
            if node:
                tree.append(node)
        total_nodes = stats["nodes"]
        max_depth_seen = stats["max_depth"]
        all_roles = stats["roles"]
        tree_or_flat = tree
    else:
        # Default: walk pre-cached subtree (zero additional COM calls)
        stats = {"nodes": 0, "max_depth": 0, "roles": {}}
        tree = []
        for _, _, el in roots:
            node = walk_cached_tree(el, 0, max_depth, id_gen, stats)
            if node:
                tree.append(node)
        total_nodes = stats["nodes"]
        max_depth_seen = stats["max_depth"]
        all_roles = stats["roles"]
        tree_or_flat = tree

    t_walk = time.perf_counter() - t0

    walk_label = "Resolve + FindAll" if args.flat else ("Resolve + TreeWalk" if args.legacy else "Resolve + CachedSubtree")
    print(f"[3] {walk_label:33s} : {t_walk*1000:8.1f} ms  ({total_nodes} nodes)")

    # -- Step 4: wrap in CUP envelope + serialise -----------------------
    t0 = time.perf_counter()
    envelope = build_envelope(tree_or_flat, app_name=app_name)
    json_str = json.dumps(envelope, ensure_ascii=False)
    t_json = time.perf_counter() - t0
    json_kb = len(json_str) / 1024
    print(f"[4] CUP envelope + JSON           : {t_json*1000:8.1f} ms  ({json_kb:.1f} KB)")

    # -- Summary --------------------------------------------------------
    total = (t_init + t_enum + t_walk + t_json) * 1000
    print()
    print(f"    TOTAL                         : {total:8.1f} ms")
    print(f"    Nodes                         : {total_nodes}")
    print(f"    Max depth reached             : {max_depth_seen}")
    print(f"    Unique roles (UIA)            : {len(all_roles)}")
    print()
    print("  Role distribution (top 15):")
    for role, count in sorted(all_roles.items(), key=lambda kv: -kv[1])[:15]:
        print(f"    {role:30s} {count:6d}")

    if args.json_out:
        pruned_tree = prune_tree(envelope["tree"])
        pruned_envelope = {**envelope, "tree": pruned_tree}
        pruned_str = json.dumps(pruned_envelope, ensure_ascii=False)
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(pruned_envelope, f, indent=2, ensure_ascii=False)
        pruned_kb = len(pruned_str) / 1024
        print(f"\n  Pruned JSON written to {args.json_out} ({pruned_kb:.1f} KB, {total_nodes} -> {pruned_kb:.1f} KB)")

    if args.full_json_out:
        with open(args.full_json_out, "w", encoding="utf-8") as f:
            json.dump(envelope, f, indent=2, ensure_ascii=False)
        print(f"  Full JSON written to {args.full_json_out} ({json_kb:.1f} KB)")

    if args.compact_out:
        compact_str = serialize_compact(envelope)
        with open(args.compact_out, "w", encoding="utf-8") as f:
            f.write(compact_str)
        compact_kb = len(compact_str) / 1024
        ratio = (1 - compact_kb / json_kb) * 100 if json_kb > 0 else 0
        print(f"  Compact written to {args.compact_out} ({compact_kb:.1f} KB, {ratio:.0f}% smaller)")


if __name__ == "__main__":
    main()
