"""Tests for app.spdx.v3.vex_parser — minimal VEX consumer."""

import json

from app.spdx.v3.vex_emitter import VexDocumentBuilder
from app.spdx.v3.vex_parser import (
    VEX_STATUS_MAP,
    VexDocumentParser,
)


def _build_sample_doc():
    """Build a sample VEX document for parser tests."""
    b = VexDocumentBuilder(
        product_name="application-x",
        product_version="1.0.0",
        author_agent_uri="urn:spdx:agent:sec-team",
    )
    b.add_subsystem("XE SDK", "xe-sdk")
    b.add_subsystem("CoreOS", "coreos")
    b.add_vulnerability(
        "CVE-2099-2001", "Fictional curl vuln"
    )
    b.add_affected(
        cve_id="CVE-2099-2001",
        subsystem_suffix="xe-sdk",
        action_statement="Patch curl.",
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
    b.add_not_affected(
        cve_id="CVE-2099-2001",
        subsystem_suffix="coreos",
        justification_type=(
            "vulnerableCodeNotInExecutePath"
        ),
        impact_statement="Not reachable.",
        status_notes="Rule 4813.",
    )
    return b.build()


class TestParserInit:
    """Parser initialization tests."""

    def test_from_dict(self):
        doc = _build_sample_doc()
        parser = VexDocumentParser(doc)
        assert parser is not None

    def test_from_json(self):
        doc = _build_sample_doc()
        text = json.dumps(doc)
        parser = VexDocumentParser.from_json(text)
        assert parser is not None

    def test_from_file(self, tmp_path):
        doc = _build_sample_doc()
        path = tmp_path / "test.spdx3.json"
        path.write_text(json.dumps(doc))
        parser = VexDocumentParser.from_file(str(path))
        assert parser is not None


class TestElementAccess:
    """Element lookup tests."""

    def test_get_element(self):
        doc = _build_sample_doc()
        parser = VexDocumentParser(doc)
        elem = parser.get_element(
            "urn:spdx:pkg:application-x"
        )
        assert elem is not None
        assert elem["name"] == "application-x"

    def test_get_element_missing(self):
        parser = VexDocumentParser(_build_sample_doc())
        assert parser.get_element("nonexistent") is None

    def test_get_elements_by_type(self):
        parser = VexDocumentParser(_build_sample_doc())
        packages = parser.get_elements_by_type("Package")
        # product + 2 subsystems = 3
        assert len(packages) == 3


class TestVulnerabilities:
    """Vulnerability extraction tests."""

    def test_get_vulnerabilities(self):
        parser = VexDocumentParser(_build_sample_doc())
        vulns = parser.get_vulnerabilities()
        assert len(vulns) == 1
        assert "CVE-2099-2001" in vulns[0]["spdxId"]

    def test_get_cve_id(self):
        parser = VexDocumentParser(_build_sample_doc())
        vulns = parser.get_vulnerabilities()
        cve = parser.get_cve_id(vulns[0])
        assert cve == "CVE-2099-2001"

    def test_get_cve_id_missing(self):
        parser = VexDocumentParser(_build_sample_doc())
        cve = parser.get_cve_id({"type": "Vulnerability"})
        assert cve is None


class TestVexRelationships:
    """VEX relationship extraction tests."""

    def test_get_vex_relationships(self):
        parser = VexDocumentParser(_build_sample_doc())
        vex_rels = parser.get_vex_relationships()
        # 1 affected + 1 not-affected
        assert len(vex_rels) == 2

    def test_get_vex_status_affected(self):
        parser = VexDocumentParser(_build_sample_doc())
        vex_rels = parser.get_vex_relationships()
        affected = [
            r for r in vex_rels
            if r["relationshipType"] == "affects"
        ]
        assert len(affected) == 1
        status = parser.get_vex_status(affected[0])
        assert status == "AFFECTED"

    def test_get_vex_status_not_affected(self):
        parser = VexDocumentParser(_build_sample_doc())
        vex_rels = parser.get_vex_relationships()
        not_affected = [
            r for r in vex_rels
            if r["relationshipType"] == "doesNotAffect"
        ]
        assert len(not_affected) == 1
        status = parser.get_vex_status(not_affected[0])
        assert status == "NOT_AFFECTED"

    def test_status_map_complete(self):
        assert len(VEX_STATUS_MAP) == 4
        assert "affects" in VEX_STATUS_MAP
        assert "doesNotAffect" in VEX_STATUS_MAP
        assert "fixedIn" in VEX_STATUS_MAP
        assert "underInvestigationFor" in VEX_STATUS_MAP


class TestSubsystems:
    """Subsystem extraction tests."""

    def test_get_packages(self):
        parser = VexDocumentParser(_build_sample_doc())
        packages = parser.get_packages()
        assert len(packages) == 3

    def test_get_subsystems_by_convention(self):
        parser = VexDocumentParser(_build_sample_doc())
        subs = parser.get_subsystems()
        assert len(subs) == 2
        ids = [s["spdxId"] for s in subs]
        assert any(":subsystem:xe-sdk" in i for i in ids)
        assert any(":subsystem:coreos" in i for i in ids)

    def test_get_subsystems_by_product(self):
        parser = VexDocumentParser(_build_sample_doc())
        subs = parser.get_subsystems(
            product_id="urn:spdx:pkg:application-x"
        )
        assert len(subs) == 2


class TestAnnotations:
    """Annotation extraction tests."""

    def test_get_annotations(self):
        parser = VexDocumentParser(_build_sample_doc())
        anns = parser.get_annotations()
        assert len(anns) == 1

    def test_get_annotations_for_subject(self):
        parser = VexDocumentParser(_build_sample_doc())
        xe_sdk_id = (
            "urn:spdx:pkg:application-x"
            ":subsystem:xe-sdk"
        )
        anns = parser.get_annotations_for(xe_sdk_id)
        assert len(anns) == 1

    def test_get_annotations_for_no_match(self):
        parser = VexDocumentParser(_build_sample_doc())
        anns = parser.get_annotations_for("nonexistent")
        assert len(anns) == 0

    def test_parse_annotation_statement(self):
        parser = VexDocumentParser(_build_sample_doc())
        anns = parser.get_annotations()
        payload = parser.parse_annotation_statement(
            anns[0]
        )
        assert payload["attribution_rule_id"] == 4812
        assert payload["rule_type"] == "regex_path"
        assert payload["matched_component"] == "curl"

    def test_parse_annotation_invalid_json(self):
        parser = VexDocumentParser(_build_sample_doc())
        result = parser.parse_annotation_statement(
            {"statement": "not json"}
        )
        assert result == {}


class TestAttributionContext:
    """Attribution context resolution tests."""

    def test_resolve_attribution_context(self):
        parser = VexDocumentParser(_build_sample_doc())
        vex_rels = parser.get_vex_relationships()
        affected = [
            r for r in vex_rels
            if r["relationshipType"] == "affects"
        ]
        ctx = parser.resolve_attribution_context(
            affected[0]
        )
        assert ctx["attribution_rule_id"] == 4812
        assert ctx["rule_type"] == "regex_path"
        assert ctx["matched_component"] == "curl"
        assert ctx["matched_version"] == "7.81.0"

    def test_resolve_no_attribution(self):
        parser = VexDocumentParser(_build_sample_doc())
        vex_rels = parser.get_vex_relationships()
        not_affected = [
            r for r in vex_rels
            if r["relationshipType"] == "doesNotAffect"
        ]
        ctx = parser.resolve_attribution_context(
            not_affected[0]
        )
        # CoreOS has no annotation in the sample doc
        assert ctx == {}


class TestRoundTrip:
    """Round-trip: build → serialize → parse → extract."""

    def test_full_round_trip(self):
        # Build
        b = VexDocumentBuilder(
            product_name="product-y",
            product_version="2.0.0",
            author_agent_uri="urn:spdx:agent:team",
        )
        b.add_subsystem("SubA", "sub-a")
        b.add_vulnerability("CVE-2099-9999")
        b.add_affected(
            cve_id="CVE-2099-9999",
            subsystem_suffix="sub-a",
            action_statement="Upgrade.",
            attribution_rule={
                "id": 100,
                "rule_type": "exact_path",
                "match_criteria": {
                    "path": "/opt/sub-a/lib/vuln.so"
                },
                "matched_component": "vuln-lib",
                "matched_version": "1.0.0",
            },
        )
        doc = b.build()

        # Serialize → parse
        text = json.dumps(doc)
        parser = VexDocumentParser.from_json(text)

        # Extract
        vulns = parser.get_vulnerabilities()
        assert len(vulns) == 1
        assert parser.get_cve_id(vulns[0]) == (
            "CVE-2099-9999"
        )

        vex_rels = parser.get_vex_relationships()
        assert len(vex_rels) == 1
        assert parser.get_vex_status(vex_rels[0]) == (
            "AFFECTED"
        )

        ctx = parser.resolve_attribution_context(
            vex_rels[0]
        )
        assert ctx["attribution_rule_id"] == 100
        assert ctx["matched_component"] == "vuln-lib"
