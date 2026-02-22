"""Tests for the action execution layer."""

from __future__ import annotations

import pytest

from cup.actions.executor import ActionExecutor, ActionResult, VALID_ACTIONS
from cup.actions._keys import parse_combo


# ---------------------------------------------------------------------------
# Key combo parsing
# ---------------------------------------------------------------------------

class TestParseCombo:
    def test_single_key(self):
        mods, keys = parse_combo("enter")
        assert mods == []
        assert keys == ["enter"]

    def test_single_character(self):
        mods, keys = parse_combo("a")
        assert mods == []
        assert keys == ["a"]

    def test_modifier_plus_key(self):
        mods, keys = parse_combo("ctrl+s")
        assert mods == ["ctrl"]
        assert keys == ["s"]

    def test_multiple_modifiers(self):
        mods, keys = parse_combo("ctrl+shift+p")
        assert mods == ["ctrl", "shift"]
        assert keys == ["p"]

    def test_alias_return(self):
        mods, keys = parse_combo("return")
        assert keys == ["enter"]

    def test_alias_esc(self):
        mods, keys = parse_combo("esc")
        assert keys == ["escape"]

    def test_alias_win(self):
        mods, keys = parse_combo("win+e")
        assert mods == ["meta"]
        assert keys == ["e"]

    def test_alias_cmd(self):
        mods, keys = parse_combo("cmd+c")
        assert mods == ["meta"]
        assert keys == ["c"]

    def test_spaces_in_combo(self):
        mods, keys = parse_combo(" ctrl + s ")
        assert mods == ["ctrl"]
        assert keys == ["s"]

    def test_empty_parts_ignored(self):
        mods, keys = parse_combo("ctrl++s")
        assert mods == ["ctrl"]
        assert keys == ["s"]

    def test_function_key(self):
        mods, keys = parse_combo("f5")
        assert mods == []
        assert keys == ["f5"]

    def test_alt_f4(self):
        mods, keys = parse_combo("alt+f4")
        assert mods == ["alt"]
        assert keys == ["f4"]


# ---------------------------------------------------------------------------
# ActionResult
# ---------------------------------------------------------------------------

class TestActionResult:
    def test_success(self):
        r = ActionResult(success=True, message="Clicked")
        assert r.success is True
        assert r.message == "Clicked"
        assert r.error is None

    def test_failure(self):
        r = ActionResult(success=False, message="", error="Not found")
        assert r.success is False
        assert r.error == "Not found"


# ---------------------------------------------------------------------------
# ActionExecutor (with mock adapter)
# ---------------------------------------------------------------------------

class _MockAdapter:
    """Minimal mock to satisfy ActionExecutor init."""

    @property
    def platform_name(self):
        return "windows"


class TestActionExecutor:
    def test_refs_initially_empty(self):
        # Will fail on non-Windows because WindowsActionHandler imports comtypes,
        # but the executor itself should construct.
        try:
            exe = ActionExecutor(_MockAdapter())
            assert exe._refs == {}
        except (ImportError, OSError):
            pytest.skip("Windows-only: comtypes not available")

    def test_execute_unknown_element(self):
        try:
            exe = ActionExecutor(_MockAdapter())
            result = exe.execute("e999", "click")
            assert result.success is False
            assert "not found" in result.error.lower()
        except (ImportError, OSError):
            pytest.skip("Windows-only: comtypes not available")

    def test_execute_unknown_action(self):
        try:
            exe = ActionExecutor(_MockAdapter())
            exe.set_refs({"e0": "fake"})
            result = exe.execute("e0", "fly")
            assert result.success is False
            assert "Unknown action" in result.error
        except (ImportError, OSError):
            pytest.skip("Windows-only: comtypes not available")

    def test_set_refs(self):
        try:
            exe = ActionExecutor(_MockAdapter())
            exe.set_refs({"e0": "fake", "e1": "other"})
            assert exe._refs == {"e0": "fake", "e1": "other"}
            # Setting new refs replaces old ones
            exe.set_refs({"e5": "new"})
            assert exe._refs == {"e5": "new"}
        except (ImportError, OSError):
            pytest.skip("Windows-only: comtypes not available")


# ---------------------------------------------------------------------------
# Valid actions match schema
# ---------------------------------------------------------------------------

class TestValidActions:
    def test_all_schema_actions_present(self):
        schema_actions = {
            "click", "collapse", "decrement", "dismiss", "doubleclick",
            "expand", "focus", "increment", "longpress", "rightclick",
            "scroll", "select", "setvalue", "toggle", "type",
        }
        assert VALID_ACTIONS == schema_actions
