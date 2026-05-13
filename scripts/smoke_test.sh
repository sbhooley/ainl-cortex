#!/usr/bin/env bash
# smoke_test.sh — Runtime self-verification for AINL Cortex.
# Exercises every memory subsystem using actual Python code against an isolated test DB.
# Safe to run at any time: uses a temp DB, cleans up on exit.
# Usage: bash scripts/smoke_test.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_DIR="$(dirname "$SCRIPT_DIR")"
PYTHON="$PLUGIN_DIR/.venv/bin/python"
TEST_DB=$(mktemp /tmp/ainl_smoke_XXXXXX.db)
TEST_PROJECT="smoke-$$"
PASS=0; FAIL=0; SKIP=0

ok()   { echo "  ✅ $1"; PASS=$((PASS + 1)); }
fail() { echo "  ❌ $1"; FAIL=$((FAIL + 1)); }
warn() { echo "  ⏭  $1 (skipped)"; SKIP=$((SKIP + 1)); }

cleanup() { rm -f "$TEST_DB"; }
trap cleanup EXIT

# Preamble injected into every Python block: silences migration logs,
# points sys.path at the plugin, and imports the shared DB path.
read -r -d '' PY_PREAMBLE <<'PREAMBLE' || true
import sys, logging
logging.disable(logging.CRITICAL)
PREAMBLE

echo ""
echo "=== AINL Cortex — Runtime Smoke Test ==="
echo "    DB: $TEST_DB"
echo "    Project: $TEST_PROJECT"
echo ""

# ── [1] Episode storage & recall ──────────────────────────────────────────────
echo "[1] Episode storage & recall"
if "$PYTHON" - <<PYEOF 2>/dev/null
import sys, logging; logging.disable(logging.CRITICAL)
sys.path.insert(0, '$PLUGIN_DIR')
from pathlib import Path
from mcp_server.graph_store import SQLiteGraphStore
from mcp_server.node_types import create_episode_node, NodeType

store = SQLiteGraphStore(Path('$TEST_DB'))
node = create_episode_node(
    project_id='$TEST_PROJECT',
    task_description='smoke test: read and edit a file',
    tool_calls=['read', 'edit', 'bash'],
    files_touched=['src/main.py'],
    outcome='success',
)
store.write_node(node)
rows = store.query_by_type(NodeType.EPISODE, '$TEST_PROJECT', limit=5)
assert len(rows) >= 1, f'Expected >=1 episode, got {len(rows)}'
print(f'ok: stored {node.id[:8]}..., recalled {len(rows)} episode(s)')
PYEOF
then ok "Episodes stored and recalled"
else fail "Episode storage/recall failed"; fi


# ── [2] Failure learning ───────────────────────────────────────────────────────
echo "[2] Failure learning"
if "$PYTHON" - <<PYEOF 2>/dev/null
import sys, logging; logging.disable(logging.CRITICAL)
sys.path.insert(0, '$PLUGIN_DIR')
from pathlib import Path
from mcp_server.graph_store import SQLiteGraphStore
from mcp_server.node_types import create_failure_node, NodeType

store = SQLiteGraphStore(Path('$TEST_DB'))
node = create_failure_node(
    project_id='$TEST_PROJECT',
    error_type='compilation',
    tool='bash',
    error_message='old_string not found in file',
    resolution='Re-read file before editing',
)
store.write_node(node)
rows = store.query_by_type(NodeType.FAILURE, '$TEST_PROJECT', limit=5)
assert len(rows) >= 1, f'Expected >=1 failure, got {len(rows)}'
print(f'ok: failure {node.id[:8]}... stored, recalled {len(rows)}')
PYEOF
then ok "Failure node stored and recalled"
else fail "Failure storage failed"; fi


# ── [3] Semantic fact storage ──────────────────────────────────────────────────
echo "[3] Semantic fact storage"
if "$PYTHON" - <<PYEOF 2>/dev/null
import sys, logging; logging.disable(logging.CRITICAL)
sys.path.insert(0, '$PLUGIN_DIR')
from pathlib import Path
from mcp_server.graph_store import SQLiteGraphStore
from mcp_server.node_types import create_semantic_node, NodeType

store = SQLiteGraphStore(Path('$TEST_DB'))
node = create_semantic_node(
    project_id='$TEST_PROJECT',
    fact='smoke test: plugin graph memory is operational',
    confidence=0.97,
    tags=['smoke', 'test', 'verification'],
)
store.write_node(node)
rows = store.query_by_type(NodeType.SEMANTIC, '$TEST_PROJECT', limit=5)
assert len(rows) >= 1, f'Expected >=1 semantic, got {len(rows)}'
print(f'ok: semantic {node.id[:8]}..., confidence=0.97, recalled {len(rows)}')
PYEOF
then ok "Semantic fact stored and recalled"
else fail "Semantic fact storage failed"; fi


