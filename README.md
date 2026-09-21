# docmost-mcp

An [MCP](https://modelcontextprotocol.io) server built with **FastMCP** that exposes the REST API of [Docmost](https://docmost.com) as tools for AI assistants (Claude Desktop, Claude Code, Cursor, VS Code…).

Managed with **[uv](https://docs.astral.sh/uv/)**.

> 📄 Full API research: [`docs/DOCMOST-API.md`](docs/DOCMOST-API.md).
> Verified against a real Docmost instance (not just the documentation).

## Why a custom MCP?

Docmost ships with an **official** MCP, but it requires a *Business/Enterprise*l icense and is enabled from *Settings → AI settings → MCP*. This project uses the **internal API** (the same one the web UI consumes), which is also available in the **self-hosted OSS** edition.

## Exposed tools (20)

| Category | Tools                                                                                                                                                                                                                                              |
| -------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Pages    | `search_pages`, `get_page`, `create_page`, `update_page`, **`update_page_content`**, `delete_page`, `restore_page`, `move_page`, `list_recent_pages`, `list_child_pages`, `get_page_breadcrumbs`, `get_page_history` |
| Spaces   | `list_spaces`, `get_space`, `create_space`                                                                                                                                                                                                   |
| Comments | `get_comments`, `create_comment`, `update_comment`                                                                                                                                                                                           |
| User     | `get_current_user`, `list_workspace_members`                                                                                                                                                                                                   |

Two tools stand out:

- **`get_page`** returns **metadata and content** in Markdown (it combines `/pages/info` with `/pages/export`, because the former **does not** return the body).
- **`update_page_content`** **replaces the body of an existing page**. The REST API can't do this: it writes directly to the Yjs document over the collaboration WebSocket. Requires the `yjs` extra and takes ~13 s (Docmost persists with a 10 s *debounce*).

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

Technical details of the protocol: [`docs/YJS-EDITING.md`](docs/YJS-EDITING.md).

## Installation

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
DOCMOST_EMAIL=tu@email.com
DOCMOST_PASSWORD=tu_password
```

Verify the connection:

```bash
uv run docmost-mcp --check
# -> OK: authenticated as tu@email.com (https://docmost.example.com)
```

## Usage

### stdio (recommended for local use)

```bash
uv run docmost-mcp
```

### HTTP (for remote access)

```bash
uv run docmost-mcp --http --port 8000
# MCP endpoint: http://127.0.0.1:8000/mcp
```

## Connecting to MCP clients

### Claude Desktop (`claude_desktop_config.json`)

```json
{
  "mcpServers": {
    "docmost": {
      "command": "uv",
      "args": ["--directory", "/ruta/a/docmost-mcp", "run", "docmost-mcp"],
      "env": {
        "DOCMOST_URL": "https://docmost.example.com",
        "DOCMOST_EMAIL": "tu@email.com",
        "DOCMOST_PASSWORD": "tu_password"
      }
    }
  }
}
```

### Claude Code

```bash
claude mcp add docmost -- uv --directory /ruta/a/docmost-mcp run docmost-mcp
```

### Cursor (`.cursor/mcp.json`)

Same as Claude Desktop, inside the `mcpServers` key.

## Tests

| Command                                               | What it validates                          | Needs instance |
| ----------------------------------------------------- | ------------------------------------------ | -------------- |
| `uv run python tests/test_client.py`                | Client against a mocked Docmost (12 cases) | No             |
| `uv run python tests/smoke_live.py`                 | Read-only against a real instance          | Yes            |
| `uv run python tests/smoke_mcp_live.py`             | Tools through the MCP layer                | Yes            |
| `uv run --extra yjs python tests/smoke_yjs_live.py` | **Body editing via Yjs** (7 checks)  | Yes            |
| `uvx ruff check .`                                  | Lint                                       | No             |

The live tests read credentials from `.docmost-creds.json` (ignored by git):

```json
{
  "url": "https://docmost.example.com",
  "email": "tu@email.com",
  "password": "tu_password"
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
docmost-mcp/
├── docmost_mcp/
│   ├── __init__.py
│   ├── client.py       # async HTTP client for the Docmost REST API
│   ├── collab.py       # Yjs WebSocket: read/write page bodies
│   └── server.py       # FastMCP server + tools
├── docs/
│   ├── DOCMOST-API.md  # API research (OSS + real instance)
│   └── YJS-EDITING.md  # collaboration WebSocket protocol
├── tests/
│   ├── test_client.py      # mocked, no network
│   ├── smoke_live.py       # real instance, read-only
│   ├── smoke_mcp_live.py   # MCP layer against a real instance
│   └── smoke_yjs_live.py   # body editing via Yjs
├── pyproject.toml      # metadata, dependencies and ruff config
├── uv.lock             # reproducible resolution (it is versioned)
└── .env.example
```
