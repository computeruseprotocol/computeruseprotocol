# CUP Compact Format

Token-efficient text representation of CUP trees for LLM context windows.

## Line format

```
[id] role "name" @x,y wxh {states} [actions] val="value" (attrs)
```

Each field is included only when non-empty:

| Field | Format | Example | When included |
|-------|--------|---------|---------------|
| id | `[eN]` | `[e14]` | Always |
| role | bare word | `button` | Always |
| name | quoted | `"Submit"` | When non-empty |
| bounds | `@x,y wxh` | `@120,340 88x36` | When element has bounds |
| states | `{csv}` | `{disabled,checked}` | When any active states |
| actions | `[csv]` | `[click,toggle]` | When any meaningful actions |
| value | `val="..."` | `val="hello"` | For input-type elements only |
| attributes | `(...)` | `(L2 ph="Search")` | When semantically useful attributes exist |

## Hierarchy

Depth is encoded as 2-space indentation:

```
[e0] window "Discord" @509,62 1992x1274
  [e1] document "General | Lechownia" @509,62 1992x1274 {readonly}
    [e2] button "Back" @518,66 26x24 [click]
    [e3] button "Forward" @546,66 26x24 {disabled} [click]
    [e7] tree "Servers" @509,94 72x1242
      [e8] treeitem "Lechownia" @513,190 64x48 {selected} [click,select]
```

## Header

Metadata lines prefixed with `#`:

```
# CUP 0.1.0 | windows | 2560x1440
# app: Discord
# 87 nodes (353 before pruning)
```

## Attributes

Semantic attributes are serialized in a compact `(...)` suffix after all other
fields. Only the most LLM-relevant attributes are included:

| Attribute | Compact | Example |
|-----------|---------|---------|
| level | `L{n}` | `L2` for heading level 2 |
| placeholder | `ph="..."` | `ph="Enter email"` (truncated to 30 chars) |
| orientation | first char | `h` for horizontal, `v` for vertical |
| valueMin/Max | `range=min..max` | `range=0..100` |

Example with attributes:

```
[e5] heading "Introduction" (L2)
[e9] textbox "Email" [type,setvalue] val="" (ph="you@example.com")
[e12] slider "Volume" @200,300 120x20 [increment,decrement] val="50" (range=0..100)
```

## Pruning rules

The compact format prunes noise from the full tree. These rules are applied
during serialization -- the source CUP JSON tree is never modified.

A "meaningful action" is any action other than `focus` (since nearly every
element supports focus, including it is noise).

### Standard pruning (default)

1. **Hoist unnamed `generic` nodes** -- remove the node and promote its children
   to the parent level. These are structural wrappers (Windows `Pane`, web
   `<div>`) with no semantic value.

2. **Hoist unnamed `group` nodes without meaningful actions** -- same as above.
   Named groups and groups with actions (e.g., clickable panels) are kept.

3. **Skip unnamed `img` nodes** -- decorative icons with no accessible name.
   Dropped entirely with any descendants.

4. **Skip empty-name `text` nodes** -- text nodes with no content.

5. **Skip redundant text labels** -- `text` nodes that are the sole child of a
   named parent duplicate information already in the parent's name.

6. **Skip offscreen nodes without content** -- unnamed, non-interactive elements
   not visible on screen. Named or interactive offscreen nodes (e.g., scrolled-away
   chat messages) are kept with an `offscreen` state flag.

7. **Drop `focus` action** -- nearly every element supports focus; including it
   adds noise without informational value.

### Detail levels

The `detail` parameter controls pruning aggressiveness:

- **`standard`** (default) -- applies all rules above. Good balance of detail
  and token efficiency.
- **`minimal`** -- keep only nodes with meaningful actions (not just focus) and
  their ancestors. Dramatically reduces token count for large trees.
- **`full`** -- no pruning at all. Every node from the raw tree is included.
  Use when you need complete structural information.

## ID mapping

Node IDs (`e0`, `e1`, ...) are **preserved from the full CUP JSON tree**.
Gaps in ID sequence are expected because pruned nodes keep their original IDs.
This means an agent can reference `[e14]` in the compact format and the same
`e14` maps to the full node in the JSON tree with all its properties and
platform metadata.

## Truncation

Names are truncated to 80 characters in compact output. Values (`val=`) are
truncated to 120 characters. Quotes and newlines in names and values are escaped.
