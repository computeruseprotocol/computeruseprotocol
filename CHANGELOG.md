# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/), and this project adheres to [Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-02-23

Initial public alpha release.

### Added
- **CUP JSON schema** with 54 ARIA-derived roles, 16 state flags, and 15 canonical actions
- **Compact text format** optimized for LLM context windows with 3-tier pruning (standard, minimal, full)
- **Platform adapters** for tree capture:
  - Windows (UIA COM via comtypes)
  - macOS (AXUIElement via pyobjc)
  - Linux (AT-SPI2 via PyGObject)
  - Web (Chrome DevTools Protocol)
- **Action execution** on Windows and Web platforms (macOS and Linux planned)
- **MCP server** (`cup-mcp`) with 7 tools for AI agent integration
- **Semantic search engine** with fuzzy matching, role synonyms, and relevance ranking
- **Viewport-aware pruning** that clips offscreen nodes using nested scrollable container intersection
- **Session API** with `capture()`, `execute()`, `press_keys()`, `find_elements()`, `batch_execute()`, and `screenshot()`
- **CLI** (`python -m cup`) for tree capture, JSON export, and compact output
- **CI** with GitHub Actions running tests on Windows, macOS, and Linux

[0.1.0]: https://github.com/k4cper-g/computer-use-protocol/releases/tag/v0.1.0
