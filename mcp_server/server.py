#!/usr/bin/env python3
"""
AINL Graph Memory MCP Server

Properly implemented using the official MCP SDK.
Exposes graph memory tools for Claude Code integration.
"""

import os
import sys
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
import asyncio

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

# Logs follow the active plugin install (user cache or dev copy), not a hardcoded path.
def _plugin_root() -> Path:
    env = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        v = int(raw)
        return v if v > 0 else default
    except ValueError:
        return default


log_dir = _plugin_root() / "logs"
log_dir.mkdir(parents=True, exist_ok=True)

# Bound the on-disk MCP-server log identically to hooks.log. Defaults: 5 MB
# per file × 3 backups. Override via AINL_CORTEX_MCP_LOG_MAX_BYTES /
# AINL_CORTEX_MCP_LOG_BACKUPS.
from logging.handlers import RotatingFileHandler  # noqa: E402

_MCP_LOG_MAX_BYTES = _env_int("AINL_CORTEX_MCP_LOG_MAX_BYTES", 5 * 1024 * 1024)
_MCP_LOG_BACKUPS = _env_int("AINL_CORTEX_MCP_LOG_BACKUPS", 3)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        RotatingFileHandler(
            log_dir / "mcp_server.log",
            maxBytes=_MCP_LOG_MAX_BYTES,
            backupCount=_MCP_LOG_BACKUPS,
            encoding="utf-8",
        ),
        logging.StreamHandler(sys.stderr)
    ]
)

logger = logging.getLogger(__name__)

# Import our modules
try:
    from .graph_store import get_graph_store
    from .node_types import (
        create_episode_node, create_semantic_node, create_procedural_node,
        create_persona_node, create_failure_node, create_edge,
        NodeType, EdgeType
    )
    from .retrieval import MemoryRetrieval, RetrievalContext
    from .persona_engine import PersonaEvolutionEngine
    from .extractor import PatternExtractor, canonicalize_tool_sequence
    from .ainl_tools import AINLTools
    from .a2a_tools import A2ATools
    from .goal_tracker import GoalTracker
except ImportError:
    # Fallback for when run as script
    sys.path.insert(0, str(Path(__file__).parent))
    from graph_store import get_graph_store
    from node_types import (
        create_episode_node, create_semantic_node, create_procedural_node,
        create_persona_node, create_failure_node, create_edge,
        NodeType, EdgeType
    )
    from retrieval import MemoryRetrieval, RetrievalContext
    from persona_engine import PersonaEvolutionEngine
    from extractor import PatternExtractor, canonicalize_tool_sequence
    from ainl_tools import AINLTools
    from a2a_tools import A2ATools
    from goal_tracker import GoalTracker


class AINLGraphMemoryServer:
    """AINL Graph Memory MCP Server"""

    def __init__(self):
        self.db_path = self._get_db_path()
        self.store = get_graph_store(self.db_path)
        self.retrieval = MemoryRetrieval(self.store, cache_dir=self.db_path.parent)
        self.persona_engine = PersonaEvolutionEngine()
        self.extractor = PatternExtractor()

        # Initialize AINL tools
        try:
            self.ainl_tools = AINLTools(memory_db_path=self.db_path)
            logger.info("AINL tools initialized successfully")
        except ImportError as e:
            logger.warning(f"AINL tools not available: {e}")
            self.ainl_tools = None

        # Initialize A2A tools
        plugin_root = _plugin_root()
        try:
            import json as _json
            config = _json.loads((plugin_root / "config.json").read_text())
        except Exception:
            config = {}
        # Cached on the server so list_tools / call_tool can gate A2A tool
        # advertisement and dispatch by config.a2a.enabled without re-reading
        # config.json on every MCP call.
        self.config = config
        self._a2a_enabled = bool(config.get("a2a", {}).get("enabled", False))
        project_id = self._compute_project_hash(Path.cwd())
        self.a2a_tools = A2ATools(plugin_root, self.store, project_id, config)
        logger.info(
            "A2A tools initialized successfully (advertised to MCP: %s)",
            self._a2a_enabled,
        )

        self.goal_tracker = GoalTracker(self.store, project_id)
        logger.info("Goal tracker initialized")

        logger.info(f"AINL Graph Memory Server initialized with DB: {self.db_path}")

    def _get_db_path(self) -> Path:
        """Get database path for the active project (per-repo by default).

        Uses the shared resolver in hooks/shared/project_id.py so the MCP
        server, hooks, and standalone scripts all agree on which bucket the
        current cwd belongs to."""
        cwd = Path.cwd()
        project_hash = self._compute_project_hash(cwd)
        memory_dir = Path.home() / ".claude" / "projects" / project_hash / "graph_memory"
        memory_dir.mkdir(parents=True, exist_ok=True)
        return memory_dir / "ainl_memory.db"

    def _compute_project_hash(self, cwd: Path) -> str:
        """Resolve the project ID via the shared per-repo resolver.

        Kept as an instance method for back-compat with any caller that holds
        a reference to it; it now delegates to hooks/shared/project_id.py
        rather than recomputing the legacy global hash inline."""
        # Lazy import: keep mcp_server importable from contexts where the
        # hooks/ tree may not be on sys.path yet.
        try:
            from project_id import get_project_id  # type: ignore
        except ImportError:
            sys.path.insert(0, str(_plugin_root() / "hooks"))
            from shared.project_id import get_project_id  # type: ignore
        return get_project_id(cwd)


