"""MCP server (FastMCP) for Docmost.

Exposes Docmost's REST API as MCP tools so that an LLM can search, read,
create and update pages, and manage spaces and comments.

Local run (stdio, for Claude Desktop / Cursor)::

    uv run docmost-mcp-oss

Remote run (HTTP)::

    uv run docmost-mcp-oss --http --port 8000

Environment variables (see .env.example): DOCMOST_URL and either DOCMOST_API_KEY
or DOCMOST_EMAIL + DOCMOST_PASSWORD.

The exposed tools are the subset of endpoints verified against real
instances; see `docs/DOCMOST-API.md`.
"""

from __future__ import annotations

import argparse
import os
import sys

from fastmcp import FastMCP

from .client import DocmostClient, DocmostError

mcp = FastMCP(
    "Docmost",
    instructions=(
        'MCP server for a Docmost workspace. To answer "what is in this '
        'workspace?" or to get an inventory, start with '
        "`get_workspace_overview`, which lists every space and every page "
        "(including nested ones). Then `get_page` reads a page (returns "
        "Markdown) and `search_pages` finds one by keyword. "
        "To create content use `create_page` with Markdown; to "
        "**replace the body of an existing page** use "
        "`update_page_content` (via the Yjs WebSocket, takes ~13 s); to "
        "rename, `update_page`. "
        "Space IDs are UUIDs; so are page IDs (`slugId` is the "
        "short identifier that appears in the URL)."
    ),
)

# Single client, lazily authenticated and reused.
_client: DocmostClient | None = None


async def _get_client() -> DocmostClient:
    global _client
    if _client is None:
        _client = DocmostClient.from_env()
    await _client.authenticate()
    return _client


def _load_dotenv() -> None:
    """Loads a .env from the current directory if `python-dotenv` is available."""
    try:
        from dotenv import load_dotenv  # type: ignore
    except ImportError:
        return
    load_dotenv()


# ====================================================================== #
# Tools — Pages
# ====================================================================== #
@mcp.tool
async def search_pages(
    query: str,
    space_id: str | None = None,
    limit: int = 20,
) -> dict:
    """Searches pages by keyword (full-text search).

    It is a lexical search (PostgreSQL FTS): use meaningful words. Empty-meaning
    terms ("a", "de", "the") are stopwords and return no results.

    Args:
        query: Search terms, e.g. "docker compose".
        space_id: UUID of the space to limit the search to. If omitted, it
            searches all accessible spaces and merges them by relevance.
        limit: Maximum number of results (1-100).
    """
    client = await _get_client()
    return await client.search_pages(query, space_id=space_id, limit=limit)


@mcp.tool
async def get_page(page_id: str, format: str = "markdown") -> dict:
    """Fetches a page: metadata **and** content.

    Returns the page's metadata plus the `content` field with the full text.
    Internally it combines `/pages/info` with `/pages/export`.

    Args:
        page_id: UUID or slugId of the page.
        format: Content format: 'markdown' (recommended) or 'html'.
    """
    client = await _get_client()
    return await client.get_page(page_id, format=format)


@mcp.tool
async def create_page(
    space_id: str,
    title: str | None = None,
    content: str | None = None,
    parent_page_id: str | None = None,
    format: str = "markdown",
) -> dict:
    """Creates a new page in a space, with or without content.

    If you provide `content`, the page is uploaded through the import endpoint
    (`/pages/import`), which is the only REST way that persists the page body
    in Docmost. The title is taken from the first heading; if you also provide
    `title`, that one is used.

    Args:
        space_id: UUID of the destination space.
        title: Title of the page (optional).
        content: Page content in Markdown (recommended).
        parent_page_id: ID of the parent page to nest it under (optional).
        format: Format of `content`: 'markdown' or 'html'.
    """
    client = await _get_client()
    return await client.create_page(
        space_id,
        title=title,
        content=content,
        parent_page_id=parent_page_id,
        format=format,
    )


@mcp.tool
async def update_page(page_id: str, title: str | None = None) -> dict:
    """Renames a page.

    To change the **content**, use `update_page_content`.

    Args:
        page_id: UUID or slugId of the page.
        title: New title.
    """
    client = await _get_client()
    return await client.update_page(page_id, title=title)


