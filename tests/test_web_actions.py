"""Tests for web action handler CDP key mapping and click point calculation."""

from __future__ import annotations

from cup.actions._web import _CDP_KEY_MAP, _CDP_MODIFIER_MAP, _get_click_point

# ---------------------------------------------------------------------------
# CDP key mapping
# ---------------------------------------------------------------------------


class TestCDPKeyMap:
    def test_common_keys_mapped(self):
        for key in ("enter", "tab", "escape", "backspace", "delete", "space"):
            assert key in _CDP_KEY_MAP
            assert "key" in _CDP_KEY_MAP[key]
            assert "code" in _CDP_KEY_MAP[key]

    def test_arrow_keys_mapped(self):
        for key in ("up", "down", "left", "right"):
            assert key in _CDP_KEY_MAP
            assert "Arrow" in _CDP_KEY_MAP[key]["key"]

    def test_function_keys_mapped(self):
        for i in range(1, 13):
            key = f"f{i}"
            assert key in _CDP_KEY_MAP
            assert _CDP_KEY_MAP[key]["key"] == f"F{i}"

    def test_modifier_map(self):
        for mod in ("ctrl", "alt", "shift", "meta"):
            assert mod in _CDP_MODIFIER_MAP
            info = _CDP_MODIFIER_MAP[mod]
            assert "key" in info
            assert "code" in info
            assert "bit" in info
            assert info["bit"] > 0


# ---------------------------------------------------------------------------
# Click point calculation
# ---------------------------------------------------------------------------


class TestGetClickPoint:
    def test_content_quad_center(self):
        """Center of a 100x50 element at (10, 20)."""
        box_model = {
            "model": {
                "content": [
                    10,
                    20,  # top-left
                    110,
                    20,  # top-right
                    110,
                    70,  # bottom-right
                    10,
                    70,  # bottom-left
                ],
            },
        }
        x, y = _get_click_point(box_model)
        assert x == 60.0
        assert y == 45.0

    def test_fallback_to_border_quad(self):
        """When content quad is missing, use border quad."""
        box_model = {
            "model": {
                "content": [],
                "border": [
                    0,
                    0,
                    200,
                    0,
                    200,
                    100,
                    0,
                    100,
                ],
            },
        }
        x, y = _get_click_point(box_model)
        assert x == 100.0
        assert y == 50.0

    def test_raises_when_no_quads(self):
        """Should raise when neither content nor border quad is available."""
        import pytest

        with pytest.raises(RuntimeError, match="Cannot determine"):
            _get_click_point({"model": {}})


# ---------------------------------------------------------------------------
# WebActionHandler dispatch (mocked CDP)
# ---------------------------------------------------------------------------


class TestWebActionDispatch:
    """Test action dispatch routing with mocked CDP transport."""

    def _make_handler(self):
        from cup.actions._web import WebActionHandler

        return WebActionHandler()

    def _mock_ws(self):
        """Create a mock websocket that records calls."""

        class MockWS:
            def __init__(self):
                self.calls = []
                self._timeout = 30

            def gettimeout(self):
                return self._timeout

            def settimeout(self, t):
                self._timeout = t

            def send(self, data):
                import json

                self.calls.append(json.loads(data))

            def recv(self):
                import json

                # Return a response matching the last sent ID
                msg_id = self.calls[-1]["id"] if self.calls else 1
                method = self.calls[-1].get("method", "") if self.calls else ""
                result = {}
                if method == "DOM.getBoxModel":
                    result = {"model": {"content": [0, 0, 100, 0, 100, 50, 0, 50]}}
                elif method == "DOM.resolveNode":
                    result = {"object": {"objectId": "obj-1"}}
                return json.dumps({"id": msg_id, "result": result})

        return MockWS()

    def test_dispatch_click_returns_success(self):
        handler = self._make_handler()
        ws = self._mock_ws()

        result = handler._dispatch(ws, 123, "click", {})
        assert result.success is True
        assert "lick" in result.message  # "Clicked"

    def test_dispatch_type_returns_success(self):
        handler = self._make_handler()
        ws = self._mock_ws()

        result = handler._dispatch(ws, 123, "type", {"value": "hello"})
        assert result.success is True
        assert "hello" in result.message

    def test_dispatch_setvalue_returns_success(self):
        handler = self._make_handler()
        ws = self._mock_ws()

        result = handler._dispatch(ws, 123, "setvalue", {"value": "test"})
        assert result.success is True

    def test_dispatch_toggle_returns_success(self):
        handler = self._make_handler()
        ws = self._mock_ws()

        result = handler._dispatch(ws, 123, "toggle", {})
        assert result.success is True
        assert "oggle" in result.message  # "Toggled"

    def test_dispatch_select_returns_success(self):
        handler = self._make_handler()
        ws = self._mock_ws()

        result = handler._dispatch(ws, 123, "select", {})
        assert result.success is True

    def test_dispatch_scroll_returns_success(self):
        handler = self._make_handler()
        ws = self._mock_ws()

        result = handler._dispatch(ws, 123, "scroll", {"direction": "down"})
        assert result.success is True
        assert "down" in result.message.lower()

    def test_dispatch_focus_returns_success(self):
        handler = self._make_handler()
        ws = self._mock_ws()

        result = handler._dispatch(ws, 123, "focus", {})
        assert result.success is True

    def test_dispatch_dismiss_returns_success(self):
        handler = self._make_handler()
        ws = self._mock_ws()

        result = handler._dispatch(ws, 123, "dismiss", {})
        assert result.success is True

    def test_dispatch_increment_returns_success(self):
        handler = self._make_handler()
        ws = self._mock_ws()

        result = handler._dispatch(ws, 123, "increment", {})
        assert result.success is True

    def test_dispatch_decrement_returns_success(self):
        handler = self._make_handler()
        ws = self._mock_ws()

        result = handler._dispatch(ws, 123, "decrement", {})
        assert result.success is True

    def test_dispatch_unknown_action_returns_error(self):
        handler = self._make_handler()
        ws = self._mock_ws()

        result = handler._dispatch(ws, 123, "explode", {})
        assert result.success is False
        assert "not implemented" in result.error.lower()

    def test_dispatch_rightclick_returns_success(self):
        handler = self._make_handler()
        ws = self._mock_ws()

        result = handler._dispatch(ws, 123, "rightclick", {})
        assert result.success is True

    def test_dispatch_doubleclick_returns_success(self):
        handler = self._make_handler()
        ws = self._mock_ws()

        result = handler._dispatch(ws, 123, "doubleclick", {})
        assert result.success is True

    def test_all_dispatch_paths_return_actionresult(self):
        """Every action path should return ActionResult, never raise."""
        from cup.actions.executor import ActionResult

        handler = self._make_handler()
        ws = self._mock_ws()

        all_actions = [
            "click",
            "rightclick",
            "doubleclick",
            "type",
            "setvalue",
            "toggle",
            "expand",
            "collapse",
            "select",
            "scroll",
            "focus",
            "dismiss",
            "increment",
            "decrement",
            "unknown",
        ]
        for action in all_actions:
            params = {}
            if action in ("type", "setvalue"):
                params["value"] = "test"
            if action == "scroll":
                params["direction"] = "down"
            result = handler._dispatch(ws, 123, action, params)
            assert isinstance(result, ActionResult), f"{action} did not return ActionResult"
