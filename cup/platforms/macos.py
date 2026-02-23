"""
macOS AXUIElement platform adapter for CUP.

Captures the accessibility tree via pyobjc AXUIElement API and maps it to the
canonical CUP schema — roles, states, actions, and platform metadata.

Requires macOS accessibility permissions:
  System Settings > Privacy & Security > Accessibility > (add Terminal / Python)

Dependencies:
  pip install pyobjc-framework-ApplicationServices pyobjc-framework-Cocoa pyobjc-framework-Quartz
"""

from __future__ import annotations

import concurrent.futures
import itertools
from typing import Any

from AppKit import NSApplicationActivationPolicyRegular, NSArray, NSScreen, NSWorkspace
from ApplicationServices import (
    AXUIElementCopyActionNames,
    AXUIElementCopyAttributeValue,
    AXUIElementCopyMultipleAttributeValues,
    AXUIElementCreateApplication,
    AXUIElementIsAttributeSettable,
    AXValueGetType,
    AXValueGetValue,
    kAXChildrenAttribute,
    kAXDescriptionAttribute,
    kAXElementBusyAttribute,
    kAXEnabledAttribute,
    kAXErrorSuccess,
    kAXExpandedAttribute,
    kAXFocusedAttribute,
    kAXFocusedWindowAttribute,
    kAXHelpAttribute,
    kAXIdentifierAttribute,
    kAXMainWindowAttribute,
    kAXModalAttribute,
    kAXPositionAttribute,
    kAXRoleAttribute,
    kAXSelectedAttribute,
    kAXSizeAttribute,
    kAXSubroleAttribute,
    kAXTitleAttribute,
    kAXValueAttribute,
    kAXValueCGPointType,
    kAXValueCGSizeType,
    kAXWindowsAttribute,
)

from cup._base import PlatformAdapter

# ---------------------------------------------------------------------------
# AXRole -> CUP role mapping
# ---------------------------------------------------------------------------

# Primary: AXRole string -> CUP role
CUP_ROLES: dict[str, str] = {
    "AXApplication": "application",
    "AXWindow": "window",
    "AXButton": "button",
    "AXCheckBox": "checkbox",
    "AXRadioButton": "radio",
    "AXComboBox": "combobox",
    "AXPopUpButton": "combobox",
    "AXTextField": "textbox",
    "AXTextArea": "textbox",
    "AXStaticText": "text",
    "AXImage": "img",
    "AXLink": "link",
    "AXList": "list",
    "AXOutline": "tree",
    "AXTable": "table",
    "AXTabGroup": "tablist",
    "AXSlider": "slider",
    "AXProgressIndicator": "progressbar",
    "AXMenu": "menu",
    "AXMenuBar": "menubar",
    "AXMenuBarItem": "menuitem",
    "AXMenuItem": "menuitem",
    "AXToolbar": "toolbar",
    "AXScrollBar": "scrollbar",
    "AXScrollArea": "generic",
    "AXGroup": "group",
    "AXSplitGroup": "group",
    "AXSplitter": "separator",
    "AXHeading": "heading",
    "AXWebArea": "document",
    "AXCell": "cell",
    "AXRow": "row",
    "AXColumn": "columnheader",
    "AXSheet": "alertdialog",
    "AXDrawer": "complementary",
    "AXGrowArea": "generic",
    "AXValueIndicator": "generic",
    "AXIncrementor": "spinbutton",
    "AXHelpTag": "tooltip",
    "AXColorWell": "button",
    "AXDisclosureTriangle": "button",
    "AXDateField": "textbox",
    "AXBrowser": "tree",
    "AXBusyIndicator": "progressbar",
    "AXRuler": "generic",
    "AXRulerMarker": "generic",
    "AXRelevanceIndicator": "progressbar",
    "AXLevelIndicator": "slider",
    "AXLayoutArea": "group",
    "AXLayoutItem": "generic",
    "AXHandle": "generic",
    "AXMatte": "generic",
    "AXUnknown": "generic",
    "AXListMarker": "text",
    "AXMenuButton": "button",
    "AXRadioGroup": "group",
}

