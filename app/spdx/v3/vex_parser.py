"""
Minimal SPDX 3 VEX document parser.

Parses an SPDX 3 JSON-LD document to extract:
  - Vulnerability elements with CVE identifiers
  - VEX assessment relationships (all four types)
  - Product/subsystem Package elements
  - Annotation elements (attribution-rule provenance)

Designed for consuming attribution-scoped VEX documents
as described in docs/target_instance_vex.md.  Supports
the Corona Gambit worker processing sketch (steps 2–8).
"""

import json

# VEX relationship type names used in SPDX 3 JSON-LD
_VEX_TYPES = frozenset({
    "VexAffectedVulnAssessmentRelationship",
    "VexNotAffectedVulnAssessmentRelationship",
    "VexFixedVulnAssessmentRelationship",
    "VexUnderInvestigationVulnAssessmentRelationship",
})

# Mapping from VEX relationshipType to Corona status
VEX_STATUS_MAP = {
    "affects": "AFFECTED",
    "doesNotAffect": "NOT_AFFECTED",
    "fixedIn": "FIXED",
    "underInvestigationFor": "UNDER_INVESTIGATION",
}


class VexDocumentParser:
    """Parse an SPDX 3 JSON-LD VEX document.

    Args:
        doc: parsed JSON dict (the output of
            ``json.loads()`` on an SPDX 3 JSON-LD file).
    """

    def __init__(self, doc):
        self._doc = doc
        self._graph = doc.get("@graph", [])
        self._index = {
            e["spdxId"]: e
            for e in self._graph
            if "spdxId" in e
        }

    @classmethod
    def from_json(cls, text):
        """Construct parser from a JSON string."""
        return cls(json.loads(text))

    @classmethod
    def from_file(cls, path):
        """Construct parser from a file path."""
        from pathlib import Path
        return cls(json.loads(Path(path).read_text()))

    # -------------------------------------------------
    # Element access
    # -------------------------------------------------

    def get_element(self, spdx_id):
        """Look up any element by spdxId.

        Returns the element dict, or None.
        """
        return self._index.get(spdx_id)

    def get_elements_by_type(self, type_name):
        """Return all elements with the given ``type``.

        Args:
            type_name: SPDX 3 type string
                (e.g. "Package", "Vulnerability").

        Returns:
            list of element dicts.
        """
        return [
            e for e in self._graph
            if e.get("type") == type_name
        ]

    # -------------------------------------------------
    # Vulnerability helpers
    # -------------------------------------------------

    def get_vulnerabilities(self):
        """Extract Vulnerability elements.

        Returns:
            list of dicts, each with at least
            ``spdxId`` and ``type``.
        """
        return self.get_elements_by_type("Vulnerability")

    def get_cve_id(self, vulnerability):
        """Extract the CVE identifier from a Vulnerability.

        Scans ``externalIdentifier`` for type ``cve``.

        Args:
            vulnerability: element dict.

        Returns:
            CVE string (e.g. "CVE-2099-2001") or None.
        """
        for ext in vulnerability.get(
            "externalIdentifier", []
        ):
            if ext.get("externalIdentifierType") == "cve":
                return ext.get("identifier")
        return None

    # -------------------------------------------------
    # VEX relationships
    # -------------------------------------------------

    def get_vex_relationships(self):
        """Extract all VEX assessment relationships.

        Returns:
            list of element dicts whose ``type`` is one
            of the four VEX assessment relationship types.
        """
        return [
            e for e in self._graph
            if e.get("type") in _VEX_TYPES
        ]

    def get_vex_status(self, vex_rel):
        """Map a VEX relationship to a Corona-style status.

        Args:
            vex_rel: VEX relationship element dict.

        Returns:
            Status string (AFFECTED, NOT_AFFECTED,
            FIXED, UNDER_INVESTIGATION) or None.
        """
        rel_type = vex_rel.get("relationshipType", "")
        return VEX_STATUS_MAP.get(rel_type)

    # -------------------------------------------------
    # Subsystem / product helpers
    # -------------------------------------------------

    def get_packages(self):
        """Extract all Package elements."""
        return self.get_elements_by_type("Package")

    def get_subsystems(self, product_id=None):
        """Extract subsystem Package elements.

        If ``product_id`` is given, returns packages that
        are targets of a CONTAINS relationship from that
        product.  Otherwise returns all packages whose
        ``spdxId`` contains ``:subsystem:``.

        Args:
            product_id: optional product spdxId to scope.

        Returns:
            list of Package element dicts.
        """
        if product_id:
            contained_ids = set()
            for e in self._graph:
                if (
                    e.get("type") == "Relationship"
                    and e.get("relationshipType")
                    == "contains"
                    and e.get("from") == product_id
                ):
                    for target in e.get("to", []):
                        contained_ids.add(target)
            return [
                self._index[sid]
                for sid in contained_ids
                if sid in self._index
            ]

        return [
            e for e in self._graph
            if e.get("type") == "Package"
            and ":subsystem:" in e.get("spdxId", "")
        ]

    # -------------------------------------------------
    # Annotation helpers
    # -------------------------------------------------

    def get_annotations(self):
        """Extract all Annotation elements."""
        return self.get_elements_by_type("Annotation")

    def get_annotations_for(self, subject_id):
        """Get annotations whose subject matches.

        Args:
            subject_id: spdxId of the annotation subject.

        Returns:
            list of Annotation element dicts.
        """
        return [
            e for e in self._graph
            if (
                e.get("type") == "Annotation"
                and e.get("subject") == subject_id
            )
        ]

    def parse_annotation_statement(self, annotation):
        """Parse the JSON statement of an Annotation.

        Returns:
            Parsed dict, or empty dict on failure.
        """
        stmt = annotation.get("statement", "")
        try:
            return json.loads(stmt)
        except (json.JSONDecodeError, TypeError):
            return {}

    # -------------------------------------------------
    # Attribution context resolution
    # -------------------------------------------------

    def resolve_attribution_context(self, vex_rel):
        """Extract attribution-rule context for a VEX rel.

        Looks up annotations on the ``to`` target(s) and
        parses their statements for attribution fields.

        Args:
            vex_rel: VEX relationship element dict.

        Returns:
            dict with keys: attribution_rule_id,
            rule_type, match_criteria,
            matched_component, matched_version,
            matched_path, scanner_assessed_element.
            Missing keys are omitted.
        """
        targets = vex_rel.get("to", [])
        for target_id in targets:
            annotations = self.get_annotations_for(
                target_id
            )
            for ann in annotations:
                parsed = self.parse_annotation_statement(
                    ann
                )
                if parsed.get("attribution_rule_id"):
                    return parsed
        return {}
