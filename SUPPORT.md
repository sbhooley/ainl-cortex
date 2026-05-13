# Support

AINL Cortex is maintained by AINativeLang, Inc. on a best-effort basis for the open-source community.

## Where to ask for help

| Channel | Use for |
|---------|---------|
| **[GitHub Issues](https://github.com/sbhooley/ainl-cortex/issues)** | Bug reports, reproducible defects |
| **[GitHub Discussions](https://github.com/sbhooley/ainl-cortex/discussions)** | Usage questions, feature ideas, general discussion |
| **`hello@ainativelang.com`** | Security issues (after following `SECURITY.md`), commercial inquiries |

## What maintainers can usually help with

- Reproducible defects in the MCP server, hook system, or memory backend
- Installation and activation issues after following the README
- Clarifying documented behavior or configuration options
- Documentation gaps affecting contributor onboarding

## What may not receive immediate support

- Custom deployment architecture consulting
- Priority feature delivery timelines
- Environment-specific debugging without a minimal reproduction
- Third-party integrations not covered by maintained adapters or tooling

## Before opening an issue

1. Check that you are on the current `main` branch (`git pull` inside `~/.claude/plugins/ainl-cortex`)
2. Re-run `bash setup.sh` to rule out a stale install
3. Check the Troubleshooting table in the README
4. Search existing issues for the same symptom

A useful bug report includes:

- OS and Python version
- Claude Code version (`claude --version`)
- The exact error message or unexpected behavior
- Steps to reproduce
- Relevant lines from `~/.armaraos/logs/` or `hooks/shared/logger.py` output if available

## Security issues

Follow [`SECURITY.md`](SECURITY.md) — use the private reporting path first. Do not post security vulnerabilities as public issues.
