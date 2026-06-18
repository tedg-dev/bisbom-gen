"""
Binary detection — detects output binary paths from Makefiles.
"""

import re

from app.repo_discovery.github_client import GitHubClient


class BinaryDetector:
    """Detects output binary paths from Makefiles and repo structure."""

    def __init__(self, github=None):
        self.github = github or GitHubClient()

    def detect(
        self, full_name, repo_name,
        build_system, files,
    ):
        """Guess the output binary paths."""
        binaries = []

        makefiles = [
            "Makefile.am", "src/Makefile.am",
        ]
        for mf in makefiles:
            if mf in files:
                content = (
                    self.github.get_file_content(
                        full_name, mf, "HEAD"
                    )
                )
                if content:
                    binaries.extend(
                        self._parse_makefile(content)
                    )

        if not binaries:
            binaries = self._fallback(
                repo_name, files
            )

        return binaries

    @staticmethod
    def _parse_makefile(content):
        """Extract binaries from Makefile.am content."""
        binaries = []
        pat_bin = r'bin_PROGRAMS\s*[+=]\s*(.+)'
        for m in re.findall(pat_bin, content):
            for prog in m.split():
                binaries.append(prog.strip())

        pat_lib = r'lib_LTLIBRARIES\s*[+=]\s*(.+)'
        for m in re.findall(pat_lib, content):
            for lib in m.split():
                lib_name = lib.strip().replace(
                    ".la", ".so"
                )
                binaries.append(
                    f"lib/.libs/{lib_name}"
                )
        return binaries

    @staticmethod
    def _fallback(repo_name, files):
        """Fallback binary detection from repo structure."""
        if any(f.startswith("src/") for f in files):
            return [
                f"src/.libs/{repo_name}",
                f"src/{repo_name}",
            ]
        return [repo_name]
