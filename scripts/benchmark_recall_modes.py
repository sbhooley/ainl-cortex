#!/usr/bin/env python3
"""
Micro-benchmark: TF-IDF vs hybrid (TF-IDF + lexical Jaccard) retrieval scores.

Uses the same token overlap helper as runtime hybrid mode. No network;
run from the plugin root with the venv activated:

  .venv/bin/python scripts/benchmark_recall_modes.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "mcp_server"))

from similarity import get_or_build_index, lexical_jaccard_overlap  # noqa: E402


def main() -> None:
    corpus = [
        ("n1", "fix sqlite migration error in auth module"),
        ("n2", "deploy kubernetes helm chart production"),
        ("n3", "graphql resolver pagination bug"),
    ]
    query = "sqlite migration error auth"
    cache = ROOT / "logs"
    cache.mkdir(parents=True, exist_ok=True)
    idx = get_or_build_index(corpus, "bench_project", cache, ttl_seconds=60)
    rows = []
    for nid, score in idx.query(query, top_k=len(corpus)):
        text = next(t for i, t in corpus if i == nid)
        lex = lexical_jaccard_overlap(query, text)
        hybrid = min(1.0, 0.7 * score + 0.3 * lex)
        rows.append((nid, score, lex, hybrid))
    print("node_id\ttfidf\tlex\t hybrid")
    for r in rows:
        print(f"{r[0]}\t{r[1]:.4f}\t{r[2]:.4f}\t{r[3]:.4f}")


if __name__ == "__main__":
    main()
