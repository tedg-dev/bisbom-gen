"""
Pipeline package — Build interception and orchestration.

Provides the classes that compose the OmniBOR analysis workflow:
clone, dependency check, instrumented build, SPDX generation,
metadata collection, binary collection, documentation, and
the AnalysisPipeline facade that ties them together.
"""

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
from app.pipeline.facade import AnalysisPipeline
from app.pipeline.runners import (
    main,
    _run_c_cpp_pipeline,
    _run_rust_pipeline,
    _run_go_pipeline,
)

__all__ = [
    "DependencyValidator",
    "RepoCloner",
    "BomtraceBuilder",
    "SpdxGenerator",
    "SpdxValidator",
    "SyftGenerator",
    "MetadataCollector",
    "AdgSpdxStep",
    "BinaryCollector",
    "DocWriter",
    "AnalysisPipeline",
    "main",
    "_run_c_cpp_pipeline",
    "_run_rust_pipeline",
    "_run_go_pipeline",
]
