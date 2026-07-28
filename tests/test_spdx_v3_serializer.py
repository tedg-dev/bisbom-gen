"""Tests for app.spdx.v3.serializer — JSON-LD serialization."""

import pytest

from app.spdx.v3.model import (
    Agent,
    AgentType,
    Annotation,
    AnnotationType,
    CreationInfo,
    ExternalIdentifier,
    ExternalIdentifierType,
    Package,
    PrimaryPurpose,
    Relationship,
    RelationshipType,
    SpdxDocument,
    VexAffectedVulnAssessmentRelationship,
    VexJustificationType,
    VexNotAffectedVulnAssessmentRelationship,
    Vulnerability,
)
from app.spdx.v3.serializer import (
    serialize_document,
    _serialize_element,
    _to_json_key,
)


class TestFieldNameConversion:
    """snake_case → camelCase / SPDX key tests."""

    def test_spdx_id(self):
        assert _to_json_key("spdx_id") == "spdxId"

    def test_from_field(self):
        assert _to_json_key("from_") == "from"

    def test_creation_info(self):
        assert _to_json_key("creation_info") == (
            "creationInfo"
        )

    def test_security_fields(self):
        assert _to_json_key(
            "security_assessed_element"
        ) == "security_assessedElement"
        assert _to_json_key(
            "security_action_statement"
        ) == "security_actionStatement"
        assert _to_json_key(
            "security_justification_type"
        ) == "security_justificationType"

    def test_mechanical_fallback(self):
        assert _to_json_key("some_new_field") == (
            "someNewField"
        )


class TestSerializeElement:
    """Element-level serialization tests."""

    def test_creation_info(self):
        ci = CreationInfo(
            spec_version="3.0.1",
            created="2026-04-27T12:00:00Z",
            created_by=["urn:spdx:agent:test"],
        )
        result = _serialize_element(ci)
        assert result["type"] == "CreationInfo"
        assert result["specVersion"] == "3.0.1"
        assert result["createdBy"] == [
            "urn:spdx:agent:test"
        ]

    def test_package(self):
        pkg = Package(
            spdx_id="urn:spdx:pkg:test",
            name="test-pkg",
            package_version="1.0.0",
            primary_purpose=PrimaryPurpose.APPLICATION,
            copyright_text="NOASSERTION",
        )
        result = _serialize_element(pkg)
        assert result["type"] == "Package"
        assert result["spdxId"] == "urn:spdx:pkg:test"
        assert result["primaryPurpose"] == "application"
        assert result["packageVersion"] == "1.0.0"

    def test_package_omits_none_fields(self):
        pkg = Package(
            spdx_id="urn:spdx:pkg:minimal",
            name="minimal",
        )
        result = _serialize_element(pkg)
        assert "packageVersion" not in result
        assert "downloadLocation" not in result
        assert "homepage" not in result

    def test_package_omits_empty_lists(self):
        pkg = Package(
            spdx_id="urn:spdx:pkg:test",
            name="test",
            external_identifier=[],
        )
        result = _serialize_element(pkg)
        assert "externalIdentifier" not in result

    def test_agent(self):
        a = Agent(
            spdx_id="urn:spdx:agent:scanner",
            name="scanner",
            agent_type=AgentType.TOOL,
        )
        result = _serialize_element(a)
        assert result["type"] == "Agent"
        assert result["agentType"] == "tool"

    def test_vulnerability(self):
        vuln = Vulnerability(
            spdx_id="urn:spdx:vuln:CVE-2099-2001",
            summary="Test vuln",
            external_identifier=[ExternalIdentifier(
                external_identifier_type=(
                    ExternalIdentifierType.CVE
                ),
                identifier="CVE-2099-2001",
            )],
        )
        result = _serialize_element(vuln)
        assert result["type"] == "Vulnerability"
        ext = result["externalIdentifier"][0]
        assert ext["externalIdentifierType"] == "cve"
        assert ext["identifier"] == "CVE-2099-2001"

    def test_relationship(self):
        rel = Relationship(
            spdx_id="urn:spdx:rel:test",
            relationship_type=RelationshipType.CONTAINS,
            from_="urn:spdx:pkg:product",
            to=["urn:spdx:pkg:sub1"],
        )
        result = _serialize_element(rel)
        assert result["type"] == "Relationship"
        assert result["from"] == "urn:spdx:pkg:product"
        assert result["relationshipType"] == "contains"

    def test_vex_affected(self):
        rel = VexAffectedVulnAssessmentRelationship(
            spdx_id="urn:spdx:vex:test",
            from_="urn:spdx:vuln:CVE-2099-2001",
            to=["urn:spdx:pkg:sub"],
            security_assessed_element=(
                "urn:scanner:artifact:abc"
            ),
            security_action_statement="Patch it.",
            status_notes="Rule 4812.",
        )
        result = _serialize_element(rel)
        assert result["type"] == (
            "VexAffectedVulnAssessmentRelationship"
        )
        assert result["security_assessedElement"] == (
            "urn:scanner:artifact:abc"
        )
        assert result["security_actionStatement"] == (
            "Patch it."
        )
        assert result["statusNotes"] == "Rule 4812."

    def test_vex_not_affected(self):
        rel = VexNotAffectedVulnAssessmentRelationship(
            spdx_id="urn:spdx:vex:test",
            from_="urn:spdx:vuln:CVE-2099-2001",
            to=["urn:spdx:pkg:sub"],
            security_justification_type=(
                VexJustificationType
                .VULNERABLE_CODE_NOT_IN_EXECUTE_PATH
            ),
            security_impact_statement="Not reachable.",
        )
        result = _serialize_element(rel)
        assert result["type"] == (
            "VexNotAffectedVulnAssessmentRelationship"
        )
        assert result["security_justificationType"] == (
            "vulnerableCodeNotInExecutePath"
        )

    def test_annotation(self):
        ann = Annotation(
            spdx_id="urn:spdx:annotation:test",
            annotation_type=AnnotationType.OTHER,
            subject="urn:spdx:pkg:sub",
            content_type="application/json",
            statement='{"rule_id":4812}',
        )
        result = _serialize_element(ann)
        assert result["type"] == "Annotation"
        assert result["annotationType"] == "other"
        assert result["contentType"] == "application/json"

    def test_vex_affected_omits_none_assessed(self):
        """security_assessedElement omitted when None."""
        rel = VexAffectedVulnAssessmentRelationship(
            spdx_id="urn:spdx:vex:test",
            from_="urn:spdx:vuln:CVE-2099-2001",
            to=["urn:spdx:pkg:sub"],
            security_action_statement="Fix it.",
        )
        result = _serialize_element(rel)
        assert "security_assessedElement" not in result


