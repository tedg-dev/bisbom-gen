"""
Tests for app/pipeline/java_capture.py.

Covers capture-log reading, hash indexing, and treedb assembly from
inline capture events.
"""

import json
import tempfile
import unittest
from pathlib import Path

from app.pipeline.java_capture import (
    CAPTURE_LOG_ENV,
    KIND_CLASS,
    KIND_JAR,
    assemble_treedb,
    load_hash_index,
    read_capture_log,
)


def _write_lines(path, lines):
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ============================================================
# read_capture_log
# ============================================================

class TestReadCaptureLog(unittest.TestCase):

    def test_missing_file_returns_empty(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(
                read_capture_log(Path(td) / "nope.jsonl"), [],
            )

    def test_reads_jsonl_in_order(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "c.jsonl"
            _write_lines(p, [
                json.dumps({"kind": "class", "path": "/a"}),
                json.dumps({"kind": "jar", "path": "/b"}),
            ])
            events = read_capture_log(p)
            self.assertEqual(
                [e["path"] for e in events], ["/a", "/b"],
            )

    def test_skips_blank_lines(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "c.jsonl"
            _write_lines(p, [
                json.dumps({"path": "/a"}),
                "",
                "   ",
                json.dumps({"path": "/b"}),
            ])
            self.assertEqual(len(read_capture_log(p)), 2)

    def test_tolerates_torn_final_line(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "c.jsonl"
            _write_lines(p, [
                json.dumps({"path": "/a"}),
                '{"path": "/b", "sha1"',  # torn write
            ])
            events = read_capture_log(p)
            self.assertEqual([e["path"] for e in events], ["/a"])

    def test_malformed_interior_line_raises(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "c.jsonl"
            _write_lines(p, [
                "{ not json",
                json.dumps({"path": "/b"}),
            ])
            with self.assertRaises(ValueError):
                read_capture_log(p)


# ============================================================
# load_hash_index
# ============================================================

class TestLoadHashIndex(unittest.TestCase):

    def test_maps_path_to_hashes(self):
        events = [
            {"path": "/a", "sha1": "s1", "gitoid": "g1"},
            {"path": "/b", "sha1": "s2", "gitoid": "g2"},
        ]
        idx = load_hash_index(events)
        self.assertEqual(idx["/a"]["sha1"], "s1")
        self.assertEqual(idx["/b"]["gitoid"], "g2")

    def test_later_event_wins(self):
        events = [
            {"path": "/a", "sha1": "old", "gitoid": "og"},
            {"path": "/a", "sha1": "new", "gitoid": "ng"},
        ]
        self.assertEqual(load_hash_index(events)["/a"]["sha1"], "new")

    def test_skips_event_without_path(self):
        events = [{"sha1": "s"}, {"path": "/a", "sha1": "s1"}]
        idx = load_hash_index(events)
        self.assertEqual(list(idx), ["/a"])


# ============================================================
# assemble_treedb
# ============================================================

class TestAssembleTreedb(unittest.TestCase):

    def test_class_with_resolved_source(self):
        events = [{
            "kind": KIND_CLASS, "path": "/t/App.class",
            "sha1": "cls1", "gitoid": "g",
            "source_file": "App.java",
            "class_name": "com.example.App",
        }]

        def resolver(source_file, class_name):
            self.assertEqual(source_file, "App.java")
            self.assertEqual(class_name, "com.example.App")
            return ("/src/com/example/App.java", "src1")

        tree = assemble_treedb(events, resolve_source=resolver)
        self.assertEqual(
            tree["cls1"]["file_path"], "/t/App.class",
        )
        self.assertEqual(tree["cls1"]["hash_tree"], ["src1"])
        self.assertEqual(
            tree["src1"],
            {"file_path": "/src/com/example/App.java"},
        )

    def test_class_without_resolver_has_empty_tree(self):
        events = [{
            "kind": KIND_CLASS, "path": "/t/App.class",
            "sha1": "cls1",
        }]
        tree = assemble_treedb(events)
        self.assertEqual(tree["cls1"]["hash_tree"], [])

    def test_class_resolver_returns_none(self):
        events = [{
            "kind": KIND_CLASS, "path": "/t/App.class",
            "sha1": "cls1", "source_file": "App.java",
        }]
        tree = assemble_treedb(
            events, resolve_source=lambda s, c: None,
        )
        self.assertEqual(tree["cls1"]["hash_tree"], [])

    def test_class_resolver_empty_sha_skips_source(self):
        events = [{
            "kind": KIND_CLASS, "path": "/t/App.class",
            "sha1": "cls1", "source_file": "App.java",
        }]
        tree = assemble_treedb(
            events, resolve_source=lambda s, c: ("/x.java", ""),
        )
        self.assertEqual(tree["cls1"]["hash_tree"], [])
        self.assertNotIn("", tree)

    def test_jar_links_members(self):
        events = [{
            "kind": KIND_JAR, "path": "/t/app.jar",
            "sha1": "jar1",
            "entries": [
                {"name": "com/example/App.class", "sha1": "cls1"},
                {"name": "com/example/B.class", "sha1": "cls2"},
                {"name": "meta.txt"},  # no sha1 -> skipped
            ],
        }]
        tree = assemble_treedb(events)
        self.assertEqual(
            tree["jar1"]["hash_tree"], ["cls1", "cls2"],
        )

    def test_jar_links_members_by_name(self):
        # No member sha1 recorded: correlate zip entry name to the
        # captured class hash via its fully-qualified class name.
        events = [
            {"kind": KIND_CLASS, "path": "/t/classes/com/x/App.class",
             "sha1": "cls1", "class_name": "com.x.App"},
            {"kind": KIND_CLASS,
             "path": "/t/classes/com/x/App$1.class",
             "sha1": "cls2", "class_name": "com.x.App$1"},
            {"kind": KIND_JAR, "path": "/t/app.jar", "sha1": "jar1",
             "entries": [
                 {"name": "com/x/App.class"},
                 {"name": "com/x/App$1.class"},
                 {"name": "com/x/Missing.class"},
             ]},
        ]
        tree = assemble_treedb(events)
        self.assertEqual(
            tree["jar1"]["hash_tree"], ["cls1", "cls2"],
        )

    def test_jar_member_sha1_wins_over_name(self):
        events = [
            {"kind": KIND_CLASS, "path": "/t/App.class",
             "sha1": "byname", "class_name": "com.x.App"},
            {"kind": KIND_JAR, "path": "/t/app.jar", "sha1": "jar1",
             "entries": [
                 {"name": "com/x/App.class", "sha1": "bysha"},
             ]},
        ]
        tree = assemble_treedb(events)
        self.assertEqual(tree["jar1"]["hash_tree"], ["bysha"])

    def test_skips_event_missing_sha_or_path(self):
        events = [
            {"kind": KIND_CLASS, "path": "/a"},   # no sha1
            {"kind": KIND_CLASS, "sha1": "s"},    # no path
            {"kind": "other", "path": "/c", "sha1": "s3"},
        ]
        self.assertEqual(assemble_treedb(events), {})

    def test_duplicate_sha_keeps_first_path(self):
        events = [
            {"kind": KIND_CLASS, "path": "/first.class",
             "sha1": "dup"},
            {"kind": KIND_CLASS, "path": "/second.class",
             "sha1": "dup"},
        ]
        tree = assemble_treedb(events)
        self.assertEqual(
            tree["dup"]["file_path"], "/first.class",
        )

    def test_env_constant_exposed(self):
        self.assertEqual(CAPTURE_LOG_ENV, "OMNIBOR_CAPTURE_LOG")


if __name__ == "__main__":
    unittest.main()
