"""Client tests against a simulated Docmost (no extra dependencies).

The test server mimics the behaviour observed on real instances:

* `POST /api/*` with the `{data, success, status}` envelope,
* two login flavours (cookie `authToken` and `data.tokens.accessToken`),
* `/pages/info` **without** content + `/pages/export` as raw text,
* `/search` that **requires** `query` and `spaceId`,
* `/pages/sidebar-pages` that requires `spaceId`,
* listings shaped as `{items, meta}`.

    uv run python tests/test_client.py
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from docmost_mcp_oss.client import DocmostClient, DocmostError  # noqa: E402

API_KEY = "test-api-key"
JWT = "test-jwt-token"
EMAIL = "user@example.com"
PASSWORD = "secret"
SPACE = "01a0c225-d97c-791f-98d0-296b43df9da7"
PAGE = "01a0c23e-870b-7d54-99dd-cc4865174ba8"

# Login mode simulated by the server: "cookie" or "tokens".
LOGIN_MODE = "cookie"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    # -- helpers ------------------------------------------------------- #
    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        self._raw = raw  # used to inspect the multipart of /pages/import
        try:
            return json.loads(raw or b"{}")
        except json.JSONDecodeError:
            return {}

    def _send(self, status: int, payload, cookies: dict | None = None):
        if payload is None:
            raw = b""
        elif isinstance(payload, str):
            raw = payload.encode()
        else:
            raw = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        for name, value in (cookies or {}).items():
            self.send_header("Set-Cookie", f"{name}={value}; HttpOnly; Path=/; SameSite=Lax")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _authed(self) -> bool:
        cookie = self.headers.get("Cookie") or ""
        bearer = (self.headers.get("Authorization") or "").removeprefix("Bearer ")
        return "authToken=" in cookie or bearer in (API_KEY, JWT)

    # -- routes -------------------------------------------------------- #
    def do_POST(self):  # noqa: N802
        path, body = self.path, self._body()

        if path == "/api/auth/login":
            if body.get("email") != EMAIL or body.get("password") != PASSWORD:
                return self._send(
                    401,
                    {"statusCode": 401, "message": "Email or password does not match"},
                )
            if LOGIN_MODE == "cookie":
                return self._send(200, {"success": True, "status": 200}, {"authToken": JWT})
            return self._send(
                200,
                {
                    "data": {"tokens": {"accessToken": JWT, "refreshToken": "r"}},
                    "success": True,
                    "status": 200,
                },
            )

        if not self._authed():
            return self._send(401, {"statusCode": 401, "message": "Unauthorized"})

        if path == "/api/users/me":
            return self._send(
                200,
                {
                    "data": {"user": {"email": EMAIL}, "workspace": {"name": "Demo"}},
                    "success": True,
                    "status": 200,
                },
            )

        if path == "/api/spaces":
            return self._send(
                200,
                {
                    "data": {"items": [{"id": SPACE, "name": "Desarrollo"}], "meta": {"page": 1}},
                    "success": True,
                    "status": 200,
                },
            )

        if path == "/api/search":
            # Same as real builds: requires query AND spaceId.
            missing = [f for f in ("query", "spaceId") if not body.get(f)]
            if missing:
                return self._send(
                    400,
                    {
                        "statusCode": 400,
                        "message": [f"{f} must be a string" for f in missing],
                    },
                )
            hits = (
                []
                if body["query"] == "nada"
                else [{"id": PAGE, "title": "Conventions", "rank": 0.7, "spaceId": body["spaceId"]}]
            )
            # The response is a raw list (real observed shape).
            return self._send(200, {"data": hits, "success": True, "status": 200})

        if path == "/api/pages/info":
            # Metadata WITHOUT content, just like on real builds.
            return self._send(
                200,
                {
                    "data": {
                        "id": PAGE,
                        "slugId": "tRUr7isZOe",
                        "title": "Conventions",
                        "spaceId": SPACE,
                    },
                    "success": True,
                    "status": 200,
                },
            )

        if path == "/api/pages/export":
            if body.get("format") not in ("markdown", "html"):
                return self._send(
                    400,
                    {
                        "statusCode": 400,
                        "message": ["format must be one of the following values: html, markdown"],
                    },
                )
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Disposition", 'attachment; filename="Conventions.md"')
            raw = b"# Conventions\n\nTest content."
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return

        if path == "/api/pages/sidebar-pages":
            if not body.get("spaceId"):
                return self._send(400, {"statusCode": 400, "message": ["spaceId must be a UUID"]})
            return self._send(
                200,
                {
                    "data": {"items": [{"id": PAGE, "title": "Conventions"}], "meta": {}},
                    "success": True,
                    "status": 200,
                },
            )

        if path == "/api/pages/breadcrumbs":
            # Raw list, not {items}.
            return self._send(
                200,
                {"data": [{"id": PAGE, "title": "Conventions"}], "success": True, "status": 200},
            )

        if path == "/api/pages/create":
            # Same as real builds: completely IGNORES `content`.
            return self._send(
                200,
                {
                    "data": {
                        "id": "nuevo-1",
                        "slugId": "abc123",
                        "title": body.get("title"),
                    },
                    "success": True,
                    "status": 200,
                },
            )

        if path == "/api/pages/import":
            # Multipart: the only way that persists the page body.
            ctype = self.headers.get("Content-Type") or ""
            if "multipart/form-data" not in ctype:
                return self._send(
                    400,
                    {"statusCode": 400, "message": "Invalid multipart content type"},
                )
            if b"spaceId" not in self._raw:
                return self._send(400, {"statusCode": 400, "message": ["spaceId must be a UUID"]})
            match = re.search(rb"#\s+([^\r\n]+)", self._raw)
            title = match.group(1).decode().strip() if match else "imported"
            return self._send(
                200,
                {
                    "data": {"id": "imp-1", "slugId": "imp123", "title": title},
                    "success": True,
                    "status": 200,
                },
            )

        if path == "/api/pages/update":
            # Metadata only: `content` is silently ignored on the server.
            return self._send(
                200,
                {
                    "data": {"id": body.get("pageId"), "title": body.get("title")},
                    "success": True,
                    "status": 200,
                },
            )

        return self._send(404, {"statusCode": 404, "message": f"Cannot POST {path}"})


def start_server() -> tuple[HTTPServer, str]:
    server = HTTPServer(("127.0.0.1", 0), Handler)
    Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


async def run_tests(base_url: str) -> None:
    global LOGIN_MODE

    # --- 1. Cookie login + `data` unwrapping ---
    LOGIN_MODE = "cookie"
    async with DocmostClient(base_url, email=EMAIL, password=PASSWORD) as dm:
        assert (await dm.get_current_user())["user"]["email"] == EMAIL
        assert (await dm.list_spaces())[0]["id"] == SPACE
        print("✓ cookie login + `{items, meta}` listings + `data` unwrapping")

    # --- 2. Login with tokens in the body (this build) ---
    LOGIN_MODE = "tokens"
    async with DocmostClient(base_url, email=EMAIL, password=PASSWORD) as dm:
        assert await dm.list_spaces(), "should authenticate with accessToken as Bearer"
        print("✓ login with `data.tokens.accessToken` re-sent as Bearer")

    # --- 3. API Key as Bearer ---
    async with DocmostClient(base_url, api_key=API_KEY) as dm:
        assert (await dm.create_page(SPACE, title="X"))["id"] == "nuevo-1"
        print("✓ API Key authentication (Bearer)")

    async with DocmostClient(base_url, api_key=API_KEY) as dm:
        # --- 3b. create_page WITHOUT content uses /pages/create ---
        assert (await dm.create_page(SPACE, title="Title only"))["slugId"] == "abc123"

        # --- 3c. create_page WITH content goes through /pages/import ---
        created = await dm.create_page(SPACE, content="# My page\n\nBody.")
        assert created["slugId"] == "imp123", created
        assert created["title"] == "My page", created

        # --- 3d. when a title is given, an H1 is prepended to pin it ---
        titled = await dm.create_page(SPACE, title="Explicit title", content="Body without H1.")
        assert titled["title"] == "Explicit title", titled
        print("✓ create_page uses `/pages/import` when there is content (and pins the title)")

        # --- 3e. update_page with content fails LOUDLY (not silently) ---
        try:
            await dm.update_page(PAGE, content="new body")
            raise AssertionError("should reject updating content")
        except DocmostError as exc:
            assert "does not allow updating page content" in exc.message, exc

        # --- 3f. update_page with title only does work ---
        renamed = await dm.update_page(PAGE, title="Renombrada")
        assert renamed["title"] == "Renombrada", renamed
        print("✓ update_page renames, but rejects `content` with an explicit error")

    async with DocmostClient(base_url, api_key=API_KEY) as dm:
        # --- 4. get_page = /pages/info + /pages/export ---
        page = await dm.get_page(PAGE)
        assert page["title"] == "Conventions", page
        assert page["content"].startswith("# Conventions"), page
        assert page["content_format"] == "markdown"
        print("✓ get_page combines `/pages/info` with `/pages/export` (real content)")

        # --- 5. export with an invalid format ---
        try:
            await dm.export_page(PAGE, format="pdf")
            raise AssertionError("should reject 'pdf'")
        except ValueError:
            pass
        print("✓ export_page validates the format locally (markdown|html)")

        # --- 6. Search: fan-out because /search requires spaceId ---
        res = await dm.search_pages("Conventions")
        assert len(res["items"]) == 1 and res["spaces_searched"] == 1, res
        assert res["items"][0]["title"] == "Conventions"
        empty = await dm.search_pages("nada")
        assert empty["items"] == []
        print("✓ search_pages requires query and fans out per space (spaceId mandatory)")

        # --- 7. breadcrumbs returns a raw list ---
        crumbs = await dm.get_page_breadcrumbs(PAGE)
        assert isinstance(crumbs, list) and crumbs[0]["title"] == "Conventions"
        print("✓ get_page_breadcrumbs normalizes list-shaped responses")

        # --- 8. list_child_pages requires spaceId; resolved from page_id ---
        kids = await dm.list_child_pages(page_id=PAGE)
        assert kids and kids[0]["id"] == PAGE, kids
        try:
            await dm.list_child_pages()
            raise AssertionError("should require space_id (or page_id)")
        except ValueError as exc:
            assert "space_id (or page_id)" in str(exc), exc
        print("✓ list_child_pages resolves space_id from page_id")

    # --- 9. Translated errors ---
    bad = DocmostClient(base_url, email=EMAIL, password="malo")
    try:
        await bad.authenticate()
        raise AssertionError("should fail")
    except DocmostError as exc:
        assert exc.status == 401 and "does not match" in exc.message, exc
        print("✓ 401 error translated with Docmost's message")
    finally:
        await bad.aclose()

    # --- 10. Empty query rejected locally ---
    async with DocmostClient(base_url, api_key=API_KEY) as dm:
        try:
            await dm.search_pages("   ")
            raise AssertionError("should require query")
        except ValueError:
            pass
        print("✓ search_pages rejects empty queries before calling the network")


def main() -> None:
    server, base_url = start_server()
    try:
        asyncio.run(run_tests(base_url))
        print("\nAll tests passed.")
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()
