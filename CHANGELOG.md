# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.5.0] - 2026-09-21

### Added

- **`move_page` no longer asks for a position.** Docmost orders pages by a
  base62 string that must be 5-12 characters and is compared lexicographically,
  which is unreasonable to hand to a caller. The tool now takes a destination:
  `parent_page_id` to nest, `after`/`before` to sit next to a sibling, or
  nothing to append at the end. The position is read from the neighbours and
  generated in between.
- `docmost_mcp_oss/position.py`, a fractional-indexing generator that works
  inside Docmost's length constraint, with property tests in
  `tests/test_positions.py` covering 3000 intervals between positions a real
  instance produced.

### Fixed

- `move_page` treated a page as its own sibling when the caller passed a
  `slugId`, because the sibling list returns UUIDs. It now matches either, so
  "move this page before itself" is reported instead of silently narrowing the
  gap until no position fits.

## [0.4.0] - 2026-09-21

### Added

- `get_workspace_overview` returns a **`summary`**: counts per space, tree shape
  (roots, containers, leaves, max depth), date range and recency buckets
  (last 7/30 days), pages never edited after creation, top editors and any
  orphaned pages (those whose parent is not part of the tree). Every figure comes
  from data already gathered, so it costs no extra requests, and
  `summary.date_coverage` states how much of the workspace the dates cover.
- `check_empty` (opt-in): downloads each page to measure its body and flag the
  empty ones. Nothing cheaper exposes page size, so it costs one request per
  page; `summary.empty_pages` reports the result.

## [0.3.0] - 2026-09-21

### Added

- `get_workspace_overview` now reports **activity**, so an agent can decide what
  is worth reading first instead of walking the inventory blindly. Each page
  gains `updated_at` and `updated_by` (resolved to a member name), and the
  result carries `recently_updated`, newest first.
- A new `activity` argument controls the cost: `"recent"` (default) reads the
  recent-pages window in one extra request, `"full"` additionally fetches each
  page so every one is dated, and `"none"` skips activity entirely.

### Fixed

- **Page sizes above 100 were rejected by the server.** `limit` is now clamped
  to 1..100 in the client, which fixes `list_recent_pages(limit=500)` and any
  other call passing a larger value — Docmost answers
  `limit must not be greater than 100`. The overview tool hit this on its first
  run.

## [0.2.0] - 2026-09-21

### Added

- **`get_workspace_overview`**: lists every space and every page in one call,
  walking the whole page tree. Answers "what is in my Docmost?" without having to
  guess a page id first.
- `DocmostClient.list_all_pages()`, which enumerates a space depth-first,
  carrying `parent_page_id` and `depth` on each entry. Cycles are guarded
  against.

### Fixed

- **`create_page` silently dropped `parent_page_id` when `content` was given.**
  Pages created with both always landed at the root, because `/pages/import`
  accepts but ignores a `parentPageId` field. Nesting is now applied afterwards
  through `/pages/move`, which is the endpoint that actually sets the parent,
  and the page keeps the position it was created with.
- `list_child_pages` with no arguments returned only the root pages of every
  space while reading as if it returned the whole tree. It now requires
  `space_id` or `page_id` and points the caller at `get_workspace_overview`.
  The underlying reason is that `/pages/sidebar-pages` returns one level, never
  the full tree.

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

[Unreleased]: https://github.com/abelsr/docmost-mcp-oss/compare/v0.5.0...HEAD
[0.5.0]: https://github.com/abelsr/docmost-mcp-oss/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/abelsr/docmost-mcp-oss/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/abelsr/docmost-mcp-oss/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/abelsr/docmost-mcp-oss/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/abelsr/docmost-mcp-oss/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/abelsr/docmost-mcp-oss/releases/tag/v0.1.0
