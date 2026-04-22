"""
Output Compression

Compresses Claude's responses before display to save tokens and improve readability.
More conservative than input compression - preserves all technical content.
"""

import re
from typing import Tuple, Optional
from dataclasses import dataclass
import logging

try:
    from .compression import EfficientMode, CompressionMetrics, compress_text
except ImportError:
    from compression import EfficientMode, CompressionMetrics, compress_text

logger = logging.getLogger(__name__)


@dataclass
class OutputCompressionConfig:
    """Configuration for output compression"""
    enabled: bool
    mode: EfficientMode
    preserve_code: bool  # Always True for output
    preserve_commands: bool  # Preserve command suggestions
    preserve_file_paths: bool  # Preserve all file references
    min_length_tokens: int  # Only compress if response is longer than this


class OutputCompressor:
    """
    Compresses assistant responses with conservative settings.

    Differences from input compression:
    - More aggressive code/command preservation
    - Preserve file paths and line numbers
    - Preserve numbered lists and steps
    - Less aggressive on technical terms
    """

    # Additional preserve patterns for output
    OUTPUT_HARD_PRESERVE = [
        # File references
        r'\w+\.\w+:\d+',  # file.ext:123
        r'[/\\][\w./\\-]+',  # paths

        # Commands and tools
        r'`[^`]+`',  # inline code
        r'\$\s+\w+',  # shell commands

        # Numbered lists and steps
        r'^\d+\.',  # 1. 2. 3.
        r'^\s*[-*]\s',  # bullet points

        # Results and metrics
        r'\d+\s*(?:ms|kb|mb|gb|%)',  # measurements
        r'\d+\s+(?:tokens?|files?|lines?)',  # counts

        # Important markers
        r'(?:TODO|FIXME|NOTE|WARNING|ERROR):',
        r'(?:Success|Failed|Completed):',
    ]

    def __init__(self, config: Optional[OutputCompressionConfig] = None):
        """
        Args:
            config: Output compression configuration
        """
        if config is None:
            config = OutputCompressionConfig(
                enabled=False,  # Default to disabled
                mode=EfficientMode.BALANCED,
                preserve_code=True,
                preserve_commands=True,
                preserve_file_paths=True,
                min_length_tokens=200  # Only compress longer responses
            )

        self.config = config

    def should_compress(self, text: str) -> bool:
        """Determine if output should be compressed"""
        if not self.config.enabled:
            return False

        # Estimate tokens
        estimated_tokens = len(text) // 4 + 1

        if estimated_tokens < self.config.min_length_tokens:
            return False

        return True

    def extract_structured_content(self, text: str) -> list:
        """
        Extract structured content that should be preserved.

        Returns list of (start, end, content_type) tuples.
        """
        preserved = []

        # Code blocks (highest priority)
        for match in re.finditer(r'```[\s\S]*?```', text):
            preserved.append((match.start(), match.end(), 'code_block'))

        # File path with line numbers
        for match in re.finditer(r'\w+\.\w+:\d+', text):
            preserved.append((match.start(), match.end(), 'file_ref'))

        # Commands (lines starting with $ or containing tool names)
        for match in re.finditer(r'^[>\$]\s+.*$', text, re.MULTILINE):
            preserved.append((match.start(), match.end(), 'command'))

        # Numbered steps
        for match in re.finditer(r'^\d+\..*$', text, re.MULTILINE):
            preserved.append((match.start(), match.end(), 'step'))

        # Sort by start position
        preserved.sort(key=lambda x: x[0])

        return preserved

    def compress(self, text: str) -> Tuple[str, Optional[CompressionMetrics]]:
        """
        Compress output text.

        Returns:
            (compressed_text, metrics)
        """
        if not self.should_compress(text):
            return text, None

        # Use conservative mode for output
        mode = EfficientMode.BALANCED if self.config.mode == EfficientMode.AGGRESSIVE else self.config.mode

        try:
            compressed, metrics = compress_text(text, mode=mode.value, emit_metrics=True)

            if metrics and metrics.tokens_saved > 0:
                logger.info(
                    f"Compressed output: {metrics.original_tokens} → "
                    f"{metrics.compressed_tokens} tokens ({metrics.savings_ratio_pct:.0f}% savings)"
                )
                return compressed, metrics
            else:
                # No savings, return original
                return text, None

        except Exception as e:
            logger.warning(f"Output compression failed: {e}")
            return text, None

    def format_compression_badge(self, metrics: CompressionMetrics) -> str:
        """Format a badge to show compression was applied"""
        if metrics.tokens_saved <= 0:
            return ""

        return f"\n\n_⚡ Response compressed: {metrics.savings_ratio_pct:.0f}% token savings_"

    def compress_with_badge(self, text: str, show_badge: bool = True) -> Tuple[str, Optional[CompressionMetrics]]:
        """
        Compress output and optionally add compression badge.

        Returns:
            (compressed_text_with_badge, metrics)
        """
        compressed, metrics = self.compress(text)

        if show_badge and metrics and metrics.tokens_saved > 0:
            badge = self.format_compression_badge(metrics)
            compressed = compressed + badge

        return compressed, metrics


def compress_output(text: str,
                    enabled: bool = False,
                    mode: EfficientMode = EfficientMode.BALANCED,
                    show_badge: bool = False) -> Tuple[str, Optional[CompressionMetrics]]:
    """
    Convenience function for output compression.

    Args:
        text: Text to compress
        enabled: Whether compression is enabled
        mode: Compression mode
        show_badge: Whether to show compression badge

    Returns:
        (compressed_text, metrics)
    """
    config = OutputCompressionConfig(
        enabled=enabled,
        mode=mode,
        preserve_code=True,
        preserve_commands=True,
        preserve_file_paths=True,
        min_length_tokens=200
    )

    compressor = OutputCompressor(config)

    if show_badge:
        return compressor.compress_with_badge(text, show_badge=True)
    else:
        return compressor.compress(text)
