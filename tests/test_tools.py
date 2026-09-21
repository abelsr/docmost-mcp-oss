"""Offline check of the MCP tool registry.

Verifies that the server exposes the expected tools, that every tool has a
description and a typed output schema, and that nothing requires network
access. Useful as a fast regression check and in CI.

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

    params = by_name["update_page_content"].parameters
    assert {"page_id", "markdown"} <= set(params.get("properties", {})), params
    print("✓ update_page_content accepts (page_id, markdown)")

    print("\nTool registry verified.")


if __name__ == "__main__":
    main()
