"""Integration tests for the Fionaa assessment graph."""

from langchain_core.messages import HumanMessage

# Minimal loan application email used across tests
_EMAIL_INPUT = {
    "from": "JohnSmith",
    "to": "fionaa@lender.com",
    "subject": "Business Loan Application — £50,000",
    "body": (
        "Dear Fionaa, I am applying for a £50,000 unsecured business loan "
        "for Smith Consulting Ltd, registered in England and Wales. "
        "The company has been trading for 3 years with annual revenues of £200,000 "
        "and net profit of £40,000. Funds will be used to hire two additional "
        "consultants to meet growing demand. I have no adverse credit history. "
        "Please assess my application."
    ),
    "id": "test-email-001",
}


async def test_run_without_ocr_returns_text(graph):
    """Graph should produce a non-empty text response when OCR is skipped."""
    result = await graph.ainvoke(
        {
            "email_input": _EMAIL_INPUT,
            "case_number": "JohnSmith",
            "messages": [HumanMessage(content=_EMAIL_INPUT["body"])],
        },
        config={
            "configurable": {
                "thread_id": "test-run-without-ocr-001",
                "run_without_ocr": True,
            }
        },
    )

    messages = result.get("messages", [])
    assert messages, "Graph should return at least one message"

    final = messages[-1]
    content = getattr(final, "content", "")
    if isinstance(content, list):
        content = " ".join(
            b.get("text", "") if isinstance(b, dict) else str(b) for b in content
        )

    assert isinstance(content, str), "Final message content should be a string"
    assert content.strip(), "Final message should not be empty"
