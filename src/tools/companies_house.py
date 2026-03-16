"""Companies House MCP client factory."""

import os
import sys
from pathlib import Path
from typing import Optional

from langchain_core.tools import StructuredTool
from pydantic import Field, create_model

# IAMAuthenticatedMCPClient lives in src/gcp/
sys.path.insert(0, str(Path(__file__).parent.parent))
from gcp.python_client_iam_mcp import IAMAuthenticatedMCPClient

_PY_TYPES = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "array": list,
    "object": dict,
}


def _make_langchain_tool(schema: dict, iam_client: IAMAuthenticatedMCPClient) -> StructuredTool:
    name = schema["name"]
    description = schema.get("description", "")
    props = schema.get("inputSchema", {}).get("properties", {})
    required = set(schema.get("inputSchema", {}).get("required", []))

    fields: dict = {}
    for prop_name, prop_schema in props.items():
        py_type = _PY_TYPES.get(prop_schema.get("type", "string"), str)
        field_desc = prop_schema.get("description", "")
        if prop_name in required:
            fields[prop_name] = (py_type, Field(description=field_desc))
        else:
            fields[prop_name] = (Optional[py_type], Field(default=None, description=field_desc))

    ArgsModel = create_model(f"{name}_args", **fields)

    def _call(**kwargs):
        args = {k: v for k, v in kwargs.items() if v is not None}
        result = iam_client.call_tool(name, args)
        content = result.get("result", {}).get("content", [])
        return content[0]["text"] if content else str(result)

    return StructuredTool(name=name, description=description, func=_call, args_schema=ArgsModel)


async def get_companies_house_tools() -> list:
    """Return a list of LangChain tools backed by the Companies House MCP server on Cloud Run.

    Requires the ``CH_MCP_SERVICE_URL`` environment variable to be set.
    Uses IAM identity token auth for Cloud Run (requires roles/run.invoker on the service account).
    The CH server uses an older MCP protocol (2024-11-05) so tools are built via
    direct JSON-RPC calls rather than the streamable_http transport.

    Raises:
        ValueError: If ``CH_MCP_SERVICE_URL`` is not set in the environment.
    """
    service_url = os.environ.get("CH_MCP_SERVICE_URL", "").strip()
    if not service_url:
        raise ValueError(
            "CH_MCP_SERVICE_URL is not set. "
            "Add it to the .env file in the project root."
        )

    iam_client = IAMAuthenticatedMCPClient(service_url)
    tool_schemas = iam_client.list_tools().get("result", {}).get("tools", [])
    return [_make_langchain_tool(s, iam_client) for s in tool_schemas]
