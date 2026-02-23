# Contributing to the Computer Use Protocol

Thanks for your interest in CUP! This repository contains the **protocol specification** — the schema, role mappings, compact format spec, and documentation.

> For SDK contributions (bug fixes, new platform adapters, tests, etc.), see the language-specific repos:
> - [Python SDK](https://github.com/computeruseprotocol/python-sdk)

## Specification contributions

High-impact areas where contributions are especially useful:

- **Role proposals** — propose new ARIA-derived roles with mappings across at least 2 platforms
- **Action proposals** — propose new canonical actions with cross-platform semantics
- **Platform mappings** — add or improve entries in [schema/mappings.json](schema/mappings.json)
- **Schema improvements** — tighten validation, add documentation, fix edge cases
- **Compact format** — propose changes to the text serialization format
- **Examples** — add or improve example envelopes in [schema/example.json](schema/example.json)

## How to contribute

1. Open an issue describing the proposed change
2. For schema changes, include:
   - Rationale for the change
   - Mapping examples for at least 2 platforms (e.g., Windows UIA + Web ARIA)
   - Impact on existing consumers
3. Submit a PR against `main`

## Pull request guidelines

- Keep PRs focused. One change per PR.
- Validate that `schema/cup.schema.json` remains valid JSON Schema.
- Update documentation if you change the schema or format spec.
- Ensure the example envelope in `schema/example.json` validates against the schema.

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).
