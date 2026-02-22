"""Tests for CUP format utilities: envelope builder, compact serializer, overview, and tree pruning."""

from __future__ import annotations

from cup.format import build_envelope, serialize_compact, serialize_overview, prune_tree


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_node(id: str, role: str, name: str = "", **kwargs) -> dict:
    """Create a minimal CUP node for testing."""
    node = {"id": id, "role": role, "name": name}
    node.update(kwargs)
    return node


def _make_envelope(tree: list[dict], **kwargs) -> dict:
    """Create a minimal CUP envelope for testing."""
    defaults = {
        "platform": "windows",
        "screen_w": 1920,
        "screen_h": 1080,
    }
    defaults.update(kwargs)
    return build_envelope(tree, **defaults)


# ---------------------------------------------------------------------------
# build_envelope
# ---------------------------------------------------------------------------

class TestBuildEnvelope:
    def test_required_fields(self):
        env = _make_envelope([])
        assert env["version"] == "0.1.0"
        assert env["platform"] == "windows"
        assert env["screen"] == {"w": 1920, "h": 1080}
        assert env["tree"] == []
        assert "timestamp" in env

    def test_screen_scale_omitted_when_1(self):
        env = _make_envelope([], screen_scale=1.0)
        assert "scale" not in env["screen"]

    def test_screen_scale_included_when_not_1(self):
        env = _make_envelope([], screen_scale=2.0)
        assert env["screen"]["scale"] == 2.0

    def test_app_info_included(self):
        env = _make_envelope([], app_name="Firefox", app_pid=1234)
        assert env["app"]["name"] == "Firefox"
        assert env["app"]["pid"] == 1234

    def test_app_info_omitted_when_empty(self):
        env = _make_envelope([])
        assert "app" not in env

    def test_tree_preserved(self):
        nodes = [_make_node("e0", "button", "OK")]
        env = _make_envelope(nodes)
        assert len(env["tree"]) == 1
        assert env["tree"][0]["role"] == "button"

    def test_tools_included(self):
        tools = [{"name": "search", "description": "Search the web"}]
        env = _make_envelope([], tools=tools)
        assert env["tools"] == tools

    def test_tools_omitted_when_none(self):
        env = _make_envelope([], tools=None)
        assert "tools" not in env

    def test_scope_included(self):
        env = _make_envelope([], scope="foreground")
        assert env["scope"] == "foreground"

    def test_scope_omitted_when_none(self):
        env = _make_envelope([])
        assert "scope" not in env


# ---------------------------------------------------------------------------
# prune_tree
# ---------------------------------------------------------------------------

