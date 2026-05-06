#!/usr/bin/env python3
"""
AINL Graph Memory MCP Server

Properly implemented using the official MCP SDK.
Exposes graph memory tools for Claude Code integration.
"""

import os
import sys
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

# Configure logging
log_dir = _plugin_root() / "logs"
log_dir.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_dir / "mcp_server.log"),
        logging.StreamHandler(sys.stderr)
    ]
)

logger = logging.getLogger(__name__)

# Import our modules
try:
    from .graph_store import SQLiteGraphStore
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
except ImportError:
    # Fallback for when run as script
    sys.path.insert(0, str(Path(__file__).parent))
    from graph_store import SQLiteGraphStore
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


class AINLGraphMemoryServer:
    """AINL Graph Memory MCP Server"""

    def __init__(self):
        self.db_path = self._get_db_path()
        self.store = SQLiteGraphStore(self.db_path)
        self.retrieval = MemoryRetrieval(self.store)
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
        project_id = self._compute_project_hash(Path.cwd())
        self.a2a_tools = A2ATools(plugin_root, self.store, project_id, config)
        logger.info("A2A tools initialized successfully")

        logger.info(f"AINL Graph Memory Server initialized with DB: {self.db_path}")

    def _get_db_path(self) -> Path:
        """Get database path (project-specific if possible)"""
        cwd = Path.cwd()
        project_hash = self._compute_project_hash(cwd)
        memory_dir = Path.home() / ".claude" / "projects" / project_hash / "graph_memory"
        memory_dir.mkdir(parents=True, exist_ok=True)
        return memory_dir / "ainl_memory.db"

    def _compute_project_hash(self, cwd: Path) -> str:
        """Compute stable global project hash (same bucket as hooks)."""
        import hashlib
        claude_dir = Path.home() / ".claude"
        return hashlib.sha256(str(claude_dir.resolve()).encode()).hexdigest()[:16]


# Create server instance
server = Server("ainl-graph-memory")
memory_server = AINLGraphMemoryServer()


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List available MCP tools"""
    return [
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
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Handle tool calls"""
    try:
        logger.info(f"Tool called: {name}")

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
                raise ValueError("AINL tools not available. Install: pip install ainativelang[mcp]")
            result = memory_server.ainl_tools.ir_diff(**arguments)
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
        else:
            raise ValueError(f"Unknown tool: {name}")

        import json
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    except Exception as e:
        logger.error(f"Tool error: {e}", exc_info=True)
        import json
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
    """Recall memory context"""
    try:
        context = RetrievalContext(
            project_id=project_id,
            current_task=current_task,
            files_mentioned=files_mentioned or []
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


# Add methods to the server instance
memory_server.memory_store_episode = memory_store_episode
memory_server.memory_store_semantic = memory_store_semantic
memory_server.memory_store_failure = memory_store_failure
memory_server.memory_promote_pattern = memory_promote_pattern
memory_server.memory_recall_context = memory_recall_context
memory_server.memory_search = memory_search
memory_server.memory_evolve_persona = memory_evolve_persona


async def main():
    """Run the MCP server"""
    logger.info("Starting AINL Graph Memory MCP Server with official SDK")
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
