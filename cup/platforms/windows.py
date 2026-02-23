"""
Windows UIA platform adapter for CUP.

Captures the accessibility tree via raw UIA COM interface and maps it to the
canonical CUP schema — roles, states, actions, and platform metadata.

Key optimisations:
  1. Direct UIA COM via comtypes — no wrapper overhead
  2. CacheRequest batches 29 properties (core + states + patterns + ARIA) in one call
  3. Win32 EnumWindows for instant HWND list (skips slow UIA root enumeration)
  4. ElementFromHandleBuildCache to get UIA elements from HWNDs
  5. FindAllBuildCache collapses entire subtree into ONE cross-process call
  6. TreeWalker with BuildCache for structured tree (one call per node, all props)
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import itertools
from typing import Any

import comtypes
import comtypes.client

from cup._base import PlatformAdapter

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
UIA_OrientationPropertyId = 30023
UIA_IsRequiredForFormPropertyId = 30025

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
UIA_RangeValueValuePropertyId = 30047
UIA_RangeValueMinimumPropertyId = 30049
UIA_RangeValueMaximumPropertyId = 30050
UIA_ExpandCollapseExpandCollapseStatePropertyId = 30070
UIA_WindowIsModalPropertyId = 30077
UIA_SelectionItemIsSelectedPropertyId = 30079
UIA_ToggleToggleStatePropertyId = 30086

# ARIA (web content hosted in UIA)
UIA_AriaRolePropertyId = 30101
UIA_AriaPropertiesPropertyId = 30102

# Tree scope / element mode
TreeScope_Element = 1
TreeScope_Children = 2
TreeScope_Subtree = 7

AutomationElementMode_None = 0
AutomationElementMode_Full = 1

# All properties to cache in a single COM call
PROP_IDS = [
    # Core (3)
    UIA_NamePropertyId,
    UIA_ControlTypePropertyId,
    UIA_BoundingRectanglePropertyId,
    # State / identification (7)
    UIA_IsEnabledPropertyId,
    UIA_HasKeyboardFocusPropertyId,
    UIA_IsOffscreenPropertyId,
    UIA_AutomationIdPropertyId,
    UIA_ClassNamePropertyId,
    UIA_HelpTextPropertyId,
    UIA_OrientationPropertyId,
    UIA_IsRequiredForFormPropertyId,
    # Pattern availability (7)
    UIA_IsInvokePatternAvailablePropertyId,
    UIA_IsTogglePatternAvailablePropertyId,
    UIA_IsExpandCollapsePatternAvailablePropertyId,
    UIA_IsValuePatternAvailablePropertyId,
    UIA_IsSelectionItemPatternAvailablePropertyId,
    UIA_IsScrollPatternAvailablePropertyId,
    UIA_IsRangeValuePatternAvailablePropertyId,
    # Pattern state values (8)
    UIA_ToggleToggleStatePropertyId,
    UIA_ExpandCollapseExpandCollapseStatePropertyId,
    UIA_SelectionItemIsSelectedPropertyId,
    UIA_ValueIsReadOnlyPropertyId,
    UIA_ValueValuePropertyId,
    UIA_RangeValueValuePropertyId,
    UIA_RangeValueMinimumPropertyId,
    UIA_RangeValueMaximumPropertyId,
    UIA_WindowIsModalPropertyId,
    # ARIA (2)
    UIA_AriaRolePropertyId,
    UIA_AriaPropertiesPropertyId,
]


# ---------------------------------------------------------------------------
# UIA ControlType display names (for benchmark stats)
# ---------------------------------------------------------------------------

CONTROL_TYPES = {
    50000: "Button",
    50001: "Calendar",
    50002: "CheckBox",
    50003: "ComboBox",
    50004: "Edit",
    50005: "Hyperlink",
    50006: "Image",
    50007: "ListItem",
    50008: "List",
    50009: "Menu",
    50010: "MenuBar",
    50011: "MenuItem",
    50012: "ProgressBar",
    50013: "RadioButton",
    50014: "ScrollBar",
    50015: "Slider",
    50016: "Spinner",
    50017: "StatusBar",
    50018: "Tab",
    50019: "TabItem",
    50020: "Text",
    50021: "ToolBar",
    50022: "ToolTip",
    50023: "Tree",
    50024: "TreeItem",
    50025: "Custom",
    50026: "Group",
    50027: "Thumb",
    50028: "DataGrid",
    50029: "DataItem",
    50030: "Document",
    50031: "SplitButton",
    50032: "Window",
    50033: "Pane",
    50034: "Header",
    50035: "HeaderItem",
    50036: "Table",
    50037: "TitleBar",
    50038: "Separator",
    50039: "SemanticZoom",
    50040: "AppBar",
}


# ---------------------------------------------------------------------------
# CUP role mapping: UIA ControlType ID -> canonical CUP role
# ---------------------------------------------------------------------------

CUP_ROLES = {
    50000: "button",  # Button
    50001: "grid",  # Calendar
    50002: "checkbox",  # CheckBox
    50003: "combobox",  # ComboBox
    50004: "textbox",  # Edit
    50005: "link",  # Hyperlink
    50006: "img",  # Image
    50007: "listitem",  # ListItem
    50008: "list",  # List
    50009: "menu",  # Menu
    50010: "menubar",  # MenuBar
    50011: "menuitem",  # MenuItem
    50012: "progressbar",  # ProgressBar
    50013: "radio",  # RadioButton
    50014: "scrollbar",  # ScrollBar
    50015: "slider",  # Slider
    50016: "spinbutton",  # Spinner
    50017: "status",  # StatusBar
    50018: "tablist",  # Tab (the container)
    50019: "tab",  # TabItem
    50020: "text",  # Text
    50021: "toolbar",  # ToolBar
    50022: "tooltip",  # ToolTip
    50023: "tree",  # Tree
    50024: "treeitem",  # TreeItem
    50025: "generic",  # Custom
    50026: "group",  # Group
    50027: "generic",  # Thumb
    50028: "grid",  # DataGrid
    50029: "row",  # DataItem
    50030: "document",  # Document
    50031: "button",  # SplitButton
    50032: "window",  # Window
    50033: "generic",  # Pane — context-dependent, refined below
    50034: "group",  # Header
    50035: "columnheader",  # HeaderItem
    50036: "table",  # Table
    50037: "titlebar",  # TitleBar
    50038: "separator",  # Separator
    50039: "generic",  # SemanticZoom
    50040: "toolbar",  # AppBar
}

# Roles that accept text input (for adding "type" action)
TEXT_INPUT_ROLES = {"textbox", "searchbox", "combobox", "document"}


# ---------------------------------------------------------------------------
# Win32: fast window enumeration via EnumWindows
# ---------------------------------------------------------------------------

user32 = ctypes.windll.user32
WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.wintypes.BOOL, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)


def _win32_enum_windows(*, visible_only: bool = True) -> list[tuple[int, str]]:
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


def _win32_foreground_window() -> tuple[int, str]:
    """Return (hwnd, title) of the current foreground window."""
    hwnd = user32.GetForegroundWindow()
    buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, buf, 512)
    return (hwnd, buf.value)


def _win32_screen_size() -> tuple[int, int]:
    """Return (width, height) of the primary monitor in pixels."""
    return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)


def _win32_screen_scale() -> float:
    """Return the display scale factor (e.g. 1.5 for 150% DPI)."""
    try:
        dpi = ctypes.windll.shcore.GetDpiForSystem()
        return dpi / 96.0
    except Exception:
        return 1.0


def get_window_pid(hwnd: int) -> int:
    """Return the process ID for a window handle."""
    pid = ctypes.wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def _win32_get_window_rect(hwnd: int) -> dict[str, int] | None:
    """Return {x, y, w, h} for a window via Win32 GetWindowRect."""
    rect = ctypes.wintypes.RECT()
    if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return {
            "x": rect.left,
            "y": rect.top,
            "w": rect.right - rect.left,
            "h": rect.bottom - rect.top,
        }
    return None


def _win32_find_desktop_hwnd() -> int | None:
    """Find the desktop window (Progman or WorkerW with SHELLDLL_DefView child)."""
    # Try Progman first (classic desktop host)
    progman = user32.FindWindowW("Progman", None)
    if progman:
        shell_view = user32.FindWindowExW(progman, 0, "SHELLDLL_DefView", None)
        if shell_view:
            return progman

    # Fallback: enumerate WorkerW windows (Windows 10/11 wallpaper engine)
    result: list[int | None] = [None]

    @WNDENUMPROC
    def _find_worker(hwnd, _lparam):
        shell_view = user32.FindWindowExW(hwnd, 0, "SHELLDLL_DefView", None)
        if shell_view:
            result[0] = hwnd
            return False  # stop
        return True

    user32.EnumWindows(_find_worker, 0)
    return result[0]


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


def make_cache_request(
    uia, *, element_mode=AutomationElementMode_Full, tree_scope=TreeScope_Element
):
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


def _cached_float(el, pid, default=None):
    """Read a cached float UIA property."""
    try:
        v = el.GetCachedPropertyValue(pid)
        if v is None:
            return default
        return float(v)
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
        _ = el.CachedControlType
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# CUP node builder
# ---------------------------------------------------------------------------


def build_cup_node(el, id_gen, stats) -> dict:
    """Build a CUP-formatted node dict from a cached UIA element.

    Reads all 29 cached properties and maps them to canonical CUP fields:
    role, states, actions, value, attributes, description, and platform metadata.
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
            bounds = {"x": int(rect[0]), "y": int(rect[1]), "w": int(rect[2]), "h": int(rect[3])}
        else:
            bounds = None
    except Exception:
        bounds = None

    # Stats tracking (uses UIA names for the benchmark report)
    ct_name = CONTROL_TYPES.get(ct, f"Unknown({ct})")
    stats["roles"][ct_name] = stats["roles"].get(ct_name, 0) + 1

    # ── State properties ──
    is_enabled = _cached_bool(el, UIA_IsEnabledPropertyId, True)
    has_focus = _cached_bool(el, UIA_HasKeyboardFocusPropertyId, False)
    is_offscreen = _cached_bool(el, UIA_IsOffscreenPropertyId, False)
    is_required = _cached_bool(el, UIA_IsRequiredForFormPropertyId, False)
    is_modal = _cached_bool(el, UIA_WindowIsModalPropertyId, False)

    # ── Pattern availability ──
    has_invoke = _cached_bool(el, UIA_IsInvokePatternAvailablePropertyId, False)
    has_toggle = _cached_bool(el, UIA_IsTogglePatternAvailablePropertyId, False)
    has_expand = _cached_bool(el, UIA_IsExpandCollapsePatternAvailablePropertyId, False)
    has_value = _cached_bool(el, UIA_IsValuePatternAvailablePropertyId, False)
    has_sel_item = _cached_bool(el, UIA_IsSelectionItemPatternAvailablePropertyId, False)
    has_scroll = _cached_bool(el, UIA_IsScrollPatternAvailablePropertyId, False)
    has_range = _cached_bool(el, UIA_IsRangeValuePatternAvailablePropertyId, False)

    # ── Pattern state values ──
    toggle_state = _cached_int(el, UIA_ToggleToggleStatePropertyId, -1)
    expand_state = _cached_int(el, UIA_ExpandCollapseExpandCollapseStatePropertyId, -1)
    is_selected = _cached_bool(el, UIA_SelectionItemIsSelectedPropertyId, False)
    val_readonly = _cached_bool(el, UIA_ValueIsReadOnlyPropertyId, False) if has_value else False
    val_str = _cached_str(el, UIA_ValueValuePropertyId) if has_value else ""

    # ── Identification ──
    automation_id = _cached_str(el, UIA_AutomationIdPropertyId)
    class_name = _cached_str(el, UIA_ClassNamePropertyId)
    help_text = _cached_str(el, UIA_HelpTextPropertyId)

    # ── ARIA properties (web content hosted in UIA) ──
    aria_role = _cached_str(el, UIA_AriaRolePropertyId)
    aria_props_str = _cached_str(el, UIA_AriaPropertiesPropertyId)
    aria_props: dict[str, str] = {}
    if aria_props_str:
        for pair in aria_props_str.split(";"):
            if "=" in pair:
                k, v = pair.split("=", 1)
                aria_props[k.strip()] = v.strip()

    # ── Role (ARIA-mapped) ──
    role = CUP_ROLES.get(ct, "generic")
    if ct == 50033 and name:  # Pane with name -> region
        role = "region"

    # Refine role from ARIA (web content in UIA) — only override ambiguous roles
    if aria_role and role in ("generic", "group", "text", "region"):
        ARIA_ROLE_MAP = {
            "heading": "heading",
            "dialog": "dialog",
            "alert": "alert",
            "alertdialog": "alertdialog",
            "searchbox": "searchbox",
            "navigation": "navigation",
            "main": "main",
            "search": "search",
            "banner": "banner",
            "contentinfo": "contentinfo",
            "complementary": "complementary",
            "region": "region",
            "form": "form",
            "cell": "cell",
            "gridcell": "cell",
            "switch": "switch",
            "tab": "tab",
            "tabpanel": "tabpanel",
            "log": "log",
            "status": "status",
            "timer": "timer",
            "marquee": "marquee",
        }
        if aria_role in ARIA_ROLE_MAP:
            role = ARIA_ROLE_MAP[aria_role]

    # MenuItem subrole refinement (no ARIA needed)
    if ct == 50011:  # MenuItem
        if has_toggle:
            role = "menuitemcheckbox"
        elif has_sel_item:
            role = "menuitemradio"

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
            # Toggle on Button = pressed (toggle button), on CheckBox = checked
            if ct == 50000:  # Button
                states.append("pressed")
            else:
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
    if is_required:
        states.append("required")
    if is_modal:
        states.append("modal")
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

    # ── Attributes ──
    attrs: dict = {}

    # Heading level from ARIA properties
    if role == "heading" and "level" in aria_props:
        try:
            attrs["level"] = int(aria_props["level"])
        except ValueError:
            pass

    # Range widget min/max/now
    if has_range:
        range_min = _cached_float(el, UIA_RangeValueMinimumPropertyId)
        range_max = _cached_float(el, UIA_RangeValueMaximumPropertyId)
        range_val = _cached_float(el, UIA_RangeValueValuePropertyId)
        if range_min is not None:
            attrs["valueMin"] = range_min
        if range_max is not None:
            attrs["valueMax"] = range_max
        if range_val is not None:
            attrs["valueNow"] = range_val

    # Orientation
    orientation = _cached_int(el, UIA_OrientationPropertyId, -1)
    if orientation == 1 and role in ("scrollbar", "slider", "separator", "toolbar", "tablist"):
        attrs["orientation"] = "horizontal"
    elif orientation == 2 and role in ("scrollbar", "slider", "separator", "toolbar", "tablist"):
        attrs["orientation"] = "vertical"

    # Placeholder from ARIA properties (web content)
    if role in ("textbox", "searchbox", "combobox") and "placeholder" in aria_props:
        attrs["placeholder"] = aria_props["placeholder"][:200]

    # URL for links from Value pattern string
    if role == "link" and val_str:
        attrs["url"] = val_str[:500]

    # ── Assemble CUP node ──
    node = {
        "id": f"e{next(id_gen)}",
        "role": role,
        "name": name[:200],
    }

    # Optional fields — omit when empty to keep payload compact
    if help_text:
        node["description"] = help_text[:200]
    if val_str and role in (
        "textbox",
        "searchbox",
        "combobox",
        "spinbutton",
        "slider",
        "progressbar",
        "document",
    ):
        node["value"] = val_str[:200]
    if bounds:
        node["bounds"] = bounds
    if states:
        node["states"] = states
    if actions:
        node["actions"] = actions
    if attrs:
        node["attributes"] = attrs

    # ── Platform extension (windows-specific raw data) ──
    patterns = []
    if has_invoke:
        patterns.append("Invoke")
    if has_toggle:
        patterns.append("Toggle")
    if has_expand:
        patterns.append("ExpandCollapse")
    if has_value:
        patterns.append("Value")
    if has_sel_item:
        patterns.append("SelectionItem")
    if has_scroll:
        patterns.append("Scroll")
    if has_range:
        patterns.append("RangeValue")

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