# Subrole refinements: (AXRole, AXSubrole) -> CUP role
CUP_SUBROLE_OVERRIDES: dict[tuple[str, str], str] = {
    # AXGroup subroles
    ("AXGroup", "AXApplicationAlert"): "alert",
    ("AXGroup", "AXApplicationDialog"): "dialog",
    ("AXGroup", "AXApplicationStatus"): "status",
    ("AXGroup", "AXLandmarkNavigation"): "navigation",
    ("AXGroup", "AXLandmarkSearch"): "search",
    ("AXGroup", "AXLandmarkRegion"): "region",
    ("AXGroup", "AXLandmarkMain"): "main",
    ("AXGroup", "AXLandmarkComplementary"): "complementary",
    ("AXGroup", "AXLandmarkContentInfo"): "contentinfo",
    ("AXGroup", "AXLandmarkBanner"): "banner",
    ("AXGroup", "AXDocument"): "document",
    ("AXGroup", "AXWebApplication"): "application",
    ("AXGroup", "AXTab"): "tabpanel",
    # AXWindow subroles
    ("AXWindow", "AXDialog"): "dialog",
    ("AXWindow", "AXFloatingWindow"): "dialog",
    ("AXWindow", "AXSystemDialog"): "dialog",
    ("AXWindow", "AXSystemFloatingWindow"): "dialog",
    # AXButton subroles
    ("AXButton", "AXCloseButton"): "button",
    ("AXButton", "AXMinimizeButton"): "button",
    ("AXButton", "AXFullScreenButton"): "button",
    # AXRadioButton used as tab
    ("AXRadioButton", "AXTabButton"): "tab",
    # AXMenuItem subroles
    ("AXMenuItem", "AXMenuItemCheckbox"): "menuitemcheckbox",
    ("AXMenuItem", "AXMenuItemRadio"): "menuitemradio",
    # AXTextField subroles
    ("AXTextField", "AXSearchField"): "searchbox",
    ("AXTextField", "AXSecureTextField"): "textbox",
    # AXStaticText as status
    ("AXStaticText", "AXApplicationStatus"): "status",
    # AXRow in outlines -> treeitem (parity with Windows TreeItem)
    ("AXRow", "AXOutlineRow"): "treeitem",
    # AXCheckBox as toggle switch
    ("AXCheckBox", "AXToggle"): "switch",
    ("AXCheckBox", "AXSwitch"): "switch",
}

# Roles that accept text input
TEXT_INPUT_ROLES = {"textbox", "searchbox", "combobox", "document"}

# Roles representing toggle-like elements
TOGGLE_ROLES = {"checkbox", "switch", "menuitemcheckbox"}

# AX roles where AXExpanded is semantically meaningful.
# Chromium/Electron apps set AXExpanded on nearly every element, so we
# restrict this to AX roles that genuinely expand/collapse.
EXPANDABLE_AX_ROLES = {
    "AXComboBox",
    "AXPopUpButton",
    "AXOutline",
    "AXDisclosureTriangle",
    "AXMenu",
    "AXMenuItem",
    "AXMenuBarItem",
    "AXRow",
    "AXBrowser",
    "AXSheet",
    "AXDrawer",
    "AXTabGroup",
}

# AX roles where AXUIElementCopyActionNames is skipped for performance.
# These roles never produce meaningful CUP actions from their AX action list
# (their only AX actions are AXScrollToVisible/AXShowMenu which we skip anyway).
# Actions like "scroll" for AXScrollArea are derived from the role, not from AX.
_SKIP_ACTIONS_AX_ROLES = {
    "AXStaticText",
    "AXHeading",
    "AXColumn",
    "AXScrollArea",
    "AXSplitGroup",
    "AXSplitter",
    "AXGrowArea",
    "AXValueIndicator",
    "AXRuler",
    "AXRulerMarker",
    "AXLayoutArea",
    "AXLayoutItem",
    "AXHandle",
    "AXMatte",
    "AXUnknown",
    "AXListMarker",
    "AXBusyIndicator",
    "AXRelevanceIndicator",
    "AXLevelIndicator",
    "AXWebArea",
    # Note: AXImage is NOT skipped — clickable images (e.g. avatars) have AXPress.
}


# ---------------------------------------------------------------------------
# AX attribute helpers
# ---------------------------------------------------------------------------

