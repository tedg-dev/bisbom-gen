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

        def resolver(source_file, class_path):
            self.assertEqual(source_file, "App.java")
            self.assertEqual(class_path, "/t/App.class")
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
            events, resolve_source=lambda s, p: None,
        )
        self.assertEqual(tree["cls1"]["hash_tree"], [])

    def test_class_resolver_empty_sha_skips_source(self):
        events = [{
            "kind": KIND_CLASS, "path": "/t/App.class",
            "sha1": "cls1", "source_file": "App.java",
        }]
        tree = assemble_treedb(
            events, resolve_source=lambda s, p: ("/x.java", ""),
        )
        self.assertEqual(tree["cls1"]["hash_tree"], [])
        self.assertNotIn("", tree)

    def test_jar_links_members_by_content(self):
        # Members carry their own git-blob sha1 (from the shim); each is
        # linked to the captured class keyed by that sha1.  A non-.class
        # member without a sha1 is skipped.
        events = [
            {"kind": KIND_CLASS, "path": "/t/App.class",
             "sha1": "cls1", "class_name": "com.example.App"},
            {"kind": KIND_CLASS, "path": "/t/B.class",
             "sha1": "cls2", "class_name": "com.example.B"},
            {"kind": KIND_JAR, "path": "/t/app.jar", "sha1": "jar1",
             "entries": [
                 {"name": "com/example/App.class", "sha1": "cls1"},
                 {"name": "com/example/B.class", "sha1": "cls2"},
                 {"name": "meta.txt"},  # no sha1 -> skipped
             ]},
        ]
        tree = assemble_treedb(events)
        self.assertEqual(
            tree["jar1"]["hash_tree"], ["cls1", "cls2"],
        )

    def test_jar_drops_member_with_unmatched_sha1(self):
        # A member whose content matches no captured class (e.g. a
        # build-rewritten module-info.class) is dropped, matching the
        # rescan which finds no workspace file with identical content.
        events = [
            {"kind": KIND_CLASS, "path": "/t/App.class",
             "sha1": "cls1", "class_name": "com.example.App"},
            {"kind": KIND_JAR, "path": "/t/app.jar", "sha1": "jar1",
             "entries": [
                 {"name": "com/example/App.class", "sha1": "cls1"},
                 {"name": "META-INF/versions/11/module-info.class",
                  "sha1": "rewritten"},  # no matching class -> dropped
             ]},
        ]
        tree = assemble_treedb(events)
        self.assertEqual(tree["jar1"]["hash_tree"], ["cls1"])
        self.assertNotIn("rewritten", tree)

    def test_jar_multirelease_member_by_content(self):
        # A versioned member is linked purely by content, regardless of
        # the on-disk write path of the captured class (here a Gradle
        # separate source-set dir, unrelated to META-INF/versions).
        events = [
            {"kind": KIND_CLASS,
             "path": "/t/build/classes/java/java11/org/j/H.class",
             "sha1": "v11", "class_name": "org.j.H"},
            {"kind": KIND_JAR, "path": "/t/app.jar", "sha1": "jar1",
             "entries": [
                 {"name": "META-INF/versions/11/org/j/H.class",
                  "sha1": "v11"},
             ]},
        ]
        tree = assemble_treedb(events)
        self.assertEqual(tree["jar1"]["hash_tree"], ["v11"])

    def test_base_and_versioned_variants_by_content(self):
        # A base class and its versioned variant share a fully-qualified
        # name but differ in bytes; each member binds to its own variant
        # by content sha1 (name-based correlation cannot disambiguate).
        events = [
            {"kind": KIND_CLASS, "path": "/t/main/org/j/H.class",
             "sha1": "base", "class_name": "org.j.H"},
            {"kind": KIND_CLASS, "path": "/t/java9/org/j/H.class",
             "sha1": "v9", "class_name": "org.j.H"},
            {"kind": KIND_JAR, "path": "/t/app.jar", "sha1": "jar1",
             "entries": [
                 {"name": "org/j/H.class", "sha1": "base"},
                 {"name": "META-INF/versions/9/org/j/H.class",
                  "sha1": "v9"},
             ]},
        ]
        tree = assemble_treedb(events)
        self.assertEqual(tree["jar1"]["hash_tree"], ["base", "v9"])

    def test_mrjar_staging_copy_does_not_steal_source(self):
        # The same versioned bytes are captured twice: once at the java9
        # module's compiler output and once as a Multi-Release JAR
        # META-INF/versions/9 staging copy under a *different* module's
        # tree.  Source must resolve from the primary compiler-output
        # path (its true origin), never the staging copy.
        def resolver(_source_file, class_path):
            if "api-java9" in class_path:
                return ("/r/api-java9/src/H.java", "j9src")
            return ("/r/api/src/H.java", "basesrc")

        events = [
            {"kind": KIND_CLASS,
             "path": "/r/api-java9/target/classes/org/j/H.class",
             "sha1": "v9", "source_file": "H.java"},
            {"kind": KIND_CLASS,
             "path": "/r/api/target/classes/org/j/H.class",
             "sha1": "base", "source_file": "H.java"},
            {"kind": KIND_CLASS,
             "path": ("/r/api/target/classes/META-INF/versions/9"
                      "/org/j/H.class"),
             "sha1": "v9", "source_file": "H.java"},
        ]
        tree = assemble_treedb(events, resolve_source=resolver)
        self.assertEqual(
            tree["v9"]["file_path"],
            "/r/api-java9/target/classes/org/j/H.class",
        )
        self.assertEqual(tree["v9"]["hash_tree"], ["j9src"])
        self.assertEqual(tree["base"]["hash_tree"], ["basesrc"])

    def test_mrjar_staging_preference_is_order_independent(self):
        # Even when the staging copy is captured *before* the primary
        # compiler output, the primary path still wins.
        def resolver(_source_file, class_path):
            if "api-java9" in class_path:
                return ("/r/api-java9/src/H.java", "j9src")
            return ("/r/api/src/H.java", "basesrc")

        events = [
            {"kind": KIND_CLASS,
             "path": ("/r/api/target/classes/META-INF/versions/9"
                      "/org/j/H.class"),
             "sha1": "v9", "source_file": "H.java"},
            {"kind": KIND_CLASS,
             "path": "/r/api-java9/target/classes/org/j/H.class",
             "sha1": "v9", "source_file": "H.java"},
        ]
        tree = assemble_treedb(events, resolve_source=resolver)
        self.assertEqual(
            tree["v9"]["file_path"],
            "/r/api-java9/target/classes/org/j/H.class",
        )
        self.assertEqual(tree["v9"]["hash_tree"], ["j9src"])

    def test_canonical_prefers_lexicographically_smallest_path(self):
        # The same class compiled identically in sibling modules yields
        # one content-addressed entry; its file_path must be the
        # lexicographically smallest (matching the sorted-first rescan),
        # not whichever module happened to be captured first.
        events = [
            {"kind": KIND_CLASS,
             "path": "/r/core/target/classes/o/package-info.class",
             "sha1": "pi", "source_file": "package-info.java"},
            {"kind": KIND_CLASS,
             "path": "/r/cli/target/classes/o/package-info.class",
             "sha1": "pi", "source_file": "package-info.java"},
        ]
        tree = assemble_treedb(events)
        self.assertEqual(
            tree["pi"]["file_path"],
            "/r/cli/target/classes/o/package-info.class",
        )

    def test_shared_source_leaf_prefers_jar_member(self):
        # A base class and a non-member java9 sibling compile from
        # byte-identical source (same src sha), so both map to one
        # content-addressed source leaf.  Although the java9 class is
        # captured first, only the base class is a JAR member, so the
        # shared leaf's path must be the member's (base) source.
        def resolver(_source_file, class_path):
            if "api-java9" in class_path:
                return ("/r/api-java9/src/H.java", "srcsha")
            return ("/r/api/src/H.java", "srcsha")

        events = [
            {"kind": KIND_CLASS,
             "path": "/r/api-java9/target/classes/o/H.class",
             "sha1": "v9", "source_file": "H.java"},
            {"kind": KIND_CLASS,
             "path": "/r/api/target/classes/o/H.class",
             "sha1": "base", "source_file": "H.java"},
            {"kind": KIND_JAR, "path": "/r/api/build/libs/api.jar",
             "sha1": "jar1",
             "entries": [{"name": "o/H.class", "sha1": "base"}]},
        ]
        tree = assemble_treedb(events, resolve_source=resolver)
        self.assertEqual(tree["jar1"]["hash_tree"], ["base"])
        self.assertEqual(
            tree["srcsha"]["file_path"], "/r/api/src/H.java",
        )
        self.assertEqual(tree["base"]["hash_tree"], ["srcsha"])
        self.assertEqual(tree["v9"]["hash_tree"], ["srcsha"])

    def test_jar_legacy_name_fallback(self):
        # Legacy capture logs with no member sha1 fall back to matching
        # the central-directory name to a captured class's FQN.
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
        self.assertEqual(CAPTURE_LOG_ENV, "BISBOM_CAPTURE_LOG")


if __name__ == "__main__":
    unittest.main()