# Create server instance
server = Server("ainl-cortex")
memory_server = AINLGraphMemoryServer()


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List available MCP tools.

    A2A tools (``a2a_*``) are advertised only when ``config.a2a.enabled`` is
    true; otherwise they are filtered out so the model does not see — and
    cannot accidentally call — features that are intentionally disabled.
    """
    tools: list[Tool] = [
        Tool(
            name="memory_store_episode",
            description="Store a coding session episode with tool calls and outcomes",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string", "description": "Project identifier"},
                    "task_description": {"type": "string", "description": "Task description"},
                    "tool_calls": {"type": "array", "items": {"type": "string"}, "description": "List of tool calls"},
                    "files_touched": {"type": "array", "items": {"type": "string"}, "description": "Files modified"},
                    "outcome": {"type": "string", "enum": ["success", "failure", "partial"], "description": "Outcome"}
                },
                "required": ["project_id", "task_description", "tool_calls", "files_touched", "outcome"]
            }
        ),
        Tool(
            name="memory_store_semantic",
            description="Store a semantic fact with confidence score",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string", "description": "Project identifier"},
                    "fact": {"type": "string", "description": "Semantic fact to store"},
                    "confidence": {"type": "number", "description": "Confidence score 0-1"},
                    "source_turn_id": {"type": "string", "description": "Optional source turn ID"}
                },
                "required": ["project_id", "fact", "confidence"]
            }
        ),
        Tool(
            name="memory_store_failure",
            description="Store a failure node for learning from errors",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string", "description": "Project identifier"},
                    "error_type": {"type": "string", "description": "Type of error"},
                    "tool": {"type": "string", "description": "Tool that failed"},
                    "error_message": {"type": "string", "description": "Error message"}
                },
                "required": ["project_id", "error_type", "tool", "error_message"]
            }
        ),
        Tool(
            name="memory_promote_pattern",
            description="Promote a successful workflow pattern for reuse",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string", "description": "Project identifier"},
                    "pattern_name": {"type": "string", "description": "Pattern name"},
                    "trigger": {"type": "string", "description": "When to use this pattern"},
                    "tool_sequence": {"type": "array", "items": {"type": "string"}, "description": "Tool sequence"},
                    "evidence_ids": {"type": "array", "items": {"type": "string"}, "description": "Evidence episode IDs"}
                },
                "required": ["project_id", "pattern_name", "trigger", "tool_sequence", "evidence_ids"]
            }
        ),
        Tool(
            name="memory_recall_context",
            description="Retrieve relevant memory context for current task",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string", "description": "Project identifier"},
                    "current_task": {"type": "string", "description": "Current task description"},
                    "files_mentioned": {"type": "array", "items": {"type": "string"}, "description": "Files mentioned"},
                    "max_nodes": {"type": "number", "description": "Maximum nodes to return", "default": 50}
                },
                "required": ["project_id"]
            }
        ),
        Tool(
            name="memory_expand_node",
            description="Fetch one graph memory node by id (drill-down for progressive disclosure)",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string", "description": "Project identifier"},
                    "node_id": {"type": "string", "description": "Graph node UUID"},
                },
                "required": ["project_id", "node_id"],
            },
        ),
        Tool(
            name="memory_search",
            description="Full-text search across graph memory",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "project_id": {"type": "string", "description": "Project identifier"},
                    "limit": {"type": "number", "description": "Max results", "default": 20}
                },
                "required": ["query", "project_id"]
            }
        ),
        Tool(
            name="memory_evolve_persona",
            description="Evolve persona traits from episode data",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string", "description": "Project identifier"},
                    "episode_data": {"type": "object", "description": "Episode data for analysis"}
                },
                "required": ["project_id", "episode_data"]
            }
        ),
        # AINL Tools
        Tool(
            name="ainl_validate",
            description="Validate AINL source code syntax and semantics",
            inputSchema={
                "type": "object",
                "properties": {
                    "source": {"type": "string", "description": "AINL source code"},
                    "strict": {"type": "boolean", "description": "Enable strict validation", "default": True},
                    "filename": {"type": "string", "description": "Filename for error messages", "default": "input.ainl"}
                },
                "required": ["source"]
            }
        ),
        Tool(
            name="ainl_compile",
            description="Compile AINL source to IR and get frame hints",
            inputSchema={
                "type": "object",
                "properties": {
                    "source": {"type": "string", "description": "AINL source code"},
                    "strict": {"type": "boolean", "description": "Enable strict mode", "default": True}
                },
                "required": ["source"]
            }
        ),
        Tool(
            name="ainl_run",
            description="Execute AINL workflow with specified frame and adapters",
            inputSchema={
                "type": "object",
                "properties": {
                    "source": {"type": "string", "description": "AINL source code"},
                    "frame": {"type": "object", "description": "Frame variables"},
                    "adapters": {"type": "object", "description": "Adapter configuration"},
                    "entry_label": {"type": "string", "description": "Entry point label"}
                },
                "required": ["source"]
            }
        ),
        Tool(
            name="ainl_capabilities",
            description="List available AINL adapters and their capabilities",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="ainl_security_report",
            description="Analyze AINL code for security risks",
            inputSchema={
                "type": "object",
                "properties": {
                    "source": {"type": "string", "description": "AINL source code"}
                },
                "required": ["source"]
            }
        ),
        Tool(
            name="ainl_ir_diff",
            description="Compare two AINL versions and show IR differences",
            inputSchema={
                "type": "object",
                "properties": {
                    "source_a": {"type": "string", "description": "First AINL source"},
                    "source_b": {"type": "string", "description": "Second AINL source"},
                    "label_a": {"type": "string", "description": "Label for first version", "default": "version_a"},
                    "label_b": {"type": "string", "description": "Label for second version", "default": "version_b"}
                },
                "required": ["source_a", "source_b"]
            }
        ),
        Tool(
            name="ainl_get_started",
            description="Start AINL authoring from a plain-language goal. First tool to call before writing unfamiliar AINL. Returns an intent-to-syntax guide and the next discovery checkpoint. Pass wizard_state_json from a prior response to resume.",
            inputSchema={
                "type": "object",
                "properties": {
                    "goal": {"type": "string", "description": "Plain-language description of what the workflow should do"},
                    "detail_level": {"type": "string", "enum": ["standard", "minimal", "verbose"], "default": "standard"},
                    "existing_source": {"type": "string", "description": "Existing AINL source to refine (optional)"},
                    "wizard_state_json": {"type": "object", "description": "State from a previous ainl_get_started response (optional, for continuity)"},
                    "current_step": {"type": "string", "description": "Fetch examples for this step without advancing wizard state"},
                    "request_examples_for": {"type": "string", "description": "Fetch examples for this adapter/topic (e.g. 'fs', 'http')"},
                    "example_count": {"type": "integer", "default": 3}
                },
                "required": []
            }
        ),
        Tool(
            name="ainl_step_examples",
            description="Return code examples for a specific wizard step or adapter topic. Use after ainl_get_started when you want adapter-specific snippets without advancing wizard state.",
            inputSchema={
                "type": "object",
                "properties": {
                    "current_step": {"type": "string", "description": "Current wizard step name (e.g. 'write_output')"},
                    "request_examples_for": {"type": "string", "description": "Adapter or topic to get examples for (e.g. 'fs', 'browser', 'http')"},
                    "example_count": {"type": "integer", "default": 3},
                    "include_corpus_references": {"type": "boolean", "default": True}
                },
                "required": []
            }
        ),
        Tool(
            name="ainl_adapter_contract",
            description="Return the argument and runtime contract for an AINL adapter. Call after ainl_get_started or ainl_capabilities, before writing adapter-specific AINL. Covers http, browser, fs, cache, core, sqlite, http_or_browser.",
            inputSchema={
                "type": "object",
                "properties": {
                    "adapter": {"type": "string", "description": "Adapter name (e.g. 'http', 'fs', 'browser', 'http_or_browser')"},
                    "detail_level": {"type": "string", "enum": ["standard", "minimal", "verbose"], "default": "standard"}
                },
                "required": ["adapter"]
            }
        ),
        # Closed-loop validation tools
        Tool(
            name="ainl_propose_improvement",
            description=(
                "Validate a proposed AINL workflow improvement and store it for user review. "
                "The proposed source is validated first — only stored if it compiles cleanly. "
                "Returns a proposal_id; present the diff to the user then call ainl_accept_proposal."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "source": {"type": "string", "description": "Original AINL source code"},
                    "proposed_source": {"type": "string", "description": "Proposed improved AINL source"},
                    "improvement_type": {
                        "type": "string",
                        "enum": ["optimize", "refactor", "fix", "enhance"],
                        "description": "Category of improvement"
                    },
                    "rationale": {"type": "string", "description": "Why this improvement is beneficial"}
                },
                "required": ["source", "proposed_source", "improvement_type", "rationale"]
            }
        ),
        Tool(
            name="ainl_accept_proposal",
            description="Record whether the user accepted or rejected an improvement proposal. Call after presenting the proposal diff to the user.",
            inputSchema={
                "type": "object",
                "properties": {
                    "proposal_id": {"type": "string", "description": "Proposal ID from ainl_propose_improvement"},
                    "accepted": {"type": "boolean", "description": "True if user accepted, false if rejected"}
                },
                "required": ["proposal_id", "accepted"]
            }
        ),
        Tool(
            name="ainl_list_proposals",
            description="List recent AINL improvement proposals. Shows pending (unreviewed) proposals and historical acceptance rate.",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {"type": "number", "description": "Max proposals to return", "default": 10}
                }
            }
        ),
        # A2A Tools
        Tool(
            name="a2a_send",
            description="Send a message to a registered A2A agent",
            inputSchema={
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "Agent name (must be registered)"},
                    "message": {"type": "string", "description": "Message text to send"},
                    "thread_id": {"type": "string", "description": "Optional thread ID for continuity"},
                    "urgency": {"type": "string", "enum": ["critical", "normal", "low"], "description": "Message urgency", "default": "normal"}
                },
                "required": ["to", "message"]
            }
        ),
        Tool(
            name="a2a_list_agents",
            description="List all registered A2A agents and their reachability status",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="a2a_register_agent",
            description="Register a new A2A agent by name and URL",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Unique agent name"},
                    "url": {"type": "string", "description": "Agent base URL (http:// or https://)"},
                    "description": {"type": "string", "description": "What this agent does"},
                    "capabilities": {"type": "array", "items": {"type": "string"}, "description": "List of capability tags"}
                },
                "required": ["name", "url", "description"]
            }
        ),
        Tool(
            name="a2a_note_to_self",
            description="Write a note to yourself that will appear in the next session's context",
            inputSchema={
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "Note content"},
                    "context": {"type": "string", "description": "Optional context or reason for the note"}
                },
                "required": ["message"]
            }
        ),
        Tool(
            name="a2a_register_monitor",
            description="Register a file/condition monitor that triggers A2A notifications",
            inputSchema={
                "type": "object",
                "properties": {
                    "paths": {"type": "array", "items": {"type": "string"}, "description": "File paths or URL patterns to watch"},
                    "conditions": {"type": "array", "items": {"type": "string"}, "description": "Conditions to watch for (e.g. 'file_changed', 'http_error')"},
                    "notify_message": {"type": "string", "description": "Message template on trigger (use {condition} placeholder)", "default": "Monitor triggered: {condition}"}
                },
                "required": ["paths", "conditions"]
            }
        ),
        Tool(
            name="a2a_task_send",
            description="Delegate an async task to an agent and receive a callback when complete",
            inputSchema={
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "Agent name to delegate to"},
                    "task_description": {"type": "string", "description": "Full task description"},
                    "callback_urgency": {"type": "string", "enum": ["critical", "normal", "low"], "description": "Urgency of the result callback", "default": "normal"}
                },
                "required": ["to", "task_description"]
            }
        ),
        Tool(
            name="a2a_task_status",
            description="Check the status of a previously delegated async task",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "Task ID returned by a2a_task_send"}
                },
                "required": ["task_id"]
            }
        ),
        # Goal management tools
        Tool(
            name="memory_set_goal",
            description="Create a new goal that persists across sessions, tracking a multi-session objective",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Short goal title (e.g. 'Implement A2A messaging')"},
                    "description": {"type": "string", "description": "Full description of what we're trying to accomplish and why"},
                    "completion_criteria": {"type": "string", "description": "How we'll know the goal is done (optional)"},
                    "tags": {"type": "array", "items": {"type": "string"}, "description": "Topic tags for this goal (optional)"}
                },
                "required": ["title", "description"]
            }
        ),
        Tool(
            name="memory_update_goal",
            description="Update a goal's status or append a progress note",
            inputSchema={
                "type": "object",
                "properties": {
                    "goal_id": {"type": "string", "description": "Goal node ID"},
                    "status": {"type": "string", "enum": ["active", "completed", "abandoned", "blocked"], "description": "New status (optional)"},
                    "progress_note": {"type": "string", "description": "Progress update to append (optional)"}
                },
                "required": ["goal_id"]
            }
        ),
        Tool(
            name="memory_complete_goal",
            description="Mark a goal as completed with an optional summary of how it was achieved",
            inputSchema={
                "type": "object",
                "properties": {
                    "goal_id": {"type": "string", "description": "Goal node ID"},
                    "summary": {"type": "string", "description": "What was accomplished (optional)"}
                },
                "required": ["goal_id"]
            }
        ),
        Tool(
            name="memory_list_goals",
            description="List goals for this project — active by default, or all including completed/abandoned",
            inputSchema={
                "type": "object",
                "properties": {
                    "include_completed": {"type": "boolean", "description": "Include completed/abandoned goals", "default": False}
                }
            }
        )
    ]

    if not getattr(memory_server, "_a2a_enabled", False):
        tools = [t for t in tools if not t.name.startswith("a2a_")]

    return tools


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Handle tool calls"""
    try:
        logger.info(f"Tool called: {name}")
        try:
            import sys as _sys
            _sys.path.insert(0, str(_plugin_root() / "hooks"))
            from telemetry import capture as _tel_capture
            _tel_capture("tool_used", {"tool": name}, _plugin_root())
        except Exception:
            pass

        # Belt-and-suspenders A2A gate: list_tools already hides a2a_* names
        # when the feature is disabled, but a non-conformant client could
        # still attempt a direct call_tool dispatch. Return a structured
        # error rather than executing or 500-ing.
        if name.startswith("a2a_") and not getattr(memory_server, "_a2a_enabled", False):
            return [TextContent(type="text", text=json.dumps({
                "ok": False,
                "error": "A2A messaging is disabled in this installation",
                "error_type": "feature_disabled",
                "hint": "Set 'a2a.enabled' to true in config.json and ensure the ArmaraOS daemon is running.",
            }))]

        if name == "memory_store_episode":
            result = await memory_server.memory_store_episode(**arguments)
        elif name == "memory_store_semantic":
            result = await memory_server.memory_store_semantic(**arguments)
        elif name == "memory_store_failure":
            result = await memory_server.memory_store_failure(**arguments)
        elif name == "memory_promote_pattern":
            result = await memory_server.memory_promote_pattern(**arguments)
        elif name == "memory_recall_context":
            result = await memory_server.memory_recall_context(**arguments)
        elif name == "memory_expand_node":
            result = await memory_server.memory_expand_node(**arguments)
        elif name == "memory_search":
            result = await memory_server.memory_search(**arguments)
        elif name == "memory_evolve_persona":
            result = await memory_server.memory_evolve_persona(**arguments)
        # AINL tools
        elif name == "ainl_validate":
            if not memory_server.ainl_tools:
                raise ValueError("AINL tools not available. Install: pip install ainativelang[mcp]")
            result = memory_server.ainl_tools.validate(**arguments)
        elif name == "ainl_compile":
            if not memory_server.ainl_tools:
                raise ValueError("AINL tools not available. Install: pip install ainativelang[mcp]")
            result = memory_server.ainl_tools.compile(**arguments)
        elif name == "ainl_run":
            if not memory_server.ainl_tools:
                raise ValueError("AINL tools not available. Install: pip install ainativelang[mcp]")
            result = memory_server.ainl_tools.run(**arguments)
        elif name == "ainl_capabilities":
            if not memory_server.ainl_tools:
                raise ValueError("AINL tools not available. Install: pip install ainativelang[mcp]")
            result = memory_server.ainl_tools.capabilities()
        elif name == "ainl_security_report":
            if not memory_server.ainl_tools:
                raise ValueError("AINL tools not available. Install: pip install ainativelang[mcp]")
            result = memory_server.ainl_tools.security_report(**arguments)
        elif name == "ainl_ir_diff":
            if not memory_server.ainl_tools:
                raise ValueError("AINL tools not available. Install: pip install ainativelang[mcp]>=1.8.0")
            result = memory_server.ainl_tools.ir_diff(**arguments)
        elif name == "ainl_get_started":
            if not memory_server.ainl_tools:
                raise ValueError("AINL tools not available. Install: pip install ainativelang[mcp]>=1.8.0")
            result = memory_server.ainl_tools.get_started(**arguments)
        elif name == "ainl_step_examples":
            if not memory_server.ainl_tools:
                raise ValueError("AINL tools not available. Install: pip install ainativelang[mcp]>=1.8.0")
            result = memory_server.ainl_tools.step_examples(**arguments)
        elif name == "ainl_adapter_contract":
            if not memory_server.ainl_tools:
                raise ValueError("AINL tools not available. Install: pip install ainativelang[mcp]>=1.8.0")
            result = memory_server.ainl_tools.adapter_contract(**arguments)
        elif name == "ainl_propose_improvement":
            if not memory_server.ainl_tools:
                raise ValueError("AINL tools not available. Install: pip install ainativelang[mcp]>=1.8.0")
            result = memory_server.ainl_tools.propose_improvement(**arguments)
        elif name == "ainl_accept_proposal":
            if not memory_server.ainl_tools:
                raise ValueError("AINL tools not available. Install: pip install ainativelang[mcp]>=1.8.0")
            result = memory_server.ainl_tools.accept_proposal(**arguments)
        elif name == "ainl_list_proposals":
            if not memory_server.ainl_tools:
                raise ValueError("AINL tools not available. Install: pip install ainativelang[mcp]>=1.8.0")
            result = memory_server.ainl_tools.list_proposals(**arguments)
        # A2A tools
        elif name == "a2a_send":
            result = memory_server.a2a_tools.a2a_send(**arguments)
        elif name == "a2a_list_agents":
            result = memory_server.a2a_tools.a2a_list_agents()
        elif name == "a2a_register_agent":
            result = memory_server.a2a_tools.a2a_register_agent(**arguments)
        elif name == "a2a_note_to_self":
            result = memory_server.a2a_tools.a2a_note_to_self(**arguments)
        elif name == "a2a_register_monitor":
            result = memory_server.a2a_tools.a2a_register_monitor(**arguments)
        elif name == "a2a_task_send":
            result = memory_server.a2a_tools.a2a_task_send(**arguments)
        elif name == "a2a_task_status":
            result = memory_server.a2a_tools.a2a_task_status(**arguments)
        elif name == "memory_set_goal":
            result = await memory_server.memory_set_goal(**arguments)
        elif name == "memory_update_goal":
            result = await memory_server.memory_update_goal(**arguments)
        elif name == "memory_complete_goal":
            result = await memory_server.memory_complete_goal(**arguments)
        elif name == "memory_list_goals":
            result = await memory_server.memory_list_goals(**arguments)
        else:
            raise ValueError(f"Unknown tool: {name}")

        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    except Exception as e:
        logger.error(f"Tool error: {e}", exc_info=True)
        return [TextContent(type="text", text=json.dumps({"error": str(e)}, indent=2))]