def walk_tree(walker, element, cache_req, depth: int, max_depth: int, id_gen, stats) -> dict | None:
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
            child_node = walk_tree(walker, child, cache_req, depth + 1, max_depth, id_gen, stats)
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


def walk_cached_tree(element, depth: int, max_depth: int, id_gen, stats, refs) -> dict | None:
    """Walk a subtree that was fully pre-cached in a single COM call.

    Uses CachedChildren (in-process memory reads) instead of
    GetFirstChild/GetNextSibling (cross-process COM calls per node).
    """
    if depth > max_depth:
        return None

    node = build_cup_node(element, id_gen, stats)
    stats["max_depth"] = max(stats["max_depth"], depth)

    refs[node["id"]] = element

    if depth < max_depth:
        children = []
        try:
            cached_children = element.GetCachedChildren()
            if cached_children is not None:
                for i in range(cached_children.Length):
                    child = cached_children.GetElement(i)
                    child_node = walk_cached_tree(child, depth + 1, max_depth, id_gen, stats, refs)
                    if child_node is not None:
                        children.append(child_node)
        except (comtypes.COMError, Exception):
            pass

        if children:
            node["children"] = children

    return node


# ---------------------------------------------------------------------------
# WindowsAdapter — PlatformAdapter implementation
# ---------------------------------------------------------------------------


