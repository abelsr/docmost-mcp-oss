# docmost-mcp-oss

[![CI](https://github.com/abelsr/docmost-mcp-oss/actions/workflows/ci.yml/badge.svg)](https://github.com/abelsr/docmost-mcp-oss/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/docmost-mcp-oss.svg)](https://pypi.org/project/docmost-mcp-oss/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://github.com/abelsr/docmost-mcp-oss/blob/main/LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)

An [MCP](https://modelcontextprotocol.io) server built with **FastMCP** that exposes the REST API of [Docmost](https://docmost.com) as tools for AI assistants (Claude Desktop, Claude Code, Cursor, VS Code…).

Managed with **[uv](https://docs.astral.sh/uv/)**.

> 📄 Full API research: [`docs/DOCMOST-API.md`](https://github.com/abelsr/docmost-mcp-oss/blob/main/docs/DOCMOST-API.md).
> Verified against a real Docmost instance (not just the documentation).

## Why a custom MCP?

Docmost ships with an **official** MCP, but it requires a *Business/Enterprise* license and is enabled from *Settings → AI settings → MCP*. This project uses the **internal API** (the same one the web UI consumes), which is also available in the **self-hosted OSS** edition.

**About the name:** the `-oss` suffix distinguishes this package from the unrelated
[`docmost-mcp`](https://pypi.org/project/docmost-mcp/) already on PyPI. They are different
projects by different authors, and they would collide if installed side by side (both used to
ship the same import package). This one targets self-hosted Docmost and can edit page bodies;
install it as `docmost-mcp-oss`.

## Exposed tools (21)

| Category | Tools                                                                                                                                                                                                                                              |
| -------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Pages    | **`get_workspace_overview`**, `search_pages`, `get_page`, `create_page`, `update_page`, **`update_page_content`**, `delete_page`, `restore_page`, `move_page`, `list_recent_pages`, `list_child_pages`, `get_page_breadcrumbs`, `get_page_history` |
| Spaces   | `list_spaces`, `get_space`, `create_space`                                                                                                                                                                                                   |
| Comments | `get_comments`, `create_comment`, `update_comment`                                                                                                                                                                                           |
| User     | `get_current_user`, `list_workspace_members`                                                                                                                                                                                                   |

Three tools stand out:

- **`get_workspace_overview`** answers *"what is in my Docmost?"* in a single call:
  every space and every page, walking the whole tree, plus who last touched each
  page and a `recently_updated` ranking so an agent knows what to read first.
  The `activity` argument trades cost for detail (`"recent"`, `"full"`, `"none"`).
- **`get_page`** returns **metadata and content** in Markdown (it combines `/pages/info` with `/pages/export`, because the former **does not** return the body).
- **`update_page_content`** **replaces the body of an existing page**. The REST API can't do this: it writes directly to the Yjs document over the collaboration WebSocket. Requires the `yjs` extra and takes ~13 s (Docmost persists with a 10 s *debounce*).

> `list_child_pages` lists **one level only** (the direct children of a space or a
> page). Enumerating a space means walking its tree, which is what
> `get_workspace_overview` does for you.

## Editing the body of an existing page

Docmost's REST API **ignores the `content` field** in `/pages/create` and `/pages/update` (they respond 200 but save nothing): the body lives in the **Yjs** collaboration server.

That's why there are two distinct paths:

| Operation                                      | How                                               |
| ---------------------------------------------- | ------------------------------------------------- |
| Read content                                   | `get_page`                                      |
| Create page**with** content              | `create_page` (uses `/pages/import`)          |
| **Replace the body of an existing page** | **`update_page_content`** (Yjs WebSocket) |
| Rename                                         | `update_page`                                   |
| Delete / restore / move                        | ✅                                                |

`update_page_content` opens the `wss://<host>/collab` WebSocket, syncs the document, replaces the content and waits for it to persist. Markdown is
converted using Docmost's own converter, so it supports the full schema (tables, lists, code, quotes, images…).

```bash
uv sync --extra yjs     # enables update_page_content
```

Technical details of the protocol: [`docs/YJS-EDITING.md`](https://github.com/abelsr/docmost-mcp-oss/blob/main/docs/YJS-EDITING.md).

## Installation

### As a tool, from PyPI (no clone needed)

```bash
uvx docmost-mcp-oss            # stdio, for MCP clients
uvx docmost-mcp-oss --check    # verify the connection to your instance
```

Add `--with pycrdt --with websockets` (or install `docmost-mcp-oss[yjs]`) to enable
`update_page_content`, the tool that edits existing page bodies.

### From source (for development)

`uv` creates the virtual environment and installs the dependencies (pinned in `uv.lock`):

```bash
uv sync
```

No need to activate the environment: use `uv run …`.

## Configuration

```bash
cp .env.example .env   # then edit the values
```

```dotenv
DOCMOST_URL=https://docmost.example.com

# Option A — API Key
DOCMOST_API_KEY=dm_xxx

# Option B — login (works on OSS)
DOCMOST_EMAIL=you@example.com
DOCMOST_PASSWORD=your-password
```

Verify the connection:

```bash
uv run docmost-mcp-oss --check
# -> OK: authenticated as you@example.com (https://docmost.example.com)
```

## Usage

### stdio (recommended for local use)

```bash
uv run docmost-mcp-oss
```

### HTTP (for remote access)

```bash
uv run docmost-mcp-oss --http --port 8000
# MCP endpoint: http://127.0.0.1:8000/mcp
```

## Connecting to MCP clients

Every client below launches the same stdio command. The examples install from
PyPI with `uvx`; to run from a clone instead, replace `uvx docmost-mcp-oss` with
`uv --directory /path/to/docmost-mcp-oss run docmost-mcp-oss`.

To enable `update_page_content` (editing existing page bodies), use the `yjs`
extra — replace `docmost-mcp-oss` with `--from "docmost-mcp-oss[yjs]"
docmost-mcp-oss`, or see the note at the end of this section.

### Claude Code

```bash
claude mcp add docmost \
  -e DOCMOST_URL=https://docmost.example.com \
  -e DOCMOST_EMAIL=you@example.com \
  -e DOCMOST_PASSWORD=your-password \
  -- uvx docmost-mcp-oss
```

Equivalent JSON, in `.mcp.json` at the root of your project (or under
`mcpServers` in `~/.claude.json` for a user-wide server):

```json
{
  "mcpServers": {
    "docmost": {
      "type": "stdio",
      "command": "uvx",
      "args": ["docmost-mcp-oss"],
      "env": {
        "DOCMOST_URL": "https://docmost.example.com",
        "DOCMOST_EMAIL": "you@example.com",
        "DOCMOST_PASSWORD": "your-password"
      }
    }
  }
}
```

### Codex

⚠️ Codex configures MCP servers in **TOML**, not JSON. Add this to
`~/.codex/config.toml`:

```toml
[mcp_servers.docmost]
command = "uvx"
args = ["docmost-mcp-oss"]

[mcp_servers.docmost.env]
DOCMOST_URL = "https://docmost.example.com"
DOCMOST_EMAIL = "you@example.com"
DOCMOST_PASSWORD = "your-password"
```

Or let the CLI write it for you:

```bash
codex mcp add docmost \
  --env DOCMOST_URL=https://docmost.example.com \
  --env DOCMOST_EMAIL=you@example.com \
  --env DOCMOST_PASSWORD=your-password \
  -- uvx docmost-mcp-oss
```

### phoson-cli

phoson reads JSON from the file named by `mcp_config_file` in
`~/.phoson/config.toml` (defaults to `~/.phoson/mcps.json`). Entries need an
explicit `"enabled": true`:

```json
{
  "mcpServers": {
    "docmost": {
      "command": "uvx",
      "args": ["docmost-mcp-oss"],
      "env": {
        "DOCMOST_URL": "https://docmost.example.com",
        "DOCMOST_EMAIL": "you@example.com",
        "DOCMOST_PASSWORD": "your-password"
      },
      "enabled": true
    }
  }
}
```

### Claude Desktop (`claude_desktop_config.json`)

```json
{
  "mcpServers": {
    "docmost": {
      "command": "uvx",
      "args": ["docmost-mcp-oss"],
      "env": {
        "DOCMOST_URL": "https://docmost.example.com",
        "DOCMOST_EMAIL": "you@example.com",
        "DOCMOST_PASSWORD": "your-password"
      }
    }
  }
}
```

### Cursor (`.cursor/mcp.json`)

Same shape as Claude Desktop, inside the `mcpServers` key.

### Enabling body editing

`update_page_content` needs the `yjs` extra, which is optional to keep the base
install small. Point the client at the extra instead of the bare package:

| Client | Launcher to use |
| ------ | --------------- |
| `uvx` | `uvx --from "docmost-mcp-oss[yjs]" docmost-mcp-oss` |
| Any `command`/`args` JSON | `"command": "uvx"`, `"args": ["--from", "docmost-mcp-oss[yjs]", "docmost-mcp-oss"]` |

For example, in Claude Code:

```bash
claude mcp add docmost \
  -e DOCMOST_URL=https://docmost.example.com \
  -e DOCMOST_EMAIL=you@example.com \
  -e DOCMOST_PASSWORD=your-password \
  -- uvx --from "docmost-mcp-oss[yjs]" docmost-mcp-oss
```

## Tests

| Command                                               | What it validates                          | Needs instance |
| ----------------------------------------------------- | ------------------------------------------ | -------------- |
| `uv run python tests/test_client.py`                | Client against a mocked Docmost (12 cases) | No             |
| `uv run python tests/test_tools.py`                 | MCP tool registry                          | No             |
| `uv run python tests/smoke_live.py`                 | Read-only against a real instance          | Yes            |
| `uv run python tests/smoke_mcp_live.py`             | Tools through the MCP layer                | Yes            |
| `uv run --extra yjs python tests/smoke_yjs_live.py` | **Body editing via Yjs** (7 checks)  | Yes            |
| `uv run ruff check .`                               | Lint                                       | No             |

The live tests read credentials from `.docmost-creds.json` (ignored by git):

```json
{
  "url": "https://docmost.example.com",
  "email": "you@example.com",
  "password": "your-password"
}
```

`--write` adds a **create → update → get → delete** cycle over a test page
(use `--write keep` to keep it).

## Implementation notes

Things that are **not** obvious and that the client already handles:

- **All endpoints are `POST`** and respond with `{data, success, status}`; the client unwraps `data`.
- **Content does not come from `/pages/info`**: it is fetched via `/pages/export` (`markdown`|`html`), which responds with the raw file, no wrapper.
- **Only `/pages/import` persists content over REST**; `/pages/create` and `/pages/update` ignore `content`. To edit the body of an already-created page you must write to the Yjs document (see above).
- **Authentication:** both real variants are supported — the `authToken` cookie (httpOnly) and `data.tokens.accessToken` forwarded as `Bearer`.
- **`/search` requires `query` and `spaceId`**; if you don't provide a space, it fans out across all accessible spaces and merges by `rank`.
- **`/pages/sidebar-pages` requires `spaceId`**; if you only provide a page, its space is resolved first.
- **Lexical search (PostgreSQL FTS):** stopwords ("a", "de", "the") return 0 results.
- **Heterogeneous response shapes:** some builds return `{items, meta}` and others raw lists; the client normalizes both.
- **Permissions:** the MCP acts *as* the authenticated user; it can never do more than the user can.

## Structure

```
docmost-mcp-oss/
├── docmost_mcp_oss/
│   ├── __init__.py
│   ├── client.py       # async HTTP client for the Docmost REST API
│   ├── collab.py       # Yjs WebSocket: read/write page bodies
│   └── server.py       # FastMCP server + tools
├── docs/
│   ├── DOCMOST-API.md  # API research (OSS + real instance)
│   └── YJS-EDITING.md  # collaboration WebSocket protocol
├── tests/
│   ├── test_client.py      # mocked, no network
│   ├── test_tools.py       # MCP tool registry, no network
│   ├── smoke_live.py       # real instance, read-only
│   ├── smoke_mcp_live.py   # MCP layer against a real instance
│   └── smoke_yjs_live.py   # body editing via Yjs
├── .github/workflows/
│   ├── ci.yml                # lint, tests and packaging
│   └── release.yml           # tag -> build -> PyPI -> GitHub Release
├── CHANGELOG.md
├── CONTRIBUTING.md
├── LICENSE                   # MIT
├── pyproject.toml            # metadata, dependencies and ruff config
├── uv.lock                   # reproducible resolution (it is versioned)
└── .env.example
```

## License

[MIT](https://github.com/abelsr/docmost-mcp-oss/blob/main/LICENSE) © 2026 Abel Santillan Rodriguez
