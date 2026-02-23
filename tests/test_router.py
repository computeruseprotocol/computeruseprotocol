"""Tests for platform detection and adapter routing."""

from __future__ import annotations

import sys

import pytest

from cup._router import detect_platform, get_adapter


class TestDetectPlatform:
    def test_returns_string(self):
        result = detect_platform()
        assert isinstance(result, str)

    def test_returns_known_platform(self):
        result = detect_platform()
        assert result in ("windows", "macos", "linux")

    def test_matches_sys_platform(self):
        result = detect_platform()
        if sys.platform == "win32":
            assert result == "windows"
        elif sys.platform == "darwin":
            assert result == "macos"
        elif sys.platform.startswith("linux"):
            assert result == "linux"


class TestGetAdapter:
    def test_unsupported_platform_raises(self):
        with pytest.raises(RuntimeError, match="No adapter available"):
            get_adapter("nintendo")

    def test_returns_correct_type_for_current_platform(self):
        platform = detect_platform()
        try:
            adapter = get_adapter(platform)
            assert adapter.platform_name == platform
        except (ImportError, OSError):
            pytest.skip(f"Adapter dependencies not available for {platform}")

    def test_two_calls_return_distinct_instances(self):
        """After singleton removal, each call should return a new adapter."""
        platform = detect_platform()
        try:
            a1 = get_adapter(platform)
            a2 = get_adapter(platform)
            assert a1 is not a2
        except (ImportError, OSError):
            pytest.skip(f"Adapter dependencies not available for {platform}")
