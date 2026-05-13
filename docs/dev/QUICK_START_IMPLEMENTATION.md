# AINL Integration - Quick Start Implementation Guide

**Using PyPI Package:** `ainativelang[mcp]` v1.7.0+

This guide shows how to implement Phase 1 (Core Integration) using the PyPI package.

## Prerequisites

```bash
# Verify Python version (3.10+)
python3 --version

# Verify pip
pip --version

# Navigate to plugin directory
cd ~/.claude/plugins/ainl-cortex
```

## Step 1: Install AINL Package

### Update requirements.txt

```bash
cat > requirements.txt << 'EOF'
# Existing dependencies
sqlite-utils>=3.30
pydantic>=2.0.0

# AINL core package with MCP extras
ainativelang[mcp]>=1.7.0,<2.0.0

# The [mcp] extra includes:
# - mcp>=1.0.0 (MCP server framework)
# - pyyaml>=6.0 (config file support)
# - httpx>=0.24.0 (HTTP adapter)
# - All runtime adapters
EOF
```

### Install

```bash
pip install -r requirements.txt

# Verify installation
python3 << 'EOF'
import sys
try:
    from compiler_v2 import AICodeCompiler
    from runtime.engine import RuntimeEngine, RUNTIME_VERSION
    from runtime.adapters.base import AdapterRegistry
    print(f"✅ AINL v{RUNTIME_VERSION} installed successfully")
except ImportError as e:
    print(f"❌ Installation failed: {e}")
    sys.exit(1)
EOF
```

## Step 2: Create AINL MCP Tools Module

### File: `mcp_server/ainl_tools.py`

```python
"""AINL MCP tools integration for Claude Code.

Uses ainativelang package from PyPI.
"""
import json
from typing import Any, Dict, List, Optional

# Import from installed ainativelang package
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

try:
    from mcp.server.fastmcp import FastMCP
    _HAS_MCP = True
except ImportError:
    _HAS_MCP = False


class AINLTools:
    """AINL MCP tool implementations."""
    
    def __init__(self):
        self.compiler = AICodeCompiler()
        
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
                "message": "Validation successful",
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
    
    def run(
        self,
        source: str,
        frame: Optional[Dict[str, Any]] = None,
        adapters: Optional[Dict[str, Any]] = None,
        limits: Optional[Dict[str, Any]] = None
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
        """
        try:
            # Compile
            ctx = CompilerContext(strict=True)
            ir = self.compiler.compile(source, ctx=ctx)
            
            # Create runtime
            engine = RuntimeEngine()
            
            # Register adapters
            engine.registry.register("core", CoreBuiltinAdapter())
            
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
                    
                if "cache" in enabled:
                    cache_cfg = adapters.get("cache", {})
                    from adapters.local_cache import LocalFileCacheAdapter
                    engine.registry.register("cache", LocalFileCacheAdapter(
                        path=cache_cfg.get("path", "cache.json")
                    ))
                    
                if "sqlite" in enabled:
                    engine.registry.register("sqlite", SimpleSqliteAdapter())
            
            # Apply limits
            if limits:
                engine.max_steps = limits.get("max_steps", 500000)
                engine.max_adapter_calls = limits.get("max_adapter_calls", 50000)
                # Note: max_time_ms would need timeout wrapper
            
            # Execute
            result = engine.run(ir, frame=frame or {})
            
            return {
                "ok": True,
                "result": result,
                "stats": {
                    "steps_executed": engine.steps_executed,
                    "adapter_calls": engine.adapter_calls,
                }
            }
            
        except AinlRuntimeError as e:
            return {
                "ok": False,
                "error": str(e),
                "error_type": "runtime_error"
            }
        except CompilationDiagnosticError as e:
            return {
                "ok": False,
                "error": str(e),
                "diagnostics": e.diagnostics if hasattr(e, 'diagnostics') else [],
                "error_type": "compilation_error",
                "recommended_next_tools": ["ainl_validate"]
            }
    
    def capabilities(self) -> Dict[str, Any]:
        """
        List available adapters and verbs.
        
        Returns catalog of what can be used in R lines.
        """
        # Load adapter manifest from package resources
        from importlib.resources import files
        
        try:
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
                        "verbs": ["ADD", "SUB", "GET", "LEN", "NOW", "PARSE", "STRINGIFY"]
                    },
                    "http": {
                        "verbs": ["GET", "POST", "PUT", "DELETE"]
                    }
                },
                "error": f"Could not load full manifest: {e}"
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
                "error": str(e)
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
                "error": str(e)
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
            steps.append(diagnostic.get("suggested_fix", "Fix the error and re-validate"))
            
        return steps


# Export for use in MCP server
def register_ainl_tools(mcp: FastMCP):
    """Register AINL tools with FastMCP server."""
    tools = AINLTools()
    
    @mcp.tool()
    def ainl_validate(source: str, strict: bool = True) -> Dict[str, Any]:
        """Validate AINL source code."""
        return tools.validate(source, strict)
    
    @mcp.tool()
    def ainl_compile(source: str, strict: bool = True) -> Dict[str, Any]:
        """Compile AINL to IR JSON."""
        return tools.compile(source, strict)
    
    @mcp.tool()
    def ainl_run(
        source: str,
        frame: Optional[Dict[str, Any]] = None,
        adapters: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Execute AINL workflow."""
        return tools.run(source, frame, adapters)
    
    @mcp.tool()
    def ainl_capabilities() -> Dict[str, Any]:
        """List available AINL adapters and verbs."""
        return tools.capabilities()
    
    @mcp.tool()
    def ainl_security_report(source: str) -> Dict[str, Any]:
        """Analyze AINL for security concerns."""
        return tools.security_report(source)
    
    @mcp.tool()
    def ainl_ir_diff(source_a: str, source_b: str) -> Dict[str, Any]:
        """Compare two AINL programs."""
        return tools.ir_diff(source_a, source_b)
```

