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


@pytest.fixture
def sample_pdf_path(tmp_path: Path) -> Path:
    """Create and return the deterministic sample PDF path."""

    from tests.fixtures.sample_pdf import make_sample_pdf

    return make_sample_pdf(tmp_path / "sample.pdf")
