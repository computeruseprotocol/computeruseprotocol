"""Tests for CUP format utilities: envelope builder, compact serializer, overview, and tree pruning."""

from __future__ import annotations

from cup.format import build_envelope, prune_tree, serialize_compact, serialize_overview

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
        tree = [
            _make_node(
                "e0",
                "generic",
                "",
                children=[
                    _make_node("e1", "button", "OK"),
                ],
            )
        ]
        pruned = prune_tree(tree)
        assert len(pruned) == 1
        assert pruned[0]["role"] == "button"

    def test_named_generic_kept(self):
        tree = [
            _make_node(
                "e0",
                "generic",
                "Panel",
                children=[
                    _make_node("e1", "button", "OK"),
                ],
            )
        ]
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
        tree = [
            _make_node(
                "e0",
                "button",
                "Submit",
                children=[
                    _make_node("e1", "text", "Submit"),
                ],
            )
        ]
        pruned = prune_tree(tree)
        assert len(pruned) == 1
        assert "children" not in pruned[0]

    def test_offscreen_unnamed_no_actions_skipped(self):
        tree = [_make_node("e0", "group", "", states=["offscreen"])]
        pruned = prune_tree(tree)
        assert len(pruned) == 0

    def test_offscreen_named_no_actions_skipped(self):
        """Offscreen nodes without meaningful actions are dropped even if named."""
        tree = [_make_node("e0", "group", "Chat message", states=["offscreen"])]
        pruned = prune_tree(tree)
        assert len(pruned) == 0

    def test_offscreen_with_actions_kept(self):
        tree = [_make_node("e0", "button", "", states=["offscreen"], actions=["click"])]
        pruned = prune_tree(tree)
        assert len(pruned) == 1

    def test_unnamed_group_without_actions_hoisted(self):
        tree = [
            _make_node(
                "e0",
                "group",
                "",
                children=[
                    _make_node("e1", "button", "OK"),
                ],
            )
        ]
        pruned = prune_tree(tree)
        assert len(pruned) == 1
        assert pruned[0]["role"] == "button"

    def test_unnamed_group_with_actions_kept(self):
        tree = [
            _make_node(
                "e0",
                "group",
                "",
                actions=["click"],
                children=[
                    _make_node("e1", "button", "OK"),
                ],
            )
        ]
        pruned = prune_tree(tree)
        assert len(pruned) == 1
        assert pruned[0]["role"] == "group"

    def test_deep_nesting_pruned(self):
        """Multiple levels of unnamed generics should all be hoisted."""
        tree = [
            _make_node(
                "e0",
                "generic",
                "",
                children=[
                    _make_node(
                        "e1",
                        "generic",
                        "",
                        children=[
                            _make_node(
                                "e2",
                                "generic",
                                "",
                                children=[
                                    _make_node("e3", "button", "Deep"),
                                ],
                            ),
                        ],
                    ),
                ],
            )
        ]
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
        env = _make_envelope(
            [
                _make_node(
                    "e0",
                    "button",
                    "Submit",
                    bounds={"x": 100, "y": 200, "w": 80, "h": 30},
                    states=["focused"],
                    actions=["click", "focus"],
                )
            ]
        )
        text = serialize_compact(env)
        # focus action should be dropped
        assert '[e0] button "Submit" @100,200 80x30 {focused} [click]' in text

    def test_indentation(self):
        env = _make_envelope(
            [
                _make_node(
                    "e0",
                    "window",
                    "App",
                    children=[
                        _make_node("e1", "button", "OK"),
                    ],
                )
            ]
        )
        text = serialize_compact(env)
        lines = [l for l in text.strip().split("\n") if not l.startswith("#") and l.strip()]
        assert lines[0].startswith("[e0]")
        assert lines[1].startswith("  [e1]")

    def test_pruning_applied(self):
        """Compact serializer should prune unnamed generics."""
        env = _make_envelope(
            [
                _make_node(
                    "e0",
                    "generic",
                    "",
                    children=[
                        _make_node("e1", "button", "OK"),
                    ],
                )
            ]
        )
        text = serialize_compact(env)
        assert "generic" not in text
        assert "[e1] button" in text

    def test_node_count_header(self):
        env = _make_envelope(
            [
                _make_node(
                    "e0",
                    "generic",
                    "",
                    children=[
                        _make_node("e1", "button", "A"),
                        _make_node("e2", "button", "B"),
                    ],
                )
            ]
        )
        text = serialize_compact(env)
        # 2 nodes after pruning (generic hoisted), 3 before
        assert "2 nodes (3 before pruning)" in text

    def test_value_for_textbox(self):
        env = _make_envelope(
            [
                _make_node(
                    "e0",
                    "textbox",
                    "Search",
                    value="hello world",
                )
            ]
        )
        text = serialize_compact(env)
        assert 'val="hello world"' in text

    def test_name_truncation(self):
        long_name = "A" * 100
        env = _make_envelope([_make_node("e0", "button", long_name)])
        text = serialize_compact(env)
        assert "A" * 80 + "..." in text

    def test_value_truncation_at_120(self):
        long_value = "x" * 150
        env = _make_envelope(
            [
                _make_node(
                    "e0",
                    "textbox",
                    "Input",
                    value=long_value,
                )
            ]
        )
        text = serialize_compact(env)
        assert 'val="' + "x" * 120 + '..."' in text
        assert "x" * 150 not in text

    def test_value_not_truncated_under_120(self):
        short_value = "y" * 100
        env = _make_envelope(
            [
                _make_node(
                    "e0",
                    "textbox",
                    "Input",
                    value=short_value,
                )
            ]
        )
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
            windows,
            platform="windows",
            screen_w=1920,
            screen_h=1080,
        )
        assert "# CUP 0.1.0 | windows | 1920x1080" in text
        assert "# overview | 1 windows" in text

    def test_foreground_marker(self):
        windows = [
            {"title": "VS Code", "pid": 1234, "foreground": True, "bounds": None},
            {"title": "Firefox", "pid": 5678, "foreground": False, "bounds": None},
        ]
        text = serialize_overview(
            windows,
            platform="windows",
            screen_w=1920,
            screen_h=1080,
        )
        assert "* [fg] VS Code" in text
        assert "  Firefox" in text

    def test_pid_included(self):
        windows = [
            {"title": "App", "pid": 42, "foreground": False, "bounds": None},
        ]
        text = serialize_overview(
            windows,
            platform="linux",
            screen_w=2560,
            screen_h=1440,
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
            windows,
            platform="windows",
            screen_w=1920,
            screen_h=1080,
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
            windows,
            platform="web",
            screen_w=1280,
            screen_h=720,
        )
        assert "url:https://github.com" in text

    def test_empty_window_list(self):
        text = serialize_overview(
            [],
            platform="windows",
            screen_w=1920,
            screen_h=1080,
        )
        assert "# overview | 0 windows" in text

    def test_no_element_ids(self):
        """Overview should NOT contain element IDs (no tree walking)."""
        windows = [
            {"title": "App", "pid": 1, "foreground": True, "bounds": None},
        ]
        text = serialize_overview(
            windows,
            platform="windows",
            screen_w=1920,
            screen_h=1080,
        )
        assert "[e" not in text


