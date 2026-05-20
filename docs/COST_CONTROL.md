# Cost control (AINL Cortex)

AINL Cortex reduces **injectable context** and **chat-orchestration waste** in Claude Code. It does **not** change Anthropic subscription limits or billable API pricing directly.

## What we measure (honest scope)

| Metric | Meaning |
|--------|---------|
| `compression_saved_tokens_est` | Tokens saved by eco compression on memory brief / user prompt (chars÷4 heuristic) |
| `recall_injected_chars` | Graph-memory brief size injected this turn |
| `recall_skips` | Turns where recall was skipped (`conversation_only`, `prompt_too_short`, …) |
| `tool_digests_count` | Large tool outputs stored as digests + blobs |
| AINL promotion counterfactual | **Analytical orchestration tokens** (`baseline_C_analytical`) — see [AI Native Lang claims](https://github.com/sbhooley/ainativelang/blob/main/docs/CLAIMS_AND_EVIDENCE.md) |

SessionStart banner and MCP tool `cortex_cost_snapshot` expose these aggregates (no prompt text).

## Cost profiles

Set in `config.json`:

```json
"cost_profile": "balanced"
```

| Profile | Behavior |
|---------|----------|
| `balanced` | Default recall + eco compression |
| `subscription_safe` | Minimal recall, tighter caps, MCP chat hint on |
| `max_learning` | Verbose recall, compression off |

Explicit keys in `config.json` win over preset merges.

## Conversation-only gate

When `has_action_intent` is false (e.g. “thanks”, “ok”):

- Skips memory recall, goals, failure advisor, AINL detection nudge
- Optional short MCP suppression hint (`conversation.suppress_mcp_hint`, opt out with `AINL_CORTEX_SUPPRESS_MCP_HINT=0`)

Capture hooks still run; graph memory updates on `stop`.

## Tool digests

Large `Read` / `Grep` / `Bash` / MCP results are summarized (zero LLM) and stored under `~/.claude/projects/<id>/graph_memory/tool_blobs/`. Recall injects digests; full text via MCP `memory_get_tool_outcome`.

## AINL promotion

After repeated similar tool trajectories, hooks may suggest compiling a strict-valid `.ainl` workflow. MCP: `ainl_promote_pattern`. Savings figures are **orchestration-token estimates**, not API dollars.

## ArmaraOS bridge

When the A2A bridge to ArmaraOS is running, SessionStart may append daemon eco hints from `GET /api/usage/summary` (graceful no-op if unavailable).

## Operator runbook (manual)

1. **Chat turn** — send “thanks”; confirm no `## Memory` block in hook output; `recall_skip` reason `conversation_only` in `logs/hook_metrics.jsonl`.
2. **Action turn** — send “fix auth.py tests”; confirm memory brief injected.
3. **Cost snapshot** — call MCP `cortex_cost_snapshot` with `project_id`; verify non-empty `session` after a few turns.
4. **Profile** — set `cost_profile: subscription_safe`, restart session; recall should be shorter (minimal headings).

## Test coverage (audit)

| Feature | Unit tests | Hook / integration | Python backend | Native (`ainl_native`) backend |
|---------|------------|--------------------|----------------|------------------------------|
| Conversation gate | `test_conversation_detection.py` | `test_cost_control_hooks.py` | Skip recall on “thanks” | Same skip (gate runs before native recall) |
| Eco metrics / ledger | `test_hook_metrics_aggregate.py`, `test_cortex_cost_snapshot.py` | Partial | Yes | Metrics shared; native uses same hooks |
| Cost profiles | `test_cost_profiles.py` | — | Yes | Profile applies to hooks/MCP |
| Tool digest | `test_tool_digest.py` | `post_tool_use` manual | Yes | Digest capture backend-agnostic |
| AINL promotion | `test_orchestration_ledger.py`, example path test | — | MCP `ainl_promote_pattern` | N/A |
| Recall dropped nodes | `test_recall_dropped_nodes.py`, `test_cost_control_native.py` | — | `format_memory_context_markdown` | `pack_native_brief` + `recall_meta` estimates drops |
| Procedure cards | `test_procedure_cards.py`, `test_cost_control_native.py` | `user_prompt_submit` | Python recall + cards | Native recall loads patterns from Python DB when `pattern_count > 0`, then same card matcher |
| Project doc sync | `test_project_context_sync.py` | startup | Python graph store | Native DB not auto-synced on startup |
| ArmaraOS bridge | `test_armaraos_cost_bridge.py` | Manual with daemon | Optional HTTP | Same |

**Automated (Pass 3):** `scripts/check_conversation_detection_parity.sh` (Python corpus + optional Rust via `ARMARAOS_ROOT`), MCP dispatch tests in `test_cost_control_mcp.py`, `ainl_run` → `pattern_fitness.record_success` in `test_pattern_fitness.py`.

Run parity script:

```bash
./scripts/check_conversation_detection_parity.sh
# optional: ARMARAOS_ROOT=/path/to/armaraos ./scripts/check_conversation_detection_parity.sh
```

Run cost-control tests:

```bash
.venv/bin/python -m pytest tests/test_conversation_detection.py tests/test_cost_profiles.py \
  tests/test_hook_metrics_aggregate.py tests/test_cortex_cost_snapshot.py tests/test_tool_digest.py \
  tests/test_recall_dropped_nodes.py tests/test_orchestration_ledger.py tests/test_cost_control_hooks.py \
  tests/test_armaraos_cost_bridge.py tests/test_procedure_cards.py tests/test_project_context_sync.py \
  tests/test_cost_control_native.py tests/test_cost_control_mcp.py tests/test_pattern_fitness.py \
  tests/test_failure_production_gaps.py -q
```

## Related docs

- [COMPRESSION_ECO_MODE.md](./COMPRESSION_ECO_MODE.md) — eco pipeline, cache state file
- [CONVERSATION_ACTION_INTENT](https://github.com/sbhooley/ainl-inference-server/blob/main/docs/architecture/CONVERSATION_ACTION_INTENT.md) — shared action-intent spec with ArmaraOS
