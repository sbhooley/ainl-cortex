"""
AINL Similarity Engine

TF-IDF based semantic similarity for graph node retrieval.
Uses sklearn when available, falls back to pure-Python implementation.
Caches the index to disk with TTL-based invalidation so repeated calls
within the same session are O(1).
"""

import json
import math
import logging
import pickle
import time
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Try to import sklearn; use pure-Python fallback if unavailable
try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity as sk_cosine
    import numpy as np
    _SKLEARN_AVAILABLE = True
except ImportError:
    _SKLEARN_AVAILABLE = False
    logger.info("sklearn not available — using pure-Python TF-IDF")


# ---------------------------------------------------------------------------
# Pure-Python TF-IDF fallback
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> List[str]:
    """Simple whitespace + punctuation tokenizer."""
    import re
    return re.findall(r'[a-z0-9_]+', text.lower())


def _build_idf(corpus: List[str]) -> Dict[str, float]:
    n = len(corpus)
    df: Counter = Counter()
    for doc in corpus:
        for term in set(_tokenize(doc)):
            df[term] += 1
    return {term: math.log((n + 1) / (count + 1)) + 1.0 for term, count in df.items()}


def _tfidf_vec(text: str, idf: Dict[str, float]) -> Dict[str, float]:
    tokens = _tokenize(text)
    if not tokens:
        return {}
    tf = Counter(tokens)
    n = len(tokens)
    return {term: (count / n) * idf.get(term, 0.0) for term, count in tf.items()}


def lexical_jaccard_overlap(query: str, doc: str) -> float:
    """Token-set Jaccard similarity in [0, 1], cheap hybrid signal vs TF-IDF alone."""
    if not query or not doc:
        return 0.0
    a = set(_tokenize(query))
    b = set(_tokenize(doc))
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return float(inter) / float(union) if union else 0.0


def _cosine(a: Dict[str, float], b: Dict[str, float]) -> float:
    dot = sum(a.get(t, 0.0) * v for t, v in b.items())
    mag_a = math.sqrt(sum(v * v for v in a.values()))
    mag_b = math.sqrt(sum(v * v for v in b.values()))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


# ---------------------------------------------------------------------------
# TFIDFIndex
# ---------------------------------------------------------------------------

