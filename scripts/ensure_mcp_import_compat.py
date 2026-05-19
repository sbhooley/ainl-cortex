#!/usr/bin/env python3
"""Backward-compatible entry: delegates to ensure_runtime_preflight.py."""
from __future__ import annotations

import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).resolve().parent / "ensure_runtime_preflight.py"))
