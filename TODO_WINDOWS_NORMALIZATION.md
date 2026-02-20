# Windows Mapper Normalization TODO

The macOS mapper (`macos_tree.py`) now fully covers the CUP schema. The Windows mapper (`bench_a11y_tree_fast.py`) needs the same treatment for unified cross-platform output.

---

## 1. Missing Role Mappings

### Context-dependent refinements (like macOS subrole overrides)

UIA doesn't have subroles, but you can use `ClassName`, `AutomationId`, or ARIA properties from the cached element to refine roles.

| CUP Role | How to detect on Windows |
|---|---|
| `heading` | ClassName contains "Heading" or ARIA role from web content. UIA has no native heading type — web-based apps expose headings via ARIA properties. Consider reading `AriaRole` (UIA property 30101) and `AriaProperties` (30102). |
| `dialog` | Window with `IsDialog` property (UIA 30174, Win10+), or ClassName heuristics (e.g. `#32770` is the standard Win32 dialog class). |
| `alert` | ARIA role "alert" from AriaRole property, or ClassName heuristic. |
| `alertdialog` | ARIA role "alertdialog" from AriaRole property. |
| `searchbox` | Edit control where AutomationId or ClassName suggests search (e.g. "SearchBox", "SearchTextBox"). Or read AriaRole for web content. |
| `cell` | Children of DataGrid rows. UIA DataItem (50029) is currently mapped to `row` — its children should be `cell`. Consider checking parent ControlType. |
| `switch` | Toggle-patterned CheckBox where ClassName or AutomationId suggests a toggle switch (e.g. "ToggleSwitch" in UWP/WinUI). |
| `menuitemcheckbox` | MenuItem (50011) with Toggle pattern available. |
| `menuitemradio` | MenuItem (50011) with SelectionItem pattern and no Toggle pattern. |
| Landmarks | Read AriaRole (30101) for: `navigation`, `main`, `search`, `banner`, `contentinfo`, `complementary`, `region`, `form`. Group (50026) or Pane (50033) with these ARIA roles should be remapped. |

### Implementation approach

Add these UIA properties to `PROP_IDS` cache:

```python
UIA_AriaRolePropertyId = 30101
UIA_AriaPropertiesPropertyId = 30102
```

Then in `build_cup_node`, after the initial role mapping:

```python
aria_role = _cached_str(el, UIA_AriaRolePropertyId)

# Refine role from ARIA (web content in UIA)
if aria_role:
    ARIA_ROLE_MAP = {
        "heading": "heading",
        "dialog": "dialog",
        "alert": "alert",
        "alertdialog": "alertdialog",
        "search": "searchbox",  # or "search" for landmark
        "navigation": "navigation",
        "main": "main",
        "banner": "banner",
        "contentinfo": "contentinfo",
        "complementary": "complementary",
        "region": "region",
        "form": "form",
        "cell": "cell",
        "gridcell": "cell",
        "switch": "switch",
        "tab": "tab",
        "tabpanel": "tabpanel",
    }
    if aria_role in ARIA_ROLE_MAP:
        role = ARIA_ROLE_MAP[aria_role]

# MenuItem subrole refinement (no ARIA needed)
if ct == 50011:  # MenuItem
    if has_toggle:
        role = "menuitemcheckbox"
    elif has_sel_item:
        role = "menuitemradio"
```

---

## 2. Missing States

Add these to the states list in `build_cup_node`:

| State | UIA Source | Notes |
|---|---|---|
| `busy` | No direct UIA cached property. Check `AriaProperties` for "busy=true", or skip for now. |
| `modal` | `IsDialog` property (30174) on Windows 10+. Or check `WindowPattern.IsModal`. Add `UIA_IsWindowPatternAvailablePropertyId = 30044` and `UIA_WindowIsModalPropertyId = 30077` to PROP_IDS. |
| `required` | `AriaProperties` string contains "required=true". Or `IsRequiredForForm` UIA property (30025). |

```python
# Add to PROP_IDS:
UIA_IsRequiredForFormPropertyId = 30025
UIA_WindowIsModalPropertyId = 30077

# In build_cup_node:
is_required = _cached_bool(el, UIA_IsRequiredForFormPropertyId, False)
is_modal = _cached_bool(el, UIA_WindowIsModalPropertyId, False)

if is_required:
    states.append("required")
if is_modal:
    states.append("modal")
```

