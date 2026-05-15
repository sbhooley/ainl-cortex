"""
NativeGraphStore — GraphStore ABC backed by ainl_native.AinlNativeStore (Rust).

Single database, single schema (Rust ainl-memory). Python extras round-trip via
the `plugin_data` field added to AinlMemoryNode.

Node type mapping:
  EPISODE    → Episode  (plugin_data carries: task_description, files_touched, outcome, session_id, …)
  SEMANTIC   → Semantic
  FAILURE    → Failure
  PERSONA    → Persona
  PROCEDURAL → Procedural
  GOAL       → Semantic with topic_cluster="_plugin:goal"
                (plugin_data = full GoalData dict; _schema_version = PLUGIN_SCHEMA_VERSION)
  RUNTIME_STATE → Semantic with topic_cluster="_plugin:runtime_state"
                (plugin_data = full RuntimeStateData dict; _schema_version = PLUGIN_SCHEMA_VERSION)

The `_plugin:*` namespace is reserved (PLUGIN_RESERVED_CLUSTERS); the Rust
session.rs side filters those clusters out of recall/scoring (issue 4), and
this module's query_by_type(SEMANTIC, ...) drops them so semantic queries
never accidentally return goals.

Back-compat: rows written with the old `goal` / `runtime_state` topic_cluster
(no underscore prefix) still round-trip correctly via `py_node_type` plugin
data — they just don't get the namespace filter benefit until rewritten.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional


# ── Plugin namespace constants ────────────────────────────────────────────────

PLUGIN_TOPIC_CLUSTER_PREFIX = "_plugin:"
PLUGIN_GOAL_CLUSTER = f"{PLUGIN_TOPIC_CLUSTER_PREFIX}goal"
PLUGIN_RUNTIME_STATE_CLUSTER = f"{PLUGIN_TOPIC_CLUSTER_PREFIX}runtime_state"
PLUGIN_RESERVED_CLUSTERS = frozenset({PLUGIN_GOAL_CLUSTER, PLUGIN_RUNTIME_STATE_CLUSTER})

# Bump when the on-disk plugin_data shape for Goal / RuntimeState changes.
PLUGIN_SCHEMA_VERSION = 1

GOAL_INDEX_FILENAME = "goal_index.json"


def _is_plugin_namespaced(topic_cluster: Optional[str]) -> bool:
    return bool(topic_cluster) and topic_cluster.startswith(PLUGIN_TOPIC_CLUSTER_PREFIX)

try:
    import ainl_native as _native
    _NATIVE_OK = True
except ImportError:
    _native = None  # type: ignore[assignment]
    _NATIVE_OK = False

try:
    from .graph_store import GraphStore
    from .node_types import GraphNode, GraphEdge, NodeType, EdgeType
except ImportError:
    from graph_store import GraphStore  # type: ignore[no-redef]
    from node_types import GraphNode, GraphEdge, NodeType, EdgeType  # type: ignore[assignment]


# ── Conversion helpers ────────────────────────────────────────────────────────

def _node_to_ainl(node: GraphNode) -> dict:
    """Convert a Python GraphNode to an AinlMemoryNode dict for Rust write."""
    now = int(time.time())
    d = node.data or {}
    nt = node.node_type

    if nt == NodeType.EPISODE:
        raw_node_type = {
            "type": "episode",
            "turn_id": d.get("turn_id") or str(uuid.uuid4()),
            "timestamp": node.created_at or now,
            "tool_calls": d.get("tool_calls", []),
            "tools_invoked": d.get("tool_calls", []),
            "delegation_to": None,
            "turn_index": 0,
            "user_message_tokens": 0,
            "assistant_response_tokens": 0,
            "persona_signals_emitted": [],
            "sentiment": None,
            "flagged": False,
            "conversation_id": d.get("session_id") or "",
            "follows_episode_id": None,
        }
        plugin_data = {
            "task_description": d.get("task_description", ""),
            "files_touched": d.get("files_touched", []),
            "outcome": d.get("outcome", "success"),
            "session_id": d.get("session_id"),
            "git_commit": d.get("git_commit"),
            "duration_ms": d.get("duration_ms"),
            "error_message": d.get("error_message"),
            "py_node_type": "episode",
        }
        memory_category = "episodic"

    elif nt == NodeType.SEMANTIC:
        raw_node_type = {
            "type": "semantic",
            "fact": d.get("fact", ""),
            "confidence": node.confidence,
            "source_turn_id": d.get("source_turn_id") or "00000000-0000-0000-0000-000000000000",
            "topic_cluster": d.get("topic_cluster"),
            "source_episode_id": "",
            "contradiction_ids": [],
            "last_referenced_at": 0,
            "reference_count": d.get("reference_count", 0),
            "decay_eligible": True,
            "tags": d.get("tags", []),
            "recurrence_count": d.get("recurrence_count", 0),
            "_last_ref_snapshot": 0,
        }
        plugin_data = {"py_node_type": "semantic"}
        if node.metadata:
            plugin_data.update(node.metadata)
        memory_category = "semantic"

    elif nt == NodeType.FAILURE:
        raw_node_type = {
            "type": "failure",
            "failure": {
                "recorded_at": node.created_at or now,
                "source": d.get("tool", "plugin"),
                "tool_name": d.get("tool"),
                "source_namespace": "plugin",
                "source_tool": d.get("tool"),
                "message": f"{d.get('error_type', '')}: {d.get('error_message', '')}".strip(": "),
                "session_id": d.get("session_id"),
            },
        }
        plugin_data = {
            "error_type": d.get("error_type", ""),
            "command": d.get("command"),
            "file": d.get("file"),
            "line": d.get("line"),
            "stack_trace": d.get("stack_trace"),
            "resolution": d.get("resolution"),
            "resolution_turn_id": d.get("resolution_turn_id"),
            "resolved_at": d.get("resolved_at"),
            "py_node_type": "failure",
        }
        memory_category = "episodic"

    elif nt == NodeType.PERSONA:
        raw_node_type = {
            "type": "persona",
            "trait_name": d.get("trait_name", ""),
            "strength": d.get("strength", node.confidence),
            "learned_from": d.get("learned_from", []),
            "layer": "base",
            "source": "evolved",
            "strength_floor": 0.0,
            "locked": False,
            "relevance_score": d.get("strength", node.confidence),
            "provenance_episode_ids": d.get("learned_from", []),
            "evolution_log": [],
            "axis_scores": {},
            "evolution_cycle": 0,
            "last_evolved": "",
            "agent_id": node.agent_id,
            "dominant_axes": [],
        }
        plugin_data = {
            "layer": d.get("layer", "adaptive"),
            "axis": d.get("axis"),
            "decay_rate": d.get("decay_rate", 0.95),
            "py_node_type": "persona",
        }
        memory_category = "persona"

    elif nt == NodeType.PROCEDURAL:
        success = d.get("success_count", 0)
        failure = d.get("failure_count", 0)
        total = success + failure
        raw_node_type = {
            "type": "procedural",
            "pattern_name": d.get("pattern_name", ""),
            "compiled_graph": [],
            "tool_sequence": d.get("tool_sequence", []),
            "confidence": None,
            "procedure_type": "tool_sequence",
            "trigger_conditions": [d.get("trigger", "")] if d.get("trigger") else [],
            "success_count": success,
            "failure_count": failure,
            "success_rate": success / total if total else 1.0,
            "last_invoked_at": d.get("last_used_at", 0) or 0,
            "reinforcement_episode_ids": d.get("evidence_ids", []),
            "suppression_episode_ids": [],
            "patch_version": 0,
            "fitness": d.get("fitness"),
            "declared_reads": [],
            "retired": False,
            "label": d.get("pattern_name", ""),
            "trace_id": None,
            "pattern_observation_count": 0,
            "prompt_eligible": True,
        }
        plugin_data = {
            "trigger": d.get("trigger", ""),
            "scope": d.get("scope", "project"),
            "py_node_type": "procedural",
        }
        memory_category = "procedural"

    elif nt == NodeType.GOAL:
        raw_node_type = {
            "type": "semantic",
            "fact": f"{d.get('title', '')}: {d.get('description', '')}".strip(": "),
            "confidence": node.confidence,
            "source_turn_id": "00000000-0000-0000-0000-000000000000",
            # Reserved namespace — Rust session.rs (is_plugin_namespaced_semantic)
            # and Python query_by_type(SEMANTIC) both filter rows in this
            # cluster so they never surface as semantic facts.
            "topic_cluster": PLUGIN_GOAL_CLUSTER,
            "source_episode_id": "",
            "contradiction_ids": [],
            "last_referenced_at": 0,
            "reference_count": 0,
            "decay_eligible": False,
            "tags": d.get("tags", []) + ["goal"],
            "recurrence_count": 0,
            "_last_ref_snapshot": 0,
        }
        # Carry the full goal payload byte-exact in plugin_data; _schema_version
        # lets future readers detect format drift without breaking back-compat.
        plugin_data = dict(d)
        plugin_data["py_node_type"] = "goal"
        plugin_data["_schema_version"] = PLUGIN_SCHEMA_VERSION
        memory_category = "semantic"

    elif nt == NodeType.RUNTIME_STATE:
        raw_node_type = {
            "type": "semantic",
            "fact": "runtime_state",
            "confidence": 1.0,
            "source_turn_id": "00000000-0000-0000-0000-000000000000",
            "topic_cluster": PLUGIN_RUNTIME_STATE_CLUSTER,
            "source_episode_id": "",
            "contradiction_ids": [],
            "last_referenced_at": now,
            "reference_count": 0,
            "decay_eligible": False,
            "tags": ["runtime_state"],
            "recurrence_count": 0,
            "_last_ref_snapshot": 0,
        }
        plugin_data = dict(d)
        plugin_data["py_node_type"] = "runtime_state"
        plugin_data["_schema_version"] = PLUGIN_SCHEMA_VERSION
        memory_category = "semantic"

    else:
        # Unknown: store as semantic with all data in plugin_data
        raw_node_type = {
            "type": "semantic",
            "fact": str(d),
            "confidence": node.confidence,
            "source_turn_id": "00000000-0000-0000-0000-000000000000",
            "topic_cluster": nt.value if hasattr(nt, "value") else str(nt),
            "source_episode_id": "",
            "contradiction_ids": [],
            "last_referenced_at": 0,
            "reference_count": 0,
            "decay_eligible": True,
            "tags": [],
            "recurrence_count": 0,
            "_last_ref_snapshot": 0,
        }
        plugin_data = {"py_node_type": str(nt), "original_data": d}
        memory_category = "semantic"

    return {
        "id": node.id,
        "memory_category": memory_category,
        "importance_score": float(node.confidence),
        "agent_id": node.agent_id or "claude-code",
        "project_id": node.project_id,
        "node_type": raw_node_type,
        "edges": [],
        "plugin_data": plugin_data,
    }


def _ainl_to_node(raw: dict) -> GraphNode:
    """Convert an AinlMemoryNode dict (from read_node) back to a Python GraphNode.

    Plugin-extension semantic rows (Goal, RuntimeState) are detected by a
    two-step rule:
      1. plugin_data.py_node_type wins (the canonical signal).
      2. Else, if topic_cluster is in PLUGIN_RESERVED_CLUSTERS, route by that.
    Step 2 protects against rows whose plugin_data was somehow lost (e.g.
    cross-version migration) but still carry the namespaced cluster.
    """
    nt_raw = raw.get("node_type", {})
    kind = nt_raw.get("type", "semantic")
    pd = raw.get("plugin_data") or {}
    py_kind = pd.get("py_node_type", kind)

    # Step 2 fallback for namespaced semantic rows.
    if py_kind == kind and kind == "semantic":
        cluster = nt_raw.get("topic_cluster")
        if cluster == PLUGIN_GOAL_CLUSTER:
            py_kind = "goal"
        elif cluster == PLUGIN_RUNTIME_STATE_CLUSTER:
            py_kind = "runtime_state"

    node_id = raw["id"]
    agent_id = raw.get("agent_id", "claude-code")
    project_id = raw.get("project_id")
    confidence = float(raw.get("importance_score", 1.0))
    now = int(time.time())

    if py_kind == "episode" or kind == "episode":
        data = {
            "turn_id": nt_raw.get("turn_id", str(uuid.uuid4())),
            "task_description": pd.get("task_description", ""),
            "tool_calls": nt_raw.get("tool_calls", []),
            "files_touched": pd.get("files_touched", []),
            "outcome": pd.get("outcome", "success"),
            "session_id": pd.get("session_id") or nt_raw.get("conversation_id") or None,
            "git_commit": pd.get("git_commit"),
            "duration_ms": pd.get("duration_ms"),
            "error_message": pd.get("error_message"),
        }
        node_type = NodeType.EPISODE

    elif py_kind == "goal":
        data = {
            k: v for k, v in pd.items()
            if k not in ("py_node_type", "_schema_version")
        }
        node_type = NodeType.GOAL

    elif py_kind == "runtime_state":
        data = {
            k: v for k, v in pd.items()
            if k not in ("py_node_type", "_schema_version")
        }
        node_type = NodeType.RUNTIME_STATE

    elif kind == "semantic":
        data = {
            "fact": nt_raw.get("fact", ""),
            "topic_cluster": nt_raw.get("topic_cluster"),
            "tags": nt_raw.get("tags", []),
            "recurrence_count": nt_raw.get("recurrence_count", 0),
            "reference_count": nt_raw.get("reference_count", 0),
            "source_turn_id": nt_raw.get("source_turn_id"),
        }
        node_type = NodeType.SEMANTIC

    elif kind == "failure":
        f = nt_raw.get("failure") or nt_raw  # nested under "failure" key
        data = {
            "error_type": pd.get("error_type", f.get("source", "unknown")),
            "tool": f.get("tool_name") or f.get("source", ""),
            "error_message": f.get("message", ""),
            "command": pd.get("command"),
            "file": pd.get("file"),
            "line": pd.get("line"),
            "stack_trace": pd.get("stack_trace"),
            "resolution": pd.get("resolution"),
            "resolution_turn_id": pd.get("resolution_turn_id"),
            "resolved_at": pd.get("resolved_at"),
            "session_id": f.get("session_id"),
        }
        node_type = NodeType.FAILURE

    elif kind == "persona":
        data = {
            "trait_name": nt_raw.get("trait_name", ""),
            "strength": float(nt_raw.get("strength", confidence)),
            "layer": pd.get("layer", "adaptive"),
            "learned_from": nt_raw.get("learned_from", []),
            "axis": pd.get("axis"),
            "decay_rate": pd.get("decay_rate", 0.95),
        }
        node_type = NodeType.PERSONA

    elif kind == "procedural":
        data = {
            "pattern_name": nt_raw.get("pattern_name", ""),
            "trigger": pd.get("trigger") or (nt_raw.get("trigger_conditions") or [""])[0],
            "tool_sequence": nt_raw.get("tool_sequence", []),
            "success_count": nt_raw.get("success_count", 0),
            "failure_count": nt_raw.get("failure_count", 0),
            "fitness": nt_raw.get("fitness") or nt_raw.get("success_rate", 1.0),
            "last_used_at": nt_raw.get("last_invoked_at") or None,
            "scope": pd.get("scope", "project"),
            "evidence_ids": nt_raw.get("reinforcement_episode_ids", []),
        }
        node_type = NodeType.PROCEDURAL

    else:
        data = dict(pd)
        data.pop("py_node_type", None)
        node_type = NodeType.SEMANTIC

    # Reconstruct embedding_text for failure nodes — not stored in the Rust schema
    # but needed for TF-IDF semantic matching in FailureAdvisor.
    embedding_text = None
    if node_type == NodeType.FAILURE:
        _parts = [
            data.get("error_type", ""),
            data.get("tool", ""),
            data.get("error_message", ""),
        ]
        if data.get("file"):
            _parts.append(str(data["file"]))
        if data.get("command"):
            _parts.append(str(data["command"]))
        if data.get("stack_trace"):
            _parts.append(str(data["stack_trace"])[:200])
        embedding_text = " ".join(p for p in _parts if p) or None

    return GraphNode(
        id=node_id,
        node_type=node_type,
        project_id=project_id or "",
        created_at=now,
        updated_at=now,
        confidence=confidence,
        data=data,
        agent_id=agent_id,
        metadata=None,
        embedding_text=embedding_text,
    )


def _edge_label(edge_type: EdgeType) -> str:
    return edge_type.value if hasattr(edge_type, "value") else str(edge_type)


# ── NativeGraphStore ──────────────────────────────────────────────────────────

class NativeGraphStore(GraphStore):
    """GraphStore backed by ainl_native.AinlNativeStore (Rust SqliteGraphStore)."""

    def __init__(self, db_path: Path, agent_id: str = "claude-code"):
        if not _NATIVE_OK:
            raise RuntimeError("ainl_native not available — build with maturin first")
        self._store = _native.AinlNativeStore.open(str(db_path))
        self._agent_id = agent_id
        self._db_path = db_path
        # Goal index lives next to the DB so a fresh process can find it.
        self._goal_index_path = Path(db_path).parent / GOAL_INDEX_FILENAME

    # ── Core writes ───────────────────────────────────────────────────────────

    def write_node(self, node: GraphNode) -> None:
        ainl_dict = _node_to_ainl(node)
        self._store.write_node(ainl_dict)
        # Maintain the goal index in lockstep with goal writes so query_goals
        # never has to scan the entire semantic table. The index is
        # best-effort: failure to update is logged but does not raise (the
        # fallback scan in query_goals catches missed entries).
        if node.node_type == NodeType.GOAL:
            try:
                self._upsert_goal_index_entry(node)
            except Exception:
                pass

    # ── Goal index ────────────────────────────────────────────────────────────

    def _read_goal_index(self) -> Dict[str, Dict[str, Any]]:
        try:
            return json.loads(self._goal_index_path.read_text())
        except (OSError, json.JSONDecodeError, ValueError):
            return {}

    def _write_goal_index_atomic(self, index: Dict[str, Dict[str, Any]]) -> None:
        # Atomic write via tmp + os.replace — never leaves a half-written file.
        self._goal_index_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._goal_index_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(index, indent=2))
        os.replace(tmp, self._goal_index_path)

    def _upsert_goal_index_entry(self, node: GraphNode) -> None:
        d = node.data or {}
        index = self._read_goal_index()
        index[node.id] = {
            "id": node.id,
            "project_id": node.project_id,
            "title": d.get("title", ""),
            "status": d.get("status", "active"),
            "updated_at": int(time.time()),
        }
        self._write_goal_index_atomic(index)

    def write_edge(self, edge: GraphEdge) -> None:
        self._store.insert_edge(edge.from_node, edge.to_node, _edge_label(edge.edge_type))

    # ── Reads ─────────────────────────────────────────────────────────────────

    def get_node(self, node_id: str) -> Optional[GraphNode]:
        raw = self._store.read_node(node_id)
        return _ainl_to_node(raw) if raw else None

    def update_node_data(self, node_id: str, data_patch: Dict[str, Any]) -> None:
        node = self.get_node(node_id)
        if node:
            node.data.update(data_patch)
            self.write_node(node)

    # ── Queries ───────────────────────────────────────────────────────────────

    def query_episodes_since(
        self, since: int, limit: int, project_id: Optional[str] = None
    ) -> List[GraphNode]:
        rows = self._store.query_episodes_since(since, limit)
        nodes = [_ainl_to_node(r) for r in rows]
        if project_id:
            nodes = [n for n in nodes if n.project_id == project_id]
        return nodes

    def query_by_type(
        self,
        node_type: NodeType,
        project_id: str,
        limit: int,
        min_confidence: float = 0.0,
    ) -> List[GraphNode]:
        rust_type_name = {
            NodeType.EPISODE: "episode",
            NodeType.SEMANTIC: "semantic",
            NodeType.FAILURE: "failure",
            NodeType.PERSONA: "persona",
            NodeType.PROCEDURAL: "procedural",
            NodeType.GOAL: "semantic",
            NodeType.RUNTIME_STATE: "semantic",
        }.get(node_type, "semantic")

        rows = self._store.find_by_type(rust_type_name)
        nodes = []
        for r in rows:
            # Issue 4: when caller asks for SEMANTIC, hide rows that live in
            # the reserved plugin namespace (Goals / RuntimeState). Callers
            # that want those use query_goals / query_runtime_state.
            if node_type == NodeType.SEMANTIC:
                cluster = (r.get("node_type") or {}).get("topic_cluster")
                if _is_plugin_namespaced(cluster):
                    continue
            n = _ainl_to_node(r)
            if n.project_id == project_id and n.confidence >= min_confidence:
                if n.node_type == node_type:
                    nodes.append(n)
        return nodes[:limit]

    def search_fts(self, query: str, project_id: str, limit: int) -> List[GraphNode]:
        rows = self._store.search_all(self._agent_id, query, limit, project_id)
        return [_ainl_to_node(r) for r in rows]

    def validate_graph(self, project_id: str) -> Dict[str, Any]:
        return self._store.validate_graph(self._agent_id)

    def get_edges_from(
        self, node_id: str, edge_type: Optional[EdgeType] = None
    ) -> List[GraphEdge]:
        label = _edge_label(edge_type) if edge_type else ""
        if not label:
            # walk all labels — iterate common types
            edges: List[GraphEdge] = []
            for et in EdgeType:
                raw_nodes = self._store.walk_edges(node_id, et.value)
                for n in raw_nodes:
                    edges.append(GraphEdge(
                        id=str(uuid.uuid4()),
                        edge_type=et,
                        from_node=node_id,
                        to_node=n["id"],
                        created_at=int(time.time()),
                        confidence=1.0,
                    ))
            return edges
        raw_nodes = self._store.walk_edges(node_id, label)
        return [
            GraphEdge(
                id=str(uuid.uuid4()),
                edge_type=edge_type,  # type: ignore[arg-type]
                from_node=node_id,
                to_node=n["id"],
                created_at=int(time.time()),
                confidence=1.0,
            )
            for n in raw_nodes
        ]

    def get_edges_to(
        self, node_id: str, edge_type: Optional[EdgeType] = None
    ) -> List[GraphEdge]:
        label = _edge_label(edge_type) if edge_type else ""
        if not label:
            edges: List[GraphEdge] = []
            for et in EdgeType:
                raw_nodes = self._store.walk_edges_to(node_id, et.value)
                for n in raw_nodes:
                    edges.append(GraphEdge(
                        id=str(uuid.uuid4()),
                        edge_type=et,
                        from_node=n["id"],
                        to_node=node_id,
                        created_at=int(time.time()),
                        confidence=1.0,
                    ))
            return edges
        raw_nodes = self._store.walk_edges_to(node_id, label)
        return [
            GraphEdge(
                id=str(uuid.uuid4()),
                edge_type=edge_type,  # type: ignore[arg-type]
                from_node=n["id"],
                to_node=node_id,
                created_at=int(time.time()),
                confidence=1.0,
            )
            for n in raw_nodes
        ]

    def get_unresolved_failures(self, project_id: str, limit: int = 100) -> List[GraphNode]:
        rows = self._store.search_failures(self._agent_id, "*", limit)
        nodes = []
        for r in rows:
            n = _ainl_to_node(r)
            if n.project_id == project_id and not (n.data or {}).get("resolution"):
                nodes.append(n)
        return nodes[:limit]

    def query_goals(
        self, project_id: str, status: Optional[str] = None, limit: int = 50
    ) -> List[GraphNode]:
        """Query goal nodes for a project.

        Fast path: read goal_index.json (maintained by write_node) and
        round-trip the listed ids through read_node. Falls back to a full
        find_by_type("semantic") scan if the index is missing or empty so
        callers always see goals even on a fresh install.
        """
        index = self._read_goal_index()
        if index:
            candidates = [
                meta for meta in index.values()
                if meta.get("project_id") == project_id
                and (status is None or meta.get("status") == status)
            ]
            nodes: List[GraphNode] = []
            for meta in candidates:
                raw = self._store.read_node(meta["id"])
                if not raw:
                    continue
                n = _ainl_to_node(raw)
                if status and (n.data or {}).get("status") != status:
                    continue
                nodes.append(n)
                if len(nodes) >= limit:
                    break
            if nodes:
                return nodes
            # Fallthrough: index hit zero matches; do a fallback scan in case
            # the index missed an entry (defensive).

        # Fallback: scan all semantic rows (legacy behavior).
        rows = self._store.find_by_type("semantic")
        nodes = []
        for r in rows:
            pd = (r.get("plugin_data") or {})
            nt_raw = r.get("node_type", {})
            cluster = nt_raw.get("topic_cluster")
            is_goal = (
                pd.get("py_node_type") == "goal"
                or cluster == PLUGIN_GOAL_CLUSTER
                or cluster == "goal"  # legacy un-namespaced rows
            )
            if not is_goal:
                continue
            n = _ainl_to_node(r)
            if n.project_id != project_id:
                continue
            if status and (n.data or {}).get("status") != status:
                continue
            nodes.append(n)
        return nodes[:limit]

    # ── Anchored summary passthrough ──────────────────────────────────────────

    def upsert_anchored_summary(self, agent_id: str, payload: str) -> str:
        return self._store.upsert_anchored_summary(agent_id, payload)

    def fetch_anchored_summary(self, agent_id: str) -> Optional[str]:
        return self._store.fetch_anchored_summary(agent_id)

    # ── Maintenance stubs (Rust manages its own TTL/decay internally) ─────────

    def decay_node_confidence(
        self, project_id: str, older_than_days: int = 90,
        factor: float = 0.05, node_types=None
    ) -> int:
        return 0

    def delete_expired_nodes(
        self, project_id: str, ttl_days: int = 365, min_confidence: float = 0.05
    ) -> int:
        return 0

    def get_failure_trends(
        self, project_id: str, since_days: int = 7, min_count: int = 2
    ) -> List[Dict[str, Any]]:
        # Delegate to the Python sidecar DB for trend aggregation
        try:
            import sqlite3 as _sq, json as _json, time as _time
            from pathlib import Path as _Path
            _py_db = _Path(str(self.db_path)).parent / "ainl_memory.db"
            if not _py_db.exists():
                return []
            _since = int(_time.time()) - since_days * 86400
            _conn = _sq.connect(str(_py_db))
            try:
                rows = _conn.execute(
                    """SELECT json_extract(data,'$.error_type'),
                              json_extract(data,'$.tool'),
                              COUNT(*), MAX(created_at)
                       FROM ainl_graph_nodes
                       WHERE node_type='failure' AND project_id=? AND created_at>=?
                       GROUP BY 1,2 HAVING COUNT(*)>=?
                       ORDER BY 3 DESC""",
                    (project_id, _since, min_count),
                ).fetchall()
                return [
                    {'error_type': r[0], 'tool': r[1], 'count': r[2], 'most_recent': r[3]}
                    for r in rows
                ]
            finally:
                _conn.close()
        except Exception:
            return []

    # ── Autonomous task queue — delegate to Python sidecar ────────────────────
    # The autonomous_tasks table lives in ainl_memory.db (Python sidecar) so
    # the same data is visible regardless of which backend is active.

    def _sidecar_store(self):
        """Open a SQLiteGraphStore against the Python sidecar DB."""
        from pathlib import Path as _P
        try:
            from graph_store import SQLiteGraphStore as _S
        except ImportError:
            import sys as _sys
            _sys.path.insert(0, str(_P(__file__).parent))
            from graph_store import SQLiteGraphStore as _S
        _py_db = _P(str(self.db_path)).parent / "ainl_memory.db"
        return _S(_py_db)

    def create_autonomous_task(self, task_id, project_id, description,
                               schedule=None, trigger_type='scheduled',
                               next_run_at=None, created_by='user',
                               max_runs=None, priority=5):
        try:
            return self._sidecar_store().create_autonomous_task(
                task_id, project_id, description, schedule, trigger_type,
                next_run_at, created_by, max_runs, priority)
        except Exception:
            return {}

    def list_autonomous_tasks(self, project_id, status='active',
                              due_only=False, due_before=None, limit=50):
        try:
            return self._sidecar_store().list_autonomous_tasks(
                project_id, status, due_only, due_before, limit)
        except Exception:
            return []

    def get_autonomous_task(self, task_id):
        try:
            return self._sidecar_store().get_autonomous_task(task_id)
        except Exception:
            return None

    def update_autonomous_task(self, task_id, **kwargs):
        try:
            return self._sidecar_store().update_autonomous_task(task_id, **kwargs)
        except Exception:
            return False

    def mark_task_run(self, task_id, run_status, note=None, next_run_at=None):
        try:
            return self._sidecar_store().mark_task_run(
                task_id, run_status, note, next_run_at)
        except Exception:
            return False

    def cancel_autonomous_task(self, task_id):
        try:
            return self._sidecar_store().cancel_autonomous_task(task_id)
        except Exception:
            return False
