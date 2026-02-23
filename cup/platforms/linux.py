"""
Linux AT-SPI2 platform adapter for CUP.

Captures the accessibility tree via AT-SPI2 over D-Bus (using PyGObject /
GObject Introspection bindings) and maps it to the canonical CUP schema.

Key design choices:
  1. Uses gi.repository.Atspi — the standard Python binding for AT-SPI2
  2. Batch-reads core properties per node (role, name, description, states,
     bounds, attributes, actions, value) in a single walk pass
  3. Xlib (via ctypes) for screen info and foreground window detection
  4. Parallel tree walking with ThreadPoolExecutor for multi-window captures
"""

from __future__ import annotations

import ctypes
import ctypes.util
import itertools
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from cup._base import PlatformAdapter

# ---------------------------------------------------------------------------
# AT-SPI2 role -> CUP ARIA role mapping
# ---------------------------------------------------------------------------
# Based on W3C Core AAM (Accessibility API Mappings) spec which defines
# how ARIA roles map to ATK/AT-SPI roles. AT-SPI role names come from
# the Atspi.Role enum (e.g. Atspi.Role.PUSH_BUTTON).
#
# We map from the string name of the enum (e.g. "push-button") rather
# than numeric values, for readability and resilience across versions.

CUP_ROLES: dict[str, str] = {
    # Core interactive
    "push-button": "button",
    "toggle-button": "button",
    "check-box": "checkbox",
    "radio-button": "radio",
    "combo-box": "combobox",
    "text": "textbox",
    "password-text": "textbox",
    "entry": "textbox",
    "spin-button": "spinbutton",
    "slider": "slider",
    "scroll-bar": "scrollbar",
    "progress-bar": "progressbar",
    "link": "link",
    "menu": "menu",
    "menu-bar": "menubar",
    "menu-item": "menuitem",
    "check-menu-item": "menuitemcheckbox",
    "radio-menu-item": "menuitemradio",
    "separator": "separator",
    # Containers / structure
    "frame": "window",
    "dialog": "dialog",
    "alert": "alert",
    "file-chooser": "dialog",
    "color-chooser": "dialog",
    "font-chooser": "dialog",
    "window": "window",
    "panel": "group",
    "filler": "generic",
    "grouping": "group",
    "split-pane": "group",
    "viewport": "group",
    "scroll-pane": "group",
    "layered-pane": "group",
    "glass-pane": "group",
    "internal-frame": "group",
    "desktop-frame": "group",
    "root-pane": "group",
    "option-pane": "group",
    # Tables / grids
    "table": "table",
    "table-cell": "cell",
    "table-row": "row",
    "table-column-header": "columnheader",
    "table-row-header": "rowheader",
    "tree-table": "treegrid",
    # Lists / trees
    "list": "list",
    "list-item": "listitem",
    "tree": "tree",
    "tree-item": "treeitem",
    # Tabs
    "page-tab-list": "tablist",
    "page-tab": "tab",
    # Text / display
    "label": "text",
    "static": "text",
    "caption": "text",
    "heading": "heading",
    "paragraph": "text",
    "section": "generic",
    "block-quote": "generic",
    "image": "img",
    "icon": "img",
    "animation": "img",
    "canvas": "img",
    "chart": "img",
    # Document / content
    "document-frame": "document",
    "document-web": "document",
    "document-text": "document",
    "document-email": "document",
    "document-spreadsheet": "document",
    "document-presentation": "document",
    "article": "article",
    "form": "form",
    # Toolbar / status
    "tool-bar": "toolbar",
    "tool-tip": "tooltip",
    "status-bar": "status",
    "info-bar": "status",
    "notification": "alert",
    # ARIA landmarks (exposed via AT-SPI when apps set ARIA roles)
    "landmark": "region",
    "log": "log",
    "marquee": "marquee",
    "math": "math",
    "timer": "timer",
    "definition": "definition",
    "note": "note",
    "figure": "figure",
    "footer": "contentinfo",
    "content-deletion": "generic",
    "content-insertion": "generic",
    "description-list": "list",
    "description-term": "term",
    "description-value": "definition",
    "comment": "note",
    # Navigation
    "page": "region",
    "redundant-object": "generic",
    "application": "application",
    "autocomplete": "combobox",
    "embedded": "generic",
    "editbar": "toolbar",
    # Catch-all
    "unknown": "generic",
    "invalid": "generic",
    "extended": "generic",
}

