"""Subagent configuration dicts for the Fionaa deep-agent orchestrator.

Each dict is passed directly to ``create_deep_agent`` / ``create_agent`` as
the ``subagents`` list entry.  The ``tools`` field is populated at runtime
(inside ``build_graph``) once the async MCP clients have been initialised.
"""

from prompts.agent_prompts import (
    COMPANIES_HOUSE_PROMPT,
    ELIGIBILITY_PROMPT,
    FINANCIAL_ASSESSMENT_PROMPT,
    INTERNET_SEARCH_PROMPT,
    LINKED_IN_PROMPT,
)
from tools.filesystem import read_external_file
from tools.internet_search import internet_search


def make_subagents(
    li_tools: list,
    ch_tools: list,
    run_without_internet_search: bool = False,
) -> list[dict]:
    """Build and return the list of subagent config dicts.

    Args:
        li_tools: LinkedIn MCP tool list (from ``get_linkedin_tools()``).
        ch_tools: Companies House MCP tool list (from ``get_companies_house_tools()``).
        run_without_internet_search: If True, return only eligibility and financial
            assessment subagents (no LinkedIn, Companies House, or internet search).

    Returns:
        List of subagent configuration dicts ready to pass to ``create_deep_agent``.
    """
    eligibility_subagent = {
        "name": "eligibility-assessment-agent",
        "description": (
            "Use this agent to check whether the applicant meets the basic "
            "eligibility criteria for the requested loan type, using loan policy "
            "documents and the applicant's submitted financial documents."
        ),
        "model": "claude-haiku-4-5-20251001",
        "tools": [read_external_file],
        "system_prompt": ELIGIBILITY_PROMPT,
    }

    financial_assessment_subagent = {
        "name": "financial-assessment-agent",
        "description": (
            "Use this agent to review the customer's submitted financial documents "
            "(bank statements, annual reports) and verify they meet eligibility criteria."
        ),
        "model": "claude-haiku-4-5-20251001",
        "tools": [read_external_file],
        "system_prompt": FINANCIAL_ASSESSMENT_PROMPT,
    }

    linkedin_subagent = {
        "name": "linkedin-search-agent",
        "description": (
            "Use this agent to search LinkedIn for a company page or employee "
            "profiles connected to the applicant's business."
        ),
        "model": "claude-haiku-4-5-20251001",
        "tools": [read_external_file] + li_tools,
        "system_prompt": LINKED_IN_PROMPT,
    }

    companies_house_subagent = {
        "name": "companies-house-search-agent",
        "description": (
            "Use this agent to search the UK register of incorporated companies "
            "(Companies House) to verify company status, directors, and filings."
        ),
        "model": "claude-haiku-4-5-20251001",
        "tools": [read_external_file] + ch_tools,
        "system_prompt": COMPANIES_HOUSE_PROMPT,
    }

    internet_subagent = {
        "name": "internet-search-agent",
        "description": (
            "Use this agent to search the web for a company website or news "
            "stories about the applicant's business."
        ),
        "model": "claude-haiku-4-5-20251001",
        "tools": [read_external_file, internet_search],
        "system_prompt": INTERNET_SEARCH_PROMPT,
    }

    if run_without_internet_search:
        return [eligibility_subagent] # , financial_assessment_subagent]

    return [
        eligibility_subagent,
        financial_assessment_subagent,
        linkedin_subagent,
        companies_house_subagent,
        internet_subagent,
    ]
