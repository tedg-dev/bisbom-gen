"""Shared pytest configuration and custom markers."""

import shutil


def pytest_configure(config):
    """Register custom markers for integration tests."""
    config.addinivalue_line(
        "markers",
        "integration: marks tests that require real OS "
        "package manager binaries (deselect with '-m "
        "\"not integration\"')",
    )
    config.addinivalue_line(
        "markers",
        "requires_dpkg: marks tests that need dpkg/dpkg-query",
    )
    config.addinivalue_line(
        "markers",
        "requires_rpm: marks tests that need rpm",
    )
    config.addinivalue_line(
        "markers",
        "requires_apk: marks tests that need apk",
    )


def has_binary(name: str) -> bool:
    """Check if a binary is available on PATH."""
    return shutil.which(name) is not None
