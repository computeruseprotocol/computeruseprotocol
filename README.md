<p align="center">
  <a href="https://computeruseprotocol.com">
    <img src="assets/banner.png" alt="Computer Use Protocol">
  </a>
</p>

<p align="center">
  <b>A universal protocol for AI agents to perceive and interact with any desktop UI</b>
</p>

<br>

<p align="center">
  <a href="https://pypi.org/project/cup"><img src="https://img.shields.io/pypi/v/cup?style=for-the-badge&color=FF6F61&labelColor=000000" alt="PyPI"></a>
  <a href="https://github.com/k4cper-g/computer-use-protocol/blob/main/LICENSE"><img src="https://img.shields.io/badge/License-MIT-0cc0df?style=for-the-badge&labelColor=000000" alt="MIT License"></a>
  <a href="https://computeruseprotocol.com"><img src="https://img.shields.io/badge/Website-7ed957?style=for-the-badge&logo=google-chrome&logoColor=white&labelColor=000000" alt="Website"></a>
</p>

The Computer Use Protocol (CUP) is an open protocol that provides a universal way for AI agents to perceive and interact with any desktop UI. Every platform exposes accessibility differently - CUP unifies them into one schema, one format, and one library. Whether you're building an AI-powered desktop assistant, automating UI testing, or creating autonomous agent workflows, CUP provides a standardized way to connect AI models with the interfaces they need to control.


## The problem

Every platform exposes UI accessibility trees differently:

| Platform | API | Roles | IPC |
|----------|-----|-------|-----|
| Windows | UIA (COM) | ~40 ControlTypes | COM |
| macOS | AXUIElement | AXRole + AXSubrole | XPC / Mach |
| Linux | AT-SPI2 | ~100+ AtspiRole values | D-Bus |
| Web | ARIA | ~80 ARIA roles | In-process / CDP |
| Android | AccessibilityNodeInfo | Java class names | Binder |
| iOS | UIAccessibility | ~15 trait flags | In-process |

AI agents like Claude Computer Use, OpenAI CUA, and Microsoft UFO² each independently reinvent UI perception. CUP solves this with one schema, one format, one library.

## Quick start

```python
import cup

# Full accessibility tree as a CUP envelope (dict)
envelope = cup.get_tree()

# Just the foreground window
envelope = cup.get_foreground_tree()

# Compact text format — optimized for LLM context windows
text = cup.get_compact()
print(text)
```

Output (compact format):

```
# CUP 0.1.0 | windows | 2560x1440
# app: Discord
# 87 nodes (353 before pruning)

[e0] window "Discord" @509,62 1992x1274
    [e1] document "General | Lechownia" @509,62 1992x1274 {readonly}
        [e2] button "Back" @518,66 26x24 [click]
        [e3] button "Forward" @546,66 26x24 {disabled} [click]
        [e7] tree "Servers" @509,94 72x1242
            [e8] treeitem "Lechownia" @513,190 64x48 {selected} [click,select]
```

## CLI

```bash
# Print compact tree of the foreground window
python -m cup --foreground --compact

# Save full JSON envelope
python -m cup --json-out tree.json

# Filter by app name
python -m cup --app Discord --compact

# Capture from Chrome via CDP
python -m cup --platform web --cdp-port 9222 --compact
```

## Platform support

| Platform | Adapter | Status |
|----------|---------|--------|
| Windows | UIA COM (comtypes) | Stable |
| macOS | AXUIElement (pyobjc) | Stable |
| Linux | AT-SPI2 (PyGObject) | Stable |
| Web | Chrome DevTools Protocol | Stable |
| Android | | Planned |
| iOS | | Planned |

### Platform dependencies

CUP auto-detects your platform. Install the extras for your OS:

```bash
# Windows (requires comtypes)
pip install cup[windows]

# macOS (requires pyobjc)
pip install cup[macos]

# Linux (requires PyGObject — install via system package manager)
sudo apt install python3-gi gir1.2-atspi-2.0
pip install cup

# Web (requires websocket-client, works on any OS)
pip install cup[web]
```

## Schema

CUP defines a JSON envelope format built on ARIA roles:

```json
{
    "version": "0.1.0",
    "platform": "windows",
    "timestamp": 1740067200000,
    "screen": { "w": 2560, "h": 1440, "scale": 1.0 },
    "app": { "name": "Discord", "pid": 1234 },
    "tree": [
        {
            "id": "e0",
            "role": "window",
            "name": "Discord",
            "bounds": { "x": 509, "y": 62, "w": 1992, "h": 1274 },
            "states": ["focused"],
            "actions": ["click"],
            "children": [ ... ]
        }
    ]
}
```

Key design decisions:
- **54 ARIA-derived roles** — the universal subset that maps cleanly across all 6 platforms
- **16 state flags** — only truthy/active states are listed (absence = default)
- **13 canonical actions** — what can an agent *do* with this element?
- **Platform escape hatch** — raw native properties preserved in `node.platform.*` for advanced use

Full schema: [schema/cup.schema.json](schema/cup.schema.json) | Compact format spec: [schema/compact.md](schema/compact.md) | Role mappings: [schema/mappings.json](schema/mappings.json)

## Architecture

```
cup/
├── __init__.py                 # Public API: get_tree, get_compact, ...
├── __main__.py                 # CLI entry point
├── _base.py                    # Abstract PlatformAdapter interface
├── _router.py                  # Platform detection & adapter dispatch
├── format.py                   # Envelope builder, compact serializer, tree pruning
└── platforms/
        ├── windows.py           # Windows UIA adapter
        ├── macos.py             # macOS AXUIElement adapter
        ├── linux.py             # Linux AT-SPI2 adapter
        └── web.py               # Chrome CDP adapter
```

Adding a new platform means implementing `PlatformAdapter` — see [cup/_base.py](cup/_base.py) for the interface.

## How it works

1. **Detect platform** — `sys.platform` → adapter selection
2. **Enumerate windows** — native API call to list top-level windows
3. **Walk accessibility tree** — recursive traversal, mapping native roles/states/actions to ARIA-based CUP schema
4. **Build envelope** — wrap tree in metadata (platform, screen size, timestamp)
5. **Serialize** — JSON envelope or compact text (with intelligent pruning for LLM consumption)

The compact format applies pruning rules to reduce token count by ~75% while preserving all semantically meaningful and interactive elements. See [schema/compact.md](schema/compact.md) for the full spec.

## Contributing

CUP is in early development (v0.1.0). Contributions welcome — especially:

- Android adapter (`cup/platforms/android.py`)
- iOS adapter (`cup/platforms/ios.py`)
- Tests and CI across platforms
- Language bindings (JS, Go, Rust)

## Research

For a deep dive into the problem space — why this standard is needed, what exists today, and how AI agents perceive UIs — see [doc.md](doc.md).

## License

[MIT](LICENSE)