# Attributes to batch-read per element via AXUIElementCopyMultipleAttributeValues.
# Order matters — indices are used to unpack the results array.
_BATCH_ATTRS_LIST = [
    kAXRoleAttribute,  # 0
    kAXSubroleAttribute,  # 1
    kAXTitleAttribute,  # 2
    kAXDescriptionAttribute,  # 3
    kAXHelpAttribute,  # 4
    kAXIdentifierAttribute,  # 5
    kAXValueAttribute,  # 6
    kAXEnabledAttribute,  # 7
    kAXFocusedAttribute,  # 8
    kAXSelectedAttribute,  # 9
    kAXExpandedAttribute,  # 10
    kAXElementBusyAttribute,  # 11
    kAXModalAttribute,  # 12
    kAXPositionAttribute,  # 13
    kAXSizeAttribute,  # 14
    "AXRequired",  # 15
    "AXIsEditable",  # 16
    kAXChildrenAttribute,  # 17
]
_BATCH_ATTRS = NSArray.arrayWithArray_(_BATCH_ATTRS_LIST)
_BATCH_IDX = {name: i for i, name in enumerate(_BATCH_ATTRS_LIST)}

# AXValueGetType returns 5 for error sentinels (kAXValueAXErrorType)
_AX_VALUE_ERROR_TYPE = 5


def _is_ax_error(val) -> bool:
    """Check if a batch-read value is an error sentinel."""
    if val is None:
        return True
    try:
        return AXValueGetType(val) == _AX_VALUE_ERROR_TYPE
    except Exception:
        return False


def _batch_read(element) -> list:
    """Read all standard attributes in one cross-process call.

    Returns a list of values aligned with _BATCH_ATTRS_LIST.
    Error sentinels are replaced with None.
    """
    try:
        err, values = AXUIElementCopyMultipleAttributeValues(element, _BATCH_ATTRS, 0, None)
        if err != kAXErrorSuccess or values is None:
            return [None] * len(_BATCH_ATTRS_LIST)
        return [None if _is_ax_error(v) else v for v in values]
    except Exception:
        return [None] * len(_BATCH_ATTRS_LIST)


def _get_attr(element, attr: str, default=None):
    """Safely read a single AX attribute (used for non-batched reads)."""
    try:
        err, value = AXUIElementCopyAttributeValue(element, attr, None)
        if err == kAXErrorSuccess and value is not None:
            return value
    except Exception:
        pass
    return default


def _is_settable(element, attr: str) -> bool:
    """Check if an attribute is settable on an element."""
    try:
        err, settable = AXUIElementIsAttributeSettable(element, attr, None)
        if err == kAXErrorSuccess:
            return bool(settable)
    except Exception:
        pass
    return False


def _unpack_bounds(pos_ref, size_ref) -> dict | None:
    """Extract {x, y, w, h} from AXPosition + AXSize value refs."""
    if pos_ref is None or size_ref is None:
        return None
    try:
        _, point = AXValueGetValue(pos_ref, kAXValueCGPointType, None)
        _, size = AXValueGetValue(size_ref, kAXValueCGSizeType, None)
        if point is not None and size is not None:
            return {
                "x": int(point.x),
                "y": int(point.y),
                "w": int(size.width),
                "h": int(size.height),
            }
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Screen metrics
# ---------------------------------------------------------------------------


def _macos_screen_info() -> tuple[int, int, float]:
    """Return (width, height, scale) of the primary display.

    Width/height are in logical points (macOS coordinates).
    Scale is the backing scale factor (2.0 on Retina, 1.0 on non-Retina).
    """
    screen = NSScreen.mainScreen()
    if screen is None:
        from Quartz import CGDisplayBounds, CGMainDisplayID

        bounds = CGDisplayBounds(CGMainDisplayID())
        return int(bounds.size.width), int(bounds.size.height), 1.0
    frame = screen.frame()
    scale = screen.backingScaleFactor()
    return int(frame.size.width), int(frame.size.height), float(scale)


# ---------------------------------------------------------------------------
# Window enumeration
# ---------------------------------------------------------------------------


