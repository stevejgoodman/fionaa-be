"""Convenience helpers for building standalone agents outside the main graph.

For the full orchestration pipeline use :func:`graph.build_graph` instead.
This module exposes factory functions to instantiate individual agents for
testing or one-off evaluations.
"""

from __future__ import annotations

from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
from dotenv import load_dotenv
from langchain.chat_models import init_chat_model

from config import WORKSPACE
from prompts.agent_prompts import ELIGIBILITY_PROMPT, FINANCIAL_ASSESSMENT_PROMPT
from tools.filesystem import read_external_file

load_dotenv()

_file_system = FilesystemBackend(root_dir=str(WORKSPACE), virtual_mode=True)


def make_eligibility_agent():
    """Return a standalone eligibility-assessment deep agent."""
    return create_deep_agent(
        model=init_chat_model("claude-sonnet-4-5-20250929", temperature=0),
        tools=[read_external_file],
        backend=_file_system,
        system_prompt=ELIGIBILITY_PROMPT,
    )


def make_financial_assessment_agent():
    """Return a standalone financial-assessment deep agent."""
    return create_deep_agent(
        model=init_chat_model("claude-sonnet-4-5-20250929", temperature=0),
        tools=[read_external_file],
        backend=_file_system,
        system_prompt=FINANCIAL_ASSESSMENT_PROMPT,
    )
