# Test remediation — top 30 impact items (164 failures → production coverage)

Baseline: **661 passed / 164 failed** (825 collected).

**Pass 1 (2026-05-19):** **750 passed / 74 failed** after autonomous MCP wiring, startup injection, store property, AINL absent payloads, harness fixes.

**Pass 2 (2026-05-19):** **809 passed / 12 skipped / 0 failed** — branch metadata, anchored summary imports, `memory_session_history`, config decay/TTL keys, decision mining, compaction recovery, failure trends, persona evolve fix, `TOOL_COUNT_MEMORY=22`, strict-native per-prompt flush (`accumulate_into_pending`), `link_resolutions` partial outcome + native edge fix, episode `session_id` stamping, `native_bindings_available()` skip gate, conftest PYTHONPATH/module hygiene.

## Tier 1 — Unblocks ~107 tests (autonomous + MCP integration)

| # | Item | Tests | Action |
|---|------|-------|--------|
| 1 | Wire **8 autonomous MCP tools** on `server.py` | ~48 `test_mcp_integration` | `memory_schedule_task`, `list_scheduled_tasks`, `approve`, `begin_task_execution`, `complete`, `cancel`, `update`, `list_autonomous_executions` |
| 2 | **Tool-call scope interceptor** (`active_task.json`) | ~15 integration | `_ALWAYS_ALLOWED_IN_TASK`, `tool_blocked_by_task_scope` in `call_tool` |
| 3 | **`config.json` → `autonomous_mode`** section | ~8 config tests | `enabled`, `inject_due_tasks_in_startup`, `due_tasks_lookahead_minutes`, `approved_autonomous_actions` |
| 4 | **`startup._inject_autonomous_blocks`** | ~20 startup/integration | Due block, approval block, path_scope filter, `memory_complete_task` hint |
| 5 | **`TOOL_COUNT_MEMORY = 21`** | 2 | Match `list_tools` memory_* count (13 existing + 8 autonomous) |
| 6 | **`autonomous_scheduler` import** in server | 1 | `is_valid_schedule` / `parse_next_run` on schedule/complete |

## Tier 2 — Import / harness (~30 tests)

| # | Item | Tests | Action |
|---|------|-------|--------|
| 7 | Fix **`test_a2a_gating`** package import | 4 | `import mcp_server.server` (not bare `server`) |
| 8 | Strengthen **`tests/conftest.py`** path hygiene | collection | Strip `/private/tmp/…/ainl-cortex*` shadow paths |
| 9 | **`a2a_tools` daemon path** fallback | import | Resolve `hooks/shared` without stale `shared` package |
| 10 | CI/doc: run tests with **`.venv-ainl`** or plugin venv | ops | Document in `CONTRIBUTING` / `pytest` hint |

## Tier 3 — Branch memory + git metadata (~21 tests)

| # | Item | Tests | Action |
|---|------|-------|--------|
| 11 | **`git_branch` on episode nodes** | 4 `test_branch_memory` | `create_episode_node` + `record_prompt_summary` |
| 12 | **Branch-filtered recall** signatures + impl | 4 `test_thorough_features` | `git_branch` param on `memory_recall_context` / `memory_search` |
| 13 | **Nested `data.git_branch`** in recall filter | 1 | Read branch from node payload when filtering |

## Tier 4 — Session delta / anchored summary (~9 tests)

| # | Item | Tests | Action |
|---|------|-------|--------|
| 14 | **`session_context` / anchored summary** roundtrip | 4 `test_delta_gates` | Native or Python fallback for `write_anchored_summary` |
| 15 | **Staleness gate** for anchored summary | 1 | Age + plugin-node exclusion in gate |
| 16 | **`test_session_delta.py`** inbox paths | 1 | Align with `{project_id}_session_id.txt` |

## Tier 5 — Failure advisor + store failure (~12 tests)

| # | Item | Tests | Action |
|---|------|-------|--------|
| 17 | **Auto-extract `file`** from error in `memory_store_failure` | 2 | Regex in server handler (tests expect wiring) |
| 18 | **Goal ↔ episode `node_id` linking** on auto-update | 1 | Goal tracker uses episode id |
| 19 | **Native `get_unresolved_failures`** | 1 | Bridge or Python store method |
| 20 | **`PatternExtractor.extract_signals`** (persona evolve) | runtime errors | Add stub or fix extractor API |

## Tier 6 — Strict native + roundtrip (~10 tests)

| # | Item | Tests | Action |
|---|------|-------|--------|
| 21 | **Strict native mode** env + recall path | 4 `test_strict_native_mode` | Honor `store_backend: native` in tests |
| 22 | **Native roundtrip** episode write/read | 2 | Ensure native DB schema + export parity |
| 23 | **Output compression on native finalize** | gap | Wire `stop.py` compression for native path |

## Tier 7 — Gap closures + misc (~15 tests)

| # | Item | Tests | Action |
|---|------|-------|--------|
| 24 | **`test_gap_closures.py`** feature flags | 8 | Map each assertion to config/hook surface |
| 25 | **`test_memory_reconcile.py`** | 5 | Environment snapshot reconcile in native/Python |
| 26 | **MCP `memory_store_failure` optional fields** | done | `file`, `command`, `stack_trace`, `resolution` |
| 27 | **Startup scope-lock clear** | done | `_clear_stale_scope_lock` |
| 28 | **Cost-control native tests** | done | `test_cost_control_native.py` |
| 29 | **Procedure cards after native recall** | done | `fetch_patterns_for_project` in `user_prompt_submit` |
| 30 | **Full-suite gate in CI** | 0 | `pytest tests/ -q` target: 0 failed before release |

## Pass 2+ (after tier 1–2 green)

- AINL tools absent-package tests (install `ainativelang[mcp]` in CI or mock)
- `test_thorough_features` remaining MCP/recall contracts
- Conversation-detection parity script vs ArmaraOS Rust
- MCP stdio integration tests for `cortex_cost_snapshot`, `ainl_promote_pattern`

## Tracking

Update this file when a tier completes. Run:

```bash
python -m pytest tests/ -q --tb=no 2>&1 | tail -3
python -m pytest tests/test_autonomous_mode.py tests/test_mcp_integration.py -q
```
