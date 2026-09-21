# Contributing

Thanks for your interest in improving `docmost-mcp-oss`. This project is small, so
the process is intentionally light.

## Setup

The project is managed with [uv](https://docs.astral.sh/uv/):

```bash
git clone https://github.com/abelsr/docmost-mcp-oss
cd docmost-mcp-oss
uv sync --extra yjs      # --extra yjs is needed for the collaboration module
```

There is no need to activate the environment: prefix commands with `uv run`.

## Checks

These are the same checks CI runs, and they need **no credentials**:

```bash
uv run ruff check .            # lint
uv run ruff format --check .   # formatting
uv run python tests/test_client.py   # client against a simulated Docmost
uv run python tests/test_tools.py    # MCP tool registry
```

`ruff format` also formats Python code blocks inside Markdown files, so run it
before committing if you touch the docs.

## Live tests

Three suites hit a **real** Docmost instance and are therefore not run in CI.
They read credentials from a `.docmost-creds.json` file in the repo root, which
is git-ignored:

```json
{
  "url": "https://docmost.example.com",
  "email": "you@example.com",
  "password": "your-password"
}
```

```bash
uv run python tests/smoke_live.py                # read-only
uv run python tests/smoke_live.py --write        # create/rename/delete
uv run python tests/smoke_mcp_live.py --write     # through the MCP layer
uv run --extra yjs python tests/smoke_yjs_live.py # body editing over Yjs
```

Use an API key (`"api_key": "..."`) instead of a password if your account has
MFA enabled. Prefer a throwaway account or a test space: `--write` creates and
deletes pages.

## Guidance

- **Nothing about this API is documented upstream.** Everything in
  [`docs/DOCMOST-API.md`](docs/DOCMOST-API.md) and
  [`docs/YJS-EDITING.md`](docs/YJS-EDITING.md) was derived from source code and
  from probing real instances. If you change a behaviour, say *how you verified
  it* — observed facts, not assumptions.
- **Several behaviours differ between Docmost builds.** The client normalizes
  them (raw lists vs `{items, meta}`, cookie vs token login, optional vs required
  `spaceId`). Keep those normalizations tolerant rather than assuming one build.
- **Tool docstrings are the LLM's interface.** They must stay accurate about
  limitations (for example, that `/pages/update` only changes titles).
- **Typed signatures matter.** FastMCP only fills a tool's structured output
  (`.data`) when the return type is annotated, hence `-> list[dict]` / `-> dict`.
  `tests/test_tools.py` guards against a regression here.

## Adding a tool

1. Add the method to `docmost_mcp_oss/client.py` (or `collab.py`).
2. Register it in `docmost_mcp_oss/server.py` with `@mcp.tool`, a **typed**
   signature, and a docstring with an `Args:` section.
3. Add it to `EXPECTED_TOOLS` in `tests/test_tools.py`.

## Commits

Short imperative subject lines, English, in the style of
`Add page history tool` or `Fix spaceId requirement in search`. Explain the
*why* in the body when the change is not obvious.

Keep [CHANGELOG.md](https://github.com/abelsr/docmost-mcp-oss/blob/main/CHANGELOG.md)
up to date under `## [Unreleased]` as you go, not at release time. It follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/): group entries under
`Added`, `Changed`, `Fixed`, `Removed`.

## Releasing

Releases are driven by tags, and the workflow refuses to publish if anything is
inconsistent — so the steps are mechanical:

1. Move the `## [Unreleased]` entries in `CHANGELOG.md` into a new
   `## [X.Y.Z] - YYYY-MM-DD` section, and update the comparison links at the
   bottom of the file.
2. Set the same `X.Y.Z` in the `version` field of `pyproject.toml`.
3. Run `uv sync` (this updates `uv.lock`) and commit both files.
4. Tag and push:

   ```bash
   git tag vX.Y.Z
   git push origin main vX.Y.Z
   ```

The [release workflow](.github/workflows/release.yml) then:

- verifies the tag matches `version` in `pyproject.toml`,
- verifies `CHANGELOG.md` has a `## [X.Y.Z]` section,
- builds the sdist and wheel,
- publishes to PyPI through Trusted Publishing (no API token),
- creates a GitHub Release using that changelog section as its notes.

There is no `workflow_dispatch` on purpose: a release is always a tag. To retry a
failed run, use *Re-run jobs* on the run itself.

## License

By contributing you agree that your contributions are licensed under the
[MIT License](https://github.com/abelsr/docmost-mcp-oss/blob/main/LICENSE).
