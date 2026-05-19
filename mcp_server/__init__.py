"""
AINL Graph Memory MCP Server

Production-grade graph-native memory system inspired by AINL unified graph execution engine.
"""

__version__ = "0.1.0"

from .runtime_bootstrap import bootstrap_runtime

bootstrap_runtime(quick=True)