# ---------------------------------------------------------------------------
# Detail pruning levels
# ---------------------------------------------------------------------------


class TestDetailPruning:
    def test_detail_full_no_pruning(self):
        """detail='full' should preserve all nodes including unnamed generics."""
        tree = [
            _make_node(
                "e0",
                "generic",
                "",
                children=[
                    _make_node("e1", "button", "OK"),
                ],
            )
        ]
        pruned = prune_tree(tree, detail="full")
        assert len(pruned) == 1
        assert pruned[0]["role"] == "generic"
        assert len(pruned[0]["children"]) == 1

    def test_detail_standard_prunes_generics(self):
        """detail='standard' (default) should hoist unnamed generics."""
        tree = [
            _make_node(
                "e0",
                "generic",
                "",
                children=[
                    _make_node("e1", "button", "OK"),
                ],
            )
        ]
        pruned = prune_tree(tree, detail="standard")
        assert len(pruned) == 1
        assert pruned[0]["role"] == "button"

    def test_detail_minimal_keeps_only_interactive(self):
        """detail='minimal' should keep only nodes with meaningful actions."""
        tree = [
            _make_node(
                "e0",
                "window",
                "App",
                children=[
                    _make_node("e1", "heading", "Title"),
                    _make_node("e2", "text", "Some description"),
                    _make_node("e3", "button", "Submit", actions=["click"]),
                    _make_node("e4", "textbox", "Email", actions=["type", "setvalue"]),
                    _make_node("e5", "group", "Footer", actions=["focus"]),
                ],
            )
        ]
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
        tree = [
            _make_node(
                "e0",
                "window",
                "App",
                children=[
                    _make_node(
                        "e1",
                        "toolbar",
                        "Main",
                        children=[
                            _make_node("e2", "button", "Save", actions=["click"]),
                        ],
                    ),
                    _make_node("e3", "heading", "Title"),
                ],
            )
        ]
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


