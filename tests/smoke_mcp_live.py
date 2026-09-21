"""End-to-end test of the MCP server against a REAL Docmost instance.

Unlike `smoke_live.py` (which uses the client directly), this test exercises
the **MCP layer**: it starts the FastMCP object and calls the tools with an
in-memory `Client`, verifying that the schema and serialization actually work.

Usage::

    uv run python tests/smoke_mcp_live.py
    uv run python tests/smoke_mcp_live.py --write   # includes create/update/delete
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

CREDS = Path(__file__).resolve().parents[1] / ".docmost-creds.json"


def pick_query_word(rows: list[dict]) -> str:
    """Pick a meaningful word from page titles to use as a search query."""
    words: list[str] = []
    for row in rows:
        for word in str(row.get("title") or "").split():
            cleaned = "".join(c for c in word if c.isalnum())
            if len(cleaned) > 4:
                words.append(cleaned)
    return max(words, key=len) if words else "docmost"


def load_env() -> None:
    data = json.loads(CREDS.read_text())
    os.environ["DOCMOST_URL"] = data["url"]
    email = data.get("email") or data.get("username")
    if data.get("api_key"):
        os.environ["DOCMOST_API_KEY"] = data["api_key"]
    else:
        os.environ["DOCMOST_EMAIL"] = email
        os.environ["DOCMOST_PASSWORD"] = data["password"]
    print(f"· instance: {data['url']}")


async def main(write: bool) -> int:
    from fastmcp import Client

    import docmost_mcp_oss.server as srv

    srv._client = None  # force a new client with the loaded environment

    async with Client(srv.mcp) as client:
        tools = await client.list_tools()
        print(f"\n▸ Exposed tools: {len(tools)}")
        print("  " + ", ".join(sorted(t.name for t in tools)))

        print("\n▸ get_current_user")
        me = (await client.call_tool("get_current_user", {})).data
        print(f"  ✓ {me['user']['email']} @ {me['workspace']['name']}")

        print("\n▸ list_spaces")
        spaces = (await client.call_tool("list_spaces", {})).data
        print(f"  ✓ {len(spaces)} space(s): {[s['name'] for s in spaces]}")

        print("\n▸ get_workspace_overview")
        overview = (await client.call_tool("get_workspace_overview", {})).data
        print(f"  ✓ {overview['total_spaces']} space(s), {overview['total_pages']} page(s)")
        for space in overview["spaces"]:
            titles = [p["title"] for p in space["pages"]]
            print(f"      [{space['name']}] {space['page_count']}: {titles}")

        print("\n▸ activity annotation")
        dated = [p for s in overview["spaces"] for p in s["pages"] if p.get("updated_at")]
        assert dated, "no page carried an updated_at; is the recent window empty?"
        newest = max(dated, key=lambda p: p["updated_at"])
        print(f"  ✓ {len(dated)} page(s) dated; newest: {newest['title']!r}")
        print(f"      {newest['updated_at']} by {newest['updated_by']}")
        assert overview["recently_updated"], overview
        order = [p["updated_at"] for p in overview["recently_updated"]]
        assert order == sorted(order, reverse=True), order
        print(f"  ✓ recently_updated is newest-first ({len(order)} entries)")

        print("\n▸ activity='none' skips the extra requests")
        lean = (await client.call_tool("get_workspace_overview", {"activity": "none"})).data
        assert "recently_updated" not in lean, lean
        assert lean["total_pages"] == overview["total_pages"], lean
        print("  ✓ same inventory, no activity payload")
        # The roots-only call must be a subset: the overview walks the tree.
        roots = 0
        for space in spaces:
            listed = await client.call_tool("list_child_pages", {"space_id": space["id"]})
            roots += len(listed.data["items"])
        assert overview["total_pages"] >= roots, (overview["total_pages"], roots)
        print(f"  ✓ overview page count ({overview['total_pages']}) >= root-only count ({roots})")

        print("\n▸ list_child_pages without arguments is refused")
        try:
            await client.call_tool("list_child_pages", {})
            print("  ✗ it should have failed")
        except Exception as exc:  # noqa: BLE001 - the message is what matters
            assert "get_workspace_overview" in str(exc), exc
            print("  ✓ points the caller at get_workspace_overview")

        print("\n▸ search_pages")
        # Derive a meaningful query word from a real page title so the test works
        # on any instance (a full-text query needs a real word; stopwords return 0).
        recent = (await client.call_tool("list_recent_pages", {"limit": 10})).data
        query = pick_query_word(recent)
        print(f"  · query derived from recent pages: {query!r}")
        hits = (await client.call_tool("search_pages", {"query": query})).data
        print(f"  ✓ {len(hits['items'])} result(s) in {hits['spaces_searched']} space(s)")
        if not hits["items"]:
            print("  ! no results: the rest of the test does not apply")
            return 0
        page_id = hits["items"][0]["id"]

        print(f"\n▸ get_page({page_id})")
        page = (await client.call_tool("get_page", {"page_id": page_id})).data
        content = page.get("content") or ""
        print(f"  ✓ {page['title']!r} — {len(content)} markdown characters")

        print(f"\n▸ get_page_breadcrumbs({page_id})")
        crumbs = (await client.call_tool("get_page_breadcrumbs", {"page_id": page_id})).data
        print(f"  ✓ {' / '.join(c['title'] for c in crumbs)}")

        if not write:
            print("\n✅ MCP layer verified (read-only).")
            return 0

        print("\n▸ create_page → get_page → update_page(title) → delete_page")
        title = "docmost-mcp-oss e2e"
        created = (
            await client.call_tool(
                "create_page",
                {
                    "space_id": spaces[-1]["id"],
                    "title": title,
                    "content": "Created via MCP.\n\n- [x] import\n",
                },
            )
        ).data
        new_id = created.get("slugId") or created.get("id")
        print(f"  ✓ create_page → {new_id}")

        back = (await client.call_tool("get_page", {"page_id": new_id})).data
        assert back.get("title") == title, back
        assert "Created via MCP" in (back.get("content") or ""), back
        print(f"  ✓ get_page re-reads the content ({len(back.get('content') or '')} chars)")

        await client.call_tool("update_page", {"page_id": new_id, "title": f"{title} (v2)"})
        renamed = (await client.call_tool("get_page", {"page_id": new_id})).data
        assert renamed.get("title") == f"{title} (v2)", renamed
        assert "Created via MCP" in (renamed.get("content") or ""), renamed
        print("  ✓ update_page renames and preserves the content")

        await client.call_tool("delete_page", {"page_id": new_id})
        print("  ✓ delete_page (moved to the trash)")

        print("\n✅ MCP layer verified (read and write).")
        return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    if not CREDS.exists():
        sys.exit(f"ERROR: missing {CREDS}")
    load_env()
    sys.exit(asyncio.run(main(args.write)))
