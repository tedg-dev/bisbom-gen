"""Tests for the Phase 2 SBOM hand-off manifest module."""
import json
import tempfile
import unittest
from pathlib import Path

from app.pipeline import handoff
from app.spdx import identity


def _write(path, text):
    """Write text to path, creating parents."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def _artifact(name="app-1.0.0.jar"):
    """A caller-supplied artifact record (Phase 1 sourced)."""
    return {
        "name": name,
        "sha256": "a" * 64,
        "gitoid": "gitoid:blob:sha256:" + ("b" * 64),
    }


class _HandoffBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.run_dir = Path(self._tmp.name)
        self.build = _write(
            self.run_dir / "app-1.0.0_build.spdx.json",
            '{"spdxVersion": "SPDX-2.3", "kind": "build"}',
        )
        self.analyzed = _write(
            self.run_dir / "app-1.0.0_analyzed.spdx.json",
            '{"spdxVersion": "SPDX-2.3", "kind": "analyzed"}',
        )

    def _sboms(self):
        return [{
            "artifact": _artifact(),
            "build": str(self.build),
            "analyzed": str(self.analyzed),
        }]

    def _write_default(self, **overrides):
        kwargs = {
            "repo_name": "app",
            "language": "java",
            "mode": "sidecar",
            "commit_sha": "0" * 40,
            "vcs_uri": "https://example.com/app.git",
            "build_id": "2026-07-10_1200",
            "sboms": self._sboms(),
        }
        kwargs.update(overrides)
        return handoff.write_handoff_manifest(self.run_dir, **kwargs)


class TestWriteHandoffManifest(_HandoffBase):
    def test_writes_expected_filename(self):
        path = self._write_default()
        self.assertEqual(path.name, handoff.HANDOFF_FILENAME)
        self.assertTrue(path.is_file())

    def test_top_level_fields(self):
        data = json.loads(self._write_default().read_text())
        self.assertEqual(data["version"], handoff.HANDOFF_VERSION)
        self.assertEqual(data["repo_name"], "app")
        self.assertEqual(data["language"], "java")
        self.assertEqual(data["commit_sha"], "0" * 40)
        self.assertEqual(data["build_id"], "2026-07-10_1200")
        self.assertIn("generated_ts", data)

    def test_producer_block(self):
        data = json.loads(self._write_default().read_text())
        self.assertEqual(data["producer"], {
            "tool": handoff.PRODUCER_TOOL,
            "phase": handoff.PRODUCER_PHASE,
            "mode": "sidecar",
        })

    def test_artifact_passthrough(self):
        data = json.loads(self._write_default().read_text())
        art = data["sboms"][0]["artifact"]
        self.assertEqual(art, _artifact())

    def test_sbom_paths_are_relative(self):
        data = json.loads(self._write_default().read_text())
        entry = data["sboms"][0]
        self.assertEqual(
            entry["build"]["path"], "app-1.0.0_build.spdx.json",
        )
        self.assertEqual(
            entry["analyzed"]["path"],
            "app-1.0.0_analyzed.spdx.json",
        )

    def test_sbom_digests_match_bytes(self):
        data = json.loads(self._write_default().read_text())
        rec = data["sboms"][0]["build"]
        self.assertEqual(rec["sha256"], identity.raw_hash(self.build))
        self.assertEqual(rec["gitoid"], identity.gitoid(self.build))

    def test_explicit_generated_ts(self):
        data = json.loads(
            self._write_default(generated_ts="2020-01-01T00:00:00Z")
            .read_text()
        )
        self.assertEqual(
            data["generated_ts"], "2020-01-01T00:00:00Z",
        )

    def test_source_manifest_included(self):
        data = json.loads(
            self._write_default(source_manifest="phase1_manifest.json")
            .read_text()
        )
        self.assertEqual(
            data["source_manifest"], "phase1_manifest.json",
        )

    def test_source_manifest_omitted_by_default(self):
        data = json.loads(self._write_default().read_text())
        self.assertNotIn("source_manifest", data)

    def test_creates_manifest_dir(self):
        nested = self.run_dir / "sub" / "run"
        path = handoff.write_handoff_manifest(
            nested,
            repo_name="app", language="java", mode="sidecar",
            commit_sha="0" * 40, vcs_uri="x", build_id="b",
            sboms=self._sboms(),
        )
        self.assertTrue(path.is_file())


class TestWriteHandoffErrors(_HandoffBase):
    def test_empty_sboms_raises(self):
        with self.assertRaises(handoff.HandoffError):
            self._write_default(sboms=[])

    def test_missing_build_file_raises(self):
        sboms = self._sboms()
        sboms[0]["build"] = str(self.run_dir / "nope.spdx.json")
        with self.assertRaises(handoff.HandoffError):
            self._write_default(sboms=sboms)

    def test_entry_not_dict_raises(self):
        with self.assertRaises(handoff.HandoffError):
            self._write_default(sboms=["not-a-dict"])

    def test_entry_missing_field_raises(self):
        with self.assertRaises(handoff.HandoffError):
            self._write_default(sboms=[{"artifact": _artifact()}])

    def test_artifact_not_dict_raises(self):
        sboms = self._sboms()
        sboms[0]["artifact"] = "nope"
        with self.assertRaises(handoff.HandoffError):
            self._write_default(sboms=sboms)

    def test_artifact_missing_field_raises(self):
        sboms = self._sboms()
        sboms[0]["artifact"] = {"name": "x"}
        with self.assertRaises(handoff.HandoffError):
            self._write_default(sboms=sboms)


class TestReadHandoffManifest(_HandoffBase):
    def test_round_trip(self):
        path = self._write_default()
        data = handoff.read_handoff_manifest(path)
        self.assertEqual(data["repo_name"], "app")
        self.assertEqual(len(data["sboms"]), 1)

    def test_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            handoff.read_handoff_manifest(
                self.run_dir / "absent.json"
            )

    def test_malformed_json_raises(self):
        bad = _write(self.run_dir / "bad.json", "{not json")
        with self.assertRaises(handoff.HandoffError):
            handoff.read_handoff_manifest(bad)

    def _write_raw(self, obj):
        p = self.run_dir / handoff.HANDOFF_FILENAME
        p.write_text(json.dumps(obj), encoding="utf-8")
        return p

    def test_non_object_raises(self):
        with self.assertRaises(handoff.HandoffError):
            handoff.read_handoff_manifest(self._write_raw([1, 2]))

    def test_missing_top_field_raises(self):
        with self.assertRaises(handoff.HandoffError):
            handoff.read_handoff_manifest(
                self._write_raw({"version": "1.0"})
            )

    def test_bad_version_raises(self):
        good = json.loads(self._write_default().read_text())
        good["version"] = "9.9"
        with self.assertRaises(handoff.HandoffError):
            handoff.read_handoff_manifest(self._write_raw(good))

    def test_producer_not_dict_raises(self):
        good = json.loads(self._write_default().read_text())
        good["producer"] = "nope"
        with self.assertRaises(handoff.HandoffError):
            handoff.read_handoff_manifest(self._write_raw(good))

    def test_producer_missing_field_raises(self):
        good = json.loads(self._write_default().read_text())
        good["producer"] = {"tool": "x"}
        with self.assertRaises(handoff.HandoffError):
            handoff.read_handoff_manifest(self._write_raw(good))

    def test_sboms_not_list_raises(self):
        good = json.loads(self._write_default().read_text())
        good["sboms"] = {}
        with self.assertRaises(handoff.HandoffError):
            handoff.read_handoff_manifest(self._write_raw(good))

    def test_entry_missing_field_raises(self):
        good = json.loads(self._write_default().read_text())
        good["sboms"] = [{"artifact": _artifact()}]
        with self.assertRaises(handoff.HandoffError):
            handoff.read_handoff_manifest(self._write_raw(good))

    def test_entry_not_dict_raises(self):
        good = json.loads(self._write_default().read_text())
        good["sboms"] = ["nope"]
        with self.assertRaises(handoff.HandoffError):
            handoff.read_handoff_manifest(self._write_raw(good))

    def test_artifact_missing_field_raises(self):
        good = json.loads(self._write_default().read_text())
        good["sboms"][0]["artifact"] = {"name": "x"}
        with self.assertRaises(handoff.HandoffError):
            handoff.read_handoff_manifest(self._write_raw(good))

    def test_file_record_not_dict_raises(self):
        good = json.loads(self._write_default().read_text())
        good["sboms"][0]["build"] = "nope"
        with self.assertRaises(handoff.HandoffError):
            handoff.read_handoff_manifest(self._write_raw(good))

    def test_file_record_missing_field_raises(self):
        good = json.loads(self._write_default().read_text())
        good["sboms"][0]["build"] = {"path": "x"}
        with self.assertRaises(handoff.HandoffError):
            handoff.read_handoff_manifest(self._write_raw(good))


class TestVerifyHandoffManifest(_HandoffBase):
    def test_all_pass(self):
        data = handoff.read_handoff_manifest(self._write_default())
        passed, failed = handoff.verify_handoff_manifest(
            data, self.run_dir,
        )
        self.assertEqual(sorted(passed), [
            "app-1.0.0_analyzed.spdx.json",
            "app-1.0.0_build.spdx.json",
        ])
        self.assertEqual(failed, [])

    def test_missing_file_fails(self):
        data = handoff.read_handoff_manifest(self._write_default())
        self.build.unlink()
        passed, failed = handoff.verify_handoff_manifest(
            data, self.run_dir,
        )
        self.assertIn("app-1.0.0_build.spdx.json", failed)
        self.assertIn("app-1.0.0_analyzed.spdx.json", passed)

    def test_tampered_file_fails(self):
        data = handoff.read_handoff_manifest(self._write_default())
        self.build.write_text("TAMPERED", encoding="utf-8")
        passed, failed = handoff.verify_handoff_manifest(
            data, self.run_dir,
        )
        self.assertIn("app-1.0.0_build.spdx.json", failed)

    def test_missing_path_key_skipped(self):
        passed, failed = handoff.verify_handoff_manifest(
            {"sboms": [{"build": {}, "analyzed": {}}]},
            self.run_dir,
        )
        self.assertEqual((passed, failed), ([], []))


if __name__ == "__main__":
    unittest.main()