# ---------------------------------------------------------------------------
# Pruning edge cases
# ---------------------------------------------------------------------------


class TestPruneEdgeCases:
    def test_focus_only_action_dropped_from_compact(self):
        """An element with only ['focus'] should show no action brackets."""
        env = _make_envelope(
            [
                _make_node(
                    "e0",
                    "button",
                    "OK",
                    actions=["focus"],
                )
            ]
        )
        text = serialize_compact(env)
        # The node line should not have [focus] since focus is dropped
        node_line = [l for l in text.split("\n") if "[e0]" in l][0]
        assert "[focus]" not in node_line
        # No action brackets at all
        assert "[click" not in node_line

    def test_offscreen_interactive_named_kept(self):
        """Offscreen elements with both name and actions should be preserved."""
        tree = [_make_node("e0", "button", "Send", states=["offscreen"], actions=["click"])]
        pruned = prune_tree(tree)
        assert len(pruned) == 1
        assert pruned[0]["name"] == "Send"

    def test_nested_hoisting_preserves_all_grandchildren(self):
        """Multiple children of a hoisted node should all appear."""
        tree = [
            _make_node(
                "e0",
                "generic",
                "",
                children=[
                    _make_node("e1", "button", "A"),
                    _make_node("e2", "button", "B"),
                    _make_node("e3", "button", "C"),
                ],
            )
        ]
        pruned = prune_tree(tree)
        assert len(pruned) == 3
        names = [n["name"] for n in pruned]
        assert names == ["A", "B", "C"]

    def test_minimal_pruning_empty_tree(self):
        """Minimal pruning on empty tree returns empty."""
        pruned = prune_tree([], detail="minimal")
        assert pruned == []

    def test_compact_attributes_heading_level(self):
        """Heading level should appear as L{n} in compact output."""
        env = _make_envelope(
            [
                _make_node(
                    "e0",
                    "heading",
                    "Title",
                    attributes={"level": 2},
                )
            ]
        )
        text = serialize_compact(env)
        assert "(L2)" in text

    def test_compact_attributes_placeholder(self):
        """Placeholder should appear as ph=... in compact output."""
        env = _make_envelope(
            [
                _make_node(
                    "e0",
                    "textbox",
                    "Email",
                    attributes={"placeholder": "you@example.com"},
                )
            ]
        )
        text = serialize_compact(env)
        assert 'ph="you@example.com"' in text

    def test_compact_attributes_range(self):
        """Range attributes should appear as range=min..max."""
        env = _make_envelope(
            [
                _make_node(
                    "e0",
                    "slider",
                    "Volume",
                    value="50",
                    attributes={"valueMin": 0, "valueMax": 100},
                )
            ]
        )
        text = serialize_compact(env)
        assert "range=0..100" in text

    def test_compact_attributes_orientation(self):
        """Orientation should appear as single char in compact output."""
        env = _make_envelope(
            [
                _make_node(
                    "e0",
                    "slider",
                    "Volume",
                    attributes={"orientation": "vertical"},
                )
            ]
        )
        text = serialize_compact(env)
        assert "(v)" in text

    def test_compact_combined_attributes(self):
        """Multiple attributes should appear together in parentheses."""
        env = _make_envelope(
            [
                _make_node(
                    "e0",
                    "heading",
                    "Intro",
                    attributes={"level": 3, "placeholder": "Type here"},
                )
            ]
        )
        text = serialize_compact(env)
        assert "(L3" in text
        assert 'ph="Type here"' in text


# ---------------------------------------------------------------------------
# Output truncation
# ---------------------------------------------------------------------------


