"""Tests for app.spdx.v3.model — SPDX 3 element dataclasses."""

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
    VexFixedVulnAssessmentRelationship,
    VexJustificationType,
    VexNotAffectedVulnAssessmentRelationship,
    VexUnderInvestigationVulnAssessmentRelationship,
    Vulnerability,
)


class TestCreationInfo:
    """CreationInfo dataclass tests."""

    def test_defaults(self):
        ci = CreationInfo()
        assert ci.spec_version == "3.0.1"
        assert ci.created == ""
        assert ci.created_by == []

    def test_custom_values(self):
        ci = CreationInfo(
            spec_version="3.0.1",
            created="2026-04-27T12:00:00Z",
            created_by=["urn:spdx:agent:test"],
        )
        assert ci.created == "2026-04-27T12:00:00Z"
        assert len(ci.created_by) == 1


class TestExternalIdentifier:
    """ExternalIdentifier dataclass tests."""

    def test_cve(self):
        ext = ExternalIdentifier(
            external_identifier_type=(
                ExternalIdentifierType.CVE
            ),
            identifier="CVE-2099-2001",
        )
        assert ext.identifier == "CVE-2099-2001"
        assert ext.external_identifier_type == (
            ExternalIdentifierType.CVE
        )

    def test_purl(self):
        ext = ExternalIdentifier(
            external_identifier_type=(
                ExternalIdentifierType.PACKAGE_URL
            ),
            identifier="pkg:generic/curl@7.81.0",
        )
        assert ext.external_identifier_type.value == (
            "packageUrl"
        )


class TestAgent:
    """Agent dataclass tests."""

    def test_tool_agent(self):
        a = Agent(
            spdx_id="urn:spdx:agent:scanner-x",
            name="scanner-x",
            agent_type=AgentType.TOOL,
        )
        assert a.agent_type == AgentType.TOOL
        assert a.agent_type.value == "tool"

    def test_organization_agent(self):
        a = Agent(
            spdx_id="urn:spdx:agent:sec-team",
            name="Security Team",
            agent_type=AgentType.ORGANIZATION,
        )
        assert a.agent_type.value == "organization"


class TestPackage:
    """Package dataclass tests."""

    def test_product_package(self):
        pkg = Package(
            spdx_id="urn:spdx:pkg:application-x",
            name="application-X",
            package_version="1.0.0",
            primary_purpose=PrimaryPurpose.APPLICATION,
        )
        assert pkg.name == "application-X"
        assert pkg.copyright_text == "NOASSERTION"

    def test_subsystem_package(self):
        pkg = Package(
            spdx_id=(
                "urn:spdx:pkg:application-x"
                ":subsystem:xe-sdk"
            ),
            name="application-X XE SDK subsystem",
        )
        assert ":subsystem:" in pkg.spdx_id

    def test_external_identifiers(self):
        pkg = Package(
            spdx_id="urn:spdx:pkg:test",
            name="test",
            external_identifier=[
                ExternalIdentifier(
                    external_identifier_type=(
                        ExternalIdentifierType.PACKAGE_URL
                    ),
                    identifier="pkg:generic/test@1.0",
                ),
            ],
        )
        assert len(pkg.external_identifier) == 1


class TestVulnerability:
    """Vulnerability dataclass tests."""

    def test_with_cve(self):
        vuln = Vulnerability(
            spdx_id="urn:spdx:vuln:CVE-2099-2001",
            summary="Test vulnerability",
            external_identifier=[
                ExternalIdentifier(
                    external_identifier_type=(
                        ExternalIdentifierType.CVE
                    ),
                    identifier="CVE-2099-2001",
                ),
            ],
        )
        assert vuln.summary == "Test vulnerability"
        assert len(vuln.external_identifier) == 1


class TestRelationship:
    """Relationship dataclass tests."""

    def test_contains(self):
        rel = Relationship(
            spdx_id="urn:spdx:rel:test",
            relationship_type=RelationshipType.CONTAINS,
            from_="urn:spdx:pkg:product",
            to=["urn:spdx:pkg:sub1", "urn:spdx:pkg:sub2"],
        )
        assert rel.relationship_type.value == "contains"
        assert len(rel.to) == 2

    def test_from_field_name(self):
        """Verify from_ is the Python field name."""
        rel = Relationship(from_="urn:spdx:pkg:a")
        assert rel.from_ == "urn:spdx:pkg:a"


