"""Tests for semantic find_elements search logic."""

from __future__ import annotations

from cup.format import _format_line
from cup.search import (
    SearchResult,
    _parse_query,
    _score_name,
    _tokenize,
    resolve_roles,
    search_tree,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _n(id: str, role: str, name: str = "", **kwargs) -> dict:
    """Shorthand node builder."""
    node = {"id": id, "role": role, "name": name}
    node.update(kwargs)
    return node


def _ids(results: list[SearchResult]) -> list[str]:
    return [r.node["id"] for r in results]


# ---------------------------------------------------------------------------
# Tokenization
# ---------------------------------------------------------------------------


class TestTokenize:
    def test_basic(self):
        assert _tokenize("Search Bar") == ["search", "bar"]

    def test_punctuation(self):
        assert _tokenize("file_name.txt") == ["file", "name", "txt"]

    def test_accents_stripped(self):
        assert _tokenize("Résumé") == ["resume"]

    def test_empty(self):
        assert _tokenize("") == []
        assert _tokenize("...") == []


# ---------------------------------------------------------------------------
# Role resolution
# ---------------------------------------------------------------------------


class TestResolveRoles:
    def test_exact_cup_role(self):
        assert resolve_roles("button") == frozenset({"button"})

    def test_synonym(self):
        roles = resolve_roles("search bar")
        assert "textbox" in roles
        assert "combobox" in roles
        assert "search" in roles

    def test_input_synonym(self):
        roles = resolve_roles("input")
        assert "textbox" in roles
        assert "combobox" in roles

    def test_unknown_returns_none(self):
        assert resolve_roles("xyznonexistent") is None

    def test_case_insensitive(self):
        assert resolve_roles("Button") == frozenset({"button"})
        assert resolve_roles("SEARCH BAR") == resolve_roles("search bar")


# ---------------------------------------------------------------------------
# Query parsing
# ---------------------------------------------------------------------------


class TestParseQuery:
    def test_button_query(self):
        role, tokens = _parse_query("the play button")
        assert role == "button"
        assert tokens == ["play"]

    def test_search_input(self):
        role, tokens = _parse_query("search input")
        # "search input" is a synonym, so it should match as a role
        assert role == "search input"
        assert tokens == []

    def test_name_only(self):
        role, tokens = _parse_query("Submit")
        # "submit" is not a role synonym
        assert role is None
        assert tokens == ["submit"]

    def test_role_with_name(self):
        role, tokens = _parse_query("volume slider")
        assert role == "slider"
        assert tokens == ["volume"]

    def test_noise_filtered(self):
        role, tokens = _parse_query("the a an button")
        assert role == "button"
        assert tokens == []

    def test_empty(self):
        role, tokens = _parse_query("")
        assert role is None
        assert tokens == []


# ---------------------------------------------------------------------------
# Name scoring
# ---------------------------------------------------------------------------


class TestScoreName:
    def test_exact_match(self):
        score = _score_name(["submit"], "Submit")
        assert score == 1.0

    def test_substring_match(self):
        score = _score_name(["submit"], "Submit Order")
        assert score > 0.5

    def test_no_match(self):
        score = _score_name(["cancel"], "Submit")
        assert score == 0.0

    def test_prefix_match(self):
        score = _score_name(["sub"], "Submit")
        assert 0.3 < score < 1.0

    def test_empty_query(self):
        assert _score_name([], "anything") == 1.0

    def test_placeholder_boost(self):
        base = _score_name(["search"], "", "", "", "")
        boosted = _score_name(["search"], "", "", "", "Search here...")
        assert boosted > base


# ---------------------------------------------------------------------------
# Backward compatibility — exact role, substring name, exact state
# ---------------------------------------------------------------------------


class TestBackwardCompat:
    def test_exact_role(self):
        tree = [
            _n(
                "e0",
                "window",
                "App",
                children=[
                    _n("e1", "button", "OK"),
                    _n("e2", "textbox", "Search"),
                    _n("e3", "button", "Cancel"),
                ],
            ),
        ]
        results = search_tree(tree, role="button", limit=10)
        ids = _ids(results)
        assert "e1" in ids
        assert "e3" in ids
        assert "e2" not in ids

    def test_name_match(self):
        tree = [
            _n(
                "e0",
                "window",
                "App",
                children=[
                    _n("e1", "button", "Submit Order"),
                    _n("e2", "button", "Cancel Order"),
                ],
            ),
        ]
        results = search_tree(tree, name="submit", limit=10)
        assert any(r.node["id"] == "e1" for r in results)

    def test_state_match(self):
        tree = [
            _n(
                "e0",
                "window",
                "App",
                children=[
                    _n("e1", "button", "OK", states=["focused"]),
                    _n("e2", "button", "Cancel", states=[]),
                ],
            ),
        ]
        results = search_tree(tree, state="focused", role="button", limit=10)
        ids = _ids(results)
        assert "e1" in ids
        assert "e2" not in ids

    def test_combined_criteria(self):
        tree = [
            _n(
                "e0",
                "window",
                "App",
                children=[
                    _n("e1", "button", "OK", states=["focused"]),
                    _n("e2", "textbox", "OK", states=["focused"]),
                    _n("e3", "button", "Cancel", states=["focused"]),
                ],
            ),
        ]
        results = search_tree(tree, role="button", name="OK", limit=10)
        assert len(results) == 1
        assert results[0].node["id"] == "e1"

    def test_no_matches(self):
        tree = [_n("e0", "button", "OK")]
        results = search_tree(tree, role="textbox")
        assert len(results) == 0

    def test_results_exclude_children(self):
        tree = [
            _n(
                "e0",
                "window",
                "App",
                children=[
                    _n("e1", "button", "OK"),
                ],
            ),
        ]
        results = search_tree(tree, role="window", limit=10)
        assert len(results) >= 1
        assert "children" not in results[0].node


# ---------------------------------------------------------------------------
# Semantic role matching
# ---------------------------------------------------------------------------


class TestSemanticRoles:
    def test_search_bar_finds_textbox(self):
        tree = [
            _n(
                "e0",
                "window",
                "App",
                children=[
                    _n("e1", "textbox", "Search", actions=["type"]),
                    _n("e2", "button", "Go"),
                ],
            ),
        ]
        results = search_tree(tree, role="search bar", limit=10)
        ids = _ids(results)
        assert "e1" in ids
        assert "e2" not in ids

    def test_input_finds_textbox_and_combobox(self):
        tree = [
            _n(
                "e0",
                "window",
                "App",
                children=[
                    _n("e1", "textbox", "Name"),
                    _n("e2", "combobox", "Country"),
                    _n("e3", "button", "Submit"),
                ],
            ),
        ]
        results = search_tree(tree, role="input", limit=10)
        ids = _ids(results)
        assert "e1" in ids
        assert "e2" in ids
        assert "e3" not in ids

    def test_dropdown_finds_combobox(self):
        tree = [_n("e0", "combobox", "Select Language")]
        results = search_tree(tree, role="dropdown", limit=10)
        assert len(results) == 1

    def test_toggle_finds_switch_and_checkbox(self):
        tree = [
            _n(
                "e0",
                "window",
                "Settings",
                children=[
                    _n("e1", "switch", "Dark Mode"),
                    _n("e2", "checkbox", "Notifications"),
                    _n("e3", "button", "Save"),
                ],
            ),
        ]
        results = search_tree(tree, role="toggle", limit=10)
        ids = _ids(results)
        assert "e1" in ids
        assert "e2" in ids
        assert "e3" not in ids


# ---------------------------------------------------------------------------
# Freeform query
# ---------------------------------------------------------------------------


class TestFreeformQuery:
    def test_play_button(self):
        tree = [
            _n(
                "e0",
                "window",
                "Player",
                children=[
                    _n("e1", "button", "Play"),
                    _n("e2", "button", "Pause"),
                    _n("e3", "slider", "Volume"),
                ],
            ),
        ]
        results = search_tree(tree, query="play button", limit=10)
        assert results[0].node["id"] == "e1"

    def test_volume_slider(self):
        tree = [
            _n(
                "e0",
                "window",
                "Player",
                children=[
                    _n("e1", "button", "Play"),
                    _n("e2", "slider", "Volume"),
                    _n("e3", "slider", "Brightness"),
                ],
            ),
        ]
        results = search_tree(tree, query="volume slider", limit=10)
        assert results[0].node["id"] == "e2"

    def test_query_name_only(self):
        tree = [
            _n(
                "e0",
                "window",
                "App",
                children=[
                    _n("e1", "button", "Submit"),
                    _n("e2", "button", "Cancel"),
                ],
            ),
        ]
        results = search_tree(tree, query="Submit", limit=10)
        # "submit" isn't a role, so it's pure name search
        assert results[0].node["id"] == "e1"


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------


class TestRanking:
    def test_exact_name_ranks_higher(self):
        tree = [
            _n(
                "e0",
                "window",
                "App",
                children=[
                    _n("e1", "button", "Play Music"),
                    _n("e2", "button", "Play"),
                ],
            ),
        ]
        results = search_tree(tree, query="play button", limit=10)
        # "Play" (exact token match) should rank >= "Play Music" (also matches)
        assert results[0].node["id"] == "e2"

    def test_onscreen_ranks_higher(self):
        tree = [
            _n(
                "e0",
                "window",
                "App",
                children=[
                    _n("e1", "button", "OK", states=["offscreen"]),
                    _n("e2", "button", "OK", states=[]),
                ],
            ),
        ]
        results = search_tree(tree, role="button", name="OK", limit=10)
        assert results[0].node["id"] == "e2"

    def test_interactive_ranks_higher(self):
        tree = [
            _n(
                "e0",
                "window",
                "App",
                children=[
                    _n("e1", "button", "OK", actions=[]),
                    _n("e2", "button", "OK", actions=["click"]),
                ],
            ),
        ]
        results = search_tree(tree, role="button", name="OK", limit=10)
        assert results[0].node["id"] == "e2"


# ---------------------------------------------------------------------------
# Raw tree search — finds elements that pruning would hide
# ---------------------------------------------------------------------------


class TestRawTreeSearch:
    def test_finds_unnamed_generic_children(self):
        """Unnamed generics are hoisted during pruning but visible in raw search."""
        tree = [
            _n(
                "e0",
                "generic",
                "",
                children=[
                    _n("e1", "button", "OK"),
                ],
            ),
        ]
        # The generic wrapper itself shouldn't match a button search
        results = search_tree(tree, role="button", limit=10)
        assert len(results) == 1
        assert results[0].node["id"] == "e1"

    def test_finds_offscreen_elements(self):
        """Offscreen elements without actions are pruned but searchable."""
        tree = [
            _n(
                "e0",
                "window",
                "App",
                children=[
                    _n("e1", "text", "Hidden Info", states=["offscreen"]),
                    _n("e2", "button", "Visible", states=[]),
                ],
            ),
        ]
        results = search_tree(tree, name="Hidden Info", limit=10)
        assert any(r.node["id"] == "e1" for r in results)

    def test_finds_deep_nested(self):
        tree = [
            _n(
                "e0",
                "window",
                "App",
                children=[
                    _n(
                        "e1",
                        "toolbar",
                        "Main",
                        children=[
                            _n("e2", "button", "Save"),
                            _n("e3", "button", "Load"),
                        ],
                    ),
                    _n(
                        "e4",
                        "region",
                        "",
                        children=[
                            _n("e5", "button", "Apply"),
                        ],
                    ),
                ],
            ),
        ]
        results = search_tree(tree, role="button", limit=10)
        ids = _ids(results)
        assert set(ids) >= {"e2", "e3", "e5"}


# ---------------------------------------------------------------------------
# Context scoring
# ---------------------------------------------------------------------------


class TestContextScoring:
    def test_textbox_in_search_region_ranks_higher(self):
        tree = [
            _n(
                "e0",
                "window",
                "App",
                children=[
                    _n(
                        "e1",
                        "search",
                        "Search",
                        children=[
                            _n("e2", "textbox", "Query", actions=["type"]),
                        ],
                    ),
                    _n(
                        "e3",
                        "group",
                        "Settings",
                        children=[
                            _n("e4", "textbox", "Username", actions=["type"]),
                        ],
                    ),
                ],
            ),
        ]
        results = search_tree(tree, query="search input", limit=10)
        # e2 is inside a "search" region — should rank higher
        ids = _ids(results)
        assert ids[0] == "e2"


# ---------------------------------------------------------------------------
# Limit
# ---------------------------------------------------------------------------


class TestLimit:
    def test_respects_limit(self):
        tree = [
            _n(
                "e0",
                "window",
                "App",
                children=[_n(f"e{i}", "button", f"Btn {i}") for i in range(1, 20)],
            ),
        ]
        results = search_tree(tree, role="button", limit=3)
        assert len(results) == 3

    def test_default_limit(self):
        tree = [
            _n(
                "e0",
                "window",
                "App",
                children=[_n(f"e{i}", "button", f"Btn {i}") for i in range(1, 20)],
            ),
        ]
        results = search_tree(tree, role="button")
        assert len(results) == 5  # default limit


# ---------------------------------------------------------------------------
# _format_line for find_element MCP output
# ---------------------------------------------------------------------------


class TestFormatLineForMatches:
    def test_format_line_basic(self):
        node = _n(
            "e5", "button", "Submit", bounds={"x": 10, "y": 20, "w": 80, "h": 30}, actions=["click"]
        )
        line = _format_line(node)
        assert "[e5]" in line
        assert "button" in line
        assert '"Submit"' in line
        assert "@10,20 80x30" in line
        assert "[click]" in line

    def test_format_line_with_states(self):
        node = _n("e0", "checkbox", "Agree", states=["checked"], actions=["toggle"])
        line = _format_line(node)
        assert "{checked}" in line
        assert "[toggle]" in line
