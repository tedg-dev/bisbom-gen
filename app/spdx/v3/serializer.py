"""
SPDX 3.0 JSON-LD serializer.

Converts SpdxDocument and its elements into the SPDX 3.0.1
JSON-LD representation.  Field names are converted from
Python snake_case to the camelCase keys expected by the
SPDX 3 JSON Schema.

The output is a plain dict suitable for ``json.dumps()``.
"""

from dataclasses import fields as dc_fields
from enum import Enum

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

# -----------------------------------------------------------
# Type name mapping: dataclass → SPDX 3 JSON-LD ``type``
# -----------------------------------------------------------
_TYPE_MAP = {
    Agent: "Agent",
    Annotation: "Annotation",
    CreationInfo: "CreationInfo",
    ExternalIdentifier: "ExternalIdentifier",
    Package: "Package",
    Relationship: "Relationship",
    Vulnerability: "Vulnerability",
    VexAffectedVulnAssessmentRelationship: (
        "VexAffectedVulnAssessmentRelationship"
    ),
    VexNotAffectedVulnAssessmentRelationship: (
        "VexNotAffectedVulnAssessmentRelationship"
    ),
    VexFixedVulnAssessmentRelationship: (
        "VexFixedVulnAssessmentRelationship"
    ),
    VexUnderInvestigationVulnAssessmentRelationship: (
        "VexUnderInvestigationVulnAssessmentRelationship"
    ),
}

# -----------------------------------------------------------
# snake_case → camelCase conversion
# -----------------------------------------------------------
# Explicit overrides where mechanical conversion is wrong.
_FIELD_OVERRIDES = {
    "spdx_id": "spdxId",
    "spec_version": "specVersion",
    "created_by": "createdBy",
    "from_": "from",
    "agent_type": "agentType",
    "creation_info": "creationInfo",
    "external_identifier_type": "externalIdentifierType",
    "external_identifier": "externalIdentifier",
    "package_version": "packageVersion",
    "primary_purpose": "primaryPurpose",
    "copyright_text": "copyrightText",
    "download_location": "downloadLocation",
    "package_url": "packageUrl",
    "annotation_type": "annotationType",
    "content_type": "contentType",
    "relationship_type": "relationshipType",
    "security_assessed_element": "security_assessedElement",
    "security_action_statement": (
        "security_actionStatement"
    ),
    "security_justification_type": (
        "security_justificationType"
    ),
    "security_impact_statement": (
        "security_impactStatement"
    ),
    "status_notes": "statusNotes",
    "published_time": "publishedTime",
}


def _to_json_key(field_name):
    """Convert a Python field name to its JSON-LD key."""
    if field_name in _FIELD_OVERRIDES:
        return _FIELD_OVERRIDES[field_name]
    # Mechanical snake_case → camelCase fallback
    parts = field_name.split("_")
    return parts[0] + "".join(
        p.capitalize() for p in parts[1:]
    )


# -----------------------------------------------------------
# Element serialization
# -----------------------------------------------------------

def _serialize_value(value):
    """Recursively serialize a value for JSON output."""
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "__dataclass_fields__"):
        return _serialize_element(value)
    if isinstance(value, list):
        return [_serialize_value(v) for v in value]
    return value


def _serialize_element(element):
    """Serialize a single dataclass element to a dict."""
    result = {}

    # Add ``type`` for elements that have a type mapping
    element_type = type(element)
    if element_type in _TYPE_MAP:
        result["type"] = _TYPE_MAP[element_type]

    for f in dc_fields(element):
        value = getattr(element, f.name)
        if value is None:
            continue
        if isinstance(value, list) and len(value) == 0:
            continue
        if isinstance(value, str) and value == "":
            continue

        key = _to_json_key(f.name)
        result[key] = _serialize_value(value)

    return result


# -----------------------------------------------------------
# Document serialization
# -----------------------------------------------------------

def serialize_document(doc):
    """Serialize an SpdxDocument to a JSON-LD dict.

    Args:
        doc: SpdxDocument instance.

    Returns:
        dict suitable for ``json.dumps(doc, indent=2)``.
    """
    if not isinstance(doc, SpdxDocument):
        raise TypeError(
            f"Expected SpdxDocument, got {type(doc)}"
        )
    return {
        "@context": doc.context,
        "@graph": [
            _serialize_element(e) for e in doc.elements
        ],
    }
