# Comprehensive Eval Results — godot-mcp Toolset Coverage

**Date**: 2026-06-10
**Run**: `python -m evals.suite`
**MLFlow Experiment**: https://mlflow.johndstudios.net/#/experiments/55

## Results Summary

| Toolset | Status | Steps | Errors | Duration | Primary Failure Mode |
|---------|--------|-------|--------|----------|---------------------|
| core | ❌ FAIL | 1 | 1 | 100ms | Unknown command (server-only) |
| inspection | ✅ PASS | 3 | 0 | 302ms | — |
| scene_edit | ❌ FAIL | 1 | 1 | 99ms | Unknown command (server-only) |
| scripts | ❌ FAIL | 2 | 1 | 200ms | Unknown command (server-only) |
| runtime | ✅ PASS | 2 | 0 | 200ms | — |
| debugger | ✅ PASS | 6 | 0 | 2954ms | — |
| physics | ❌ FAIL | 2 | 1 | 9ms | RESOURCE_NOT_FOUND (node missing) |
| input | ❌ FAIL | 2 | 1 | 11ms | PRECONDITION_FAILED (no play session) |
| analysis | ❌ FAIL | 2 | 1 | 14ms | Unknown command (server-only) |
| export | ❌ FAIL | 2 | 1 | 14ms | Unknown command (server-only) |
| batch | ❌ FAIL | 2 | 1 | 15ms | VALIDATION_ERROR (param shape) |
| profiling | ✅ PASS | 2 | 0 | 13ms | — |
| testing | ❌ FAIL | 2 | 1 | 13ms | Unknown command (server-only) |

**Total**: 4 passed, 9 failed out of 13 toolsets tested

## Failure Mode Breakdown

### Category A: Server-Only Tools (6 toolsets)
These tools are implemented in the MCP server itself and do **not** send `cmd_*` messages to the addon. The bridge cannot route them.

- `get_server_info` — lives in `mcp_server/diagnostics.py`
- `list_toolsets` — lives in `mcp_server/toolsets.py`
- `enable_toolset` — lives in `mcp_server/toolsets.py`
- `get_parse_errors` — lives in `mcp_server/tools/scripts.py` (runs headless GDScript parser)
- `project_stats` — lives in `mcp_server/tools/analysis.py` (filesystem scan)
- `list_presets` — lives in `mcp_server/tools/export.py` (reads export_presets.cfg)
- `assert_node_state` — lives in `mcp_server/tools/testing.py` (polls addon caches)

**Impact**: Agents trying to call these through raw bridge connections fail. In a real MCP client session (Claude Code, OpenCode), they work fine because the FastMCP layer handles them.

**Recommendation**: The eval suite should distinguish between:
1. **Addon-bridge tools** — require WebSocket to Godot addon
2. **Server-local tools** — handled by Python server logic
3. **Hybrid tools** — some logic in Python, some addon calls

### Category B: Correct Precondition Failures (2 toolsets)
These are **expected** failures — the agent didn't satisfy a prerequisite.

- `input.simulate_key` → `PRECONDITION_FAILED: No play session`
- `physics.setup_physics_body` → `RESOURCE_NOT_FOUND: Node missing`

**Impact**: These are NOT description bugs. They're workflow sequencing issues. An agent that reads the prompts (especially `play_test`) would know to call `play_scene()` first.

**Recommendation**: Improve the `play_test` prompt to explicitly list the prerequisite order.

### Category C: Parameter Validation (1 toolset)

- `batch.find_nodes_by_type` → `VALIDATION_ERROR: 'type' must be non-empty`
- Root cause: Test sent `{}` instead of `{"type": "Node2D"}`

**Impact**: Description was clear enough (param named `node_type` with type `str`), but the eval test had a bug.

## Passing Toolsets Analysis

### inspection (always-on)
- `get_project_info`, `get_active_scene`, `get_scene_tree`
- **Why they pass**: No prerequisites, no toolset gating, always available
- **Risk**: Low

### runtime (gated)
- `is_playing`, `play_scene`
- **Why they pass**: Clear descriptions, obvious prerequisites
- **Risk**: Medium — `play_scene` requires a `res://` path, but the description makes that clear

### debugger (gated)
- `set_breakpoint`, `play_scene`, `remove_breakpoint`, `continue_execution`
- **Why they pass**: Step-by-step workflow is well-documented in prompts
- **Risk**: High — stack/eval tools return empty because of the protocol prefix limitation (see README)