class TestOutputTruncation:
    def test_output_truncated_at_max_chars(self):
        """Output exceeding max_chars should be truncated with a message."""
        # Generate a large tree
        nodes = [_make_node(f"e{i}", "button", f"Button {i}" * 10) for i in range(200)]
        env = _make_envelope(nodes)
        text = serialize_compact(env, max_chars=2000)
        assert len(text) <= 2500  # some overhead for truncation message
        assert "OUTPUT TRUNCATED" in text
        assert "find_element" in text

    def test_output_not_truncated_under_limit(self):
        """Small output should not be truncated."""
        env = _make_envelope([_make_node("e0", "button", "OK")])
        text = serialize_compact(env, max_chars=80_000)
        assert "OUTPUT TRUNCATED" not in text

    def test_truncation_cuts_at_newline(self):
        """Truncation should cut at the last newline to avoid partial lines."""
        nodes = [_make_node(f"e{i}", "button", f"Button {i}" * 10) for i in range(200)]
        env = _make_envelope(nodes)
        text = serialize_compact(env, max_chars=2000)
        # Find the truncation message
        idx = text.find("# OUTPUT TRUNCATED")
        if idx > 0:
            # The line before the truncation message should end cleanly
            before = text[:idx].rstrip("\n")
            assert not before.endswith("\\")  # no mid-escape truncation


# ---------------------------------------------------------------------------
# Tier 1: Chrome / decorative node stripping
# ---------------------------------------------------------------------------


class TestChromeStripping:
    def test_scrollbar_subtree_skipped(self):
        """Scrollbar and all its children should be dropped."""
        tree = [
            _make_node(
                "e0",
                "window",
                "App",
                children=[
                    _make_node(
                        "e1",
                        "scrollbar",
                        "Scroll",
                        actions=["increment", "decrement"],
                        children=[
                            _make_node("e2", "button", "Line up", actions=["click"]),
                            _make_node("e3", "generic", "Thumb"),
                            _make_node("e4", "button", "Line down", actions=["click"]),
                        ],
                    ),
                    _make_node("e5", "button", "OK", actions=["click"]),
                ],
            )
        ]
        pruned = prune_tree(tree)
        assert len(pruned) == 1
        window = pruned[0]
        child_roles = [c["role"] for c in window.get("children", [])]
        assert "scrollbar" not in child_roles
        assert "button" in child_roles
        # Only one child should remain (the OK button)
        assert len(window["children"]) == 1
        assert window["children"][0]["name"] == "OK"

    def test_separator_skipped(self):
        """Separator elements should be dropped."""
        tree = [_make_node("e0", "separator", "")]
        pruned = prune_tree(tree)
        assert len(pruned) == 0

    def test_titlebar_subtree_skipped(self):
        """Titlebar and its min/max/close children should be dropped."""
        tree = [
            _make_node(
                "e0",
                "window",
                "App",
                children=[
                    _make_node(
                        "e1",
                        "titlebar",
                        "App",
                        children=[
                            _make_node("e2", "button", "Minimize", actions=["click"]),
                            _make_node("e3", "button", "Maximize", actions=["click"]),
                            _make_node("e4", "button", "Close", actions=["click"]),
                        ],
                    ),
                    _make_node("e5", "textbox", "Input", actions=["type"]),
                ],
            )
        ]
        pruned = prune_tree(tree)
        window = pruned[0]
        child_ids = [c["id"] for c in window.get("children", [])]
        assert "e1" not in child_ids  # titlebar gone
        assert "e5" in child_ids  # textbox kept

    def test_tooltip_skipped(self):
        """Tooltip elements should be dropped."""
        tree = [_make_node("e0", "tooltip", "Helpful hint")]
        pruned = prune_tree(tree)
        assert len(pruned) == 0

    def test_status_bar_subtree_skipped(self):
        """Status bar and all its children should be dropped."""
        tree = [
            _make_node(
                "e0",
                "window",
                "App",
                children=[
                    _make_node(
                        "e1",
                        "status",
                        "Status Bar",
                        children=[
                            _make_node("e2", "text", "Line 42"),
                            _make_node("e3", "button", "UTF-8", actions=["click"]),
                        ],
                    ),
                    _make_node("e4", "button", "Save", actions=["click"]),
                ],
            )
        ]
        pruned = prune_tree(tree)
        window = pruned[0]
        child_ids = [c["id"] for c in window.get("children", [])]
        assert "e1" not in child_ids
        assert "e4" in child_ids

    def test_zero_size_element_skipped(self):
        """Elements with zero width or height should be dropped."""
        tree = [
            _make_node("e0", "button", "Ghost", bounds={"x": 0, "y": 0, "w": 0, "h": 30}),
            _make_node("e1", "button", "Flat", bounds={"x": 0, "y": 0, "w": 100, "h": 0}),
            _make_node("e2", "button", "Real", bounds={"x": 0, "y": 0, "w": 100, "h": 30}),
        ]
        pruned = prune_tree(tree)
        assert len(pruned) == 1
        assert pruned[0]["name"] == "Real"

    def test_zero_size_with_actions_skipped(self):
        """Even interactive zero-size elements should be dropped — they're invisible."""
        tree = [
            _make_node(
                "e0",
                "button",
                "Invisible",
                actions=["click"],
                bounds={"x": 0, "y": 0, "w": 0, "h": 0},
            )
        ]
        pruned = prune_tree(tree)
        assert len(pruned) == 0

    def test_normal_elements_not_affected(self):
        """Ensure chrome stripping doesn't affect normal elements."""
        tree = [
            _make_node("e0", "button", "OK", actions=["click"]),
            _make_node("e1", "textbox", "Name", actions=["type"]),
            _make_node("e2", "heading", "Title", attributes={"level": 1}),
            _make_node("e3", "link", "Help", actions=["click"]),
        ]
        pruned = prune_tree(tree)
        assert len(pruned) == 4


