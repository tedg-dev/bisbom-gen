"""
SPDX 3.0 element dataclasses — Security Profile subset.

Covers the element types needed for attribution-scoped VEX:
  - Core: CreationInfo, Agent, ExternalIdentifier
  - Software: Package
  - Relationships: Relationship (base), VEX assessment subtypes
  - Security: Vulnerability, VEX assessment relationships
  - Annotation
  - SpdxDocument (Bundle wrapper)

Reference: SPDX 3.0.1 specification
https://spdx.github.io/spdx-spec/v3.0.1/

Field names use snake_case in Python; the serializer
converts to the camelCase JSON-LD representation.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# -----------------------------------------------------------
# Enums
# -----------------------------------------------------------

class AgentType(str, Enum):
    """SPDX 3 agent types."""
    PERSON = "person"
    ORGANIZATION = "organization"
    TOOL = "tool"


class PrimaryPurpose(str, Enum):
    """Subset of SPDX 3 primaryPurpose values used here."""
    APPLICATION = "application"
    LIBRARY = "library"
    FRAMEWORK = "framework"
    SOURCE = "source"
    OTHER = "other"


class RelationshipType(str, Enum):
    """SPDX 3 relationship types used in this module."""
    CONTAINS = "contains"
    DEPENDS_ON = "dependsOn"
    DESCRIBES = "describes"
    DYNAMIC_LINK = "dynamicLink"
    STATIC_LINK = "staticLink"
    BUILD_TOOL_OF = "buildToolOf"
    # VEX-specific
    AFFECTS = "affects"
    DOES_NOT_AFFECT = "doesNotAffect"
    FIXED_IN = "fixedIn"
    UNDER_INVESTIGATION_FOR = "underInvestigationFor"


class ExternalIdentifierType(str, Enum):
    """SPDX 3 ExternalIdentifier types."""
    CVE = "cve"
    CPE23 = "cpe23"
    PACKAGE_URL = "packageUrl"
    GITOID = "gitoid"
    SWHID = "swhid"


class AnnotationType(str, Enum):
    """SPDX 3 annotation types."""
    REVIEW = "review"
    OTHER = "other"


class VexJustificationType(str, Enum):
    """SPDX 3 VEX not-affected justification types."""
    COMPONENT_NOT_PRESENT = "componentNotPresent"
    VULNERABLE_CODE_NOT_PRESENT = "vulnerableCodeNotPresent"
    VULNERABLE_CODE_NOT_IN_EXECUTE_PATH = (
        "vulnerableCodeNotInExecutePath"
    )
    VULNERABLE_CODE_CANNOT_BE_CONTROLLED_BY_ADVERSARY = (
        "vulnerableCodeCannotBeControlledByAdversary"
    )
    INLINE_MITIGATIONS_ALREADY_EXIST = (
        "inlineMitigationsAlreadyExist"
    )


# -----------------------------------------------------------
# Core elements
# -----------------------------------------------------------

@dataclass
class CreationInfo:
    """SPDX 3 CreationInfo — attached to every element."""
    spec_version: str = "3.0.1"
    created: str = ""
    created_by: list[str] = field(default_factory=list)


@dataclass
class ExternalIdentifier:
    """SPDX 3 ExternalIdentifier."""
    external_identifier_type: ExternalIdentifierType = (
        ExternalIdentifierType.CVE
    )
    identifier: str = ""


@dataclass
class Agent:
    """SPDX 3 Agent — person, organization, or tool."""
    spdx_id: str = ""
    name: str = ""
    agent_type: Optional[AgentType] = None
    creation_info: Optional[CreationInfo] = None


# -----------------------------------------------------------
# Software elements
# -----------------------------------------------------------

@dataclass
class Package:
    """SPDX 3 Package element.

    Covers product, subsystem, and scanner-derived
    package representations.
    """
    spdx_id: str = ""
    name: str = ""
    package_version: Optional[str] = None
    primary_purpose: Optional[PrimaryPurpose] = None
    copyright_text: str = "NOASSERTION"
    download_location: Optional[str] = None
    homepage: Optional[str] = None
    package_url: Optional[str] = None
    external_identifier: list[ExternalIdentifier] = field(
        default_factory=list
    )
    comment: Optional[str] = None
    creation_info: Optional[CreationInfo] = None


# -----------------------------------------------------------
# Security elements
# -----------------------------------------------------------

@dataclass
class Vulnerability:
    """SPDX 3 Vulnerability element."""
    spdx_id: str = ""
    summary: Optional[str] = None
    external_identifier: list[ExternalIdentifier] = field(
        default_factory=list
    )
    creation_info: Optional[CreationInfo] = None


# -----------------------------------------------------------
# Relationships
# -----------------------------------------------------------

@dataclass
class Relationship:
    """SPDX 3 Relationship (base).

    ``from_`` maps to the JSON-LD ``from`` field.
    ``to`` is a list of target spdxIds.
    """
    spdx_id: str = ""
    relationship_type: RelationshipType = (
        RelationshipType.DESCRIBES
    )
    from_: str = ""
    to: list[str] = field(default_factory=list)
    creation_info: Optional[CreationInfo] = None


@dataclass
class VexAffectedVulnAssessmentRelationship:
    """SPDX 3 VexAffectedVulnAssessmentRelationship.

    Required: security_action_statement (remediation
    guidance per SPDX 3 Security Profile).
    """
    spdx_id: str = ""
    relationship_type: RelationshipType = (
        RelationshipType.AFFECTS
    )
    from_: str = ""
    to: list[str] = field(default_factory=list)
    security_assessed_element: Optional[str] = None
    security_action_statement: str = ""
    status_notes: Optional[str] = None
    published_time: Optional[str] = None
    creation_info: Optional[CreationInfo] = None


@dataclass
class VexNotAffectedVulnAssessmentRelationship:
    """SPDX 3 VexNotAffectedVulnAssessmentRelationship."""
    spdx_id: str = ""
    relationship_type: RelationshipType = (
        RelationshipType.DOES_NOT_AFFECT
    )
    from_: str = ""
    to: list[str] = field(default_factory=list)
    security_assessed_element: Optional[str] = None
    security_justification_type: Optional[
        VexJustificationType
    ] = None
    security_impact_statement: Optional[str] = None
    status_notes: Optional[str] = None
    published_time: Optional[str] = None
    creation_info: Optional[CreationInfo] = None


@dataclass
class VexFixedVulnAssessmentRelationship:
    """SPDX 3 VexFixedVulnAssessmentRelationship."""
    spdx_id: str = ""
    relationship_type: RelationshipType = (
        RelationshipType.FIXED_IN
    )
    from_: str = ""
    to: list[str] = field(default_factory=list)
    security_assessed_element: Optional[str] = None
    status_notes: Optional[str] = None
    published_time: Optional[str] = None
    creation_info: Optional[CreationInfo] = None


@dataclass
class VexUnderInvestigationVulnAssessmentRelationship:
    """SPDX 3 VexUnderInvestigationVulnAssessmentRelationship."""
    spdx_id: str = ""
    relationship_type: RelationshipType = (
        RelationshipType.UNDER_INVESTIGATION_FOR
    )
    from_: str = ""
    to: list[str] = field(default_factory=list)
    security_assessed_element: Optional[str] = None
    status_notes: Optional[str] = None
    published_time: Optional[str] = None
    creation_info: Optional[CreationInfo] = None


# -----------------------------------------------------------
# Annotation
# -----------------------------------------------------------

@dataclass
class Annotation:
    """SPDX 3 Annotation — carries attribution provenance."""
    spdx_id: str = ""
    annotation_type: AnnotationType = AnnotationType.OTHER
    subject: str = ""
    content_type: str = "application/json"
    statement: str = ""
    creation_info: Optional[CreationInfo] = None


# -----------------------------------------------------------
# Document wrapper
# -----------------------------------------------------------

# Union of all element types that can appear in @graph.
Element = (
    Agent
    | Package
    | Vulnerability
    | Relationship
    | VexAffectedVulnAssessmentRelationship
    | VexNotAffectedVulnAssessmentRelationship
    | VexFixedVulnAssessmentRelationship
    | VexUnderInvestigationVulnAssessmentRelationship
    | Annotation
)


@dataclass
class SpdxDocument:
    """SPDX 3 document — serialized as a JSON-LD @graph.

    The context URI references the official SPDX 3.0.1
    JSON-LD context published by the SPDX project.
    """
    context: str = (
        "https://spdx.org/rdf/3.0.1/spdx-context.jsonld"
    )
    elements: list[Element] = field(default_factory=list)
