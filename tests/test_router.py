"""Tests for platform detection and adapter routing."""

from __future__ import annotations

import sys

import pytest

from cup._router import detect_platform


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
