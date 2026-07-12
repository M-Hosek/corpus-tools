from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def sample_pdf() -> Path:
    p = FIXTURES / "sample_chunk.pdf"
    if not p.exists():
        pytest.skip("real-PDF fixture not present")
    return p
