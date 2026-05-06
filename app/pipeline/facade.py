"""
AnalysisPipeline facade for OmniBOR Analysis.

Composes all pipeline components into a single orchestration class.
"""

from app.runner import CommandRunner
from app.pipeline.validator import DependencyValidator
from app.pipeline.cloner import RepoCloner
from app.pipeline.builder import BomtraceBuilder
from app.pipeline.spdx_generator import SpdxGenerator
from app.pipeline.spdx_validator import SpdxValidator
from app.pipeline.syft import SyftGenerator
from app.pipeline.metadata_collector import MetadataCollector
from app.pipeline.adg_spdx import AdgSpdxStep
from app.pipeline.binary_collector import BinaryCollector
from app.pipeline.doc_writer import DocWriter


class AnalysisPipeline:
    """Orchestrates the full OmniBOR analysis workflow.

    Composes CommandRunner, RepoCloner,
    BomtraceBuilder, SpdxGenerator, MetadataCollector,
    AdgSpdxStep, SpdxValidator, SyftGenerator,
    BinaryCollector, and DocWriter.
    """

    def __init__(
        self,
        runner=None,
        validator=None,
        cloner=None,
        builder=None,
        spdx_gen=None,
        metadata_collector=None,
        adg_spdx=None,
        spdx_validator=None,
        syft_gen=None,
        binary_collector=None,
        doc_writer=None,
    ):
        self.runner = runner or CommandRunner()
        self.validator = (
            validator
            or DependencyValidator()
        )
        self.cloner = cloner or RepoCloner(
            self.runner
        )
        self.builder = builder or BomtraceBuilder(
            self.runner
        )
        self.spdx_gen = spdx_gen or SpdxGenerator(
            self.runner
        )
        self.metadata_collector = (
            metadata_collector
            or MetadataCollector(self.runner)
        )
        self.adg_spdx = (
            adg_spdx or AdgSpdxStep()
        )
        self.spdx_validator = (
            spdx_validator or SpdxValidator()
        )
        self.syft_gen = syft_gen or SyftGenerator(
            self.runner
        )
        self.binary_collector = (
            binary_collector or BinaryCollector()
        )
        self.docs = doc_writer or DocWriter()

    @staticmethod
    def list_repos(config):
        """List available repositories from config."""
        print("\nAvailable repositories:\n")
        for name, cfg in config["repos"].items():
            desc = cfg.get(
                "description", "No description"
            )
            print(f"  {name:12s}  {desc}")
            print(f"               {cfg['url']}")
            print()
