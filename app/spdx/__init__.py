"""
SPDX package — ADG-to-SPDX generation pipeline.

Provides classes for parsing OmniBOR ADG data, resolving
components, detecting vendored library versions, emitting
SPDX 2.3 JSON documents, and the AdgSpdxGenerator facade.
"""

from app.spdx.parser import AdgParser
from app.spdx.resolver import ComponentResolver
from app.spdx.version_detector import VendoredVersionDetector
from app.spdx.emitter import SpdxEmitter
from app.spdx.generator import AdgSpdxGenerator
from app.spdx.cli import main

__all__ = [
    "AdgParser",
    "ComponentResolver",
    "VendoredVersionDetector",
    "SpdxEmitter",
    "AdgSpdxGenerator",
    "main",
]
