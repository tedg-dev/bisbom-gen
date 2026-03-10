"""
Build system detection from repository file lists.
"""


class BuildSystemDetector:
    """Detects the build system from a repository's file list."""

    def __init__(self, indicators=None):
        self.indicators = indicators or []

    def detect(self, files):
        """Return the build system name for the given file list."""
        for indicator, system in self.indicators:
            if indicator in files:
                return system
        return "unknown"

