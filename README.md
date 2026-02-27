<p align="center">
  <a href="https://computeruseprotocol.com">
    <img src="assets/banner.png" alt="Computer Use Protocol" width="1200">
  </a>
</p>

<p align="center">
  A universal protocol for AI agents to perceive and interact with any desktop UI.
</p>

<p align="center">
  <a href="https://www.npmjs.com/package/computeruseprotocol"><img src="https://img.shields.io/npm/v/computeruseprotocol" alt="npm version"></a>
  <a href="https://pypi.org/project/computeruseprotocol/"><img src="https://img.shields.io/pypi/v/computeruseprotocol" alt="PyPI version"></a>
  <a href="https://github.com/computeruseprotocol/computer-use-protocol/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue" alt="MIT License"></a>
  <a href="https://computeruseprotocol.com"><img src="https://img.shields.io/badge/website-computeruseprotocol.com-green" alt="Website"></a>
</p>

---

Computer Use Protocol is a universal schema for representing UI accessibility trees, one format that works identically across Windows, macOS, Linux, Web, Android, and iOS. It includes a compact text encoding optimized for LLM context windows (~75% smaller than JSON), making it ideal for AI agents that need to perceive and act on desktop UIs. This repository is that core: the JSON schema, the compact text format, the cross-platform role/state/action mappings, and documentation.

CUP also provides [SDKs](#sdks) for capturing and interacting with native UI trees, and MCP servers for exposing those capabilities directly to AI agents like Claude and Copilot.

## Schema

CUP defines a JSON envelope format built on ARIA-derived roles:

```json
{
    "version": "0.1.0",
    "platform": "windows",
    "timestamp": 1740067200000,
    "screen": { "w": 2560, "h": 1440, "scale": 1.0 },
    "app": { "name": "Spotify", "pid": 1234 },
    "tree": [
        {
            "id": "e0",
            "role": "window",
            "name": "Spotify",
            "bounds": { "x": 120, "y": 40, "w": 1680, "h": 1020 },
            "states": ["focused"],
            "actions": ["click"],
            "children": [ ... ]
        }
    ]
}
```

CUP compact format (~75% token reduction, heavily optimized for CUA/LLMs):

```json
[e0] win "Spotify" 120,40 1680x1020
  [e1] doc "Spotify" 120,40 1680x1020
    [e2] btn "Back" 132,52 32x32 [clk]
    [e3] btn "Forward" 170,52 32x32 {dis} [clk]
    [e7] nav "Main" 120,88 240x972
      [e8] lnk "Home" 132,100 216x40 {sel} [clk]
```

Key design decisions:
- **59 ARIA-derived roles** - the universal subset that maps cleanly across all 6 platforms
- **16 state flags** - only truthy/active states are listed (absence = default)
- **15 action verbs** - a canonical vocabulary for what can be done with an element (the protocol defines the names; SDKs provide execution)
- **Platform escape hatch** - raw native properties preserved in `node.platform.*` for advanced use


Full schema: [schema/cup.schema.json](schema/cup.schema.json) | 
Compact format spec: [schema/compact.md](schema/compact.md)


## Roles

59 ARIA-derived roles:

`alert` `alertdialog` `application` `banner` `button` `cell` `checkbox` `columnheader` `combobox` `complementary` `contentinfo` `dialog` `document` `form` `generic` `grid` `group` `heading` `img` `link` `list` `listitem` `log` `main` `marquee` `menu` `menubar` `menuitem` `menuitemcheckbox` `menuitemradio` `navigation` `none` `option` `progressbar` `radio` `region` `row` `rowheader` `scrollbar` `search` `searchbox` `separator` `slider` `spinbutton` `status` `switch` `tab` `table` `tablist` `tabpanel` `text` `textbox` `timer` `titlebar` `toolbar` `tooltip` `tree` `treeitem` `window`

Role mappings: [schema/mappings.json](schema/mappings.json)

## States

16 state flags (only truthy/active states are listed, absence = default):

`busy` `checked` `collapsed` `disabled` `editable` `expanded` `focused` `hidden` `mixed` `modal` `multiselectable` `offscreen` `pressed` `readonly` `required` `selected`

## Actions

The protocol defines 15 canonical action verbs, the vocabulary for what an agent can do with an element. The protocol specifies the names and semantics; SDKs provide the actual execution against native platform APIs.

| Action | Parameters | Description |
|--------|-----------|-------------|
| `click` | - | Click/invoke the element |
| `collapse` | - | Collapse an expanded element |
| `decrement` | - | Decrement a slider/spinbutton |
| `dismiss` | - | Dismiss a dialog/popup |
| `doubleclick` | - | Double-click |
| `expand` | - | Expand a collapsed element |
| `focus` | - | Move keyboard focus to the element |
| `increment` | - | Increment a slider/spinbutton |
| `longpress` | - | Long-press (touch/mobile interaction) |
| `rightclick` | - | Right-click (context menu) |
| `scroll` | `direction: str` | Scroll container (up/down/left/right) |
| `select` | - | Select an item in a list/tree/tab |
| `setvalue` | `value: str` | Set element value programmatically |
| `toggle` | - | Toggle checkbox or switch |
| `type` | `value: str` | Type text into a field |

Session-level actions (not element-scoped):

| Action | Parameters | Description |
|--------|-----------|-------------|
| `press_keys` | `keys: str` | Send a keyboard shortcut |
| `wait` | `ms: int` | Wait/delay between actions in a batch |

## Why CUP?

Every platform exposes UI accessibility differently. Windows uses UIA with ~40 ControlTypes, macOS has AXUIElement with its own role system, Linux uses AT-SPI2 with 100+ roles, and the web has ~80 ARIA roles. AI agents like Claude Computer Use, OpenAI CUA, and Microsoft UFO2 each independently reinvent UI perception.

- **One format everywhere** - write agent logic once, run it on any platform
- **LLM-optimized** - compact encoding uses ~75% fewer tokens than raw JSON
- **Built for actions** - 15 canonical verbs that map to native platform APIs
- **No information loss** - raw native properties preserved via `node.platform.*`

## SDKs

SDKs implement the protocol. They capture native accessibility trees, normalize them into CUP format, execute actions, and optionally expose everything through MCP servers for AI agent integration.

| Language | Repository | Package |
|----------|-----------|---------|
| Python | [python-sdk](https://github.com/computeruseprotocol/python-sdk) | `pip install computeruseprotocol` |
| TypeScript | [typescript-sdk](https://github.com/computeruseprotocol/typescript-sdk) | `npm install computeruseprotocol` |

Building your own SDK? All you need is this spec. Implement tree capture for your target platform, normalize into the CUP schema, and you're compatible with every tool in the ecosystem.

## Documentation

- **[JSON Schema](schema/cup.schema.json)** - Full envelope schema
- **[Compact Format Spec](schema/compact.md)** - LLM-optimized text format
- **[Role Mappings](schema/mappings.json)** - 59 roles mapped across 6 platforms
- **[Example Envelope](schema/example.json)** - Sample CUP output

## Contributing

CUP is in early development (v0.1.0). Contributions to the specification are welcome, especially:

- New role or action proposals with cross-platform mapping rationale
- Platform mapping improvements in [schema/mappings.json](schema/mappings.json)
- Schema documentation and examples

For SDK contributions (bug fixes, new platform adapters, etc.), see the language-specific repos above.

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## License

[MIT](LICENSE)
