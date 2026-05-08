#!/usr/bin/env python3
"""Test hook execution"""

import sys
import json
import subprocess
from pathlib import Path

def test_hook(hook_name, test_data):
    """Test a specific hook"""
    hook_path = Path(__file__).parent / "hooks" / f"{hook_name}.py"

    if not hook_path.exists():
        return False, f"Hook file not found: {hook_path}"

    try:
        # Run the hook with test data
        result = subprocess.run(
            [".venv/bin/python", str(hook_path)],
            input=json.dumps(test_data),
            capture_output=True,
            text=True,
            timeout=5,
            cwd=Path(__file__).parent
        )

        if result.returncode == 0:
            return True, "Hook executed successfully"
        else:
            return False, f"Hook failed: {result.stderr}"

    except subprocess.TimeoutExpired:
        return False, "Hook timed out"
    except Exception as e:
        return False, f"Error: {e}"


def main():
    print("🧪 Testing AINL Hook Execution\n")

    hooks_to_test = [
        ("pre_compact", {
            "messages": [
                {"role": "user", "content": "Test message 1"},
                {"role": "assistant", "content": "Test response 1"}
            ]
        }),
        ("post_compact", {
            "messagesBefore": 10,
            "messagesAfter": 5
        }),
        ("post_tool_use", {
            "tool": "Read",
            "success": True
        })
    ]

    results = []
    for hook_name, test_data in hooks_to_test:
        print(f"Testing {hook_name}...")
        success, message = test_hook(hook_name, test_data)

        if success:
            print(f"  ✓ {message}")
        else:
            print(f"  ✗ {message}")

        results.append((hook_name, success))
        print()

    # Summary
    print("=" * 50)
    passed = sum(1 for _, success in results if success)
    total = len(results)

    if passed == total:
        print(f"✅ ALL {total} HOOKS PASSED!")
    else:
        print(f"⚠️  {passed}/{total} hooks passed")

    print("=" * 50)


if __name__ == "__main__":
    main()
