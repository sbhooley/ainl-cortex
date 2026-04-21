"""
Unified Compression Pipeline

Integrates all 5 compression enhancements:
1. Adaptive eco mode
2. Semantic preservation scoring
3. Per-project compression profiles
4. Output compression
5. Prompt cache awareness
"""

from typing import Tuple, Optional
from dataclasses import dataclass
import logging

from .compression import EfficientMode, CompressionMetrics, compress_text
from .adaptive_eco import AdaptivePolicy
from .semantic_scoring import SemanticScorer, PreservationScore
from .project_profiles import get_profile_manager, ProjectProfileManager
from .cache_awareness import get_cache_coordinator, CacheCoordinator, CacheDecision
from .output_compression import OutputCompressor, OutputCompressionConfig
from .config import get_config

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    """Result of compression pipeline"""
    compressed_text: str
    original_text: str
    compression_metrics: Optional[CompressionMetrics]
    preservation_score: Optional[PreservationScore]
    mode_used: EfficientMode
    mode_source: str  # 'manual', 'adaptive', 'project_profile', 'cache_constrained'
    cache_decision: Optional[CacheDecision]
    warnings: list


class CompressionPipeline:
    """
    Unified compression pipeline with all enhancements.

    Flow:
    1. Get manual/default mode from config
    2. Check project profile for preferred mode
    3. Run adaptive eco if enabled (content-based recommendation)
    4. Check cache awareness (apply hysteresis if needed)
    5. Compress with final mode
    6. Score semantic preservation
    7. Fallback to original if quality too low
    8. Record outcome for learning
    """

    def __init__(self):
        self.config = get_config()
        self.adaptive_policy: Optional[AdaptivePolicy] = None
        self.semantic_scorer: Optional[SemanticScorer] = None
        self.profile_manager: Optional[ProjectProfileManager] = None
        self.cache_coordinator: Optional[CacheCoordinator] = None

        # Track last used mode per project for cache awareness
        self.last_mode_by_project: dict = {}

        # Initialize based on config
        self._init_components()

    def _init_components(self):
        """Initialize pipeline components based on configuration"""

        # Adaptive eco mode
        if self.config.is_adaptive_eco_enabled():
            adaptive_config = self.config.get_adaptive_eco_config()
            self.adaptive_policy = AdaptivePolicy(
                enabled=True,
                min_confidence=adaptive_config.get('min_confidence', 0.7),
                hysteresis_count=adaptive_config.get('hysteresis_count', 2)
            )
            logger.info("Adaptive eco mode enabled")

        # Semantic scoring
        if self.config.is_semantic_scoring_enabled():
            self.semantic_scorer = SemanticScorer()
            logger.info("Semantic preservation scoring enabled")

        # Project profiles
        if self.config.is_project_profiles_enabled():
            self.profile_manager = get_profile_manager()
            logger.info("Per-project compression profiles enabled")

        # Cache awareness
        if self.config.is_cache_awareness_enabled():
            cache_config = self.config.get_cache_awareness_config()
            self.cache_coordinator = get_cache_coordinator()
            self.cache_coordinator.cache_ttl = cache_config.get('cache_ttl', 300)
            logger.info("Prompt cache awareness enabled")

    def compress_memory_context(self,
                                text: str,
                                project_id: str) -> PipelineResult:
        """
        Compress memory context with full pipeline.

        Args:
            text: Text to compress
            project_id: Project identifier for profiling

        Returns:
            PipelineResult with compressed text and metadata
        """
        warnings = []

        # Step 1: Get base mode from config
        base_mode = self.config.get_compression_mode()
        current_mode = base_mode
        mode_source = 'manual'

        # Step 2: Check project profile
        if self.profile_manager and self.config.get_project_profiles_config().get('auto_detect_mode', True):
            profile_mode = self.profile_manager.suggest_mode(project_id, base_mode)
            if profile_mode != base_mode:
                current_mode = profile_mode
                mode_source = 'project_profile'
                logger.debug(f"Using project profile mode: {profile_mode.value}")

        # Step 3: Adaptive eco recommendation
        adaptive_mode = current_mode
        if self.adaptive_policy:
            adaptive_mode, adaptive_reason = self.adaptive_policy.get_mode(text, current_mode)
            if adaptive_reason:
                current_mode = adaptive_mode
                mode_source = 'adaptive'
                logger.debug(f"Adaptive override: {adaptive_mode.value} ({adaptive_reason})")

        # Step 4: Cache awareness
        cache_decision = None
        if self.cache_coordinator:
            last_mode = self.last_mode_by_project.get(project_id, current_mode)
            cache_decision = self.cache_coordinator.decide_mode_with_hysteresis(
                project_id,
                current_mode,
                last_mode
            )
            if cache_decision.use_mode != current_mode:
                current_mode = cache_decision.use_mode
                mode_source = 'cache_constrained'
                logger.debug(f"Cache awareness: {cache_decision.reason}")

        # Step 5: Compress
        compressed, compression_metrics = compress_text(
            text,
            mode=current_mode.value,
            emit_metrics=True
        )

        # Step 6: Score preservation quality
        preservation_score = None
        if self.semantic_scorer and compression_metrics:
            preservation_score = self.semantic_scorer.score(
                text,
                compressed,
                compression_metrics.tokens_saved
            )

            # Check quality thresholds
            scoring_config = self.config.get_semantic_scoring_config()
            min_overall = scoring_config.get('min_overall_score', 0.70)

            if preservation_score.overall_score < min_overall:
                warnings.append(
                    f"Low preservation quality ({preservation_score.overall_score:.0%}), "
                    f"falling back to original"
                )
                compressed = text
                compression_metrics = None

            # Add preservation warnings
            warnings.extend(preservation_score.warnings)

        # Step 7: Record outcome for learning
        if compression_metrics:
            # Record for adaptive policy
            if self.adaptive_policy:
                self.adaptive_policy.record_outcome(
                    text,
                    current_mode,
                    compression_metrics.original_tokens,
                    compression_metrics.compressed_tokens
                )

            # Record for project profile
            if self.profile_manager:
                quality_score = preservation_score.overall_score if preservation_score else 0.0
                self.profile_manager.record_compression(
                    project_id,
                    current_mode,
                    compression_metrics.original_tokens,
                    compression_metrics.compressed_tokens,
                    quality_score
                )

        # Track last used mode for cache awareness
        self.last_mode_by_project[project_id] = current_mode

        return PipelineResult(
            compressed_text=compressed,
            original_text=text,
            compression_metrics=compression_metrics,
            preservation_score=preservation_score,
            mode_used=current_mode,
            mode_source=mode_source,
            cache_decision=cache_decision,
            warnings=warnings
        )

    def compress_output(self, text: str) -> Tuple[str, Optional[CompressionMetrics]]:
        """
        Compress Claude's output response.

        Args:
            text: Response text to compress

        Returns:
            (compressed_text, metrics)
        """
        if not self.config.is_output_compression_enabled():
            return text, None

        output_config_dict = self.config.get_output_compression_config()

        output_config = OutputCompressionConfig(
            enabled=output_config_dict.get('enabled', False),
            mode=EfficientMode.parse_config(output_config_dict.get('mode', 'balanced')),
            preserve_code=True,
            preserve_commands=True,
            preserve_file_paths=True,
            min_length_tokens=output_config_dict.get('min_length_tokens', 200)
        )

        compressor = OutputCompressor(output_config)

        show_badge = output_config_dict.get('show_badge', False)
        return compressor.compress_with_badge(text, show_badge=show_badge)

    def get_pipeline_stats(self, project_id: Optional[str] = None) -> dict:
        """Get comprehensive statistics from all pipeline components"""
        stats = {}

        # Adaptive eco stats
        if self.adaptive_policy:
            stats['adaptive_eco'] = self.adaptive_policy.get_stats()

        # Semantic scoring stats
        if self.semantic_scorer:
            stats['semantic_scoring'] = self.semantic_scorer.get_quality_stats()

        # Project profile stats
        if self.profile_manager and project_id:
            stats['project_profile'] = self.profile_manager.get_project_stats(project_id)

        # Cache awareness stats
        if self.cache_coordinator and project_id:
            stats['cache_awareness'] = self.cache_coordinator.get_cache_metrics(project_id)

        return stats


# Global pipeline singleton
_pipeline: Optional[CompressionPipeline] = None


def get_compression_pipeline() -> CompressionPipeline:
    """Get global compression pipeline instance"""
    global _pipeline
    if _pipeline is None:
        _pipeline = CompressionPipeline()
    return _pipeline


def compress_with_pipeline(text: str, project_id: str) -> PipelineResult:
    """Convenience function for pipeline compression"""
    pipeline = get_compression_pipeline()
    return pipeline.compress_memory_context(text, project_id)