class TFIDFIndex:
    """
    Lazily-built, disk-cached TF-IDF index over graph node embedding texts.

    Cache file lives next to the DB:
        {db_dir}/tfidf_index_{project_id}.pkl

    Cache is invalidated when:
    - The TTL expires (default 300 s)
    - The node count in the corpus changes
    """

    def __init__(self, cache_dir: Path, project_id: str, ttl_seconds: int = 300):
        self.cache_path = cache_dir / f"tfidf_index_{project_id}.pkl"
        self.ttl = ttl_seconds
        self._node_ids: List[str] = []
        self._texts: List[str] = []
        self._built_at: float = 0.0
        self._idf: Optional[Dict[str, float]] = None          # pure-Python path
        self._vectorizer: Optional["TfidfVectorizer"] = None   # sklearn path
        self._matrix = None                                    # sklearn sparse matrix

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build(self, node_ids: List[str], texts: List[str]) -> None:
        """Build (or rebuild) the index from scratch."""
        self._node_ids = node_ids
        self._texts = texts

        if _SKLEARN_AVAILABLE and len(texts) >= 2:
            self._vectorizer = TfidfVectorizer(
                max_features=8000,
                ngram_range=(1, 2),
                sublinear_tf=True,
                min_df=1
            )
            self._matrix = self._vectorizer.fit_transform(texts)
        else:
            self._idf = _build_idf(texts)

        self._built_at = time.time()
        self._save_cache()
        logger.debug(f"TF-IDF index built: {len(texts)} docs, backend={'sklearn' if _SKLEARN_AVAILABLE else 'pure-python'}")

    def query(self, text: str, top_k: int = 20) -> List[Tuple[str, float]]:
        """
        Return (node_id, similarity_score) pairs for the top_k most similar nodes.
        Scores are in [0, 1].
        """
        if not self._node_ids:
            return []

        if _SKLEARN_AVAILABLE and self._vectorizer is not None and self._matrix is not None:
            return self._query_sklearn(text, top_k)
        elif self._idf is not None:
            return self._query_pure(text, top_k)
        return []

    def is_valid(self, expected_count: int) -> bool:
        """Return True if the cache is still current."""
        if not self._node_ids:
            return False
        if time.time() - self._built_at > self.ttl:
            return False
        if len(self._node_ids) != expected_count:
            return False
        return True

    # ------------------------------------------------------------------
    # Cache persistence
    # ------------------------------------------------------------------

    def load_cache(self) -> bool:
        """Attempt to load index from disk. Returns True on success."""
        if not self.cache_path.exists():
            return False
        try:
            with open(self.cache_path, 'rb') as f:
                state = pickle.load(f)
            if time.time() - state['built_at'] > self.ttl:
                return False
            self._node_ids = state['node_ids']
            self._texts = state['texts']
            self._built_at = state['built_at']
            self._idf = state.get('idf')
            self._vectorizer = state.get('vectorizer')
            self._matrix = state.get('matrix')
            return True
        except Exception as e:
            logger.debug(f"Cache load failed: {e}")
            return False

    def _save_cache(self) -> None:
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            state = {
                'built_at': self._built_at,
                'node_ids': self._node_ids,
                'texts': self._texts,
                'idf': self._idf,
                'vectorizer': self._vectorizer,
                'matrix': self._matrix,
            }
            with open(self.cache_path, 'wb') as f:
                pickle.dump(state, f, protocol=4)
        except Exception as e:
            logger.debug(f"Cache save failed (non-fatal): {e}")

    # ------------------------------------------------------------------
    # Query backends
    # ------------------------------------------------------------------

    def _query_sklearn(self, text: str, top_k: int) -> List[Tuple[str, float]]:
        q_vec = self._vectorizer.transform([text])
        scores = sk_cosine(q_vec, self._matrix)[0]
        top_indices = scores.argsort()[::-1][:top_k]
        return [
            (self._node_ids[i], float(scores[i]))
            for i in top_indices
            if scores[i] > 0
        ]

    def _query_pure(self, text: str, top_k: int) -> List[Tuple[str, float]]:
        q_vec = _tfidf_vec(text, self._idf)
        if not q_vec:
            return []
        scored = []
        for node_id, doc_text in zip(self._node_ids, self._texts):
            d_vec = _tfidf_vec(doc_text, self._idf)
            sim = _cosine(q_vec, d_vec)
            if sim > 0:
                scored.append((node_id, sim))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]


# ---------------------------------------------------------------------------
# Module-level helper used by retrieval.py
# ---------------------------------------------------------------------------

_index_cache: Dict[str, TFIDFIndex] = {}  # keyed by project_id


def get_or_build_index(
    nodes_with_text: List[Tuple[str, str]],   # [(node_id, embedding_text)]
    project_id: str,
    cache_dir: Path,
    ttl_seconds: int = 300
) -> TFIDFIndex:
    """
    Return a valid TFIDFIndex for the given corpus, using disk cache when possible.
    `nodes_with_text` is the full corpus derived from the DB.
    """
    idx = _index_cache.get(project_id)
    expected = len(nodes_with_text)

    if idx is None:
        idx = TFIDFIndex(cache_dir, project_id, ttl_seconds)
        _index_cache[project_id] = idx
        if not idx.load_cache():
            ids = [n[0] for n in nodes_with_text]
            texts = [n[1] for n in nodes_with_text]
            idx.build(ids, texts)
    elif not idx.is_valid(expected):
        ids = [n[0] for n in nodes_with_text]
        texts = [n[1] for n in nodes_with_text]
        idx.build(ids, texts)

    return idx
