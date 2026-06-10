#!/usr/bin/env python3
"""Ollama LLM agent integration for godot-mcp evals.

Connects to a local Ollama instance (default: http://localhost:11434) and uses
qwen3-coder:30b to make tool decisions. The agent receives tool descriptions,
task context, and error hints, then chooses which tool to call next.

Usage:
    python -m evals.ollama_agent --task "Create a Player node and run the game"
    python -m evals.ollama_agent --suite agent_suite_v2
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from typing import Any

import requests

sys.path.insert(0, "/Users/johnd/Development/godot-mcp")

from mcp_server.bridge import Bridge
from mcp_server.config import BridgeConfig

OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "qwen3-coder:30b"


@dataclass
class LLMCall:
    """A single tool call chosen by the LLM."""

    tool: str
    params: dict[str, Any]
    reasoning: str = ""


@dataclass
class LLMStep:
    """One step in an LLM-driven task execution."""

    step: int
    call: LLMCall
    result: dict[str, Any] = field(default_factory=dict)
    score: float = 0.0


class OllamaAgent:
    """LLM agent that uses Ollama to choose tools."""

    def __init__(self, bridge: Bridge, model: str = MODEL) -> None:
        self._bridge = bridge
        self._model = model
        self._history: list[dict] = []

    def _system_prompt(self, task: str, available_tools: list[dict]) -> str:
        """Build the system prompt with tool descriptions."""
        tools_desc = "\n".join(
            f"- {t['name']}: {t.get('description', 'No description')[:200]}"
            for t in available_tools
        )
        return (
            f"You are an AI agent controlling a Godot game engine via MCP tools.\n\n"
            f"TASK: {task}\n\n"
            f"AVAILABLE TOOLS:\n{tools_desc}\n\n"
            f"RULES:\n"
            f"1. Only call tools that are listed above.\n"
            f"2. Follow the MANDATORY PROTOCOL: enable_toolset first, then use tools.\n"
            f"3. If a tool fails, read the error hint and choose a recovery action.\n"
            f"4. Respond ONLY with a JSON object:\n"
            f"   {{\"tool\": \"...\", \"params\": {{...}}, \"reasoning\": \"...\"}}\n"
            f"5. Use empty params {{}} if the tool takes no arguments.\n"
            f"6. When done, respond with {{\"tool\": \"done\"}}"
        )

    def _ask(self, task: str, available_tools: list[dict]) -> LLMCall:
        """Ask the LLM to choose the next tool."""
        system = self._system_prompt(task, available_tools)
        messages = [
            {"role": "system", "content": system},
            *self._history,
        ]

        resp = requests.post(
            OLLAMA_URL,
            json={
                "model": self._model,
                "messages": messages,
                "stream": False,
                "options": {"temperature": 0.2, "num_predict": 500},
            },
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()
        content = data["message"]["content"]

        # Parse JSON from the response
        try:
            # Sometimes the model wraps JSON in markdown
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            parsed = json.loads(content)
        except (json.JSONDecodeError, IndexError):
            # Fallback: try to extract the first JSON object
            start = content.find("{")
            end = content.rfind("}")
            if start >= 0 and end > start:
                try:
                    parsed = json.loads(content[start:end + 1])
                except json.JSONDecodeError:
                    parsed = {
                        "tool": "done",
                        "params": {},
                        "reasoning": f"Parse: {content[:80]}",
                    }
            else:
                parsed = {
                    "tool": "done",
                    "params": {},
                    "reasoning": f"No JSON: {content[:80]}",
                }

        self._history.append({"role": "assistant", "content": json.dumps(parsed)})
        return LLMCall(
            tool=parsed.get("tool", "done"),
            params=parsed.get("params", {}),
            reasoning=parsed.get("reasoning", ""),
        )

    async def _execute(self, call: LLMCall) -> dict:
        """Execute a tool call via the bridge (async)."""
        if call.tool == "done":
            return {"ok": True, "result": {}, "done": True}

        cmd = f"cmd_{call.tool}"
        try:
            response = await self._bridge.send(cmd, call.params)
            return {
                "ok": response.ok,
                "result": response.result or {},
                "error": response.error,
                "hint": response.hint,
                "done": False,
            }
        except Exception as e:
            return {"ok": False, "error": str(e), "hint": "Bridge execution failed", "done": False}

    def _add_result(self, result: dict) -> None:
        """Add the tool result to history for the LLM."""
        summary = json.dumps({
            "ok": result["ok"],
            "error": result.get("error"),
            "hint": result.get("hint"),
            "result_keys": list(result.get("result", {}).keys()),
        })
        self._history.append({"role": "user", "content": f"Tool result: {summary}"})

    async def run_task(
        self,
        task: str,
        available_tools: list[dict],
        max_steps: int = 10,
    ) -> list[LLMStep]:
        """Run a task with the LLM agent, returning the step-by-step trace."""
        steps: list[LLMStep] = []
        for i in range(max_steps):
            call = self._ask(task, available_tools)
            result = await self._execute(call)
            self._add_result(result)
            steps.append(LLMStep(step=i+1, call=call, result=result))
            if result.get("done") or call.tool == "done":
                break
        return steps


def get_available_tools() -> list[dict]:
    """Return a subset of tools the LLM agent can use."""
    return [
        {"name": "list_toolsets", "description": "See available tool categories"},
        {"name": "enable_toolset", "description": "Enable a tool category"},
        {"name": "disable_toolset", "description": "Disable a tool category"},
        {"name": "get_project_info", "description": "Get project name, main scene, autoloads"},
        {"name": "get_scene_tree", "description": "Get open scene's node hierarchy"},
        {"name": "create_node", "description": "Add a node (needs scene_edit)"},
        {"name": "set_node_property", "description": "Set a node property (needs scene_edit)"},
        {"name": "play_scene", "description": "Run game in editor (needs runtime)"},
        {"name": "simulate_key", "description": "Send key press (needs input + runtime)"},
        {"name": "get_game_scene_tree", "description": "Get live game tree (needs runtime)"},
        {"name": "get_editor_performance", "description": "Read editor FPS (needs profiling)"},
        {"name": "write_script", "description": "Write a GDScript (needs scripts)"},
        {"name": "get_parse_errors", "description": "Check script syntax (needs scripts)"},
        {"name": "done", "description": "Signal that the task is complete"},
    ]


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Ollama LLM agent for godot-mcp")
    parser.add_argument("--task", default="Create a Node2D named TestNode and run the game")
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--max-steps", type=int, default=10)
    args = parser.parse_args()

    bridge = Bridge(BridgeConfig.from_env())
    import asyncio
    asyncio.run(bridge.connect())

    agent = OllamaAgent(bridge, model=args.model)
    tools = get_available_tools()

    async def _run():
        await bridge.connect()
        steps = await agent.run_task(args.task, tools, max_steps=args.max_steps)
        return steps

    steps = asyncio.run(_run())

    print(f"\nTask: {args.task}")
    print("=" * 60)
    for s in steps:
        status = "✅" if s.result.get("ok") else "❌"
        print(f"{status} Step {s.step}: {s.call.tool}({json.dumps(s.call.params)})")
        print(f"   Reasoning: {s.call.reasoning[:80]}")
        if not s.result.get("ok"):
            print(f"   Error: {s.result.get('error')} | {s.result.get('hint')}")
    print("=" * 60)

    bridge.close()


if __name__ == "__main__":
    main()
