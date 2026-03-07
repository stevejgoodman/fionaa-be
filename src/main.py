"""Entry point for the Fionaa loan application Deep Agents assessment pipeline.

If ran independently of the email trigger

Otherwise its uv run python src/gmail/ingest.py --email my.email@gmail.com --minutes-since 60



"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import os

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage

from graph import build_graph
from application_forms import steve_application_str, synthesia_application_str

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


async def run_assessment(
    case_number: str,
    application_text: str,
    thread_id: str | None = None,
    run_without_ocr: bool = True,
    run_without_internet_search: bool = True,
    graph=None,
) -> str:
    """Run the full loan assessment pipeline for a single case.

    Args:
        case_number:      Unique case ID — must match a sub-directory under
                          ``data/`` that contains the applicant's documents.
        application_text: Free-text application form submitted by the applicant.
        thread_id:        LangGraph conversation thread ID for checkpointing.
                          Defaults to ``case_number``.
        run_without_ocr:  If True, skip the OCR startup node.
        run_without_internet_search: If True, use only eligibility and financial
            subagents (and no LinkedIn/CH/internet tools). Requires building the
            graph with this flag when graph is not provided.
        graph:            Compiled graph to use. If None, builds a new graph
                          (must be called from an async context with a running
                          event loop).

    Returns:
        The final assessment report as a string.
    """
    if thread_id is None:
        thread_id = case_number

    if graph is None:
        graph = await build_graph(
            run_without_internet_search=run_without_internet_search,
        )

    config = {
        "configurable": {
            "thread_id": thread_id,
            "case_number": case_number,
            "recursion_limit": 10,
            "run_without_ocr": run_without_ocr,
        }
    }

    logger.info("Running assessment for case: %s", case_number)
    result = await graph.ainvoke(
        {
            "messages": [HumanMessage(content=application_text)],
            "case_number": case_number,
        },
        config=config,
    )

    final_message = result["messages"][-1].content
    return final_message


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fionaa — Loan Application Assessment"
    )
    parser.add_argument(
        "--case",
        default="SteveGoodman",
        help="Case number / sub-directory name under data/  (default: stevejgoodman@gmail.com)",
    )
    parser.add_argument(
        "--application",
        default=None,
        help="Application text.  If omitted, the built-in demo application is used.",
    )
    parser.add_argument(
        "--thread",
        default=None,
        help="LangGraph thread ID for checkpointing (default: same as --case).",
    )
    return parser.parse_args()


async def _main() -> None:
    args = _parse_args()
    application_text = args.application or steve_application_str
    run_without_ocr = os.environ.get("RUN_WITHOUT_OCR", "").lower() in (
        "1",
        "true",
        "yes",
    )
    run_without_internet_search = os.environ.get(
        "RUN_WITHOUT_INTERNET_SEARCH", ""
    ).lower() in ("1", "true", "yes")

    # Build graph in this event loop so store/checkpointer use the same loop.
    graph = await build_graph(
        run_without_internet_search=True,
    )
    report = await run_assessment(
        case_number='Synthesia',  # args.case,
        application_text=synthesia_application_str,
        thread_id='Synthesia', #args.thread,
        run_without_ocr=True,
        run_without_internet_search=True,
        graph=graph,
    )

    print("\n" + "=" * 72)
    print("ASSESSMENT REPORT")
    print("=" * 72)
    print(report)


if __name__ == "__main__":
    asyncio.run(_main())
