"""Tests for the artifact identity layer (app/spdx/identity.py).

Design of record: .windsurf/rules/project/artifact-identity.md.
Verifies raw SHA-256 vs SHA-256 gitOID are distinct values, the
canonical ``gitoid:blob:<algo>:<hex>`` IRI form, SPDX rendering
helpers, algorithm parameterization, and the offline-safe helpers.
"""
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).parent.parent)
)

from app.spdx import identity
from app.spdx.identity import (
    ArtifactIdentity,
    raw_hash,
    gitoid,
    gitoid_hex,
    spdx_2_3_file_checksums,
    try_from_file,
    write_identity_index,
)


CONTENT = b"the quick brown fox\n"


def _expected_raw(content, algo="sha256"):
    return hashlib.new(algo, content).hexdigest()


def _expected_gitoid_hex(content, algo="sha256"):
    header = f"blob {len(content)}\0".encode("ascii")
    return hashlib.new(algo, header + content).hexdigest()


class TestRawAndGitoid(unittest.TestCase):
    """Raw hash and gitOID are distinct SHA-256 values."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "artifact.bin"
        self.path.write_bytes(CONTENT)

    def test_raw_hash_matches_sha256sum(self):
        self.assertEqual(
            raw_hash(self.path),
            _expected_raw(CONTENT),
        )

    def test_gitoid_hex_uses_blob_framing(self):
        self.assertEqual(
            gitoid_hex(self.path),
            _expected_gitoid_hex(CONTENT),
        )

    def test_raw_and_gitoid_differ(self):
        self.assertNotEqual(
            raw_hash(self.path),
            gitoid_hex(self.path),
        )

    def test_gitoid_iri_form(self):
        self.assertEqual(
            gitoid(self.path),
            "gitoid:blob:sha256:"
            + _expected_gitoid_hex(CONTENT),
        )

    def test_algorithm_parameterized_sha1(self):
        self.assertEqual(
            raw_hash(self.path, algo="sha1"),
            _expected_raw(CONTENT, "sha1"),
        )
        self.assertEqual(
            gitoid(self.path, algo="sha1"),
            "gitoid:blob:sha1:"
            + _expected_gitoid_hex(CONTENT, "sha1"),
        )

    def test_large_file_chunked_raw_hash(self):
        big = Path(self._tmp.name) / "big.bin"
        payload = b"x" * (1 << 21)  # 2 MiB, > 1 MiB chunk
        big.write_bytes(payload)
        self.assertEqual(
            raw_hash(big), _expected_raw(payload)
        )


class TestArtifactIdentity(unittest.TestCase):
    """ArtifactIdentity dataclass and SPDX helpers."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "artifact.bin"
        self.path.write_bytes(CONTENT)
        self.ident = ArtifactIdentity.from_file(self.path)

    def test_from_file_values(self):
        self.assertEqual(self.ident.path, str(self.path))
        self.assertEqual(self.ident.algo, "sha256")
        self.assertEqual(
            self.ident.raw, _expected_raw(CONTENT)
        )
        self.assertEqual(
            self.ident.gitoid,
            "gitoid:blob:sha256:"
            + _expected_gitoid_hex(CONTENT),
        )

    def test_gitoid_hex_property(self):
        self.assertEqual(
            self.ident.gitoid_hex,
            _expected_gitoid_hex(CONTENT),
        )

    def test_checksum_algorithm_uppercased(self):
        self.assertEqual(
            self.ident.checksum_algorithm, "SHA256"
        )

    def test_as_spdx_checksum(self):
        self.assertEqual(
            self.ident.as_spdx_checksum(),
            {
                "algorithm": "SHA256",
                "checksumValue": _expected_raw(CONTENT),
            },
        )

    def test_as_spdx_gitoid_ref(self):
        self.assertEqual(
            self.ident.as_spdx_gitoid_ref(),
            {
                "referenceCategory": "PERSISTENT-ID",
                "referenceType": "gitoid",
                "referenceLocator": self.ident.gitoid,
            },
        )

    def test_from_file_reads_once_consistent(self):
        again = ArtifactIdentity.from_file(self.path)
        self.assertEqual(again, self.ident)


