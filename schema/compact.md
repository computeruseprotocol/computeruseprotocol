# CUP Compact Format

Token-efficient text representation of CUP trees for LLM context windows.

## Line format

```
[id] role "name" x,y wxh {states} [actions] val="value" (attrs)
```

Each field is included only when non-empty:

| Field | Format | Example | When included |
|-------|--------|---------|---------------|
| id | `[eN]` | `[e14]` | Always |
| role | short code | `btn` | Always |
| name | quoted | `"Submit"` | When non-empty |
| bounds | `x,y wxh` | `120,340 88x36` | When node has meaningful actions |
| states | `{csv}` | `{dis,chk}` | When any active states |
| actions | `[csv]` | `[clk,tog]` | When any meaningful actions |
| value | `val="..."` | `val="hello"` | For input-type elements only |
| attributes | `(...)` | `(L2 ph="Search")` | When semantically useful attributes exist |

## Vocabulary short codes

Roles, states, and actions use short codes to reduce token cost. The full
mappings are listed below. Unknown values pass through unchanged.

### Roles (59)

| Role | Code | | Role | Code | | Role | Code |
|------|------|-|------|------|-|------|------|
| alert | `alrt` | | link | `lnk` | | separator | `sep` |
| alertdialog | `adlg` | | list | `lst` | | slider | `sld` |
| application | `app` | | listitem | `li` | | spinbutton | `spn` |
| banner | `bnr` | | log | `log` | | status | `sts` |
| button | `btn` | | main | `main` | | switch | `sw` |
| cell | `cel` | | marquee | `mrq` | | tab | `tab` |
| checkbox | `chk` | | menu | `mnu` | | table | `tbl` |
| columnheader | `colh` | | menubar | `mnub` | | tablist | `tabs` |
| combobox | `cmb` | | menuitem | `mi` | | tabpanel | `tpnl` |
| complementary | `cmp` | | menuitemcheckbox | `mic` | | text | `txt` |
| contentinfo | `ci` | | menuitemradio | `mir` | | textbox | `tbx` |
| dialog | `dlg` | | navigation | `nav` | | timer | `tmr` |
| document | `doc` | | none | `none` | | titlebar | `ttlb` |
| form | `frm` | | option | `opt` | | toolbar | `tlbr` |
| generic | `gen` | | progressbar | `pbar` | | tooltip | `ttp` |
| grid | `grd` | | radio | `rad` | | tree | `tre` |
| group | `grp` | | region | `rgn` | | treeitem | `ti` |
| heading | `hdg` | | row | `row` | | window | `win` |
| img | `img` | | rowheader | `rowh` | | | |
|  |  | | scrollbar | `sb` | | | |
|  |  | | search | `srch` | | | |
|  |  | | searchbox | `sbx` | | | |

### States (16)

| State | Code | | State | Code |
|-------|------|-|-------|------|
| busy | `bsy` | | mixed | `mix` |
| checked | `chk` | | modal | `mod` |
| collapsed | `col` | | multiselectable | `msel` |
| disabled | `dis` | | offscreen | `off` |
| editable | `edt` | | pressed | `prs` |
| expanded | `exp` | | readonly | `ro` |
| focused | `foc` | | required | `req` |
| hidden | `hid` | | selected | `sel` |

### Actions (15)

| Action | Code | | Action | Code |
|--------|------|-|--------|------|
| click | `clk` | | increment | `inc` |
| collapse | `col` | | longpress | `lp` |
| decrement | `dec` | | rightclick | `rclk` |
| dismiss | `dsm` | | scroll | `scr` |
| doubleclick | `dbl` | | select | `sel` |
| expand | `exp` | | setvalue | `sv` |
| focus | `foc` | | toggle | `tog` |
|  |  | | type | `typ` |

## Bounds

Bounds are only included for **interactable nodes** (those with meaningful
actions beyond `focus`). Non-interactable nodes are context-only — agents
reference them by ID, not coordinates, so spatial info adds tokens without
value.

Format: `x,y wxh` (no `@` prefix). Position and size are in physical pixels.

```
[e2] btn "Back" 132,52 32x32 [clk]
[e5] hdg "Introduction"                  # no bounds — not interactable
```

## Hierarchy

Depth is encoded as 2-space indentation:

```
[e0] win "Discord"
  [e1] doc "General | Lechownia" {ro}
    [e2] btn "Back" 518,66 26x24 [clk]
    [e3] btn "Forward" 546,66 26x24 {dis} [clk]
    [e7] tre "Servers" 509,94 72x1242 [scr]
      [e8] ti "Lechownia" 513,190 64x48 {sel} [clk,sel]
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
[e5] hdg "Introduction" (L2)
[e9] tbx "Email" [typ,sv] val="" (ph="you@example.com")
[e12] sld "Volume" 200,300 120x20 [inc,dec] val="50" (range=0..100)
```

## Pruning rules

The compact format prunes noise from the full tree. These rules are applied
during serialization -- the source CUP JSON tree is never modified.

A "meaningful action" is any action other than `focus` (since nearly every
element supports focus, including it is noise).

### Compact pruning (default)

1. **Skip chrome/decorative roles** -- `scrollbar`, `separator`, `titlebar`,
   `tooltip`, and `status` nodes (and their entire subtrees) are dropped.
   Scrollbar parents already expose `[scroll]`; titlebar actions use keyboard
   shortcuts; the rest are decorative or read-only status info.

2. **Skip zero-size elements** -- nodes with 0 width or 0 height are invisible
   and dropped entirely.

3. **Hoist unnamed `generic` nodes** -- remove the node and promote its children
   to the parent level. These are structural wrappers (Windows `Pane`, web
   `<div>`) with no semantic value.

4. **Hoist unnamed `region` nodes** -- same as above. Common in Electron/Chromium
   apps where nested `<div>` wrappers get exposed as UIA regions.

5. **Hoist unnamed `group` nodes without meaningful actions** -- same as above.
   Named groups and groups with actions (e.g., clickable panels) are kept.

6. **Skip unnamed `img` nodes** -- decorative icons with no accessible name.
   Dropped entirely with any descendants.

7. **Skip empty-name `text` nodes** -- text nodes with no content.

8. **Skip redundant text labels** -- `text` nodes that are the sole child of a
   named parent duplicate information already in the parent's name.

9. **Skip offscreen non-interactive nodes** -- offscreen elements with no
   meaningful actions are dropped. Interactive offscreen nodes (e.g.,
   scrolled-away buttons) are kept so the LLM knows what's available after
   scrolling.

10. **Collapse single-child structural containers** -- unnamed nodes with a
    structural role (`region`, `document`, `main`, `complementary`, `navigation`,
    `search`, `banner`, `contentinfo`, `form`) that have no meaningful actions
    and end up with exactly one child after pruning are replaced by that child.

11. **Drop `focus` action** -- nearly every element supports focus; including it
    adds noise without informational value.

### Detail levels

The `detail` parameter controls pruning aggressiveness:

- **`compact`** (default) -- applies all rules above. Good balance of detail
  and token efficiency.
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