@mcp.tool
async def update_page_content(page_id: str, markdown: str) -> dict:
    """**Replaces the body** of an already-created page with the given Markdown.

    This is the operation Docmost's REST API cannot do: the body lives in the
    Yjs collaboration server. This tool opens the collaboration WebSocket,
    replaces the document and waits for it to be persisted (~13 s).

    The Markdown is converted with Docmost's own converter, so it supports its
    whole schema: headings, bold, italics, code, lists, tables, blockquotes,
    code blocks, etc.

    ⚠️ Replaces **all** the page's previous content. Requires the `yjs` extra
    to be installed (`uv sync --extra yjs`).

    Args:
        page_id: UUID or slugId of the page to edit.
        markdown: New complete content, in Markdown.
    """
    try:
        from .collab import CollabError
        from .collab import update_page_content as _update
    except ImportError as exc:  # missing extra
        raise RuntimeError("The 'yjs' extra is not installed. Run: uv sync --extra yjs") from exc

    client = await _get_client()
    try:
        return await _update(client, page_id, markdown)
    except CollabError as exc:
        raise RuntimeError(f"Could not edit the body: {exc}") from exc


@mcp.tool
async def delete_page(page_id: str) -> dict:
    """Moves a page to the trash (recoverable with `restore_page`).

    Args:
        page_id: UUID or slugId of the page.
    """
    client = await _get_client()
    return await client.delete_page(page_id)


@mcp.tool
async def restore_page(page_id: str) -> dict:
    """Restores a page that is in the trash.

    Args:
        page_id: UUID or slugId of the page.
    """
    client = await _get_client()
    return await client.restore_page(page_id)


@mcp.tool
async def move_page(
    page_id: str,
    position: str,
    parent_page_id: str | None = None,
) -> dict:
    """Moves or reorders a page within its space.

    Docmost orders pages with *fractional indexing*: `position` is a 5- to
    12-character string compared lexicographically (e.g. 'a0000' comes before
    'a0001'). To place a page between two existing ones, use an intermediate
    value.

    Args:
        page_id: UUID or slugId of the page to move.
        position: 5-12 character string with the new position.
        parent_page_id: New parent; `None` to leave it at the root.
    """
    client = await _get_client()
    return await client.move_page(page_id, position, parent_page_id=parent_page_id)


@mcp.tool
async def list_recent_pages(space_id: str | None = None, limit: int = 20) -> list[dict]:
    """Lists recently updated pages.

    Args:
        space_id: UUID of the space (optional; without it, from the whole workspace).
        limit: Maximum number of results.
    """
    client = await _get_client()
    return await client.list_recent_pages(space_id=space_id, limit=limit)


@mcp.tool
async def get_workspace_overview(
    space_id: str | None = None,
    max_pages: int = 500,
) -> dict:
    """**Start here.** Lists everything in the workspace: every space and every page.

    Use this to answer questions like "what do I have in Docmost?", to take an
    inventory, or to find a page by title before reading it with `get_page`.
    Unlike `list_child_pages`, it walks the whole page tree, so nested pages are
    included.

    Each page carries `id`, `slug_id`, `title`, `parent_page_id` and `depth`,
    which is enough to rebuild the tree or to list everything flat.

    Args:
        space_id: UUID of a single space to limit the listing (optional).
            Without it, every space the user can access is included.
        max_pages: Safety cap on the total number of pages returned.
    """
    client = await _get_client()
    spaces = [await client.get_space(space_id)] if space_id else await client.list_spaces(limit=100)

    described: list[dict] = []
    remaining = max(1, max_pages)
    for space in spaces:
        if not isinstance(space, dict) or not space.get("id"):
            continue
        pages = await client.list_all_pages(space_id=space["id"], max_pages=remaining)
        remaining -= len(pages)
        described.append(
            {
                "id": space["id"],
                "name": space.get("name"),
                "slug": space.get("slug"),
                "page_count": len(pages),
                "pages": pages,
            }
        )
        if remaining <= 0:
            break

    return {
        "total_pages": sum(s["page_count"] for s in described),
        "total_spaces": len(described),
        "truncated": remaining <= 0,
        "spaces": described,
    }


@mcp.tool
async def list_child_pages(
    space_id: str | None = None,
    page_id: str | None = None,
    limit: int = 100,
) -> dict:
    """Lists only the **direct** children of a space or a page.

    This is one level, not the whole tree. To enumerate everything in the
    workspace, use `get_workspace_overview` instead.

    Args:
        space_id: UUID of the space whose root pages you want.
        page_id: UUID or slugId of the parent page whose children you want
            (the `space_id` is resolved automatically).
        limit: Maximum number of results.
    """
    if not space_id and not page_id:
        raise ValueError(
            "Provide space_id or page_id. To list the whole workspace, use get_workspace_overview."
        )
    client = await _get_client()
    return {"items": await client.list_child_pages(space_id=space_id, page_id=page_id, limit=limit)}


