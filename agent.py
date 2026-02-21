"""
CUP Agent: Interactive AI UI automation powered by Gemini and the CUP format.

Captures all visible windows' accessibility trees in CUP compact format,
sends them to Gemini with tool definitions, and executes the returned actions
via UIA COM patterns.

Usage:
    python agent.py                              # interactive REPL
    python agent.py --model gemini-3-flash-preview  # choose model
"""

from __future__ import annotations

from dotenv import load_dotenv
load_dotenv()

import argparse
import ctypes
import ctypes.wintypes
import itertools
import json
import os
import time
from datetime import datetime

import comtypes
import mss
from google import genai
from google.genai import types

# Existing CUP infrastructure ------------------------------------------------
from cup.platforms.windows import (
    init_uia,
    make_cache_request,
    build_cup_node,
    _win32_enum_windows,
    _win32_screen_size,
    AutomationElementMode_Full,
    TreeScope_Subtree,
)
from cup.format import build_envelope, serialize_compact

# ---------------------------------------------------------------------------
# UIA Pattern IDs (for action execution)
# ---------------------------------------------------------------------------

UIA_InvokePatternId = 10000
UIA_ValuePatternId = 10002
UIA_ScrollPatternId = 10004
UIA_ExpandCollapsePatternId = 10005
UIA_SelectionItemPatternId = 10010
UIA_TogglePatternId = 10015

# ---------------------------------------------------------------------------
# Win32 keyboard input via SendInput
# ---------------------------------------------------------------------------

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_EXTENDEDKEY = 0x0001

VK_MAP = {
    "enter": 0x0D, "return": 0x0D, "tab": 0x09,
    "escape": 0x1B, "esc": 0x1B,
    "backspace": 0x08, "delete": 0x2E, "space": 0x20,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
    "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73,
    "f5": 0x74, "f6": 0x75, "f7": 0x76, "f8": 0x77,
    "f9": 0x78, "f10": 0x79, "f11": 0x7A, "f12": 0x7B,
    "ctrl": 0xA2, "alt": 0xA4, "shift": 0xA0, "win": 0x5B,
}

# Extended keys that need KEYEVENTF_EXTENDEDKEY
_EXTENDED_VKS = {0x26, 0x28, 0x25, 0x27, 0x24, 0x23, 0x21, 0x22, 0x2E}

# --- Win32 INPUT structures (must match 64-bit layout: sizeof(INPUT) == 40) ---

ULONG_PTR = ctypes.c_uint64


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.wintypes.DWORD),
        ("dwFlags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.wintypes.WORD),
        ("wScan", ctypes.wintypes.WORD),
        ("dwFlags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", ctypes.wintypes.DWORD),
        ("wParamL", ctypes.wintypes.WORD),
        ("wParamH", ctypes.wintypes.WORD),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("mi", MOUSEINPUT),
        ("ki", KEYBDINPUT),
        ("hi", HARDWAREINPUT),
    ]


class INPUT(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.wintypes.DWORD),
        ("_input", _INPUT_UNION),
    ]


def _make_key_input(vk: int, *, down: bool = True) -> INPUT:
    flags = 0 if down else KEYEVENTF_KEYUP
    if vk in _EXTENDED_VKS:
        flags |= KEYEVENTF_EXTENDEDKEY
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp._input.ki.wVk = vk
    inp._input.ki.dwFlags = flags
    return inp


def send_key_combo(keys_string: str) -> None:
    """Parse 'ctrl+s', 'enter', 'alt+f4' etc. and send via SendInput."""
    parts = [p.strip().lower() for p in keys_string.split("+")]
    modifiers = []
    main_keys = []
    for p in parts:
        if p in ("ctrl", "alt", "shift", "win"):
            modifiers.append(VK_MAP[p])
        elif p in VK_MAP:
            main_keys.append(VK_MAP[p])
        elif len(p) == 1:
            main_keys.append(ord(p.upper()))

    inputs = []
    for mod in modifiers:
        inputs.append(_make_key_input(mod, down=True))
    for key in main_keys:
        inputs.append(_make_key_input(key, down=True))
    for key in reversed(main_keys):
        inputs.append(_make_key_input(key, down=False))
    for mod in reversed(modifiers):
        inputs.append(_make_key_input(mod, down=False))

    if inputs:
        arr = (INPUT * len(inputs))(*inputs)
        sent = ctypes.windll.user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))
        if sent == 0:
            err = ctypes.get_last_error()
            raise RuntimeError(f"SendInput failed, sent 0/{len(inputs)} events (error={err})")