def _macos_foreground_app() -> tuple[int, str, str | None]:
    """Return (pid, app_name, bundle_id) of the frontmost application."""
    workspace = NSWorkspace.sharedWorkspace()
    app = workspace.frontmostApplication()
    return (
        app.processIdentifier(),
        app.localizedName() or "",
        app.bundleIdentifier(),
    )


def _macos_visible_apps() -> list[tuple[int, str, str | None]]:
    """Return [(pid, app_name, bundle_id)] for all visible (regular) apps."""
    workspace = NSWorkspace.sharedWorkspace()
    apps = []
    for app in workspace.runningApplications():
        if app.activationPolicy() == NSApplicationActivationPolicyRegular:
            apps.append(
                (
                    app.processIdentifier(),
                    app.localizedName() or "",
                    app.bundleIdentifier(),
                )
            )
    return apps


def _macos_windows_for_app(pid: int):
    """Return list of AXWindow elements for an app, or empty list."""
    app_ref = AXUIElementCreateApplication(pid)
    windows = _get_attr(app_ref, kAXWindowsAttribute)
    if windows is not None:
        return list(windows)
    return []


def _macos_focused_window(pid: int):
    """Return the focused window AXUIElement for an app, or None."""
    app_ref = AXUIElementCreateApplication(pid)
    win = _get_attr(app_ref, kAXFocusedWindowAttribute)
    if win is not None:
        return win
    return _get_attr(app_ref, kAXMainWindowAttribute)


# ---------------------------------------------------------------------------
# CUP node builder
# ---------------------------------------------------------------------------


