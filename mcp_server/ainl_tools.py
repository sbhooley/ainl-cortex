"""AINL MCP tools integration for Claude Code.

Uses ainativelang package from PyPI (v1.7.0+).
"""
import json
import hashlib
from typing import Any, Dict, List, Optional
from pathlib import Path

# Import from installed ainativelang package
try:
    from compiler_v2 import AICodeCompiler
    from compiler_diagnostics import CompilationDiagnosticError, CompilerContext
    from runtime.engine import RuntimeEngine, AinlRuntimeError, RUNTIME_VERSION
    from runtime.adapters.base import AdapterRegistry
    from runtime.adapters.builtins import CoreBuiltinAdapter
    from runtime.adapters.http import SimpleHttpAdapter
    from runtime.adapters.sqlite import SimpleSqliteAdapter
    from runtime.adapters.fs import SandboxedFileSystemAdapter
    from tooling.capability_grant import (
        empty_grant,
        merge_grants,
        load_profile_as_grant,
    )
    from tooling.security_report import analyze_ir
    from tooling.graph_diff import graph_diff
    _HAS_AINL = True
except ImportError:
    _HAS_AINL = False
    print("Warning: ainativelang package not installed. AINL tools will not be available.")
    print("Install with: pip install ainativelang[mcp]")


try:
    from adapters.local_cache import LocalFileCacheAdapter
    _HAS_CACHE_ADAPTER = True
except ImportError:
    _HAS_CACHE_ADAPTER = False


