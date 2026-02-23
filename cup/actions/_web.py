"""Web action handler — CDP-based action execution."""

from __future__ import annotations

import os
import time
from typing import Any

from cup.actions._handler import ActionHandler
from cup.actions._keys import parse_combo
from cup.actions.executor import ActionResult

# ---------------------------------------------------------------------------
# CDP key mapping for Input.dispatchKeyEvent
# ---------------------------------------------------------------------------

_CDP_KEY_MAP: dict[str, dict[str, str]] = {
    "enter": {"key": "Enter", "code": "Enter"},
    "tab": {"key": "Tab", "code": "Tab"},
    "escape": {"key": "Escape", "code": "Escape"},
    "backspace": {"key": "Backspace", "code": "Backspace"},
    "delete": {"key": "Delete", "code": "Delete"},
    "space": {"key": " ", "code": "Space"},
    "up": {"key": "ArrowUp", "code": "ArrowUp"},
    "down": {"key": "ArrowDown", "code": "ArrowDown"},
    "left": {"key": "ArrowLeft", "code": "ArrowLeft"},
    "right": {"key": "ArrowRight", "code": "ArrowRight"},
    "home": {"key": "Home", "code": "Home"},
    "end": {"key": "End", "code": "End"},
    "pageup": {"key": "PageUp", "code": "PageUp"},
    "pagedown": {"key": "PageDown", "code": "PageDown"},
    "f1": {"key": "F1", "code": "F1"},
    "f2": {"key": "F2", "code": "F2"},
    "f3": {"key": "F3", "code": "F3"},
    "f4": {"key": "F4", "code": "F4"},
    "f5": {"key": "F5", "code": "F5"},
    "f6": {"key": "F6", "code": "F6"},
    "f7": {"key": "F7", "code": "F7"},
    "f8": {"key": "F8", "code": "F8"},
    "f9": {"key": "F9", "code": "F9"},
    "f10": {"key": "F10", "code": "F10"},
    "f11": {"key": "F11", "code": "F11"},
    "f12": {"key": "F12", "code": "F12"},
}

_CDP_MODIFIER_MAP: dict[str, dict[str, Any]] = {
    "ctrl": {"key": "Control", "code": "ControlLeft", "bit": 2},
    "alt": {"key": "Alt", "code": "AltLeft", "bit": 1},
    "shift": {"key": "Shift", "code": "ShiftLeft", "bit": 8},
    "meta": {"key": "Meta", "code": "MetaLeft", "bit": 4},
}


def _get_click_point(box_model: dict) -> tuple[float, float]:
    """Compute the center point of a DOM.getBoxModel result.

    The content quad is returned as [x1,y1, x2,y2, x3,y3, x4,y4].
    We average all four corners to get the center.
    """
    content = box_model.get("model", {}).get("content", [])
    if len(content) >= 8:
        xs = [content[i] for i in range(0, 8, 2)]
        ys = [content[i] for i in range(1, 8, 2)]
        return sum(xs) / 4, sum(ys) / 4
    # Fallback: use border quad
    border = box_model.get("model", {}).get("border", [])
    if len(border) >= 8:
        xs = [border[i] for i in range(0, 8, 2)]
        ys = [border[i] for i in range(1, 8, 2)]
        return sum(xs) / 4, sum(ys) / 4
    raise RuntimeError("Cannot determine element position from box model")


# ---------------------------------------------------------------------------
# WebActionHandler
# ---------------------------------------------------------------------------


