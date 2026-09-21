# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.1] - 2026-09-21

### Added

- Documentation for connecting the server in **Claude Code**, **Codex** and
  **phoson-cli**, with copy-pasteable configuration for each. Codex is documented
  in TOML, since it has no JSON form for MCP servers.
- A table explaining how to enable the optional `yjs` extra per client, which is
  what unlocks `update_page_content`.
- A PyPI badge and `uvx` as the primary install route in the README.

### Fixed

- `__version__` was hardcoded in `__init__.py` alongside the `version` field in
  `pyproject.toml`, so it kept reporting `0.1.0` after a version bump. It is now
  read from the installed distribution metadata, leaving `pyproject.toml` as the
  single source of truth.
- Remaining placeholder values in the documentation that were still in Spanish.

## [0.1.0] - 2026-09-21

### Added

- Initial release.
- 20 MCP tools covering pages, spaces, comments and workspace members.
- Async REST client for Docmost's internal API, tolerant of the differences
  between builds: cookie vs. token login, `{items, meta}` vs. raw lists, and a
  required `spaceId` in `/search`.
- `create_page`, which routes through `/pages/import` because `/pages/create`
  and `/pages/update` silently ignore the `content` field.
- `update_page_content`, which replaces the body of an existing page over the
  Yjs collaboration WebSocket (Hocuspocus) — something the REST API cannot do.
- `docs/DOCMOST-API.md`: API research, including how a real instance differs
  from the OSS source, and the methodology used to discover it.
- `docs/YJS-EDITING.md`: the reverse-engineered collaboration protocol.
- MIT license, `CONTRIBUTING.md`, and a CI workflow covering lint, offline tests
  on Python 3.10/3.12/3.13, and packaging.

[Unreleased]: https://github.com/abelsr/docmost-mcp-oss/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/abelsr/docmost-mcp-oss/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/abelsr/docmost-mcp-oss/releases/tag/v0.1.0