# ---------------------------------------------------------------------------
# Tree capture with element reference mapping
# ---------------------------------------------------------------------------

def walk_cached_tree_with_refs(
    element, depth: int, max_depth: int,
    id_gen, stats: dict, ref_map: dict,
) -> dict | None:
    """Walk pre-cached UIA subtree, building CUP nodes AND storing element refs."""
    if depth > max_depth:
        return None

    node = build_cup_node(element, id_gen, stats)
    ref_map[node["id"]] = element  # map element ID to live COM element

    if depth < max_depth:
        children = []
        try:
            cached_children = element.GetCachedChildren()
            if cached_children is not None:
                for i in range(cached_children.Length):
                    child = cached_children.GetElement(i)
                    child_node = walk_cached_tree_with_refs(
                        child, depth + 1, max_depth, id_gen, stats, ref_map,
                    )
                    if child_node is not None:
                        children.append(child_node)
        except (comtypes.COMError, Exception):
            pass
        if children:
            node["children"] = children

    return node


def capture_all_windows(uia, subtree_cr) -> tuple[str, dict, str]:
    """Capture all visible windows. Returns (compact_text, ref_map, summary)."""
    windows = _win32_enum_windows(visible_only=True)

    id_gen = itertools.count()
    stats = {"nodes": 0, "max_depth": 0, "roles": {}}
    ref_map: dict[str, object] = {}
    roots: list[dict] = []

    for hwnd, title in windows:
        try:
            el = uia.ElementFromHandleBuildCache(hwnd, subtree_cr)
        except comtypes.COMError:
            continue
        root = walk_cached_tree_with_refs(el, 0, 999, id_gen, stats, ref_map)
        if root is not None:
            roots.append(root)

    if not roots:
        return "# Empty tree", {}, "(no windows)"

    summary = f"{len(roots)} windows"
    sw, sh = _win32_screen_size()
    envelope = build_envelope(roots, platform="windows",
                              screen_w=sw, screen_h=sh)
    compact = serialize_compact(envelope)
    return compact, ref_map, summary


# ---------------------------------------------------------------------------
# Step logging (accessibility tree + screenshot per step)
# ---------------------------------------------------------------------------

def take_screenshot(filepath: str) -> None:
    """Capture a full-screen screenshot and save as PNG."""
    with mss.mss() as sct:
        sct.shot(output=filepath)


def save_step(session_dir: str, step: int, compact: str, label: str = "") -> None:
    """Save the accessibility tree and a screenshot for the current step."""
    prefix = f"step_{step:03d}"
    if label:
        prefix += f"_{label}"

    tree_path = os.path.join(session_dir, f"{prefix}_tree.cup")
    with open(tree_path, "w", encoding="utf-8") as f:
        f.write(compact)

    screenshot_path = os.path.join(session_dir, f"{prefix}_screenshot.png")
    take_screenshot(screenshot_path)

    print(f"  [saved] {prefix} (tree + screenshot)")


# ---------------------------------------------------------------------------
# Action executors
# ---------------------------------------------------------------------------

# Pattern interfaces — imported lazily after init_uia() generates the module
_IInvoke = None
_IToggle = None
_IValue = None
_IExpandCollapse = None
_ISelectionItem = None
_IScroll = None


def _ensure_pattern_interfaces():
    """Import comtypes pattern interfaces (must be called after init_uia)."""
    global _IInvoke, _IToggle, _IValue, _IExpandCollapse, _ISelectionItem, _IScroll
    if _IInvoke is not None:
        return
    from comtypes.gen.UIAutomationClient import (
        IUIAutomationInvokePattern,
        IUIAutomationTogglePattern,
        IUIAutomationValuePattern,
        IUIAutomationExpandCollapsePattern,
        IUIAutomationSelectionItemPattern,
        IUIAutomationScrollPattern,
    )
    _IInvoke = IUIAutomationInvokePattern
    _IToggle = IUIAutomationTogglePattern
    _IValue = IUIAutomationValuePattern
    _IExpandCollapse = IUIAutomationExpandCollapsePattern
    _ISelectionItem = IUIAutomationSelectionItemPattern
    _IScroll = IUIAutomationScrollPattern


