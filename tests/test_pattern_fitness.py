"""Procedural pattern fitness after successful ``ainl_run``."""

import uuid

from mcp_server.graph_store import SQLiteGraphStore
from mcp_server.node_types import NodeType, create_procedural_node
from mcp_server.pattern_fitness import record_success


def test_record_success_bumps_matching_adapter_pattern(tmp_path):
    store = SQLiteGraphStore(tmp_path / "g.db")
    pid = "proj-" + uuid.uuid4().hex[:8]
    node = create_procedural_node(
        project_id=pid,
        pattern_name="http_cache_flow",
        trigger="after repeated http+cache runs",
        tool_sequence=["http", "cache"],
        description="demo",
    )
    node.data["fitness"] = 0.5
    store.write_node(node)

    out = record_success(
        store,
        pid,
        adapters={"enable": ["http", "cache"]},
    )
    assert out["ok"] is True
    assert out["updated"] == 1

    refreshed = store.query_by_type(NodeType.PROCEDURAL, pid, limit=10)[0]
    assert float(refreshed.data.get("fitness", 0)) > 0.5
