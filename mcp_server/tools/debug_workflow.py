"""Stub for debug workflow. Full implementation lands in feat/100-debug-workflow."""

from __future__ import annotations

from fastmcp import FastMCP

from mcp_server.bridge import Bridge
from mcp_server.config import ServerConfig
from mcp_server.runtime import Runner


def register_debug_workflow(
    mcp: FastMCP, bridge: Bridge, config: ServerConfig, runner: Runner
) -> None:
    """Stub — replaced by full implementation in PR #100."""
    pass
