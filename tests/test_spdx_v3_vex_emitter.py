"""Tests for app.spdx.v3.vex_emitter — VEX document builder."""

import json

import pytest

from app.spdx.v3.vex_emitter import VexDocumentBuilder


def _make_builder():
    """Helper: create a builder with standard test config."""
    return VexDocumentBuilder(
        product_name="application-x",
        product_version="1.0.0",
        author_agent_uri="urn:spdx:agent:sec-team",
    )


class TestBuilderInit:
    """Builder initialization tests."""

    def test_creates_builder(self):
        b = _make_builder()
        assert b is not None

    def test_empty_build(self):
        doc = _make_builder().build()
        assert "@context" in doc
        assert "3.0.1" in doc["@context"]
        # Should have product package only
        graph = doc["@graph"]
        types = [e["type"] for e in graph]
        assert "Package" in types


class TestSubsystems:
    """Subsystem registration tests."""

    def test_add_subsystem(self):
        b = _make_builder()
        b.add_subsystem("XE SDK subsystem", "xe-sdk")
        doc = b.build()
        packages = [
            e for e in doc["@graph"]
            if e["type"] == "Package"
        ]
        ids = [p["spdxId"] for p in packages]
        assert any(":subsystem:xe-sdk" in i for i in ids)

    def test_multiple_subsystems(self):
        b = _make_builder()
        b.add_subsystem("XE SDK", "xe-sdk")
        b.add_subsystem("CoreOS", "coreos")
        b.add_subsystem("XRsubsysA", "xrsubsysa")
        b.add_subsystem("XRsubsysB", "xrsubsysb")
        doc = b.build()
        packages = [
            e for e in doc["@graph"]
            if e["type"] == "Package"
        ]
        # Product + 4 subsystems
        assert len(packages) == 5

    def test_contains_relationship(self):
        b = _make_builder()
        b.add_subsystem("XE SDK", "xe-sdk")
        b.add_subsystem("CoreOS", "coreos")
        doc = b.build()
        rels = [
            e for e in doc["@graph"]
            if e.get("type") == "Relationship"
        ]
        contains = [
            r for r in rels
            if r["relationshipType"] == "contains"
        ]
        assert len(contains) == 1
        assert len(contains[0]["to"]) == 2


class TestVulnerabilities:
    """Vulnerability registration tests."""

    def test_add_vulnerability(self):
        b = _make_builder()
        b.add_vulnerability(
            "CVE-2099-2001", "Test vuln"
        )
        doc = b.build()
        vulns = [
            e for e in doc["@graph"]
            if e["type"] == "Vulnerability"
        ]
        assert len(vulns) == 1
        assert vulns[0]["summary"] == "Test vuln"
        ext = vulns[0]["externalIdentifier"][0]
        assert ext["identifier"] == "CVE-2099-2001"


class TestVexAffected:
    """VexAffectedVulnAssessmentRelationship tests."""

    def test_affected(self):
        b = _make_builder()
        b.add_subsystem("XE SDK", "xe-sdk")
        b.add_vulnerability("CVE-2099-2001")
        b.add_affected(
            cve_id="CVE-2099-2001",
            subsystem_suffix="xe-sdk",
            action_statement="Patch the curl dep.",
            assessed_element=(
                "urn:scanner-x:artifact:7b4f2c9a"
            ),
        )
        doc = b.build()
        vex = [
            e for e in doc["@graph"]
            if e["type"] == (
                "VexAffectedVulnAssessmentRelationship"
            )
        ]
        assert len(vex) == 1
        assert vex[0]["relationshipType"] == "affects"
        assert vex[0]["security_actionStatement"] == (
            "Patch the curl dep."
        )
        assert vex[0]["security_assessedElement"] == (
            "urn:scanner-x:artifact:7b4f2c9a"
        )

    def test_affected_without_assessed_element(self):
        b = _make_builder()
        b.add_subsystem("XRsubsysA", "xrsubsysa")
        b.add_vulnerability("CVE-2099-2001")
        b.add_affected(
            cve_id="CVE-2099-2001",
            subsystem_suffix="xrsubsysa",
            action_statement="Patch it.",
        )
        doc = b.build()
        vex = [
            e for e in doc["@graph"]
            if e["type"] == (
                "VexAffectedVulnAssessmentRelationship"
            )
        ]
        assert "security_assessedElement" not in vex[0]

    def test_affected_unknown_subsystem(self):
        b = _make_builder()
        b.add_vulnerability("CVE-2099-2001")
        with pytest.raises(ValueError, match="Unknown"):
            b.add_affected(
                cve_id="CVE-2099-2001",
                subsystem_suffix="nonexistent",
                action_statement="Fix.",
            )

    def test_affected_unknown_cve(self):
        b = _make_builder()
        b.add_subsystem("XE SDK", "xe-sdk")
        with pytest.raises(ValueError, match="Unknown"):
            b.add_affected(
                cve_id="CVE-9999-9999",
                subsystem_suffix="xe-sdk",
                action_statement="Fix.",
            )