---

## 3. Missing Attributes

macOS now emits the `attributes` field. Windows needs the same.

### 3a. Heading level

```python
# AriaProperties is a semicolon-delimited string like "level=2;required=true"
# Parse it once and extract structured data:
aria_props_str = _cached_str(el, UIA_AriaPropertiesPropertyId)
aria_props = {}
if aria_props_str:
    for pair in aria_props_str.split(";"):
        if "=" in pair:
            k, v = pair.split("=", 1)
            aria_props[k.strip()] = v.strip()

# Then for headings:
attrs = {}
if role == "heading" and "level" in aria_props:
    try:
        attrs["level"] = int(aria_props["level"])
    except ValueError:
        pass
```

### 3b. Range widget min/max/now

UIA has `RangeValuePattern` properties. Add to `PROP_IDS`:

```python
UIA_RangeValueValuePropertyId = 30047
UIA_RangeValueIsReadOnlyPropertyId = 30048
UIA_RangeValueMinimumPropertyId = 30049
UIA_RangeValueMaximumPropertyId = 30050
```

```python
if has_range:
    range_min = _cached_float(el, UIA_RangeValueMinimumPropertyId)
    range_max = _cached_float(el, UIA_RangeValueMaximumPropertyId)
    range_val = _cached_float(el, UIA_RangeValueValuePropertyId)
    if range_min is not None:
        attrs["valueMin"] = range_min
    if range_max is not None:
        attrs["valueMax"] = range_max
    if range_val is not None:
        attrs["valueNow"] = range_val
```

### 3c. Placeholder

No direct UIA property for placeholder. Can be extracted from `AriaProperties` string if present (`placeholder=...`), or from the `FullDescription` property (30159, Win10+).

### 3d. URL

For Hyperlink controls (50005), read the Value pattern string — it often contains the URL.

```python
if role == "link" and val_str:
    attrs["url"] = val_str[:500]
```

### 3e. Orientation

```python
UIA_OrientationPropertyId = 30023

# Add to PROP_IDS, then:
orientation = _cached_int(el, UIA_OrientationPropertyId, -1)
if orientation == 1 and role in ("scrollbar", "slider", "separator", "toolbar", "tablist"):
    attrs["orientation"] = "horizontal"
elif orientation == 2:
    attrs["orientation"] = "vertical"
```

---

## 4. Value Field Filtering

Currently Windows emits `value` for ANY node with the Value pattern. Align with macOS — only emit for meaningful roles:

```python
# Change from:
if val_str:
    node["value"] = val_str[:200]

# To:
if val_str and role in ("textbox", "searchbox", "combobox", "spinbutton",
                         "slider", "progressbar", "document"):
    node["value"] = val_str[:200]
```

---

## 5. Envelope Enrichment

### Screen scale

```python
# Use GetDpiForSystem (Win10+) or GetDeviceCaps
def get_screen_info() -> tuple[int, int, float]:
    w = user32.GetSystemMetrics(0)
    h = user32.GetSystemMetrics(1)
    try:
        dpi = ctypes.windll.shcore.GetDpiForSystem()
        scale = dpi / 96.0
    except Exception:
        scale = 1.0
    return w, h, scale
```

### App PID and process name

```python
import ctypes.wintypes

def get_window_pid(hwnd: int) -> int:
    pid = ctypes.wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value
```

Then pass to `build_envelope(..., app_pid=pid)`.

---

## 6. Summary of PROP_IDS additions

```python
# New properties to add to PROP_IDS:
UIA_AriaRolePropertyId = 30101
UIA_AriaPropertiesPropertyId = 30102
UIA_IsRequiredForFormPropertyId = 30025
UIA_WindowIsModalPropertyId = 30077
UIA_OrientationPropertyId = 30023
UIA_RangeValueValuePropertyId = 30047
UIA_RangeValueMinimumPropertyId = 30049
UIA_RangeValueMaximumPropertyId = 30050
```

This brings the cache from 21 properties to 29. Should have negligible performance impact since UIA batches them in a single COM call.
