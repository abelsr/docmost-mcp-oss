"""Smoke test against a REAL Docmost instance (read-only by default).

Reads credentials from `.docmost-creds.json` (default) or from the usual
environment variables.

JSON format (one of the two auth options)::

    { "url": "https://docmost.example.com",
      "email": "user@example.com", "password": "secret" }

    { "url": "https://docmost.example.com",
      "api_key": "dm_xxx" }

(`username` is accepted as an alias for `email`.)

Usage::

    uv run python tests/smoke_live.py              # read-only
    uv run python tests/smoke_live.py --write      # + create/update/delete cycle
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from docmost_mcp.client import DocmostClient, DocmostError  # noqa: E402

DEFAULT_CREDS = Path(__file__).resolve().parents[1] / ".docmost-creds.json"


# ---------------------------------------------------------------------- #
# Presentation utilities
# ---------------------------------------------------------------------- #
def ok(msg: str) -> None:
    print(f"  ✓ {msg}")


def fail(msg: str) -> None:
    print(f"  ✗ {msg}")


def step(msg: str) -> None:
    print(f"\n▸ {msg}")


def pick_query_word(rows: list[dict]) -> str:
    """Pick a meaningful word from the titles to test the search."""
    words: list[str] = []
    for row in rows:
        for word in str(row.get("title") or "").split():
            cleaned = "".join(c for c in word if c.isalnum())
            if len(cleaned) > 4:
                words.append(cleaned)
    return max(words, key=len) if words else "docmost"


def load_creds(path: Path) -> dict:
    if path.exists():
        print(f"· credentials: {path}")
        data = json.loads(path.read_text())
        if not data.get("email") and data.get("username"):
            data["email"] = data["username"]  # lenient alias
        return data
    if os.getenv("DOCMOST_URL"):
        print("· credentials: environment variables")
        return {
            "url": os.environ["DOCMOST_URL"],
            "api_key": os.getenv("DOCMOST_API_KEY"),
            "email": os.getenv("DOCMOST_EMAIL"),
            "password": os.getenv("DOCMOST_PASSWORD"),
        }
    sys.exit(f"ERROR: could not find {path} or DOCMOST_URL in the environment.")


# ---------------------------------------------------------------------- #
# Test
# ---------------------------------------------------------------------- #
async def run(creds: dict, write: bool) -> bool:
    client = DocmostClient(
        creds["url"],
        api_key=creds.get("api_key"),
        email=creds.get("email"),
        password=creds.get("password"),
    )
    print(f"\n=== Instance: {client.base_url} ===")

    try:
        step("Authentication")
        t0 = time.perf_counter()
        me = await client.get_current_user()
        user = (me or {}).get("user", {})
        ws = (me or {}).get("workspace", {})
        ok(f"login in {time.perf_counter() - t0:.2f}s as {user.get('email', '?')}")
        ok(f"workspace: {ws.get('name', '?')}")

        step("Spaces")
        spaces = await client.list_spaces(limit=100)
        ok(f"list_spaces: {len(spaces)} space(s)")
        for s in spaces[:10]:
            print(f"      - {s.get('name')}  id={s.get('id')}")
        if not spaces:
            fail("no accessible spaces: the rest does not apply")
            return True
        space = spaces[0]

        step("Navigation")
        tree = await client.list_child_pages(space_id=space["id"], limit=20)
        ok(f"list_child_pages('{space.get('name')}'): {len(tree)} root page(s)")
        recent = await client.list_recent_pages(limit=5)
        ok(f"list_recent_pages: {len(recent)} page(s)")
        for p in recent[:3]:
            print(f"      - {str(p.get('title'))[:60]!r}")

        step("Full-text search")
        word = pick_query_word(recent or tree)
        found = await client.search_pages(word, limit=5)
        ok(
            f"search_pages({word!r}): {len(found['items'])} result(s) "
            f"in {found['spaces_searched']} space(s)"
        )
        for r in found["items"][:3]:
            print(f"      - {str(r.get('title'))[:60]!r} rank={r.get('rank')}")

        step("Page read (metadata + content)")
        candidates = recent or found["items"] or tree
        if not candidates:
            fail("found no page to read")
            return True

        page_id = candidates[0].get("id") or candidates[0].get("slugId")
        page = await client.get_page(page_id, format="markdown")
        content = page.get("content") or ""
        ok(f"get_page({page_id}): {str(page.get('title'))[:60]!r}")
        if page.get("content_error"):
            fail(f"content not available: {page['content_error']}")
        else:
            ok(f"content: {len(content)} markdown characters")
            print("      ┌─── markdown ───")
            for line in content.splitlines()[:6]:
                print(f"      │ {line[:100]}")
            print("      └────────────────")

        crumbs = await client.get_page_breadcrumbs(page_id)
        ok(f"breadcrumbs: {' / '.join(str(b.get('title')) for b in crumbs) or '(root)'}")

        history = await client.get_page_history(page_id)
        ok(f"history: {len(history)} version(s)")

        step("Comments")
        comments = await client.get_comments(page_id, limit=10)
        ok(f"get_comments: {len(comments)} comment(s)")

        if write:
            step("Writing (create with content → rename → get → delete)")
            title = f"docmost-mcp smoke test {int(time.time())}"
            created = await client.create_page(
                space["id"],
                title=title,
                content="Created by `docmost-mcp`.\n\n- [x] create_page\n- [x] import\n",
            )
            new_id = (created or {}).get("slugId") or (created or {}).get("id")
            ok(f"create_page: {title!r} → id={new_id}")

            roundtrip = await client.get_page(new_id, format="markdown")
            body = roundtrip.get("content") or ""
            ok(f"get_page: title={roundtrip.get('title')!r}, {len(body)} characters")
            assert roundtrip.get("title") == title, f"unexpected title: {roundtrip.get('title')!r}"
            assert "Created by" in body, "the content was not persisted"
            assert "create_page" in body, "the content was not fully persisted"
            ok("the written content is read back intact ✓")

            renamed = f"{title} (renamed)"
            await client.update_page(new_id, title=renamed)
            after = await client.get_page(new_id, format="markdown")
            assert after.get("title") == renamed, f"the rename failed: {after.get('title')!r}"
            assert "Created by" in (after.get("content") or ""), "the rename lost the content"
            ok(f"update_page(title): {after.get('title')!r} (content intact) ✓")

            # Check that content is rejected instead of failing silently.
            try:
                await client.update_page(new_id, content="should not be applied")
                fail("update_page(content) should have raised an error")
            except DocmostError as exc:
                assert "does not allow updating page content" in exc.message
                ok("update_page(content) fails explicitly ✓ (real API limitation)")

            if write == "keep":
                print(f"      ℹ️  page kept: {after.get('title')!r}")
            else:
                await client.delete_page(new_id)
                ok(f"delete_page: {after.get('title')!r} moved to the trash")

        return True

    except DocmostError as exc:
        fail(f"DocmostError: {exc}")
        if exc.payload:
            print(f"      payload: {json.dumps(exc.payload)[:300]}")
        return False
    finally:
        await client.aclose()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--creds", type=Path, default=DEFAULT_CREDS)
    ap.add_argument(
        "--write",
        nargs="?",
        const=True,
        default=False,
        choices=[True, "keep"],
        help=(
            "Also create/update/delete a test page. "
            "Use --write keep to not delete it at the end."
        ),
    )
    args = ap.parse_args()
    creds = load_creds(args.creds)
    ok_run = asyncio.run(run(creds, args.write))
    print(f"\n{'✅ Smoke test passed' if ok_run else '❌ Smoke test failed'}")
    sys.exit(0 if ok_run else 1)


if __name__ == "__main__":
    main()
