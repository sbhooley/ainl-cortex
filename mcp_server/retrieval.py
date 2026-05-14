"""
AINL Graph Memory Retrieval and Ranking

Context-aware retrieval with AINL-inspired ranking algorithm.
Follows ainl-runtime memory context compilation pattern.
"""

from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
from pathlib import Path
import time
import logging

try:
    from .node_types import GraphNode, NodeType
except ImportError:
    from node_types import GraphNode, NodeType
try:
    from .graph_store import GraphStore
except ImportError:
    from graph_store import GraphStore
try:
    from .similarity import get_or_build_index
except ImportError:
    from similarity import get_or_build_index

logger = logging.getLogger(__name__)


@dataclass
class RetrievalContext:
    """Context for ranking relevance.

    `project_id` is the active per-repo bucket. `project_id_chain`, when set,
    is the read-fallback list (typically `[project_id, LEGACY_GLOBAL_PROJECT_ID]`)
    used to merge in pre-rewrite memories until backfill has run. When unset,
    only `project_id` is queried (back-compat).
    """
    project_id: str
    current_task: Optional[str] = None
    files_mentioned: List[str] = None
    topics: List[str] = None
    project_id_chain: Optional[List[str]] = None

    def __post_init__(self):
        if self.files_mentioned is None:
            self.files_mentioned = []
        if self.topics is None:
            self.topics = []
        # Default chain = single id, dedup-preserve-order.
        if self.project_id_chain is None:
            self.project_id_chain = [self.project_id]
        else:
            seen = set()
            deduped = []
            for pid in self.project_id_chain:
                if pid and pid not in seen:
                    seen.add(pid)
                    deduped.append(pid)
            if not deduped:
                deduped = [self.project_id]
            self.project_id_chain = deduped


