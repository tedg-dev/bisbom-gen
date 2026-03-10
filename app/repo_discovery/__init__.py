"""
Repo discovery package — smart repo detection and config generation.

Provides classes for searching GitHub, detecting build systems,
analyzing dependencies, identifying output binaries, generating
build steps, and writing config.yaml entries.
"""

from app.repo_discovery.github_client import GitHubClient
from app.repo_discovery.build_system_detector import BuildSystemDetector
from app.repo_discovery.dependency_analyzer import DependencyAnalyzer
from app.repo_discovery.binary_detector import BinaryDetector
from app.repo_discovery.build_step_generator import BuildStepGenerator
from app.repo_discovery.config_generator import ConfigGenerator
from app.repo_discovery.facade import RepoDiscovery
from app.repo_discovery.cli import main

__all__ = [
    "GitHubClient",
    "BuildSystemDetector",
    "DependencyAnalyzer",
    "BinaryDetector",
    "BuildStepGenerator",
    "ConfigGenerator",
    "RepoDiscovery",
    "main",
]
