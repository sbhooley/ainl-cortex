"""AINL MCP tools integration for Claude Code.

Uses ainativelang package from PyPI (v1.8.0+).
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
    # v1.8.0+: authoring wizard and adapter contracts
    from tooling.ainl_get_started import (
        get_started as _ainl_get_started_wizard,
        step_examples as _ainl_step_examples,
        adapter_contract as _ainl_adapter_contract_payload,
    )
    _HAS_AINL = True
except ImportError:
    _HAS_AINL = False
    print("Warning: ainativelang package not installed. AINL tools will not be available.")
    print("Install with: pip install ainativelang[mcp]>=1.8.0")


try:
    from adapters.local_cache import LocalFileCacheAdapter
    _HAS_CACHE_ADAPTER = True
except ImportError:
    _HAS_CACHE_ADAPTER = False


def _make_compiler_context(strict: bool):
    """Build a CompilerContext that works across the ainativelang API shift.

    ainativelang <1.7 accepted ``CompilerContext(strict=bool)``; 1.7+ removed
    the kwarg and moved strictness onto the compiler instance via
    ``AICodeCompiler.strict_mode``. We keep the legacy call path inside a
    try/except so this module survives a hypothetical future revert without
    behavior change.
    """
    try:
        return CompilerContext(strict=strict)  # type: ignore[call-arg]
    except TypeError:
        return CompilerContext()


def _diag_to_dict(diag: Any) -> Dict[str, Any]:
    """Normalize a Diagnostic (1.7+ dataclass, older dict, or repr-only) into
    a JSON-serializable dict.

    Older ainativelang produced plain dicts on ``CompilationDiagnosticError``;
    1.7+ ships a ``Diagnostic`` dataclass exposing ``to_dict()``. Both shapes
    must be handled because the error envelope ends up in MCP tool JSON
    responses (which must be serializable) and feeds ``_get_repair_steps``
    (which calls ``.get()``).
    """
    if diag is None:
        return {}
    if isinstance(diag, dict):
        return diag
    to_dict = getattr(diag, "to_dict", None)
    if callable(to_dict):
        try:
            return to_dict()
        except Exception:
            pass
    try:
        import dataclasses

        if dataclasses.is_dataclass(diag):
            return dataclasses.asdict(diag)
    except Exception:
        pass
    return {
        "kind": getattr(diag, "kind", type(diag).__name__),
        "message": getattr(diag, "message", str(diag)),
    }


def _diags_to_list(diags: Any) -> List[Dict[str, Any]]:
    """Normalize an iterable of Diagnostics into a list of dicts."""
    if not diags:
        return []
    return [_diag_to_dict(d) for d in diags]


def _graph_diff(ir_a, ir_b, *, labels: Optional[List[str]] = None):
    """Call graph_diff across the labels=/label_id= rename in 1.7+.

    The new signature accepts a single ``label_id``; we collapse a list to
    its first element for parity, and fall back to the legacy plural
    keyword if available.
    """
    label_id = labels[0] if labels else None
    try:
        return graph_diff(ir_a, ir_b, label_id=label_id)
    except TypeError:
        return graph_diff(ir_a, ir_b, labels=labels)  # type: ignore[call-arg]


def _make_http_adapter(http_cfg: Dict[str, Any]):
    """Construct a SimpleHttpAdapter across the timeout-kwarg rename.

    1.7+ renamed ``timeout_s`` to ``default_timeout_s``. We accept both
    spellings on the input config (``timeout_s`` wins for back-compat with
    existing AINL workflow files) and try each kwarg in turn.
    """
    allow_hosts = http_cfg.get("allow_hosts")
    timeout = http_cfg.get("timeout_s", http_cfg.get("default_timeout_s", 30))
    try:
        return SimpleHttpAdapter(
            allow_hosts=allow_hosts,
            default_timeout_s=timeout,
        )
    except TypeError:
        return SimpleHttpAdapter(  # type: ignore[call-arg]
            allow_hosts=allow_hosts,
            timeout_s=timeout,
        )


def _make_engine(ir, *, registry, limits: Optional[Dict[str, Any]] = None):
    """Construct a RuntimeEngine across the 1.6/1.7+ API shift.

    1.7+ requires ``ir`` (and accepts ``adapters`` / ``limits``) at
    construction time and removed the ``engine.registry`` mutable accessor.
    Older versions allowed ``RuntimeEngine()`` followed by
    ``engine.registry.register(...)`` — we keep that path as a fallback.
    """
    try:
        return RuntimeEngine(ir, adapters=registry, limits=limits or None)
    except TypeError:
        engine = RuntimeEngine()  # legacy
        if hasattr(engine, "registry") and registry is not None:
            for name, adapter in getattr(registry, "adapters", {}).items():
                engine.registry.register(name, adapter)
        if limits:
            if hasattr(engine, "max_steps"):
                engine.max_steps = limits.get("max_steps", 500000)
            if hasattr(engine, "max_adapter_calls"):
                engine.max_adapter_calls = limits.get("max_adapter_calls", 50000)
        return engine


def _engine_run(engine, *, label: Optional[str], frame: Dict[str, Any]):
    """Run an engine across the 1.6/1.7+ API shift.

    1.7+ exposes ``run_label(label_id, frame=...)``; the older API used
    ``engine.run(ir, frame=..., label=...)``.
    """
    if hasattr(engine, "run_label"):
        target_label = label or engine.default_entry_label()
        return engine.run_label(target_label, frame=frame)
    # legacy: requires the original IR; engine has no public IR accessor in
    # the new API, so this path only fires when run_label is missing.
    return engine.run(frame=frame, label=label)  # type: ignore[call-arg]


def _compile(compiler, source: str, *, strict: bool):
    """Compile ``source`` with the given strict flag, regardless of upstream
    ainativelang version.

    The 1.7 release renamed the keyword argument from ``ctx=`` to
    ``context=`` and dropped strictness from CompilerContext, so we set
    ``compiler.strict_mode`` (when supported) and fall back through both
    keyword spellings. Any explicit ``ctx=``/``context=`` call site can be
    replaced by a single call to this helper.
    """
    if hasattr(compiler, "strict_mode"):
        compiler.strict_mode = strict
    ctx = _make_compiler_context(strict)
    try:
        return compiler.compile(source, context=ctx)
    except TypeError:
        return compiler.compile(source, ctx=ctx)


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

        # Initialize improvement proposal store (closed-loop validation)
        try:
            from .improvement_proposals import ImprovementProposalStore
        except ImportError:
            from improvement_proposals import ImprovementProposalStore
        if memory_db_path:
            self.proposal_store = ImprovementProposalStore(
                memory_db_path.parent / "ainl_proposals.db"
            )
        else:
            self.proposal_store = None

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
            ir = _compile(self.compiler, source, strict=strict)

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
            diagnostics = _diags_to_list(getattr(e, 'diagnostics', None))
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
            ir = _compile(self.compiler, source, strict=strict)

            # 1.7+ no longer raises CompilationDiagnosticError for input that
            # produced zero labels (e.g. "INVALID AINL" — a bare token line is
            # silently absorbed). In strict mode, treat empty/no-graph IR as
            # a compile failure so callers see ``ok: false`` instead of valid
            # garbage.
            if strict and not ir.get("labels"):
                return {
                    "ok": False,
                    "error": "Compiled IR has no labels (no graph defined). Source may be malformed.",
                    "diagnostics": _diags_to_list(ir.get("diagnostics") or ir.get("structured_diagnostics")),
                    "error_type": "empty_graph",
                    "recommended_next_tools": ["ainl_validate"],
                }

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
                "diagnostics": _diags_to_list(getattr(e, 'diagnostics', None)),
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
            ir = _compile(self.compiler, source, strict=True)

            registry = AdapterRegistry()
            registry.register("core", CoreBuiltinAdapter())

            if adapters:
                enabled = adapters.get("enable", [])

                if "http" in enabled:
                    http_cfg = adapters.get("http", {})
                    registry.register("http", _make_http_adapter(http_cfg))

                if "fs" in enabled:
                    fs_cfg = adapters.get("fs", {})
                    registry.register("fs", SandboxedFileSystemAdapter(
                        root=fs_cfg.get("root", "/tmp"),
                        allow_extensions=fs_cfg.get("allow_extensions")
                    ))

                if "cache" in enabled and _HAS_CACHE_ADAPTER:
                    cache_cfg = adapters.get("cache", {})
                    registry.register("cache", LocalFileCacheAdapter(
                        path=cache_cfg.get("path", "cache.json")
                    ))

                if "sqlite" in enabled:
                    sqlite_cfg = adapters.get("sqlite", {})
                    registry.register("sqlite", SimpleSqliteAdapter(
                        db_path=sqlite_cfg.get("db_path")
                    ))

            engine = _make_engine(ir, registry=registry, limits=limits)
            result = _engine_run(engine, label=label, frame=frame or {})

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
                "diagnostics": _diags_to_list(getattr(e, 'diagnostics', None)),
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
            ir = _compile(self.compiler, source, strict=False)

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
            ir_a = _compile(self.compiler, source_a, strict=False)
            ir_b = _compile(self.compiler, source_b, strict=False)

            diff = _graph_diff(ir_a, ir_b, labels=labels)

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

    def get_started(
        self,
        goal: Optional[str] = None,
        detail_level: str = "standard",
        existing_source: Optional[str] = None,
        path: Optional[str] = None,
        diagnostics: Optional[Dict] = None,
        capabilities_snapshot: Optional[Dict] = None,
        adapter_contracts_snapshot: Optional[Dict] = None,
        wizard_state_json: Optional[Dict] = None,
        current_step: Optional[str] = None,
        request_examples_for: Optional[str] = None,
        example_count: int = 3,
    ) -> Dict[str, Any]:
        """
        Start AINL authoring from a plain-language goal (v1.8.0+).

        Pass wizard_state_json from a prior response to resume from the last
        checkpoint. Use current_step or request_examples_for to fetch step-local
        examples without advancing wizard state.
        """
        try:
            if current_step or request_examples_for:
                return _ainl_step_examples(
                    current_step=current_step or request_examples_for or "",
                    request_examples_for=request_examples_for,
                    example_count=example_count,
                )
            if not goal or not str(goal).strip():
                return {
                    "ok": False,
                    "error": "missing required argument: goal",
                    "next_step": "Call ainl_get_started with a plain-language goal, e.g. {'goal': 'Monitor an API and alert on failure.'}",
                }
            return _ainl_get_started_wizard(
                goal,
                detail_level=detail_level,
                existing_source=existing_source,
                path=path,
                diagnostics=diagnostics,
                capabilities_snapshot=capabilities_snapshot,
                adapter_contracts_snapshot=adapter_contracts_snapshot,
                wizard_state_json=wizard_state_json,
            )
        except Exception as e:
            return {"ok": False, "error": str(e), "error_type": type(e).__name__}

    def step_examples(
        self,
        current_step: str = "",
        request_examples_for: Optional[str] = None,
        example_count: int = 3,
        include_corpus_references: bool = True,
    ) -> Dict[str, Any]:
        """
        Return code examples for a wizard step or adapter topic (v1.8.0+).

        Use this after ainl_get_started when you want examples for a specific
        adapter (fs, browser, http, cache, etc.) without advancing wizard state.
        """
        try:
            result = _ainl_step_examples(
                current_step=current_step,
                request_examples_for=request_examples_for,
                example_count=example_count,
                include_corpus_references=include_corpus_references,
            )
            result.setdefault("ok", True)
            result.setdefault("recommended_next_tools", ["ainl_validate", "ainl_compile"])
            return result
        except Exception as e:
            return {"ok": False, "error": str(e), "error_type": type(e).__name__}

    def adapter_contract(
        self,
        adapter: str,
        detail_level: str = "standard",
    ) -> Dict[str, Any]:
        """
        Return the argument and runtime contract for an AINL adapter (v1.8.0+).

        Call this after ainl_get_started or ainl_capabilities and before writing
        adapter-specific AINL. Covers http, browser, fs, cache, core, sqlite, and
        composite choices like http_or_browser.
        """
        try:
            if not adapter or not str(adapter).strip():
                return {
                    "ok": False,
                    "error": "missing required argument: adapter",
                    "next_step": "Call ainl_adapter_contract with an adapter name, e.g. {'adapter': 'http'}",
                }
            return _ainl_adapter_contract_payload(adapter, detail_level=detail_level)
        except Exception as e:
            return {"ok": False, "error": str(e), "error_type": type(e).__name__}

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

    def _get_repair_steps(self, diagnostic: Optional[Any]) -> List[str]:
        """Generate repair steps from diagnostic.

        Accepts either a dict (legacy ainativelang) or a Diagnostic dataclass
        (1.7+); both are normalized via _diag_to_dict before introspection.
        """
        if not diagnostic:
            return ["Check AINL syntax", "Run ainl_validate with strict=true"]

        diagnostic = _diag_to_dict(diagnostic)
        steps = []
        kind = diagnostic.get("kind", "") or ""
        msg = diagnostic.get("message", "") or ""

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

    # ── Closed-loop validation (improvement proposals) ────────────────────────

    def propose_improvement(
        self,
        source: str,
        proposed_source: str,
        improvement_type: str,
        rationale: str,
    ) -> Dict[str, Any]:
        """
        Validate a proposed AINL improvement and store it if valid.

        Closed-loop: validate first, only persist if the proposed source
        compiles cleanly. Returns proposal_id on success so the user can
        accept or reject via ainl_accept_proposal.
        """
        if not self.proposal_store:
            return {"ok": False, "error": "Proposal store not available"}

        # Validate proposed source before storing
        validation = self.validate(proposed_source, strict=True)
        if not validation.get("valid"):
            return {
                "ok": False,
                "validation_passed": False,
                "errors": validation.get("errors", []),
                "message": "Proposed improvement did not pass validation — fix errors before proposing.",
            }

        proposal_id = self.proposal_store.propose_improvement(
            original_source=source,
            proposed_source=proposed_source,
            improvement_type=improvement_type,
            rationale=rationale,
            validation_result=validation,
        )

        confidence = self.proposal_store.get_confidence_adjustment(improvement_type)
        return {
            "ok": True,
            "validation_passed": True,
            "proposal_id": proposal_id,
            "confidence": confidence,
            "message": (
                f"Improvement validated and stored (id={proposal_id[:8]}…). "
                "Present it to the user and call ainl_accept_proposal with their answer."
            ),
        }

    def accept_proposal(self, proposal_id: str, accepted: bool) -> Dict[str, Any]:
        """Record whether the user accepted or rejected a proposed improvement."""
        if not self.proposal_store:
            return {"ok": False, "error": "Proposal store not available"}
        self.proposal_store.mark_accepted(proposal_id, accepted)
        return {
            "ok": True,
            "proposal_id": proposal_id,
            "accepted": accepted,
            "message": "Outcome recorded. Historical acceptance rate will influence future proposal confidence.",
        }

    def list_proposals(self, limit: int = 10) -> Dict[str, Any]:
        """List recent improvement proposals and their acceptance status."""
        if not self.proposal_store:
            return {"ok": False, "error": "Proposal store not available"}
        proposals = self.proposal_store.get_recent_proposals(limit=limit)
        pending = [p for p in proposals if p.accepted is None and p.validation_passed]
        reviewed = [p for p in proposals if p.accepted is not None]
        success_rate = self.proposal_store.get_success_rate()
        return {
            "ok": True,
            "pending_count": len(pending),
            "pending": [
                {
                    "id": p.id,
                    "improvement_type": p.improvement_type,
                    "rationale": p.rationale,
                    "created_at": p.created_at,
                }
                for p in pending
            ],
            "reviewed_count": len(reviewed),
            "acceptance_rate": success_rate,
        }


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
