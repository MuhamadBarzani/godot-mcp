"""Unit tests for argument coercion (stringified-JSON repair, issue: opencode arg layer).

Some MCP clients serialize nested JSON objects as *strings* (pydantic then rejects
them with ``dict_type`` errors, making every properties-taking tool unusable).
``coerce_arguments`` repairs these at the tools/call boundary using the tool's own
input schema, touching only arguments the schema types as object/array/number/bool
(or leaves untyped) — genuine strings are never modified.
"""

from __future__ import annotations

from typing import Any

import pytest

from mcp_server.coercion_middleware import coerce_arguments
from mcp_server.qa import evaluate_assertion


def test_object_param_from_json_string() -> None:
    schema = {
        "type": "object",
        "properties": {"properties": {"type": "object", "additionalProperties": True}},
    }
    out = coerce_arguments(schema, {"properties": '{"albedo_color": "#2b3140"}'})
    assert out["properties"] == {"albedo_color": "#2b3140"}


def test_object_param_inner_types_recursed() -> None:
    schema = {
        "properties": {
            "properties": {
                "type": "object",
                "properties": {
                    "volume_db": {"type": "number"},
                    "name": {"type": "string"},
                },
            }
        }
    }
    out = coerce_arguments(schema, {"properties": '{"volume_db": "-6", "name": "123"}'})
    assert out["properties"] == {"volume_db": -6.0, "name": "123"}


def test_array_of_objects_param_from_string() -> None:
    schema = {
        "properties": {
            "events": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"type": {"type": "string"}, "pressed": {"type": "boolean"}},
                },
            }
        }
    }
    out = coerce_arguments(schema, {"events": '[{"type": "key", "pressed": "True"}]'})
    assert out["events"] == [{"type": "key", "pressed": True}]


def test_boolean_param_from_string() -> None:
    schema = {"properties": {"dry_run": {"type": "boolean"}}}
    assert coerce_arguments(schema, {"dry_run": "True"})["dry_run"] is True
    assert coerce_arguments(schema, {"dry_run": "false"})["dry_run"] is False


def test_integer_param_from_string() -> None:
    schema = {"properties": {"timeout_ms": {"type": "integer"}}}
    assert coerce_arguments(schema, {"timeout_ms": "3000"})["timeout_ms"] == 3000


def test_typed_string_params_never_touched() -> None:
    schema = {
        "properties": {
            "script_path": {"type": "string"},
            "content": {"type": "string"},
        }
    }
    args = {
        "script_path": "res://x.gd",
        "content": '{"json": "file body"}',
    }
    out = coerce_arguments(schema, args)
    assert out == args


def test_untyped_any_param_repairs_json_shapes() -> None:
    # FastMCP renders ``Any`` params (``value``, ``expected``) with no type.
    schema: dict[str, Any] = {"properties": {"value": {}, "expected": {}}}
    out = coerce_arguments(
        schema,
        {
            "value": '{"x": 10, "y": 20}',
            "expected": "True",
            "other": "res://keep.me",
        },
    )
    assert out["value"] == {"x": 10, "y": 20}
    assert out["expected"] is True
    assert out["other"] == "res://keep.me"


def test_untyped_numeric_string_repairs() -> None:
    schema: dict[str, Any] = {"properties": {"expected": {}}}
    assert coerce_arguments(schema, {"expected": "15"})["expected"] == 15


def test_invalid_json_left_untouched() -> None:
    schema: dict[str, Any] = {"properties": {"properties": {"type": "object"}}}
    args = {"properties": "{not valid json"}
    assert coerce_arguments(schema, args) == args


def test_nested_ref_resolution() -> None:
    schema = {
        "type": "object",
        "$defs": {"Thing": {"type": "object", "properties": {"ok": {"type": "boolean"}}}},
        "properties": {"thing": {"$ref": "#/$defs/Thing"}},
    }
    out = coerce_arguments(schema, {"thing": '{"ok": "True"}'})
    assert out["thing"] == {"ok": True}


def test_noop_when_already_typed() -> None:
    schema = {"properties": {"properties": {"type": "object"}}}
    args = {"properties": {"volume_db": -6.0}}
    assert coerce_arguments(schema, args) == args


def test_schemaless_call_passes_through() -> None:
    args = {"a": '{"b": 1}'}
    assert coerce_arguments({}, args) == {"a": {"b": 1}}  # untyped top-level keys repaired
    assert coerce_arguments(None, args) == args  # no schema at all → untouched


# --- schema-combinator coverage (review follow-up) ---------------------------


def test_allof_flattened_before_recursing() -> None:
    schema = {
        "properties": {
            "cfg": {
                "allOf": [
                    {"type": "object", "properties": {"speed": {"type": "number"}}},
                    {"properties": {"label": {"type": "string"}}},
                ]
            }
        }
    }
    out = coerce_arguments(schema, {"cfg": '{"speed": "3.5", "label": "7"}'})
    assert out["cfg"] == {"speed": 3.5, "label": "7"}


def test_anyof_non_string_branches_repair() -> None:
    schema = {"properties": {"p": {"anyOf": [{"type": "array"}, {"type": "object"}]}}}
    out = coerce_arguments(schema, {"p": '[{"q": "True"}]'})
    assert out["p"] == [{"q": True}]


def test_oneof_branch_selected_for_parsed_shape() -> None:
    schema = {
        "properties": {
            "p": {
                "oneOf": [
                    {"type": "object", "properties": {"x": {"type": "boolean"}}},
                    {"type": "integer"},
                ]
            }
        }
    }
    out = coerce_arguments(schema, {"p": '{"x": "False"}'})
    assert out["p"] == {"x": False}


def test_string_branch_is_conservative_noop() -> None:
    # anyOf([object, string]) declares a literal string as valid; never touch it.
    schema = {"properties": {"p": {"anyOf": [{"type": "object"}, {"type": "string"}]}}}
    out = coerce_arguments(schema, {"p": '{"a": "1"}'})
    assert out["p"] == '{"a": "1"}'


# --- evaluate_assertion scalar-string normalization --------------------------


@pytest.mark.parametrize(
    ("actual", "expected", "op", "want"),
    [
        (False, "False", "==", True),
        (False, "false", "==", True),
        (True, "True", "==", True),
        (True, "False", "==", False),
        (15, "0", "==", False),
        (15, "15", "==", True),
        (3.5, "3.5", "approx", True),
        ("hello", "hello", "==", True),
        ("5", 5, "==", False),  # actual is the string; do not bend non-string actual rules
        ("score", "core", "contains", True),
    ],
)
def test_evaluate_assertion_string_normalization(
    actual: object, expected: object, op: str, want: bool
) -> None:
    assert evaluate_assertion(actual, expected, op) is want
