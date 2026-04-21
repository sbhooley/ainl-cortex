#!/usr/bin/env python3
"""
Advanced Compression CLI

Manage and monitor advanced compression features:
- Adaptive eco mode
- Semantic preservation scoring
- Per-project profiles
- Cache awareness
- Output compression
"""

import sys
import json
from pathlib import Path
from datetime import datetime

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp_server.compression import EfficientMode
from mcp_server.compression_pipeline import get_compression_pipeline, compress_with_pipeline
from mcp_server.config import get_config
from mcp_server.project_profiles import get_profile_manager
from mcp_server.cache_awareness import get_cache_coordinator
import argparse


def cmd_pipeline_test(args):
    """Test compression pipeline with all enhancements"""
    if args.file:
        with open(args.file, 'r') as f:
            text = f.read()
    elif args.text:
        text = args.text
    else:
        text = sys.stdin.read()

    project_id = args.project_id or "test_project"

    # Run through pipeline
    result = compress_with_pipeline(text, project_id)

    print(f"\n=== Pipeline Compression Results ===")
    print(f"Project ID:  {project_id}")
    print(f"Mode used:   {result.mode_used.value}")
    print(f"Mode source: {result.mode_source}")

    if result.compression_metrics:
        m = result.compression_metrics
        print(f"\nCompression:")
        print(f"  Original:    {m.original_tokens} tokens ({m.original_chars} chars)")
        print(f"  Compressed:  {m.compressed_tokens} tokens ({m.compressed_chars} chars)")
        print(f"  Saved:       {m.tokens_saved} tokens ({m.savings_ratio_pct:.1f}%)")

    if result.preservation_score:
        p = result.preservation_score
        print(f"\nQuality:")
        print(f"  Overall:     {p.overall_score:.2%}")
        print(f"  Key terms:   {p.key_term_retention:.2%}")
        print(f"  Structure:   {p.structural_similarity:.2%}")
        print(f"  Code:        {p.code_preservation:.2%}")

    if result.cache_decision:
        c = result.cache_decision
        print(f"\nCache:")
        print(f"  Decision:    {c.reason}")
        print(f"  Preserved:   {c.cache_preserved}")

    if result.warnings:
        print(f"\nWarnings:")
        for warning in result.warnings:
            print(f"  - {warning}")

    if args.show_output:
        print(f"\n=== Compressed Text ===")
        print(result.compressed_text)


def cmd_adaptive_stats(args):
    """Show adaptive eco mode statistics"""
    pipeline = get_compression_pipeline()

    if pipeline.adaptive_policy is None:
        print("Adaptive eco mode is not enabled")
        return

    stats = pipeline.adaptive_policy.get_stats()

    print("\n=== Adaptive Eco Mode Statistics ===")

    if not stats:
        print("No decisions recorded yet")
        return

    print(f"Total decisions:    {stats.get('total_decisions', 0)}")
    print(f"Avg confidence:     {stats.get('avg_confidence', 0):.2%}")
    print(f"Avg effectiveness:  {stats.get('avg_effectiveness', 0):.2%}")

    by_mode = stats.get('by_mode', {})
    if by_mode:
        print("\nEffectiveness by mode:")
        for mode, effectiveness in by_mode.items():
            print(f"  {mode:12} → {effectiveness:.2%}")


def cmd_quality_stats(args):
    """Show semantic preservation quality statistics"""
    pipeline = get_compression_pipeline()

    if pipeline.semantic_scorer is None:
        print("Semantic scoring is not enabled")
        return

    stats = pipeline.semantic_scorer.get_quality_stats()

    print("\n=== Semantic Preservation Quality ===")

    if not stats:
        print("No quality scores recorded yet")
        return

    print(f"Total compressions: {stats.get('total_compressions', 0)}")
    print(f"\nAverage scores:")
    print(f"  Overall:          {stats.get('avg_overall_score', 0):.2%}")
    print(f"  Key terms:        {stats.get('avg_key_term_retention', 0):.2%}")
    print(f"  Structure:        {stats.get('avg_structural_similarity', 0):.2%}")
    print(f"  Detail level:     {stats.get('avg_detail_level', 0):.2%}")

    print(f"\nQuality distribution:")
    print(f"  High (≥90%):      {stats.get('high_quality_pct', 0):.1%}")
    print(f"  Good (70-90%):    {stats.get('good_quality_pct', 0):.1%}")
    print(f"  Low (<70%):       {stats.get('low_quality_pct', 0):.1%}")

    print(f"\nWarnings: {stats.get('total_warnings', 0)} total, "
          f"{stats.get('avg_warnings_per_compression', 0):.1f} avg/compression")


