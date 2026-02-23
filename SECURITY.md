# Security Policy

## Supported Versions

| Version | Supported          |
|---------|--------------------|
| 0.1.x   | Yes                |

## Reporting a Vulnerability

If you discover a security issue in the CUP specification, please report it responsibly.

**Do not open a public issue.**

Instead, email **cup@computeruseprotocol.com** with:

- A description of the vulnerability
- The potential impact
- Any suggested fixes (optional)

We will acknowledge receipt within 48 hours and aim to provide an initial assessment within 7 days.

## Security Considerations for Implementers

The CUP specification defines how AI agents perceive and interact with UI elements. SDK implementers should consider:

- **Action execution scope** — CUP actions can interact with any accessible UI element. Implementations should provide mechanisms for consumers to constrain which actions are permitted.
- **Element references** — Element IDs are ephemeral and scoped to a single tree capture. Implementations must not allow IDs to be reused across captures.
- **Sensitive content** — Accessibility trees may contain sensitive on-screen content (passwords in cleartext, personal data, etc.). Implementations should document this risk for consumers who transmit trees to external services.
- **No credential storage** — CUP does not define any credential or authentication mechanisms. API keys for LLM providers belong in the application layer.