# Roles that accept text input (for adding "type" action)
TEXT_INPUT_ROLES = {"textbox", "searchbox", "combobox", "document"}

# AT-SPI state names -> CUP state mappings
# We read Atspi.StateSet and map relevant states to CUP equivalents
STATE_MAP: dict[str, str] = {
    "focused": "focused",
    "selected": "selected",
    "checked": "checked",
    "pressed": "pressed",
    "expanded": "expanded",
    "expandable": "",  # used to derive collapsed
    "sensitive": "",  # inverse -> disabled
    "enabled": "",  # inverse -> disabled
    "editable": "editable",
    "required": "required",
    "modal": "modal",
    "multi-selectable": "multiselectable",
    "busy": "busy",
    "read-only": "readonly",
    "visible": "",  # inverse -> hidden
    "showing": "",  # inverse -> offscreen
    "indeterminate": "mixed",
}

# AT-SPI action names -> CUP action mappings
ACTION_MAP: dict[str, str] = {
    "click": "click",
    "press": "click",
    "activate": "click",
    "jump": "click",
    "toggle": "toggle",
    "expand or contract": "expand",
    "menu": "click",
}


# ---------------------------------------------------------------------------
# X11 helpers via ctypes (for screen info and foreground window)
# ---------------------------------------------------------------------------


class _X11:
    """Thin ctypes wrapper around libX11 for screen/window queries."""

    def __init__(self):
        self._lib = None
        self._display = None

    def _ensure_open(self):
        if self._lib is not None:
            return
        libx11_name = ctypes.util.find_library("X11")
        if not libx11_name:
            raise RuntimeError("libX11 not found. Install libx11-dev or xorg-x11-libs.")
        self._lib = ctypes.cdll.LoadLibrary(libx11_name)
        display_name = os.environ.get("DISPLAY", ":0").encode()
        self._display = self._lib.XOpenDisplay(display_name)
        if not self._display:
            raise RuntimeError(
                f"Cannot open X11 display '{display_name.decode()}'. "
                "Ensure DISPLAY is set and X server is running."
            )

    def get_screen_size(self) -> tuple[int, int]:
        """Return (width, height) of the default screen."""
        self._ensure_open()
        screen = self._lib.XDefaultScreen(self._display)
        w = self._lib.XDisplayWidth(self._display, screen)
        h = self._lib.XDisplayHeight(self._display, screen)
        return (w, h)

    def get_foreground_xid(self) -> int | None:
        """Return the X11 window ID of the currently focused window."""
        self._ensure_open()
        focus_window = ctypes.c_ulong()
        revert_to = ctypes.c_int()
        self._lib.XGetInputFocus(
            self._display,
            ctypes.byref(focus_window),
            ctypes.byref(revert_to),
        )
        xid = focus_window.value
        return xid if xid > 1 else None  # 0=None, 1=PointerRoot

    def close(self):
        if self._lib and self._display:
            self._lib.XCloseDisplay(self._display)
            self._display = None


