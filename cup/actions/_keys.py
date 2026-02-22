"""Shared key combo parsing and normalization."""

from __future__ import annotations

# Modifier key names (normalized)
MODIFIERS = frozenset({"ctrl", "alt", "shift", "win", "cmd", "meta", "super"})

# Alias normalization
_ALIASES: dict[str, str] = {
    "return": "enter",
    "esc": "escape",
    "del": "delete",
    "bs": "backspace",
    "cmd": "meta",
    "super": "meta",
    "win": "meta",
    "pgup": "pageup",
    "pgdn": "pagedown",
    "pgdown": "pagedown",
}


def parse_combo(combo: str) -> tuple[list[str], list[str]]:
    """Parse a key combo string into (modifiers, keys).

    Examples::

        >>> parse_combo("ctrl+s")
        (['ctrl'], ['s'])
        >>> parse_combo("ctrl+shift+p")
        (['ctrl', 'shift'], ['p'])
        >>> parse_combo("enter")
        ([], ['enter'])
        >>> parse_combo("a")
        ([], ['a'])

    Args:
        combo: Key combination string, parts joined with "+".

    Returns:
        (modifiers, keys) where modifiers are normalized modifier names
        and keys are the non-modifier key names.
    """
    parts = [p.strip().lower() for p in combo.split("+") if p.strip()]
    modifiers: list[str] = []
    keys: list[str] = []

    for part in parts:
        # Normalize aliases
        normalized = _ALIASES.get(part, part)
        if normalized in ("ctrl", "alt", "shift", "meta"):
            modifiers.append(normalized)
        else:
            keys.append(normalized)

    return modifiers, keys
