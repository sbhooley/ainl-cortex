"""
Tests for unified compression pipeline
"""

import pytest
import sys
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp_server.compression import EfficientMode
from mcp_server.compression_pipeline import get_compression_pipeline, PipelineResult
from mcp_server.adaptive_eco import ContentAnalyzer, ModeRecommender
from mcp_server.semantic_scoring import SemanticScorer
from mcp_server.project_profiles import ProjectProfileManager
from mcp_server.cache_awareness import CacheCoordinator


class TestContentAnalyzer:
    """Test content analysis"""

    def test_code_detection(self):
        analyzer = ContentAnalyzer()

        # Text with code
        text_with_code = """
        Here's a function:
        ```python
        def hello():
            print("world")
        ```
        """

        chars = analyzer.analyze(text_with_code)
        assert chars.has_code is True
        assert chars.code_ratio > 0.3

    def test_technical_density(self):
        analyzer = ContentAnalyzer()

        # Technical text
        tech_text = "The error exception occurred in the API endpoint during database query execution"
        chars = analyzer.analyze(tech_text)
        assert chars.technical_density > 0.3

        # Non-technical text
        normal_text = "The quick brown fox jumps over the lazy dog"
        chars = analyzer.analyze(normal_text)
        assert chars.technical_density < 0.2

    def test_question_detection(self):
        analyzer = ContentAnalyzer()

        question = "What is the best way to handle errors?"
        chars = analyzer.analyze(question)
        assert chars.is_question is True


class TestModeRecommender:
    """Test adaptive mode recommendations"""

    def test_high_code_ratio_recommends_off(self):
        recommender = ModeRecommender()

        code_heavy = """
        ```python
        # Long code block
        def function1():
            pass

        def function2():
            pass

        def function3():
            pass
        ```
        """

        rec = recommender.recommend(code_heavy, EfficientMode.BALANCED)
        assert rec.mode == EfficientMode.OFF
        assert rec.confidence > 0.8

    def test_long_narrative_recommends_aggressive(self):
        recommender = ModeRecommender()

        narrative = " ".join(["This is a long narrative text."] * 30)

        rec = recommender.recommend(narrative, EfficientMode.BALANCED)
        assert rec.mode == EfficientMode.AGGRESSIVE
        assert rec.confidence > 0.7


class TestSemanticScorer:
    """Test semantic preservation scoring"""

    def test_perfect_preservation(self):
        scorer = SemanticScorer()

        text = "This is a test with error handling"
        score = scorer.score(text, text)

        assert score.overall_score == 1.0
        assert score.key_term_retention == 1.0

    def test_code_preservation(self):
        scorer = SemanticScorer()

        original = "Here's code: ```python\nprint('hello')\n```"
        compressed = "Code: ```python\nprint('hello')\n```"

        score = scorer.score(original, compressed)
        assert score.code_preservation == 1.0

    def test_url_preservation(self):
        scorer = SemanticScorer()

        original = "Check https://example.com for docs"
        compressed = "Check example.com for docs"

        score = scorer.score(original, compressed)
        assert score.url_preservation < 1.0


class TestProjectProfileManager:
    """Test per-project profiles"""

    def test_create_and_get_profile(self, tmp_path):
        manager = ProjectProfileManager(tmp_path)

        profile = manager.get_profile("test_project")
        assert profile.project_id == "test_project"
        assert profile.preferred_mode is None

    def test_set_preferred_mode(self, tmp_path):
        manager = ProjectProfileManager(tmp_path)

        manager.set_preferred_mode("test_project", EfficientMode.AGGRESSIVE)

        mode = manager.get_preferred_mode("test_project")
        assert mode == EfficientMode.AGGRESSIVE

    def test_record_and_auto_detect(self, tmp_path):
        manager = ProjectProfileManager(tmp_path)

        # Record several compressions with balanced mode
        for _ in range(6):
            manager.record_compression(
                "test_project",
                EfficientMode.BALANCED,
                original_tokens=1000,
                compressed_tokens=550,
                quality_score=0.85
            )

        # Auto-detect should recommend balanced
        detected = manager.auto_detect_mode("test_project")
        assert detected == EfficientMode.BALANCED


class TestCacheCoordinator:
    """Test cache awareness"""

    def test_preserve_warm_cache(self):
        coordinator = CacheCoordinator(cache_ttl=300)

        # First decision sets mode
        decision1 = coordinator.decide_mode_with_hysteresis(
            "test_project",
            EfficientMode.BALANCED,
            EfficientMode.BALANCED
        )
        assert decision1.use_mode == EfficientMode.BALANCED

        # Immediately try to change mode - should preserve cache
        decision2 = coordinator.decide_mode_with_hysteresis(
            "test_project",
            EfficientMode.AGGRESSIVE,
            EfficientMode.BALANCED
        )

        # Should keep balanced to preserve cache
        assert decision2.use_mode == EfficientMode.BALANCED
        assert decision2.cache_preserved is True

    def test_hysteresis_prevents_oscillation(self):
        coordinator = CacheCoordinator(cache_ttl=300)

        # Start with balanced
        current = EfficientMode.BALANCED

        # Recommend aggressive
        decision = coordinator.decide_mode_with_hysteresis(
            "test_project",
            EfficientMode.AGGRESSIVE,
            current
        )

        # Should stick with current due to hysteresis
        assert decision.use_mode == EfficientMode.BALANCED
        assert "Hysteresis" in decision.reason


class TestCompressionPipeline:
    """Test full pipeline integration"""

    def test_pipeline_compress_memory_context(self):
        pipeline = get_compression_pipeline()

        text = """
        ## Recent Episodes
        - Fixed authentication error in user login
        - Updated database schema

        ## Patterns
        Read → Edit → Test workflow works well
        """

        result = pipeline.compress_memory_context(text, "test_project")

        assert isinstance(result, PipelineResult)
        assert result.compressed_text is not None
        assert result.mode_used in [EfficientMode.OFF, EfficientMode.BALANCED, EfficientMode.AGGRESSIVE]
        assert result.mode_source in ['manual', 'adaptive', 'project_profile', 'cache_constrained']

    def test_pipeline_respects_config(self):
        pipeline = get_compression_pipeline()

        # Simple text
        text = "This is a simple test message"
        result = pipeline.compress_memory_context(text, "test_project_2")

        # Should complete without errors
        assert result.compressed_text is not None

    def test_pipeline_quality_fallback(self):
        """Test that pipeline falls back to original on low quality"""
        pipeline = get_compression_pipeline()

        # Text that's mostly important technical terms
        # (might trigger quality fallback in aggressive mode)
        text = "error exception failure API endpoint database query SQL"

        result = pipeline.compress_memory_context(text, "test_project_quality")

        # Should have preservation score
        if result.preservation_score:
            # If quality is low, should fallback
            if result.preservation_score.overall_score < 0.7:
                assert result.compressed_text == text


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