class WebActionHandler(ActionHandler):
    """Execute CUP actions on web pages via Chrome DevTools Protocol.

    Native refs are (ws_url, backend_dom_node_id) tuples stored by the
    web adapter during tree capture.
    """

    def __init__(self, *, cdp_host: str | None = None):
        self._host = cdp_host or os.environ.get("CUP_CDP_HOST", "127.0.0.1")

    def execute(
        self,
        native_ref: Any,
        action: str,
        params: dict[str, Any],
    ) -> ActionResult:
        from cup.platforms.web import _cdp_close, _cdp_connect

        ws_url, backend_node_id = native_ref
        ws = _cdp_connect(ws_url, self._host)
        try:
            return self._dispatch(ws, backend_node_id, action, params)
        except Exception as exc:
            return ActionResult(
                success=False,
                message="",
                error=f"Web action '{action}' failed: {exc}",
            )
        finally:
            _cdp_close(ws)

    def press_keys(self, combo: str) -> ActionResult:
        """Send a keyboard shortcut via CDP Input.dispatchKeyEvent.

        This sends to the currently focused element in the most recently
        used tab. We need a websocket URL — use the CDP target list.
        """
        from cup.platforms.web import (
            _cdp_close,
            _cdp_connect,
            _cdp_get_targets,
        )

        port = int(os.environ.get("CUP_CDP_PORT", "9222"))
        try:
            targets = _cdp_get_targets(self._host, port)
        except Exception as exc:
            return ActionResult(
                success=False,
                message="",
                error=f"Cannot connect to CDP for press_keys: {exc}",
            )

        page_targets = [t for t in targets if t.get("type") == "page"]
        if not page_targets:
            return ActionResult(
                success=False,
                message="",
                error="No browser tabs found for press_keys",
            )

        ws_url = page_targets[0]["webSocketDebuggerUrl"]
        ws = _cdp_connect(ws_url, self._host)
        try:
            self._send_key_combo(ws, combo)
            return ActionResult(success=True, message=f"Pressed {combo}")
        except Exception as exc:
            return ActionResult(
                success=False,
                message="",
                error=f"Failed to press keys: {exc}",
            )
        finally:
            _cdp_close(ws)

    # -- dispatch -----------------------------------------------------------

    def _dispatch(
        self,
        ws: Any,
        backend_node_id: int,
        action: str,
        params: dict,
    ) -> ActionResult:

        if action == "click":
            return self._click(ws, backend_node_id)
        elif action == "rightclick":
            return self._mouse_click(ws, backend_node_id, button="right")
        elif action == "doubleclick":
            return self._mouse_click(ws, backend_node_id, button="left", click_count=2)
        elif action == "type":
            text = params.get("value", "")
            return self._type(ws, backend_node_id, text)
        elif action == "setvalue":
            text = params.get("value", "")
            return self._setvalue(ws, backend_node_id, text)
        elif action == "toggle":
            return self._toggle(ws, backend_node_id)
        elif action in ("expand", "collapse"):
            return self._click(ws, backend_node_id)
        elif action == "select":
            return self._select(ws, backend_node_id)
        elif action == "scroll":
            direction = params.get("direction", "down")
            return self._scroll(ws, backend_node_id, direction)
        elif action == "focus":
            return self._focus(ws, backend_node_id)
        elif action == "dismiss":
            return self._dismiss(ws)
        elif action == "increment":
            return self._arrow_key(ws, backend_node_id, "ArrowUp")
        elif action == "decrement":
            return self._arrow_key(ws, backend_node_id, "ArrowDown")
        else:
            return ActionResult(
                success=False,
                message="",
                error=f"Action '{action}' not implemented for web",
            )

    # -- individual actions -------------------------------------------------

    def _click(self, ws: Any, backend_node_id: int) -> ActionResult:
        return self._mouse_click(ws, backend_node_id, button="left", click_count=1)

    def _mouse_click(
        self,
        ws: Any,
        backend_node_id: int,
        *,
        button: str = "left",
        click_count: int = 1,
    ) -> ActionResult:
        from cup.platforms.web import _cdp_send

        resp = _cdp_send(
            ws,
            "DOM.getBoxModel",
            {
                "backendNodeId": backend_node_id,
            },
        )
        x, y = _get_click_point(resp.get("result", {}))

        for i in range(click_count):
            _cdp_send(
                ws,
                "Input.dispatchMouseEvent",
                {
                    "type": "mousePressed",
                    "x": x,
                    "y": y,
                    "button": button,
                    "clickCount": i + 1,
                },
            )
            _cdp_send(
                ws,
                "Input.dispatchMouseEvent",
                {
                    "type": "mouseReleased",
                    "x": x,
                    "y": y,
                    "button": button,
                    "clickCount": i + 1,
                },
            )

        action_name = {
            ("left", 1): "Clicked",
            ("left", 2): "Double-clicked",
            ("right", 1): "Right-clicked",
        }.get((button, click_count), f"Mouse {button} x{click_count}")
        return ActionResult(success=True, message=action_name)

    def _type(self, ws: Any, backend_node_id: int, text: str) -> ActionResult:
        from cup.platforms.web import _cdp_send

        # Focus the element first
        _cdp_send(ws, "DOM.focus", {"backendNodeId": backend_node_id})
        time.sleep(0.05)

        # Select all existing content, then type new text
        self._send_key_combo(ws, "ctrl+a")
        time.sleep(0.05)

        # Use insertText for reliable text input
        _cdp_send(ws, "Input.insertText", {"text": text})

        return ActionResult(success=True, message=f"Typed: {text}")

    def _setvalue(self, ws: Any, backend_node_id: int, text: str) -> ActionResult:
        from cup.platforms.web import _cdp_send

        # Resolve the backend node to a Runtime object
        resp = _cdp_send(
            ws,
            "DOM.resolveNode",
            {
                "backendNodeId": backend_node_id,
            },
        )
        object_id = resp.get("result", {}).get("object", {}).get("objectId")
        if not object_id:
            return ActionResult(
                success=False,
                message="",
                error="Cannot resolve DOM node for setvalue",
            )

        # Set value and dispatch input/change events
        _cdp_send(
            ws,
            "Runtime.callFunctionOn",
            {
                "objectId": object_id,
                "functionDeclaration": """function(v) {
                this.value = v;
                this.dispatchEvent(new Event('input', {bubbles: true}));
                this.dispatchEvent(new Event('change', {bubbles: true}));
            }""",
                "arguments": [{"value": text}],
            },
        )
        return ActionResult(success=True, message=f"Set value to: {text}")

    def _scroll(
        self,
        ws: Any,
        backend_node_id: int,
        direction: str,
    ) -> ActionResult:
        from cup.platforms.web import _cdp_send

        resp = _cdp_send(
            ws,
            "DOM.getBoxModel",
            {
                "backendNodeId": backend_node_id,
            },
        )
        x, y = _get_click_point(resp.get("result", {}))

        delta_x, delta_y = 0, 0
        if direction == "up":
            delta_y = -200
        elif direction == "down":
            delta_y = 200
        elif direction == "left":
            delta_x = -200
        elif direction == "right":
            delta_x = 200

        _cdp_send(
            ws,
            "Input.dispatchMouseEvent",
            {
                "type": "mouseWheel",
                "x": x,
                "y": y,
                "deltaX": delta_x,
                "deltaY": delta_y,
            },
        )
        return ActionResult(success=True, message=f"Scrolled {direction}")

    def _focus(self, ws: Any, backend_node_id: int) -> ActionResult:
        from cup.platforms.web import _cdp_send

        _cdp_send(ws, "DOM.focus", {"backendNodeId": backend_node_id})
        return ActionResult(success=True, message="Focused")

    def _toggle(self, ws: Any, backend_node_id: int) -> ActionResult:
        from cup.platforms.web import _cdp_send

        # Use JS .click() for reliable toggling of checkboxes/switches
        resp = _cdp_send(
            ws,
            "DOM.resolveNode",
            {
                "backendNodeId": backend_node_id,
            },
        )
        object_id = resp.get("result", {}).get("object", {}).get("objectId")
        if not object_id:
            # Fallback to coordinate click
            return self._click(ws, backend_node_id)

        _cdp_send(
            ws,
            "Runtime.callFunctionOn",
            {
                "objectId": object_id,
                "functionDeclaration": "function() { this.click(); }",
            },
        )
        return ActionResult(success=True, message="Toggled")

    def _select(self, ws: Any, backend_node_id: int) -> ActionResult:
        from cup.platforms.web import _cdp_send

        # Handle <option> elements by setting selected on the option
        # and dispatching change on the parent <select>
        resp = _cdp_send(
            ws,
            "DOM.resolveNode",
            {
                "backendNodeId": backend_node_id,
            },
        )
        object_id = resp.get("result", {}).get("object", {}).get("objectId")
        if not object_id:
            return self._click(ws, backend_node_id)

        _cdp_send(
            ws,
            "Runtime.callFunctionOn",
            {
                "objectId": object_id,
                "functionDeclaration": """function() {
                if (this.tagName === 'OPTION') {
                    this.selected = true;
                    if (this.parentElement) {
                        this.parentElement.dispatchEvent(
                            new Event('change', {bubbles: true})
                        );
                    }
                } else {
                    this.click();
                }
            }""",
            },
        )
        return ActionResult(success=True, message="Selected")

    def _dismiss(self, ws: Any) -> ActionResult:
        from cup.platforms.web import _cdp_send

        _cdp_send(
            ws,
            "Input.dispatchKeyEvent",
            {
                "type": "keyDown",
                "key": "Escape",
                "code": "Escape",
            },
        )
        _cdp_send(
            ws,
            "Input.dispatchKeyEvent",
            {
                "type": "keyUp",
                "key": "Escape",
                "code": "Escape",
            },
        )
        return ActionResult(success=True, message="Dismissed (Escape)")

    def _arrow_key(
        self,
        ws: Any,
        backend_node_id: int,
        key: str,
    ) -> ActionResult:
        from cup.platforms.web import _cdp_send

        _cdp_send(ws, "DOM.focus", {"backendNodeId": backend_node_id})
        time.sleep(0.05)
        code = key  # ArrowUp, ArrowDown are both key and code
        _cdp_send(
            ws,
            "Input.dispatchKeyEvent",
            {
                "type": "keyDown",
                "key": key,
                "code": code,
            },
        )
        _cdp_send(
            ws,
            "Input.dispatchKeyEvent",
            {
                "type": "keyUp",
                "key": key,
                "code": code,
            },
        )
        verb = "Incremented" if key == "ArrowUp" else "Decremented"
        return ActionResult(success=True, message=verb)

    # -- keyboard helpers ---------------------------------------------------

    def _send_key_combo(self, ws: Any, combo: str) -> None:
        """Parse a key combo and send via CDP Input.dispatchKeyEvent."""
        from cup.platforms.web import _cdp_send

        modifiers, keys = parse_combo(combo)

        # Calculate modifier bitmask
        mod_bits = 0
        for mod in modifiers:
            info = _CDP_MODIFIER_MAP.get(mod)
            if info:
                mod_bits |= info["bit"]

        # Press modifiers down
        for mod in modifiers:
            info = _CDP_MODIFIER_MAP.get(mod)
            if info:
                _cdp_send(
                    ws,
                    "Input.dispatchKeyEvent",
                    {
                        "type": "keyDown",
                        "key": info["key"],
                        "code": info["code"],
                        "modifiers": mod_bits,
                    },
                )

        # Press and release main keys
        for key in keys:
            mapped = _CDP_KEY_MAP.get(key)
            if mapped:
                cdp_key = mapped["key"]
                cdp_code = mapped["code"]
                text = ""
            elif len(key) == 1:
                cdp_key = key
                cdp_code = f"Key{key.upper()}" if key.isalpha() else ""
                text = key
            else:
                continue

            params: dict[str, Any] = {
                "type": "keyDown",
                "key": cdp_key,
                "code": cdp_code,
                "modifiers": mod_bits,
            }
            if text and not mod_bits:
                params["text"] = text
            _cdp_send(ws, "Input.dispatchKeyEvent", params)

            _cdp_send(
                ws,
                "Input.dispatchKeyEvent",
                {
                    "type": "keyUp",
                    "key": cdp_key,
                    "code": cdp_code,
                    "modifiers": mod_bits,
                },
            )

        # Release modifiers
        for mod in reversed(modifiers):
            info = _CDP_MODIFIER_MAP.get(mod)
            if info:
                _cdp_send(
                    ws,
                    "Input.dispatchKeyEvent",
                    {
                        "type": "keyUp",
                        "key": info["key"],
                        "code": info["code"],
                        "modifiers": 0,
                    },
                )

    def launch_app(self, name: str) -> ActionResult:
        return ActionResult(
            success=False,
            message="",
            error="launch_app is not applicable for web platform",
        )
