"""
Adaptive Eco Mode

Automatically adjusts compression based on prompt type and content.
Inspired by ArmaraOS adaptive_eco system.
"""

import re
from typing import Tuple, Optional, Dict, List
from dataclasses import dataclass
from datetime import datetime
import logging

try:
    from .compression import EfficientMode
except ImportError:
    from compression import EfficientMode

logger = logging.getLogger(__name__)


@dataclass
class ContentCharacteristics:
    """Analyzed characteristics of prompt content"""
    has_code: bool
    code_ratio: float  # 0.0 to 1.0
    technical_density: float  # 0.0 to 1.0
    is_question: bool
    is_command: bool
    has_urls: bool
    has_file_paths: bool
    word_count: int
    avg_sentence_length: float


@dataclass
class ModeRecommendation:
    """Recommended compression mode with confidence"""
    mode: EfficientMode
    confidence: float  # 0.0 to 1.0
    reason: str


@dataclass
class AdaptiveDecision:
    """Record of an adaptive mode decision"""
    timestamp: float
    content_chars: ContentCharacteristics
    recommended_mode: EfficientMode
    confidence: float
    original_tokens: int
    compressed_tokens: int
    effectiveness_score: float  # Actual savings vs expected


class ContentAnalyzer:
    """Analyzes prompt content to detect characteristics"""

    # Technical terms that indicate high-value content
    TECHNICAL_TERMS = {
        'error', 'exception', 'stack', 'trace', 'debug', 'log',
        'function', 'method', 'class', 'variable', 'parameter',
        'api', 'endpoint', 'request', 'response', 'http', 'https',
        'database', 'query', 'sql', 'schema', 'table', 'index',
        'git', 'commit', 'branch', 'merge', 'diff', 'patch',
        'test', 'assert', 'mock', 'fixture', 'coverage',
        'build', 'compile', 'deploy', 'runtime', 'process',
        'memory', 'cpu', 'thread', 'async', 'await', 'promise',
        'docker', 'kubernetes', 'container', 'pod', 'service',
        'auth', 'token', 'session', 'cookie', 'jwt', 'oauth'
    }

    # Question patterns
    QUESTION_PATTERNS = [
        r'^\s*(?:what|why|how|when|where|who|which|can|could|would|should|is|are|does|do)\b',
        r'\?$'
    ]

    # Command patterns
    COMMAND_PATTERNS = [
        r'^\s*(?:create|make|build|add|remove|delete|update|fix|refactor|optimize)\b',
        r'^\s*(?:implement|write|generate|extract|move|rename|split|merge)\b',
        r'^\s*(?:show|list|find|search|check|verify|test|run|execute)\b'
    ]

    def analyze(self, text: str) -> ContentCharacteristics:
        """Analyze text content and return characteristics"""

        # Detect code blocks
        code_blocks = re.findall(r'```[\s\S]*?```', text)
        code_chars = sum(len(block) for block in code_blocks)
        total_chars = len(text)
        code_ratio = code_chars / max(total_chars, 1)
        has_code = len(code_blocks) > 0

        # Calculate technical density
        words = re.findall(r'\w+', text.lower())
        word_count = len(words)
        technical_word_count = sum(1 for word in words if word in self.TECHNICAL_TERMS)
        technical_density = technical_word_count / max(word_count, 1)

        # Detect URLs and file paths
        has_urls = bool(re.search(r'https?://', text))
        has_file_paths = bool(re.search(r'[/\\][\w./\\-]+\.\w+', text))

        # Detect question vs command
        first_line = text.strip().split('\n')[0] if text.strip() else ''
        is_question = any(re.search(pat, first_line, re.IGNORECASE) for pat in self.QUESTION_PATTERNS)
        is_command = any(re.search(pat, first_line, re.IGNORECASE) for pat in self.COMMAND_PATTERNS)

        # Calculate average sentence length
        sentences = re.split(r'[.!?]\s+', text)
        sentence_lengths = [len(s.split()) for s in sentences if s.strip()]
        avg_sentence_length = sum(sentence_lengths) / max(len(sentence_lengths), 1)

        return ContentCharacteristics(
            has_code=has_code,
            code_ratio=code_ratio,
            technical_density=technical_density,
            is_question=is_question,
            is_command=is_command,
            has_urls=has_urls,
            has_file_paths=has_file_paths,
            word_count=word_count,
            avg_sentence_length=avg_sentence_length
        )


