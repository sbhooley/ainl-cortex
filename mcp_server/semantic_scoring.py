"""
Semantic Preservation Scoring

Tracks information retention quality during compression.
Uses embedding-free heuristics for fast local evaluation.
"""

import re
from typing import Set, List, Tuple, Dict
from dataclasses import dataclass
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


@dataclass
class PreservationScore:
    """Semantic preservation quality metrics"""
    overall_score: float  # 0.0 to 1.0
    key_term_retention: float  # Ratio of key terms preserved
    structural_similarity: float  # Similarity of structure (sentences, paragraphs)
    code_preservation: float  # Code block preservation (0.0 or 1.0)
    url_preservation: float  # URL preservation ratio
    detail_level: float  # Detail preservation (sentence count ratio)
    warnings: List[str]  # Quality warnings


@dataclass
class ScoringResult:
    """Complete scoring result with metadata"""
    score: PreservationScore
    original_text: str
    compressed_text: str
    timestamp: float
    tokens_saved: int
    savings_ratio: float


class SemanticScorer:
    """
    Scores semantic preservation quality without embeddings.

    Uses heuristics:
    - Key term extraction and retention
    - Structural similarity (sentence/paragraph count)
    - Code fence preservation
    - URL preservation
    - Detail level (sentence count)
    """

    # Terms that should be preserved (domain-specific)
    CRITICAL_TERM_PATTERNS = [
        r'\b(?:error|exception|failure|bug|issue|warning)\b',
        r'\b(?:http://|https://)\S+',
        r'\b(?:TODO|FIXME|HACK|NOTE)\b',
        r'`[^`]+`',  # Inline code
        r'\b\w+\.\w+\b',  # File paths (basic)
        r'\b\d+\.\d+\.\d+\b',  # Version numbers
        r'#\d+',  # Issue/PR numbers
    ]

    # Quality thresholds
    MIN_KEY_TERM_RETENTION = 0.80  # 80% of key terms should survive
    MIN_OVERALL_SCORE = 0.70  # 70% overall quality

    def __init__(self):
        self.scoring_history: List[ScoringResult] = []

    def extract_key_terms(self, text: str) -> Set[str]:
        """Extract important terms from text"""
        key_terms = set()

        # Extract by patterns
        for pattern in self.CRITICAL_TERM_PATTERNS:
            matches = re.findall(pattern, text, re.IGNORECASE)
            key_terms.update(match.lower() for match in matches)

        # Extract capitalized terms (likely important names)
        capitalized = re.findall(r'\b[A-Z][a-z]+(?:[A-Z][a-z]+)*\b', text)
        key_terms.update(term.lower() for term in capitalized if len(term) > 3)

        # Extract technical terms (snake_case, camelCase)
        snake_case = re.findall(r'\b[a-z]+_[a-z_]+\b', text)
        camel_case = re.findall(r'\b[a-z]+[A-Z][a-zA-Z]*\b', text)
        key_terms.update(snake_case)
        key_terms.update(camel_case)

        return key_terms

    def calculate_structural_similarity(self, original: str, compressed: str) -> float:
        """Calculate structural similarity between texts"""

        # Sentence count
        orig_sentences = len(re.split(r'[.!?]\s+', original))
        comp_sentences = len(re.split(r'[.!?]\s+', compressed))
        sentence_ratio = min(comp_sentences, orig_sentences) / max(orig_sentences, 1)

        # Paragraph count
        orig_paragraphs = len([p for p in original.split('\n\n') if p.strip()])
        comp_paragraphs = len([p for p in compressed.split('\n\n') if p.strip()])
        paragraph_ratio = min(comp_paragraphs, orig_paragraphs) / max(orig_paragraphs, 1)

        # Line count (for code/lists)
        orig_lines = len([l for l in original.split('\n') if l.strip()])
        comp_lines = len([l for l in compressed.split('\n') if l.strip()])
        line_ratio = min(comp_lines, orig_lines) / max(orig_lines, 1)

        # Weighted average
        return 0.4 * sentence_ratio + 0.3 * paragraph_ratio + 0.3 * line_ratio

    def check_code_preservation(self, original: str, compressed: str) -> float:
        """Check if code blocks are preserved"""
        orig_code_blocks = re.findall(r'```[\s\S]*?```', original)
        comp_code_blocks = re.findall(r'```[\s\S]*?```', compressed)

        if not orig_code_blocks:
            return 1.0  # No code to preserve

        # Check if all original code blocks are in compressed
        if len(orig_code_blocks) != len(comp_code_blocks):
            return 0.0

        # Check exact preservation
        for orig_block, comp_block in zip(orig_code_blocks, comp_code_blocks):
            if orig_block != comp_block:
                return 0.5  # Partial preservation

        return 1.0  # Perfect preservation

    def check_url_preservation(self, original: str, compressed: str) -> float:
        """Check URL preservation ratio"""
        orig_urls = set(re.findall(r'https?://\S+', original))
        comp_urls = set(re.findall(r'https?://\S+', compressed))

        if not orig_urls:
            return 1.0  # No URLs to preserve

        preserved = len(orig_urls & comp_urls)
        return preserved / len(orig_urls)

    def score(self, original: str, compressed: str, tokens_saved: int = 0) -> PreservationScore:
        """
        Score semantic preservation quality.

        Returns score from 0.0 (complete loss) to 1.0 (perfect preservation)
        """
        warnings = []

        # 1. Key term retention
        orig_terms = self.extract_key_terms(original)
        comp_terms = self.extract_key_terms(compressed)

        if orig_terms:
            key_term_retention = len(orig_terms & comp_terms) / len(orig_terms)
        else:
            key_term_retention = 1.0

        if key_term_retention < self.MIN_KEY_TERM_RETENTION:
            warnings.append(
                f"Low key term retention: {key_term_retention:.0%} "
                f"(threshold: {self.MIN_KEY_TERM_RETENTION:.0%})"
            )

        # 2. Structural similarity
        structural_similarity = self.calculate_structural_similarity(original, compressed)

        # 3. Code preservation
        code_preservation = self.check_code_preservation(original, compressed)
        if code_preservation < 1.0:
            warnings.append("Code blocks not perfectly preserved")

        # 4. URL preservation
        url_preservation = self.check_url_preservation(original, compressed)
        if url_preservation < 1.0:
            warnings.append(f"URLs lost: {url_preservation:.0%} preserved")

        # 5. Detail level (sentence count ratio)
        orig_sentences = len(re.split(r'[.!?]\s+', original))
        comp_sentences = len(re.split(r'[.!?]\s+', compressed))
        detail_level = min(comp_sentences, orig_sentences) / max(orig_sentences, 1)

        # Overall score (weighted average)
        overall_score = (
            0.30 * key_term_retention +
            0.20 * structural_similarity +
            0.25 * code_preservation +
            0.15 * url_preservation +
            0.10 * detail_level
        )

        if overall_score < self.MIN_OVERALL_SCORE:
            warnings.append(
                f"Low overall quality: {overall_score:.0%} "
                f"(threshold: {self.MIN_OVERALL_SCORE:.0%})"
            )

        return PreservationScore(
            overall_score=overall_score,
            key_term_retention=key_term_retention,
            structural_similarity=structural_similarity,
            code_preservation=code_preservation,
            url_preservation=url_preservation,
            detail_level=detail_level,
            warnings=warnings
        )

    def score_and_record(self,
                         original: str,
                         compressed: str,
                         tokens_saved: int,
                         savings_ratio: float) -> ScoringResult:
        """Score compression and record in history"""
        score = self.score(original, compressed, tokens_saved)

        result = ScoringResult(
            score=score,
            original_text=original,
            compressed_text=compressed,
            timestamp=datetime.now().timestamp(),
            tokens_saved=tokens_saved,
            savings_ratio=savings_ratio
        )

        self.scoring_history.append(result)

        # Keep last 100 results
        if len(self.scoring_history) > 100:
            self.scoring_history = self.scoring_history[-100:]

        # Log warnings
        if score.warnings:
            logger.warning(
                f"Compression quality issues: {'; '.join(score.warnings)}"
            )

        return result

    def get_quality_stats(self) -> Dict[str, float]:
        """Get quality statistics across history"""
        if not self.scoring_history:
            return {}

        total = len(self.scoring_history)

        # Average scores
        avg_overall = sum(r.score.overall_score for r in self.scoring_history) / total
        avg_key_term = sum(r.score.key_term_retention for r in self.scoring_history) / total
        avg_structural = sum(r.score.structural_similarity for r in self.scoring_history) / total
        avg_detail = sum(r.score.detail_level for r in self.scoring_history) / total

        # Quality distribution
        high_quality = sum(1 for r in self.scoring_history if r.score.overall_score >= 0.9)
        good_quality = sum(1 for r in self.scoring_history if 0.7 <= r.score.overall_score < 0.9)
        low_quality = sum(1 for r in self.scoring_history if r.score.overall_score < 0.7)

        # Issues
        total_warnings = sum(len(r.score.warnings) for r in self.scoring_history)

        return {
            'total_compressions': total,
            'avg_overall_score': avg_overall,
            'avg_key_term_retention': avg_key_term,
            'avg_structural_similarity': avg_structural,
            'avg_detail_level': avg_detail,
            'high_quality_pct': high_quality / total,
            'good_quality_pct': good_quality / total,
            'low_quality_pct': low_quality / total,
            'total_warnings': total_warnings,
            'avg_warnings_per_compression': total_warnings / total
        }

    def should_fallback_to_original(self, score: PreservationScore) -> bool:
        """Determine if compression quality is too low and should fallback"""
        # Fallback if overall score is very low
        if score.overall_score < 0.5:
            return True

        # Fallback if code is not preserved
        if score.code_preservation < 1.0:
            return True

        # Fallback if key terms are heavily lost
        if score.key_term_retention < 0.6:
            return True

        return False
