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
                "min_tokens_for_compression": 80
            },
            "memory": {
                "max_context_tokens": 800,
                "project_isolation": True,
                "enable_persona_evolution": True,
                "enable_pattern_extraction": True
            },
            "telemetry": {
                "track_compression_savings": True,
                "log_compression_details": False
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


# Global config singleton
_config: Optional[PluginConfig] = None


def get_config() -> PluginConfig:
    """Get global configuration instance"""
    global _config
    if _config is None:
        _config = PluginConfig()
    return _config
