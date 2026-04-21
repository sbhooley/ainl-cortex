"""
Configuration Management

Handles plugin configuration including eco mode settings.
"""

from pathlib import Path
from typing import Optional
import json
import logging

from .compression import EfficientMode

logger = logging.getLogger(__name__)


class PluginConfig:
    """Plugin configuration singleton"""

    def __init__(self):
        self.config_path = Path.home() / ".claude" / "plugins" / "ainl-graph-memory" / "config.json"
        self.config = self._load_config()

    def _load_config(self) -> dict:
        """Load configuration from file"""
        if self.config_path.exists():
            try:
                with open(self.config_path, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load config: {e}, using defaults")

        # Default configuration
        return {
            "compression": {
                "enabled": True,
                "mode": "balanced",  # off, balanced, aggressive
                "compress_memory_context": True,
                "compress_user_prompt": False,  # Optional: compress user input
                "compress_output": False,  # Compress Claude's responses
                "min_tokens_for_compression": 80,

                # Adaptive eco mode
                "adaptive_eco": {
                    "enabled": True,
                    "min_confidence": 0.7,  # Min confidence to override manual mode
                    "hysteresis_count": 2  # Consistent recommendations before switching
                },

                # Semantic preservation scoring
                "semantic_scoring": {
                    "enabled": True,
                    "min_overall_score": 0.70,  # Fallback if score too low
                    "min_key_term_retention": 0.80,  # Min key term preservation
                    "track_quality": True
                },

                # Per-project profiles
                "project_profiles": {
                    "enabled": True,
                    "auto_detect_mode": True,  # Auto-detect best mode per project
                    "min_compressions_for_detection": 5
                },

                # Cache awareness
                "cache_awareness": {
                    "enabled": True,
                    "cache_ttl": 300,  # 5 minutes (Anthropic/OpenAI default)
                    "hysteresis_duration": 120,  # 2 minutes before mode switch
                    "preserve_warm_cache": True
                },

                # Output compression
                "output": {
                    "enabled": False,
                    "mode": "balanced",
                    "min_length_tokens": 200,
                    "show_badge": False  # Show compression savings badge
                }
            },
            "memory": {
                "max_context_tokens": 800,
                "project_isolation": True,
                "enable_persona_evolution": True,
                "enable_pattern_extraction": True
            },
            "telemetry": {
                "track_compression_savings": True,
                "log_compression_details": False,
                "track_quality_scores": True,
                "track_adaptive_decisions": True
            }
        }

    def save_config(self) -> None:
        """Save configuration to file"""
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_path, 'w') as f:
                json.dump(self.config, f, indent=2)
            logger.info(f"Configuration saved to {self.config_path}")
        except Exception as e:
            logger.error(f"Failed to save config: {e}")

    def get_compression_mode(self) -> EfficientMode:
        """Get current compression mode"""
        mode_str = self.config.get("compression", {}).get("mode", "balanced")
        return EfficientMode.parse_config(mode_str)

    def set_compression_mode(self, mode: str) -> None:
        """Set compression mode"""
        if "compression" not in self.config:
            self.config["compression"] = {}

        self.config["compression"]["mode"] = mode
        self.save_config()
        logger.info(f"Compression mode set to: {mode}")

    def is_compression_enabled(self) -> bool:
        """Check if compression is enabled"""
        return self.config.get("compression", {}).get("enabled", True)

    def should_compress_memory_context(self) -> bool:
        """Check if memory context should be compressed"""
        return (
            self.is_compression_enabled() and
            self.config.get("compression", {}).get("compress_memory_context", True)
        )

    # Adaptive eco mode
    def is_adaptive_eco_enabled(self) -> bool:
        """Check if adaptive eco mode is enabled"""
        return self.config.get("compression", {}).get("adaptive_eco", {}).get("enabled", True)

    def get_adaptive_eco_config(self) -> dict:
        """Get adaptive eco configuration"""
        return self.config.get("compression", {}).get("adaptive_eco", {
            "enabled": True,
            "min_confidence": 0.7,
            "hysteresis_count": 2
        })

    # Semantic scoring
    def is_semantic_scoring_enabled(self) -> bool:
        """Check if semantic scoring is enabled"""
        return self.config.get("compression", {}).get("semantic_scoring", {}).get("enabled", True)

    def get_semantic_scoring_config(self) -> dict:
        """Get semantic scoring configuration"""
        return self.config.get("compression", {}).get("semantic_scoring", {
            "enabled": True,
            "min_overall_score": 0.70,
            "min_key_term_retention": 0.80,
            "track_quality": True
        })

    # Project profiles
    def is_project_profiles_enabled(self) -> bool:
        """Check if per-project profiles are enabled"""
        return self.config.get("compression", {}).get("project_profiles", {}).get("enabled", True)

    def get_project_profiles_config(self) -> dict:
        """Get project profiles configuration"""
        return self.config.get("compression", {}).get("project_profiles", {
            "enabled": True,
            "auto_detect_mode": True,
            "min_compressions_for_detection": 5
        })

    # Cache awareness
    def is_cache_awareness_enabled(self) -> bool:
        """Check if cache awareness is enabled"""
        return self.config.get("compression", {}).get("cache_awareness", {}).get("enabled", True)

    def get_cache_awareness_config(self) -> dict:
        """Get cache awareness configuration"""
        return self.config.get("compression", {}).get("cache_awareness", {
            "enabled": True,
            "cache_ttl": 300,
            "hysteresis_duration": 120,
            "preserve_warm_cache": True
        })

    # Output compression
    def is_output_compression_enabled(self) -> bool:
        """Check if output compression is enabled"""
        return self.config.get("compression", {}).get("output", {}).get("enabled", False)

    def get_output_compression_config(self) -> dict:
        """Get output compression configuration"""
        return self.config.get("compression", {}).get("output", {
            "enabled": False,
            "mode": "balanced",
            "min_length_tokens": 200,
            "show_badge": False
        })


# Global config singleton
_config: Optional[PluginConfig] = None


def get_config() -> PluginConfig:
    """Get global configuration instance"""
    global _config
    if _config is None:
        _config = PluginConfig()
    return _config
