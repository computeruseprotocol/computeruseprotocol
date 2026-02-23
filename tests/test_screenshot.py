"""Tests for Session.screenshot()."""

from __future__ import annotations

import pytest


class TestScreenshotImportError:
    def test_error_mentions_install_command(self):
        """When mss is missing, ImportError should tell the user how to install."""
        import builtins

        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "mss" or name.startswith("mss."):
                raise ImportError("No module named 'mss'")
            return original_import(name, *args, **kwargs)

        from cup import Session

        try:
            session = Session()
        except Exception:
            pytest.skip("Platform adapter not available")

        import unittest.mock

        with unittest.mock.patch("builtins.__import__", side_effect=mock_import):
            with pytest.raises(ImportError, match="pip install cup"):
                session.screenshot()


class TestScreenshotBasic:
    def test_returns_png_bytes(self):
        try:
            import mss
        except ImportError:
            pytest.skip("mss not installed")

        from cup import Session

        try:
            session = Session()
        except Exception:
            pytest.skip("Platform adapter not available")

        result = session.screenshot()
        assert isinstance(result, bytes)
        assert result[:8] == b"\x89PNG\r\n\x1a\n"

    def test_region_capture(self):
        try:
            import mss
        except ImportError:
            pytest.skip("mss not installed")

        from cup import Session

        try:
            session = Session()
        except Exception:
            pytest.skip("Platform adapter not available")

        result = session.screenshot(region={"x": 0, "y": 0, "w": 100, "h": 100})
        assert isinstance(result, bytes)
        assert result[:8] == b"\x89PNG\r\n\x1a\n"
