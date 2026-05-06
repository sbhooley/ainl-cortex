"""
A2A graph memory writer for hooks.

Stores A2A messages as SEMANTIC nodes directly via SQLiteGraphStore.
Used by user_prompt_submit hook — avoids the MCP round-trip.
"""

import sys
import time
import uuid
import json
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "mcp_server"))


def store_message_node(
    db_path: Path,
    project_id: str,
    direction: str,       # "inbound" or "outbound"
    from_agent: str,
    to_agent: str,
    thread_id: Optional[str],
    urgency: str,
    message_text: str,
) -> str:
    """Store an A2A message as a SEMANTIC graph node. Returns node_id or ''."""
    try:
        from graph_store import SQLiteGraphStore
        from node_types import GraphNode, NodeType

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
                "received_at": int(time.time()),
            },
            embedding_text=fact,
        )

        db_path.parent.mkdir(parents=True, exist_ok=True)
        store = SQLiteGraphStore(db_path)
        store.write_node(node)
        return node.id

    except Exception:
        return ""


def query_thread_history(
    db_path: Path,
    project_id: str,
    thread_id: str,
    n: int = 5,
) -> list:
    """Return last N message nodes for a thread, newest first."""
    try:
        from graph_store import SQLiteGraphStore

        store = SQLiteGraphStore(db_path)
        results = store.search_fts(f"thread:{thread_id}", project_id, limit=n * 2)

        # Filter to confirmed thread members via metadata
        filtered = []
        for node in results:
            meta = node.metadata or {}
            if meta.get("thread_id") == thread_id:
                filtered.append(node)
            if len(filtered) >= n:
                break

        filtered.sort(key=lambda n: -n.created_at)
        return filtered

    except Exception:
        return []