class TestVexNotAffected:
    """VexNotAffectedVulnAssessmentRelationship tests."""

    def test_not_affected(self):
        b = _make_builder()
        b.add_subsystem("CoreOS", "coreos")
        b.add_vulnerability("CVE-2099-2001")
        b.add_not_affected(
            cve_id="CVE-2099-2001",
            subsystem_suffix="coreos",
            justification_type=(
                "vulnerableCodeNotInExecutePath"
            ),
            impact_statement="Not reachable.",
        )
        doc = b.build()
        vex = [
            e for e in doc["@graph"]
            if e["type"] == (
                "VexNotAffectedVulnAssessment"
                "Relationship"
            )
        ]
        assert len(vex) == 1
        assert vex[0]["relationshipType"] == (
            "doesNotAffect"
        )
        assert vex[0]["security_justificationType"] == (
            "vulnerableCodeNotInExecutePath"
        )

    def test_not_affected_adversary_justification(self):
        b = _make_builder()
        b.add_subsystem("XRsubsysB", "xrsubsysb")
        b.add_vulnerability("CVE-2099-2001")
        b.add_not_affected(
            cve_id="CVE-2099-2001",
            subsystem_suffix="xrsubsysb",
            justification_type=(
                "vulnerableCodeCannot"
                "BeControlledByAdversary"
            ),
        )
        doc = b.build()
        vex = [
            e for e in doc["@graph"]
            if e["type"] == (
                "VexNotAffectedVulnAssessment"
                "Relationship"
            )
        ]
        assert vex[0]["security_justificationType"] == (
            "vulnerableCodeCannot"
            "BeControlledByAdversary"
        )


class TestVexFixed:
    """VexFixedVulnAssessmentRelationship tests."""

    def test_fixed(self):
        b = _make_builder()
        b.add_subsystem("XE SDK", "xe-sdk")
        b.add_vulnerability("CVE-2099-2001")
        b.add_fixed(
            cve_id="CVE-2099-2001",
            subsystem_suffix="xe-sdk",
            status_notes="Patched in v2.0.",
        )
        doc = b.build()
        vex = [
            e for e in doc["@graph"]
            if e["type"] == (
                "VexFixedVulnAssessmentRelationship"
            )
        ]
        assert len(vex) == 1
        assert vex[0]["relationshipType"] == "fixedIn"
        assert vex[0]["statusNotes"] == "Patched in v2.0."


class TestVexUnderInvestigation:
    """VexUnderInvestigationVulnAssessmentRelationship tests."""

    def test_under_investigation(self):
        b = _make_builder()
        b.add_subsystem("CoreOS", "coreos")
        b.add_vulnerability("CVE-2099-2001")
        b.add_under_investigation(
            cve_id="CVE-2099-2001",
            subsystem_suffix="coreos",
        )
        doc = b.build()
        vex = [
            e for e in doc["@graph"]
            if e["type"] == (
                "VexUnderInvestigationVuln"
                "AssessmentRelationship"
            )
        ]
        assert len(vex) == 1
        assert vex[0]["relationshipType"] == (
            "underInvestigationFor"
        )


class TestAttributionAnnotations:
    """Attribution-rule annotation tests."""

    def test_manual_annotation(self):
        b = _make_builder()
        b.add_subsystem("XE SDK", "xe-sdk")
        b.add_attribution_annotation(
            subsystem_suffix="xe-sdk",
            rule_id=4812,
            rule_type="regex_path",
            match_criteria={"regex_path": "xe[-_]?sdk"},
            matched_component="curl",
            matched_version="7.81.0",
            matched_path=(
                "/opt/application-X/xe-sdk/bin/curl"
            ),
            scanner_element=(
                "urn:scanner-x:artifact:7b4f2c9a"
            ),
        )
        doc = b.build()
        anns = [
            e for e in doc["@graph"]
            if e["type"] == "Annotation"
        ]
        assert len(anns) == 1
        payload = json.loads(anns[0]["statement"])
        assert payload["attribution_rule_id"] == 4812
        assert payload["rule_type"] == "regex_path"
        assert payload["matched_component"] == "curl"
        assert payload["matched_version"] == "7.81.0"

    def test_auto_annotation_from_rule(self):
        b = _make_builder()
        b.add_subsystem("XE SDK", "xe-sdk")
        b.add_vulnerability("CVE-2099-2001")
        rule = {
            "id": 4812,
            "rule_type": "regex_path",
            "match_criteria": {
                "regex_path": "xe[-_]?sdk"
            },
            "matched_component": "curl",
            "matched_version": "7.81.0",
        }
        b.add_affected(
            cve_id="CVE-2099-2001",
            subsystem_suffix="xe-sdk",
            action_statement="Patch.",
            attribution_rule=rule,
        )
        doc = b.build()
        anns = [
            e for e in doc["@graph"]
            if e["type"] == "Annotation"
        ]
        assert len(anns) == 1
        payload = json.loads(anns[0]["statement"])
        assert payload["attribution_rule_id"] == 4812


