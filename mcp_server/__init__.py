"""
AINL Graph Memory MCP Server

Production-grade graph-native memory system inspired by AINL unified graph execution engine.
"""

__version__ = "0.1.0"


def _register_bare_node_types_alias() -> None:
    """
    Register ``node_types`` in sys.modules for package-mode MCP (``python -m mcp_server.server``).

    Claude Code loads the server as a package. Top-level code uses ``from .node_types import …``,
    but many tool bodies still use bare ``from node_types import …``. Without this alias, those
    imports fail at call time with ``No module named node_types`` even though the server started.
    """
    import sys

    if "node_types" in sys.modules:
        return
    try:
        from . import node_types as _node_types
    except ImportError:
        return
    sys.modules["node_types"] = _node_types


_register_bare_node_types_alias()
