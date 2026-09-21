# Research: Docmost API (for building an MCP with FastMCP)

> Sources: `docmost/docmost` source code (branch `main`) **and** reverse
> engineering against a real, self-hosted instance (2026-09-21).
>
> ⚠️ The two sources **do not agree**: the real instance behaves differently
> from OSS `main` in critical points. This document clearly marks which
> claims are verified where.

## 0. Executive summary

| Layer | Auth | Availability |
|---|---|---|
| **Internal API** (`/api/*`, the one the web app uses) | JWT via login or API Key | ✅ OSS — **the one we use** |
| Documented public API | API Key | Enterprise only |
| Official MCP (`https://INSTANCE/mcp`) | OAuth or API Key | Business/Enterprise only |

The MCP in this repo relies on the **internal API**, which works without a license.

## 1. Overall architecture

- NestJS + Fastify. Global prefix `/api`.
- **All endpoints are `POST` with a JSON body**, including reads.
- Responses are wrapped by `TransformHttpResponseInterceptor`:

  ```json
  { "data": <payload>, "success": true, "status": 200 }
  ```

- **Important exception:** `/pages/export` does **not** use the wrapper; it
  returns the file raw (`application/octet-stream`) with `Content-Disposition`.
- Errors (Nest format): `{ "statusCode", "message", "error" }`, where
  `message` is an **array** on validation failures.

## 2. Authentication — two distinct forms

### 2.1 Form A: `authToken` cookie (OSS code)

`AuthController.login` does `res.setCookie('authToken', token, {httpOnly, ...})`
and does **not** return the token in the body. `JwtStrategy` reads it like this:

```ts
jwtFromRequest: (req) => req.cookies?.authToken || extractBearerTokenFromHeader(req)
```

### 2.2 Form B: tokens in the body (✅ observed on the real instance)

`POST /api/auth/login` with `{email, password}` returns **200 and no cookie**:

```json
{
  "data": { "tokens": { "accessToken": "eyJ…", "refreshToken": "eyJ…" } },
  "success": true, "status": 200
}
```

- `accessToken` is a JWT with `type: "access"`, `workspaceId`, and a **30-day**
  lifetime (`exp - iat = 2 592 000`).
- Used as `Authorization: Bearer <accessToken>`.
- The client in this repo supports **both forms** automatically.

### 2.3 API Key

`payload.type === JwtType.API_KEY` is validated in `ee/api-key/api-key.service`
(enterprise module). On an OSS build it throws
`UnauthorizedException('Enterprise API Key module missing')`.
With an API Key, just `Authorization: Bearer <key>` is enough.

### 2.4 MFA / SSO

Login can respond 200 with `{userHasMfa, requiresMfaSetup, isMfaEnforced}`
and no session. The client throws `DocmostMFARequired` in that case.

### 2.5 Workspace resolution