def _get_pattern(element, pattern_id, interface):
    """Get a UIA pattern from an element, returning None if unavailable."""
    try:
        pat = element.GetCurrentPattern(pattern_id)
        if pat:
            return pat.QueryInterface(interface)
    except (comtypes.COMError, Exception):
        pass
    return None


def execute_click(element):
    pat = _get_pattern(element, UIA_InvokePatternId, _IInvoke)
    if pat:
        pat.Invoke()
        return "Clicked"
    # Fallback: try SetFocus + Enter
    try:
        element.SetFocus()
        time.sleep(0.05)
        send_key_combo("enter")
        return "Clicked (focus+enter fallback)"
    except Exception:
        raise RuntimeError("Element does not support click")


def execute_toggle(element):
    pat = _get_pattern(element, UIA_TogglePatternId, _IToggle)
    if pat:
        pat.Toggle()
        return "Toggled"
    raise RuntimeError("Element does not support toggle")


def execute_type(element, text: str):
    # Try ValuePattern first
    pat = _get_pattern(element, UIA_ValuePatternId, _IValue)
    if pat:
        try:
            pat.SetValue(text)
            return f"Set value to: {text}"
        except comtypes.COMError:
            pass
    # Fallback: focus + type character by character
    try:
        element.SetFocus()
        time.sleep(0.05)
        # Select all existing text, then type
        send_key_combo("ctrl+a")
        time.sleep(0.05)
        for char in text:
            send_key_combo(char)
            time.sleep(0.01)
        return f"Typed: {text}"
    except Exception as e:
        raise RuntimeError(f"Failed to type: {e}")


def execute_expand(element):
    pat = _get_pattern(element, UIA_ExpandCollapsePatternId, _IExpandCollapse)
    if pat:
        pat.Expand()
        return "Expanded"
    raise RuntimeError("Element does not support expand")


def execute_collapse(element):
    pat = _get_pattern(element, UIA_ExpandCollapsePatternId, _IExpandCollapse)
    if pat:
        pat.Collapse()
        return "Collapsed"
    raise RuntimeError("Element does not support collapse")


def execute_select(element):
    pat = _get_pattern(element, UIA_SelectionItemPatternId, _ISelectionItem)
    if pat:
        pat.Select()
        return "Selected"
    # Fallback: click
    return execute_click(element)


def execute_scroll(element, direction: str):
    pat = _get_pattern(element, UIA_ScrollPatternId, _IScroll)
    if pat:
        # ScrollAmount: 0=LargeDecrement 1=SmallDecrement 2=NoAmount 3=SmallIncrement 4=LargeIncrement
        h, v = 2, 2  # NoAmount by default
        if direction == "up":
            v = 1
        elif direction == "down":
            v = 3
        elif direction == "left":
            h = 1
        elif direction == "right":
            h = 3
        pat.Scroll(h, v)
        return f"Scrolled {direction}"
    raise RuntimeError("Element does not support scroll")


# ---------------------------------------------------------------------------
# Tool dispatch
# ---------------------------------------------------------------------------