# Copy the tool implementation methods from the old server
async def memory_store_episode(
    project_id: str,
    task_description: str,
    tool_calls: List[str],
    files_touched: List[str],
    outcome: str,
    **kwargs
) -> Dict[str, Any]:
    """Store an episode node"""
    try:
        canonical_tools = canonicalize_tool_sequence(tool_calls)
        node = create_episode_node(
            project_id=project_id,
            task_description=task_description,
            tool_calls=canonical_tools,
            files_touched=files_touched,
            outcome=outcome,
            **kwargs
        )
        memory_server.store.write_node(node)

        # Create FOLLOWS edge
        prev_episodes = memory_server.store.query_episodes_since(
            since=0, limit=2, project_id=project_id
        )
        edges_created = []
        if len(prev_episodes) > 1:
            prev_ep = prev_episodes[1]
            edge = create_edge(
                from_node=node.id,
                to_node=prev_ep.id,
                edge_type=EdgeType.FOLLOWS,
                project_id=project_id
            )
            memory_server.store.write_edge(edge)
            edges_created.append(edge.id)

        return {
            "node_id": node.id,
            "node_type": "episode",
            "canonical_tools": canonical_tools,
            "edges_created": edges_created
        }
    except Exception as e:
        logger.error(f"Failed to store episode: {e}")
        return {"error": str(e)}