class ModeRecommender:
    """Recommends optimal compression mode based on content characteristics"""

    def __init__(self):
        self.analyzer = ContentAnalyzer()
        self.decision_history: List[AdaptiveDecision] = []

    def recommend(self, text: str, current_mode: EfficientMode) -> ModeRecommendation:
        """
        Recommend compression mode based on content analysis.

        Rules:
        - High code ratio (>40%) → OFF (preserve code exactly)
        - High technical density (>30%) + short (< 100 words) → BALANCED
        - Question + technical → BALANCED (preserve details for understanding)
        - Long + low technical density → AGGRESSIVE (changelog, narrative)
        - Command + high file paths → BALANCED (preserve paths)
        """
        chars = self.analyzer.analyze(text)

        # Rule 1: High code ratio → OFF
        if chars.code_ratio > 0.4:
            return ModeRecommendation(
                mode=EfficientMode.OFF,
                confidence=0.9,
                reason=f"High code ratio ({chars.code_ratio:.0%}), preserve exactly"
            )

        # Rule 2: High technical density + short → BALANCED
        if chars.technical_density > 0.3 and chars.word_count < 100:
            return ModeRecommendation(
                mode=EfficientMode.BALANCED,
                confidence=0.85,
                reason=f"Technical content ({chars.technical_density:.0%} density), safe compression"
            )

        # Rule 3: Question + technical → BALANCED
        if chars.is_question and chars.technical_density > 0.2:
            return ModeRecommendation(
                mode=EfficientMode.BALANCED,
                confidence=0.8,
                reason="Technical question, preserve details for understanding"
            )

        # Rule 4: Long + low technical → AGGRESSIVE
        if chars.word_count > 150 and chars.technical_density < 0.15:
            return ModeRecommendation(
                mode=EfficientMode.AGGRESSIVE,
                confidence=0.75,
                reason=f"Long narrative ({chars.word_count} words), aggressive savings"
            )

        # Rule 5: Command + file paths → BALANCED
        if chars.is_command and chars.has_file_paths:
            return ModeRecommendation(
                mode=EfficientMode.BALANCED,
                confidence=0.8,
                reason="Command with file paths, preserve structure"
            )

        # Rule 6: Has URLs → BALANCED (preserve URLs)
        if chars.has_urls:
            return ModeRecommendation(
                mode=EfficientMode.BALANCED,
                confidence=0.85,
                reason="Contains URLs, use safe compression"
            )

        # Default: Stick with current mode but low confidence
        return ModeRecommendation(
            mode=current_mode,
            confidence=0.5,
            reason="No strong signal, maintain current mode"
        )

    def record_decision(self, decision: AdaptiveDecision):
        """Record an adaptive decision for effectiveness tracking"""
        self.decision_history.append(decision)

        # Keep last 100 decisions
        if len(self.decision_history) > 100:
            self.decision_history = self.decision_history[-100:]

    def get_effectiveness_stats(self) -> Dict[str, float]:
        """Calculate effectiveness statistics across decisions"""
        if not self.decision_history:
            return {}

        total_decisions = len(self.decision_history)

        # Average effectiveness by mode
        by_mode = {}
        for mode in [EfficientMode.OFF, EfficientMode.BALANCED, EfficientMode.AGGRESSIVE]:
            mode_decisions = [d for d in self.decision_history if d.recommended_mode == mode]
            if mode_decisions:
                avg_effectiveness = sum(d.effectiveness_score for d in mode_decisions) / len(mode_decisions)
                by_mode[mode.value] = avg_effectiveness

        # Overall stats
        avg_confidence = sum(d.confidence for d in self.decision_history) / total_decisions
        avg_effectiveness = sum(d.effectiveness_score for d in self.decision_history) / total_decisions

        return {
            'total_decisions': total_decisions,
            'avg_confidence': avg_confidence,
            'avg_effectiveness': avg_effectiveness,
            'by_mode': by_mode
        }


class AdaptivePolicy:
    """Manages adaptive compression policy with hysteresis"""

    def __init__(self,
                 enabled: bool = True,
                 min_confidence: float = 0.7,
                 hysteresis_count: int = 2):
        """
        Args:
            enabled: Whether adaptive mode is enabled
            min_confidence: Minimum confidence to override manual mode
            hysteresis_count: Number of consistent recommendations before switching
        """
        self.enabled = enabled
        self.min_confidence = min_confidence
        self.hysteresis_count = hysteresis_count
        self.recommender = ModeRecommender()
        self.recent_recommendations: List[Tuple[EfficientMode, float]] = []

    def get_mode(self, text: str, manual_mode: EfficientMode) -> Tuple[EfficientMode, Optional[str]]:
        """
        Get compression mode considering adaptive policy.

        Returns:
            (mode_to_use, override_reason)
        """
        if not self.enabled:
            return manual_mode, None

        # Get recommendation
        rec = self.recommender.recommend(text, manual_mode)

        # Record for hysteresis
        self.recent_recommendations.append((rec.mode, rec.confidence))
        if len(self.recent_recommendations) > self.hysteresis_count:
            self.recent_recommendations = self.recent_recommendations[-self.hysteresis_count:]

        # Check if we should override
        if rec.confidence >= self.min_confidence:
            # Check hysteresis: require consistent recommendations
            if len(self.recent_recommendations) >= self.hysteresis_count:
                recent_modes = [mode for mode, _ in self.recent_recommendations]
                if all(mode == rec.mode for mode in recent_modes):
                    # Consistent high-confidence recommendation
                    if rec.mode != manual_mode:
                        logger.info(
                            f"Adaptive override: {manual_mode.value} → {rec.mode.value} "
                            f"(confidence: {rec.confidence:.2f}, reason: {rec.reason})"
                        )
                        return rec.mode, rec.reason

        # No override
        return manual_mode, None

    def record_outcome(self,
                      text: str,
                      mode: EfficientMode,
                      original_tokens: int,
                      compressed_tokens: int):
        """Record compression outcome for effectiveness tracking"""
        chars = self.recommender.analyzer.analyze(text)

        # Calculate effectiveness score
        expected_retention = mode.retention_ratio()
        actual_retention = compressed_tokens / max(original_tokens, 1)

        # Effectiveness: how close to expected retention (1.0 = perfect)
        # Higher is better - means we achieved expected savings
        effectiveness_score = 1.0 - abs(actual_retention - expected_retention)

        decision = AdaptiveDecision(
            timestamp=datetime.now().timestamp(),
            content_chars=chars,
            recommended_mode=mode,
            confidence=0.0,  # Not available for outcomes
            original_tokens=original_tokens,
            compressed_tokens=compressed_tokens,
            effectiveness_score=effectiveness_score
        )

        self.recommender.record_decision(decision)

    def get_stats(self) -> Dict[str, float]:
        """Get effectiveness statistics"""
        return self.recommender.get_effectiveness_stats()
