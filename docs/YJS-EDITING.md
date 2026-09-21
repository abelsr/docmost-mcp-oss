# Editing the body of an existing page (WebSocket Yjs)

> How the limitation in section 5.2 of
> [`DOCMOST-API.md`](DOCMOST-API.md) was resolved: the REST API **does not**
> allow modifying the body of a page that has already been created.
>
> **Result: it is possible**, by writing directly to the Yjs document over
> the collaboration WebSocket. Implemented in `docmost_mcp/collab.py` and
> exposed as the MCP tool `update_page_content`.

## 1. The problem

`/pages/create` and `/pages/update` accept the `content` field and respond 200,
but **ignore it**: the body is owned by the collaboration server
(Hocuspocus + Yjs), not by the REST API. Verified with 5 formats × 2 operations.

The REST path only allows *creating* pages with content (`/pages/import`).

## 2. The key: the WebSocket token

Reading the frontend bundle:

```js
const docName = `page.${pageId}`;
new HocuspocusProvider({
  name: docName,
  url: "wss://<host>/collab",
  document: ydoc,
  token: session.accessToken,   // ← the same accessToken as from login!
});
```

**The WebSocket token is the `accessToken` already returned by
`POST /api/auth/login`.** No extra "collab token" endpoint is needed.

The server validates it in `AuthenticationExtension.onAuthenticate` and responds
with the scope (`read-write` or `read-only`, depending on the role in the space).

## 3. The protocol

Binary messages with lib0 *varint*s. General structure:

```
varString(documentName) + varUint(messageType) + payload
```

### Message types (`br` in the bundle)

| Value | Type |
|---|---|
| 0 | Sync |
| 1 | Awareness |
| 2 | Auth |
| 3 | QueryAwareness |
| 5 | Stateless |
| 7 | CLOSE |
| 8 | SyncStatus |

### Handshake

**1. Auth** (sent by the client on open):

```
varString("page.<pageId>") + varUint(2) + varUint(0 /*Token*/) + varString(token)
```

Server response:

```
varString(docName) + varUint(2) + varUint(2 /*Authenticated*/) + varString("read-write")
```

On failure: close with code **4401** (`Unauthorized`); without write permission,
**4403** (`Forbidden`).

**2. Sync** — the payload is a standard `y-protocols` message:

```
varString(docName) + varUint(0 /*Sync*/) + varUint(subtype) + varUint8Array(payload)
```

| subtype | meaning |
|---|---|
| 0 | SyncStep1 — state vector |
| 1 | SyncStep2 — full update |
| 2 | Update — incremental changes |

Flow:

1. The client sends SyncStep1 with an empty state vector.
2. The server responds with **SyncStep1** (its state vector) and **SyncStep2**
   (the whole document). ⚠️ You must wait for **both**: the state vector is
   what is used afterwards to compute the delta.
3. The client applies the update, modifies the document and computes
   `delta = doc.get_update(server_state)`.
4. Sends the delta as `Sync + Update`.

## 4. Document format

The document has a single `XmlFragment` named **`default`**. Its children are
elements whose `tag` is the name of the Tiptap node:

`paragraph`, `heading` (`level`), `codeBlock` (`language`), `bulletList`,
`orderedList`, `listItem`, `blockquote`, `horizontalRule`, `table` >
`tableRow` > `tableHeader`/`tableCell` (`colspan`, `rowspan`), `taskList`, ...

**Marks** (bold, italic, code, strike, link) **are not elements**: they are
formatting attributes over ranges of `XmlText`:

```python
text = XmlText()
paragraph.children.append(text)
text.insert(0, "hola", {"bold": True})     # **hola**
```

> Note on pycrdt: a node must **be integrated into the document before**
> touching its attributes or children (`parent.children.append(el)` first, then
> `el.attributes[...]`), otherwise it raises `Not integrated in a document yet`.

## 5. Persistence is delayed

```ts
new Hocuspocus({ debounce: 10000, maxDebounce: 45000, unloadImmediately: false })
```

Docmost batches the changes and writes them to the database **up to 10 s
later** (45 s in the worst case). Hence:

- A change is not visible via `/pages/export` immediately.
- `update_page_content` waits ~13 s before returning.

This also explains why the first verification attempt "failed": it was
querying via REST before the changes had been persisted.

## 6. Converting Markdown → Tiptap structure

Reimplementing the Tiptap schema in Python (tables, lists, tasks, images,
mentions...) would be a lot of work and would fall out of sync with Docmost.

**Solution: use Docmost as the converter.** The Markdown is uploaded with
`/pages/import` to a temporary page (the server converts it to
ProseMirror/Yjs), its document is read over WebSocket and the temporary page
is deleted. That structure is then written to the destination page.

```
markdown ──/pages/import──> temporary page ──WS read──> blocks ──WS write──> destination page
                                    │
                                    └── delete ──> (cleanup)
```

Benefits: full fidelity (supports everything Docmost supports, including
`.docx` and `.pdf`) and zero schema maintenance.

Important detail: Docmost uses the **first heading** of the file as the page
title and removes it from the body. So that the user's Markdown arrives
intact, `blocks_from_markdown` prepends a `# __docmost_mcp_tmp__` that takes
that role.

## 7. Implementation

`docmost_mcp/collab.py`:

| Element | Purpose |
|---|---|
| `CollabClient.open(page_id)` | authenticates and syncs the document |
| `CollabClient.read_blocks()` | current structure as `list[Block]` |
| `CollabClient.replace_blocks(blocks)` | replaces the body and sends the delta |
| `CollabClient.wait_for_persistence()` | waits out the debounce |
| `blocks_from_markdown(client, space_id, md)` | conversion via `/pages/import` |
| `blocks_to_markdown(blocks)` | approximate rendering (debugging) |
| `update_page_content(client, page_id, md)` | the full operation |

MCP tool: **`update_page_content(page_id, markdown)`**.

Requires the `yjs` extra:

```bash
uv sync --extra yjs
```

## 8. Verification

`tests/smoke_yjs_live.py` edits the body of a real page and checks it via
REST, with **7/7 checks**:

```
✓ the title is preserved         ✓ the inline code is present
✓ the old content is gone        ✓ the code block is present
✓ the new paragraph is present   ✓ the table is present
✓ the bold text is preserved
```

## 9. Limitations and next steps

- **Full replacement, not incremental editing.** `replace_blocks` substitutes
  the entire body. Adding `operation=append/prepend` is straightforward
  (insert blocks at the end/beginning without deleting).
- **~13 s latency** due to persistence. It can be reduced to ~1 s if
  verification happens over the WebSocket itself instead of REST, or if the
  server's `debounce` is tuned.
- **One temporary page per edit.** It could be cached, or a dedicated space
  could be used for conversions.
- **If the user is editing the page in the browser** at that moment, changes
  from both sides are merged (normal CRDT behaviour). For a clean
  replacement, the page should not be open.
- **True incremental editing** (inserting a paragraph in the middle without
  touching the rest) would require locating the node by index/position and
  emitting surgical operations. The groundwork is already in place.
