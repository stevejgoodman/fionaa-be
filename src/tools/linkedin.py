"""LinkedIn MCP client factory."""

import os

import google.auth.transport.requests
from google.oauth2 import id_token as oauth2_id_token
from langchain_mcp_adapters.client import MultiServerMCPClient


async def get_linkedin_tools() -> list:
    """Return a list of LangChain tools backed by the LinkedIn MCP server on Cloud Run.

    Requires the ``LINKEDIN_MCP_SERVICE_URL`` environment variable to be set.
    Uses IAM identity token auth for Cloud Run (requires roles/run.invoker on the service account).

    Raises:
        ValueError: If ``LINKEDIN_MCP_SERVICE_URL`` is not set in the environment.
    """
    service_url = os.environ.get("LINKEDIN_MCP_SERVICE_URL", "").strip()
    if not service_url:
        raise ValueError(
            "LINKEDIN_MCP_SERVICE_URL is not set. "
            "Add it to the .env file in the project root."
        )

    request = google.auth.transport.requests.Request()
    token = oauth2_id_token.fetch_id_token(request, service_url)

    client = MultiServerMCPClient(
        {
            "linkedin": {
                "transport": "streamable_http",
                "url": f"{service_url}/mcp",
                "headers": {"Authorization": f"Bearer {token}"},
            }
        }
    )
    return await client.get_tools()
