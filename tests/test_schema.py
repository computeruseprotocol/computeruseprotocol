"""Tests for CUP JSON schema validation using jsonschema."""

from __future__ import annotations

import json
import pathlib

import pytest
from jsonschema import ValidationError, validate

from cup.format import build_envelope

SCHEMA_DIR = pathlib.Path(__file__).resolve().parent.parent / "schema"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def schema():
    with open(SCHEMA_DIR / "cup.schema.json", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def example():
    with open(SCHEMA_DIR / "example.json", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def mappings():
    with open(SCHEMA_DIR / "mappings.json", encoding="utf-8") as f:
        return json.load(f)


def _make_node(id: str, role: str, name: str = "", **kwargs) -> dict:
    node = {"id": id, "role": role, "name": name}
    node.update(kwargs)
    return node


# ---------------------------------------------------------------------------
# Schema structure
# ---------------------------------------------------------------------------


class TestSchemaStructure:
    def test_schema_valid_json(self, schema):
        assert "$schema" in schema
        assert schema["type"] == "object"

    def test_required_fields(self, schema):
        assert set(schema["required"]) == {"version", "platform", "screen", "tree"}

    def test_platform_enum(self, schema):
        platforms = schema["$defs"]["platformId"]["enum"]
        assert set(platforms) == {"windows", "macos", "linux", "web", "android", "ios"}

    def test_role_enum_nonempty(self, schema):
        roles = schema["$defs"]["role"]["enum"]
        assert len(roles) >= 50
        for role in ["button", "textbox", "link", "checkbox", "window", "generic"]:
            assert role in roles

    def test_state_enum(self, schema):
        states = schema["$defs"]["state"]["enum"]
        for state in ["focused", "disabled", "checked", "expanded", "selected"]:
            assert state in states

    def test_action_enum(self, schema):
        actions = schema["$defs"]["action"]["enum"]
        for action in ["click", "type", "scroll", "toggle", "expand", "collapse"]:
            assert action in actions

    def test_node_required_fields(self, schema):
        node = schema["$defs"]["node"]
        assert set(node["required"]) == {"id", "role", "name"}

    def test_all_six_platform_extensions(self, schema):
        platform_props = schema["$defs"]["node"]["properties"]["platform"]["properties"]
        assert set(platform_props.keys()) == {"windows", "macos", "linux", "web", "android", "ios"}


# ---------------------------------------------------------------------------
# Schema validation — valid envelopes
# ---------------------------------------------------------------------------


class TestSchemaValidation:
    def test_minimal_envelope_valid(self, schema):
        envelope = {
            "version": "0.1.0",
            "platform": "windows",
            "screen": {"w": 1920, "h": 1080},
            "tree": [],
        }
        validate(instance=envelope, schema=schema)

    def test_full_envelope_valid(self, schema):
        envelope = {
            "version": "0.1.0",
            "platform": "macos",
            "timestamp": 1740067200000,
            "screen": {"w": 2560, "h": 1440, "scale": 2.0},
            "app": {"name": "Firefox", "pid": 1234, "bundleId": "org.mozilla.firefox"},
            "tree": [
                {
                    "id": "e0",
                    "role": "window",
                    "name": "Firefox",
                    "bounds": {"x": 0, "y": 0, "w": 2560, "h": 1440},
                    "states": ["focused"],
                    "actions": ["click", "focus"],
                    "children": [
                        {
                            "id": "e1",
                            "role": "textbox",
                            "name": "URL bar",
                            "value": "https://example.com",
                            "bounds": {"x": 100, "y": 50, "w": 600, "h": 30},
                            "states": ["focused", "editable"],
                            "actions": ["click", "type", "setvalue"],
                            "attributes": {"placeholder": "Search or enter address"},
                        },
                    ],
                },
            ],
        }
        validate(instance=envelope, schema=schema)

    def test_all_platforms_valid(self, schema):
        for platform in ["windows", "macos", "linux", "web", "android", "ios"]:
            envelope = {
                "version": "0.1.0",
                "platform": platform,
                "screen": {"w": 1920, "h": 1080},
                "tree": [],
            }
            validate(instance=envelope, schema=schema)

    def test_node_with_platform_metadata_valid(self, schema):
        envelope = {
            "version": "0.1.0",
            "platform": "windows",
            "screen": {"w": 1920, "h": 1080},
            "tree": [
                {
                    "id": "e0",
                    "role": "button",
                    "name": "OK",
                    "platform": {
                        "windows": {
                            "controlType": 50000,
                            "automationId": "btnOK",
                            "className": "Button",
                        }
                    },
                },
            ],
        }
        validate(instance=envelope, schema=schema)

    def test_node_with_all_attributes_valid(self, schema):
        envelope = {
            "version": "0.1.0",
            "platform": "web",
            "screen": {"w": 1920, "h": 1080},
            "tree": [
                {
                    "id": "e0",
                    "role": "slider",
                    "name": "Volume",
                    "value": "75",
                    "attributes": {
                        "valueMin": 0,
                        "valueMax": 100,
                        "valueNow": 75,
                        "orientation": "horizontal",
                    },
                },
            ],
        }
        validate(instance=envelope, schema=schema)

    def test_build_envelope_output_valid(self, schema):
        """Envelope produced by build_envelope() should pass schema validation."""
        tree = [_make_node("e0", "button", "Submit", bounds={"x": 0, "y": 0, "w": 80, "h": 30})]
        envelope = build_envelope(
            tree,
            platform="windows",
            screen_w=1920,
            screen_h=1080,
            app_name="Test App",
            app_pid=999,
        )
        validate(instance=envelope, schema=schema)


# ---------------------------------------------------------------------------
# Schema validation — invalid envelopes
# ---------------------------------------------------------------------------


class TestSchemaRejection:
    def test_missing_version(self, schema):
        envelope = {
            "platform": "windows",
            "screen": {"w": 1920, "h": 1080},
            "tree": [],
        }
        with pytest.raises(ValidationError):
            validate(instance=envelope, schema=schema)

    def test_missing_platform(self, schema):
        envelope = {
            "version": "0.1.0",
            "screen": {"w": 1920, "h": 1080},
            "tree": [],
        }
        with pytest.raises(ValidationError):
            validate(instance=envelope, schema=schema)

    def test_missing_tree(self, schema):
        envelope = {
            "version": "0.1.0",
            "platform": "windows",
            "screen": {"w": 1920, "h": 1080},
        }
        with pytest.raises(ValidationError):
            validate(instance=envelope, schema=schema)

    def test_invalid_platform(self, schema):
        envelope = {
            "version": "0.1.0",
            "platform": "playstation",
            "screen": {"w": 1920, "h": 1080},
            "tree": [],
        }
        with pytest.raises(ValidationError):
            validate(instance=envelope, schema=schema)

    def test_invalid_role(self, schema):
        envelope = {
            "version": "0.1.0",
            "platform": "windows",
            "screen": {"w": 1920, "h": 1080},
            "tree": [{"id": "e0", "role": "not_a_role", "name": "bad"}],
        }
        with pytest.raises(ValidationError):
            validate(instance=envelope, schema=schema)

    def test_invalid_state(self, schema):
        envelope = {
            "version": "0.1.0",
            "platform": "windows",
            "screen": {"w": 1920, "h": 1080},
            "tree": [{"id": "e0", "role": "button", "name": "X", "states": ["flying"]}],
        }
        with pytest.raises(ValidationError):
            validate(instance=envelope, schema=schema)

    def test_invalid_action(self, schema):
        envelope = {
            "version": "0.1.0",
            "platform": "windows",
            "screen": {"w": 1920, "h": 1080},
            "tree": [{"id": "e0", "role": "button", "name": "X", "actions": ["explode"]}],
        }
        with pytest.raises(ValidationError):
            validate(instance=envelope, schema=schema)

    def test_invalid_node_id_format(self, schema):
        envelope = {
            "version": "0.1.0",
            "platform": "windows",
            "screen": {"w": 1920, "h": 1080},
            "tree": [{"id": "node_0", "role": "button", "name": "X"}],
        }
        with pytest.raises(ValidationError):
            validate(instance=envelope, schema=schema)

    def test_extra_top_level_property(self, schema):
        envelope = {
            "version": "0.1.0",
            "platform": "windows",
            "screen": {"w": 1920, "h": 1080},
            "tree": [],
            "garbage": True,
        }
        with pytest.raises(ValidationError):
            validate(instance=envelope, schema=schema)

    def test_negative_bounds_width(self, schema):
        envelope = {
            "version": "0.1.0",
            "platform": "windows",
            "screen": {"w": 1920, "h": 1080},
            "tree": [
                {
                    "id": "e0",
                    "role": "button",
                    "name": "X",
                    "bounds": {"x": 0, "y": 0, "w": -10, "h": 30},
                }
            ],
        }
        with pytest.raises(ValidationError):
            validate(instance=envelope, schema=schema)


# ---------------------------------------------------------------------------
# Example envelope — full schema validation
# ---------------------------------------------------------------------------


class TestExample:
    def test_example_validates_against_schema(self, example, schema):
        """The shipped example.json must be valid according to cup.schema.json."""
        validate(instance=example, schema=schema)

    def test_example_tree_nonempty(self, example):
        assert len(example["tree"]) > 0

    def test_example_nodes_have_sequential_ids(self, example):
        def check_node(node):
            assert node["id"].startswith("e")
            int(node["id"][1:])  # raises ValueError if not numeric
            for child in node.get("children", []):
                check_node(child)

        for root in example["tree"]:
            check_node(root)


# ---------------------------------------------------------------------------
# Mappings consistency
# ---------------------------------------------------------------------------


class TestMappings:
    def test_all_schema_roles_mapped(self, schema, mappings):
        schema_roles = set(schema["$defs"]["role"]["enum"])
        mapped_roles = {k for k in mappings["roles"] if not k.startswith("$")}
        missing = schema_roles - mapped_roles
        assert not missing, f"Roles in schema but not in mappings: {missing}"

    def test_all_mapped_roles_in_schema(self, schema, mappings):
        schema_roles = set(schema["$defs"]["role"]["enum"])
        mapped_roles = {k for k in mappings["roles"] if not k.startswith("$")}
        extra = mapped_roles - schema_roles
        assert not extra, f"Roles in mappings but not in schema: {extra}"

    def test_all_schema_states_mapped(self, schema, mappings):
        schema_states = set(schema["$defs"]["state"]["enum"])
        mapped_states = {k for k in mappings["states"] if not k.startswith("$")}
        missing = schema_states - mapped_states
        assert not missing, f"States in schema but not in mappings: {missing}"

    def test_all_schema_actions_mapped(self, schema, mappings):
        schema_actions = set(schema["$defs"]["action"]["enum"])
        mapped_actions = {k for k in mappings["actions"] if not k.startswith("$")}
        missing = schema_actions - mapped_actions
        assert not missing, f"Actions in schema but not in mappings: {missing}"

    def test_all_mapped_actions_in_schema(self, schema, mappings):
        schema_actions = set(schema["$defs"]["action"]["enum"])
        mapped_actions = {k for k in mappings["actions"] if not k.startswith("$")}
        extra = mapped_actions - schema_actions
        assert not extra, f"Actions in mappings but not in schema: {extra}"

    def test_mappings_cover_six_platforms(self, mappings):
        expected = {"windows", "macos", "linux", "web", "android", "ios"}
        first_role = next(k for k in mappings["roles"] if not k.startswith("$"))
        assert set(mappings["roles"][first_role].keys()) == expected


# ---------------------------------------------------------------------------
# Schema validation — scope, tools, windows fields
# ---------------------------------------------------------------------------


class TestScopeToolsWindows:
    def test_envelope_with_scope_valid(self, schema):
        envelope = {
            "version": "0.1.0",
            "platform": "windows",
            "screen": {"w": 1920, "h": 1080},
            "tree": [],
            "scope": "foreground",
        }
        validate(instance=envelope, schema=schema)

    def test_all_scopes_valid(self, schema):
        for scope in ("overview", "foreground", "desktop", "full"):
            envelope = {
                "version": "0.1.0",
                "platform": "windows",
                "screen": {"w": 1920, "h": 1080},
                "tree": [],
                "scope": scope,
            }
            validate(instance=envelope, schema=schema)

    def test_invalid_scope_rejected(self, schema):
        envelope = {
            "version": "0.1.0",
            "platform": "windows",
            "screen": {"w": 1920, "h": 1080},
            "tree": [],
            "scope": "imaginary",
        }
        with pytest.raises(ValidationError):
            validate(instance=envelope, schema=schema)

    def test_envelope_with_tools_valid(self, schema):
        envelope = {
            "version": "0.1.0",
            "platform": "web",
            "screen": {"w": 1920, "h": 1080},
            "tree": [],
            "tools": [{"name": "search", "description": "Find stuff"}],
        }
        validate(instance=envelope, schema=schema)

    def test_envelope_with_empty_tools_valid(self, schema):
        envelope = {
            "version": "0.1.0",
            "platform": "web",
            "screen": {"w": 1280, "h": 720},
            "tree": [],
            "tools": [],
        }
        validate(instance=envelope, schema=schema)

    def test_tool_without_name_rejected(self, schema):
        envelope = {
            "version": "0.1.0",
            "platform": "web",
            "screen": {"w": 1920, "h": 1080},
            "tree": [],
            "tools": [{"description": "Missing name"}],
        }
        with pytest.raises(ValidationError):
            validate(instance=envelope, schema=schema)

    def test_envelope_with_windows_valid(self, schema):
        envelope = {
            "version": "0.1.0",
            "platform": "windows",
            "screen": {"w": 1920, "h": 1080},
            "tree": [],
            "scope": "overview",
            "windows": [
                {"title": "VS Code", "pid": 1234, "foreground": True},
                {"title": "Firefox", "pid": 5678, "foreground": False},
            ],
        }
        validate(instance=envelope, schema=schema)

    def test_build_envelope_with_scope_valid(self, schema):
        envelope = build_envelope(
            [],
            platform="windows",
            screen_w=1920,
            screen_h=1080,
            scope="foreground",
        )
        validate(instance=envelope, schema=schema)

    def test_build_envelope_with_tools_valid(self, schema):
        envelope = build_envelope(
            [],
            platform="web",
            screen_w=1280,
            screen_h=720,
            tools=[{"name": "navigate"}],
        )
        validate(instance=envelope, schema=schema)