def handle_tool_call(name: str, inp: dict, ref_map: dict) -> dict:
    """Execute a tool call, return result dict."""
    if name == "done":
        return {"success": True, "message": inp.get("summary", "")}

    if name == "keypress":
        try:
            send_key_combo(inp["keys"])
            return {"success": True, "message": f"Pressed {inp['keys']}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    eid = inp.get("element_id", "")
    if eid not in ref_map:
        return {"success": False, "error": f"Element '{eid}' not found in current tree"}

    element = ref_map[eid]
    try:
        if name == "click":
            msg = execute_click(element)
        elif name == "type_text":
            msg = execute_type(element, inp["text"])
        elif name == "toggle":
            msg = execute_toggle(element)
        elif name == "select":
            msg = execute_select(element)
        elif name == "expand":
            msg = execute_expand(element)
        elif name == "collapse":
            msg = execute_collapse(element)
        elif name == "scroll":
            msg = execute_scroll(element, inp.get("direction", "down"))
        else:
            return {"success": False, "error": f"Unknown tool: {name}"}
        return {"success": True, "message": msg}
    except comtypes.COMError as e:
        return {"success": False, "error": f"UIA COM error: {e}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Gemini integration
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are a Windows UI automation agent. You read the accessibility tree (CUP compact format) of all visible windows and execute actions to accomplish the user's goal.

## CUP Compact Format

Each line represents a UI element:
  [id] role "name" @x,y wxh {states} [actions] val="value"

- [id]: Element identifier like [e14]. Use this to reference elements in tool calls (pass "e14", not "[e14]").
- role: Semantic type — button, textbox, menuitem, tab, treeitem, checkbox, link, etc.
- "name": The element's label.
- @x,y wxh: Screen position and size in pixels.
- {states}: Active states — disabled, focused, checked, expanded, collapsed, selected, readonly, editable, offscreen.
- [actions]: Supported actions — click, toggle, type, setvalue, select, expand, collapse, scroll.
- val="...": Current value for input fields.

Hierarchy is shown by 2-space indentation.

## Rules

1. Only reference element IDs that exist in the current tree.
2. Only use actions listed in the element's [actions] bracket.
3. Elements with {disabled} cannot be interacted with.
4. After each action, you'll receive the updated tree — check it before the next action.
5. Work step-by-step. Do one action at a time.
6. Call 'done' when you've completed the user's instruction.
7. If you can't find the right element, explain what you see and suggest alternatives.\
"""

TOOL_DECLARATIONS = [
    {
        "name": "click",
        "description": "Click a UI element (InvokePattern). For buttons, links, menu items, and elements with [click] action.",
        "parameters": {
            "type": "object",
            "properties": {
                "element_id": {"type": "string", "description": "Element ID, e.g. 'e14'"}
            },
            "required": ["element_id"],
        },
    },
    {
        "name": "type_text",
        "description": "Type text into a text field. Replaces existing content. For elements with [type] or [setvalue] action.",
        "parameters": {
            "type": "object",
            "properties": {
                "element_id": {"type": "string", "description": "Element ID of the text field"},
                "text": {"type": "string", "description": "Text to type"},
            },
            "required": ["element_id", "text"],
        },
    },
    {
        "name": "toggle",
        "description": "Toggle a checkbox or toggle button. For elements with [toggle] action.",
        "parameters": {
            "type": "object",
            "properties": {
                "element_id": {"type": "string", "description": "Element ID"}
            },
            "required": ["element_id"],
        },
    },
    {
        "name": "select",
        "description": "Select an item in a list, tree, or tab. For elements with [select] action.",
        "parameters": {
            "type": "object",
            "properties": {
                "element_id": {"type": "string", "description": "Element ID"}
            },
            "required": ["element_id"],
        },
    },
    {
        "name": "expand",
        "description": "Expand a collapsed element (tree node, combo box). For elements with [expand] action.",
        "parameters": {
            "type": "object",
            "properties": {
                "element_id": {"type": "string", "description": "Element ID"}
            },
            "required": ["element_id"],
        },
    },
    {
        "name": "collapse",
        "description": "Collapse an expanded element. For elements with [collapse] action.",
        "parameters": {
            "type": "object",
            "properties": {
                "element_id": {"type": "string", "description": "Element ID"}
            },
            "required": ["element_id"],
        },
    },
    {
        "name": "scroll",
        "description": "Scroll within a scrollable container. For elements with [scroll] action.",
        "parameters": {
            "type": "object",
            "properties": {
                "element_id": {"type": "string", "description": "Element ID of the scrollable container"},
                "direction": {"type": "string", "enum": ["up", "down", "left", "right"]},
            },
            "required": ["element_id", "direction"],
        },
    },
    {
        "name": "keypress",
        "description": "Send a keyboard shortcut. E.g. 'enter', 'escape', 'ctrl+s', 'alt+f4', 'ctrl+shift+p'.",
        "parameters": {
            "type": "object",
            "properties": {
                "keys": {"type": "string", "description": "Key combination, e.g. 'ctrl+s'"}
            },
            "required": ["keys"],
        },
    },
    {
        "name": "done",
        "description": "Signal that the task is complete.",
        "parameters": {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "What was accomplished"}
            },
            "required": ["summary"],
        },
    },
]


