"""
AINL Prompt Compression

Python port of ainl-compression crate from ArmaraOS.
Embedding-free input/output compression for token/cost savings.

Target bands (token savings vs estimated original):
- Balanced: ~40–60% savings (retention ~0.50, floor ~0.40 of original)
- Aggressive: ~60–70% savings (retention ~0.33, floor ~0.30 of original)
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional, List, Tuple, Callable
import re
import time
import logging

logger = logging.getLogger(__name__)


class EfficientMode(str, Enum):
    """Input compression aggressiveness"""
    OFF = "off"
    BALANCED = "balanced"
    AGGRESSIVE = "aggressive"

    @classmethod
    def parse_config(cls, s: str) -> 'EfficientMode':
        """Parse from config string; unknown values → OFF"""
        s_lower = s.lower()
        if s_lower == "balanced":
            return cls.BALANCED
        elif s_lower == "aggressive":
            return cls.AGGRESSIVE
        else:
            return cls.OFF

    @classmethod
    def parse_natural_language(cls, s: str) -> 'EfficientMode':
        """
        Parse from natural language intent.

        Examples:
        - "use aggressive eco mode" -> AGGRESSIVE
        - "balanced mode please" -> BALANCED
        - "disable compression" -> OFF
        """
        lo = s.lower()

        # Check for disable/off
        if any(phrase in lo for phrase in [
            "disable compression", "no compression", "compression off",
            "eco off", "turn off eco", "off mode"
        ]):
            return cls.OFF

        # Check for aggressive
        if any(phrase in lo for phrase in [
            "aggressive", "max savings", "highest savings",
            "ultra eco", "eco aggressive"
        ]):
            return cls.AGGRESSIVE

        # Check for balanced
        if any(phrase in lo for phrase in [
            "balanced", "default eco", "eco balanced",
            "enable eco", "compression on"
        ]):
            return cls.BALANCED

        return cls.parse_config(lo)

    def retention_ratio(self) -> float:
        """
        Target fraction of original tokens to retain after compression
        (before per-pass budgeting; floors clamp max savings).
        """
        if self == EfficientMode.BALANCED:
            return 0.50  # ~50% savings (center of 40–60% band)
        elif self == EfficientMode.AGGRESSIVE:
            return 0.33  # ~67% savings (center of 60–70% band)
        else:
            return 1.0


@dataclass
class CompressionMetrics:
    """Structured telemetry for compression operations"""
    mode: EfficientMode
    original_chars: int
    compressed_chars: int
    original_tokens: int
    compressed_tokens: int
    tokens_saved: int
    savings_ratio_pct: float
    semantic_preservation_score: Optional[float]
    elapsed_ms: int


@dataclass
class Compressed:
    """Result of compression pass"""
    text: str
    original_tokens: int
    compressed_tokens: int

    def tokens_saved(self) -> int:
        """Tokens saved; 0 when compression was no-op"""
        return max(0, self.original_tokens - self.compressed_tokens)


# Token estimation (chars/4 + 1, matching Rust implementation)
def estimate_tokens(s: str) -> int:
    """Estimate token count (same heuristic as ArmaraOS)"""
    return len(s) // 4 + 1


# Filler phrases to strip (from ainl-compression)
FILLERS = [
    "I think ",
    "I believe ",
    "Basically, ",
    "Essentially, ",
    "Of course, ",
    "Please note that ",
    "It is worth noting that ",
    "It's worth noting that ",
    "I would like to ",
    "I'd like to ",
    "Don't hesitate to ",
    "Feel free to ",
    "As you know, ",
    "As mentioned earlier, ",
    "That being said, ",
    "To be honest, ",
    "Needless to say, ",
    # Mid-sentence hedging
    " basically ",
    " essentially ",
    " simply ",
    " just ",
    " very ",
    " really ",
]

# Hard-preserve: force-keep in both Balanced and Aggressive
HARD_PRESERVE = [
    "exact",
    "steps",
    "already tried",
    "already restarted",
    "already checked",
    "restart",
    "daemon",
    "error",
    "http://",
    "https://",
    "R http",
    "R web",
    "L_",
    "->",
    "::",
    ".ainl",
    "opcode",
    "R queue",
    "R llm",
    "R core",
    "```",
    # Claude Code specific
    "claude",
    "mcp",
    "tool",
    "Read",
    "Edit",
    "Bash",
    "src/",
    "crates/",
]

# URLs, paths, inline code, IPs — always keep the whole sentence in every mode
_CRITICAL_SNIPPETS = re.compile(
    r"(https?://[^\s]+|s3://[^\s]+|file://[^\s]+|"
    r"www\.[^\s]+|"
    r"git@[^\s]+|"
    r"`[^`\n]{1,400}`|"
    r"(?:/[\w.-]+){2,}[\w.-]*|"  # unix-ish absolute/relative paths
    r"Traceback|File \"[^\"]+\"|"
    r"\b(?:\d{1,3}\.){3}\d{1,3}\b)",
    re.IGNORECASE,
)

# Soft-preserve: force-keep in Balanced; score-boost only in Aggressive
SOFT_PRESERVE = [
    "##", " ms", " kb", " mb", " gb", " %",
    "openfang", "armaraos", "manifest",
    # Claude Code specific
    "graph memory", "episode", "persona", "pattern",
]


def hard_keep(s: str) -> bool:
    """Check if sentence contains hard-preserve terms or critical structured content."""
    lo = s.lower()
    if any(p.lower() in lo for p in HARD_PRESERVE):
        return True
    return bool(_CRITICAL_SNIPPETS.search(s))


def soft_match(s: str) -> bool:
    """Check if sentence contains soft-preserve terms"""
    lo = s.lower()
    return any(p.lower() in lo for p in SOFT_PRESERVE)


def must_keep(s: str, mode: EfficientMode) -> bool:
    """Check if sentence must be kept regardless of budget"""
    return hard_keep(s) or (mode != EfficientMode.AGGRESSIVE and soft_match(s))


def strip_fillers(text: str) -> str:
    """Remove filler phrases from text"""
    result = text
    for filler in FILLERS:
        result = result.replace(filler, "")

    # Re-capitalize first character if needed
    if result and result[0].islower():
        result = result[0].upper() + result[1:]

    return result


def split_sentences(text: str) -> List[str]:
    """
    Split text into sentences.

    Simple approach: split on '. ' and newlines.
    """
    # Split on periods followed by space, or newlines
    sentences = re.split(r'\.\s+|\n+', text)

    # Clean up and filter empty
    sentences = [s.strip() for s in sentences if s.strip()]

    return sentences


def score_sentence(sentence: str, mode: EfficientMode) -> float:
    """
    Score a sentence for importance.

    Higher scores = more likely to keep.
    """
    score = 1.0

    # Length bonus (longer sentences often more informative)
    length = len(sentence)
    if length > 100:
        score += 0.5
    elif length > 50:
        score += 0.3

    # Soft match bonus (in aggressive, this is just a boost not force-keep)
    if soft_match(sentence):
        score += 0.4 if mode == EfficientMode.AGGRESSIVE else 1.0

    # Aggressive penalties
    if mode == EfficientMode.AGGRESSIVE:
        # Penalize meta/trailing explanations
        if sentence.startswith(("This ", "These ", "It ", "Which ")):
            score -= 0.3

        # Penalize very short sentences
        if length < 20:
            score -= 0.2

    return score


def compress_prose(text: str, budget: int, mode: EfficientMode) -> str:
    """
    Compress prose text to fit within token budget.

    Splits into sentences, scores them, packs high-scoring ones.
    """
    if not text.strip():
        return text

    sentences = split_sentences(text)

    # Very short blocks: keep as-is
    if len(sentences) <= 2:
        return text

    # Score and sort sentences
    scored = []
    for sent in sentences:
        # Must-keep sentences always included
        if must_keep(sent, mode):
            scored.append((sent, float('inf')))
        else:
            score = score_sentence(sent, mode)
            scored.append((sent, score))

    # Sort by score descending
    scored.sort(key=lambda x: x[1], reverse=True)

    # Pack sentences into budget
    result = []
    tokens_used = 0

    for sent, score in scored:
        sent_tokens = estimate_tokens(sent)

        # Always include must-keep (infinite score)
        if score == float('inf'):
            result.append(sent)
            tokens_used += sent_tokens
        elif tokens_used + sent_tokens <= budget:
            result.append(sent)
            tokens_used += sent_tokens

    # Reassemble in original order (approximately)
    # This is simplified - full version would track original indices
    result_text = ". ".join(result)
    if result_text and not result_text.endswith('.'):
        result_text += "."

    return strip_fillers(result_text)


def extract_code_blocks(text: str) -> List[Tuple[bool, str]]:
    """
    Extract code blocks from text.

    Returns list of (is_code, content) tuples.
    Code blocks (```...```) are preserved verbatim.
    """
    blocks = []
    rest = text

    while "```" in rest:
        # Find opening fence
        fence_start = rest.find("```")

        # Add prose before fence
        if fence_start > 0:
            blocks.append((False, rest[:fence_start]))

        # Find closing fence
        rest = rest[fence_start + 3:]
        fence_end = rest.find("```")

        if fence_end != -1:
            # Complete code block
            blocks.append((True, f"```{rest[:fence_end]}```"))
            rest = rest[fence_end + 3:]
        else:
            # Unclosed code block - keep rest as code
            blocks.append((True, f"```{rest}"))
            rest = ""
            break

    # Add remaining prose
    if rest:
        blocks.append((False, rest))

    return blocks


def _max_savings_ratio(mode: EfficientMode) -> float:
    """Upper bound on fractional token savings for the mode (heuristic estimates)."""
    if mode == EfficientMode.BALANCED:
        return 0.60
    if mode == EfficientMode.AGGRESSIVE:
        return 0.70
    return 0.0


def _assemble_compressed(
    text: str,
    mode: EfficientMode,
    original_tokens: int,
    budget: int,
) -> tuple[str, int]:
    """Rebuild compressed text for a given total token budget."""
    blocks = extract_code_blocks(text)
    code_tokens = sum(
        estimate_tokens(content)
        for is_code, content in blocks
        if is_code
    )
    prose_budget = max(0, budget - code_tokens)
    result_blocks = []
    pb = prose_budget
    for is_code, content in blocks:
        if is_code:
            result_blocks.append(content)
        else:
            compressed_prose = compress_prose(content, pb, mode)
            pb = max(0, pb - estimate_tokens(compressed_prose))
            if compressed_prose.strip():
                result_blocks.append(compressed_prose)
    result = "\n\n".join(result_blocks).strip()
    return result, estimate_tokens(result)


def compress(text: str, mode: EfficientMode) -> Compressed:
    """
    Compress text toward mode.retention_ratio() of original token budget.

    Prompts shorter than 80 tokens, or OFF mode, pass through unchanged.
    Code fences (```) are extracted and re-inserted verbatim.
    """
    original_tokens = estimate_tokens(text)

    # Passthrough conditions
    if mode == EfficientMode.OFF or original_tokens < 80:
        return Compressed(
            text=text,
            original_tokens=original_tokens,
            compressed_tokens=original_tokens
        )

    # Calculate budget (mode-specific floor to prevent over-compression)
    target_budget = int(original_tokens * mode.retention_ratio())

    # Floors cap maximum savings so modes stay in intended bands.
    if mode == EfficientMode.AGGRESSIVE:
        # Floor ~30% of original → at most ~70% token savings
        min_budget = max(int(original_tokens * 0.30), 12)
    else:  # BALANCED
        # Floor ~40% of original → at most ~60% token savings
        min_budget = max(int(original_tokens * 0.40), 15)

    budget = max(target_budget, min_budget)

    result, compressed_tokens = _assemble_compressed(
        text, mode, original_tokens, budget
    )

    # Widen budget if sentence packing removed more than the policy cap allows
    cap = _max_savings_ratio(mode)
    widen_rounds = 0
    while (
        cap > 0
        and original_tokens > 0
        and compressed_tokens < original_tokens
        and (original_tokens - compressed_tokens) / original_tokens > cap
        and widen_rounds < 14
    ):
        budget = min(original_tokens, int(budget * 1.07) + 12)
        result, compressed_tokens = _assemble_compressed(
            text, mode, original_tokens, budget
        )
        widen_rounds += 1

    # Safety: never return longer than original
    if compressed_tokens >= original_tokens:
        logger.debug(f"No compression gain ({compressed_tokens} >= {original_tokens}), using original")
        return Compressed(
            text=text,
            original_tokens=original_tokens,
            compressed_tokens=original_tokens
        )

    savings_pct = ((original_tokens - compressed_tokens) * 100) // max(original_tokens, 1)
    logger.info(
        f"Compressed: {original_tokens} → {compressed_tokens} tokens "
        f"({savings_pct}% savings, mode={mode.value})"
    )

    return Compressed(
        text=result,
        original_tokens=original_tokens,
        compressed_tokens=compressed_tokens
    )


class PromptCompressor:
    """
    Standalone input prompt compressor.

    This is the public API for agents that want to adopt
    AINL eco-mode compression.
    """

    def __init__(
        self,
        mode: EfficientMode,
        telemetry_callback: Optional[Callable[[CompressionMetrics], None]] = None
    ):
        self.mode = mode
        self.telemetry_callback = telemetry_callback

    @classmethod
    def from_natural_language(cls, mode_hint: str) -> 'PromptCompressor':
        """Create compressor from natural language hint"""
        mode = EfficientMode.parse_natural_language(mode_hint)
        return cls(mode)

    def compress(self, text: str) -> Compressed:
        """Compress text with current mode"""
        return self.compress_with_semantic_score(text, None)

    def compress_with_semantic_score(
        self,
        text: str,
        semantic_preservation_score: Optional[float] = None
    ) -> Compressed:
        """Compress with optional semantic preservation tracking"""
        start_time = time.time()

        result = compress(text, self.mode)

        elapsed_ms = int((time.time() - start_time) * 1000)

        # Emit telemetry if callback provided
        if self.telemetry_callback:
            tokens_saved = result.tokens_saved()
            savings_pct = (
                (tokens_saved * 100.0) / result.original_tokens
                if result.original_tokens > 0
                else 0.0
            )

            metrics = CompressionMetrics(
                mode=self.mode,
                original_chars=len(text),
                compressed_chars=len(result.text),
                original_tokens=result.original_tokens,
                compressed_tokens=result.compressed_tokens,
                tokens_saved=tokens_saved,
                savings_ratio_pct=savings_pct,
                semantic_preservation_score=semantic_preservation_score,
                elapsed_ms=elapsed_ms
            )

            self.telemetry_callback(metrics)

        return result


# Convenience function for one-off compression
def compress_text(
    text: str,
    mode: str = "balanced",
    emit_metrics: bool = False
) -> Tuple[str, Optional[CompressionMetrics]]:
    """
    Compress text with specified mode.

    Args:
        text: Input text to compress
        mode: "off", "balanced", or "aggressive"
        emit_metrics: Whether to return metrics

    Returns:
        Tuple of (compressed_text, metrics)
    """
    efficient_mode = EfficientMode.parse_config(mode)

    metrics_collected = None

    def collect_metrics(m: CompressionMetrics):
        nonlocal metrics_collected
        metrics_collected = m

    compressor = PromptCompressor(
        mode=efficient_mode,
        telemetry_callback=collect_metrics if emit_metrics else None
    )

    result = compressor.compress(text)

    return result.text, metrics_collected