async def memory_store_semantic(
    project_id: str,
    fact: str,
    confidence: float,
    source_turn_id: Optional[str] = None,
    **kwargs
) -> Dict[str, Any]:
    """Store a semantic fact"""
    try:
        node = create_semantic_node(
            project_id=project_id,
            fact=fact,
            confidence=confidence,
            source_turn_id=source_turn_id,
            **kwargs
        )
        memory_server.store.write_node(node)
        return {
            "node_id": node.id,
            "node_type": "semantic",
            "fact": fact
        }
    except Exception as e:
        logger.error(f"Failed to store semantic: {e}")
        return {"error": str(e)}


async def memory_store_failure(
    project_id: str,
    error_type: str,
    tool: str,
    error_message: str,
    **kwargs
) -> Dict[str, Any]:
    """Store a failure node"""
    try:
        node = create_failure_node(
            project_id=project_id,
            error_type=error_type,
            tool=tool,
            error_message=error_message,
            **kwargs
        )
        memory_server.store.write_node(node)
        return {
            "node_id": node.id,
            "node_type": "failure",
            "error_type": error_type
        }
    except Exception as e:
        logger.error(f"Failed to store failure: {e}")
        return {"error": str(e)}


async def memory_promote_pattern(
    project_id: str,
    pattern_name: str,
    trigger: str,
    tool_sequence: List[str],
    evidence_ids: List[str],
    **kwargs
) -> Dict[str, Any]:
    """Promote a pattern"""
    try:
        canonical_tools = canonicalize_tool_sequence(tool_sequence)
        node = create_procedural_node(
            project_id=project_id,
            pattern_name=pattern_name,
            trigger=trigger,
            tool_sequence=canonical_tools,
            success_count=len(evidence_ids),
            evidence_ids=evidence_ids,
            **kwargs
        )
        memory_server.store.write_node(node)

        edges_created = []
        for evidence_id in evidence_ids[:5]:
            edge = create_edge(
                from_node=node.id,
                to_node=evidence_id,
                edge_type=EdgeType.PATTERN_FOR,
                project_id=project_id
            )
            try:
                memory_server.store.write_edge(edge)
                edges_created.append(edge.id)
            except Exception as edge_err:
                logger.warning(f"Failed to create edge: {edge_err}")

        return {
            "node_id": node.id,
            "node_type": "procedural",
            "pattern_name": pattern_name,
            "edges_created": edges_created
        }
    except Exception as e:
        logger.error(f"Failed to promote pattern: {e}")
        return {"error": str(e)}