class TestPruneTree:
    def test_unnamed_generic_hoisted(self):
        tree = [_make_node("e0", "generic", "", children=[
            _make_node("e1", "button", "OK"),
        ])]
        pruned = prune_tree(tree)
        assert len(pruned) == 1
        assert pruned[0]["role"] == "button"

    def test_named_generic_kept(self):
        tree = [_make_node("e0", "generic", "Panel", children=[
            _make_node("e1", "button", "OK"),
        ])]
        pruned = prune_tree(tree)
        assert len(pruned) == 1
        assert pruned[0]["role"] == "generic"
        assert pruned[0]["name"] == "Panel"

    def test_unnamed_img_skipped(self):
        tree = [_make_node("e0", "img", "")]
        pruned = prune_tree(tree)
        assert len(pruned) == 0

    def test_named_img_kept(self):
        tree = [_make_node("e0", "img", "Logo")]
        pruned = prune_tree(tree)
        assert len(pruned) == 1

    def test_empty_text_skipped(self):
        tree = [_make_node("e0", "text", "")]
        pruned = prune_tree(tree)
        assert len(pruned) == 0

    def test_named_text_kept(self):
        tree = [_make_node("e0", "text", "Hello")]
        pruned = prune_tree(tree)
        assert len(pruned) == 1

    def test_redundant_text_child_skipped(self):
        """Text that is the sole child of a named parent is redundant."""
        tree = [_make_node("e0", "button", "Submit", children=[
            _make_node("e1", "text", "Submit"),
        ])]
        pruned = prune_tree(tree)
        assert len(pruned) == 1
        assert "children" not in pruned[0]

    def test_offscreen_unnamed_no_actions_skipped(self):
        tree = [_make_node("e0", "group", "", states=["offscreen"])]
        pruned = prune_tree(tree)
        assert len(pruned) == 0

    def test_offscreen_named_kept(self):
        tree = [_make_node("e0", "group", "Chat message", states=["offscreen"])]
        pruned = prune_tree(tree)
        assert len(pruned) == 1

    def test_offscreen_with_actions_kept(self):
        tree = [_make_node("e0", "button", "", states=["offscreen"], actions=["click"])]
        pruned = prune_tree(tree)
        assert len(pruned) == 1

    def test_unnamed_group_without_actions_hoisted(self):
        tree = [_make_node("e0", "group", "", children=[
            _make_node("e1", "button", "OK"),
        ])]
        pruned = prune_tree(tree)
        assert len(pruned) == 1
        assert pruned[0]["role"] == "button"

    def test_unnamed_group_with_actions_kept(self):
        tree = [_make_node("e0", "group", "", actions=["click"], children=[
            _make_node("e1", "button", "OK"),
        ])]
        pruned = prune_tree(tree)
        assert len(pruned) == 1
        assert pruned[0]["role"] == "group"

    def test_deep_nesting_pruned(self):
        """Multiple levels of unnamed generics should all be hoisted."""
        tree = [_make_node("e0", "generic", "", children=[
            _make_node("e1", "generic", "", children=[
                _make_node("e2", "generic", "", children=[
                    _make_node("e3", "button", "Deep"),
                ]),
            ]),
        ])]
        pruned = prune_tree(tree)
        assert len(pruned) == 1
        assert pruned[0]["id"] == "e3"
        assert pruned[0]["role"] == "button"


# ---------------------------------------------------------------------------
# serialize_compact
# ---------------------------------------------------------------------------