class TestFullDocument:
    """End-to-end document assembly matching the
    target_instance_vex.md example."""

    def test_four_subsystem_vex(self):
        b = _make_builder()
        b.add_subsystem("XE SDK", "xe-sdk")
        b.add_subsystem("CoreOS", "coreos")
        b.add_subsystem("XRsubsysA", "xrsubsysa")
        b.add_subsystem("XRsubsysB", "xrsubsysb")

        b.add_vulnerability(
            "CVE-2099-2001",
            "Fictional curl 7.81.0 vulnerability",
        )

        # XE SDK: affected
        b.add_affected(
            cve_id="CVE-2099-2001",
            subsystem_suffix="xe-sdk",
            action_statement=(
                "Patch the XE SDK curl dependency."
            ),
            assessed_element=(
                "urn:scanner-x:artifact:7b4f2c9a"
            ),
            attribution_rule={
                "id": 4812,
                "rule_type": "regex_path",
                "match_criteria": {
                    "regex_path": "xe[-_]?sdk"
                },
                "matched_component": "curl",
                "matched_version": "7.81.0",
                "matched_path": (
                    "/opt/application-X/xe-sdk/bin/curl"
                ),
            },
        )

        # CoreOS: not affected
        b.add_not_affected(
            cve_id="CVE-2099-2001",
            subsystem_suffix="coreos",
            justification_type=(
                "vulnerableCodeNotInExecutePath"
            ),
            impact_statement=(
                "Curl present but code path "
                "not reachable."
            ),
            status_notes="Rule 4813.",
        )

        # XRsubsysA: affected
        b.add_affected(
            cve_id="CVE-2099-2001",
            subsystem_suffix="xrsubsysa",
            action_statement=(
                "Patch XRsubsysA curl dependency."
            ),
            status_notes="Rule 4814.",
        )

        # XRsubsysB: not affected
        b.add_not_affected(
            cve_id="CVE-2099-2001",
            subsystem_suffix="xrsubsysb",
            justification_type=(
                "vulnerableCodeCannot"
                "BeControlledByAdversary"
            ),
            status_notes="Rule 4815.",
        )

        doc = b.build()

        # Verify structure
        graph = doc["@graph"]
        types = [e["type"] for e in graph]

        # 1 product + 4 subsystems = 5 packages
        assert types.count("Package") == 5
        # 1 contains relationship
        assert types.count("Relationship") == 1
        # 1 vulnerability
        assert types.count("Vulnerability") == 1
        # 2 affected + 2 not-affected
        assert types.count(
            "VexAffectedVulnAssessment"
            "Relationship"
        ) == 2
        assert types.count(
            "VexNotAffectedVulnAssessment"
            "Relationship"
        ) == 2
        # 1 auto-annotation from XE SDK rule
        assert types.count("Annotation") == 1

    def test_output_is_json_serializable(self):
        """Verify the output can be serialized to JSON."""
        b = _make_builder()
        b.add_subsystem("XE SDK", "xe-sdk")
        b.add_vulnerability("CVE-2099-2001")
        b.add_affected(
            cve_id="CVE-2099-2001",
            subsystem_suffix="xe-sdk",
            action_statement="Fix.",
        )
        doc = b.build()
        text = json.dumps(doc, indent=2)
        assert len(text) > 0
        # Round-trip: parse back
        parsed = json.loads(text)
        assert parsed["@context"] == doc["@context"]


class TestAgents:
    """Agent element tests."""

    def test_add_agent(self):
        b = _make_builder()
        b.add_agent(
            "urn:spdx:agent:scanner-x",
            "scanner-x",
        )
        doc = b.build()
        agents = [
            e for e in doc["@graph"]
            if e["type"] == "Agent"
        ]
        assert len(agents) == 1
        assert agents[0]["name"] == "scanner-x"


class TestChainedApi:
    """Verify builder methods return self for chaining."""

    def test_chaining(self):
        doc = (
            _make_builder()
            .add_subsystem("XE SDK", "xe-sdk")
            .add_vulnerability("CVE-2099-2001")
            .add_affected(
                cve_id="CVE-2099-2001",
                subsystem_suffix="xe-sdk",
                action_statement="Fix.",
            )
            .build()
        )
        assert "@graph" in doc