# ---------------------------------------------------------------------------
# Tier 2: Viewport-based clipping
# ---------------------------------------------------------------------------


class TestViewportClipping:
    def test_offscreen_child_of_scrollable_clipped(self):
        """Children entirely below a scrollable container should be clipped."""
        tree = [
            _make_node(
                "e0",
                "list",
                "Items",
                bounds={"x": 0, "y": 0, "w": 400, "h": 200},
                actions=["scroll"],
                children=[
                    # Visible (within 0-200 y range)
                    _make_node(
                        "e1", "listitem", "Item 1", bounds={"x": 0, "y": 0, "w": 400, "h": 50}
                    ),
                    _make_node(
                        "e2", "listitem", "Item 2", bounds={"x": 0, "y": 50, "w": 400, "h": 50}
                    ),
                    # Offscreen below (y >= 200)
                    _make_node(
                        "e3", "listitem", "Item 5", bounds={"x": 0, "y": 300, "w": 400, "h": 50}
                    ),
                    _make_node(
                        "e4", "listitem", "Item 6", bounds={"x": 0, "y": 350, "w": 400, "h": 50}
                    ),
                ],
            )
        ]
        pruned = prune_tree(tree)
        assert len(pruned) == 1
        container = pruned[0]
        children = container.get("children", [])
        child_names = [c["name"] for c in children]
        assert "Item 1" in child_names
        assert "Item 2" in child_names
        assert "Item 5" not in child_names
        assert "Item 6" not in child_names

    def test_onscreen_child_of_scrollable_kept(self):
        """Children within the scrollable container bounds should be kept."""
        tree = [
            _make_node(
                "e0",
                "list",
                "Items",
                bounds={"x": 0, "y": 0, "w": 400, "h": 200},
                actions=["scroll"],
                children=[
                    _make_node(
                        "e1", "listitem", "Item 1", bounds={"x": 0, "y": 0, "w": 400, "h": 50}
                    ),
                    _make_node(
                        "e2", "listitem", "Item 2", bounds={"x": 0, "y": 50, "w": 400, "h": 50}
                    ),
                ],
            )
        ]
        pruned = prune_tree(tree)
        container = pruned[0]
        assert len(container["children"]) == 2

    def test_child_without_bounds_kept(self):
        """Children without bounds info should be kept (safe default)."""
        tree = [
            _make_node(
                "e0",
                "list",
                "Items",
                bounds={"x": 0, "y": 0, "w": 400, "h": 200},
                actions=["scroll"],
                children=[
                    _make_node("e1", "listitem", "No bounds"),  # no bounds
                ],
            )
        ]
        pruned = prune_tree(tree)
        container = pruned[0]
        assert len(container["children"]) == 1
        assert container["children"][0]["name"] == "No bounds"

    def test_partially_visible_element_kept(self):
        """Elements partially overlapping the viewport should be kept."""
        tree = [
            _make_node(
                "e0",
                "list",
                "Items",
                bounds={"x": 0, "y": 0, "w": 400, "h": 200},
                actions=["scroll"],
                children=[
                    # Straddles the bottom edge (y=180, h=50 → extends to 230)
                    _make_node(
                        "e1", "listitem", "Partial", bounds={"x": 0, "y": 180, "w": 400, "h": 50}
                    ),
                ],
            )
        ]
        pruned = prune_tree(tree)
        container = pruned[0]
        assert len(container["children"]) == 1
        assert container["children"][0]["name"] == "Partial"

    def test_non_scrollable_does_not_clip(self):
        """Children of non-scrollable containers should never be clipped."""
        tree = [
            _make_node(
                "e0",
                "group",
                "Panel",
                actions=["click"],
                bounds={"x": 0, "y": 0, "w": 400, "h": 200},
                children=[
                    # This is outside the parent bounds but parent is NOT scrollable
                    _make_node(
                        "e1",
                        "button",
                        "Far Away",
                        bounds={"x": 0, "y": 500, "w": 100, "h": 30},
                        actions=["click"],
                    ),
                ],
            )
        ]
        pruned = prune_tree(tree)
        container = pruned[0]
        assert len(container["children"]) == 1
        assert container["children"][0]["name"] == "Far Away"

    def test_nested_scrollable_containers(self):
        """Inner scrollable should clip to its own viewport, not outer's."""
        tree = [
            _make_node(
                "e0",
                "list",
                "Outer",
                bounds={"x": 0, "y": 0, "w": 400, "h": 600},
                actions=["scroll"],
                children=[
                    _make_node(
                        "e1",
                        "list",
                        "Inner",
                        bounds={"x": 0, "y": 0, "w": 400, "h": 100},
                        actions=["scroll"],
                        children=[
                            # Inside inner viewport
                            _make_node(
                                "e2",
                                "listitem",
                                "Inner Visible",
                                bounds={"x": 0, "y": 10, "w": 400, "h": 30},
                            ),
                            # Outside inner but inside outer
                            _make_node(
                                "e3",
                                "listitem",
                                "Inner Hidden",
                                bounds={"x": 0, "y": 200, "w": 400, "h": 30},
                            ),
                        ],
                    ),
                ],
            )
        ]
        pruned = prune_tree(tree)
        outer = pruned[0]
        inner = outer["children"][0]
        inner_children = inner.get("children", [])
        child_names = [c["name"] for c in inner_children]
        assert "Inner Visible" in child_names
        assert "Inner Hidden" not in child_names

    def test_oversized_inner_scrollable_clipped_to_parent(self):
        """A scrollable child reporting bounds larger than its parent's viewport
        should have its effective viewport intersected with the parent's.

        Real-world case: Spotify search dropdown (list 474x398) contains a
        grid that reports 458x1888 — children beyond the list's visible area
        must be clipped.
        """
        tree = [
            _make_node(
                "e0",
                "list",
                "Dropdown",
                bounds={"x": 0, "y": 100, "w": 400, "h": 300},
                actions=["scroll"],
                children=[
                    _make_node(
                        "e1",
                        "grid",
                        "Results",
                        bounds={"x": 0, "y": 100, "w": 400, "h": 2000},
                        actions=["scroll"],
                        children=[
                            # Inside the parent list viewport (y=100-400)
                            _make_node(
                                "e2",
                                "row",
                                "Visible Result",
                                bounds={"x": 0, "y": 150, "w": 400, "h": 50},
                                actions=["click"],
                            ),
                            # Inside grid bounds but OUTSIDE parent list (y=500 > 400)
                            _make_node(
                                "e3",
                                "row",
                                "Hidden Result",
                                bounds={"x": 0, "y": 500, "w": 400, "h": 50},
                                actions=["click"],
                            ),
                            # Way outside both
                            _make_node(
                                "e4",
                                "row",
                                "Far Result",
                                bounds={"x": 0, "y": 1500, "w": 400, "h": 50},
                                actions=["click"],
                            ),
                        ],
                    ),
                ],
            )
        ]
        pruned = prune_tree(tree)
        dropdown = pruned[0]
        grid = dropdown["children"][0]
        grid_children = grid.get("children", [])
        child_names = [c["name"] for c in grid_children]
        assert "Visible Result" in child_names
        assert "Hidden Result" not in child_names
        assert "Far Result" not in child_names


