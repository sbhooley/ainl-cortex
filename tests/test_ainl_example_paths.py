from pathlib import Path

from mcp_server.ainl_example_paths import resolve_example_path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent


def test_resolve_bundled_example():
    p = resolve_example_path("examples/compact/hello_compact.ainl", PLUGIN_ROOT)
    assert p is not None
    assert "hello_compact.ainl" in str(p)
