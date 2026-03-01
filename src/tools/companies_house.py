"""Companies House MCP client factory."""

import os
import shutil

from langchain_mcp_adapters.client import MultiServerMCPClient


async def get_companies_house_tools() -> list:
    """Return a list of LangChain tools backed by the Companies House MCP server.

    Requires the ``COMPANIES_HOUSE_API_KEY`` environment variable to be set.
    The MCP server is started as a subprocess (via npx) and communicates over stdio.
    Call this once at startup and reuse the returned tool list.

    Raises:
        ValueError: If ``COMPANIES_HOUSE_API_KEY`` is not set in the environment.
    """
    api_key = os.environ.get("COMPANIES_HOUSE_API_KEY", "").strip()
    if not api_key:
        raise ValueError(
            "COMPANIES_HOUSE_API_KEY is not set. "
            "Add it to the .env file in the project root."
        )

    npx_path = shutil.which("npx") or "/opt/homebrew/bin/npx"

    env = os.environ.copy()
    if "/opt/homebrew/bin" not in env.get("PATH", ""):
        env["PATH"] = f"/opt/homebrew/bin:{env['PATH']}"

    client = MultiServerMCPClient(
        {
            "companies-house": {
                "command": npx_path,
                "transport": "stdio",
                "args": ["-y", "companies-house-mcp-server"],
                "env": {
                    **env,
                    "COMPANIES_HOUSE_API_KEY": api_key,
                },
            }
        }
    )
    return await client.get_tools()
