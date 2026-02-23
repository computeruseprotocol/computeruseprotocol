"""Semantic search engine for CUP accessibility trees.

Searches the full (unpruned) tree with:
- Semantic role matching (natural-language role synonyms)
- Fuzzy name matching (token overlap, prefix matching)
- Relevance-ranked results (role + name + context scoring)
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# All canonical CUP roles
# ---------------------------------------------------------------------------

ALL_ROLES: frozenset[str] = frozenset(
    {
        "alert",
        "alertdialog",
        "application",
        "banner",
        "blockquote",
        "button",
        "caption",
        "cell",
        "checkbox",
        "code",
        "columnheader",
        "combobox",
        "complementary",
        "contentinfo",
        "deletion",
        "dialog",
        "document",
        "emphasis",
        "figure",
        "form",
        "generic",
        "grid",
        "group",
        "heading",
        "img",
        "insertion",
        "link",
        "list",
        "listitem",
        "log",
        "main",
        "marquee",
        "math",
        "menu",
        "menubar",
        "menuitem",
        "menuitemcheckbox",
        "menuitemradio",
        "navigation",
        "none",
        "note",
        "option",
        "paragraph",
        "progressbar",
        "radio",
        "region",
        "row",
        "rowheader",
        "scrollbar",
        "search",
        "searchbox",
        "separator",
        "slider",
        "spinbutton",
        "status",
        "strong",
        "subscript",
        "superscript",
        "switch",
        "tab",
        "table",
        "tablist",
        "tabpanel",
        "text",
        "textbox",
        "timer",
        "titlebar",
        "toolbar",
        "tooltip",
        "tree",
        "treeitem",
        "window",
    }
)

# ---------------------------------------------------------------------------
# Semantic role synonyms
# ---------------------------------------------------------------------------

ROLE_SYNONYMS: dict[str, frozenset[str]] = {
    # -- text input --
    "input": frozenset({"textbox", "combobox", "searchbox", "spinbutton", "slider"}),
    "text input": frozenset({"textbox", "searchbox", "combobox"}),
    "text field": frozenset({"textbox", "searchbox", "combobox"}),
    "text box": frozenset({"textbox", "searchbox"}),
    "textarea": frozenset({"textbox", "document"}),
    "edit": frozenset({"textbox", "searchbox", "combobox", "document"}),
    "editor": frozenset({"textbox", "document"}),
    # -- search --
    "search": frozenset({"search", "searchbox", "textbox", "combobox"}),
    "search bar": frozenset({"search", "searchbox", "textbox", "combobox"}),
    "search box": frozenset({"search", "searchbox", "textbox", "combobox"}),
    "search field": frozenset({"search", "searchbox", "textbox", "combobox"}),
    "search input": frozenset({"search", "searchbox", "textbox", "combobox"}),
    # -- buttons --
    "btn": frozenset({"button"}),
    "clickable": frozenset({"button", "link", "menuitem", "tab", "treeitem", "listitem"}),
    # -- links --
    "hyperlink": frozenset({"link"}),
    "anchor": frozenset({"link"}),
    # -- dropdowns / selects --
    "dropdown": frozenset({"combobox", "menu", "list"}),
    "select": frozenset({"combobox", "list", "listitem"}),
    "combo": frozenset({"combobox"}),
    "combo box": frozenset({"combobox"}),
    # -- toggles --
    "check": frozenset({"checkbox", "switch", "menuitemcheckbox"}),
    "toggle": frozenset({"switch", "checkbox"}),
    "radio button": frozenset({"radio", "menuitemradio"}),
    "option": frozenset({"option", "radio", "listitem", "menuitemradio"}),
    # -- sliders / ranges --
    "range": frozenset({"slider", "progressbar", "spinbutton"}),
    "progress": frozenset({"progressbar"}),
    "progress bar": frozenset({"progressbar"}),
    "spinner": frozenset({"spinbutton"}),
    # -- tabs --
    "tab bar": frozenset({"tablist"}),
    "tab list": frozenset({"tablist"}),
    "tabs": frozenset({"tablist", "tab"}),
    "tab panel": frozenset({"tabpanel"}),
    # -- menus --
    "menu bar": frozenset({"menubar"}),
    "menu item": frozenset({"menuitem", "menuitemcheckbox", "menuitemradio"}),
    # -- dialogs --
    "modal": frozenset({"dialog", "alertdialog"}),
    "popup": frozenset({"dialog", "alertdialog", "tooltip", "menu"}),
    "notification": frozenset({"alert", "status", "log"}),
    "message": frozenset({"alert", "status", "log"}),
    # -- headings / titles --
    "title": frozenset({"heading", "titlebar"}),
    "header": frozenset({"heading", "banner", "columnheader", "rowheader"}),
    # -- images --
    "image": frozenset({"img"}),
    "picture": frozenset({"img"}),
    "icon": frozenset({"img", "button"}),
    # -- trees / lists --
    "tree item": frozenset({"treeitem"}),
    "list item": frozenset({"listitem"}),
    # -- tables / grids --
    "table": frozenset({"table", "grid"}),
    # -- navigation --
    "nav": frozenset({"navigation"}),
    "sidebar": frozenset({"complementary", "navigation"}),
    # -- containers --
    "panel": frozenset({"region", "group", "tabpanel"}),
    "section": frozenset({"region", "group", "main"}),
    "container": frozenset({"region", "group", "generic"}),
    # -- misc --
    "divider": frozenset({"separator"}),
    "scroll": frozenset({"scrollbar"}),
    "status bar": frozenset({"status"}),
    "tool bar": frozenset({"toolbar"}),
}

# Add identity mappings: every CUP role maps to itself.
for _r in ALL_ROLES:
    ROLE_SYNONYMS.setdefault(_r, frozenset({_r}))


# ---------------------------------------------------------------------------
# Noise words filtered from freeform queries
# ---------------------------------------------------------------------------

_NOISE_WORDS: frozenset[str] = frozenset(
    {
        "the",
        "a",
        "an",
        "this",
        "that",
        "for",
        "in",
        "on",
        "of",
        "with",
        "to",
        "and",
        "or",
        "is",
        "it",
        "its",
        "my",
        "your",
    }
)


# ---------------------------------------------------------------------------
# Tokenization
# ---------------------------------------------------------------------------

_SPLIT_RE = re.compile(r"[^a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    """Split text into lowercase tokens, stripping accents and punctuation."""
    normalized = unicodedata.normalize("NFD", text.lower())
    stripped = "".join(c for c in normalized if unicodedata.category(c) != "Mn")
    return [t for t in _SPLIT_RE.split(stripped) if t]


# ---------------------------------------------------------------------------
# Role resolution
# ---------------------------------------------------------------------------


def resolve_roles(role_query: str) -> frozenset[str] | None:
    """Resolve a role query to a set of matching CUP roles.

    Returns None if the query doesn't constrain roles at all.
    """
    q = role_query.strip().lower()

    # Direct synonym lookup (covers exact CUP roles + natural language)
    if q in ROLE_SYNONYMS:
        return ROLE_SYNONYMS[q]

    # Token-based fallback: try each token
    for token in _tokenize(q):
        if token in ROLE_SYNONYMS:
            return ROLE_SYNONYMS[token]

    # Last resort: check if the query IS a substring of a role name.
    # Don't check the reverse (role in query) — too many false positives
    # (e.g., "none" found inside "xyznonexistent").
    if len(q) >= 3:
        matches = frozenset(r for r in ALL_ROLES if q in r)
        if matches:
            return matches

    return None  # don't filter by role


# ---------------------------------------------------------------------------
# Query parsing
# ---------------------------------------------------------------------------


def _parse_query(query: str) -> tuple[str | None, list[str]]:
    """Parse a freeform query into (role_hint, name_tokens).

    Tries longest-first token subsequences against ROLE_SYNONYMS.
    Remaining tokens (minus noise words) become the name query.

    Examples:
        "the play button"  -> ("button", ["play"])
        "search input"     -> ("search input", [])
        "Submit"           -> (None, ["submit"])
        "volume slider"    -> ("slider", ["volume"])
    """
    tokens = _tokenize(query)
    if not tokens:
        return None, []

    # Try longest-first subsequences (max 3 words)
    best_role: str | None = None
    best_span: tuple[int, int] = (0, 0)

    for length in range(min(len(tokens), 3), 0, -1):
        for start in range(len(tokens) - length + 1):
            candidate = " ".join(tokens[start : start + length])
            if candidate in ROLE_SYNONYMS:
                best_role = candidate
                best_span = (start, start + length)
                break
        if best_role:
            break

    # Remaining tokens = name query (filter noise)
    name_tokens = tokens[: best_span[0]] + tokens[best_span[1] :]
    name_tokens = [t for t in name_tokens if t not in _NOISE_WORDS]

    return best_role, name_tokens


# ---------------------------------------------------------------------------
# Name scoring
# ---------------------------------------------------------------------------


def _score_name(
    query_tokens: list[str],
    node_name: str,
    node_description: str = "",
    node_value: str = "",
    placeholder: str = "",
) -> float:
    """Score how well a node's text fields match the query tokens.

    Returns a score in [0.0, 1.0].
    """
    if not query_tokens:
        return 1.0  # no name filter = everything matches

    query_joined = " ".join(query_tokens)
    name_lower = node_name.lower()

    # Signal 1: full substring match in name
    full_substr = 0.0
    if query_joined in name_lower:
        full_substr = 1.0 if query_joined == name_lower else 0.85

    # Signal 2: token-level matching
    name_tokens = set(_tokenize(node_name))
    token_score = 0.0

    if name_tokens:
        matched = 0.0
        for qt in query_tokens:
            if qt in name_tokens:
                matched += 1.0
            elif any(nt.startswith(qt) for nt in name_tokens):
                matched += 0.7  # prefix: "sub" matches "submit"
            elif any(qt.startswith(nt) for nt in name_tokens):
                matched += 0.5  # reverse prefix
            elif any(qt in nt for nt in name_tokens):
                matched += 0.6  # substring within token
        token_score = matched / len(query_tokens)

    name_score = max(full_substr, token_score)

    # Exactness bonus: prefer tighter matches (fewer extra tokens in name)
    if name_tokens and name_score > 0:
        overlap = len(set(query_tokens) & name_tokens) / max(len(name_tokens), 1)
        name_score = name_score * (0.85 + 0.15 * overlap)

    # Boost from secondary fields
    secondary = _score_secondary(query_tokens, node_description, node_value, placeholder)

    return min(1.0, name_score + secondary * 0.15)


def _score_secondary(
    query_tokens: list[str],
    description: str,
    value: str,
    placeholder: str,
) -> float:
    """Score secondary text fields (description, value, placeholder)."""
    best = 0.0
    for field in (description, value, placeholder):
        if not field:
            continue
        field_tokens = set(_tokenize(field))
        if not field_tokens:
            continue
        matched = sum(1 for qt in query_tokens if qt in field_tokens)
        best = max(best, matched / len(query_tokens))
    return best


# ---------------------------------------------------------------------------
# Context scoring
# ---------------------------------------------------------------------------


def _score_context(
    node: dict,
    parent_chain: list[dict],
    query_tokens: list[str],
    target_roles: frozenset[str] | None,
) -> float:
    """Score contextual relevance of a node."""
    score = 0.0

    # Ancestor name matches query tokens
    if query_tokens:
        qt_set = set(query_tokens)
        for ancestor in parent_chain:
            if set(_tokenize(ancestor.get("name", ""))) & qt_set:
                score += 0.1
                break

    # Ancestor role matches target roles
    if target_roles:
        for ancestor in parent_chain:
            if ancestor.get("role") in target_roles:
                score += 0.1
                break

    # Interactive bonus
    actions = node.get("actions", [])
    if any(a != "focus" for a in actions):
        score += 0.05

    # Visibility bonus
    states = node.get("states", [])
    if "offscreen" not in states:
        score += 0.05

    # Focused bonus
    if "focused" in states:
        score += 0.02

    return score


# ---------------------------------------------------------------------------
# Per-node scoring
# ---------------------------------------------------------------------------


def _score_node(
    node: dict,
    parent_chain: list[dict],
    target_roles: frozenset[str] | None,
    name_tokens: list[str],
    state: str | None,
) -> float:
    """Score a single node. Returns 0.0 if hard-filtered out.

    Weight budget: role=0.35, name=0.50, state=0.10, context≤0.25
    """
    # State: hard filter
    if state is not None and state not in node.get("states", []):
        return 0.0

    # Role: hard filter when specified
    node_role = node.get("role", "")
    role_score = 0.0
    if target_roles is not None:
        if node_role in target_roles:
            role_score = 0.35
        else:
            return 0.0

    # Name scoring
    if name_tokens:
        raw = _score_name(
            name_tokens,
            node.get("name", ""),
            node.get("description", ""),
            node.get("value", ""),
            (node.get("attributes") or {}).get("placeholder", ""),
        )
        if raw == 0.0:
            return 0.0  # hard filter: name specified but no match at all
        name_score = raw * 0.50
    else:
        # No name filter: partial credit if role matched
        name_score = 0.15 if target_roles else 0.0

    # State bonus
    state_score = 0.10 if state is not None else 0.0

    # Context
    context_score = _score_context(node, parent_chain, name_tokens, target_roles)

    return role_score + name_score + state_score + context_score


# ---------------------------------------------------------------------------
# Tree walking
# ---------------------------------------------------------------------------


def _walk_and_score(
    nodes: list[dict],
    parent_chain: list[dict],
    target_roles: frozenset[str] | None,
    name_tokens: list[str],
    state: str | None,
    results: list[SearchResult],
    threshold: float,
) -> None:
    """Recursively walk the tree, scoring each node."""
    for node in nodes:
        score = _score_node(node, parent_chain, target_roles, name_tokens, state)

        if score >= threshold:
            result_node = {k: v for k, v in node.items() if k != "children"}
            results.append(SearchResult(node=result_node, score=score))

        children = node.get("children", [])
        if children:
            _walk_and_score(
                children,
                parent_chain + [node],
                target_roles,
                name_tokens,
                state,
                results,
                threshold,
            )


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class SearchResult:
    """A scored search result."""

    node: dict
    score: float


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def search_tree(
    tree: list[dict],
    *,
    query: str | None = None,
    role: str | None = None,
    name: str | None = None,
    state: str | None = None,
    limit: int = 5,
    threshold: float = 0.15,
) -> list[SearchResult]:
    """Search a CUP tree with semantic matching and relevance ranking.

    Searches the full (unpruned) tree.

    Args:
        tree: Raw CUP tree nodes.
        query: Freeform semantic query ("play button", "search input").
               Auto-parsed into role + name signals.
        role: Role filter (exact CUP role or synonym like "search bar").
        name: Name filter (fuzzy token matching).
        state: State filter (exact match).
        limit: Max results to return.
        threshold: Minimum score to include.

    Returns:
        List of SearchResult sorted by descending score.
    """
    # Parse inputs
    effective_role = role
    effective_name_tokens: list[str] = []

    if query:
        parsed_role, parsed_name = _parse_query(query)
        effective_role = role or parsed_role
        effective_name_tokens = _tokenize(name) if name else parsed_name
    elif name:
        effective_name_tokens = _tokenize(name)

    # Resolve roles
    target_roles: frozenset[str] | None = None
    if effective_role:
        target_roles = resolve_roles(effective_role)

    # Walk and score
    results: list[SearchResult] = []
    _walk_and_score(
        tree,
        parent_chain=[],
        target_roles=target_roles,
        name_tokens=effective_name_tokens,
        state=state,
        results=results,
        threshold=threshold,
    )

    # Sort by score descending (stable: preserves tree order for equal scores)
    results.sort(key=lambda r: -r.score)

    return results[:limit]