def cmd_profile_stats(args):
    """Show per-project profile statistics"""
    manager = get_profile_manager()

    if args.project_id:
        # Show specific project
        stats = manager.get_project_stats(args.project_id)
        print(f"\n=== Project Profile: {args.project_id} ===")
        print(f"Preferred mode: {stats.get('preferred_mode', 'None')}")
        print(f"Auto-detected:  {stats.get('auto_detected', False)}")

        modes = stats.get('modes', {})
        if modes:
            print("\nMode usage:")
            for mode, mode_stats in modes.items():
                print(f"\n  {mode}:")
                print(f"    Usage:          {mode_stats['usage_count']} times")
                print(f"    Avg savings:    {mode_stats['avg_savings_ratio']}")
                print(f"    Avg quality:    {mode_stats['avg_quality_score']}")
                print(f"    Tokens saved:   {mode_stats['total_tokens_saved']}")
                print(f"    Last used:      {mode_stats['last_used']}")
        else:
            print("\nNo compression history yet")

    else:
        # List all projects
        projects = manager.get_all_projects()

        print(f"\n=== All Project Profiles ({len(projects)} total) ===")

        for project_id in projects[:10]:  # Show first 10
            stats = manager.get_project_stats(project_id)
            preferred = stats.get('preferred_mode', 'None')
            auto = "(auto)" if stats.get('auto_detected') else ""
            print(f"  {project_id}: {preferred} {auto}")

        if len(projects) > 10:
            print(f"\n  ... and {len(projects) - 10} more")


def cmd_cache_stats(args):
    """Show cache awareness statistics"""
    if not args.project_id:
        print("Error: --project-id required")
        return

    coordinator = get_cache_coordinator()
    metrics = coordinator.get_cache_metrics(args.project_id)

    print(f"\n=== Cache Awareness: {args.project_id} ===")
    print(f"Current mode:      {metrics.get('current_mode', 'None')}")
    print(f"Cache warm:        {metrics.get('cache_is_warm', False)}")

    if metrics.get('cache_age_seconds') is not None:
        print(f"Cache age:         {metrics['cache_age_seconds']:.0f}s")

    print(f"Cache TTL:         {metrics.get('cache_ttl', 0)}s")

    if metrics.get('time_until_cold') is not None:
        print(f"Time until cold:   {metrics['time_until_cold']:.0f}s")

    if 'candidate_mode' in metrics:
        print(f"\nCandidate mode:    {metrics['candidate_mode']}")
        print(f"Candidate since:   {metrics['candidate_duration']:.0f}s")


def cmd_profile_set(args):
    """Set preferred compression mode for a project"""
    manager = get_profile_manager()

    mode = EfficientMode.parse_config(args.mode)
    manager.set_preferred_mode(args.project_id, mode, auto_detected=False)

    print(f"✓ Set preferred mode for {args.project_id}: {mode.value}")


def cmd_profile_detect(args):
    """Auto-detect best compression mode for a project"""
    manager = get_profile_manager()

    detected_mode = manager.auto_detect_mode(args.project_id)

    if detected_mode:
        print(f"✓ Auto-detected best mode for {args.project_id}: {detected_mode.value}")

        if args.apply:
            manager.set_preferred_mode(args.project_id, detected_mode, auto_detected=True)
            print(f"  Applied as preferred mode")
    else:
        print(f"⚠ Insufficient data to auto-detect mode for {args.project_id}")
        print(f"  Need at least 5 compressions per mode")


