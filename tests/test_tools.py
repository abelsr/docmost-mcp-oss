"""Offline check of the MCP tool registry.

Verifies that the server exposes the expected tools, that every tool has a
description, a typed output schema and the four annotation hints, and that
nothing requires network access. Useful as a fast regression check and in CI.

    uv run python tests/test_tools.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from docmost_mcp_oss.server import mcp  # noqa: E402

EXPECTED_TOOLS = {
    # Pages
    "search_pages",
    "get_page",
    "create_page",
    "update_page",
    "update_page_content",
    "delete_page",
    "restore_page",
    "move_page",
    "list_recent_pages",
    "get_workspace_overview",
    "list_child_pages",
    "get_page_breadcrumbs",
    "get_page_history",
    # Spaces
    "list_spaces",
    "get_space",
    "create_space",
    # Comments
    "get_comments",
    "create_comment",
    "update_comment",
    # Workspace
    "get_current_user",
    "list_workspace_members",
}


def main() -> None:
    tools = asyncio.run(mcp.list_tools())
    by_name = {tool.name: tool for tool in tools}

    actual = set(by_name)
    missing = EXPECTED_TOOLS - actual
    extra = actual - EXPECTED_TOOLS
    assert not missing, f"missing tools: {sorted(missing)}"
    assert not extra, f"unexpected tools: {sorted(extra)}"
    print(f"✓ {len(tools)} tools registered, exactly as expected")

    # Every tool must be documented: the description is what the LLM reads.
    undocumented = [name for name, tool in by_name.items() if not (tool.description or "").strip()]
    assert not undocumented, f"tools without a description: {undocumented}"
    print("✓ every tool has a description")

    # Typed output schemas are what let MCP clients get structured results
    # (FastMCP only fills `.data` when the return type is annotated).
    untyped = [name for name, tool in by_name.items() if not tool.output_schema]
    assert not untyped, f"tools without an output schema: {untyped}"
    print("✓ every tool declares a typed output schema")

    # The four hints are what a client reads to decide whether it may call a
    # tool without asking, and a directory such as OpenAI's rejects a tool that
    # leaves any of them out. All four must be declared, and all four booleans.
    HINTS = ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint")
    incomplete = {}
    for name, tool in by_name.items():
        declared = tool.annotations.model_dump(by_alias=True) if tool.annotations else {}
        missing = [hint for hint in HINTS if not isinstance(declared.get(hint), bool)]
        if missing:
            incomplete[name] = missing
    assert not incomplete, f"tools with missing annotation hints: {incomplete}"
    print("✓ every tool declares the four annotation hints")

    # The hints have to agree with the tool's name and with each other: a read
    # is never a writer, a read-only tool is neither destructive nor
    # non-idempotent, and every tool here reaches a remote instance.
    mislabelled = set()
    for name, tool in by_name.items():
        hints = tool.annotations
        if name.startswith(("get_", "list_", "search_")) and not hints.read_only_hint:
            mislabelled.add(name)
        if hints.read_only_hint and (hints.destructive_hint or not hints.idempotent_hint):
            mislabelled.add(name)
        if not hints.open_world_hint:
            mislabelled.add(name)
    assert not mislabelled, f"inconsistent annotation hints: {sorted(mislabelled)}"
    print("✓ read-only tools are announced as read-only")

    # The three that are easy to get wrong when a decorator is copied around.
    assert by_name["delete_page"].annotations.destructive_hint
    assert not by_name["create_page"].annotations.idempotent_hint
    assert by_name["update_page_content"].annotations.destructive_hint
    assert not by_name["update_page_content"].annotations.idempotent_hint
    print("✓ the write hints match what those tools do")

    # And the helper refuses a combination that cannot be true.
    from docmost_mcp_oss.server import _hints

    try:
        _hints(read_only=True, destructive=True)
    except ValueError:
        pass
    else:
        raise AssertionError("a read-only tool was allowed to be destructive")

    params = by_name["update_page_content"].parameters
    assert {"page_id", "markdown"} <= set(params.get("properties", {})), params
    print("✓ update_page_content accepts (page_id, markdown)")

    overview = set(by_name["get_workspace_overview"].parameters.get("properties", {}))
    assert {"space_id", "max_pages", "activity", "check_empty"} <= overview, overview
    print("✓ get_workspace_overview exposes the activity and check_empty knobs")

    # A page with no body still exports its title as a leading H1.
    from docmost_mcp_oss.server import _body_is_empty

    assert _body_is_empty("# Title only") is True
    assert _body_is_empty("# Title\n\n") is True
    assert _body_is_empty("") is True
    assert _body_is_empty("# Title\n\nSome text.") is False
    assert _body_is_empty("# Title\n\n- item") is False
    print("✓ _body_is_empty ignores the title heading when measuring a body")

    params = by_name["update_page_content"].parameters
    assert {"page_id", "markdown", "mode"} <= set(params.get("properties", {})), params
    print("✓ update_page_content exposes the write mode")

    # The mode is validated before any connection is attempted, so a typo fails
    # immediately instead of after opening the collaboration WebSocket.
    from docmost_mcp_oss.collab import CollabClient

    collab = CollabClient("https://docmost.example.com", "token")
    for bad in ("bogus", "", "REPLACE"):
        try:
            asyncio.run(collab.replace_blocks([], mode=bad))
        except ValueError:
            continue
        raise AssertionError(f"mode {bad!r} was accepted")
    print("✓ an unknown write mode is rejected up front")

    print("\nTool registry verified.")


if __name__ == "__main__":
    main()