async def memory_recall_context(
    project_id: str,
    current_task: Optional[str] = None,
    files_mentioned: Optional[List[str]] = None,
    max_nodes: int = 50
) -> Dict[str, Any]:
    """Recall memory context.

    Always merges in the legacy global bucket (LEGACY_GLOBAL_PROJECT_ID) so
    callers that pass a per-repo `project_id` still see pre-issue-1 memories
    until `scripts/repartition_by_repo.py` has been run."""
    try:
        try:
            from project_id import LEGACY_GLOBAL_PROJECT_ID  # type: ignore
        except ImportError:
            sys.path.insert(0, str(_plugin_root() / "hooks"))
            from shared.project_id import LEGACY_GLOBAL_PROJECT_ID  # type: ignore

        chain = [project_id]
        if LEGACY_GLOBAL_PROJECT_ID != project_id:
            chain.append(LEGACY_GLOBAL_PROJECT_ID)

        context = RetrievalContext(
            project_id=project_id,
            current_task=current_task,
            files_mentioned=files_mentioned or [],
            project_id_chain=chain,
        )
        memory_context = memory_server.retrieval.compile_memory_context(context, max_nodes)
        return {
            "context": memory_context,
            "node_count": sum(
                len(v) for k, v in memory_context.items()
                if isinstance(v, list)
            )
        }
    except Exception as e:
        logger.error(f"Failed to recall context: {e}")
        return {"error": str(e)}


