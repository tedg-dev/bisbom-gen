"""
SPDX validation for OmniBOR Analysis.

Two-phase validation of SPDX 2.3 JSON documents:
  1. JSON Schema — structural correctness
  2. Semantic — business-rule checks via spdx-tools
"""

from pathlib import Path


class SpdxValidator:
    """Validates SPDX v2.3 JSON documents.

    Two-phase validation:
      1. JSON Schema — structural correctness against the
         official SPDX 2.3 JSON Schema.
      2. Semantic — business-rule checks via spdx-tools
         (parse + validate_full_spdx_document).

    Either phase can be skipped if its library is unavailable,
    with a warning printed instead of a hard failure.
    """

    # Directory holding vendored SPDX JSON Schemas. Validating
    # against bundled copies avoids a network fetch (the upstream
    # raw URL has returned 404 when the spec layout changes) and
    # makes validation deterministic and offline-capable.
    SCHEMA_DIR = Path(__file__).parent

    # Maps an SPDX document's declared version to its vendored
    # JSON Schema file. Version-keyed selection keeps the
    # validator forward-compatible: support a new SPDX release
    # (e.g. SPDX 3.x) by vendoring its schema here and adding an
    # entry — no change to the validation logic is required.
    # The JSON Schema draft is auto-detected per schema via
    # ``validator_for`` (2.3.1 uses draft 2019-09; 3.x may differ).
    SCHEMA_FILES = {
        "SPDX-2.3": "spdx-2.3.1.schema.json",
    }

    def _schema_path_for(self, doc_json):
        """Resolve the vendored schema for a document's version.

        Reads the SPDX version from the document (``spdxVersion``
        for 2.x, ``specVersion`` for 3.x) and returns
        ``(Path, version)`` for the matching vendored schema, or
        ``(None, version)`` when the version is unsupported so the
        caller can skip schema validation rather than validate
        against the wrong schema.
        """
        version = (
            doc_json.get("spdxVersion")
            or doc_json.get("specVersion")
            or ""
        )
        filename = self.SCHEMA_FILES.get(version)
        if filename is None:
            return None, version
        return self.SCHEMA_DIR / filename, version

    def validate(self, spdx_path):
        """Run both validation phases on *spdx_path*.

        Returns a dict:
          {
            "schema_ok": bool | None,
            "semantic_ok": bool | None,
            "schema_errors": [str],
            "semantic_errors": [str],
          }
        None means the check was skipped (library missing).
        """
        result = {
            "schema_ok": None,
            "semantic_ok": None,
            "schema_errors": [],
            "semantic_errors": [],
        }

        spdx_path = Path(spdx_path)
        if not spdx_path.exists():
            print(
                f"[WARN] SPDX file not found: "
                f"{spdx_path}"
            )
            return result

        import json
        try:
            with open(spdx_path, "r") as f:
                doc_json = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(
                f"[ERROR] Cannot read SPDX JSON: {e}"
            )
            return result

        # Phase 1: JSON Schema
        result = self._validate_schema(
            doc_json, spdx_path, result
        )

        # Phase 2: Semantic (spdx-tools)
        result = self._validate_semantic(
            spdx_path, result
        )

        self._print_summary(spdx_path, result)
        return result

    def _validate_schema(
        self, doc_json, spdx_path, result
    ):
        """Validate against the vendored SPDX JSON Schema.

        The schema is chosen from the document's declared SPDX
        version, so the same validator handles both current
        (2.3) and future (3.x) documents.
        """
        try:
            from jsonschema.validators import validator_for
        except ImportError:
            print(
                "[WARN] jsonschema not installed — "
                "skipping JSON Schema validation"
            )
            return result

        schema_path, version = self._schema_path_for(doc_json)
        if schema_path is None:
            print(
                f"[WARN] No vendored schema for SPDX version "
                f"'{version}' — skipping schema validation"
            )
            return result

        try:
            import json
            with open(
                schema_path, "r", encoding="utf-8"
            ) as f:
                schema = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            print(
                f"[WARN] Could not load vendored SPDX schema: "
                f"{e} — skipping schema validation"
            )
            return result

        # Auto-select the validator draft declared in the
        # schema's $schema field (SPDX 2.3.1 uses 2019-09;
        # a future 3.x schema may declare a newer draft).
        validator_cls = validator_for(schema)
        validator = validator_cls(schema)
        errors = sorted(
            validator.iter_errors(doc_json),
            key=lambda e: list(e.absolute_path),
        )
        result["schema_errors"] = [
            f"{'.'.join(str(p) for p in e.absolute_path)}: "
            f"{e.message}"
            if e.absolute_path
            else e.message
            for e in errors
        ]
        result["schema_ok"] = len(errors) == 0
        return result

    def _validate_semantic(self, spdx_path, result):
        """Validate with spdx-tools parse + validate."""
        try:
            from spdx_tools.spdx.parser.parse_anything import (
                parse_file,
            )
            from spdx_tools.spdx.validation.document_validator import (
                validate_full_spdx_document,
            )
        except ImportError:
            print(
                "[WARN] spdx-tools not installed — "
                "skipping semantic validation"
            )
            return result

        try:
            document = parse_file(str(spdx_path))
        except Exception as e:
            result["semantic_ok"] = False
            result["semantic_errors"] = [
                f"Parse error: {e}"
            ]
            return result

        messages = validate_full_spdx_document(
            document
        )
        result["semantic_errors"] = [
            str(m.validation_message)
            for m in messages
        ]
        result["semantic_ok"] = len(messages) == 0
        return result

    @staticmethod
    def _print_summary(spdx_path, result):
        """Print human-readable validation summary."""
        name = Path(spdx_path).name
        print(
            f"\n{'='*60}\n"
            f"  SPDX Validation: {name}\n"
            f"{'='*60}"
        )

        # Schema
        if result["schema_ok"] is None:
            print("  JSON Schema:  SKIPPED")
        elif result["schema_ok"]:
            print("  JSON Schema:  PASS")
        else:
            n = len(result["schema_errors"])
            print(f"  JSON Schema:  FAIL ({n} errors)")
            for e in result["schema_errors"][:10]:
                print(f"    - {e}")
            if n > 10:
                print(f"    ... and {n - 10} more")

        # Semantic
        if result["semantic_ok"] is None:
            print("  Semantic:     SKIPPED")
        elif result["semantic_ok"]:
            print("  Semantic:     PASS")
        else:
            n = len(result["semantic_errors"])
            print(f"  Semantic:     FAIL ({n} errors)")
            for e in result["semantic_errors"][:10]:
                print(f"    - {e}")
            if n > 10:
                print(f"    ... and {n - 10} more")

        print(f"{'='*60}\n")
