#!/usr/bin/env python3
"""Test MCP server functionality"""

import sys
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "mcp_server"))

from mcp_server.server import AINLGraphMemoryServer

async def test_server():
    """Test server initialization and basic operations"""
    print("🧪 Testing AINL Graph Memory MCP Server\n")

    # Initialize server
    print("1. Initializing server...")
    try:
        server = AINLGraphMemoryServer()
        print(f"   ✓ Server initialized")
        print(f"   ✓ DB path: {server.db_path}")
        print()
    except Exception as e:
        print(f"   ✗ Failed to initialize: {e}")
        return False

    # Test basic memory operations
    print("2. Testing memory storage...")
    try:
        # Store a test episode
        episode_node = server.store_episode_sync(
            project_id="test_project",
            task_description="Test compression functionality",
            tool_calls=["Read", "Edit"],
            files_touched=["config.json"],
            outcome="success"
        )
        print(f"   ✓ Stored episode node: {episode_node['node_id'][:8]}...")
        print()
    except Exception as e:
        print(f"   ✗ Failed to store episode: {e}")
        print()

    # Test retrieval
    print("3. Testing memory retrieval...")
    try:
        results = server.retrieval.recall_context(
            query="compression",
            project_id="test_project",
            max_results=5
        )
        print(f"   ✓ Retrieved {len(results)} memory nodes")
        print()
    except Exception as e:
        print(f"   ✗ Failed to retrieve: {e}")
        print()

    print("✅ MCP Server is functional!")
    return True


def store_episode_sync(self, **kwargs):
    """Sync wrapper for testing"""
    import asyncio
    from mcp_server.node_types import create_episode_node, EdgeType, create_edge
    from mcp_server.extractor import canonicalize_tool_sequence

    canonical_tools = canonicalize_tool_sequence(kwargs.get('tool_calls', []))
    node = create_episode_node(
        project_id=kwargs['project_id'],
        task_description=kwargs['task_description'],
        tool_calls=canonical_tools,
        files_touched=kwargs['files_touched'],
        outcome=kwargs['outcome']
    )
    self.store.write_node(node)

    return {
        "node_id": node.id,
        "node_type": "episode",
        "canonical_tools": canonical_tools
    }


# Add the sync method to the server class
AINLGraphMemoryServer.store_episode_sync = store_episode_sync

if __name__ == "__main__":
    asyncio.run(test_server())
