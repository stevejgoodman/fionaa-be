"""PGVectorStore setup and helpers for ADE document chunks.

Run this module directly uv run python src/vector_store.py to create the ade_documents table in Postgres. 
 the table is only created if it does not already exist.
"""

import asyncio
import logging

from langchain_openai import OpenAIEmbeddings
from langchain_postgres import PGEngine, PGVectorStore
from langchain_postgres.v2.engine import Column
from sqlalchemy.ext.asyncio import create_async_engine

from config import (
    EMBEDDING_MODEL,
    PG_DB,
    PG_HOST,
    PG_PASSWORD,
    PG_PORT,
    PG_TABLE,
    PG_USER,
    VECTOR_SIZE,
)

logger = logging.getLogger(__name__)


def _connection_string() -> str:
    return (
        f"postgresql+asyncpg://{PG_USER}:{PG_PASSWORD}@{PG_HOST}:{PG_PORT}/{PG_DB}"
    )


async def init_table() -> None:
    """Create the ade_documents table with filterable metadata columns.

    Safe to run when the table already exists — raises no error.
    """
    engine = create_async_engine(_connection_string())
    pg_engine = PGEngine.from_engine(engine=engine)

    await pg_engine.ainit_vectorstore_table(
        table_name=PG_TABLE,
        vector_size=VECTOR_SIZE,
        metadata_columns=[
            Column(name="case_number", data_type="VARCHAR", nullable=False),
            Column(name="chunk_type",  data_type="VARCHAR", nullable=True),
            Column(name="page_num",    data_type="INTEGER",  nullable=True),
        ],
        overwrite_existing=False,
    )
    logger.info("Table '%s' ready.", PG_TABLE)


async def get_store() -> PGVectorStore:
    """Return a PGVectorStore connected to the ade_documents table."""
    engine = create_async_engine(_connection_string())
    pg_engine = PGEngine.from_engine(engine=engine)
    embeddings = OpenAIEmbeddings(model=EMBEDDING_MODEL)

    return await PGVectorStore.create(
        engine=pg_engine,
        table_name=PG_TABLE,
        embedding_service=embeddings,
        metadata_columns=["case_number", "chunk_type", "page_num"],
    )


def get_retriever(store: PGVectorStore, case_number: str, k: int = 10):
    """Return a retriever scoped to a single case_number."""
    return store.as_retriever(
        search_kwargs={"filter": {"case_number": case_number}, "k": k}
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s - %(message)s")
    asyncio.run(init_table())
    print("Done — table is ready.")