def _get_scale_factor() -> float:
    """Detect display scale factor from common Linux mechanisms."""
    # GDK_SCALE env var (set by GTK/GNOME)
    gdk_scale = os.environ.get("GDK_SCALE")
    if gdk_scale:
        try:
            return float(gdk_scale)
        except ValueError:
            pass

    # Qt scale factor
    qt_scale = os.environ.get("QT_SCALE_FACTOR")
    if qt_scale:
        try:
            return float(qt_scale)
        except ValueError:
            pass

    # gsettings (GNOME)
    try:
        result = subprocess.run(
            ["gsettings", "get", "org.gnome.desktop.interface", "text-scaling-factor"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode == 0:
            val = float(result.stdout.strip())
            if val > 0:
                return val
    except Exception:
        pass

    return 1.0


# ---------------------------------------------------------------------------
# AT-SPI2 helpers
# ---------------------------------------------------------------------------


def _init_atspi():
    """Import and initialize AT-SPI2 via GObject Introspection."""
    import gi

    gi.require_version("Atspi", "2.0")
    from gi.repository import Atspi

    # Event listeners are not needed — we only read the tree.
    # But we need to make sure the registry is initialized.
    return Atspi


def _atspi_role_name(accessible) -> str:
    """Get the AT-SPI role as a lowercase dash-separated string.

    AT-SPI2 returns role names with spaces (e.g. "push button") over D-Bus.
    We normalize to dashes to match our CUP_ROLES mapping keys.
    """
    try:
        raw = accessible.get_role_name() or ""
        return raw.lower().replace(" ", "-") if raw else "unknown"
    except Exception:
        return "unknown"


def _atspi_get_states(accessible) -> set[str]:
    """Read the StateSet and return a set of state name strings.

    Uses get_states() which returns the list of active Atspi.StateType
    values directly, rather than iterating all possible enum values
    (which can be unreliable across PyGObject versions).
    """
    states: set[str] = set()
    try:
        state_set = accessible.get_state_set()
        active_states = state_set.get_states()
        for st in active_states:
            # GObject enum nick: SENSITIVE -> "sensitive",
            # MULTI_SELECTABLE -> "multi-selectable"
            name = st.value_nick.replace("_", "-")
            states.add(name)
    except Exception:
        pass
    return states


def _atspi_get_actions(accessible) -> list[str]:
    """Read the Action interface and return action names."""
    actions: list[str] = []
    try:
        action = accessible.get_action_iface()
        if action is not None:
            n = action.get_n_actions()
            for i in range(n):
                name = action.get_action_name(i)
                if name:
                    actions.append(name.lower())
    except Exception:
        pass
    return actions


def _atspi_get_attributes(accessible) -> dict[str, str]:
    """Read the object attributes dict (e.g. xml-roles, level, etc.)."""
    try:
        attrs = accessible.get_attributes()
        return dict(attrs) if attrs else {}
    except Exception:
        return {}


def _atspi_get_value(accessible) -> tuple[float | None, float | None, float | None]:
    """Read Value interface: (current, min, max) or (None, None, None)."""
    try:
        value_iface = accessible.get_value_iface()
        if value_iface is not None:
            current = value_iface.get_current_value()
            minimum = value_iface.get_minimum_value()
            maximum = value_iface.get_maximum_value()
            return (current, minimum, maximum)
    except Exception:
        pass
    return (None, None, None)


def _atspi_get_text(accessible) -> str:
    """Read the Text interface to get the current text content."""
    try:
        text_iface = accessible.get_text_iface()
        if text_iface is not None:
            char_count = text_iface.get_character_count()
            if 0 < char_count <= 10000:
                return text_iface.get_text(0, char_count)
    except Exception:
        pass
    return ""


def _atspi_get_bounds(accessible) -> dict | None:
    """Get the bounding rectangle in screen coordinates."""
    try:
        comp = accessible.get_component_iface()
        if comp is not None:
            # ATSPI_COORD_TYPE_SCREEN = 0
            rect = comp.get_extents(0)
            if rect.width > 0 or rect.height > 0:
                return {
                    "x": rect.x,
                    "y": rect.y,
                    "w": rect.width,
                    "h": rect.height,
                }
    except Exception:
        pass
    return None


def _get_pid(accessible) -> int | None:
    """Get the process ID of the application owning this accessible."""
    try:
        pid = accessible.get_process_id()
        return pid if pid > 0 else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# CUP node builder
# ---------------------------------------------------------------------------


def _build_cup_node(
    accessible,
    id_gen,
    stats: dict,
    depth: int,
    max_depth: int,
    screen_w: int,
    screen_h: int,
    refs: dict,
) -> dict | None:
    """Build a CUP node dict from an AT-SPI2 accessible object.

    Recursively walks children up to max_depth.
    """
    if depth > max_depth:
        return None

    stats["nodes"] += 1
    stats["max_depth"] = max(stats["max_depth"], depth)

    # ── Role ──
    role_name = _atspi_role_name(accessible)
    role = CUP_ROLES.get(role_name, "generic")

    # Track raw AT-SPI role names in stats (like Windows tracks ControlType names)
    stats["roles"][role_name] = stats["roles"].get(role_name, 0) + 1

    # ── Name / description ──
    try:
        name = accessible.get_name() or ""
    except Exception:
        name = ""
    try:
        description = accessible.get_description() or ""
    except Exception:
        description = ""

    # ── Object attributes (may refine role) ──
    obj_attrs = _atspi_get_attributes(accessible)

    # xml-roles / tag can refine the CUP role for web content
    xml_role = obj_attrs.get("xml-roles", "").lower()
    if xml_role:
        # Direct ARIA role override for ambiguous base roles
        ARIA_REFINEMENTS = {
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
            "switch": "switch",
            "tabpanel": "tabpanel",
            "log": "log",
            "status": "status",
            "timer": "timer",
            "marquee": "marquee",
            "feed": "feed",
            "figure": "figure",
            "math": "math",
            "note": "note",
            "article": "article",
            "directory": "directory",
        }
        if xml_role in ARIA_REFINEMENTS:
            role = ARIA_REFINEMENTS[xml_role]

    # Panel with a name -> region (like Windows Pane heuristic)
    if role == "group" and name:
        role = "region"

    # ── Bounds ──
    bounds = _atspi_get_bounds(accessible)

    # ── States ──
    raw_states = _atspi_get_states(accessible)
    states: list[str] = []

    # In ATK/AT-SPI2, STATE_SENSITIVE is the primary interactivity flag.
    # STATE_ENABLED is often set alongside it but not always.
    # A widget is disabled only when it lacks sensitive state.
    is_sensitive = "sensitive" in raw_states
    if not is_sensitive:
        states.append("disabled")
    if "focused" in raw_states:
        states.append("focused")
    if "checked" in raw_states:
        states.append("checked")
    if "pressed" in raw_states:
        states.append("pressed")
    if "indeterminate" in raw_states:
        states.append("mixed")
    if "expanded" in raw_states:
        states.append("expanded")
    elif "expandable" in raw_states:
        states.append("collapsed")
    if "selected" in raw_states:
        states.append("selected")
    if "required" in raw_states:
        states.append("required")
    if "modal" in raw_states:
        states.append("modal")
    if "read-only" in raw_states:
        states.append("readonly")
    if "editable" in raw_states and "read-only" not in raw_states:
        states.append("editable")
    if "busy" in raw_states:
        states.append("busy")
    if "multi-selectable" in raw_states:
        states.append("multiselectable")

    # Offscreen detection: not "showing" or bounds entirely outside screen
    is_offscreen = False
    if "showing" not in raw_states and "visible" in raw_states:
        is_offscreen = True
    elif bounds and screen_w > 0 and screen_h > 0:
        bx, by, bw, bh = bounds["x"], bounds["y"], bounds["w"], bounds["h"]
        if bx + bw <= 0 or by + bh <= 0 or bx >= screen_w or by >= screen_h:
            is_offscreen = True
    if is_offscreen:
        states.append("offscreen")

    # ── Actions ──
    raw_actions = _atspi_get_actions(accessible)
    actions: list[str] = []
    seen_actions: set[str] = set()

    for raw_act in raw_actions:
        mapped = ACTION_MAP.get(raw_act, raw_act)
        if mapped and mapped not in seen_actions:
            actions.append(mapped)
            seen_actions.add(mapped)

    # Expand/collapse from state rather than action list
    if "expandable" in raw_states and "expand" not in seen_actions:
        actions.append("expand")
        actions.append("collapse")

    # Text input action
    if role in TEXT_INPUT_ROLES and "editable" in raw_states:
        if "type" not in seen_actions:
            actions.append("type")
        if "setvalue" not in seen_actions:
            actions.append("setvalue")

    # Selection action
    if "selectable" in raw_states and "select" not in seen_actions:
        actions.append("select")

    # Default focus action
    if not actions and "focusable" in raw_states:
        actions.append("focus")

    # ── Role refinement from actions ──
    # GTK3/4 headerbar buttons and model buttons may report as "panel" or
    # other non-button roles via AT-SPI.  If an element mapped to "generic"
    # has a name and a click action, it's almost certainly a button.
    if role == "generic" and name and "click" in seen_actions:
        role = "button"

    # ── Value ──
    value_current, value_min, value_max = _atspi_get_value(accessible)

    # For text inputs, prefer Text interface content as the value
    text_content = ""
    if role in ("textbox", "searchbox", "combobox", "spinbutton", "document"):
        text_content = _atspi_get_text(accessible)

    value_str = ""
    if text_content:
        value_str = text_content[:200]
    elif value_current is not None and role in (
        "slider",
        "progressbar",
        "spinbutton",
        "scrollbar",
    ):
        value_str = str(value_current)

    # ── Attributes ──
    attrs: dict = {}

    # Heading level
    if role == "heading":
        level_str = obj_attrs.get("level", "")
        if level_str:
            try:
                attrs["level"] = int(level_str)
            except ValueError:
                pass

    # Range widget min/max
    if value_min is not None and role in ("slider", "progressbar", "spinbutton", "scrollbar"):
        attrs["valueMin"] = value_min
    if value_max is not None and role in ("slider", "progressbar", "spinbutton", "scrollbar"):
        attrs["valueMax"] = value_max
    if value_current is not None and role in ("slider", "progressbar", "spinbutton", "scrollbar"):
        attrs["valueNow"] = value_current

    # Placeholder
    placeholder = obj_attrs.get("placeholder-text", "")
    if placeholder and role in ("textbox", "searchbox", "combobox"):
        attrs["placeholder"] = placeholder[:200]

    # Orientation
    if "horizontal" in raw_states and role in (
        "scrollbar",
        "slider",
        "separator",
        "toolbar",
        "tablist",
    ):
        attrs["orientation"] = "horizontal"
    elif "vertical" in raw_states and role in (
        "scrollbar",
        "slider",
        "separator",
        "toolbar",
        "tablist",
    ):
        attrs["orientation"] = "vertical"

    # URL for links
    if role == "link":
        link_url = obj_attrs.get("href", "")
        if link_url:
            attrs["url"] = link_url[:500]

    # ── Assemble CUP node ──
    node: dict = {
        "id": f"e{next(id_gen)}",
        "role": role,
        "name": name[:200],
    }

    if description:
        node["description"] = description[:200]
    if value_str:
        node["value"] = value_str
    if bounds:
        node["bounds"] = bounds
    if states:
        node["states"] = states
    if actions:
        node["actions"] = actions
    if attrs:
        node["attributes"] = attrs

    # ── Platform extension ──
    plat: dict = {"atspiRole": role_name}
    if obj_attrs.get("id"):
        plat["id"] = obj_attrs["id"]
    if obj_attrs.get("class"):
        plat["class"] = obj_attrs["class"]
    if obj_attrs.get("toolkit"):
        plat["toolkit"] = obj_attrs["toolkit"]
    if raw_actions:
        plat["actions"] = raw_actions
    node["platform"] = {"linux": plat}

    refs[node["id"]] = accessible

    # ── Children ──
    if depth < max_depth:
        children: list[dict] = []
        try:
            n_children = accessible.get_child_count()
            for i in range(n_children):
                try:
                    child_acc = accessible.get_child_at_index(i)
                    if child_acc is None:
                        continue
                    child_node = _build_cup_node(
                        child_acc,
                        id_gen,
                        stats,
                        depth + 1,
                        max_depth,
                        screen_w,
                        screen_h,
                        refs,
                    )
                    if child_node is not None:
                        children.append(child_node)
                except Exception:
                    continue
        except Exception:
            pass

        if children:
            node["children"] = children

    return node


# ---------------------------------------------------------------------------
# LinuxAdapter — PlatformAdapter implementation
# ---------------------------------------------------------------------------


class LinuxAdapter(PlatformAdapter):
    """CUP adapter for Linux via AT-SPI2 (D-Bus accessibility)."""

    def __init__(self):
        self._atspi = None
        self._x11: _X11 | None = None
        self._screen_w: int = 0
        self._screen_h: int = 0
        self._scale: float = 1.0

    @property
    def platform_name(self) -> str:
        return "linux"

    def initialize(self) -> None:
        if self._atspi is not None:
            return  # already initialized
        self._atspi = _init_atspi()

        # Screen info via X11
        try:
            self._x11 = _X11()
            self._screen_w, self._screen_h = self._x11.get_screen_size()
        except Exception:
            # Fallback: try xdpyinfo or xrandr
            self._screen_w, self._screen_h = _fallback_screen_size()

        self._scale = _get_scale_factor()

    def get_screen_info(self) -> tuple[int, int, float]:
        return self._screen_w, self._screen_h, self._scale

    def get_foreground_window(self) -> dict[str, Any]:
        """Return the focused application's top-level window via AT-SPI2.

        Walks the AT-SPI desktop to find the application whose window
        currently has keyboard focus, falling back to X11 focus detection.
        """
        desktop = self._atspi.get_desktop(0)

        # Strategy: find the accessible with STATE_FOCUSED or STATE_ACTIVE
        # among top-level application windows
        best: dict[str, Any] | None = None

        for i in range(desktop.get_child_count()):
            try:
                app = desktop.get_child_at_index(i)
                if app is None:
                    continue
                app_name = app.get_name() or ""
                pid = _get_pid(app)

                for j in range(app.get_child_count()):
                    try:
                        win = app.get_child_at_index(j)
                        if win is None:
                            continue
                        state_set = win.get_state_set()
                        from gi.repository import Atspi

                        is_active = state_set.contains(Atspi.StateType.ACTIVE)
                        is_focused = state_set.contains(Atspi.StateType.FOCUSED)
                        title = win.get_name() or app_name

                        if is_active or is_focused:
                            return {
                                "handle": win,
                                "title": title,
                                "pid": pid,
                                "bundle_id": None,
                            }
                        # Track first visible window as fallback
                        if best is None and state_set.contains(Atspi.StateType.VISIBLE):
                            best = {
                                "handle": win,
                                "title": title,
                                "pid": pid,
                                "bundle_id": None,
                            }
                    except Exception:
                        continue
            except Exception:
                continue

        # Fallback to first visible window, or the desktop itself
        if best is not None:
            return best
        return {
            "handle": desktop,
            "title": "Desktop",
            "pid": None,
            "bundle_id": None,
        }

    def get_all_windows(self) -> list[dict[str, Any]]:
        """Return all visible top-level windows across all AT-SPI applications."""
        desktop = self._atspi.get_desktop(0)
        windows: list[dict[str, Any]] = []

        for i in range(desktop.get_child_count()):
            try:
                app = desktop.get_child_at_index(i)
                if app is None:
                    continue
                app_name = app.get_name() or ""
                pid = _get_pid(app)

                for j in range(app.get_child_count()):
                    try:
                        win = app.get_child_at_index(j)
                        if win is None:
                            continue
                        state_set = win.get_state_set()
                        from gi.repository import Atspi

                        if not state_set.contains(Atspi.StateType.VISIBLE):
                            continue
                        title = win.get_name() or app_name
                        windows.append(
                            {
                                "handle": win,
                                "title": title,
                                "pid": pid,
                                "bundle_id": None,
                            }
                        )
                    except Exception:
                        continue
            except Exception:
                continue

        return windows

    def get_window_list(self) -> list[dict[str, Any]]:
        self.initialize()
        desktop = self._atspi.get_desktop(0)
        results: list[dict[str, Any]] = []

        # Find foreground PID for marking
        fg_info = self.get_foreground_window()
        fg_pid = fg_info.get("pid")
        fg_title = fg_info.get("title")

        for i in range(desktop.get_child_count()):
            try:
                app = desktop.get_child_at_index(i)
                if app is None:
                    continue
                app_name = app.get_name() or ""
                pid = _get_pid(app)

                for j in range(app.get_child_count()):
                    try:
                        win = app.get_child_at_index(j)
                        if win is None:
                            continue
                        state_set = win.get_state_set()
                        from gi.repository import Atspi

                        if not state_set.contains(Atspi.StateType.VISIBLE):
                            continue
                        title = win.get_name() or app_name
                        is_fg = state_set.contains(Atspi.StateType.ACTIVE) or (
                            pid == fg_pid and title == fg_title
                        )
                        results.append(
                            {
                                "title": title,
                                "pid": pid,
                                "bundle_id": None,
                                "foreground": is_fg,
                                "bounds": _atspi_get_bounds(win),
                            }
                        )
                    except Exception:
                        continue
            except Exception:
                continue

        return results

    def get_desktop_window(self) -> dict[str, Any] | None:
        self.initialize()
        desktop = self._atspi.get_desktop(0)
        desktop_apps = {"nautilus", "nemo", "caja", "pcmanfm", "pcmanfm-qt", "thunar"}

        for i in range(desktop.get_child_count()):
            try:
                app = desktop.get_child_at_index(i)
                if app is None:
                    continue
                app_name = (app.get_name() or "").lower()
                if app_name not in desktop_apps:
                    continue
                pid = _get_pid(app)

                for j in range(app.get_child_count()):
                    try:
                        win = app.get_child_at_index(j)
                        if win is None:
                            continue
                        role = win.get_role_name() or ""
                        if role == "desktop frame":
                            return {
                                "handle": win,
                                "title": "Desktop",
                                "pid": pid,
                                "bundle_id": None,
                            }
                    except Exception:
                        continue
            except Exception:
                continue

        return None

    def capture_tree(
        self,
        windows: list[dict[str, Any]],
        *,
        max_depth: int = 999,
    ) -> tuple[list[dict], dict, dict[str, Any]]:
        self.initialize()
        refs: dict[str, Any] = {}

        if len(windows) <= 1:
            # Single window — sequential walk
            id_gen = itertools.count()
            stats: dict = {"nodes": 0, "max_depth": 0, "roles": {}}
            tree: list[dict] = []
            for win in windows:
                node = _build_cup_node(
                    win["handle"],
                    id_gen,
                    stats,
                    0,
                    max_depth,
                    self._screen_w,
                    self._screen_h,
                    refs,
                )
                if node is not None:
                    tree.append(node)
            return tree, stats, refs
        else:
            # Multiple windows — parallel walk with merged stats
            return self._parallel_capture(windows, max_depth=max_depth, refs=refs)

    def _parallel_capture(
        self,
        windows: list[dict[str, Any]],
        *,
        max_depth: int = 999,
        refs: dict[str, Any],
    ) -> tuple[list[dict], dict, dict[str, Any]]:
        """Walk multiple window trees in parallel threads."""
        # Shared counter for globally unique IDs
        id_gen = itertools.count()
        num_workers = min(len(windows), 8)

        per_window_results: list[tuple[dict | None, dict]] = [(None, {}) for _ in windows]

        def walk_one(idx: int):
            win = windows[idx]
            local_stats: dict = {"nodes": 0, "max_depth": 0, "roles": {}}
            node = _build_cup_node(
                win["handle"],
                id_gen,
                local_stats,
                0,
                max_depth,
                self._screen_w,
                self._screen_h,
                refs,
            )
            per_window_results[idx] = (node, local_stats)

        with ThreadPoolExecutor(max_workers=num_workers) as pool:
            list(pool.map(walk_one, range(len(windows))))

        # Merge results
        tree: list[dict] = []
        merged_stats: dict = {"nodes": 0, "max_depth": 0, "roles": {}}
        for node, st in per_window_results:
            if node is not None:
                tree.append(node)
            merged_stats["nodes"] += st.get("nodes", 0)
            merged_stats["max_depth"] = max(merged_stats["max_depth"], st.get("max_depth", 0))
            for role, count in st.get("roles", {}).items():
                merged_stats["roles"][role] = merged_stats["roles"].get(role, 0) + count

        return tree, merged_stats, refs


# ---------------------------------------------------------------------------
# Fallback screen size detection
# ---------------------------------------------------------------------------


def _fallback_screen_size() -> tuple[int, int]:
    """Try xrandr / xdpyinfo as fallback for screen dimensions."""
    # Try xrandr
    try:
        result = subprocess.run(
            ["xrandr", "--query"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if result.returncode == 0:
            import re

            match = re.search(r"(\d+)x(\d+)\+0\+0", result.stdout)
            if match:
                return (int(match.group(1)), int(match.group(2)))
            # Fallback: look for "current WxH"
            match = re.search(r"current\s+(\d+)\s*x\s*(\d+)", result.stdout)
            if match:
                return (int(match.group(1)), int(match.group(2)))
    except Exception:
        pass

    # Try xdpyinfo
    try:
        result = subprocess.run(
            ["xdpyinfo"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if result.returncode == 0:
            import re

            match = re.search(r"dimensions:\s+(\d+)x(\d+)", result.stdout)
            if match:
                return (int(match.group(1)), int(match.group(2)))
    except Exception:
        pass

    # Last resort default
    return (1920, 1080)
