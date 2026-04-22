"""
Prompt Cache Awareness

Coordinates compression decisions with provider-level prompt caching.
Prevents compression oscillation that breaks cache effectiveness.

Key insight: Anthropic/OpenAI cache has 5-minute TTL. Changing compression
mode within that window breaks cache, negating token savings.
"""

from typing import Optional, Dict
from dataclasses import dataclass
from datetime import datetime
import logging

try:
    from .compression import EfficientMode
except ImportError:
    from compression import EfficientMode

logger = logging.getLogger(__name__)


@dataclass
class CacheState:
    """State of prompt cache for a project"""
    project_id: str
    current_mode: Optional[EfficientMode]
    mode_set_at: float  # timestamp when mode was set
    cache_ttl: int  # Cache TTL in seconds (default 300 for most providers)
    is_warm: bool  # Whether cache is currently warm


@dataclass
class CacheDecision:
    """Decision about cache-aware compression"""
    use_mode: EfficientMode
    reason: str
    cache_preserved: bool
    recommended_mode: Optional[EfficientMode]  # What we would use without cache constraint


class CacheCoordinator:
    """
    Coordinates compression mode changes with prompt cache state.

    Rules:
    1. If cache is warm (< TTL), avoid mode changes
    2. Use hysteresis to prevent oscillation
    3. Only change mode if benefit outweighs cache miss cost
    """

    # Provider cache TTLs (seconds)
    CACHE_TTL_ANTHROPIC = 300  # 5 minutes
    CACHE_TTL_OPENAI = 300  # 5 minutes
    CACHE_TTL_DEFAULT = 300

    # Hysteresis: require mode to be better for this many seconds before switching
    HYSTERESIS_DURATION = 120  # 2 minutes

    def __init__(self, cache_ttl: int = CACHE_TTL_DEFAULT):
        """
        Args:
            cache_ttl: Cache time-to-live in seconds
        """
        self.cache_ttl = cache_ttl
        self.cache_states: Dict[str, CacheState] = {}
        self.mode_candidates: Dict[str, tuple] = {}  # project_id -> (mode, first_seen_at)

    def get_cache_state(self, project_id: str) -> CacheState:
        """Get current cache state for project"""
        if project_id not in self.cache_states:
            self.cache_states[project_id] = CacheState(
                project_id=project_id,
                current_mode=None,
                mode_set_at=0.0,
                cache_ttl=self.cache_ttl,
                is_warm=False
            )

        state = self.cache_states[project_id]

        # Update warmth
        now = datetime.now().timestamp()
        time_since_set = now - state.mode_set_at
        state.is_warm = time_since_set < self.cache_ttl

        return state

    def should_preserve_cache(self,
                             project_id: str,
                             recommended_mode: EfficientMode,
                             current_mode: EfficientMode) -> bool:
        """
        Determine if we should preserve cache by keeping current mode.

        Returns True if cache is warm and mode change would break it.
        """
        if recommended_mode == current_mode:
            return False  # No change needed

        state = self.get_cache_state(project_id)

        # If cache is warm, preserve it
        if state.is_warm and state.current_mode == current_mode:
            logger.debug(
                f"Cache warm for {project_id}, preserving current mode: {current_mode.value}"
            )
            return True

        return False

    def decide_mode_with_hysteresis(self,
                                    project_id: str,
                                    recommended_mode: EfficientMode,
                                    current_mode: EfficientMode) -> CacheDecision:
        """
        Decide compression mode with cache-aware hysteresis.

        Hysteresis prevents oscillation:
        - Track how long recommended_mode has been the same
        - Only switch after HYSTERESIS_DURATION seconds of consistency
        - Reset if recommended_mode changes
        """
        now = datetime.now().timestamp()
        state = self.get_cache_state(project_id)

        # If modes match, no decision needed
        if recommended_mode == current_mode:
            # Clear candidate
            if project_id in self.mode_candidates:
                del self.mode_candidates[project_id]

            return CacheDecision(
                use_mode=current_mode,
                reason="Recommended mode matches current",
                cache_preserved=True,
                recommended_mode=recommended_mode
            )

        # Check if we have a candidate mode
        if project_id in self.mode_candidates:
            candidate_mode, first_seen = self.mode_candidates[project_id]

            if candidate_mode != recommended_mode:
                # Recommendation changed, reset hysteresis
                logger.debug(
                    f"Mode recommendation changed from {candidate_mode.value} "
                    f"to {recommended_mode.value}, resetting hysteresis"
                )
                self.mode_candidates[project_id] = (recommended_mode, now)
                candidate_mode = recommended_mode
                first_seen = now
        else:
            # First time seeing this recommendation
            self.mode_candidates[project_id] = (recommended_mode, now)
            candidate_mode = recommended_mode
            first_seen = now

        # Check hysteresis duration
        duration = now - first_seen

        # If cache is warm, wait longer before switching
        required_duration = self.HYSTERESIS_DURATION
        if state.is_warm:
            required_duration = self.cache_ttl  # Wait for cache to expire

        if duration < required_duration:
            # Not enough time passed, keep current mode
            return CacheDecision(
                use_mode=current_mode,
                reason=(
                    f"Hysteresis: waiting {required_duration - duration:.0f}s more "
                    f"({'cache warm' if state.is_warm else 'preventing oscillation'})"
                ),
                cache_preserved=state.is_warm,
                recommended_mode=recommended_mode
            )

        # Hysteresis satisfied, switch mode
        logger.info(
            f"Switching compression mode for {project_id}: "
            f"{current_mode.value} → {recommended_mode.value} "
            f"(stable for {duration:.0f}s)"
        )

        # Update cache state
        state.current_mode = recommended_mode
        state.mode_set_at = now
        state.is_warm = True

        # Clear candidate
        if project_id in self.mode_candidates:
            del self.mode_candidates[project_id]

        return CacheDecision(
            use_mode=recommended_mode,
            reason=f"Hysteresis satisfied ({duration:.0f}s stable)",
            cache_preserved=False,
            recommended_mode=recommended_mode
        )

    def estimate_cache_savings(self,
                               project_id: str,
                               tokens_per_turn: int) -> Dict[str, float]:
        """
        Estimate token savings from cache vs compression.

        Compares:
        - Cache savings (100% on cached prefix)
        - Compression savings (40-70% on full context)
        """
        state = self.get_cache_state(project_id)

        # Assume 50% of context can be cached (system + memory prefix)
        cacheable_tokens = tokens_per_turn * 0.5
        compressible_tokens = tokens_per_turn

        # Cache savings (if warm)
        cache_savings = cacheable_tokens if state.is_warm else 0

        # Compression savings (varies by mode)
        compression_savings_balanced = compressible_tokens * 0.45  # 45% savings
        compression_savings_aggressive = compressible_tokens * 0.65  # 65% savings

        return {
            'cache_savings': cache_savings,
            'compression_balanced': compression_savings_balanced,
            'compression_aggressive': compression_savings_aggressive,
            'cache_is_warm': state.is_warm,
            'recommendation': (
                'Keep cache warm with stable mode' if state.is_warm
                else 'Cache cold, compression recommended'
            )
        }

    def reset_cache(self, project_id: str):
        """Reset cache state (e.g., after conversation reset)"""
        if project_id in self.cache_states:
            del self.cache_states[project_id]
        if project_id in self.mode_candidates:
            del self.mode_candidates[project_id]
        logger.debug(f"Reset cache state for {project_id}")

    def get_cache_metrics(self, project_id: str) -> Dict:
        """Get cache metrics for monitoring"""
        state = self.get_cache_state(project_id)
        now = datetime.now().timestamp()

        metrics = {
            'project_id': project_id,
            'current_mode': state.current_mode.value if state.current_mode else None,
            'cache_is_warm': state.is_warm,
            'cache_age_seconds': now - state.mode_set_at if state.mode_set_at > 0 else None,
            'cache_ttl': state.cache_ttl,
            'time_until_cold': max(0, state.cache_ttl - (now - state.mode_set_at)) if state.is_warm else 0
        }

        # Add candidate info if exists
        if project_id in self.mode_candidates:
            candidate_mode, first_seen = self.mode_candidates[project_id]
            metrics['candidate_mode'] = candidate_mode.value
            metrics['candidate_duration'] = now - first_seen

        return metrics


# Global singleton
_cache_coordinator: Optional[CacheCoordinator] = None


def get_cache_coordinator() -> CacheCoordinator:
    """Get global cache coordinator instance"""
    global _cache_coordinator
    if _cache_coordinator is None:
        _cache_coordinator = CacheCoordinator()
    return _cache_coordinator
