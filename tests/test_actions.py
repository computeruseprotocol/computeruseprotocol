"""Tests for the action execution layer."""

from __future__ import annotations

import pytest

from cup.actions._keys import parse_combo
from cup.actions.executor import VALID_ACTIONS, ActionExecutor, ActionResult

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

    def test_execute_type_without_value_rejected(self):
        try:
            exe = ActionExecutor(_MockAdapter())
            exe.set_refs({"e0": "fake"})
            result = exe.execute("e0", "type")
            assert result.success is False
            assert "requires a 'value' parameter" in result.error
        except (ImportError, OSError):
            pytest.skip("Windows-only: comtypes not available")

    def test_execute_setvalue_without_value_rejected(self):
        try:
            exe = ActionExecutor(_MockAdapter())
            exe.set_refs({"e0": "fake"})
            result = exe.execute("e0", "setvalue")
            assert result.success is False
            assert "requires a 'value' parameter" in result.error
        except (ImportError, OSError):
            pytest.skip("Windows-only: comtypes not available")

    def test_execute_scroll_without_direction_rejected(self):
        try:
            exe = ActionExecutor(_MockAdapter())
            exe.set_refs({"e0": "fake"})
            result = exe.execute("e0", "scroll")
            assert result.success is False
            assert "requires 'direction'" in result.error
        except (ImportError, OSError):
            pytest.skip("Windows-only: comtypes not available")

    def test_execute_scroll_invalid_direction_rejected(self):
        try:
            exe = ActionExecutor(_MockAdapter())
            exe.set_refs({"e0": "fake"})
            result = exe.execute("e0", "scroll", {"direction": "sideways"})
            assert result.success is False
            assert "requires 'direction'" in result.error
        except (ImportError, OSError):
            pytest.skip("Windows-only: comtypes not available")

    def test_execute_press_keys_without_keys_rejected(self):
        try:
            exe = ActionExecutor(_MockAdapter())
            result = exe.execute("", "press_keys", {})
            assert result.success is False
            assert "keys" in result.error.lower()
        except (ImportError, OSError):
            pytest.skip("Windows-only: comtypes not available")

    def test_execute_press_keys_skips_element_lookup(self):
        """press_keys should not fail with 'not found in tree' even with empty refs."""
        try:
            exe = ActionExecutor(_MockAdapter())
            # refs are empty — press_keys should NOT check refs
            result = exe.execute("", "press_keys", {"keys": "ctrl+s"})
            # It will either succeed or fail for platform reasons,
            # but must NOT fail with "not found in current tree snapshot"
            if result.error:
                assert "not found in current tree" not in result.error
        except (ImportError, OSError):
            pytest.skip("Windows-only: comtypes not available")


# ---------------------------------------------------------------------------
# Valid actions match schema
# ---------------------------------------------------------------------------


class TestValidActions:
    def test_all_schema_actions_present(self):
        schema_actions = {
            "click",
            "collapse",
            "decrement",
            "dismiss",
            "doubleclick",
            "expand",
            "focus",
            "increment",
            "longpress",
            "press_keys",
            "rightclick",
            "scroll",
            "select",
            "setvalue",
            "toggle",
            "type",
        }
        assert schema_actions == VALID_ACTIONS


# ---------------------------------------------------------------------------
# Stub handler tests (macOS / Linux)
# ---------------------------------------------------------------------------


class TestMacosStub:
    def test_execute_returns_not_implemented(self):
        from cup.actions._macos import MacosActionHandler

        handler = MacosActionHandler()
        result = handler.execute(None, "click", {})
        assert result.success is False
        assert "not yet implemented" in result.error.lower()
        assert "click" in result.error

    def test_press_keys_returns_not_implemented(self):
        from cup.actions._macos import MacosActionHandler

        handler = MacosActionHandler()
        result = handler.press_keys("ctrl+s")
        assert result.success is False
        assert "not yet implemented" in result.error.lower()
        assert "ctrl+s" in result.error

    def test_launch_app_returns_not_implemented(self):
        from cup.actions._macos import MacosActionHandler

        handler = MacosActionHandler()
        result = handler.launch_app("chrome")
        assert result.success is False
        assert "not yet implemented" in result.error.lower()
        assert "chrome" in result.error


class TestLinuxStub:
    def test_execute_returns_not_implemented(self):
        from cup.actions._linux import LinuxActionHandler

        handler = LinuxActionHandler()
        result = handler.execute(None, "click", {})
        assert result.success is False
        assert "not yet implemented" in result.error.lower()
        assert "click" in result.error

    def test_press_keys_returns_not_implemented(self):
        from cup.actions._linux import LinuxActionHandler

        handler = LinuxActionHandler()
        result = handler.press_keys("ctrl+s")
        assert result.success is False
        assert "not yet implemented" in result.error.lower()
        assert "ctrl+s" in result.error

    def test_launch_app_returns_not_implemented(self):
        from cup.actions._linux import LinuxActionHandler

        handler = LinuxActionHandler()
        result = handler.launch_app("firefox")
        assert result.success is False
        assert "not yet implemented" in result.error.lower()
        assert "firefox" in result.error


# ---------------------------------------------------------------------------
# Web stub test
# ---------------------------------------------------------------------------


class TestWebStub:
    def test_launch_app_returns_not_applicable(self):
        from cup.actions._web import WebActionHandler

        handler = WebActionHandler()
        result = handler.launch_app("chrome")
        assert result.success is False
        assert "not applicable" in result.error.lower()


# ---------------------------------------------------------------------------
# Fuzzy matching tests (Windows)
# ---------------------------------------------------------------------------


class TestFuzzyMatch:
    def test_exact_match(self):
        from cup.actions._windows import _fuzzy_match

        result = _fuzzy_match("notepad", ["notepad", "google chrome", "slack"])
        assert result == "notepad"

    def test_substring_match(self):
        from cup.actions._windows import _fuzzy_match

        result = _fuzzy_match("chrome", ["google chrome", "notepad", "slack"])
        assert result == "google chrome"

    def test_fuzzy_match(self):
        from cup.actions._windows import _fuzzy_match

        result = _fuzzy_match("chrom", ["google chrome", "notepad", "slack"])
        assert result == "google chrome"

    def test_no_match(self):
        from cup.actions._windows import _fuzzy_match

        result = _fuzzy_match("zzzznonexistent", ["notepad", "slack"])
        assert result is None

    def test_case_insensitive(self):
        from cup.actions._windows import _fuzzy_match

        result = _fuzzy_match("Chrome", ["google chrome", "notepad"])
        assert result == "google chrome"

    def test_empty_candidates(self):
        from cup.actions._windows import _fuzzy_match

        result = _fuzzy_match("chrome", [])
        assert result is None
