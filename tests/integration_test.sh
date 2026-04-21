#!/bin/bash
# Integration test for advanced compression features

set -e

echo "=== AINL Graph Memory Advanced Compression Integration Test ==="
echo ""

cd "$(dirname "$0")/.."

# Test 1: Show config
echo "Test 1: Show advanced configuration"
python3 cli/compression_advanced_cli.py config
echo "✓ Config display works"
echo ""

# Test 2: Pipeline test with sample text
echo "Test 2: Test compression pipeline"
echo "This is a test message with error handling and API endpoint references. The database query failed with an exception during execution." | \
  python3 cli/compression_advanced_cli.py test -p test_integration --show-output
echo "✓ Pipeline test works"
echo ""

# Test 3: Set preferred mode
echo "Test 3: Set preferred compression mode"
python3 cli/compression_advanced_cli.py set-mode -p test_integration -m balanced
echo "✓ Set mode works"
echo ""

# Test 4: Show project profile
echo "Test 4: Show project profile stats"
python3 cli/compression_advanced_cli.py profile -p test_integration
echo "✓ Profile display works"
echo ""

# Test 5: Cache stats
echo "Test 5: Show cache awareness stats"
python3 cli/compression_advanced_cli.py cache -p test_integration
echo "✓ Cache stats works"
echo ""

# Test 6: Run pytest if available
if command -v pytest &> /dev/null; then
    echo "Test 6: Run unit tests"
    pytest tests/test_compression_pipeline.py -v
    echo "✓ Unit tests pass"
else
    echo "Test 6: Skipped (pytest not installed)"
fi

echo ""
echo "=== All Integration Tests Passed! ==="