- **Self-hosted:** the first workspace in the DB (the host doesn't matter).
- **Cloud:** the **subdomain of the `Host` header** → `base_url` must include it.

## 3. ⚠️ Verified differences: real instance vs. OSS `main`

| Topic | OSS `main` (source) | Real instance (verified) |
|---|---|---|
| Login | `authToken` cookie | `data.tokens.accessToken` in the body |
| Content (read) | `/pages/info` includes it with `format` | ❌ **Does not include it**: you have to go to `/pages/export` |
| Content (write) | `content` in `/create` and `/update` | ❌ **Both ignore `content`**; only `/pages/import` writes |
| `/search` | `spaceId` optional | ❌ **`query` AND `spaceId` required** |
| Invalid `spaceId` | validation error | **HTTP 500** |
| `/search` response | `{items: [...]}` | **raw list** |
| `/pages/sidebar-pages` | `spaceId` or `pageId` | ❌ **`spaceId` required** |
| Pagination | cursor (`limit`/`cursor`) | numeric `page`, response `{items, meta}` |
| `/pages/breadcrumbs` | `{items: [...]}` | **raw list** |
| Missing routes | `duplicate`, `move-to-space`, `trash`, `backlinks*`, `labels*`, `created-by-user` | **do not exist (404)** |

The client normalizes all of these differences (list-or-`{items}`, search
fan-out, `spaceId` resolution, double call for the content).

## 4. Capability map of the real instance

Side-effect-free probing: an empty body yields **400** (validation) if the route
exists, or **404 `Cannot POST …`** if it doesn't.

### 4.1 Routes that EXIST

| Endpoint | Notes |
|---|---|
| `POST /api/auth/login` | returns tokens in `data.tokens` |
| `POST /api/users/me` | `{user, workspace}` |
| `POST /api/spaces` | user's spaces, `{items, meta}` |
| `POST /api/spaces/info` · `create` · `update` · `delete` · `members` · `members/add` · `members/remove` · `members/change-role` | |
| `POST /api/search` | **`query` + `spaceId` required**; returns a list |
| `POST /api/search/suggest` | `query` required |
| `POST /api/pages/info` | metadata, **no content** |
| `POST /api/pages/create` · `update` · `delete` · `restore` · `move` | |
| `POST /api/pages/export` | **content** in `markdown`\|`html`, raw response |
| `POST /api/pages/import` | multipart |
| `POST /api/pages/recent` | `{items, meta}` |
| `POST /api/pages/sidebar-pages` | **`spaceId` required**, `pageId` optional |
| `POST /api/pages/breadcrumbs` | raw list |
| `POST /api/pages/history` · `history/info` | |
| `POST /api/comments` · `create` · `update` · `delete` · `info` | |
| `POST /api/workspace/members` · `invites*` · `public` · `update` | |
| `POST /api/groups*`, `/api/attachments/upload-image`, `/api/files/upload` | |

### 4.2 Routes that DO NOT exist (404)

`/pages/duplicate` · `/pages/move-to-space` · `/pages/trash` ·
`/pages/backlinks` · `/pages/backlinks-count` · `/pages/labels` ·
`/pages/labels/add` · `/pages/created-by-user`

> These are present in OSS `main`, so **they depend on the version**.

## 5. Details of key endpoints

### 5.1 Reading content: `/pages/info` + `/pages/export`

`/pages/info` (`{pageId}`) returns metadata and **no** `content`
(the `format` and `includeContent` parameters are ignored):

```
id, slugId, title, icon, coverPhoto, position, parentPageId, creatorId,
lastUpdatedById, spaceId, workspaceId, isLocked, createdAt, updatedAt,
deletedAt, space
```

The content is obtained separately:

```http
POST /api/pages/export
{ "pageId": "<uuid>", "format": "markdown" }   // or "html"
```

- Response: the file **raw** (`application/octet-stream`).
- `Content-Disposition: attachment; filename="<Title>.md"` (URL-encoded).
- Validation: `format must be one of the following values: html, markdown`.
- Real example: 8 883 characters of Markdown for a page.

### 5.2 Writing content: only `/pages/import` works

This is the most important and counterintuitive finding. **`/pages/create` and
`/pages/update` accept `content` but ignore it completely**: they respond 200
and the page ends up empty. Verified by creating pages with `markdown`, `html`,
ProseMirror JSON (object and string), and without `format` — all five were
left with no body.

Same with `/pages/update`: tried `replace`/`append` on empty pages and on
pages that already had content, with all three formats. **The body never
changes.** The only field that does update is `title`.

The reason: in this build the page body is owned by the **Yjs collaboration
server** (`wss://<host>/collab`), not the REST API. The frontend never
sends `content` over REST.

**The path that does work is `/pages/import`** (multipart):

```http
POST /api/pages/import
Content-Type: multipart/form-data

spaceId=<uuid>
file=@page.md     (Content-Type: text/markdown)
```

- Creates a new page **with** the file's body.
- Formats accepted by the UI: `text/markdown` and `text/html`.
- **The title is derived from the first heading** of the document. Without a
  heading, it uses the file name (`mi-titulo.md` → `mi-titulo`).
- Returns the created page object inside the `data` wrapper.
- Verified round-trip: importing Markdown → `/pages/export` returns the same
  content.

**Consequences for the MCP:**

| Operation | Possible via REST? |
|---|---|
| Read content | ✅ `/pages/export` |
| Create page **with** content | ✅ `/pages/import` |
| Rename page | ✅ `/pages/update` (`title`) |
| **Change the body of an existing page** | ❌ No way |
| Delete / restore / move | ✅ |

The client turns `create_page(..., content=...)` into an import and makes
`update_page(..., content=...)` **fail with an explicit error** instead of
failing silently (an LLM would believe it had saved the content).

> **Resolved:** the body can be edited by writing to the Yjs document over
> the collaboration WebSocket. See [`YJS-EDITING.md`](YJS-EDITING.md).

### 5.3 Search: `/search` requires a space

```http
POST /api/search
{ "query": "docker", "spaceId": "<uuid>", "limit": 5 }
```

- Without `query` → `query must be a string`. Without `spaceId` → `spaceId must be a string`.
- Non-UUID `spaceId` → **HTTP 500** (not a 400).
- Returns a **list** of:
  `{id, title, icon, parentPageId, slugId, creatorId, createdAt, updatedAt, rank, highlight}`
- `highlight` carries fragments with `<b>…</b>`.
- **It is PostgreSQL lexical FTS**: stopwords (`a`, `de`, `the`) return 0
  results, even when pages exist. Use meaningful words.
- To search the whole workspace, the client does a **fan-out** per space and
  merges by `rank` (deduplicating by `id`).

### 5.4 Moving: `/pages/move`

```json
{ "pageId": "…", "position": "a0000", "parentPageId": null }
```

`position` is a string of **5 to 12** characters (fractional indexing,
compared lexicographically). To insert between two pages, use an
intermediate value.

### 5.5 Creating a space: `/spaces/create`

`slug` must be **letters and numbers only** (no hyphens or underscores):

```
name must be a string, slug must contain only letters and numbers
```

### 5.6 Comments

- `POST /comments` → `{pageId, limit}` → `{items, meta}`.
- `POST /comments/create` → `{pageId, content, type, parentCommentId?}` where
  `content` must be a **valid JSON string** (Tiptap document):
  `content must be a json string`.

### 5.7 Pagination

List endpoints return `{items, meta}` with **`page`**-based (numeric)
pagination, not cursor-based. The client sends `limit`, which the server
accepts without complaint.

## 6. The editor and the `/collab` WebSocket

The frontend uses **Tiptap + Yjs** and syncs content over
`wss://<host>/collab`. This explains the finding in section 5.2: the UI **does
not** save the page body via `/pages/update`; the collaboration server does.
That is why `content` is a dead field in `/pages/create` and
`/pages/update`.

For a REST-based MCP:

- **Read** → `/pages/export`.
- **Write new content** → `/pages/import`.
- **Edit the body of an existing page** → over the Yjs WebSocket
  (Hocuspocus). See [`YJS-EDITING.md`](YJS-EDITING.md).

## 7. Discovery methodology (reusable)

For a real instance with no accessible documentation:

1. **Side-effect-free route probing**: `POST` with body `{}` →
   `400` = exists (validation), `404 Cannot POST` = does not exist.
2. **Reading the validation messages**: they reveal the required fields and
   the allowed values (`format must be one of…`).
3. **Frontend bundle**: download `/assets/index-*.js` and extract the real
   calls with a regex:

   ```python
   re.finditer(r'\.(post|get|put|delete|patch)\(\s*"([^"]+)"', bundle)
   ```

   This gives the exact inventory of endpoints the interface uses.
4. Don't trust `/api-docs` or `/openapi.json`: on the instance they return
   the SPA fallback (HTML), not a spec.

## 8. Environment configuration

```
DOCMOST_URL       # https://docmost.example.com (in cloud, with subdomain)
DOCMOST_API_KEY   # optional (alternative to login)
DOCMOST_EMAIL     # optional, for password login
DOCMOST_PASSWORD  # optional
DOCMOST_TIMEOUT   # seconds, default 30
```