async def memory_expand_node(project_id: str, node_id: str) -> Dict[str, Any]:
    """Return a single node payload for MCP drill-down."""
    _ = project_id  # Echoed for tool contract symmetry; DB is cwd-scoped.
    try:
        node = memory_server.store.get_node(node_id)
        if node is None:
            return {"error": "node_not_found", "node_id": node_id}
        return {"node": node.to_dict()}
    except Exception as e:
        logger.error(f"memory_expand_node failed: {e}")
        return {"error": str(e)}


async def memory_search(
    query: str,
    project_id: str,
    limit: int = 20
) -> Dict[str, Any]:
    """Search memory"""
    try:
        results = memory_server.store.search_fts(query, project_id, limit)
        return {
            "results": [node.to_dict() for node in results],
            "count": len(results)
        }
    except Exception as e:
        logger.error(f"Failed to search: {e}")
        return {"error": str(e)}


async def memory_evolve_persona(
    project_id: str,
    episode_data: Dict[str, Any]
) -> Dict[str, Any]:
    """Evolve persona"""
    try:
        signals = memory_server.extractor.extract_signals(episode_data)
        traits = memory_server.persona_engine.evolve(project_id, signals)

        # Store persona nodes
        nodes_created = []
        for trait_name, strength in traits.items():
            node = create_persona_node(
                project_id=project_id,
                trait_name=trait_name,
                strength=strength
            )
            memory_server.store.write_node(node)
            nodes_created.append(node.id)

        return {
            "traits_evolved": traits,
            "nodes_created": nodes_created
        }
    except Exception as e:
        logger.error(f"Failed to evolve persona: {e}")
        return {"error": str(e)}