def build_cup_node(element, id_gen, stats: dict) -> tuple[dict, list] | None:
    """Build a CUP-formatted node from a macOS AXUIElement.

    Uses batch attribute reading for performance — a single cross-process call
    fetches all 18 standard attributes (including children) instead of
    individual calls per attribute.

    Returns (node_dict, children_refs) or None if the element has no role.
    """
    stats["nodes"] += 1

    # ── Batch-read all standard attributes in one call ──
    vals = _batch_read(element)

    # ── Core properties ──
    ax_role = vals[0]  # kAXRoleAttribute
    if not ax_role or not isinstance(ax_role, str):
        return None

    ax_subrole = vals[1]  # kAXSubroleAttribute
    if ax_subrole is not None and not isinstance(ax_subrole, str):
        ax_subrole = None

    title = vals[2]  # kAXTitleAttribute
    if title is not None and not isinstance(title, str):
        title = None

    description = vals[3]  # kAXDescriptionAttribute
    if description is not None and not isinstance(description, str):
        description = None

    help_text = vals[4]  # kAXHelpAttribute
    if help_text is not None and not isinstance(help_text, str):
        help_text = None

    ax_identifier = vals[5]  # kAXIdentifierAttribute
    if ax_identifier is not None and not isinstance(ax_identifier, str):
        ax_identifier = None

    raw_value = vals[6]  # kAXValueAttribute

    # Name: prefer title, fall back to description.
    # For AXStaticText, the visible text is often in AXValue (native macOS apps
    # like System Settings), so use that as final fallback for text elements.
    name = title or description or ""
    if not name and ax_role in ("AXStaticText", "AXHeading"):
        if raw_value is not None and isinstance(raw_value, str):
            name = raw_value

    # Bounds from AXPosition + AXSize
    bounds = _unpack_bounds(vals[13], vals[14])

    # Stats tracking
    role_key = f"{ax_role}:{ax_subrole}" if ax_subrole else ax_role
    stats["roles"][role_key] = stats["roles"].get(role_key, 0) + 1

    # ── Role mapping ──
    role = CUP_SUBROLE_OVERRIDES.get((ax_role, ax_subrole))
    if role is None:
        role = CUP_ROLES.get(ax_role, "generic")

    # ── State properties (from batch values) ──
    is_enabled_val = vals[7]  # kAXEnabledAttribute
    is_enabled = bool(is_enabled_val) if is_enabled_val is not None else True
    is_focused = bool(vals[8])  # kAXFocusedAttribute
    is_selected = bool(vals[9])  # kAXSelectedAttribute
    is_busy = bool(vals[11])  # kAXElementBusyAttribute
    is_modal = bool(vals[12])  # kAXModalAttribute

    # Expanded state — only meaningful for certain AX roles (Chromium/Electron
    # apps set AXExpanded on nearly every element, causing noise)
    expanded_val = vals[10]  # kAXExpandedAttribute
    has_expanded = ax_role in EXPANDABLE_AX_ROLES and expanded_val is not None
    is_expanded = bool(expanded_val) if has_expanded else None

    # Required (from batch)
    is_required = bool(vals[15])  # AXRequired

    # Value as string
    val_str = ""
    if raw_value is not None:
        try:
            val_str = str(raw_value)
        except Exception:
            pass

    # Editable (from batch, with settable fallback)
    is_editable = bool(vals[16])  # AXIsEditable
    if not is_editable and role in TEXT_INPUT_ROLES:
        is_editable = _is_settable(element, kAXValueAttribute)

    # ── Offscreen detection ──
    # macOS has no IsOffscreen property, so we check bounds against screen rect
    is_offscreen = False
    if bounds:
        screen_w = stats.get("screen_w", 99999)
        screen_h = stats.get("screen_h", 99999)
        bx, by, bw, bh = bounds["x"], bounds["y"], bounds["w"], bounds["h"]
        # Element is offscreen if entirely outside screen or has zero size
        if bw <= 0 or bh <= 0 or bx + bw <= 0 or by + bh <= 0 or bx >= screen_w or by >= screen_h:
            is_offscreen = True

    # ── Build states list ──
    states: list[str] = []
    if not is_enabled:
        states.append("disabled")
    if is_focused:
        states.append("focused")
    if is_offscreen:
        states.append("offscreen")
    if is_selected:
        states.append("selected")
    if is_busy:
        states.append("busy")
    if is_modal:
        states.append("modal")
    if is_required:
        states.append("required")
    if has_expanded:
        if is_expanded:
            states.append("expanded")
        else:
            states.append("collapsed")

    # Checked/mixed for toggles
    if role in TOGGLE_ROLES and raw_value is not None:
        try:
            int_val = int(raw_value)
            if int_val == 1:
                states.append("checked")
            elif int_val == 2:
                states.append("mixed")
        except (ValueError, TypeError):
            pass

    if is_editable:
        states.append("editable")
    elif role in TEXT_INPUT_ROLES and not is_editable:
        states.append("readonly")

    # ── Actions ──
    # Skip the action names cross-process call for roles that never produce
    # meaningful CUP actions (saves ~30-60% of per-node overhead).
    skip_actions = ax_role in _SKIP_ACTIONS_AX_ROLES or (ax_role == "AXGroup" and not name)
    if skip_actions:
        ax_action_list = []
    else:
        try:
            err, ax_actions = AXUIElementCopyActionNames(element, None)
            ax_action_list = list(ax_actions) if err == kAXErrorSuccess and ax_actions else []
        except Exception:
            ax_action_list = []

    actions: list[str] = []
    for ax_act in ax_action_list:
        if ax_act == "AXPress":
            if role in TOGGLE_ROLES:
                actions.append("toggle")
            elif role in (
                "listitem",
                "option",
                "tab",
                "treeitem",
                "menuitem",
                "menuitemcheckbox",
                "menuitemradio",
            ):
                actions.append("select")
            else:
                actions.append("click")
        elif ax_act == "AXIncrement":
            actions.append("increment")
        elif ax_act == "AXDecrement":
            actions.append("decrement")
        elif ax_act == "AXCancel":
            actions.append("dismiss")
        elif ax_act == "AXRaise":
            actions.append("focus")
        elif ax_act == "AXConfirm":
            actions.append("click")
        elif ax_act == "AXPick":
            if "select" not in actions:
                actions.append("select")
        # Note: AXScrollToVisible and AXShowMenu are skipped —
        # Chromium/Electron sets them on ~99% of elements as noise.
        # AXScrollToVisible means "scroll parent to show me" (passive),
        # not "I am scrollable". AXShowMenu opens a context menu.

    # Text input: add type/setvalue if value is settable
    if role in TEXT_INPUT_ROLES and is_editable:
        if "setvalue" not in actions:
            actions.append("setvalue")
        if "type" not in actions:
            actions.append("type")

    # Expand/collapse from expanded state
    if has_expanded:
        if "expand" not in actions:
            actions.append("expand")
        if "collapse" not in actions:
            actions.append("collapse")

    # Scroll areas are scrollable containers
    if ax_role == "AXScrollArea" and "scroll" not in actions:
        actions.append("scroll")

    # Fallback: focusable
    if not actions and is_enabled:
        actions.append("focus")

    # ── Attributes (read conditionally per role to avoid overhead on all nodes) ──
    attrs: dict = {}

    # Tree item nesting depth
    if role == "treeitem":
        dl = _get_attr(element, "AXDisclosureLevel")
        if dl is not None:
            try:
                attrs["level"] = int(dl) + 1  # AX is 0-based, CUP is 1-based
            except (ValueError, TypeError):
                pass

    # Range widget min/max/current
    if role in ("slider", "progressbar", "spinbutton", "scrollbar"):
        min_val = _get_attr(element, "AXMinValue")
        max_val = _get_attr(element, "AXMaxValue")
        if min_val is not None:
            try:
                attrs["valueMin"] = float(min_val)
            except (ValueError, TypeError):
                pass
        if max_val is not None:
            try:
                attrs["valueMax"] = float(max_val)
            except (ValueError, TypeError):
                pass
        if raw_value is not None:
            try:
                attrs["valueNow"] = float(raw_value)
            except (ValueError, TypeError):
                pass

    # Placeholder text for inputs
    if role in ("textbox", "searchbox", "combobox"):
        placeholder = _get_attr(element, "AXPlaceholderValue")
        if placeholder is not None and isinstance(placeholder, str) and placeholder:
            attrs["placeholder"] = placeholder[:200]

    # Link URL
    if role == "link":
        url = _get_attr(element, "AXURL")
        if url is not None:
            url_str = str(url)
            if url_str:
                attrs["url"] = url_str[:500]

    # Orientation
    if role in ("scrollbar", "slider", "separator", "toolbar", "tablist"):
        orientation = _get_attr(element, "AXOrientation")
        if orientation is not None:
            orient_str = str(orientation)
            if "Vertical" in orient_str:
                attrs["orientation"] = "vertical"
            elif "Horizontal" in orient_str:
                attrs["orientation"] = "horizontal"

    # ── Assemble CUP node ──
    node: dict = {
        "id": f"e{next(id_gen)}",
        "role": role,
        "name": name[:200],
    }

    # Description: use help text (or description if title was used as name)
    desc_text = help_text if help_text else (description if title and description else "")
    if desc_text:
        node["description"] = desc_text[:200]
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

    # ── Platform extension (macOS-specific raw data) ──
    pm: dict = {"axRole": ax_role}
    if ax_subrole:
        pm["axSubrole"] = ax_subrole
    if ax_identifier:
        pm["axIdentifier"] = ax_identifier
    if ax_action_list:
        pm["axActions"] = ax_action_list
    node["platform"] = {"macos": pm}

    # Children refs from batch (index 17)
    children_refs = vals[17]
    if children_refs is not None:
        children_refs = list(children_refs)
    else:
        children_refs = []

    return node, children_refs