class TestTryFromFile(unittest.TestCase):
    """try_from_file returns None when unreadable."""

    def test_returns_identity_for_readable(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "a.bin"
            p.write_bytes(CONTENT)
            ident = try_from_file(p)
            self.assertIsNotNone(ident)
            self.assertEqual(
                ident.raw, _expected_raw(CONTENT)
            )

    def test_returns_none_for_missing(self):
        self.assertIsNone(
            try_from_file("/no/such/file.bin")
        )

    def test_returns_none_for_directory(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertIsNone(try_from_file(td))


class TestWriteIdentityIndex(unittest.TestCase):
    """write_identity_index persists identities to JSON."""

    def test_writes_index_and_skips_unreadable(self):
        with tempfile.TemporaryDirectory() as td:
            a = Path(td) / "a.bin"
            b = Path(td) / "b.bin"
            a.write_bytes(b"aaa")
            b.write_bytes(b"bbb")
            missing = Path(td) / "gone.bin"
            out = Path(td) / "nested" / "index.json"

            count = write_identity_index(
                [str(a), str(b), str(missing)], out
            )

            self.assertEqual(count, 2)
            self.assertTrue(out.exists())
            data = json.loads(out.read_text())
            self.assertIn(str(a), data)
            self.assertIn(str(b), data)
            self.assertNotIn(str(missing), data)
            self.assertEqual(data[str(a)]["algo"], "sha256")
            self.assertEqual(
                data[str(a)]["raw"], _expected_raw(b"aaa")
            )
            self.assertTrue(
                data[str(a)]["gitoid"].startswith(
                    "gitoid:blob:sha256:"
                )
            )

    def test_empty_input_writes_empty_index(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "index.json"
            count = write_identity_index([], out)
            self.assertEqual(count, 0)
            self.assertEqual(
                json.loads(out.read_text()), {}
            )


class TestSpdx23FileChecksums(unittest.TestCase):
    """SPDX 2.3 File checksums: mandated raw SHA-1 + raw SHA-256.

    Design of record §5.1: SPDX 2.3 requires exactly one raw
    ``SHA-1`` per File (Clause 8.4, Table 39); the raw ``SHA-256``
    identity hash is emitted alongside it.  The SHA-1 is a legacy
    corruption checksum (``sha1sum`` of the bytes), never a git-blob
    or identity value.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "src.c"
        self.path.write_bytes(CONTENT)

    def test_emits_sha1_then_sha256_in_spec_order(self):
        result = spdx_2_3_file_checksums(self.path)
        self.assertEqual(
            result,
            [
                {
                    "algorithm": "SHA1",
                    "checksumValue": _expected_raw(
                        CONTENT, "sha1"
                    ),
                },
                {
                    "algorithm": "SHA256",
                    "checksumValue": _expected_raw(CONTENT),
                },
            ],
        )

    def test_sha1_is_raw_not_gitoid(self):
        result = spdx_2_3_file_checksums(self.path)
        sha1_value = result[0]["checksumValue"]
        self.assertEqual(
            sha1_value, _expected_raw(CONTENT, "sha1")
        )
        # Must NOT be the git-blob SHA-1 (the corrected bug).
        self.assertNotEqual(
            sha1_value, _expected_gitoid_hex(CONTENT, "sha1")
        )

    def test_unreadable_returns_empty_list(self):
        self.assertEqual(
            spdx_2_3_file_checksums("/no/such/file.c"), []
        )

    def test_sha1_algo_yields_single_entry(self):
        result = spdx_2_3_file_checksums(
            self.path, algo="sha1"
        )
        self.assertEqual(
            result,
            [{
                "algorithm": "SHA1",
                "checksumValue": _expected_raw(
                    CONTENT, "sha1"
                ),
            }],
        )

    def test_legacy_algo_constant(self):
        self.assertEqual(
            identity.SPDX_2_3_FILE_LEGACY_ALGO, "sha1"
        )


class TestReadIdentityIndex(unittest.TestCase):
    """Tests for identity.read_identity_index."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def test_missing_returns_empty(self):
        self.assertEqual(
            identity.read_identity_index(self.tmp / "absent.json"),
            {},
        )

    def test_valid_returns_mapping(self):
        p = self.tmp / "idx.json"
        p.write_text(
            json.dumps({"/a/x.jar": {"raw": "r", "gitoid": "g"}}),
            encoding="utf-8",
        )
        idx = identity.read_identity_index(p)
        self.assertEqual(idx["/a/x.jar"]["gitoid"], "g")

    def test_non_dict_returns_empty(self):
        p = self.tmp / "list.json"
        p.write_text(json.dumps([1, 2]), encoding="utf-8")
        self.assertEqual(identity.read_identity_index(p), {})

    def test_malformed_returns_empty(self):
        p = self.tmp / "bad.json"
        p.write_text("{not json", encoding="utf-8")
        self.assertEqual(identity.read_identity_index(p), {})


class TestIdentityForBasename(unittest.TestCase):
    """Tests for identity.identity_for_basename."""

    def test_exact_key_match(self):
        idx = {"app.jar": {"raw": "r"}}
        self.assertEqual(
            identity.identity_for_basename(idx, "app.jar"),
            {"raw": "r"},
        )

    def test_suffix_match(self):
        idx = {"/build/libs/app.jar": {"raw": "r"}}
        self.assertEqual(
            identity.identity_for_basename(idx, "app.jar")["raw"],
            "r",
        )

    def test_no_match_returns_none(self):
        idx = {"/build/libs/other.jar": {"raw": "r"}}
        self.assertIsNone(
            identity.identity_for_basename(idx, "app.jar")
        )


class TestModuleConstants(unittest.TestCase):
    """Module-level defaults align with the design of record."""

    def test_default_algo_is_sha256(self):
        self.assertEqual(identity.DEFAULT_ALGO, "sha256")


if __name__ == "__main__":
    unittest.main()