async def memory_set_goal(
    title: str,
    description: str,
    completion_criteria: Optional[str] = None,
    tags: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Create a new persistent goal node"""
    try:
        goal_id = memory_server.goal_tracker.create_goal(
            title=title,
            description=description,
            completion_criteria=completion_criteria,
            tags=tags or [],
            inferred=False,
        )
        return {"goal_id": goal_id, "title": title, "status": "active"}
    except Exception as e:
        logger.error(f"Failed to set goal: {e}")
        return {"error": str(e)}


async def memory_update_goal(
    goal_id: str,
    status: Optional[str] = None,
    progress_note: Optional[str] = None,
) -> Dict[str, Any]:
    """Update a goal's status or progress"""
    try:
        ok = memory_server.goal_tracker.update_goal(goal_id, status=status, progress_note=progress_note)
        return {"updated": ok, "goal_id": goal_id}
    except Exception as e:
        logger.error(f"Failed to update goal: {e}")
        return {"error": str(e)}


async def memory_complete_goal(
    goal_id: str,
    summary: Optional[str] = None,
) -> Dict[str, Any]:
    """Mark a goal complete"""
    try:
        ok = memory_server.goal_tracker.complete_goal(goal_id, summary=summary)
        return {"completed": ok, "goal_id": goal_id}
    except Exception as e:
        logger.error(f"Failed to complete goal: {e}")
        return {"error": str(e)}


async def memory_list_goals(
    include_completed: bool = False,
) -> Dict[str, Any]:
    """List goals for this project"""
    try:
        project_id = memory_server.goal_tracker.project_id
        goals = memory_server.goal_tracker.get_all_goals(include_completed=include_completed)
        return {"goals": goals, "count": len(goals), "project_id": project_id}
    except Exception as e:
        logger.error(f"Failed to list goals: {e}")
        return {"error": str(e)}


# Add methods to the server instance
memory_server.memory_store_episode = memory_store_episode
memory_server.memory_store_semantic = memory_store_semantic
memory_server.memory_store_failure = memory_store_failure
memory_server.memory_promote_pattern = memory_promote_pattern
memory_server.memory_recall_context = memory_recall_context
memory_server.memory_expand_node = memory_expand_node
memory_server.memory_search = memory_search
memory_server.memory_evolve_persona = memory_evolve_persona
memory_server.memory_set_goal = memory_set_goal
memory_server.memory_update_goal = memory_update_goal
memory_server.memory_complete_goal = memory_complete_goal
memory_server.memory_list_goals = memory_list_goals


async def main():
    """Run the MCP server"""
    logger.info("Starting AINL Graph Memory MCP Server with official SDK")
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
