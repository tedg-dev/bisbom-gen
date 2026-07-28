"""
VEX Document Builder — attribution-scoped VEX in SPDX 3.

Builds an SPDX 3 document containing:
  - A controlled product Package element
  - Controlled subsystem Package elements
  - Product→subsystem CONTAINS relationships
  - Vulnerability elements with CVE ExternalIdentifiers
  - VEX assessment relationships (affects / doesNotAffect /
    fixedIn / underInvestigationFor)
  - Annotation elements carrying attribution-rule provenance

The builder follows the pattern described in
docs/target_instance_vex.md — subsystem-scoped VEX with
optional scanner-element precision.
"""

import json
from datetime import datetime, timezone

from app.spdx.v3.model import (
    Agent,
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
from app.spdx.v3.serializer import serialize_document


class VexDocumentBuilder:
    """Build an SPDX 3 VEX document for attribution-scoped
    vulnerability dispositioning.

    Usage::

        builder = VexDocumentBuilder(
            product_name="application-X",
            product_version="1.0.0",
            author_agent_uri="urn:spdx:agent:sec-team",
        )
        builder.add_subsystem("XE SDK", "xe-sdk")
        builder.add_vulnerability("CVE-2099-2001")
        builder.add_affected(
            cve_id="CVE-2099-2001",
            subsystem_suffix="xe-sdk",
            action_statement="Patch the curl dep.",
        )
        doc = builder.build()
    """

    def __init__(
        self,
        product_name,
        product_version,
        author_agent_uri,
        namespace_prefix="urn:spdx:pkg",
    ):
        self._product_name = product_name
        self._product_version = product_version
        self._author_uri = author_agent_uri
        self._ns = namespace_prefix
        self._product_id = (
            f"{self._ns}:{self._product_name}"
        )
        self._now = datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        self._creation_info = CreationInfo(
            spec_version="3.0.1",
            created=self._now,
            created_by=[self._author_uri],
        )

        # Internal registries
        self._subsystems = {}
        self._vulnerabilities = {}
        self._vex_relationships = []
        self._annotations = []
        self._agents = []

    # -------------------------------------------------
    # Agent
    # -------------------------------------------------

    def add_agent(self, spdx_id, name, agent_type=None):
        """Add an Agent element (person/org/tool)."""
        self._agents.append(Agent(
            spdx_id=spdx_id,
            name=name,
            agent_type=agent_type,
            creation_info=self._creation_info,
        ))
        return self

    # -------------------------------------------------
    # Product / subsystem structure
    # -------------------------------------------------

    def add_subsystem(self, display_name, spdx_id_suffix):
        """Add a controlled subsystem Package element.

        Args:
            display_name: human-readable name
                (e.g. "application-X XE SDK subsystem")
            spdx_id_suffix: URI suffix for the subsystem
                (e.g. "xe-sdk" → ...subsystem:xe-sdk)
        """
        sub_id = (
            f"{self._product_id}"
            f":subsystem:{spdx_id_suffix}"
        )
        self._subsystems[spdx_id_suffix] = Package(
            spdx_id=sub_id,
            name=display_name,
            primary_purpose=PrimaryPurpose.APPLICATION,
            copyright_text="NOASSERTION",
            creation_info=self._creation_info,
        )
        return self

    # -------------------------------------------------
    # Vulnerability
    # -------------------------------------------------

    def add_vulnerability(self, cve_id, summary=None):
        """Add a Vulnerability element with a CVE
        ExternalIdentifier."""
        vuln_id = f"urn:spdx:vuln:{cve_id}"
        self._vulnerabilities[cve_id] = Vulnerability(
            spdx_id=vuln_id,
            summary=summary,
            external_identifier=[ExternalIdentifier(
                external_identifier_type=(
                    ExternalIdentifierType.CVE
                ),
                identifier=cve_id,
            )],
            creation_info=self._creation_info,
        )
        return self

    # -------------------------------------------------
    # VEX assessment relationships
    # -------------------------------------------------

    def _subsystem_id(self, suffix):
        """Resolve subsystem suffix to its spdxId."""
        sub = self._subsystems.get(suffix)
        if not sub:
            raise ValueError(
                f"Unknown subsystem '{suffix}'. "
                f"Call add_subsystem() first."
            )
        return sub.spdx_id

    def _vuln_id(self, cve_id):
        """Resolve CVE to its Vulnerability spdxId."""
        vuln = self._vulnerabilities.get(cve_id)
        if not vuln:
            raise ValueError(
                f"Unknown CVE '{cve_id}'. "
                f"Call add_vulnerability() first."
            )
        return vuln.spdx_id

    def _vex_spdx_id(self, cve_id, subsystem_suffix):
        """Generate a deterministic spdxId for a VEX rel."""
        return (
            f"urn:spdx:vex:{cve_id}"
            f":{self._product_name}"
            f":{subsystem_suffix}"
        )

    def add_affected(
        self,
        cve_id,
        subsystem_suffix,
        action_statement,
        assessed_element=None,
        attribution_rule=None,
        status_notes=None,
        published_time=None,
    ):
        """Add a VexAffectedVulnAssessmentRelationship.

        Args:
            cve_id: CVE identifier (must be pre-registered).
            subsystem_suffix: target subsystem suffix.
            action_statement: required remediation guidance.
            assessed_element: optional scanner spdxId URI.
            attribution_rule: optional dict with rule fields
                for automatic annotation generation.
            status_notes: optional status notes string.
            published_time: ISO 8601 timestamp; defaults
                to current time.
        """
        rel = VexAffectedVulnAssessmentRelationship(
            spdx_id=self._vex_spdx_id(
                cve_id, subsystem_suffix
            ),
            from_=self._vuln_id(cve_id),
            to=[self._subsystem_id(subsystem_suffix)],
            security_assessed_element=assessed_element,
            security_action_statement=action_statement,
            status_notes=status_notes,
            published_time=(
                published_time or self._now
            ),
            creation_info=self._creation_info,
        )
        self._vex_relationships.append(rel)

        if attribution_rule:
            self._add_rule_annotation(
                subsystem_suffix, attribution_rule,
                assessed_element,
            )
        return self

    def add_not_affected(
        self,
        cve_id,
        subsystem_suffix,
        justification_type,
        impact_statement=None,
        assessed_element=None,
        attribution_rule=None,
        status_notes=None,
        published_time=None,
    ):
        """Add a VexNotAffectedVulnAssessmentRelationship.

        Args:
            justification_type: VexJustificationType enum
                value or its string name.
        """
        if isinstance(justification_type, str):
            justification_type = VexJustificationType(
                justification_type
            )
        rel = VexNotAffectedVulnAssessmentRelationship(
            spdx_id=self._vex_spdx_id(
                cve_id, subsystem_suffix
            ),
            from_=self._vuln_id(cve_id),
            to=[self._subsystem_id(subsystem_suffix)],
            security_assessed_element=assessed_element,
            security_justification_type=(
                justification_type
            ),
            security_impact_statement=impact_statement,
            status_notes=status_notes,
            published_time=(
                published_time or self._now
            ),
            creation_info=self._creation_info,
        )
        self._vex_relationships.append(rel)

        if attribution_rule:
            self._add_rule_annotation(
                subsystem_suffix, attribution_rule,
                assessed_element,
            )
        return self

    def add_fixed(
        self,
        cve_id,
        subsystem_suffix,
        assessed_element=None,
        attribution_rule=None,
        status_notes=None,
        published_time=None,
    ):
        """Add a VexFixedVulnAssessmentRelationship."""
        rel = VexFixedVulnAssessmentRelationship(
            spdx_id=self._vex_spdx_id(
                cve_id, subsystem_suffix
            ),
            from_=self._vuln_id(cve_id),
            to=[self._subsystem_id(subsystem_suffix)],
            security_assessed_element=assessed_element,
            status_notes=status_notes,
            published_time=(
                published_time or self._now
            ),
            creation_info=self._creation_info,
        )
        self._vex_relationships.append(rel)

        if attribution_rule:
            self._add_rule_annotation(
                subsystem_suffix, attribution_rule,
                assessed_element,
            )
        return self

    def add_under_investigation(
        self,
        cve_id,
        subsystem_suffix,
        assessed_element=None,
        attribution_rule=None,
        status_notes=None,
        published_time=None,
    ):
        """Add VexUnderInvestigationVulnAssessmentRelationship."""
        rel = VexUnderInvestigationVulnAssessmentRelationship(
            spdx_id=self._vex_spdx_id(
                cve_id, subsystem_suffix
            ),
            from_=self._vuln_id(cve_id),
            to=[self._subsystem_id(subsystem_suffix)],
            security_assessed_element=assessed_element,
            status_notes=status_notes,
            published_time=(
                published_time or self._now
            ),
            creation_info=self._creation_info,
        )
        self._vex_relationships.append(rel)

        if attribution_rule:
            self._add_rule_annotation(
                subsystem_suffix, attribution_rule,
                assessed_element,
            )
        return self

    # -------------------------------------------------
    # Attribution annotations
    # -------------------------------------------------

    def add_attribution_annotation(
        self,
        subsystem_suffix,
        rule_id,
        rule_type,
        match_criteria,
        matched_component=None,
        matched_version=None,
        matched_path=None,
        scanner_element=None,
    ):
        """Add an Annotation preserving attribution-rule
        provenance on a subsystem element.

        Args:
            subsystem_suffix: target subsystem.
            rule_id: attribution rule numeric ID.
            rule_type: rule type string (e.g. "regex_path").
            match_criteria: dict of match criteria.
            matched_component: component name (e.g. "curl").
            matched_version: component version.
            matched_path: filesystem path matched.
            scanner_element: scanner spdxId if available.
        """
        subject_id = self._subsystem_id(subsystem_suffix)
        payload = {
            "attribution_rule_id": rule_id,
            "rule_type": rule_type,
            "match_criteria": match_criteria,
        }
        if matched_component:
            payload["matched_component"] = (
                matched_component
            )
        if matched_version:
            payload["matched_version"] = matched_version
        if matched_path:
            payload["matched_path"] = matched_path
        if scanner_element:
            payload["scanner_assessed_element"] = (
                scanner_element
            )

        ann_id = (
            f"urn:spdx:annotation"
            f":{self._product_name}"
            f":subsystem:{subsystem_suffix}"
            f":rule-{rule_id}"
        )
        self._annotations.append(Annotation(
            spdx_id=ann_id,
            annotation_type=AnnotationType.OTHER,
            subject=subject_id,
            content_type="application/json",
            statement=json.dumps(
                payload, separators=(",", ":")
            ),
            creation_info=self._creation_info,
        ))
        return self

    def _add_rule_annotation(
        self, subsystem_suffix, rule, assessed_element,
    ):
        """Auto-generate annotation from rule dict."""
        self.add_attribution_annotation(
            subsystem_suffix=subsystem_suffix,
            rule_id=rule.get("id"),
            rule_type=rule.get("rule_type", ""),
            match_criteria=rule.get(
                "match_criteria", {}
            ),
            matched_component=rule.get(
                "matched_component"
            ),
            matched_version=rule.get(
                "matched_version"
            ),
            matched_path=rule.get("matched_path"),
            scanner_element=assessed_element,
        )

    # -------------------------------------------------
    # Build
    # -------------------------------------------------

    def build(self):
        """Assemble and return the SPDX 3 JSON-LD dict.

        Returns:
            dict: complete document ready for
            ``json.dumps()``.
        """
        elements = []

        # Agents
        elements.extend(self._agents)

        # Product package
        product = Package(
            spdx_id=self._product_id,
            name=self._product_name,
            package_version=self._product_version,
            primary_purpose=PrimaryPurpose.APPLICATION,
            copyright_text="NOASSERTION",
            creation_info=self._creation_info,
        )
        elements.append(product)

        # Subsystem packages
        subsystem_ids = []
        for suffix in sorted(self._subsystems):
            sub = self._subsystems[suffix]
            elements.append(sub)
            subsystem_ids.append(sub.spdx_id)

        # Product CONTAINS subsystems relationship
        if subsystem_ids:
            contains_rel = Relationship(
                spdx_id=(
                    f"urn:spdx:rel"
                    f":{self._product_name}"
                    f"-contains-subsystems"
                ),
                relationship_type=(
                    RelationshipType.CONTAINS
                ),
                from_=self._product_id,
                to=subsystem_ids,
                creation_info=self._creation_info,
            )
            elements.append(contains_rel)

        # Vulnerabilities
        for cve_id in sorted(self._vulnerabilities):
            elements.append(
                self._vulnerabilities[cve_id]
            )

        # VEX assessment relationships
        elements.extend(self._vex_relationships)

        # Annotations
        elements.extend(self._annotations)

        doc = SpdxDocument(elements=elements)
        return serialize_document(doc)