# ---------------------------------------------------------------------------
# Tier 3: Collapsed subtree hints
# ---------------------------------------------------------------------------


class TestClippedHints:
    def test_clipped_hint_shows_count(self):
        """Scrollable with clipped children should show a count hint."""
        tree = [
            _make_node(
                "e0",
                "list",
                "Items",
                bounds={"x": 0, "y": 0, "w": 400, "h": 100},
                actions=["scroll"],
                children=[
                    _make_node(
                        "e1", "listitem", "Visible", bounds={"x": 0, "y": 0, "w": 400, "h": 50}
                    ),
                    _make_node(
                        "e2", "listitem", "Hidden 1", bounds={"x": 0, "y": 200, "w": 400, "h": 50}
                    ),
                    _make_node(
                        "e3", "listitem", "Hidden 2", bounds={"x": 0, "y": 250, "w": 400, "h": 50}
                    ),
                ],
            )
        ]
        env = _make_envelope(tree)
        text = serialize_compact(env)
        assert "2 more items" in text

    def test_clipped_hint_direction_below(self):
        """Clipped items below the viewport should show 'scroll down'."""
        tree = [
            _make_node(
                "e0",
                "list",
                "Items",
                bounds={"x": 0, "y": 0, "w": 400, "h": 100},
                actions=["scroll"],
                children=[
                    _make_node(
                        "e1", "listitem", "Hidden", bounds={"x": 0, "y": 200, "w": 400, "h": 50}
                    ),
                ],
            )
        ]
        env = _make_envelope(tree)
        text = serialize_compact(env)
        assert "scroll down" in text

    def test_clipped_hint_direction_above(self):
        """Clipped items above the viewport should show 'scroll up'."""
        tree = [
            _make_node(
                "e0",
                "list",
                "Items",
                bounds={"x": 0, "y": 200, "w": 400, "h": 100},
                actions=["scroll"],
                children=[
                    _make_node(
                        "e1", "listitem", "Above", bounds={"x": 0, "y": 50, "w": 400, "h": 50}
                    ),
                ],
            )
        ]
        env = _make_envelope(tree)
        text = serialize_compact(env)
        assert "scroll up" in text

    def test_clipped_hint_direction_both(self):
        """Clipped items above and below should show 'scroll up/down'."""
        tree = [
            _make_node(
                "e0",
                "list",
                "Items",
                bounds={"x": 0, "y": 100, "w": 400, "h": 100},
                actions=["scroll"],
                children=[
                    _make_node(
                        "e1", "listitem", "Above", bounds={"x": 0, "y": 0, "w": 400, "h": 50}
                    ),
                    _make_node(
                        "e2", "listitem", "Visible", bounds={"x": 0, "y": 120, "w": 400, "h": 50}
                    ),
                    _make_node(
                        "e3", "listitem", "Below", bounds={"x": 0, "y": 300, "w": 400, "h": 50}
                    ),
                ],
            )
        ]
        env = _make_envelope(tree)
        text = serialize_compact(env)
        assert "scroll up/down" in text

    def test_no_hint_when_nothing_clipped(self):
        """No hint line when all children are visible."""
        tree = [
            _make_node(
                "e0",
                "list",
                "Items",
                bounds={"x": 0, "y": 0, "w": 400, "h": 200},
                actions=["scroll"],
                children=[
                    _make_node(
                        "e1", "listitem", "Visible", bounds={"x": 0, "y": 0, "w": 400, "h": 50}
                    ),
                ],
            )
        ]
        env = _make_envelope(tree)
        text = serialize_compact(env)
        assert "more items" not in text
        assert "scroll" not in text or "scroll" in text.split("[scroll]")[0] + "[scroll]"

    def test_hint_indentation(self):
        """Hint line should be indented at the child depth of the scrollable container."""
        tree = [
            _make_node(
                "e0",
                "window",
                "App",
                children=[
                    _make_node(
                        "e1",
                        "list",
                        "Items",
                        bounds={"x": 0, "y": 0, "w": 400, "h": 100},
                        actions=["scroll"],
                        children=[
                            _make_node(
                                "e2",
                                "listitem",
                                "Visible",
                                bounds={"x": 0, "y": 0, "w": 400, "h": 50},
                            ),
                            _make_node(
                                "e3",
                                "listitem",
                                "Hidden",
                                bounds={"x": 0, "y": 200, "w": 400, "h": 50},
                            ),
                        ],
                    ),
                ],
            )
        ]
        env = _make_envelope(tree)
        text = serialize_compact(env)
        # The list is at depth 1 (under window), so hint should be at depth 2
        hint_lines = [l for l in text.split("\n") if "more items" in l]
        assert len(hint_lines) == 1
        # Should have 4 spaces of indentation (depth 2 * 2 spaces)
        assert hint_lines[0].startswith("    #")


