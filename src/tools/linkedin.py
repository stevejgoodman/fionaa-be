"""LinkedIn MCP client factory.

Prerequisites (run once from the linkedin-mcp-server directory):
    uv run linkedin-mcp-server --get-session   # authenticate with LinkedIn
    uv run playwright install chromium          # install browser if needed
"""

import os
import shutil
from pathlib import Path

from langchain_mcp_adapters.client import MultiServerMCPClient

LINKEDIN_SERVER_DIR = Path(os.path.expanduser("~/dev/linkedin-mcp-server"))


async def get_linkedin_tools() -> list:
    """Return a list of LangChain tools backed by the LinkedIn MCP server.

    The MCP server is started as a subprocess and communicates over stdio.
    Call this once at startup and reuse the returned tool list.
    """
    uv_path = shutil.which("uv") or "/opt/homebrew/bin/uv"

    env = os.environ.copy()
    if "/opt/homebrew/bin" not in env.get("PATH", ""):
        env["PATH"] = f"/opt/homebrew/bin:{env['PATH']}"
    env["TRANSPORT"] = "stdio"

    client = MultiServerMCPClient(
        {
            "linkedin": {
                "command": uv_path,
                "transport": "stdio",
                "args": [
                    "--directory",
                    str(LINKEDIN_SERVER_DIR),
                    "run",
                    "linkedin-mcp-server",
                ],
                "cwd": str(LINKEDIN_SERVER_DIR),
                "env": env,
            }
        }
    )
    return await client.get_tools()