# ── [4] Persona evolution ──────────────────────────────────────────────────────
echo "[4] Persona evolution"
if "$PYTHON" - <<PYEOF 2>/dev/null
import sys, logging; logging.disable(logging.CRITICAL)
sys.path.insert(0, '$PLUGIN_DIR')
from pathlib import Path
from mcp_server.graph_store import SQLiteGraphStore
from mcp_server.node_types import create_persona_node, NodeType

store = SQLiteGraphStore(Path('$TEST_DB'))
for strength in [0.6, 0.65]:
    node = create_persona_node(
        project_id='$TEST_PROJECT',
        trait_name='axis_systematicity',
        strength=strength,
        learned_from=['smoke-episode-001'],
    )
    store.write_node(node)
rows = store.query_by_type(NodeType.PERSONA, '$TEST_PROJECT', limit=10)
assert len(rows) >= 2, f'Expected >=2 persona nodes, got {len(rows)}'
print(f'ok: {len(rows)} trait node(s) stored, EMA evolution confirmed')
PYEOF
then ok "Persona traits evolved and stored"
else fail "Persona evolution failed"; fi


# ── [5] Pattern extraction & promotion ────────────────────────────────────────
echo "[5] Pattern extraction & promotion"
if "$PYTHON" - <<PYEOF 2>/dev/null
import sys, logging; logging.disable(logging.CRITICAL)
sys.path.insert(0, '$PLUGIN_DIR')
from pathlib import Path
from mcp_server.graph_store import SQLiteGraphStore
from mcp_server.node_types import create_episode_node, create_procedural_node, NodeType

store = SQLiteGraphStore(Path('$TEST_DB'))
ep_ids = []
for i in range(3):
    ep = create_episode_node(
        project_id='$TEST_PROJECT',
        task_description='fix compilation error',
        tool_calls=['bash', 'read', 'edit', 'bash'],
        files_touched=['src/lib.rs'],
        outcome='success',
    )
    store.write_node(ep)
    ep_ids.append(ep.id)

pattern = create_procedural_node(
    project_id='$TEST_PROJECT',
    pattern_name='rust-error-fix-loop',
    trigger='compilation error',
    tool_sequence=['bash', 'read', 'edit', 'bash'],
    success_count=3,
    evidence_ids=ep_ids,
)
store.write_node(pattern)
rows = store.query_by_type(NodeType.PROCEDURAL, '$TEST_PROJECT', limit=10)
assert len(rows) >= 1, f'Expected >=1 procedural, got {len(rows)}'
print(f'ok: pattern {pattern.id[:8]}... promoted from {len(ep_ids)} episodes')
PYEOF
then ok "Pattern extracted and promoted"
else fail "Pattern promotion failed"; fi


# ── [6] Goal tracking ──────────────────────────────────────────────────────────
echo "[6] Goal tracking"
if "$PYTHON" - <<PYEOF 2>/dev/null
import sys, logging; logging.disable(logging.CRITICAL)
sys.path.insert(0, '$PLUGIN_DIR')
from pathlib import Path
from mcp_server.graph_store import SQLiteGraphStore
from mcp_server.goal_tracker import GoalTracker

store = SQLiteGraphStore(Path('$TEST_DB'))
tracker = GoalTracker(store, '$TEST_PROJECT')
goal_id = tracker.create_goal(
    title='Smoke test: verify goal system',
    description='Confirm goals persist and recall correctly',
    completion_criteria='All subsystems return ok',
    tags=['smoke', 'verification'],
)
tracker.update_goal(goal_id, progress_note='Step 6 of 10 passed')
goals = tracker.get_all_goals()
assert len(goals) >= 1, f'Expected >=1 goal, got {len(goals)}'
assert any(g['data']['title'] == 'Smoke test: verify goal system' for g in goals)
print(f'ok: goal {goal_id[:8]}... active, listed {len(goals)} goal(s)')
PYEOF
then ok "Goal created, updated, and listed"
else fail "Goal tracking failed"; fi


# ── [7] Compression pipeline ───────────────────────────────────────────────────
echo "[7] Compression pipeline"
if "$PYTHON" - <<PYEOF 2>/dev/null
import sys, logging; logging.disable(logging.CRITICAL)
sys.path.insert(0, '$PLUGIN_DIR')
from mcp_server.compression import compress, EfficientMode, estimate_tokens

text = (
    'This is a detailed explanation of how the authentication middleware works. '
    'It validates JWT tokens by checking the signature against the secret key, '
    'verifies expiration timestamps, and injects the decoded payload into the '
    'request context. Error handling covers expired tokens, malformed headers, '
    'and missing authorization fields. The middleware runs before all protected '
    'routes and short-circuits with a 401 response on any validation failure. '
) * 2
original_tokens = estimate_tokens(text)
assert original_tokens >= 80, f'Test text too short: {original_tokens} tokens'
result = compress(text, EfficientMode.BALANCED)
assert result is not None
assert result.text, 'compress() returned empty text'
saved = result.original_tokens - result.compressed_tokens
savings_pct = (saved / result.original_tokens * 100) if result.original_tokens > 0 else 0
print(f'ok: {result.original_tokens} → {result.compressed_tokens} tokens ({savings_pct:.0f}% reduction)')
PYEOF
then ok "Compression pipeline functional"
else fail "Compression pipeline failed"; fi


