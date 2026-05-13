# Security

## Reporting a vulnerability

If you believe you have found a **security issue** in AINL Cortex (including the MCP server, hook system, A2A bridge, notification poller, or native Rust extension), please report it **privately** so we can address it before public disclosure.

**Preferred:** Open a **[private security advisory](https://github.com/sbhooley/ainl-cortex/security/advisories/new)** (repository **Security** tab → **Report a vulnerability**). This allows coordinated disclosure, a private thread with maintainers, and an optional CVE or GitHub advisory once fixed. You need a GitHub account; the form accepts description, impact, and reproduction details.

**Alternative:** Email `hello@ainativelang.com` with subject line `[SECURITY] ainl-cortex` if you prefer not to use GitHub.

**Include (when possible):**

- A short description of the issue and its impact
- Steps to reproduce or a proof-of-concept
- Affected version or commit, if known

**Please do not** file public issues for **undisclosed** security bugs until a fix and coordinated disclosure window have been agreed upon.

## Security-sensitive areas

- **Hook execution** — Hooks run at every session start, prompt submit, and tool call. A hook that performs unsafe file reads, shell calls, or network requests without validation could be exploited by a malicious project environment. Hooks must validate inputs and avoid executing user-controlled strings as shell commands.
- **MCP server** — The MCP server handles tool calls from Claude Code. Ensure that tool inputs are validated before being passed to SQLite queries, file paths, or subprocess calls to prevent injection.
- **A2A bridge and outbound HTTP** — The A2A bridge and notification poller make outbound network requests. Use allowlists, validate redirect targets, and avoid logging bearer tokens or sensitive frame values.
- **Native Rust extension (`ainl_native`)** — The PyO3 extension wraps armaraos crates. Memory safety issues in the Rust layer or unsafe FFI boundary crossings should be reported as security issues.
- **Notification auto-update** — When `auto_update` is enabled, the plugin runs `git pull --ff-only` based on a server-controlled payload. Treat the notification feed URL as a trust boundary; only enable auto-update in controlled environments.
- **Secrets** — Do not commit API keys, tokens, or private keys. Prefer environment variables and your platform's secret stores. The plugin reads `config.json` and `secrets.env` — ensure these files have appropriate file permissions.

## Supported versions

Security fixes are applied to the current `main` branch. Run a current release and follow the changelog when upgrading.
