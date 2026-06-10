# Evaluation Framework for godot-mcp

A/B testing harness for tool description variants, logging metrics to MLFlow.

## Files

| File | Purpose |
|---|---|
| `evals/mlflow_tracker.py` | MLFlow REST API client (uses curl due to local Python socket issue) |
| `evals/variants.py` | Description variant definitions: baseline, concise, structured, agent_optimized |
| `evals/harness.py` | Evaluation runner — connects to the Godot addon bridge, runs benchmark tasks, logs to MLFlow |

## Usage

### Run a single variant
```bash
python -m evals.harness --variant baseline --tasks debugger_basic
```

### Run all variants
```bash
python -m evals.harness --variant all --tasks all
```

## Metrics logged to MLFlow

- `completion_rate` — % of tasks that succeed
- `mean_steps` — average tool calls per task
- `mean_errors` — average validation/precondition errors per task
- `mean_duration_ms` — average wall-clock time per task
- `token_efficiency` — tokens per step (lower is better)
- Per-task breakdowns: `{task_name}_success`, `{task_name}_steps`, etc.

## MLFlow Instance

Tracking URI: `https://mlflow.johndstudios.net`
Experiment: `godot-mcp-tool-desc-eval`

## Current Limitations

1. **Debugger evals require manual pause**: The harness can't reliably pause the running game via `force_break` or `set_breakpoint` in headless mode. For accurate debugger tool evals, pause the game manually (via editor breakpoint or the DebuggerDemo's `breakpoint` keyword) before running the harness.

2. **Python socket timeout**: Direct Python HTTP connections to `192.168.0.20:443` fail with `Errno 65 No route to host`. The MLFlow tracker works around this by delegating to `curl` via subprocess.

## Next Steps

1. Add more task definitions (scene creation, script editing, etc.)
2. Implement description swapping in `mcp_server/tools/*.py`
3. Run full A/B test across all variants
4. Analyze results and apply the winning variant
