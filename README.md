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
  <a href="https://github.com/computeruseprotocol/computer-use-protocol/blob/main/LICENSE"><img src="https://img.shields.io/badge/License-MIT-0cc0df?style=for-the-badge&labelColor=000000" alt="MIT License"></a>
  <a href="https://computeruseprotocol.com"><img src="https://img.shields.io/badge/Website-7ed957?style=for-the-badge&logo=google-chrome&logoColor=white&labelColor=000000" alt="Website"></a>
</p>

The Computer Use Protocol (CUP) is an open specification that defines a universal way for AI agents to perceive and interact with any desktop UI. Every platform exposes accessibility differently — CUP unifies them into one schema and one format.

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

AI agents like Claude Computer Use, OpenAI CUA, and Microsoft UFO2 each independently reinvent UI perception. CUP solves this with one schema, one format, and a set of language SDKs.

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
- **15 element-level actions** + session-level `press_keys` for keyboard shortcuts — what can an agent *do* with this element?
- **Platform escape hatch** — raw native properties preserved in `node.platform.*` for advanced use

Full schema: [schema/cup.schema.json](schema/cup.schema.json) | Compact format spec: [schema/compact.md](schema/compact.md) | Role mappings: [schema/mappings.json](schema/mappings.json)

## Roles

54 ARIA-derived roles:

`alert` `alertdialog` `application` `banner` `button` `cell` `checkbox` `columnheader` `combobox` `complementary` `contentinfo` `dialog` `document` `form` `generic` `grid` `group` `heading` `img` `link` `list` `listitem` `log` `main` `marquee` `menu` `menubar` `menuitem` `menuitemcheckbox` `menuitemradio` `navigation` `none` `option` `progressbar` `radio` `region` `row` `rowheader` `scrollbar` `search` `searchbox` `separator` `slider` `spinbutton` `status` `switch` `tab` `table` `tablist` `tabpanel` `text` `textbox` `timer` `titlebar` `toolbar` `tooltip` `tree` `treeitem` `window`

## States

16 state flags (only truthy/active states are listed — absence = default):

`busy` `checked` `collapsed` `disabled` `editable` `expanded` `focused` `hidden` `mixed` `modal` `multiselectable` `offscreen` `pressed` `readonly` `required` `selected`

## Actions

15 element-level actions:

| Action | Parameters | Description |
|--------|-----------|-------------|
| `click` | — | Click/invoke the element |
| `collapse` | — | Collapse an expanded element |
| `decrement` | — | Decrement a slider/spinbutton |
| `dismiss` | — | Dismiss a dialog/popup |
| `doubleclick` | — | Double-click |
| `expand` | — | Expand a collapsed element |
| `focus` | — | Move keyboard focus to the element |
| `increment` | — | Increment a slider/spinbutton |
| `longpress` | — | Long-press (touch/mobile interaction) |
| `rightclick` | — | Right-click (context menu) |
| `scroll` | `direction: str` | Scroll container (up/down/left/right) |
| `select` | — | Select an item in a list/tree/tab |
| `setvalue` | `value: str` | Set element value programmatically |
| `toggle` | — | Toggle checkbox or switch |
| `type` | `value: str` | Type text into a field |

Session-level action (not element-scoped):

| Action | Parameters | Description |
|--------|-----------|-------------|
| `press_keys` | `keys: str` | Send a keyboard shortcut |

## Compact format

A token-efficient text representation optimized for LLM context windows (~75% smaller than JSON):

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

Line format: `[id] role "name" @x,y wxh {states} [actions] val="value" (attrs)`

Full spec: [schema/compact.md](schema/compact.md)

## SDKs

| Language | Repository | Package |
|----------|-----------|---------|
| Python | [python-sdk](https://github.com/computeruseprotocol/python-sdk) | `pip install computer-use-protocol` |
| TypeScript | [typescript-sdk](https://github.com/computeruseprotocol/typescript-sdk) | `npm install computer-use-protocol` |

## Documentation

- **[JSON Schema](schema/cup.schema.json)** — Full envelope schema
- **[Compact Format Spec](schema/compact.md)** — LLM-optimized text format
- **[Role Mappings](schema/mappings.json)** — 54 roles mapped across 6 platforms
- **[Example Envelope](schema/example.json)** — Sample CUP output

## Research

For a deep dive into the problem space — why this standard is needed, what exists today, and how AI agents perceive UIs — see [doc.md](doc.md).

## Contributing

CUP is in early development (v0.1.0). Contributions to the specification are welcome — especially:

- New role or action proposals with cross-platform mapping rationale
- Platform mapping improvements in [schema/mappings.json](schema/mappings.json)
- Schema documentation and examples

For SDK contributions (bug fixes, new platform adapters, etc.), see the language-specific repos above.

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## License

[MIT](LICENSE)
