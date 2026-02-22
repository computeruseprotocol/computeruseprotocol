"""Tests for web action handler CDP key mapping and click point calculation."""

from __future__ import annotations

from cup.actions._web import _get_click_point, _CDP_KEY_MAP, _CDP_MODIFIER_MAP


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
                    10, 20,   # top-left
                    110, 20,  # top-right
                    110, 70,  # bottom-right
                    10, 70,   # bottom-left
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
                    0, 0,
                    200, 0,
                    200, 100,
                    0, 100,
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
