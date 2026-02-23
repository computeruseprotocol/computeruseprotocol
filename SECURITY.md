# Security Policy

## Supported Versions

| Version | Supported          |
|---------|--------------------|
| 0.1.x   | Yes                |

## Reporting a Vulnerability

If you discover a security vulnerability in CUP, please report it responsibly.

**Do not open a public issue.**

Instead, email **cup@computeruseprotocol.com** with:

- A description of the vulnerability
- Steps to reproduce the issue
- The potential impact
- Any suggested fixes (optional)

We will acknowledge receipt within 48 hours and aim to provide an initial assessment within 7 days.

## Security Considerations

CUP interacts with OS accessibility APIs and can execute UI actions on behalf of AI agents. Developers integrating CUP should be aware of:

- **Action execution scope** — CUP can click, type, and interact with any accessible UI element. Always validate and constrain which actions an agent is allowed to perform.
- **Element references** — Element IDs are ephemeral and scoped to a single tree capture. They cannot be reused across sessions.
- **MCP server** — The `cup-mcp` server runs locally over stdio. It does not expose a network interface by default.
- **No credential storage** — CUP does not store, transmit, or handle credentials. API keys for LLM providers belong in your application layer, not in CUP.

## Best Practices for Integrators

- Run CUP with the minimum OS permissions needed for your use case
- Implement action allowlists in your agent layer — don't give agents unrestricted access to all CUP actions
- Review tree captures before sending them to external LLM APIs, as accessibility trees may contain sensitive on-screen content
- Keep CUP updated to receive security fixes
