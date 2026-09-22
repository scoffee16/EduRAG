from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from edurage.main import create_app


@pytest.fixture
def client() -> Iterator[TestClient]:
    """Provide a TestClient for a freshly created EduRAG application."""

    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def project_root() -> Path:
    """Return the repository root."""

    return Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def configs_dir(project_root: Path) -> Path:
    """Return the repository's configuration directory."""

    return project_root / "configs"
