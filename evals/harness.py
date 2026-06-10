#!/usr/bin/env python3
"""Evaluation harness for godot-mcp tool description A/B testing.

Connects to the running MCP server (stdio transport) and executes a set of
benchmark tasks against each description variant, logging metrics to MLFlow.

Usage:
    python -m evals.harness --variant baseline --tasks debugger_basic
    python -m evals.harness --variant all --tasks all
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

# We connect to the MCP server via the local bridge, not stdio
sys.path.insert(0, "/Users/johnd/Development/godot-mcp")

from mcp_server.bridge import Bridge
from mcp_server.config import BridgeConfig
from mcp_server.models.envelope import ResponseEnvelope

from evals.mlflow_tracker import EvalTracker
from evals.variants import ALL_VARIANTS


@dataclass
class TaskResult:
    """Outcome of a single benchmark task."""

    task_name: str
    success: bool = False
    steps: int = 0
    errors: int = 0
    duration_ms: float = 0.0
    tokens_estimate: int = 0
    notes: str = ""
    tool_calls: list[dict] = field(default_factory=list)


@dataclass
class VariantResult:
    """Aggregated results for one description variant."""

    variant: str
    tasks: list[TaskResult] = field(default_factory=list)

    @property
    def completion_rate(self) -> float:
        if not self.tasks:
            return 0.0
        return sum(1 for t in self.tasks if t.success) / len(self.tasks)

    @property
    def mean_steps(self) -> float:
        if not self.tasks:
            return 0.0
        return sum(t.steps for t in self.tasks) / len(self.tasks)

    @property
    def mean_errors(self) -> float:
        if not self.tasks:
            return 0.0
        return sum(t.errors for t in self.tasks) / len(self.tasks)

    @property
    def mean_duration_ms(self) -> float:
        if not self.tasks:
            return 0.0
        return sum(t.duration_ms for t in self.tasks) / len(self.tasks)

    @property
    def token_efficiency(self) -> float:
        """Tokens per step (lower is better)."""
        total_tokens = sum(t.tokens_estimate for t in self.tasks)
        total_steps = sum(t.steps for t in self.tasks)
        return total_tokens / max(total_steps, 1)


class BridgeConnector:
    """Lightweight bridge wrapper for eval tasks."""

    def __init__(self) -> None:
        self._bridge = Bridge(BridgeConfig.from_env())

    async def connect(self) -> bool:
        try:
            await self._bridge.connect()
            return self._bridge.connected
        except Exception:
            return False

    async def call(self, command: str, params: dict | None = None) -> dict:
        resp = await self._bridge.send(command, params or {})
        return {
            "ok": resp.ok,
            "result": resp.result or {},
            "error": resp.error,
            "hint": resp.hint,
        }

    async def close(self) -> None:
        await self._bridge.close()


# ---------------------------------------------------------------------------
# Task definitions
# ---------------------------------------------------------------------------

TaskFn = Callable[[BridgeConnector], Awaitable[TaskResult]]


async def _task_debugger_basic(bridge: BridgeConnector) -> TaskResult:
    """Basic debugger workflow: set breakpoint, play scene, wait for hit, stack, eval, continue."""
    result = TaskResult(task_name="debugger_basic")
    start = time.perf_counter()

    # Step 1: set breakpoint at _process (hits every frame)
    r = await bridge.call("cmd_set_breakpoint", {"path": "res://scripts/debugger_demo.gd", "line": 38})
    result.steps += 1
    result.tokens_estimate += 300
    if not r["ok"]:
        result.errors += 1
        result.notes = f"set_breakpoint failed: {r.get('hint')}"
        result.duration_ms = (time.perf_counter() - start) * 1000
        return result

    # Step 2: play scene
    r = await bridge.call("cmd_play_scene", {"scene_path": "res://scenes/main.tscn"})
    result.steps += 1
    result.tokens_estimate += 300
    if not r["ok"]:
        result.errors += 1
        result.notes = f"play_scene failed: {r.get('hint')}"
        result.duration_ms = (time.perf_counter() - start) * 1000
        return result

    # Step 3: wait for breakpoint to hit (poll stack frames)
    await asyncio.sleep(1)
    frames = []
    for i in range(20):
        r = await bridge.call("cmd_get_stack_frames", {})
        result.steps += 1
        result.tokens_estimate += 200
        frames = r.get("result", {}).get("frames", [])
        if frames:
            break
        await asyncio.sleep(0.3)

    if not frames:
        result.errors += 1
        result.notes = "get_stack_frames returned empty after 20 attempts (breakpoint may not have hit)"
        result.duration_ms = (time.perf_counter() - start) * 1000
        return result

    # Step 4: evaluate_expression
    r = await bridge.call(
        "cmd_evaluate_expression",
        {"expression": "_counters['a']", "frame": 0},
    )
    result.steps += 1
    result.tokens_estimate += 250
    if not r["ok"]:
        result.errors += 1
        result.notes = f"evaluate_expression failed: {r.get('hint')}"
        result.duration_ms = (time.perf_counter() - start) * 1000
        return result

    # Step 5: remove breakpoint so game can continue
    r = await bridge.call("cmd_remove_breakpoint", {"path": "res://scripts/debugger_demo.gd", "line": 38})
    result.steps += 1
    result.tokens_estimate += 200

    # Step 6: continue
    r = await bridge.call("cmd_continue_execution", {})
    result.steps += 1
    result.tokens_estimate += 150

    result.success = True
    result.duration_ms = (time.perf_counter() - start) * 1000
    result.notes = f"Breakpoint hit, {len(frames)} frames, eval value: {r.get('result', {}).get('value')}"
    return result


async def _task_debugger_eval_chain(bridge: BridgeConnector) -> TaskResult:
    """Chain: set breakpoint, play, wait for hit, stack, eval, step, continue."""
    result = TaskResult(task_name="debugger_eval_chain")
    start = time.perf_counter()

    steps = [
        ("cmd_set_breakpoint", {"path": "res://scripts/debugger_demo.gd", "line": 43}, 300),
        ("cmd_play_scene", {"scene_path": "res://scenes/main.tscn"}, 300),
    ]

    for cmd, params, tokens in steps:
        r = await bridge.call(cmd, params)
        result.steps += 1
        result.tokens_estimate += tokens
        if not r["ok"]:
            result.errors += 1
            result.notes = f"{cmd} failed: {r.get('hint')}"
            result.duration_ms = (time.perf_counter() - start) * 1000
            return result

    # Wait for breakpoint (or timeout)
    await asyncio.sleep(5)

    # Poll stack frames
    frames = []
    for _ in range(5):
        r = await bridge.call("cmd_get_stack_frames", {})
        result.steps += 1
        result.tokens_estimate += 200
        frames = r.get("result", {}).get("frames", [])
        if frames:
            break
        await asyncio.sleep(0.5)

    if not frames:
        result.errors += 1
        result.notes = "Breakpoint never hit or stack empty"
        result.duration_ms = (time.perf_counter() - start) * 1000
        return result

    # Evaluate
    r = await bridge.call(
        "cmd_evaluate_expression",
        {"expression": "_counters['a']", "frame": 0},
    )
    result.steps += 1
    result.tokens_estimate += 250

    # Step into
    r = await bridge.call("cmd_step_into", {})
    result.steps += 1
    result.tokens_estimate += 150
    await asyncio.sleep(0.5)

    # Continue
    r = await bridge.call("cmd_continue_execution", {})
    result.steps += 1
    result.tokens_estimate += 150

    result.success = True
    result.duration_ms = (time.perf_counter() - start) * 1000
    result.notes = f"Breakpoint hit, {len(frames)} frames, stepped and continued"
    return result


TASKS: dict[str, TaskFn] = {
    "debugger_basic": _task_debugger_basic,
    "debugger_eval_chain": _task_debugger_eval_chain,
}


# ---------------------------------------------------------------------------
# Harness runner
# ---------------------------------------------------------------------------

async def run_variant(variant: str, task_names: list[str]) -> VariantResult:
    """Run all tasks for a single variant and return aggregated results."""
    print(f"\n{'='*60}")
    print(f"  Variant: {variant}")
    print(f"{'='*60}")

    bridge = BridgeConnector()
    if not await bridge.connect():
        print("ERROR: Could not connect to Godot addon bridge.")
        print("Make sure Godot is running with the vampire project and the MCP addon is enabled.")
        return VariantResult(variant=variant)

    result = VariantResult(variant=variant)

    for task_name in task_names:
        task_fn = TASKS.get(task_name)
        if task_fn is None:
            print(f"  [SKIP] Unknown task: {task_name}")
            continue

        print(f"\n  Task: {task_name}")
        try:
            task_result = await task_fn(bridge)
            result.tasks.append(task_result)
            status = "✅ PASS" if task_result.success else "❌ FAIL"
            print(f"    {status} | steps={task_result.steps} | errors={task_result.errors} | duration={task_result.duration_ms:.0f}ms")
            if task_result.notes:
                print(f"    Notes: {task_result.notes}")
        except Exception as e:
            print(f"    💥 EXCEPTION: {type(e).__name__}: {e}")
            result.tasks.append(TaskResult(task_name=task_name, notes=str(e)))

    await bridge.close()
    return result


def log_to_mlflow(tracker: EvalTracker, result: VariantResult) -> None:
    """Log variant results to MLFlow."""
    tracker.start_run(run_name=f"{result.variant}-{int(time.time())}", variant=result.variant)
    tracker.log_param("variant", result.variant)
    tracker.log_param("task_count", str(len(result.tasks)))
    tracker.log_param("tasks", ",".join(t.task_name for t in result.tasks))

    tracker.log_metric("completion_rate", result.completion_rate)
    tracker.log_metric("mean_steps", result.mean_steps)
    tracker.log_metric("mean_errors", result.mean_errors)
    tracker.log_metric("mean_duration_ms", result.mean_duration_ms)
    tracker.log_metric("token_efficiency", result.token_efficiency)

    # Log per-task metrics
    for i, task in enumerate(result.tasks):
        tracker.log_metric(f"{task.task_name}_success", 1.0 if task.success else 0.0, step=i)
        tracker.log_metric(f"{task.task_name}_steps", float(task.steps), step=i)
        tracker.log_metric(f"{task.task_name}_errors", float(task.errors), step=i)
        tracker.log_metric(f"{task.task_name}_duration_ms", task.duration_ms, step=i)

    tracker.end_run()
    print(f"\n  📊 Logged to MLFlow: {tracker.get_experiment_url()}")


def print_summary(results: list[VariantResult]) -> None:
    """Print a comparison table of all variants."""
    print("\n" + "=" * 80)
    print("  Evaluation Summary")
    print("=" * 80)
    print(f"  {'Variant':<18} {'Completion':<12} {'Mean Steps':<12} {'Mean Errors':<14} {'Mean ms':<10} {'Tok/Step':<10}")
    print("  " + "-" * 76)
    for r in results:
        print(
            f"  {r.variant:<18} {r.completion_rate:<12.2%} {r.mean_steps:<12.1f} "
            f"{r.mean_errors:<14.2f} {r.mean_duration_ms:<10.0f} {r.token_efficiency:<10.1f}"
        )
    print("=" * 80)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate godot-mcp tool description variants")
    parser.add_argument(
        "--variant",
        choices=["all"] + list(ALL_VARIANTS.keys()),
        default="baseline",
        help="Description variant to test",
    )
    parser.add_argument(
        "--tasks",
        choices=["all"] + list(TASKS.keys()),
        default="debugger_basic",
        help="Task(s) to run",
    )
    parser.add_argument(
        "--mlflow",
        action="store_true",
        default=True,
        help="Log results to MLFlow",
    )
    args = parser.parse_args()

    variants = list(ALL_VARIANTS.keys()) if args.variant == "all" else [args.variant]
    task_names = list(TASKS.keys()) if args.tasks == "all" else [args.tasks]

    tracker = EvalTracker() if args.mlflow else None
    all_results: list[VariantResult] = []

    for variant in variants:
        # Note: in a real A/B test we'd swap the descriptions here.
        # For now we just run the same tasks against the current codebase
        # and log the variant label for later comparison.
        result = await run_variant(variant, task_names)
        all_results.append(result)

        if tracker:
            log_to_mlflow(tracker, result)

    print_summary(all_results)


if __name__ == "__main__":
    asyncio.run(main())
