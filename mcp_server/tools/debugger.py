"""Debugger breakpoint control tools (issue #110, Tier 1).

Control breakpoints in a running editor play session via the debugger session.
Requires a play session; the game must be connected to the editor debugger.
Gated in the ``debugger`` toolset.
"""

from __future__ import annotations

from fastmcp import FastMCP

from mcp_server.bridge import Bridge
from mcp_server.categories import DEBUGGER_TAG
from mcp_server.models.debugger import (
    BreakpointResult,
    ClearBreakpointsResult,
    ForceBreakResult,
)
from mcp_server.safety import RUNTIME
from mcp_server.tools._route import route

DEBUGGER = {DEBUGGER_TAG}


def register_debugger(mcp: FastMCP, bridge: Bridge) -> None:
    """Register the debugger breakpoint control tools."""

    @mcp.tool(meta=RUNTIME, tags=DEBUGGER)
    async def set_breakpoint(path: str, line: int) -> BreakpointResult:
        """Set a breakpoint at ``line`` in ``path`` (a ``res://`` script path).
        The game must be running from the editor so the debugger session is active.
        """
        params = {"path": path, "line": line}
        return BreakpointResult(**await route(bridge, "cmd_set_breakpoint", params))

    @mcp.tool(meta=RUNTIME, tags=DEBUGGER)
    async def remove_breakpoint(path: str, line: int) -> BreakpointResult:
        """Remove a previously-set breakpoint at ``line`` in ``path``."""
        params = {"path": path, "line": line}
        return BreakpointResult(**await route(bridge, "cmd_remove_breakpoint", params))

    @mcp.tool(meta=RUNTIME, tags=DEBUGGER)
    async def clear_breakpoints() -> ClearBreakpointsResult:
        """Clear every breakpoint in the current debug session (editor + game side)."""
        return ClearBreakpointsResult(**await route(bridge, "cmd_clear_breakpoints", {}))

    @mcp.tool(meta=RUNTIME, tags=DEBUGGER)
    async def force_break() -> ForceBreakResult:
        """Trigger an immediate break in the running game via the runtime probe.
        Requires a play session with the godot-mcp runtime probe autoload.
        """
        return ForceBreakResult(**await route(bridge, "cmd_force_break", {}))
