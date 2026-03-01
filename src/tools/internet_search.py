"""Internet search tool powered by Tavily."""

from typing import Literal

from langchain.tools import tool
from tavily import TavilyClient

tavily_client = TavilyClient()


@tool
def internet_search(
    query: str,
    max_results: int = 5,
    topic: Literal["general", "news", "finance"] = "general",
    include_raw_content: bool = False,
) -> dict:
    """Run a web search and return structured results.

    Args:
        query: The search query string.
        max_results: Maximum number of results to return (default 5).
        topic: Search topic category — "general", "news", or "finance".
        include_raw_content: Whether to include raw page content in results.

    Returns:
        Tavily search response dict containing results and metadata.
    """
    return tavily_client.search(
        query,
        max_results=max_results,
        include_raw_content=include_raw_content,
        topic=topic,
    )