@mcp.tool
async def get_page_breadcrumbs(page_id: str) -> list[dict]:
    """Returns the ancestor path (breadcrumbs) of a page.

    Args:
        page_id: UUID or slugId of the page.
    """
    client = await _get_client()
    return await client.get_page_breadcrumbs(page_id)


@mcp.tool
async def get_page_history(page_id: str) -> list[dict]:
    """Lists the version history of a page.

    Args:
        page_id: UUID or slugId of the page.
    """
    client = await _get_client()
    return await client.get_page_history(page_id)


# ====================================================================== #
# Tools — Spaces
# ====================================================================== #
@mcp.tool
async def list_spaces(limit: int = 50) -> list[dict]:
    """Lists the spaces the user has access to.

    Args:
        limit: Maximum number of spaces to return.
    """
    client = await _get_client()
    return await client.list_spaces(limit=limit)


@mcp.tool
async def get_space(space_id: str) -> dict:
    """Gets the details of a space.

    Args:
        space_id: UUID of the space.
    """
    client = await _get_client()
    return await client.get_space(space_id)


@mcp.tool
async def create_space(name: str, slug: str | None = None, description: str | None = None) -> dict:
    """Creates a new space.

    Args:
        name: Name of the space.
        slug: Identifier for the URL. **Letters and numbers only** (no
            hyphens or underscores), e.g. 'mySpace'.
        description: Description (optional).
    """
    client = await _get_client()
    return await client.create_space(name, slug=slug, description=description)


# ====================================================================== #
# Tools — Comments
# ====================================================================== #
@mcp.tool
async def get_comments(page_id: str, limit: int = 50) -> list[dict]:
    """Gets the comments of a page.

    Args:
        page_id: UUID or slugId of the page.
        limit: Maximum number of comments.
    """
    client = await _get_client()
    return await client.get_comments(page_id, limit=limit)


@mcp.tool
async def create_comment(
    page_id: str,
    content: str,
    parent_comment_id: str | None = None,
) -> dict:
    """Adds a comment to a page.

    Args:
        page_id: UUID or slugId of the page.
        content: Content as a **JSON string** of a Tiptap document, e.g.
            '{"type":"doc","content":[{"type":"paragraph","content":'
            '[{"type":"text","text":"Hello"}]}]}'.
        parent_comment_id: UUID of the parent comment to reply to (optional).
    """
    client = await _get_client()
    return await client.create_comment(page_id, content, parent_comment_id=parent_comment_id)


@mcp.tool
async def update_comment(comment_id: str, content: str) -> dict:
    """Updates the content of a comment.

    Args:
        comment_id: UUID of the comment.
        content: New content as a Tiptap JSON string.
    """
    client = await _get_client()
    return await client.update_comment(comment_id, content)


# ====================================================================== #
# Tools — User / workspace
# ====================================================================== #
@mcp.tool
async def get_current_user() -> dict:
    """Returns the authenticated user and workspace information."""
    client = await _get_client()
    return await client.get_current_user()


@mcp.tool
async def list_workspace_members(limit: int = 50) -> list[dict]:
    """Lists the members of the workspace.

    Args:
        limit: Maximum number of members to return.
    """
    client = await _get_client()
    return await client.list_workspace_members(limit=limit)


# ====================================================================== #
# Entry point
# ====================================================================== #
def main() -> None:
    _load_dotenv()

    parser = argparse.ArgumentParser(description="MCP server for Docmost")
    parser.add_argument(
        "--http",
        action="store_true",
        help="Use HTTP (streamable-http) transport instead of stdio.",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Only verify the connection and authentication with Docmost.",
    )
    args = parser.parse_args()

    if not os.getenv("DOCMOST_URL"):
        print("ERROR: define DOCMOST_URL (see .env.example)", file=sys.stderr)
        sys.exit(1)

    if args.check:
        import asyncio

        async def _check() -> None:
            client = DocmostClient.from_env()
            try:
                me = await client.get_current_user()
                user = (me or {}).get("user", {})
                print(f"OK: authenticated as {user.get('email', '?')} ({client.base_url})")
            except DocmostError as exc:
                print(f"FAIL: {exc}", file=sys.stderr)
                sys.exit(1)
            finally:
                await client.aclose()

        asyncio.run(_check())
        return

    if args.http:
        mcp.run(transport="http", host=args.host, port=args.port)
    else:
        mcp.run()


if __name__ == "__main__":
    main()
