# Migrating Python ↔ Native (Rust) backend

This plugin ships two storage backends (see `CLAUDE.md` § *Backend Selection*).
Migration is a **5-phase, gated, reversible** flow; nothing happens
automatically. The wrapper script orchestrates the whole thing:

```bash
cd ~/.claude/plugins/ainl-cortex
bash scripts/migrate_python_to_native.sh
```

If anything fails, the wrapper exits non-zero **before** flipping the
`store_backend`, so you can roll back without data loss.

---

## The 5 phases

```
Phase 1: Build native      ──▶  ainl_native importable check
Phase 2: Dry run           ──▶  Catches schema drift; no writes
Phase 3: Real migration    ──▶  Per-project atomic write to ainl_native.db.staging
                                 → os.replace onto ainl_native.db only on zero errors
Phase 4: Verification      ──▶  Row counts + sample round-trip
                                 (logs/verify_<UTC>.json)
Phase 5: Inject + flip     ──▶  Adds verify_status=passed to migration report
                                 → flips memory.store_backend to "native"
```

`migrate_to_native.py --flip-config` refuses to flip unless **all** of:
* `logs/migration_latest.json` exists
* report is `< 5 minutes old`
* `errors == 0`
* `verify_status == "passed"`

`--force` exists, but using it skips every safety net — only do this if you
deeply understand the consequences.

---

## Manual flow (per-phase)

If you need to skip / repeat a single phase, run the underlying scripts:

```bash
# Phase 1 — sanity check
.venv/bin/python -c "import ainl_native"

# Phase 2 — dry run (no writes)
.venv/bin/python migrate_to_native.py --dry-run --strict

# Phase 3 — atomic migration (per-project commit-or-rollback)
.venv/bin/python migrate_to_native.py --strict

# Phase 4 — verification
.venv/bin/python scripts/verify_migration.py

# Phase 5a — inject verify status into the migration report
.venv/bin/python migrate_to_native.py --inject-verify-status passed

# Phase 5b — flip config.json
.venv/bin/python migrate_to_native.py --flip-config
```

`--project-hash <id>` on `migrate_to_native.py` and `verify_migration.py`
restricts the operation to a single project graph_memory directory.

---

## Atomicity guarantee

`migrate_project()` in `migrate_to_native.py` writes to
`<gm_dir>/ainl_native.db.staging` first. The native handle is dropped (so SQLite
flushes), then `os.replace(staging, ainl_native.db)` atomically commits.

On any per-row write failure:
1. The staging file is `unlink()`d.
2. The live `ainl_native.db` is NEVER touched (still empty or still old).
3. The per-project entry in the JSON report shows `committed=false` and lists
   the offending node/edge ids in `errors`.
4. With `--strict`, the script exits non-zero and refuses to flip.

So the worst-case failure mode is: a stale `ainl_native.db.staging` file (which
the next run cleans up), plus a fresh JSON report telling you exactly which
node failed and why.

---

## Rollback

The Python sidecar (`ainl_memory.db`) is **always** preserved during migration
— `migrate_to_native.py` only reads from it. To return to the Python backend:

```bash
# Just flip config back (Python sidecar still has all the data)
.venv/bin/python migrate_to_python.py

# Optionally also delete the (possibly partial) native DB so a fresh
# re-migration starts clean
.venv/bin/python migrate_to_python.py --purge-native

# Preview without writing
.venv/bin/python migrate_to_python.py --purge-native --dry-run
```

Rollback removes:
* `ainl_native.db` (and `-wal`, `-shm`)
* `goal_index.json`

It does NOT touch `ainl_memory.db` or any backup files.

---

## Reports under `logs/`

* `logs/migration_<UTC>.json` — per-project migration result, with
  `nodes_written/total`, `committed`, list of errors, `verify_status` (filled
  in by phase 5a). Symlinked as `logs/migration_latest.json`.
* `logs/verify_<UTC>.json` — per-project verifier result, with row-count
  parity, sample round-trip mismatches (capped at 50), and recall smoke
  outcome. Symlinked as `logs/verify_latest.json`.
* `logs/rollback_<UTC>.json` — `migrate_to_python.py` output. Symlinked as
  `logs/rollback_latest.json`.

The wrapper script reads `logs/migration_latest.json` between phases — if you
edit reports manually, make sure both the symlink target and the underlying
file stay in sync (or run with `--force` to skip the gate).

---

## Common failure modes

| Symptom | Cause | Fix |
|---|---|---|
| `ERROR: ainl_native module not built` | `.venv/bin/maturin develop` was never run, or Rust isn't installed. | `bash setup.sh --auto-install-rust` then re-run the wrapper. |
| Phase 3 reports `errors > 0` | Schema drift between Python and Rust types (rare; usually a hand-edited DB). | Inspect the per-project `errors` array in `logs/migration_latest.json`; the offending node id + node_type point you at the row. Fix the source DB and re-run, or skip just that project with `--project-hash <other_id>`. |
| Phase 4 reports `mismatches` | A field round-trip lost data (most often a Goal whose `plugin_data` schema changed). | The verifier's per-mismatch entry shows `python` vs `rust` values — usually a missing back-compat branch in `_ainl_to_node`. Don't flip the config; report the mismatch (or roll back). |
| `ERROR: migration report is stale` | More than 5 minutes elapsed between phase 3 and phase 5. | Re-run phase 3; the freshness window is intentional so a long-stale report can't be replayed days later. |
| Phase 5 wrapper hangs after `flip-config` | The plugin daemon already cached the old `store_backend`. | Restart Claude Code so `hooks/shared/config.py:read_config` reloads. |

---

## Project isolation (issue 1) and migration

The migration scripts work **per project** (`~/.claude/projects/<project_id>/graph_memory`),
exactly as the plugin organizes data on disk. They do NOT change the
`project_id` of any node — that's the backfill's job:

```bash
.venv/bin/python scripts/repartition_by_repo.py --dry-run     # preview
.venv/bin/python scripts/repartition_by_repo.py               # execute
.venv/bin/python scripts/repartition_by_repo.py --purge-legacy
```

Recommended order if you are going Python → Native AND switching to per-repo
project isolation:

1. Run the repartition first (`scripts/repartition_by_repo.py`). This works
   on `ainl_memory.db` only and rewrites `project_id` on each node.
2. Then run the native migration (`bash scripts/migrate_python_to_native.sh`).
   The new project ids carry over byte-exact into `ainl_native.db`.
3. Optional: `--purge-legacy` on repartition + `--purge-native` on rollback
   give you a clean slate if you change your mind.