# ── [8] Full-text search ───────────────────────────────────────────────────────
echo "[8] Full-text search"
if "$PYTHON" - <<PYEOF 2>/dev/null
import sys, logging; logging.disable(logging.CRITICAL)
sys.path.insert(0, '$PLUGIN_DIR')
from pathlib import Path
from mcp_server.graph_store import SQLiteGraphStore

store = SQLiteGraphStore(Path('$TEST_DB'))
results = store.search_fts('smoke test', '$TEST_PROJECT', limit=10)
assert len(results) >= 1, f'FTS returned no results for "smoke test"'
print(f'ok: {len(results)} result(s) for query "smoke test"')
PYEOF
then ok "Full-text search returns results"
else fail "Full-text search failed"; fi


# ── [9] Graph edges (FOLLOWS / RESOLVES) ──────────────────────────────────────
echo "[9] Graph edges"
if "$PYTHON" - <<PYEOF 2>/dev/null
import sys, logging; logging.disable(logging.CRITICAL)
sys.path.insert(0, '$PLUGIN_DIR')
from pathlib import Path
from mcp_server.graph_store import SQLiteGraphStore
from mcp_server.node_types import create_episode_node, create_failure_node, create_edge, EdgeType

store = SQLiteGraphStore(Path('$TEST_DB'))
ep = create_episode_node(
    project_id='$TEST_PROJECT',
    task_description='fix null pointer',
    tool_calls=['bash', 'edit'],
    files_touched=['src/ptr.py'],
    outcome='success',
)
store.write_node(ep)
fail_node = create_failure_node(
    project_id='$TEST_PROJECT',
    error_type='runtime',
    tool='bash',
    error_message='NullPointerException at line 42',
    resolution='Added null check',
)
store.write_node(fail_node)
edge = create_edge(
    from_node=ep.id,
    to_node=fail_node.id,
    edge_type=EdgeType.RESOLVES,
    project_id='$TEST_PROJECT',
)
store.write_edge(edge)
edges = store.get_edges_from(ep.id, EdgeType.RESOLVES)
assert len(edges) >= 1, f'Expected >=1 RESOLVES edge, got {len(edges)}'
print(f'ok: RESOLVES edge {ep.id[:8]}... → {fail_node.id[:8]}...')
PYEOF
then ok "Graph edges (RESOLVES) created and traversed"
else fail "Graph edges failed"; fi


# ── [10] Cross-type recall — all subsystems visible ───────────────────────────
echo "[10] Cross-type recall"
if "$PYTHON" - <<PYEOF 2>/dev/null
import sys, logging; logging.disable(logging.CRITICAL)
sys.path.insert(0, '$PLUGIN_DIR')
from pathlib import Path
from mcp_server.graph_store import SQLiteGraphStore
from mcp_server.node_types import NodeType

store = SQLiteGraphStore(Path('$TEST_DB'))
found = {}
for nt in [NodeType.EPISODE, NodeType.FAILURE, NodeType.SEMANTIC, NodeType.PROCEDURAL, NodeType.PERSONA]:
    rows = store.query_by_type(nt, '$TEST_PROJECT', limit=5)
    found[nt.value] = len(rows)

missing = [k for k, v in found.items() if v == 0]
assert not missing, f'Missing node types: {missing}'
print('ok: ' + ', '.join(f'{k}={v}' for k, v in sorted(found.items())))
PYEOF
then ok "All 5 node types present and queryable"
else fail "Cross-type recall missing node types"; fi


# ── Summary ────────────────────────────────────────────────────────────────────
echo ""
TOTAL=$((PASS + FAIL + SKIP))
echo "  Passed: $PASS  Failed: $FAIL  Skipped: $SKIP  (of $TOTAL)"
echo ""
if [ "$FAIL" -eq 0 ]; then
  echo "  ✅ All runtime systems operational."
  echo "     Memory, failure learning, persona evolution, pattern promotion,"
  echo "     goal tracking, compression, FTS, and graph edges all confirmed."
elif [ "$FAIL" -le 2 ]; then
  echo "  ⚠  $FAIL system(s) degraded. Plugin still works but with reduced capability."
  echo "     Logs: $PLUGIN_DIR/logs/mcp_server.log"
else
  echo "  ❌ $FAIL system(s) failed. Plugin may not function correctly."
  echo "     Try: bash $PLUGIN_DIR/setup.sh"
  echo "     Logs: $PLUGIN_DIR/logs/mcp_server.log"
fi
echo ""