class TestSerializeCompact:
    def test_header_format(self):
        env = _make_envelope([_make_node("e0", "button", "OK")])
        text = serialize_compact(env)
        lines = text.strip().split("\n")
        assert lines[0].startswith("# CUP 0.1.0 | windows | 1920x1080")

    def test_header_with_app(self):
        env = _make_envelope(
            [_make_node("e0", "button", "OK")],
            app_name="Firefox",
        )
        text = serialize_compact(env)
        assert "# app: Firefox" in text

    def test_node_format(self):
        env = _make_envelope([_make_node(
            "e0", "button", "Submit",
            bounds={"x": 100, "y": 200, "w": 80, "h": 30},
            states=["focused"],
            actions=["click", "focus"],
        )])
        text = serialize_compact(env)
        # focus action should be dropped
        assert "[e0] button \"Submit\" @100,200 80x30 {focused} [click]" in text

    def test_indentation(self):
        env = _make_envelope([_make_node("e0", "window", "App", children=[
            _make_node("e1", "button", "OK"),
        ])])
        text = serialize_compact(env)
        lines = [l for l in text.strip().split("\n") if not l.startswith("#") and l.strip()]
        assert lines[0].startswith("[e0]")
        assert lines[1].startswith("  [e1]")

    def test_pruning_applied(self):
        """Compact serializer should prune unnamed generics."""
        env = _make_envelope([_make_node("e0", "generic", "", children=[
            _make_node("e1", "button", "OK"),
        ])])
        text = serialize_compact(env)
        assert "generic" not in text
        assert "[e1] button" in text

    def test_node_count_header(self):
        env = _make_envelope([_make_node("e0", "generic", "", children=[
            _make_node("e1", "button", "A"),
            _make_node("e2", "button", "B"),
        ])])
        text = serialize_compact(env)
        # 2 nodes after pruning (generic hoisted), 3 before
        assert "2 nodes (3 before pruning)" in text

    def test_value_for_textbox(self):
        env = _make_envelope([_make_node(
            "e0", "textbox", "Search",
            value="hello world",
        )])
        text = serialize_compact(env)
        assert 'val="hello world"' in text

    def test_name_truncation(self):
        long_name = "A" * 100
        env = _make_envelope([_make_node("e0", "button", long_name)])
        text = serialize_compact(env)
        assert "A" * 80 + "..." in text

    def test_value_truncation_at_120(self):
        long_value = "x" * 150
        env = _make_envelope([_make_node(
            "e0", "textbox", "Input", value=long_value,
        )])
        text = serialize_compact(env)
        assert 'val="' + "x" * 120 + '..."' in text
        assert "x" * 150 not in text

    def test_value_not_truncated_under_120(self):
        short_value = "y" * 100
        env = _make_envelope([_make_node(
            "e0", "textbox", "Input", value=short_value,
        )])
        text = serialize_compact(env)
        assert 'val="' + "y" * 100 + '"' in text

    def test_webmcp_tools_header(self):
        tools = [{"name": "search"}, {"name": "navigate"}]
        env = _make_envelope([_make_node("e0", "button", "OK")], tools=tools)
        text = serialize_compact(env)
        assert "2 WebMCP tools available" in text

    def test_window_list_in_header(self):
        """When window_list is provided, compact output includes window names."""
        env = _make_envelope([_make_node("e0", "button", "OK")], app_name="VS Code")
        window_list = [
            {"title": "VS Code", "pid": 1234, "foreground": True, "bounds": None},
            {"title": "Firefox", "pid": 5678, "foreground": False, "bounds": None},
        ]
        text = serialize_compact(env, window_list=window_list)
        assert "# --- 2 open windows ---" in text
        assert "#   VS Code [fg]" in text
        assert "#   Firefox" in text
        # Foreground marker should NOT appear on non-fg windows
        lines = text.split("\n")
        firefox_line = [l for l in lines if "Firefox" in l and l.startswith("#")]
        assert len(firefox_line) == 1
        assert "[fg]" not in firefox_line[0]

    def test_no_window_list_when_none(self):
        """When window_list is None, no window section in header."""
        env = _make_envelope([_make_node("e0", "button", "OK")])
        text = serialize_compact(env)
        assert "open windows" not in text


# ---------------------------------------------------------------------------
# serialize_overview
# ---------------------------------------------------------------------------

class TestSerializeOverview:
    def test_header_format(self):
        windows = [
            {"title": "VS Code", "pid": 1234, "foreground": True, "bounds": None},
        ]
        text = serialize_overview(
            windows, platform="windows", screen_w=1920, screen_h=1080,
        )
        assert "# CUP 0.1.0 | windows | 1920x1080" in text
        assert "# overview | 1 windows" in text

    def test_foreground_marker(self):
        windows = [
            {"title": "VS Code", "pid": 1234, "foreground": True, "bounds": None},
            {"title": "Firefox", "pid": 5678, "foreground": False, "bounds": None},
        ]
        text = serialize_overview(
            windows, platform="windows", screen_w=1920, screen_h=1080,
        )
        assert "* [fg] VS Code" in text
        assert "  Firefox" in text

    def test_pid_included(self):
        windows = [
            {"title": "App", "pid": 42, "foreground": False, "bounds": None},
        ]
        text = serialize_overview(
            windows, platform="linux", screen_w=2560, screen_h=1440,
        )
        assert "(pid:42)" in text

    def test_bounds_included(self):
        windows = [
            {
                "title": "App",
                "pid": 1,
                "foreground": False,
                "bounds": {"x": 100, "y": 50, "w": 800, "h": 600},
            },
        ]
        text = serialize_overview(
            windows, platform="windows", screen_w=1920, screen_h=1080,
        )
        assert "@100,50 800x600" in text

    def test_url_included_for_web(self):
        windows = [
            {
                "title": "GitHub",
                "pid": None,
                "foreground": True,
                "bounds": None,
                "url": "https://github.com",
            },
        ]
        text = serialize_overview(
            windows, platform="web", screen_w=1280, screen_h=720,
        )
        assert "url:https://github.com" in text

    def test_empty_window_list(self):
        text = serialize_overview(
            [], platform="windows", screen_w=1920, screen_h=1080,
        )
        assert "# overview | 0 windows" in text

    def test_no_element_ids(self):
        """Overview should NOT contain element IDs (no tree walking)."""
        windows = [
            {"title": "App", "pid": 1, "foreground": True, "bounds": None},
        ]
        text = serialize_overview(
            windows, platform="windows", screen_w=1920, screen_h=1080,
        )
        assert "[e" not in text


