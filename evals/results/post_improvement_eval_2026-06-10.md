# godot-mcp Eval Results — Post-Improvement Comparison

**Date**: 2026-06-10  
**Run type**: Comprehensive suite (`python -m evals.suite`)  
**Changes since baseline**: PRs #133–#136 (decision tree prompts, WHEN/WHEN-NOT sections, error recovery hints, `check_force_break()` helper)  
**Godot**: 4.4+ with vampire example project (MCPRuntimeProbe autoload enabled)  
**MLFlow**: https://mlflow.johndstudios.net/#/experiments/55

---

## Results Comparison

| Toolset | Baseline | Post-Improvement | Change |
|---------|----------|-----------------|--------|
| core | FAIL | FAIL | None — server-only tool routed through bridge |
| inspection | PASS | PASS | None |
| scene_edit | FAIL | FAIL | None — server-only `enable_toolset` routed through bridge |
| scripts | FAIL | FAIL | None — server-only `get_parse_errors` routed through bridge |
| runtime | PASS | PASS | None |
| debugger | PASS | PASS | None — `force_break` still works via flag |
| physics | FAIL | FAIL | None — TestBody not in scene (correct precondition) |
| input | FAIL | FAIL | None — no play session (correct precondition) |
| analysis | FAIL | FAIL | None — server-only |
| export | FAIL | FAIL | None — server-only |
| batch | FAIL | FAIL | None — param name mismatch (`type` vs `node_type`) |
| profiling | PASS | PASS | None |
| testing | FAIL | FAIL | None — server-only |

**Score**: 4/13 before → **4/13 after** (no change expected)

---

## Why No Change?

The comprehensive suite measures **tool existence and routing** (can the tool be called and does it return a valid shape?). It does NOT measure:

1. **Agent tool selection accuracy** — Does the agent choose `play_scene` vs `run_and_capture`?
2. **Toolset gating compliance** — Does the agent call `enable_toolset` BEFORE `create_node`?
3. **Error recovery behavior** — Does the agent retry with `play_scene()` after "No play session"?
4. **Decision tree usage** — Does the agent follow the intent → toolset mapping?

Our PRs (#133–#136) improved **descriptions, prompts, and instructions** — all signals consumed by an LLM agent. The suite's failures are at the infrastructure layer (server vs addon routing, missing nodes, param shapes), not the agent behavior layer.

---

## What WAS Improved (Agent-Facing)

### PR #133: Decision Tree + Strengthened Instructions
- `toolset_discovery` prompt now maps 10 common intents to required toolsets
- Server vs addon boundary explicitly documented
- Warning: "EVERY tool call will fail if you skip enable_toolset"

**Expected impact**: Fewer "unknown tool" errors from agents calling `get_server_info` or `enable_toolset` through the addon bridge.

### PR #134: WHEN/WHEN-NOT Sections
- 10 high-risk tools now have explicit WHEN TO USE / WHEN NOT TO USE
- Examples: `play_scene` vs `run_and_capture`, `get_scene_tree` vs `get_game_scene_tree`

**Expected impact**: Agents less likely to choose the wrong tool for the intent.

### PR #129: Error Recovery Hints
- 7 commonly failing tools now embed "IF THIS FAILS with X → do Y"
- Examples: `simulate_key` → "IF 'No play session' → call play_scene() first"

**Expected impact**: Agents recover from precondition failures instead of stalling.

### PR #131: `check_force_break()` Helper
- `MCPRuntimeProbe.check_force_break()` encapsulates flag-check + `breakpoint`
- Updated example scripts; documented deadlock limitation

**Expected impact**: Debugger workflows are more reliable in consuming games.

---

## How to Measure Agent Impact

To verify the description improvements actually help agents, run an **LLM agent behavior test**:

### Option 1: A/B Harness (evals/harness.py)
```bash
# Requires an LLM client (Claude Code, OpenCode, etc.) connected to the MCP server
python -m evals.harness --variant all --tasks all
```

Metrics to compare across variants:
- `completion_rate` — % of tasks the agent completes without errors
- `mean_steps` — fewer steps = more efficient routing
- `mean_errors` — fewer errors = better error recovery
- `token_efficiency` — lower = less back-and-forth

### Option 2: Manual Verification
1. Connect Claude Code / OpenCode to the updated MCP server
2. Give the agent a task: "Create a Player node with a script and run the game"
3. Observe:
   - Does it call `list_toolsets()` first?
   - Does it enable `scene_edit`, `scripts`, `runtime` before use?
   - Does it call `play_scene()` before `simulate_key()`?
   - Does it recover from "No play session" with the hint?

### Option 3: Regression Suite
Add new eval tasks that explicitly test agent behavior:

```python
async def _task_agent_toolset_discovery(bridge: BridgeConnector) -> TaskResult:
    """Does the agent enable toolsets before using them?"""
    # Simulate an agent that reads instructions, then tries create_node
    # without enable_toolset. With PR #133, it should succeed.

async def _task_agent_error_recovery(bridge: BridgeConnector) -> TaskResult:
    """Does the agent recover from 'No play session'?"""
    # Call simulate_key without play_scene
    # With PR #129, agent should see hint and retry with play_scene
```

---

## Recommendation

1. **Keep the comprehensive suite** for infrastructure regression testing (tool existence, routing, preconditions)
2. **Add agent behavior tasks** to the harness to measure the impact of description/prompt changes
3. **Log A/B results to MLFlow** with variant tags (`baseline`, `post-133-136`) for comparison
4. **Re-run after 1–2 weeks of agent usage** to gather real-world completion rate data

---

## Files

- Baseline: `evals/results/comprehensive_suite_results.md`
- This report: `evals/results/post_improvement_eval_2026-06-10.md`