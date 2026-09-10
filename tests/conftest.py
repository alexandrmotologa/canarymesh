"""Pytest fixtures and test configuration."""
import pytest


@pytest.fixture
def mock_timestamp():
    """Returns a deterministic reference timestamp."""
    return 1700000000.0
