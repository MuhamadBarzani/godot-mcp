@tool
class_name MCPDebuggerHandlers
extends RefCounted
## Domain handler: debugger breakpoint control (issue #110, Tier 1).
##
## Registered by the router on _init().  Each handler receives params dict and
## returns a response body (without id) via the router's _ok / _fail builders.

var _router: MCPCommandRouter


func _init(router: MCPCommandRouter) -> void:
	_router = router


func register(handlers: Dictionary) -> void:
	handlers["cmd_set_breakpoint"] = _cmd_set_breakpoint
	handlers["cmd_remove_breakpoint"] = _cmd_remove_breakpoint
	handlers["cmd_clear_breakpoints"] = _cmd_clear_breakpoints
	handlers["cmd_force_break"] = _cmd_force_break


# -- handlers ----------------------------------------------------------------

func _cmd_set_breakpoint(params: Dictionary) -> Dictionary:
	var guard := _router._require_debug_session()
	if not guard["ok"]:
		return guard
	var path := str(params.get("path", ""))
	var line := int(params.get("line", 0))
	if path.is_empty() or line <= 0:
		return _router._fail("VALIDATION_ERROR", "'path' and 'line' are required and line must be > 0.")

	var debugger := _router._debugger as MCPDebugger
	var session := debugger.get_session(debugger.get_session_id())
	session.set_breakpoint(path, line, true)
	debugger.track_breakpoint(path, line, true)
	return _router._ok({"breakpoint_set": true, "path": path, "line": line})


func _cmd_remove_breakpoint(params: Dictionary) -> Dictionary:
	var guard := _router._require_debug_session()
	if not guard["ok"]:
		return guard
	var path := str(params.get("path", ""))
	var line := int(params.get("line", 0))
	if path.is_empty() or line <= 0:
		return _router._fail("VALIDATION_ERROR", "'path' and 'line' are required and line must be > 0.")

	var debugger := _router._debugger as MCPDebugger
	var session := debugger.get_session(debugger.get_session_id())
	session.set_breakpoint(path, line, false)
	debugger.track_breakpoint(path, line, false)
	return _router._ok({"breakpoint_removed": true, "path": path, "line": line})


func _cmd_clear_breakpoints(_params: Dictionary) -> Dictionary:
	var guard := _router._require_debug_session()
	if not guard["ok"]:
		return guard

	var debugger := _router._debugger as MCPDebugger
	# Clear on the game side via the probe when available.
	if debugger.is_connected_to_probe():
		debugger.send_to_probe("godot_mcp:clear_breakpoints", [])
	# Also clear any individually tracked breakpoints in the current session.
	var tracked: Array = debugger.get_tracked_breakpoints()
	for bp in tracked:
		var bp_path: String = str(bp.get("path", ""))
		var bp_line: int = int(bp.get("line", 0))
		if not bp_path.is_empty() and bp_line > 0:
			var session := debugger.get_session(debugger.get_session_id())
			session.set_breakpoint(bp_path, bp_line, false)
	debugger.clear_tracked_breakpoints()
	return _router._ok({"breakpoints_cleared": true})


func _cmd_force_break(_params: Dictionary) -> Dictionary:
	var guard := _router._require_live_probe()
	if not guard["ok"]:
		return guard
	_router._debugger.send_to_probe("godot_mcp:force_break", [])
	return _router._ok({"force_break_sent": true})
