"""
A2A graph store helpers for MCP tools.

Operates on an already-open SQLiteGraphStore instance.
"""

import time
import uuid
from typing import Optional, List

try:
    from .node_types import GraphNode, NodeType
    from .graph_store import GraphStore
except ImportError:
    from node_types import GraphNode, NodeType
    from graph_store import GraphStore


def store_message_node(
    store: GraphStore,
    project_id: str,
    direction: str,
    from_agent: str,
    to_agent: str,
    thread_id: Optional[str],
    urgency: str,
    message_text: str,
) -> str:
    """Store an A2A message as a SEMANTIC node. Returns node_id."""
    tid = thread_id or "none"
    preview = message_text[:200]
    fact = f"A2A {direction} {from_agent}→{to_agent} [thread:{tid}]: {preview}"

    node = GraphNode(
        id=str(uuid.uuid4()),
        node_type=NodeType.SEMANTIC,
        project_id=project_id,
        agent_id="claude-code",
        created_at=int(time.time()),
        updated_at=int(time.time()),
        confidence=0.9,
        data={
            "fact": fact,
            "topic_cluster": "a2a",
            "tags": [
                "a2a",
                f"from:{from_agent}",
                f"thread:{tid}",
                f"urgency:{urgency}",
                f"direction:{direction}",
            ],
            "recurrence_count": 1,
            "reference_count": 0,
            "source_turn_id": None,
        },
        metadata={
            "a2a_id": str(uuid.uuid4()),
            "direction": direction,
            "from_agent": from_agent,
            "to_agent": to_agent,
            "thread_id": thread_id,
            "urgency": urgency,
            "timestamp": int(time.time()),
        },
        embedding_text=fact,
    )

    store.write_node(node)
    return node.id


def store_task_episode(
    store: GraphStore,
    project_id: str,
    task_id: str,
    task_description: str,
    to_agent: str,
    outcome: str,
    result_text: str = "",
) -> str:
    """Store an A2A task delegation as an EPISODE node. Returns node_id."""
    node = GraphNode(
        id=str(uuid.uuid4()),
        node_type=NodeType.EPISODE,
        project_id=project_id,
        agent_id="claude-code",
        created_at=int(time.time()),
        updated_at=int(time.time()),
        confidence=1.0,
        data={
            "turn_id": str(uuid.uuid4()),
            "task_description": f"A2A task to {to_agent}: {task_description[:120]}",
            "tool_calls": ["a2a_task_send"],
            "files_touched": [],
            "outcome": outcome,
            "duration_ms": 0,
            "git_commit": None,
            "test_results": None,
            "session_id": None,
            "error_message": None,
        },
        metadata={
            "task_id": task_id,
            "to_agent": to_agent,
            "result_text": result_text[:500] if result_text else "",
        },
        embedding_text=f"A2A task {to_agent}: {task_description[:120]}",
    )

    store.write_node(node)
    return node.id


def store_thread_summary(
    store: GraphStore,
    project_id: str,
    thread_id: str,
    from_agent: str,
    summary_text: str,
) -> str:
    """Store a summarised A2A thread as a SEMANTIC node. Returns node_id."""
    fact = f"Thread {thread_id} with {from_agent}: {summary_text[:300]}"

    node = GraphNode(
        id=str(uuid.uuid4()),
        node_type=NodeType.SEMANTIC,
        project_id=project_id,
        agent_id="claude-code",
        created_at=int(time.time()),
        updated_at=int(time.time()),
        confidence=0.85,
        data={
            "fact": fact,
            "topic_cluster": "a2a",
            "tags": ["a2a", "thread_summary", f"thread:{thread_id}", f"from:{from_agent}"],
            "recurrence_count": 1,
            "reference_count": 0,
            "source_turn_id": None,
        },
        metadata={
            "thread_id": thread_id,
            "from_agent": from_agent,
            "is_thread_summary": True,
        },
        embedding_text=fact,
    )

    store.write_node(node)
    return node.id


def query_thread_history(
    store: GraphStore,
    project_id: str,
    thread_id: str,
    n: int = 5,
) -> List[GraphNode]:
    """Return last N message nodes for a given thread_id."""
    results = store.search_fts(f"thread:{thread_id}", project_id, limit=n * 2)
    filtered = [
        node for node in results
        if (node.metadata or {}).get("thread_id") == thread_id
    ]
    filtered.sort(key=lambda node: -node.created_at)
    return filtered[:n]