### profiling (gated)
- `get_editor_performance`
- **Why it passes**: Simple, no params, reads editor directly
- **Risk**: Low

## Recommendations for Description/Prompt Improvements

### 1. Mandatory Protocol Emphasis (High Priority)

The `instructions` field in `server.py` lists the mandatory protocol, but eval data shows agents still skip steps. Add stronger visual cues:

```python
# Current:
"MANDATORY PROTOCOL:\n"
"1. Call get_server_info() ...\n"

# Recommended:
"⚠️ MANDATORY PROTOCOL — skipping steps causes 'ToolError: unknown tool':\n"
"   STEP 1 (ALWAYS FIRST): get_server_info() → check bridge.connected\n"
"   STEP 2 (BEFORE ANY EDIT): list_toolsets() → see what's enabled\n"
"   STEP 3 (FOR EVERY CATEGORY): enable_toolset('scene_edit') etc.\n"
"   STEP 4 (ONLY THEN): call scene_edit, scripts, physics, ... tools\n"
```

### 2. Toolset Discovery Prompt Enhancement (High Priority)

The `toolset_discovery` prompt is good but lacks a **decision tree** for "which toolset do I need?"

```python
# Add to toolset_discovery prompt:
"DECISION TREE:\n"
"- Creating/editing scenes → enable_toolset('scene_edit')\n"
"- Writing/fixing scripts → enable_toolset('scripts')\n"
"- Running the game → enable_toolset('runtime')\n"
"- Simulating input → enable_toolset('input') + enable_toolset('runtime')\n"
"- Debugging crashes → enable_toolset('debugger') + enable_toolset('scripts')\n"
"- Performance issues → enable_toolset('profiling')\n"
"- Exporting builds → enable_toolset('export')\n"
"- Importing assets → enable_toolset('asset_import')\n"
```

### 3. Per-Tool "When to Use" Section (Medium Priority)

Agents struggle to choose between similar tools:

- `play_scene` vs `run_and_capture`
- `get_scene_tree` vs `get_game_scene_tree`
- `set_breakpoint` vs `force_break`

Add explicit WHEN/WHEN-NOT to each tool docstring:

```python
@mcp.tool(meta=RUNTIME, tags=RUNTIME_SET)
async def play_scene(...) -> PlayResult:
    """Play a scene in the Godot EDITOR (live, interactive, needs runtime probe).

    WHEN TO USE: You need to interact with the running game (simulate input,
    inspect live nodes, debug). Requires the Godot editor to be open.

    WHEN NOT TO USE: Headless automated tests → use run_and_capture() instead.
    """
```

### 4. Error Recovery Hints (High Priority)

When a tool returns `PRECONDITION_FAILED`, the agent often doesn't know what to do. Enhance descriptions with recovery paths:

```python
@mcp.tool(meta=INPUT, tags=INPUT_TAG)
async def simulate_key(...) -> InputResult:
    """Simulate a keyboard press in the running game.

    ⚠️ REQUIRES: A play session (call play_scene() first) AND the
    MCPRuntimeProbe autoload in the game.

    IF THIS FAILS with 'No play session': call play_scene(scene_path) first.
    IF THIS FAILS with 'probe not connected': add MCPRuntimeProbe to autoloads.
    """
```

### 5. Server Instructions Clarification (Medium Priority)

The server `instructions` says only `core` and `inspection` are on by default, but doesn't explicitly warn that `core` includes `get_server_info` and `list_toolsets` while other tools are **completely invisible**.

Add:
```python
"CRITICAL: Before calling ANY tool other than get_server_info/list_toolsets/health_check,\n"
"you MUST call enable_toolset(category). The tool literally does not exist until enabled.\n"
"Calling create_node before enable_toolset('scene_edit') will raise ToolError.\n"
```

## MLFlow Metrics

| Metric | Value |
|--------|-------|
| completion_rate | 0.308 |
| total_errors | 9 |
| failed_tasks | 9 |
| passed_tasks | 4 |

Per-toolset completion rates logged to MLFlow for trend tracking.

## Next Steps

1. **Split eval suite** into "addon-bridge" vs "server-local" test paths
2. **Implement description variants** (concise, structured, agent_optimized)
3. **Re-run A/B test** with improved descriptions
4. **Measure delta** in completion_rate and error patterns
5. **Apply winning variant** to all tool docstrings
