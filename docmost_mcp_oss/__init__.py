"""MCP server (FastMCP) for Docmost."""

from .client import DocmostClient, DocmostError, DocmostMFARequired

__all__ = ["DocmostClient", "DocmostError", "DocmostMFARequired"]
__version__ = "0.1.0"