class TestVexRelationships:
    """VEX assessment relationship tests."""

    def test_affected_defaults(self):
        rel = VexAffectedVulnAssessmentRelationship()
        assert rel.relationship_type == (
            RelationshipType.AFFECTS
        )
        assert rel.security_action_statement == ""

    def test_affected_full(self):
        rel = VexAffectedVulnAssessmentRelationship(
            spdx_id="urn:spdx:vex:test",
            from_="urn:spdx:vuln:CVE-2099-2001",
            to=["urn:spdx:pkg:sub"],
            security_assessed_element=(
                "urn:scanner-x:artifact:abc"
            ),
            security_action_statement="Patch it.",
            status_notes="Rule 4812.",
            published_time="2026-04-27T12:35:00Z",
        )
        assert rel.security_action_statement == "Patch it."
        assert rel.security_assessed_element is not None

    def test_not_affected(self):
        rel = VexNotAffectedVulnAssessmentRelationship(
            security_justification_type=(
                VexJustificationType
                .VULNERABLE_CODE_NOT_IN_EXECUTE_PATH
            ),
            security_impact_statement=(
                "Code path not reachable."
            ),
        )
        assert rel.relationship_type == (
            RelationshipType.DOES_NOT_AFFECT
        )
        assert rel.security_justification_type.value == (
            "vulnerableCodeNotInExecutePath"
        )

    def test_fixed(self):
        rel = VexFixedVulnAssessmentRelationship(
            from_="urn:spdx:vuln:CVE-2099-2001",
            to=["urn:spdx:pkg:sub"],
        )
        assert rel.relationship_type == (
            RelationshipType.FIXED_IN
        )

    def test_under_investigation(self):
        rel = VexUnderInvestigationVulnAssessmentRelationship(
            from_="urn:spdx:vuln:CVE-2099-2001",
            to=["urn:spdx:pkg:sub"],
        )
        assert rel.relationship_type == (
            RelationshipType.UNDER_INVESTIGATION_FOR
        )


class TestAnnotation:
    """Annotation dataclass tests."""

    def test_defaults(self):
        ann = Annotation()
        assert ann.annotation_type == AnnotationType.OTHER
        assert ann.content_type == "application/json"

    def test_attribution_annotation(self):
        ann = Annotation(
            spdx_id="urn:spdx:annotation:test",
            subject="urn:spdx:pkg:sub",
            statement='{"attribution_rule_id":4812}',
        )
        assert "4812" in ann.statement


class TestSpdxDocument:
    """SpdxDocument wrapper tests."""

    def test_defaults(self):
        doc = SpdxDocument()
        assert "3.0.1" in doc.context
        assert doc.elements == []

    def test_with_elements(self):
        doc = SpdxDocument(elements=[
            Package(
                spdx_id="urn:spdx:pkg:test",
                name="test",
            ),
        ])
        assert len(doc.elements) == 1


class TestEnums:
    """Enum value correctness tests."""

    def test_relationship_types(self):
        assert RelationshipType.AFFECTS.value == "affects"
        assert RelationshipType.DOES_NOT_AFFECT.value == (
            "doesNotAffect"
        )
        assert RelationshipType.FIXED_IN.value == "fixedIn"
        assert (
            RelationshipType.UNDER_INVESTIGATION_FOR.value
            == "underInvestigationFor"
        )

    def test_justification_types(self):
        assert (
            VexJustificationType.COMPONENT_NOT_PRESENT.value
            == "componentNotPresent"
        )
        assert (
            VexJustificationType
            .VULNERABLE_CODE_CANNOT_BE_CONTROLLED_BY_ADVERSARY
            .value
            == "vulnerableCodeCannotBeControlledByAdversary"
        )

    def test_external_identifier_types(self):
        assert (
            ExternalIdentifierType.CVE.value == "cve"
        )
        assert (
            ExternalIdentifierType.PACKAGE_URL.value
            == "packageUrl"
        )
        assert (
            ExternalIdentifierType.GITOID.value == "gitoid"
        )