class TestSerializeDocument:
    """Document-level serialization tests."""

    def test_empty_document(self):
        doc = SpdxDocument()
        result = serialize_document(doc)
        assert "@context" in result
        assert "3.0.1" in result["@context"]
        assert result["@graph"] == []

    def test_document_with_elements(self):
        doc = SpdxDocument(elements=[
            Package(
                spdx_id="urn:spdx:pkg:test",
                name="test",
            ),
            Vulnerability(
                spdx_id="urn:spdx:vuln:CVE-2099-2001",
            ),
        ])
        result = serialize_document(doc)
        assert len(result["@graph"]) == 2
        types = [e["type"] for e in result["@graph"]]
        assert "Package" in types
        assert "Vulnerability" in types

    def test_rejects_non_document(self):
        with pytest.raises(TypeError, match="SpdxDocument"):
            serialize_document({"not": "a document"})

    def test_nested_creation_info(self):
        """CreationInfo nested inside a Package."""
        ci = CreationInfo(
            created="2026-04-27T12:00:00Z",
            created_by=["urn:spdx:agent:test"],
        )
        doc = SpdxDocument(elements=[
            Package(
                spdx_id="urn:spdx:pkg:test",
                name="test",
                creation_info=ci,
            ),
        ])
        result = serialize_document(doc)
        pkg = result["@graph"][0]
        assert "creationInfo" in pkg
        assert pkg["creationInfo"]["type"] == (
            "CreationInfo"
        )
        assert pkg["creationInfo"]["created"] == (
            "2026-04-27T12:00:00Z"
        )