class WindowsAdapter(PlatformAdapter):
    """CUP adapter for Windows via UIA COM."""

    def __init__(self):
        self._uia = None
        self._subtree_cr = None

    @property
    def platform_name(self) -> str:
        return "windows"

    def initialize(self) -> None:
        if self._uia is not None:
            return  # already initialized
        self._uia = init_uia()
        self._subtree_cr = make_cache_request(
            self._uia,
            element_mode=AutomationElementMode_Full,
            tree_scope=TreeScope_Subtree,
        )

    def get_screen_info(self) -> tuple[int, int, float]:
        w, h = _win32_screen_size()
        scale = _win32_screen_scale()
        return w, h, scale

    def get_foreground_window(self) -> dict[str, Any]:
        hwnd, title = _win32_foreground_window()
        pid = get_window_pid(hwnd)
        return {
            "handle": hwnd,
            "title": title,
            "pid": pid,
            "bundle_id": None,
        }

    def get_all_windows(self) -> list[dict[str, Any]]:
        results = []
        for hwnd, title in _win32_enum_windows(visible_only=True):
            results.append(
                {
                    "handle": hwnd,
                    "title": title,
                    "pid": get_window_pid(hwnd),
                    "bundle_id": None,
                }
            )
        return results

    def get_window_list(self) -> list[dict[str, Any]]:
        fg_hwnd = user32.GetForegroundWindow()
        results = []
        for hwnd, title in _win32_enum_windows(visible_only=True):
            if not title:
                continue
            results.append(
                {
                    "title": title,
                    "pid": get_window_pid(hwnd),
                    "bundle_id": None,
                    "foreground": hwnd == fg_hwnd,
                    "bounds": _win32_get_window_rect(hwnd),
                }
            )
        return results

    def get_desktop_window(self) -> dict[str, Any] | None:
        hwnd = _win32_find_desktop_hwnd()
        if hwnd is None:
            return None
        return {
            "handle": hwnd,
            "title": "Desktop",
            "pid": get_window_pid(hwnd),
            "bundle_id": None,
        }

    # Chromium/Electron apps lazily initialise their accessibility tree.
    # The renderer won't expose web content to UIA until a11y is triggered.
    # We detect this by checking for a "Document" node (the web content
    # root) — browser chrome alone (toolbar, tabs) can produce 40+ nodes
    # but won't include a Document until the renderer initialises a11y.
    _SPARSE_TREE_THRESHOLD = 30

    def capture_tree(
        self,
        windows: list[dict[str, Any]],
        *,
        max_depth: int = 999,
    ) -> tuple[list[dict], dict, dict[str, Any]]:
        self.initialize()
        tree, stats, refs = self._walk_windows(windows, max_depth=max_depth)

        if len(windows) == 1 and self._tree_needs_poke(stats):
            hwnd = windows[0]["handle"]
            self._poke_window(hwnd)
            tree, stats, refs = self._walk_windows(windows, max_depth=max_depth)

        return tree, stats, refs

    @staticmethod
    def _tree_needs_poke(stats: dict) -> bool:
        """Decide whether the captured tree looks uninitialised.

        Two heuristics (either triggers a retry):
        1. Very few nodes overall (original threshold) — catches apps
           that returned almost nothing.
        2. Has browser-chrome roles (ToolBar, TabItem) but no Document —
           Chromium/Electron rendered the shell but the web content
           a11y tree hasn't been built yet.
        """
        if stats["nodes"] < WindowsAdapter._SPARSE_TREE_THRESHOLD:
            return True

        roles = stats.get("roles", {})
        has_chrome = bool(roles.get("ToolBar") or roles.get("TabItem"))
        has_document = bool(roles.get("Document"))
        if has_chrome and not has_document:
            return True

        return False

    def _walk_windows(
        self,
        windows: list[dict[str, Any]],
        *,
        max_depth: int = 999,
    ) -> tuple[list[dict], dict, dict[str, Any]]:
        """Walk the UIA tree for the given windows."""
        id_gen = itertools.count()
        stats: dict = {"nodes": 0, "max_depth": 0, "roles": {}}
        refs: dict[str, Any] = {}
        tree: list[dict] = []
        for win in windows:
            hwnd = win["handle"]
            try:
                el = self._uia.ElementFromHandleBuildCache(hwnd, self._subtree_cr)
            except Exception:
                continue
            node = walk_cached_tree(el, 0, max_depth, id_gen, stats, refs)
            if node:
                tree.append(node)
        return tree, stats, refs

    @staticmethod
    def _poke_window(hwnd: int) -> None:
        """Nudge a window to force Chromium to initialise its a11y tree.

        SetForegroundWindow triggers the renderer's accessibility mode.
        A short sleep gives Chromium time to build the tree before we retry.
        """
        import time

        user32.SetForegroundWindow(hwnd)
        time.sleep(0.3)
