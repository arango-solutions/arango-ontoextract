"""AOE MCP server — development-time and runtime.

Supports two transports:
  - stdio: for Cursor/Claude Desktop (default, no auth)
  - sse: for remote AI agents and custom clients

Usage:
    # Dev-time (stdio, existing behavior)
    python -m app.mcp.server

    # Runtime (SSE on port 8001)
    python -m app.mcp.server --transport sse --port 8001

    # Full options
    python -m app.mcp.server --transport sse --host 0.0.0.0 --port 8001
"""

from __future__ import annotations

import argparse
import logging
from typing import Any

from mcp.server.fastmcp import FastMCP

from app.mcp.resources.ontology import register_ontology_resources
from app.mcp.tools.er import register_er_tools
from app.mcp.tools.export import register_export_tools
from app.mcp.tools.introspection import register_introspection_tools
from app.mcp.tools.ontology import register_ontology_tools
from app.mcp.tools.pipeline import register_pipeline_tools
from app.mcp.tools.temporal import register_temporal_tools

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger(__name__)


def create_mcp_server(
    transport: str = "stdio",
    host: str = "0.0.0.0",
    port: int = 8001,
) -> FastMCP:
    """Create and configure the AOE MCP server with all tools and resources.

    Args:
        transport: The transport mode — "stdio" or "sse".
        host: Host to bind for SSE transport.
        port: Port for SSE transport.
    """
    server_name = "aoe-dev" if transport == "stdio" else "aoe-runtime"

    kwargs: dict[str, Any] = {
        "instructions": (
            "AOE (Arango-OntoExtract) MCP server. "
            "Provides tools to query ontologies, trigger extractions, "
            "inspect temporal history, run entity resolution, "
            "trace provenance, and export ontology graphs. "
            "Also exposes read-only resources for system health, "
            "ontology summaries, and recent extraction runs."
        ),
    }
    if transport == "sse":
        kwargs["host"] = host
        kwargs["port"] = port

    mcp = FastMCP(server_name, **kwargs)

    register_introspection_tools(mcp)
    register_ontology_tools(mcp)
    register_pipeline_tools(mcp)
    register_temporal_tools(mcp)
    register_export_tools(mcp)
    register_er_tools(mcp)
    register_ontology_resources(mcp)

    log.info(
        "MCP server configured",
        extra={"transport": transport, "server_name": server_name},
    )
    return mcp


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments for transport, host, and port."""
    parser = argparse.ArgumentParser(
        description="AOE MCP Server — ontology operations for AI agents",
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse"],
        default="stdio",
        help="Transport protocol (default: stdio)",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host to bind SSE server to (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8001,
        help="Port for SSE server (default: 8001)",
    )
    return parser.parse_args(argv)


mcp = create_mcp_server()


if __name__ == "__main__":
    args = parse_args()
    server = create_mcp_server(
        transport=args.transport,
        host=args.host,
        port=args.port,
    )

    if args.transport == "sse":
        log.info(
            "Starting AOE runtime MCP server (SSE)",
            extra={"host": args.host, "port": args.port},
        )
        server.run(transport="sse")
    else:
        log.info("Starting AOE dev-time MCP server (stdio)")
        server.run(transport="stdio")
