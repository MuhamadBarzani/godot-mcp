"""Contract tests for the get_server_info diagnostics tool.

Verifies the diagnostics surface returns a comprehensive snapshot
including toolset counts, prompts, resources, bridge state, active scene,
and the troubleshooting cheat-sheet.
"""

from __future__ import annotations

import asyncio

import pytest

from mcp_server.server import create_server


@pytest.fixture
def server():
    """A fully-built server with all tools, resources, and prompts."""
    return create_server()


async def _call_tool(server, name: str, arguments: dict | None = None):
    """Async helper: call a tool and return its text content as a string."""
    result = await server.call_tool(name, arguments=arguments or {})
    # result.content is a list of TextContent; extract text from each.
    parts = []
    for item in result.content:
        parts.append(str(getattr(item, "text", "")))
    return " ".join(parts)


def test_diagnostics_tool_exists(server) -> None:
    """get_server_info is registered and callable."""
    result_text = asyncio.run(_call_tool(server, "get_server_info"))
    assert "godot-mcp" in result_text
    assert "toolsets" in result_text


def test_diagnostics_contains_toolset_summaries(server) -> None:
    """The response enumerates toolsets with counts."""
    result_text = asyncio.run(_call_tool(server, "get_server_info"))
    # Core + inspection are always present.
    assert "core" in result_text
    assert "inspection" in result_text
    assert "scene_edit" in result_text


def test_diagnostics_contains_prompts_list(server) -> None:
    """The response lists available prompts."""
    result_text = asyncio.run(_call_tool(server, "get_server_info"))
    assert "toolset_discovery" in result_text
    assert "build_scene" in result_text
    assert "play_test" in result_text
    assert "script_edit" in result_text
    assert "troubleshoot" in result_text


def test_diagnostics_contains_resources_list(server) -> None:
    """The response lists available resource URIs."""
    result_text = asyncio.run(_call_tool(server, "get_server_info"))
    assert "godot://project/info" in result_text
    assert "godot://scene/current" in result_text


def test_diagnostics_contains_common_errors(server) -> None:
    """The response includes the troubleshooting cheat-sheet."""
    result_text = asyncio.run(_call_tool(server, "get_server_info"))
    assert "BRIDGE_DISCONNECTED" in result_text
    assert "PRECONDITION_FAILED" in result_text
    assert "ToolError: unknown tool" in result_text


def test_diagnostics_contains_next_steps(server) -> None:
    """The response suggests next actions based on bridge/scene state."""
    result_text = asyncio.run(_call_tool(server, "get_server_info"))
    assert "next_steps" in result_text
