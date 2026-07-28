"""
SPDX 3.0 partial support — Security Profile and VEX.

Provides element dataclasses, JSON-LD serialization,
VEX document authoring, and minimal VEX parsing for
attribution-scoped vulnerability dispositioning.

This package does NOT replace the SPDX 2.3 emitter.
It adds a complementary VEX output that references
elements from existing 2.3 SBOMs.
"""

from app.spdx.v3.model import (
    Agent,
    Annotation,
    CreationInfo,
    ExternalIdentifier,
    Package,
    Relationship,
    SpdxDocument,
    VexAffectedVulnAssessmentRelationship,
    VexFixedVulnAssessmentRelationship,
    VexNotAffectedVulnAssessmentRelationship,
    VexUnderInvestigationVulnAssessmentRelationship,
    Vulnerability,
)
from app.spdx.v3.serializer import serialize_document

__all__ = [
    "Agent",
    "Annotation",
    "CreationInfo",
    "ExternalIdentifier",
    "Package",
    "Relationship",
    "SpdxDocument",
    "VexAffectedVulnAssessmentRelationship",
    "VexFixedVulnAssessmentRelationship",
    "VexNotAffectedVulnAssessmentRelationship",
    "VexUnderInvestigationVulnAssessmentRelationship",
    "Vulnerability",
    "serialize_document",
]
