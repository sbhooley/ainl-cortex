#!/usr/bin/env python3
"""
Compression CLI

Manage compression settings and test compression algorithms.
"""

import sys
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp_server.compression import PromptCompressor, EfficientMode, compress_text
from mcp_server.config import get_config
import argparse


def cmd_test(args):
    """Test compression on sample text"""
    if args.file:
        with open(args.file, 'r') as f:
            text = f.read()
    elif args.text:
        text = args.text
    else:
        # Read from stdin
        text = sys.stdin.read()

    compressed, metrics = compress_text(text, mode=args.mode, emit_metrics=True)

    print(f"\n=== Compression Results (mode={args.mode}) ===")
    print(f"Original:    {metrics.original_tokens} tokens ({metrics.original_chars} chars)")
    print(f"Compressed:  {metrics.compressed_tokens} tokens ({metrics.compressed_chars} chars)")
    print(f"Saved:       {metrics.tokens_saved} tokens ({metrics.savings_ratio_pct:.1f}%)")
    print(f"Time:        {metrics.elapsed_ms}ms")

    if args.show_output:
        print(f"\n=== Compressed Text ===")
        print(compressed)


def cmd_config(args):
    """Show or update compression configuration"""
    config = get_config()

    if args.mode:
        # Set mode
        config.set_compression_mode(args.mode)
        print(f"✓ Compression mode set to: {args.mode}")
    else:
        # Show current config
        print(f"\n=== Compression Configuration ===")
        print(f"Enabled:       {config.is_compression_enabled()}")
        print(f"Mode:          {config.get_compression_mode().value}")
        print(f"Compress ctx:  {config.should_compress_memory_context()}")
        print(f"\nConfig file:   {config.config_path}")


def cmd_benchmark(args):
    """Benchmark compression modes"""
    samples = [
        ("Short", "This is a short test message with some basic content."),
        ("Medium", """
        This is a medium-length test message with multiple sentences.
        It contains some technical terms like HTTP, error messages, and steps.
        The compression algorithm should handle this reasonably well.
        We expect to see some savings but not too aggressive.
        """),
        ("Long", """
        This is a much longer test message designed to trigger compression.
        I think we should basically see some good results here. Essentially,
        the compression algorithm needs to remove filler words and keep the
        important content. Of course, this means preserving technical terms
        like HTTP, daemon, error, and already tried steps.

        To be honest, the algorithm should keep code fences:
        ```python
        def example():
            return "preserved"
        ```

        Feel free to test this with various modes. As you know, balanced mode
        targets around 55% retention while aggressive mode goes for 35%.
        That being said, both modes should preserve critical information.
        Needless to say, the results will vary based on content type.
        """),
    ]

    modes = ["balanced", "aggressive"]

    print("\n=== Compression Benchmark ===\n")

    for sample_name, text in samples:
        print(f"Sample: {sample_name} ({len(text)} chars)")
        original_tokens = len(text) // 4 + 1

        for mode in modes:
            compressed, metrics = compress_text(text, mode=mode, emit_metrics=True)
            print(f"  {mode:12} → {metrics.compressed_tokens:4} tok ({metrics.savings_ratio_pct:5.1f}% saved)")

        print()


def main():
    parser = argparse.ArgumentParser(
        description="AINL Graph Memory - Compression CLI"
    )

    subparsers = parser.add_subparsers(dest='command', help='Commands')

    # Test command
    test_parser = subparsers.add_parser('test', help='Test compression on text')
    test_parser.add_argument(
        '--mode',
        choices=['off', 'balanced', 'aggressive'],
        default='balanced',
        help='Compression mode'
    )
    test_parser.add_argument('--file', '-f', help='Input file (default: stdin)')
    test_parser.add_argument('--text', '-t', help='Input text directly')
    test_parser.add_argument('--show-output', '-s', action='store_true', help='Show compressed output')
    test_parser.set_defaults(func=cmd_test)

    # Config command
    config_parser = subparsers.add_parser('config', help='Show or update configuration')
    config_parser.add_argument(
        '--mode',
        choices=['off', 'balanced', 'aggressive'],
        help='Set compression mode'
    )
    config_parser.set_defaults(func=cmd_config)

    # Benchmark command
    benchmark_parser = subparsers.add_parser('benchmark', help='Benchmark compression modes')
    benchmark_parser.set_defaults(func=cmd_benchmark)

    args = parser.parse_args()

    if hasattr(args, 'func'):
        args.func(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
