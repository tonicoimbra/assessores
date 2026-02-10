"""Shared test fixtures for all Sprint 1 tests."""

from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_recurso_path() -> str:
    """Path to a valid PDF with recurso text."""
    return str(FIXTURES_DIR / "sample_recurso.pdf")


@pytest.fixture
def sample_minimal_path() -> str:
    """Path to a PDF with very little text (triggers fallback)."""
    return str(FIXTURES_DIR / "sample_minimal.pdf")


@pytest.fixture
def corrupted_pdf_path() -> str:
    """Path to a corrupted (invalid) PDF file."""
    return str(FIXTURES_DIR / "corrupted.pdf")


@pytest.fixture
def not_a_pdf_path() -> str:
    """Path to a .txt file (invalid format)."""
    return str(FIXTURES_DIR / "not_a_pdf.txt")


@pytest.fixture
def nonexistent_path() -> str:
    """Path to a file that does not exist."""
    return str(FIXTURES_DIR / "does_not_exist.pdf")
