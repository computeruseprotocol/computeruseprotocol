# CUP Compact Format

Token-efficient text representation of CUP trees for LLM context windows.

## Line format

```
[id] role "name" @x,y wxh {states} [actions] val="value"
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

## Hierarchy

Depth is encoded as 2-space indentation:

```
[e0] window "Discord" @509,62 1992x1274
  [e1] document "Siema eniu | Lechownia" @509,62 1992x1274 {readonly}
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

## Pruning rules

The compact format prunes noise from the full tree. These rules are applied
during serialization -- the source CUP JSON tree is never modified.

1. **Skip unnamed `generic` nodes** -- hoist their children to the parent level.
   These are structural wrappers (Windows `Pane`, web `<div>`) with no semantic value.

2. **Skip unnamed `img` nodes** -- decorative icons with no accessible name.

3. **Skip offscreen nodes without content** -- unnamed, non-interactive elements
   not visible on screen. Named or interactive offscreen nodes (e.g. scrolled-away
   chat messages) are kept with an `offscreen` state flag.

4. **Drop `focus` action** -- nearly every element supports focus; including it is noise.

5. **Skip redundant text labels** -- `text` nodes that are the sole child of a
   named parent duplicate information already in the parent's name.

## ID mapping

Node IDs (`e0`, `e1`, ...) are **preserved from the full CUP JSON tree**.
Gaps in ID sequence are expected because pruned nodes keep their original IDs.
This means an agent can reference `[e14]` in the compact format and the same
`e14` maps to the full node in the JSON tree with all its properties and
platform metadata.

## Name truncation

Names are truncated to 80 characters in compact output. Values (`val=`) are
truncated to 40 characters. Quotes and newlines in names are escaped.