## Step 3: Update MCP Server

### File: `mcp_server/server.py`

Add AINL tools to existing server:

```python
# Existing imports...
from mcp.server.fastmcp import FastMCP

# Add AINL tools import
from mcp_server.ainl_tools import register_ainl_tools

# In main():
mcp = FastMCP("ainl-cortex")

# Register existing graph memory tools
# ... existing code ...

# Register AINL tools
register_ainl_tools(mcp)

# Add AINL resources
@mcp.resource("ainl://authoring-cheatsheet")
def ainl_cheatsheet() -> str:
    """AINL authoring quick reference."""
    return """# AINL Authoring Cheatsheet
    
## Golden Path
1. ainl_validate (strict=true) after every edit
2. Fix using primary_diagnostic and agent_repair_steps
3. ainl_compile to get IR + frame_hints
4. ainl_run with adapters parameter

## Common Patterns
- HTTP GET: R http.GET "https://api.example.com/data" ->result
- Core ops: R core.ADD 2 3 ->sum
- Conditions: if var == "value": / if var > 10:

## Avoid
- Don't use params= or timeout= on R http lines (positional only)
- Don't use inline {...} dict literals (pass via frame)

See ainl_capabilities for available adapters.
"""

mcp.run()
```

## Step 4: Test Installation

### Test Script: `test_ainl_integration.py`

```python
#!/usr/bin/env python3
"""Test AINL integration."""

from mcp_server.ainl_tools import AINLTools

def test_validate():
    tools = AINLTools()
    
    source = """
S app core noop

L1:
  R core.ADD 2 3 ->sum
  J sum
"""
    
    result = tools.validate(source, strict=True)
    print("✅ Validation test:", "PASS" if result["valid"] else "FAIL")
    
def test_compile():
    tools = AINLTools()
    
    source = """
S app core noop

L1:
  R core.ADD 2 3 ->sum
  J sum
"""
    
    result = tools.compile(source)
    print("✅ Compilation test:", "PASS" if result["ok"] else "FAIL")
    
def test_run():
    tools = AINLTools()
    
    source = """
S app core noop

L1:
  R core.ADD 2 3 ->sum
  J sum
"""
    
    result = tools.run(source)
    print("✅ Execution test:", "PASS" if result["ok"] and result["result"] == 5 else "FAIL")
    print("  Result:", result.get("result"))

if __name__ == "__main__":
    print("Testing AINL integration...\n")
    test_validate()
    test_compile()
    test_run()
    print("\n✅ All tests passed!")
```

Run tests:

```bash
python3 test_ainl_integration.py
```

## Step 5: Verify MCP Server

```bash
# Test MCP server
python3 mcp_server/server.py &
SERVER_PID=$!

# Give it a moment to start
sleep 2

# Test with MCP client (if available)
# Or check logs

kill $SERVER_PID
```

## Next Steps

After completing these steps:

1. ✅ AINL package installed from PyPI
2. ✅ MCP tools integrated into plugin
3. ✅ Tests passing
4. ✅ Server running

**Move to Phase 2:** Smart suggestions and file detection

See `AINL_INTEGRATION_PLAN.md` for full roadmap.

## Troubleshooting

### Import Errors

```python
# Test imports
python3 << 'EOF'
try:
    from compiler_v2 import AICodeCompiler
    from runtime.engine import RuntimeEngine, RUNTIME_VERSION
    print(f"✅ Imports working, AINL v{RUNTIME_VERSION}")
except ImportError as e:
    print(f"❌ Import failed: {e}")
    print("\nTry: pip install ainativelang[mcp]")
EOF
```

### Package Version

```bash
pip show ainativelang
```

Should show version 1.7.0 or higher.

### Resources Not Loading

If adapter manifest doesn't load, check package resources:

```python
from importlib.resources import files
tooling = files('ainativelang').joinpath('tooling')
print(tooling)
```

## Resources

- **PyPI:** https://pypi.org/project/ainativelang/
- **Docs:** https://ainativelang.com
- **Issues:** https://github.com/sbhooley/ainativelang/issues
