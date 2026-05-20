#!/usr/bin/env bash
# Compare Python conversation_detection with armara-provider-api Rust tests corpus.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CORPUS="${ROOT}/tests/fixtures/conversation_detection_corpus.json"
PY="${PYTHON:-python3}"

if [[ ! -f "${CORPUS}" ]]; then
  echo "missing corpus: ${CORPUS}" >&2
  exit 1
fi

export PYTHONPATH="${ROOT}/hooks:${ROOT}${PYTHONPATH:+:${PYTHONPATH}}"

echo "== Python corpus (conversation_detection) =="
"${PY}" -c "
import json
import sys
from pathlib import Path

root = Path('${ROOT}')
sys.path.insert(0, str(root / 'hooks'))
from shared.conversation_detection import has_action_intent

corpus = json.loads(Path('${CORPUS}').read_text(encoding='utf-8'))
failed = 0
for i, row in enumerate(corpus):
    got = has_action_intent(row['prompt'])
    want = bool(row['expect_action'])
    if got != want:
        failed += 1
        print(f'FAIL[{i}] prompt={row[\"prompt\"]!r} got={got} want={want}')
if failed:
    print(f'Python corpus: {failed} mismatch(es)')
    sys.exit(1)
print(f'Python corpus: {len(corpus)} cases OK')
"

ARMARA_ROOT="${ARMARAOS_ROOT:-${ARMARA_ROOT:-}}"
if [[ -z "${ARMARA_ROOT}" ]]; then
  for candidate in \
    "${ROOT}/../../armaraos" \
    "${ROOT}/../../../openclaw/workspace/armaraos" \
    "${HOME}/.openclaw/workspace/armaraos"; do
    if [[ -f "${candidate}/crates/armara-provider-api/src/conversation_detection.rs" ]]; then
      ARMARA_ROOT="$(cd "${candidate}" && pwd)"
      break
    fi
  done
fi

if [[ -n "${ARMARA_ROOT}" && -d "${ARMARA_ROOT}/crates/armara-provider-api" ]]; then
  echo "== Rust tests (armara-provider-api conversation_detection) =="
  (cd "${ARMARA_ROOT}" && cargo test -p armara-provider-api conversation_detection -- --nocapture)
else
  echo "skip Rust parity: set ARMARAOS_ROOT to armaraos checkout (optional)"
fi

echo "parity check OK"
