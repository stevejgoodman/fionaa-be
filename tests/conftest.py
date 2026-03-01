import pytest_asyncio

from graph import build_graph


@pytest_asyncio.fixture(scope="session")
async def graph():
    """Build and return the compiled Fionaa graph once per test session."""
    return await build_graph()
