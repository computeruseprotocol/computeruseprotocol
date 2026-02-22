"""Tests for find_elements matching and search logic."""

from __future__ import annotations

from cup.format import prune_tree, _format_line


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_node(id: str, role: str, name: str = "", **kwargs) -> dict:
    node = {"id": id, "role": role, "name": name}
    node.update(kwargs)
    return node


# ---------------------------------------------------------------------------
# _node_matches (Session.@staticmethod — tested inline here)
# ---------------------------------------------------------------------------

def _node_matches(node, *, role=None, name=None, state=None) -> bool:
    """Mirror of Session._node_matches for unit testing without an adapter."""
    if role is not None and node.get("role") != role:
        return False
    if name is not None and name.lower() not in node.get("name", "").lower():
        return False
    if state is not None and state not in node.get("states", []):
        return False
    return True


def _search_tree(nodes, *, role=None, name=None, state=None):
    """Mirror of Session._search_tree + find_elements for testing."""
    results = []
    _walk(nodes, role=role, name=name, state=state, results=results)
    return results


def _walk(nodes, *, role, name, state, results):
    for node in nodes:
        if _node_matches(node, role=role, name=name, state=state):
            results.append({k: v for k, v in node.items() if k != "children"})
        for child in node.get("children", []):
            _walk([child], role=role, name=name, state=state, results=results)


# ---------------------------------------------------------------------------
# Node matching
# ---------------------------------------------------------------------------

class TestNodeMatches:
    def test_match_role_exact(self):
        node = _make_node("e0", "button", "OK")
        assert _node_matches(node, role="button")
        assert not _node_matches(node, role="textbox")

    def test_match_name_case_insensitive_substring(self):
        node = _make_node("e0", "button", "Submit Order")
        assert _node_matches(node, name="submit")
        assert _node_matches(node, name="Order")
        assert _node_matches(node, name="SUBMIT ORDER")
        assert not _node_matches(node, name="Cancel")

    def test_match_state_exact(self):
        node = _make_node("e0", "button", "OK", states=["focused", "enabled"])
        assert _node_matches(node, state="focused")
        assert not _node_matches(node, state="disabled")

    def test_match_all_criteria_and_logic(self):
        node = _make_node("e0", "button", "Submit", states=["focused"])
        assert _node_matches(node, role="button", name="Submit", state="focused")
        assert not _node_matches(node, role="button", name="Submit", state="disabled")
        assert not _node_matches(node, role="textbox", name="Submit", state="focused")

    def test_match_no_criteria_matches_everything(self):
        node = _make_node("e0", "button", "OK")
        assert _node_matches(node)

    def test_match_empty_name(self):
        node = _make_node("e0", "button", "")
        assert _node_matches(node, name="")
        assert not _node_matches(node, name="something")


# ---------------------------------------------------------------------------
# Tree search integration
# ---------------------------------------------------------------------------

class TestFindElements:
    def test_find_by_role(self):
        tree = prune_tree([
            _make_node("e0", "window", "App", children=[
                _make_node("e1", "button", "OK"),
                _make_node("e2", "textbox", "Search"),
                _make_node("e3", "button", "Cancel"),
            ]),
        ])
        matches = _search_tree(tree, role="button")
        assert len(matches) == 2
        assert {m["name"] for m in matches} == {"OK", "Cancel"}

    def test_find_by_name_substring(self):
        tree = prune_tree([
            _make_node("e0", "window", "App", children=[
                _make_node("e1", "button", "Submit Order"),
                _make_node("e2", "button", "Cancel Order"),
                _make_node("e3", "textbox", "Order Number"),
            ]),
        ])
        matches = _search_tree(tree, name="order")
        assert len(matches) == 3

    def test_find_by_state(self):
        tree = prune_tree([
            _make_node("e0", "window", "App", children=[
                _make_node("e1", "button", "OK", states=["focused"]),
                _make_node("e2", "button", "Cancel", states=[]),
            ]),
        ])
        matches = _search_tree(tree, state="focused")
        assert len(matches) == 1
        assert matches[0]["name"] == "OK"

    def test_find_combined_criteria(self):
        tree = prune_tree([
            _make_node("e0", "window", "App", children=[
                _make_node("e1", "button", "OK", states=["focused"]),
                _make_node("e2", "textbox", "OK", states=["focused"]),
                _make_node("e3", "button", "Cancel", states=["focused"]),
            ]),
        ])
        matches = _search_tree(tree, role="button", name="OK")
        assert len(matches) == 1
        assert matches[0]["id"] == "e1"

    def test_find_no_matches(self):
        tree = prune_tree([_make_node("e0", "button", "OK")])
        matches = _search_tree(tree, role="textbox")
        assert len(matches) == 0

    def test_results_exclude_children(self):
        tree = prune_tree([
            _make_node("e0", "window", "App", children=[
                _make_node("e1", "button", "OK"),
            ]),
        ])
        matches = _search_tree(tree, role="window")
        assert len(matches) == 1
        assert "children" not in matches[0]

    def test_searches_pruned_tree(self):
        """Unnamed generics should be hoisted out before search."""
        tree = prune_tree([
            _make_node("e0", "generic", "", children=[
                _make_node("e1", "button", "OK"),
            ]),
        ])
        assert _search_tree(tree, role="generic") == []
        assert len(_search_tree(tree, role="button")) == 1

    def test_deep_nested_matches(self):
        tree = prune_tree([
            _make_node("e0", "window", "App", children=[
                _make_node("e1", "toolbar", "Main", children=[
                    _make_node("e2", "button", "Save"),
                    _make_node("e3", "button", "Load"),
                ]),
                _make_node("e4", "panel", "Content", children=[
                    _make_node("e5", "button", "Apply"),
                ]),
            ]),
        ])
        matches = _search_tree(tree, role="button")
        assert len(matches) == 3
        assert {m["name"] for m in matches} == {"Save", "Load", "Apply"}


# ---------------------------------------------------------------------------
# _format_line for find_element MCP output
# ---------------------------------------------------------------------------

class TestFormatLineForMatches:
    def test_format_line_basic(self):
        node = _make_node("e5", "button", "Submit",
                          bounds={"x": 10, "y": 20, "w": 80, "h": 30},
                          actions=["click"])
        line = _format_line(node)
        assert "[e5]" in line
        assert "button" in line
        assert '"Submit"' in line
        assert "@10,20 80x30" in line
        assert "[click]" in line

    def test_format_line_with_states(self):
        node = _make_node("e0", "checkbox", "Agree",
                          states=["checked"],
                          actions=["toggle"])
        line = _format_line(node)
        assert "{checked}" in line
        assert "[toggle]" in line
