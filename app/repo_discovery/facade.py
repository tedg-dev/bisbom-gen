"""
RepoDiscovery facade — orchestrates the full repo discovery pipeline.
"""

from data_loader import DataLoader

from app.repo_discovery.github_client import GitHubClient
from app.repo_discovery.build_system_detector import BuildSystemDetector
from app.repo_discovery.dependency_analyzer import DependencyAnalyzer
from app.repo_discovery.binary_detector import BinaryDetector
from app.repo_discovery.build_step_generator import BuildStepGenerator
from app.repo_discovery.config_generator import ConfigGenerator


class RepoDiscovery:
    """Orchestrates the full repo discovery pipeline.

    Composes GitHubClient, BuildSystemDetector,
    DependencyAnalyzer, BinaryDetector,
    BuildStepGenerator, and ConfigGenerator.
    """

    def __init__(
        self,
        github=None,
        data_loader=None,
        detector=None,
        analyzer=None,
        binary_detector=None,
        step_generator=None,
        config_generator=None,
    ):
        self.github = github or GitHubClient()
        self.data = data_loader or DataLoader()

        indicators = self.data.load_build_systems()
        deps = self.data.load_dependencies()

        self.detector = detector or (
            BuildSystemDetector(indicators)
        )
        self.analyzer = analyzer or (
            DependencyAnalyzer(deps, self.github)
        )
        self.binary_detector = binary_detector or (
            BinaryDetector(self.github)
        )
        self.steps = step_generator or (
            BuildStepGenerator()
        )
        self.config = config_generator or (
            ConfigGenerator()
        )

    @staticmethod
    def build_description(
        repo_info, stats, repo_name
    ):
        """Build a description string from repo info."""
        desc_parts = []
        if repo_info.get("description"):
            desc = repo_info["description"]
            if len(desc) > 60:
                desc = desc[:57] + "..."
            desc_parts.append(desc)
        if stats:
            desc_parts.append(f"({stats})")
        return (
            " ".join(desc_parts)
            if desc_parts
            else repo_name
        )
