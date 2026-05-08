#!/usr/bin/env python3
"""
Verify MCP server exposes all tools correctly
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from mcp_server.server import server, memory_server


async def verify_tools():
    """Verify all tools are registered"""
    print("🔍 Verifying AINL Graph Memory MCP Server Tools\n")
    print("=" * 60)

    # Import the list_tools function
    from mcp_server.server import list_tools

    # Get tool list
    tools = await list_tools()

    print(f"\n✅ Total tools registered: {len(tools)}\n")

    # Group tools
    memory_tools = []
    ainl_tools = []

    for tool in tools:
        print(f"  • {tool.name}")
        if tool.name.startswith("memory_"):
            memory_tools.append(tool.name)
        elif tool.name.startswith("ainl_"):
            ainl_tools.append(tool.name)

    print("\n" + "=" * 60)
    print(f"\n📊 Summary:")
    print(f"  Memory Tools: {len(memory_tools)}")
    print(f"  AINL Tools: {len(ainl_tools)}")

    # Check AINL tools availability
    print(f"\n🔧 AINL Tools Status:")
    if memory_server.ainl_tools:
        print("  ✅ AINL tools initialized successfully")
        print(f"  ✅ Database: {memory_server.db_path}")
    else:
        print("  ⚠️  AINL tools not available")
        print("  💡 Install: pip install ainativelang[mcp]")

    # Expected tools
    expected_memory = [
        "memory_store_episode",
        "memory_store_semantic",
        "memory_store_failure",
        "memory_promote_pattern",
        "memory_recall_context",
        "memory_search",
        "memory_evolve_persona"
    ]

    expected_ainl = [
        "ainl_validate",
        "ainl_compile",
        "ainl_run",
        "ainl_capabilities",
        "ainl_security_report",
        "ainl_ir_diff"
    ]

    print(f"\n✅ Verification:")

    # Check memory tools
    missing_memory = set(expected_memory) - set(memory_tools)
    if missing_memory:
        print(f"  ⚠️  Missing memory tools: {missing_memory}")
    else:
        print(f"  ✅ All {len(expected_memory)} memory tools present")

    # Check AINL tools
    missing_ainl = set(expected_ainl) - set(ainl_tools)
    if missing_ainl:
        print(f"  ⚠️  Missing AINL tools: {missing_ainl}")
    else:
        print(f"  ✅ All {len(expected_ainl)} AINL tools present")

    print("\n" + "=" * 60)

    if not missing_memory and not missing_ainl:
        print("\n🎉 SUCCESS: All tools properly registered!")
        print("\n💡 Next steps:")
        print("  1. Restart Claude Code to load the updated MCP server")
        print("  2. The tools will be available automatically")
        return 0
    else:
        print("\n❌ FAILED: Some tools are missing")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(verify_tools())
    sys.exit(exit_code)