class AINLTools:
    """AINL MCP tool implementations."""

    def __init__(self, memory_db_path: Optional[Path] = None):
        if not _HAS_AINL:
            raise ImportError("ainativelang package not installed")
        self.compiler = AICodeCompiler()

        # Initialize trajectory store
        try:
            from .trajectory_capture import TrajectoryStore
        except ImportError:
            from trajectory_capture import TrajectoryStore
        if memory_db_path:
            self.trajectory_store = TrajectoryStore(
                memory_db_path.parent / "ainl_trajectories.db"
            )
        else:
            self.trajectory_store = None

    def validate(
        self,
        source: str,
        strict: bool = True,
        filename: str = "input.ainl"
    ) -> Dict[str, Any]:
        """
        Validate AINL source code.

        Args:
            source: AINL source code
            strict: Enable strict validation
            filename: Filename for error messages

        Returns:
            {
                "valid": bool,
                "diagnostics": [...],
                "primary_diagnostic": {...},
                "agent_repair_steps": [...],
                "recommended_next_tools": [...]
            }
        """
        try:
            ctx = CompilerContext(strict=strict)
            ir = self.compiler.compile(source, ctx=ctx)

            return {
                "valid": True,
                "message": "Validation successful ✅",
                "diagnostics": [],
                "ir_summary": {
                    "labels": len(ir.get("labels", {})),
                    "services": len(ir.get("services", {})),
                    "types": len(ir.get("types", {})),
                },
                "recommended_next_tools": [
                    "ainl_compile",
                    "ainl_capabilities",
                    "ainl_run"
                ]
            }
        except CompilationDiagnosticError as e:
            diagnostics = e.diagnostics if hasattr(e, 'diagnostics') else []
            primary = diagnostics[0] if diagnostics else None

            return {
                "valid": False,
                "diagnostics": diagnostics,
                "primary_diagnostic": primary,
                "agent_repair_steps": self._get_repair_steps(primary),
                "recommended_next_tools": [
                    "ainl_capabilities",  # Check adapter/verb spelling
                ],
                "recommended_resources": [
                    "ainl://authoring-cheatsheet",
                    "ainl://adapter-manifest"
                ]
            }
        except Exception as e:
            return {
                "valid": False,
                "error": str(e),
                "error_type": type(e).__name__,
                "recommended_next_tools": ["ainl_capabilities"]
            }

    def compile(
        self,
        source: str,
        strict: bool = True,
        include_frame_hints: bool = True
    ) -> Dict[str, Any]:
        """
        Compile AINL source to IR JSON.

        Returns IR + frame hints for use with ainl_run.
        """
        try:
            ctx = CompilerContext(strict=strict)
            ir = self.compiler.compile(source, ctx=ctx)

            result = {
                "ok": True,
                "ir": ir,
                "runtime_version": RUNTIME_VERSION,
                "recommended_next_tools": ["ainl_run", "ainl_security_report"]
            }

            if include_frame_hints:
                result["frame_hints"] = self._extract_frame_hints(source, ir)

            return result

        except CompilationDiagnosticError as e:
            return {
                "ok": False,
                "error": str(e),
                "diagnostics": e.diagnostics if hasattr(e, 'diagnostics') else [],
                "recommended_next_tools": ["ainl_validate"]
            }
        except Exception as e:
            return {
                "ok": False,
                "error": str(e),
                "error_type": type(e).__name__
            }

    def run(
        self,
        source: str,
        frame: Optional[Dict[str, Any]] = None,
        adapters: Optional[Dict[str, Any]] = None,
        limits: Optional[Dict[str, Any]] = None,
        label: Optional[str] = None,
        session_id: Optional[str] = None,
        project_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Compile and execute AINL workflow.

        Args:
            source: AINL source code
            frame: Initial frame variables
            adapters: Adapter configuration
                {
                    "enable": ["http", "fs", "cache"],
                    "http": {"allow_hosts": [...], "timeout_s": 30},
                    "fs": {"root": "/path", "allow_extensions": [".json"]}
                }
            limits: Execution limits
                {
                    "max_steps": 500000,
                    "max_adapter_calls": 50000,
                    "max_time_ms": 900000
                }
            label: Specific label to execute (default: first label)
            session_id: Session ID for trajectory tracking
            project_id: Project ID for trajectory tracking
        """
        import time
        start_time = time.time()

        try:
            # Compile
            ctx = CompilerContext(strict=True)
            ir = self.compiler.compile(source, ctx=ctx)

            # Create runtime
            engine = RuntimeEngine()

            # Register core adapter (always available)
            engine.registry.register("core", CoreBuiltinAdapter())

            # Register requested adapters
            if adapters:
                enabled = adapters.get("enable", [])

                if "http" in enabled:
                    http_cfg = adapters.get("http", {})
                    engine.registry.register("http", SimpleHttpAdapter(
                        allow_hosts=http_cfg.get("allow_hosts"),
                        timeout_s=http_cfg.get("timeout_s", 30)
                    ))

                if "fs" in enabled:
                    fs_cfg = adapters.get("fs", {})
                    engine.registry.register("fs", SandboxedFileSystemAdapter(
                        root=fs_cfg.get("root", "/tmp"),
                        allow_extensions=fs_cfg.get("allow_extensions")
                    ))

                if "cache" in enabled and _HAS_CACHE_ADAPTER:
                    cache_cfg = adapters.get("cache", {})
                    engine.registry.register("cache", LocalFileCacheAdapter(
                        path=cache_cfg.get("path", "cache.json")
                    ))

                if "sqlite" in enabled:
                    sqlite_cfg = adapters.get("sqlite", {})
                    engine.registry.register("sqlite", SimpleSqliteAdapter(
                        db_path=sqlite_cfg.get("db_path")
                    ))

            # Apply limits
            if limits:
                engine.max_steps = limits.get("max_steps", 500000)
                engine.max_adapter_calls = limits.get("max_adapter_calls", 50000)

            # Execute
            result = engine.run(ir, frame=frame or {}, label=label)

            # Calculate execution time
            duration_ms = (time.time() - start_time) * 1000

            response = {
                "ok": True,
                "result": result,
                "stats": {
                    "steps_executed": getattr(engine, 'steps_executed', 0),
                    "adapter_calls": getattr(engine, 'adapter_calls', 0),
                },
                "duration_ms": duration_ms
            }

            # Capture trajectory if store is available
            if self.trajectory_store and session_id and project_id:
                from .trajectory_capture import capture_trajectory_from_run

                trajectory_result = {
                    "success": True,
                    "duration_ms": duration_ms,
                    "steps": [],  # RuntimeEngine doesn't expose steps yet
                }

                trajectory = capture_trajectory_from_run(
                    ainl_source=source,
                    frame=frame or {},
                    adapters=adapters or {},
                    result=trajectory_result,
                    session_id=session_id,
                    project_id=project_id
                )

                try:
                    self.trajectory_store.record_trajectory(trajectory)
                    response["trajectory_id"] = trajectory.trajectory_id
                except Exception as e:
                    # Non-fatal: trajectory recording failed
                    response["trajectory_error"] = str(e)

            return response

        except AinlRuntimeError as e:
            duration_ms = (time.time() - start_time) * 1000

            response = {
                "ok": False,
                "error": str(e),
                "error_type": "runtime_error",
                "duration_ms": duration_ms
            }

            # Capture failed trajectory
            if self.trajectory_store and session_id and project_id:
                from .trajectory_capture import capture_trajectory_from_run

                trajectory_result = {
                    "success": False,
                    "error": str(e),
                    "duration_ms": duration_ms,
                    "steps": [],
                }

                try:
                    trajectory = capture_trajectory_from_run(
                        ainl_source=source,
                        frame=frame or {},
                        adapters=adapters or {},
                        result=trajectory_result,
                        session_id=session_id,
                        project_id=project_id
                    )
                    self.trajectory_store.record_trajectory(trajectory)
                except:
                    pass  # Silent failure

            return response

        except CompilationDiagnosticError as e:
            return {
                "ok": False,
                "error": str(e),
                "diagnostics": e.diagnostics if hasattr(e, 'diagnostics') else [],
                "error_type": "compilation_error",
                "recommended_next_tools": ["ainl_validate"]
            }
        except Exception as e:
            return {
                "ok": False,
                "error": str(e),
                "error_type": type(e).__name__
            }

    def capabilities(self) -> Dict[str, Any]:
        """
        List available adapters and verbs.

        Returns catalog of what can be used in R lines.
        """
        # Try to load adapter manifest from package resources
        try:
            from importlib.resources import files
            tooling = files('ainativelang').joinpath('tooling')
            manifest_path = tooling / 'adapter_manifest.json'
            manifest = json.loads(manifest_path.read_text())

            return {
                "runtime_version": RUNTIME_VERSION,
                "adapters": manifest.get("adapters", {}),
                "builtin_core_ops": manifest.get("core_ops", []),
                "note": "Use these in R lines: R adapter.verb args ->result"
            }
        except Exception as e:
            # Fallback to minimal catalog
            return {
                "runtime_version": RUNTIME_VERSION,
                "adapters": {
                    "core": {
                        "description": "Built-in operations",
                        "verbs": [
                            "ADD", "SUB", "MUL", "DIV", "IDIV",
                            "EQ", "NEQ", "GT", "LT", "GTE", "LTE",
                            "GET", "LEN", "NOW", "PARSE", "STRINGIFY",
                            "CONCAT", "SPLIT", "TRIM", "KEYS", "VALUES",
                            "STR", "INT", "FLOAT", "BOOL"
                        ]
                    },
                    "http": {
                        "description": "HTTP requests",
                        "verbs": ["GET", "POST", "PUT", "DELETE", "PATCH"],
                        "note": "Positional args: url [headers] [timeout_s]"
                    },
                    "sqlite": {
                        "description": "SQLite database",
                        "verbs": ["QUERY", "EXECUTE"]
                    }
                },
                "manifest_load_error": str(e),
                "note": "Minimal catalog - install ainativelang[mcp] for full manifest"
            }

    def security_report(self, source: str) -> Dict[str, Any]:
        """
        Analyze AINL source for security concerns.
        """
        try:
            ctx = CompilerContext(strict=False)
            ir = self.compiler.compile(source, ctx=ctx)

            report = analyze_ir(ir)

            return {
                "ok": True,
                "report": report,
                "summary": {
                    "risk_level": report.get("risk_level", "unknown"),
                    "adapters_used": report.get("adapters", []),
                    "external_calls": report.get("external_calls", 0),
                }
            }
        except Exception as e:
            return {
                "ok": False,
                "error": str(e),
                "error_type": type(e).__name__
            }

    def ir_diff(
        self,
        source_a: str,
        source_b: str,
        labels: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Compare two AINL programs at IR level.

        Shows blast radius of changes.
        """
        try:
            ctx = CompilerContext(strict=False)
            ir_a = self.compiler.compile(source_a, ctx=ctx)
            ir_b = self.compiler.compile(source_b, ctx=ctx)

            diff = graph_diff(ir_a, ir_b, labels=labels)

            return {
                "ok": True,
                "diff": diff,
                "summary": {
                    "labels_changed": len(diff.get("labels", {})),
                    "services_changed": len(diff.get("services", {})),
                    "types_changed": len(diff.get("types", {})),
                }
            }
        except Exception as e:
            return {
                "ok": False,
                "error": str(e),
                "error_type": type(e).__name__
            }

    # Helper methods

    def _extract_frame_hints(self, source: str, ir: Dict) -> List[Dict[str, str]]:
        """Extract frame hints from comments and IR."""
        hints = []

        # Parse # frame: name: type comments
        for line in source.split('\n'):
            line = line.strip()
            if line.startswith('# frame:'):
                parts = line[8:].strip().split(':')
                if len(parts) >= 1:
                    name = parts[0].strip()
                    type_hint = parts[1].strip() if len(parts) > 1 else "any"
                    hints.append({
                        "name": name,
                        "type": type_hint,
                        "source": "comment"
                    })

        return hints

    def _get_repair_steps(self, diagnostic: Optional[Dict]) -> List[str]:
        """Generate repair steps from diagnostic."""
        if not diagnostic:
            return ["Check AINL syntax", "Run ainl_validate with strict=true"]

        steps = []
        kind = diagnostic.get("kind", "")
        msg = diagnostic.get("message", "")

        if "unknown_adapter" in kind.lower() or "unknown adapter" in msg.lower():
            steps.append("Run ainl_capabilities to see available adapters")
            steps.append("Check adapter spelling (case-sensitive)")

        if "http" in msg.lower():
            steps.append("Check HTTP adapter syntax: R http.GET url ->result")
            steps.append("Don't use params= or timeout= (use positional args)")

        if not steps:
            suggested_fix = diagnostic.get("suggested_fix", "")
            if suggested_fix:
                steps.append(suggested_fix)
            else:
                steps.append("Fix the error and re-validate")

        return steps


def get_ainl_resources() -> Dict[str, str]:
    """Get AINL MCP resource content."""

    resources = {
        "ainl://authoring-cheatsheet": """# AINL Authoring Cheatsheet

## Golden Path
1. ainl_validate (strict=true) after every edit
2. Fix using primary_diagnostic and agent_repair_steps
3. ainl_compile to get IR + frame_hints
4. ainl_run with adapters parameter

## Common Patterns

### HTTP GET
R http.GET "https://api.example.com/data" ->result

### HTTP GET with query params (in URL)
R http.GET "https://api.example.com/users?id=123&type=active" ->result

### HTTP GET with timeout
R http.GET "https://api.example.com/data" {} 30 ->result

### Core operations
R core.ADD 2 3 ->sum
R core.GET object "key" ->value
R core.LEN array ->count

### Conditions (compact syntax)
if var == "value":
  # then block
if var > 10:
  # then block

## Critical Rules

❌ DON'T use params= or timeout= on R http lines (not supported)
❌ DON'T use inline {...} dict literals (pass via frame)
✅ DO use positional args for HTTP: url [headers] [timeout_s]
✅ DO pass dicts via frame parameter in ainl_run
✅ DO use core.GET with object first: R core.GET obj "key"

## See Also
- ainl_capabilities: List available adapters
- ainl://adapter-manifest: Full adapter reference
""",

        "ainl://adapter-manifest": """# AINL Adapter Manifest

Run `ainl_capabilities` for the full programmatic list.

## Core Adapters

### core
Built-in operations (always available)
- Arithmetic: ADD, SUB, MUL, DIV, IDIV
- Comparison: EQ, NEQ, GT, LT, GTE, LTE
- String: CONCAT, SPLIT, TRIM, LOWER, UPPER
- Data: GET, PARSE, STRINGIFY, LEN, KEYS, VALUES
- Type: STR, INT, FLOAT, BOOL
- Time: NOW, ISO, ISO_TS

### http
HTTP requests
- GET, POST, PUT, DELETE, PATCH
- Syntax: R http.GET url [headers] [timeout_s] ->result

### sqlite
SQLite database operations
- QUERY, EXECUTE

## Enable in ainl_run

adapters: {
  enable: ["http", "sqlite", "cache"],
  http: {allow_hosts: [...], timeout_s: 30},
  sqlite: {db_path: "/path/to/db.sqlite"}
}
""",

        "ainl://impact-checklist": """# Impact Checklist

Before running AINL workflows:

1. ✅ Validate: ainl_validate with strict=true
2. ✅ Compile: ainl_compile to get IR
3. ✅ Security: ainl_security_report for risk analysis
4. ✅ Diff: ainl_ir_diff when modifying existing workflows
5. ✅ Test: ainl_run with test data first
6. ✅ Limits: Set appropriate max_adapter_calls limits
7. ✅ Adapters: Only enable needed adapters

## Adapter Risk Matrix

- http/web: Network egress, use allow_hosts
- fs: File system access, use sandbox root
- sqlite: Database mutations, test first
- llm: LLM calls, requires config + costs
""",

        "ainl://run-readiness": """# Run Readiness Guide

Before executing AINL workflows:

## Validation Chain
1. ainl_validate (strict=true)
2. ainl_compile (get IR + frame_hints)
3. ainl_security_report (check adapters)
4. ainl_run (with appropriate adapters)

## Adapter Configuration

Always specify which adapters to enable:

```javascript
ainl_run({
  source: "...",
  adapters: {
    enable: ["http"],  // Only enable what you need
    http: {
      allow_hosts: ["api.example.com"],  // Allowlist
      timeout_s: 30
    }
  }
})
```

## Frame Hints

Check frame_hints from ainl_compile:
- Tells you what variables workflow expects
- Pass via frame parameter in ainl_run

## Limits

Set conservative limits:
- max_steps: 500000 (default)
- max_adapter_calls: 50000 (default)
- Adjust based on workflow complexity
"""
    }

    return resources


# Export interface for other modules
__all__ = ['AINLTools', 'get_ainl_resources', '_HAS_AINL']
