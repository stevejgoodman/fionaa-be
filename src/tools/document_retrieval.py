"""Semantic retrieval tool — searches document chunks stored in the LangGraph store."""

from langchain.tools import tool
from langgraph.utils.config import get_store


@tool
def search_document_chunks(query: str, case_number: str, k: int = 5) -> str:
    """Search the parsed document chunks for a case using semantic similarity.

    Use this tool when you need to answer a specific question about the content
    of the applicant's submitted documents (bank statements, annual accounts, etc.)
    and the OCR extraction JSON does not contain the detail you need.

    Args:
        query:       Natural-language question or search phrase, e.g.
                     "total revenue for 2023" or "monthly closing balance".
        case_number: The case identifier (e.g. "SteveGoodman").  Must match
                     the case_number used during document ingestion.
        k:           Maximum number of chunks to return (default 5).

    Returns:
        Formatted string of the most relevant document chunks with their
        source document name, page number, and relevance score.
    """
    store = get_store()
    if store is None:
        return "Document store is not available in this environment."

    results = store.search(
        ("cases", case_number),
        query=query,
        limit=k,
    )

    if not results:
        return f"No document chunks found for case '{case_number}' matching: {query}"

    lines = [f"Found {len(results)} chunk(s) for query: '{query}'\n"]
    for i, item in enumerate(results, start=1):
        v = item.value
        score = f"{item.score:.3f}" if item.score is not None else "n/a"
        lines.append(
            f"--- Chunk {i} (score={score}) ---\n"
            f"Source: {v.get('document_name', 'unknown')}  "
            f"| Type: {v.get('document_type', '?')}  "
            f"| Page: {v.get('page_num', '?')}  "
            f"| Chunk type: {v.get('chunk_type', '?')}\n"
            f"{v.get('text', '')}\n"
        )

    return "\n".join(lines)