# ---------------------------------------------------------------------------
# Detail pruning levels
# ---------------------------------------------------------------------------

class TestDetailPruning:
    def test_detail_full_no_pruning(self):
        """detail='full' should preserve all nodes including unnamed generics."""
        tree = [_make_node("e0", "generic", "", children=[
            _make_node("e1", "button", "OK"),
        ])]
        pruned = prune_tree(tree, detail="full")
        assert len(pruned) == 1
        assert pruned[0]["role"] == "generic"
        assert len(pruned[0]["children"]) == 1

    def test_detail_standard_prunes_generics(self):
        """detail='standard' (default) should hoist unnamed generics."""
        tree = [_make_node("e0", "generic", "", children=[
            _make_node("e1", "button", "OK"),
        ])]
        pruned = prune_tree(tree, detail="standard")
        assert len(pruned) == 1
        assert pruned[0]["role"] == "button"

    def test_detail_minimal_keeps_only_interactive(self):
        """detail='minimal' should keep only nodes with meaningful actions."""
        tree = [_make_node("e0", "window", "App", children=[
            _make_node("e1", "heading", "Title"),
            _make_node("e2", "text", "Some description"),
            _make_node("e3", "button", "Submit", actions=["click"]),
            _make_node("e4", "textbox", "Email", actions=["type", "setvalue"]),
            _make_node("e5", "group", "Footer", actions=["focus"]),
        ])]
        pruned = prune_tree(tree, detail="minimal")
        assert len(pruned) == 1  # window kept as ancestor
        window = pruned[0]
        children = window.get("children", [])
        child_roles = [c["role"] for c in children]
        assert "button" in child_roles
        assert "textbox" in child_roles
        # heading, text, and focus-only group should be dropped
        assert "heading" not in child_roles
        assert "text" not in child_roles
        assert "group" not in child_roles

    def test_detail_minimal_preserves_ancestors(self):
        """detail='minimal' should keep ancestors of interactive nodes."""
        tree = [_make_node("e0", "window", "App", children=[
            _make_node("e1", "toolbar", "Main", children=[
                _make_node("e2", "button", "Save", actions=["click"]),
            ]),
            _make_node("e3", "heading", "Title"),
        ])]
        pruned = prune_tree(tree, detail="minimal")
        assert len(pruned) == 1
        window = pruned[0]
        assert window["role"] == "window"
        children = window.get("children", [])
        assert len(children) == 1  # only toolbar kept (has interactive descendant)
        toolbar = children[0]
        assert toolbar["role"] == "toolbar"
        assert len(toolbar["children"]) == 1
        assert toolbar["children"][0]["role"] == "button"

    def test_detail_full_returns_deep_copy(self):
        """detail='full' should return a deep copy, not modify original."""
        tree = [_make_node("e0", "button", "OK")]
        pruned = prune_tree(tree, detail="full")
        pruned[0]["name"] = "Changed"
        assert tree[0]["name"] == "OK"