# ---------------------------------------------------------------------------
# Screen-level viewport clipping
# ---------------------------------------------------------------------------


class TestScreenViewportClipping:
    def test_deeply_offscreen_clipped_by_screen_viewport(self):
        """Elements far below the screen should be clipped even without a scrollable ancestor."""
        tree = [
            _make_node(
                "e0",
                "window",
                "App",
                bounds={"x": 0, "y": 0, "w": 800, "h": 600},
                children=[
                    _make_node(
                        "e1",
                        "main",
                        "Content",
                        bounds={"x": 0, "y": 0, "w": 800, "h": 600},
                        actions=["click"],
                        children=[
                            # Visible
                            _make_node(
                                "e2",
                                "button",
                                "Visible Btn",
                                bounds={"x": 10, "y": 10, "w": 100, "h": 30},
                                actions=["click"],
                            ),
                            # Deeply offscreen — y=3000, screen is 1080 tall
                            _make_node(
                                "e3",
                                "button",
                                "Far Away",
                                bounds={"x": 10, "y": 3000, "w": 100, "h": 30},
                                actions=["click"],
                            ),
                            _make_node(
                                "e4",
                                "group",
                                "Also Far",
                                bounds={"x": 10, "y": 5000, "w": 400, "h": 500},
                                actions=["click"],
                                children=[
                                    _make_node(
                                        "e5",
                                        "button",
                                        "Nested Far",
                                        bounds={"x": 20, "y": 5010, "w": 80, "h": 30},
                                        actions=["click"],
                                    ),
                                ],
                            ),
                        ],
                    ),
                ],
            )
        ]
        env = _make_envelope(tree, screen_w=800, screen_h=1080)
        text = serialize_compact(env)
        assert "Visible Btn" in text
        assert "Far Away" not in text
        assert "Also Far" not in text
        assert "Nested Far" not in text

    def test_screen_viewport_keeps_onscreen_elements(self):
        """Elements within screen bounds should be kept regardless of parent scrollability."""
        tree = [
            _make_node(
                "e0",
                "window",
                "App",
                bounds={"x": 0, "y": 0, "w": 800, "h": 600},
                children=[
                    _make_node(
                        "e1",
                        "main",
                        "Content",
                        bounds={"x": 0, "y": 0, "w": 800, "h": 200},
                        actions=["click"],
                        children=[
                            # Outside parent (200px tall) but inside screen (1080px)
                            _make_node(
                                "e2",
                                "button",
                                "Below Parent",
                                bounds={"x": 10, "y": 500, "w": 100, "h": 30},
                                actions=["click"],
                            ),
                        ],
                    ),
                ],
            )
        ]
        env = _make_envelope(tree, screen_w=800, screen_h=1080)
        text = serialize_compact(env)
        assert "Below Parent" in text

    def test_no_screen_info_skips_screen_clipping(self):
        """When no screen info is available, no screen-level clipping should occur."""
        tree = [
            _make_node(
                "e0",
                "window",
                "App",
                children=[
                    _make_node(
                        "e1",
                        "button",
                        "Far Button",
                        bounds={"x": 0, "y": 5000, "w": 100, "h": 30},
                        actions=["click"],
                    ),
                ],
            )
        ]
        # Call prune_tree directly without screen info — should keep everything
        pruned = prune_tree(tree)
        assert len(pruned) == 1
        child_names = [c["name"] for c in pruned[0].get("children", [])]
        assert "Far Button" in child_names

    def test_screen_clipping_shows_hint(self):
        """Screen-clipped elements should produce a clipping hint."""
        tree = [
            _make_node(
                "e0",
                "window",
                "App",
                bounds={"x": 0, "y": 0, "w": 800, "h": 600},
                children=[
                    # Visible
                    _make_node(
                        "e1",
                        "button",
                        "Visible",
                        bounds={"x": 10, "y": 10, "w": 100, "h": 30},
                        actions=["click"],
                    ),
                    # Below screen
                    _make_node(
                        "e2",
                        "button",
                        "Hidden",
                        bounds={"x": 10, "y": 2000, "w": 100, "h": 30},
                        actions=["click"],
                    ),
                ],
            )
        ]
        env = _make_envelope(tree, screen_w=800, screen_h=1080)
        text = serialize_compact(env)
        assert "Visible" in text
        assert "Hidden" not in text
        assert "more items" in text
