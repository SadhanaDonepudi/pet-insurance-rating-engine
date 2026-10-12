"""Pytest fixtures: build a fresh pipeline database per test session.

The suite validates the real pipeline output (not mocks): the fixture runs
ReleasePipeline into a tmp directory, so every assertion below is checked
against a from-scratch, seeded, reproducible run.
"""

import sqlite3
from pathlib import Path

import pytest

from src.release_pipeline import (
    PREMIUM_MAX,
    PREMIUM_MIN,
    QUOTES_PER_VERSION,
    ReleasePipeline,
)


@pytest.fixture(scope="session")
def pipeline_run(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("pipeline")
    pipe = ReleasePipeline(str(tmp / "test.db"),
                           str(tmp / "summaries"))
    report = pipe.run()
    conn = pipe.conn
    yield {"conn": conn, "report": report,
           "summaries_dir": tmp / "summaries", "db_path": tmp / "test.db"}
    conn.close()


@pytest.fixture(scope="session")
def db(pipeline_run):
    return pipeline_run["conn"]
