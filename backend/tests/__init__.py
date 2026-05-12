"""
Tests module initialization.
"""

# Test configuration
import pytest

@pytest.fixture
def anyio_backend():
    return "asyncio"