def cmd_config_show(args):
    """Show current advanced configuration"""
    config = get_config()

    print("\n=== Advanced Compression Configuration ===")

    print("\nAdaptive Eco Mode:")
    adaptive = config.get_adaptive_eco_config()
    print(f"  Enabled:         {adaptive.get('enabled', False)}")
    print(f"  Min confidence:  {adaptive.get('min_confidence', 0.7):.0%}")
    print(f"  Hysteresis:      {adaptive.get('hysteresis_count', 2)} decisions")

    print("\nSemantic Scoring:")
    scoring = config.get_semantic_scoring_config()
    print(f"  Enabled:         {scoring.get('enabled', False)}")
    print(f"  Min overall:     {scoring.get('min_overall_score', 0.7):.0%}")
    print(f"  Min key terms:   {scoring.get('min_key_term_retention', 0.8):.0%}")

    print("\nProject Profiles:")
    profiles = config.get_project_profiles_config()
    print(f"  Enabled:         {profiles.get('enabled', False)}")
    print(f"  Auto-detect:     {profiles.get('auto_detect_mode', False)}")

    print("\nCache Awareness:")
    cache = config.get_cache_awareness_config()
    print(f"  Enabled:         {cache.get('enabled', False)}")
    print(f"  Cache TTL:       {cache.get('cache_ttl', 0)}s")
    print(f"  Hysteresis:      {cache.get('hysteresis_duration', 0)}s")

    print("\nOutput Compression:")
    output = config.get_output_compression_config()
    print(f"  Enabled:         {output.get('enabled', False)}")
    print(f"  Mode:            {output.get('mode', 'balanced')}")
    print(f"  Min tokens:      {output.get('min_length_tokens', 0)}")
    print(f"  Show badge:      {output.get('show_badge', False)}")


def main():
    parser = argparse.ArgumentParser(
        description="AINL Graph Memory - Advanced Compression CLI"
    )

    subparsers = parser.add_subparsers(dest='command', help='Commands')

    # Pipeline test
    test_parser = subparsers.add_parser('test', help='Test compression pipeline')
    test_parser.add_argument('--file', '-f', help='Input file')
    test_parser.add_argument('--text', '-t', help='Input text')
    test_parser.add_argument('--project-id', '-p', help='Project ID')
    test_parser.add_argument('--show-output', '-s', action='store_true', help='Show compressed output')
    test_parser.set_defaults(func=cmd_pipeline_test)

    # Adaptive stats
    adaptive_parser = subparsers.add_parser('adaptive', help='Show adaptive eco stats')
    adaptive_parser.set_defaults(func=cmd_adaptive_stats)

    # Quality stats
    quality_parser = subparsers.add_parser('quality', help='Show quality stats')
    quality_parser.set_defaults(func=cmd_quality_stats)

    # Profile stats
    profile_parser = subparsers.add_parser('profile', help='Show project profile stats')
    profile_parser.add_argument('--project-id', '-p', help='Specific project ID')
    profile_parser.set_defaults(func=cmd_profile_stats)

    # Cache stats
    cache_parser = subparsers.add_parser('cache', help='Show cache awareness stats')
    cache_parser.add_argument('--project-id', '-p', required=True, help='Project ID')
    cache_parser.set_defaults(func=cmd_cache_stats)

    # Profile set
    set_parser = subparsers.add_parser('set-mode', help='Set preferred mode for project')
    set_parser.add_argument('--project-id', '-p', required=True, help='Project ID')
    set_parser.add_argument('--mode', '-m', required=True,
                           choices=['off', 'balanced', 'aggressive'],
                           help='Compression mode')
    set_parser.set_defaults(func=cmd_profile_set)

    # Profile detect
    detect_parser = subparsers.add_parser('auto-detect', help='Auto-detect best mode')
    detect_parser.add_argument('--project-id', '-p', required=True, help='Project ID')
    detect_parser.add_argument('--apply', '-a', action='store_true',
                              help='Apply detected mode as preferred')
    detect_parser.set_defaults(func=cmd_profile_detect)

    # Config show
    config_parser = subparsers.add_parser('config', help='Show advanced configuration')
    config_parser.set_defaults(func=cmd_config_show)

    args = parser.parse_args()

    if hasattr(args, 'func'):
        args.func(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