class MemoryRetrieval:
    """
    Memory retrieval with AINL-inspired ranking.

    Ranking factors (from ArmaraOS):
    - Project match: +10.0
    - Recency decay (30 days): +5.0 → 0.0
    - Success outcome: +3.0
    - Pattern fitness: +success_count * 0.5
    - File/topic overlap: +2.0 per match
    - Confidence multiplier
    """

    RECENCY_WINDOW_DAYS = 30
    RECENCY_SCORE = 5.0
    PROJECT_MATCH_SCORE = 10.0
    SUCCESS_SCORE = 3.0
    PATTERN_FITNESS_MULTIPLIER = 0.5
    OVERLAP_SCORE = 2.0
    SIMILARITY_WEIGHT = 6.0   # Max bonus for TF-IDF cosine similarity

    def __init__(self, store: GraphStore, cache_dir: Optional[Path] = None, tfidf_ttl: int = 300):
        self.store = store
        self._cache_dir = cache_dir
        self._tfidf_ttl = tfidf_ttl
        self._sim_scores: Dict[str, float] = {}  # node_id → score for current query

    def compute_similarity_scores(
        self,
        nodes: List[GraphNode],
        query_text: str,
        project_id: str
    ) -> None:
        """
        Pre-compute TF-IDF similarity scores for all nodes against query_text.
        Results stored in self._sim_scores so rank_nodes() can use them without
        rebuilding the index on each call.
        """
        self._sim_scores = {}
        if not query_text or not nodes:
            return

        # Build corpus from all nodes that have embedding text
        corpus = [
            (n.id, n.embedding_text)
            for n in nodes
            if n.embedding_text
        ]
        if not corpus:
            return

        try:
            cache_dir = self._cache_dir or Path.home() / ".claude" / "projects" / project_id / "graph_memory"
            idx = get_or_build_index(corpus, project_id, cache_dir, self._tfidf_ttl)
            for node_id, score in idx.query(query_text, top_k=len(corpus)):
                self._sim_scores[node_id] = score
            mode = "tfidf"
            try:
                from config import get_config
                mode = str(
                    (get_config().config.get("retrieval") or {}).get("retrieval_mode", "tfidf")
                ).lower()
            except Exception:
                pass
            if mode == "hybrid":
                try:
                    from similarity import lexical_jaccard_overlap
                    for n in nodes:
                        et = n.embedding_text or ""
                        lex = lexical_jaccard_overlap(query_text, et)
                        tid = self._sim_scores.get(n.id, 0.0)
                        self._sim_scores[n.id] = min(1.0, 0.7 * tid + 0.3 * lex)
                except Exception as ex:
                    logger.debug(f"Hybrid similarity blend failed (non-fatal): {ex}")
        except Exception as e:
            logger.debug(f"Similarity scoring failed (non-fatal): {e}")

    def rank_nodes(
        self,
        nodes: List[GraphNode],
        context: RetrievalContext
    ) -> List[Tuple[GraphNode, float]]:
        """
        Rank nodes by relevance to context.

        Returns list of (node, score) tuples sorted by score descending.
        """
        scored = []
        now = int(time.time())

        chain = set(context.project_id_chain or [context.project_id])

        for node in nodes:
            score = 0.0

            # Project match (critical) — any id in the read-fallback chain
            # counts so legacy nodes still earn the boost during the
            # backfill grace period.
            if node.project_id in chain:
                score += self.PROJECT_MATCH_SCORE

            # Recency (decay over 30 days)
            age_seconds = now - node.created_at
            age_days = age_seconds / 86400  # seconds to days
            recency_factor = max(0, 1 - (age_days / self.RECENCY_WINDOW_DAYS))
            score += self.RECENCY_SCORE * recency_factor

            # Type-specific scoring
            if node.node_type == NodeType.EPISODE:
                outcome = node.data.get('outcome')
                if outcome == 'success':
                    score += self.SUCCESS_SCORE

                # File overlap
                files_touched = node.data.get('files_touched', [])
                overlap = len(set(files_touched) & set(context.files_mentioned))
                score += overlap * self.OVERLAP_SCORE

            elif node.node_type == NodeType.PROCEDURAL:
                # Pattern fitness and usage
                fitness = node.data.get('fitness', 0.0)
                success_count = node.data.get('success_count', 0)
                score += success_count * self.PATTERN_FITNESS_MULTIPLIER
                score += fitness * 2.0  # Bonus for high fitness

            elif node.node_type == NodeType.SEMANTIC:
                # Recurrence and reference count
                recurrence = node.data.get('recurrence_count', 1)
                references = node.data.get('reference_count', 0)
                score += (recurrence + references) * 0.3

                # Topic overlap
                tags = node.data.get('tags', [])
                topic_overlap = len(set(tags) & set(context.topics))
                score += topic_overlap * self.OVERLAP_SCORE

            elif node.node_type == NodeType.PERSONA:
                # Strength-based scoring
                strength = node.data.get('strength', 0.0)
                score += strength * 1.5

            # Semantic similarity bonus (TF-IDF cosine against current task)
            sim = self._sim_scores.get(node.id, 0.0)
            score += sim * self.SIMILARITY_WEIGHT

            # Confidence multiplier
            score *= node.confidence

            scored.append((node, score))

        # Sort by score descending
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored

    def compile_memory_context(
        self,
        context: RetrievalContext,
        max_nodes: int = 50
    ) -> Dict[str, Any]:
        """
        Compile working memory context (AINL MemoryContext pattern).

        Returns structured context with:
        - recent_episodes: Last N successful turns
        - relevant_facts: High-confidence semantics (topic-ranked if task provided)
        - applicable_patterns: High-fitness procedurals matching context
        - known_failures: Unresolved failures for mentioned files
        - persona_traits: Active persona axes
        """

        # Build similarity query from all available context signals
        query_text = " ".join(filter(None, [
            context.current_task or "",
            " ".join(context.files_mentioned),
            " ".join(context.topics)
        ])).strip()

        # Gather broad candidate pools across every project_id in the legacy
        # read-fallback chain. After issue 1 lands, the chain is normally
        # [per_repo_id, LEGACY_GLOBAL_PROJECT_ID] so users keep seeing memories
        # that were captured before the per-repo rewrite. Dedup by node id.
        chain = context.project_id_chain or [context.project_id]

        def _query_chain(fn):
            seen: Dict[str, GraphNode] = {}
            for pid in chain:
                for node in fn(pid):
                    if node.id not in seen:
                        seen[node.id] = node
            return list(seen.values())

        all_episodes = _query_chain(
            lambda pid: self.store.query_episodes_since(0, limit=100, project_id=pid)
        )
        all_semantics = _query_chain(
            lambda pid: self.store.query_by_type(
                NodeType.SEMANTIC, pid, limit=200, min_confidence=0.2
            )
        )
        all_procedurals = _query_chain(
            lambda pid: self.store.query_by_type(
                NodeType.PROCEDURAL, pid, limit=100, min_confidence=0.2
            )
        )
        all_personas = _query_chain(
            lambda pid: self.store.query_by_type(
                NodeType.PERSONA, pid, limit=100, min_confidence=0.1
            )
        )

        # Pre-compute similarity scores across ALL candidates in one pass
        all_candidates = all_episodes + all_semantics + all_procedurals + all_personas
        if query_text:
            self.compute_similarity_scores(all_candidates, query_text, context.project_id)

        # Rank each pool with similarity scores already populated
        ranked_episodes = self.rank_nodes(all_episodes, context)
        recent_episodes = [node.to_dict() for node, score in ranked_episodes[:5]]

        ranked_semantics = self.rank_nodes(all_semantics, context)
        relevant_facts = [node.to_dict() for node, score in ranked_semantics[:10]]

        ranked_procedurals = self.rank_nodes(all_procedurals, context)
        applicable_patterns = [
            node.to_dict() for node, score in ranked_procedurals[:5]
            if node.data.get('fitness', 0) > 0.2
        ]

        ranked_personas = self.rank_nodes(all_personas, context)
        persona_traits = [
            node.to_dict() for node, score in ranked_personas[:5]
            if node.data.get('strength', 0) >= 0.1
        ]

        # Failures — similarity-ranked unresolved failures across the chain.
        failures_seen: Dict[str, GraphNode] = {}
        for pid in chain:
            for node in self.store.get_unresolved_failures(pid, limit=50):
                if node.id not in failures_seen:
                    failures_seen[node.id] = node
        failures = list(failures_seen.values())
        if query_text and failures:
            self.compute_similarity_scores(failures, query_text, context.project_id)
        ranked_failures = self.rank_nodes(failures, context)
        known_failures = [node.to_dict() for node, score in ranked_failures[:5]]

        # Clear sim scores after compile (don't pollute next call)
        self._sim_scores = {}

        return {
            "recent_episodes": recent_episodes,
            "relevant_facts": relevant_facts,
            "applicable_patterns": applicable_patterns,
            "known_failures": known_failures,
            "persona_traits": persona_traits,
            "context": {
                "project_id": context.project_id,
                "task": context.current_task,
                "files": context.files_mentioned,
                "topics": context.topics
            }
        }

    def format_memory_brief(self, memory_context: Dict[str, Any], max_tokens: int = 800) -> str:
        """
        Format memory context into compact markdown (same tiering as hook recall).
        """
        try:
            from dataclasses import replace

            from recall_budget import format_memory_context_markdown, recall_budget_from_memory_config
            from config import get_config

            b = recall_budget_from_memory_config(get_config().get_memory_block())
            b = replace(b, max_chars=max(256, int(max_tokens) * 4))
            text, _stats = format_memory_context_markdown(memory_context, b)
            return text
        except Exception as e:
            logger.debug(f"recall_budget format failed, legacy brief: {e}")
        lines = ["## Relevant Graph Memory", ""]

        # Recent episodes
        if memory_context.get('recent_episodes'):
            lines.append("**Recent Work:**")
            for ep in memory_context['recent_episodes'][:3]:
                timestamp = time.strftime('%Y-%m-%d', time.localtime(ep['created_at']))
                task = ep['data']['task_description'][:60]
                outcome = ep['data']['outcome']
                lines.append(f"- [{timestamp}] {task} → {outcome}")
            lines.append("")

        # Relevant facts
        if memory_context.get('relevant_facts'):
            lines.append("**Known Facts:**")
            for fact in memory_context['relevant_facts'][:5]:
                fact_text = fact['data']['fact'][:80]
                confidence = fact['confidence']
                lines.append(f"- {fact_text} (conf: {confidence:.2f})")
            lines.append("")

        # Applicable patterns
        if memory_context.get('applicable_patterns'):
            lines.append("**Reusable Patterns:**")
            for pat in memory_context['applicable_patterns'][:2]:
                name = pat['data']['pattern_name']
                sequence = ' → '.join(pat['data']['tool_sequence'][:4])
                fitness = pat['data']['fitness']
                lines.append(f"- \"{name}\": {sequence} (fitness: {fitness:.2f})")
            lines.append("")

        # Known failures
        if memory_context.get('known_failures'):
            lines.append("**Known Issues:**")
            for fail in memory_context['known_failures'][:3]:
                file = fail['data'].get('file', 'unknown')
                line = fail['data'].get('line', '?')
                msg = fail['data'].get('error_message', '')[:60]
                lines.append(f"- {file}:{line}: {msg}")
            lines.append("")

        # Persona traits
        if memory_context.get('persona_traits'):
            traits = []
            for trait in memory_context['persona_traits'][:3]:
                name = trait['data']['trait_name']
                strength = trait['data']['strength']
                traits.append(f"{name} ({strength:.2f})")

            if traits:
                lines.append(f"**Project Style:** {', '.join(traits)}")
                lines.append("")

        brief = "\n".join(lines)

        # Rough token estimate (1 token ≈ 4 chars)
        estimated_tokens = len(brief) // 4
        if estimated_tokens > max_tokens:
            # Truncate if over budget
            chars_to_keep = max_tokens * 4
            brief = brief[:chars_to_keep] + "\n\n[... truncated for context budget]"
            logger.warning(f"Memory brief truncated: {estimated_tokens} → {max_tokens} tokens")

        return brief