# ---------------------------------------------------------------------------
# Main REPL
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="CUP Agent — AI-powered UI automation")
    parser.add_argument("--model", default="gemini-3-flash-preview",
                        help="Gemini model to use (default: gemini-3-flash-preview)")
    args = parser.parse_args()

    print("CUP Agent — Interactive AI UI Automation")
    print("=" * 42)
    print("Initializing UIA COM...")

    uia = init_uia()
    _ensure_pattern_interfaces()

    subtree_cr = make_cache_request(
        uia,
        element_mode=AutomationElementMode_Full,
        tree_scope=TreeScope_Subtree,
    )

    client = genai.Client(
        api_key=os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"),
    )
    gemini_tools = types.Tool(function_declarations=TOOL_DECLARATIONS)
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        tools=[gemini_tools],
    )

    session_dir = os.path.join("runs", datetime.now().strftime("%Y-%m-%d_%H-%M-%S"))
    os.makedirs(session_dir, exist_ok=True)
    step_counter = 0

    print(f"Model: {args.model}")
    print(f"Session logs: {session_dir}")
    print("Ready. Focus a window, then type an instruction.")
    print("Type 'quit' to exit, 'tree' to see the current tree.\n")

    while True:
        try:
            user_input = input("You> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            break

        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit", "q"):
            break

        # Show tree on demand
        if user_input.lower() == "tree":
            compact, _, _ = capture_all_windows(uia, subtree_cr)
            print(compact)
            continue

        # Capture current UI state
        compact, ref_map, summary = capture_all_windows(uia, subtree_cr)
        print(f"  Captured {summary} — {len(ref_map)} elements")
        save_step(session_dir, step_counter, compact, "initial")
        step_counter += 1

        # Build conversation contents
        contents = [
            types.Content(
                role="user",
                parts=[types.Part.from_text(
                    text=f"Current UI:\n\n{compact}\n\nInstruction: {user_input}",
                )],
            )
        ]

        # Agent tool-use loop
        done = False
        while not done:
            try:
                response = client.models.generate_content(
                    model=args.model,
                    config=config,
                    contents=contents,
                )
            except Exception as e:
                print(f"  API error: {e}")
                break

            # Append assistant response to conversation
            assistant_content = response.candidates[0].content
            contents.append(assistant_content)

            function_responses = []
            has_function_call = False

            for part in assistant_content.parts:
                if part.text and part.text.strip():
                    print(f"Agent> {part.text}")
                elif part.function_call:
                    has_function_call = True
                    fc = part.function_call
                    fc_args = dict(fc.args) if fc.args else {}
                    print(f"  -> {fc.name}({json.dumps(fc_args, ensure_ascii=False)})")

                    if fc.name == "done":
                        print(f"  Done: {fc_args.get('summary', '')}")
                        function_responses.append(
                            types.Part.from_function_response(
                                name=fc.name,
                                response={"result": "Task complete."},
                            )
                        )
                        done = True
                    else:
                        result = handle_tool_call(fc.name, fc_args, ref_map)
                        ok = result.get("success", False)
                        msg = result.get("message", result.get("error", ""))
                        print(f"     {'OK' if ok else 'FAIL'}: {msg}")

                        # Re-capture tree after action (longer wait for keypresses
                        # that open new windows/menus)
                        delay = 1.0 if fc.name == "keypress" else 0.5
                        time.sleep(delay)
                        compact, ref_map, _ = capture_all_windows(uia, subtree_cr)
                        save_step(session_dir, step_counter, compact, fc.name)
                        step_counter += 1

                        function_responses.append(
                            types.Part.from_function_response(
                                name=fc.name,
                                response={
                                    "result": (
                                        f"{'Success' if ok else 'Error'}: {msg}\n\n"
                                        f"Updated UI:\n{compact}"
                                    )
                                },
                            )
                        )

            if function_responses:
                contents.append(
                    types.Content(role="user", parts=function_responses)
                )

            if not has_function_call:
                done = True

        print()


if __name__ == "__main__":
    main()