# ---------------------------------------------------------------------------
# Tree walker
# ---------------------------------------------------------------------------


def walk_tree(element, depth: int, max_depth: int, id_gen, stats: dict, refs: dict) -> dict | None:
    """Recursively walk an AXUIElement tree and build CUP nodes."""
    if depth > max_depth:
        return None

    result = build_cup_node(element, id_gen, stats)
    if result is None:
        return None
    node, children_refs = result

    refs[node["id"]] = element

    stats["max_depth"] = max(stats["max_depth"], depth)

    if depth < max_depth and children_refs:
        children: list[dict] = []
        for child_ref in children_refs:
            child_node = walk_tree(child_ref, depth + 1, max_depth, id_gen, stats, refs)
            if child_node is not None:
                children.append(child_node)
        if children:
            node["children"] = children

    return node


# ---------------------------------------------------------------------------
# MacosAdapter — PlatformAdapter implementation
# ---------------------------------------------------------------------------


class MacosAdapter(PlatformAdapter):
    """CUP adapter for macOS via pyobjc AXUIElement API."""

    @property
    def platform_name(self) -> str:
        return "macos"

    def initialize(self) -> None:
        pass  # pyobjc has no explicit init step

    def get_screen_info(self) -> tuple[int, int, float]:
        return _macos_screen_info()

    def get_foreground_window(self) -> dict[str, Any]:
        pid, app_name, bundle_id = _macos_foreground_app()
        win_ref = _macos_focused_window(pid)
        return {
            "handle": win_ref,
            "title": app_name,
            "pid": pid,
            "bundle_id": bundle_id,
        }

    def get_all_windows(self) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        apps = _macos_visible_apps()

        def _enum(app_info):
            p, n, b = app_info
            return [(p, n, b, w) for w in _macos_windows_for_app(p)]

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            for batch in pool.map(_enum, apps):
                for pid, name, bid, win_ref in batch:
                    results.append(
                        {
                            "handle": win_ref,
                            "title": name,
                            "pid": pid,
                            "bundle_id": bid,
                        }
                    )
        return results

    def get_window_list(self) -> list[dict[str, Any]]:
        fg_pid, _, _ = _macos_foreground_app()
        results: list[dict[str, Any]] = []
        seen_pids: set[int] = set()
        for pid, name, bundle_id in _macos_visible_apps():
            if pid in seen_pids:
                continue
            seen_pids.add(pid)
            results.append(
                {
                    "title": name,
                    "pid": pid,
                    "bundle_id": bundle_id,
                    "foreground": pid == fg_pid,
                    "bounds": None,  # skip AX calls for speed
                }
            )
        return results

    def get_desktop_window(self) -> dict[str, Any] | None:
        for pid, _name, bundle_id in _macos_visible_apps():
            if bundle_id == "com.apple.finder":
                windows = _macos_windows_for_app(pid)
                for win in windows:
                    subrole = _get_attr(win, kAXSubroleAttribute)
                    if subrole == "AXDesktop":
                        return {
                            "handle": win,
                            "title": "Desktop",
                            "pid": pid,
                            "bundle_id": bundle_id,
                        }
                # Fallback: first Finder window
                if windows:
                    return {
                        "handle": windows[0],
                        "title": "Desktop",
                        "pid": pid,
                        "bundle_id": bundle_id,
                    }
        return None

    def capture_tree(
        self,
        windows: list[dict[str, Any]],
        *,
        max_depth: int = 999,
    ) -> tuple[list[dict], dict, dict[str, Any]]:
        sw, sh, _ = self.get_screen_info()
        refs: dict[str, Any] = {}

        if len(windows) <= 1:
            # Single window — walk sequentially (no thread overhead)
            id_gen = itertools.count()
            stats: dict = {"nodes": 0, "max_depth": 0, "roles": {}, "screen_w": sw, "screen_h": sh}
            tree: list[dict] = []
            for win in windows:
                node = walk_tree(win["handle"], 0, max_depth, id_gen, stats, refs)
                if node is not None:
                    tree.append(node)
            return tree, stats, refs
        else:
            # Multiple windows — walk in parallel threads.
            # AX API calls release the GIL (C calls via pyobjc), so threads
            # give real parallelism for cross-process attribute reads.
            shared_id_gen = itertools.count()
            merged_stats: dict = {
                "nodes": 0,
                "max_depth": 0,
                "roles": {},
                "screen_w": sw,
                "screen_h": sh,
            }
            tree = []

            def _walk_one(win):
                local_stats = {
                    "nodes": 0,
                    "max_depth": 0,
                    "roles": {},
                    "screen_w": sw,
                    "screen_h": sh,
                }
                node = walk_tree(win["handle"], 0, max_depth, shared_id_gen, local_stats, refs)
                return node, local_stats

            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                for node, local_stats in pool.map(_walk_one, windows):
                    if node is not None:
                        tree.append(node)
                    merged_stats["nodes"] += local_stats["nodes"]
                    merged_stats["max_depth"] = max(
                        merged_stats["max_depth"], local_stats["max_depth"]
                    )
                    for k, v in local_stats["roles"].items():
                        merged_stats["roles"][k] = merged_stats["roles"].get(k, 0) + v

            return tree, merged_stats, refs
