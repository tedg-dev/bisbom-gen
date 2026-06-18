"""
Dependency analysis — inspects build config files for dependency flags.
"""

from app.repo_discovery.github_client import GitHubClient


class DependencyAnalyzer:
    """Inspects build config files to detect optional dependencies."""

    _CONFIG_FILES = {
        "autoconf": (
            "configure.ac", "configure_flag"
        ),
        "cmake": (
            "CMakeLists.txt", "cmake_flag"
        ),
        "configure-only": (
            "configure", "configure_flag"
        ),
    }

    def __init__(self, known_deps=None, github=None):
        self.known_deps = known_deps or {}
        self.github = github or GitHubClient()

    def analyze(
        self, full_name, branch,
        build_system, files,
    ):
        """Detect configure flags and apt packages.

        Returns (flags, apt_packages) tuple.
        """
        config = self._CONFIG_FILES.get(
            build_system
        )
        if config is None:
            return [], []

        config_file, flag_key = config
        if config_file not in files:
            return [], []

        content = self.github.get_file_content(
            full_name, config_file, branch
        )
        if not content:
            return [], []

        flags = []
        apt_packages = []
        content_lower = content.lower()

        for dep_name, dep_info in (
            self.known_deps.items()
        ):
            flag = dep_info.get(flag_key, "")
            if (
                dep_name.lower() in content_lower
                and flag
            ):
                flags.append(flag)
                apt_packages.extend(
                    dep_info.get("apt_packages", [])
                )

        return flags, list(set(apt_packages))
