# Contributing to CUP

Thanks for your interest in the Computer Use Protocol! CUP is in early development (v0.1.0) and contributions are welcome.

## Getting started

1. Fork the repository and clone your fork
2. Create a virtual environment and install dev dependencies:

```bash
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install -e ".[dev]"
```

3. Run the test suite to verify your setup:

```bash
pytest -v
```

## Making changes

1. Create a branch from `main`:

```bash
git checkout -b my-feature
```

2. Make your changes. Follow existing code style — type hints, docstrings on public APIs, 4-space indentation.

3. Add or update tests for any changed behavior. Tests live in `tests/`.

4. Run the full suite and ensure it passes:

```bash
pytest -v
```

5. Run linting and type checks:

```bash
ruff check cup/ tests/
mypy cup/
```

6. Open a pull request against `main`. Describe what you changed and why.

## What we're looking for

High-impact areas where contributions are especially useful:

- **Android adapter** (`cup/platforms/android.py`) — ADB + AccessibilityNodeInfo
- **iOS adapter** (`cup/platforms/ios.py`) — XCUITest accessibility
- **macOS / Linux action execution** — currently tree capture only
- **Tests** — especially cross-platform integration tests
- **Language bindings** — TypeScript/Node, Go, Rust SDKs
- **Documentation** — tutorials, examples, API reference improvements

## Pull request guidelines

- Keep PRs focused. One feature or fix per PR.
- Include tests for new functionality.
- Update documentation if you change public APIs.
- Ensure CI passes before requesting review.

## Reporting bugs

Open an issue with:
- Platform and Python version
- Minimal reproduction steps
- Expected vs. actual behavior
- Full traceback if applicable

## Code style

- Python 3.10+ with `from __future__ import annotations`
- Type hints on all public function signatures
- Docstrings on public classes and functions (Google style)
- No unnecessary dependencies — platform deps are conditional

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).
