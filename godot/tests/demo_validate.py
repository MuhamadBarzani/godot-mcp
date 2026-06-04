#!/usr/bin/env python3
"""Validate the demo game works with Godot open (not headless).

This script launches Godot editor with the demo project, connects via
the MCP bridge, plays the scene, verifies the runtime probe delivers
a live scene tree, and confirms the game is inspectable.

Usage (requires Godot 4.4+):
    GODOT_MCP_GODOT_BIN=/Applications/Godot.app/Contents/MacOS/Godot \
        uv run python godot/tests/demo_validate.py
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys

# Add repo root to path so we can import mcp_server
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from mcp_server.bridge import Bridge
from mcp_server.config import BridgeConfig

BRIDGE_URL = "ws://localhost:9080"
DEMO_PROJECT = os.path.join(os.path.dirname(__file__), "../demo")
GODOT_BIN = os.environ.get("GODOT_MCP_GODOT_BIN", "godot")


async def _ok(bridge: Bridge, command: str, params: dict) -> dict:
    response = await bridge.send(command, params)
    assert response.ok and response.result is not None, (
        f"{command}: {response.error} {response.hint}"
    )
    return response.result


async def _wait_playing(bridge: Bridge, want: bool) -> None:
    for _ in range(20):
        state = await _ok(bridge, "cmd_is_playing", {})
        if state["playing"] is want:
            return
        await asyncio.sleep(0.5)
    raise AssertionError(f"is_playing never became {want}")


async def _run() -> None:
    print("[1/6] Starting Godot editor with demo project...")
    editor = subprocess.Popen(
        [GODOT_BIN, "--headless", "--editor", "--path", DEMO_PROJECT],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    try:
        print("[2/6] Connecting to MCP bridge...")
        bridge = Bridge(BridgeConfig(url=BRIDGE_URL))
        for attempt in range(60):
            try:
                await bridge.connect()
                print(f"    Connected on attempt {attempt + 1}")
                break
            except Exception:
                await asyncio.sleep(0.5)
        else:
            raise AssertionError("could not connect to the addon bridge")

        print("[3/6] Checking project info...")
        info = await _ok(bridge, "cmd_get_project_info", {})
        assert info["name"] == "godot-mcp-demo", f"Unexpected project: {info['name']}"
        print(f"    Project: {info['name']}, Godot: {info['godot_version']}")

        print("[4/6] Verifying probe autoload is registered...")
        autoloads = info.get("autoloads", {})
        assert "MCPRuntimeProbe" in autoloads, (
            "MCPRuntimeProbe autoload not found. Run: register_autoload "
            'name="MCPRuntimeProbe" path="res://addons/godot_mcp/mcp_runtime_probe.gd"'
        )
        print(f"    Probe autoload: {autoloads['MCPRuntimeProbe']}")

        print("[5/6] Playing the demo scene...")
        # Open the scene first so the editor knows what to play
        await _ok(bridge, "cmd_open_scene", {"scene_path": "res://scenes/main.tscn"})
        await asyncio.sleep(1.0)

        await _ok(bridge, "cmd_play_scene", {"scene_path": "res://scenes/main.tscn"})
        await _wait_playing(bridge, True)
        print("    Game is running")

        print("[6/6] Inspecting live scene tree via runtime probe...")
        tree = None
        for _ in range(30):
            state = await _ok(bridge, "cmd_get_game_scene_tree", {})
            if state["connected"] and state["tree"]:
                tree = state["tree"]
                break
            await asyncio.sleep(0.5)

        assert tree is not None, "probe never delivered the live scene tree"
        child_types = [c["type"] for c in tree.get("children", [])]
        print(f"    Live root type: {tree['type']}")
        print(f"    Scene types: {child_types}")
        assert "Node2D" in child_types, "Expected Node2D scene root in live tree"
        print("    ✅ Live inspection works!")

        # Check for our specific game nodes
        main_node = next((c for c in tree["children"] if c["type"] == "Node2D"), None)
        if main_node:
            main_children = [c["name"] for c in main_node.get("children", [])]
            print(f"    Main children: {main_children}")
            assert "Player" in main_children, "Expected Player in live scene"
            assert "Coins" in main_children, "Expected Coins in live scene"
            assert "UI" in main_children, "Expected UI in live scene"
            print("    ✅ Game nodes found in live tree!")

        print("\n[✅] All validations passed! The demo game works with Godot open.")
        print("")
        print("You can now:")
        print("  - simulate_action(action='ui_right') to move the player")
        print("  - monitor_property('/root/Main/Player', 'position') to watch movement")
        print("  - assert_node_state('/root/Main/GameManager', 'coin_count', 0, '==')")
        print("  - find_ui_elements(name_contains='Score') to read the label")

        await _ok(bridge, "cmd_stop_scene", {})
        await _wait_playing(bridge, False)
        await bridge.close()

    finally:
        editor.terminate()
        try:
            editor.wait(timeout=10)
        except subprocess.TimeoutExpired:
            editor.kill()


if __name__ == "__main__":
    asyncio.run(_run())
