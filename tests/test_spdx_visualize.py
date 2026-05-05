"""Tests for spdx_visualize module."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(
    0, str(Path(__file__).parent.parent / "app")
)

from spdx_visualize import extract_graph, generate_html


def _make_doc(
    packages=None, relationships=None,
    name="Test Doc", created="2026-01-01",
):
    """Build a minimal SPDX doc for testing."""
    return {
        "name": name,
        "creationInfo": {"created": created},
        "packages": packages or [],
        "relationships": relationships or [],
    }


def _root_pkg(spdx_id="SPDXRef-Root"):
    return {
        "SPDXID": spdx_id,
        "name": "myapp",
        "versionInfo": "1.0",
        "primaryPackagePurpose": "APPLICATION",
        "comment": "Root binary",
    }


def _lib_pkg(spdx_id, name, version=""):
    pkg = {
        "SPDXID": spdx_id,
        "name": name,
        "primaryPackagePurpose": "LIBRARY",
    }
    if version:
        pkg["versionInfo"] = version
    return pkg


def _rel(src, rel_type, tgt):
    return {
        "spdxElementId": src,
        "relationshipType": rel_type,
        "relatedSpdxElement": tgt,
    }


class TestExtractGraph(unittest.TestCase):
    """Tests for extract_graph."""

    def test_empty_doc(self):
        doc = _make_doc()
        nodes, edges = extract_graph(doc)
        self.assertEqual(nodes, [])
        self.assertEqual(edges, [])

    def test_root_only(self):
        doc = _make_doc(
            packages=[_root_pkg()],
            relationships=[
                _rel(
                    "SPDXRef-Doc", "DESCRIBES",
                    "SPDXRef-Root",
                ),
            ],
        )
        nodes, edges = extract_graph(doc)
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0]["group"], "root")
        self.assertEqual(len(edges), 0)

    def test_static_link_group(self):
        """STATIC_LINK targets get depth-based group."""
        doc = _make_doc(
            packages=[
                _root_pkg(),
                _lib_pkg("SPDXRef-Lib", "libfoo"),
            ],
            relationships=[
                _rel(
                    "SPDXRef-Root", "STATIC_LINK",
                    "SPDXRef-Lib",
                ),
            ],
        )
        nodes, edges = extract_graph(doc)
        lib_node = [
            n for n in nodes
            if n["id"] == "SPDXRef-Lib"
        ][0]
        self.assertEqual(lib_node["group"], "depth-1")
        self.assertEqual(len(edges), 1)
        self.assertEqual(
            edges[0]["type"], "STATIC_LINK",
        )

    def test_dynamic_link_group(self):
        """DYNAMIC_LINK targets get group='dynamic'."""
        doc = _make_doc(
            packages=[
                _root_pkg(),
                _lib_pkg("SPDXRef-Lib", "libbar"),
            ],
            relationships=[
                _rel(
                    "SPDXRef-Root", "DYNAMIC_LINK",
                    "SPDXRef-Lib",
                ),
            ],
        )
        nodes, edges = extract_graph(doc)
        lib_node = [
            n for n in nodes
            if n["id"] == "SPDXRef-Lib"
        ][0]
        self.assertEqual(lib_node["group"], "dynamic")

    def test_build_tool_group(self):
        """BUILD_TOOL_OF sources get group='build'."""
        doc = _make_doc(
            packages=[
                _root_pkg(),
                _lib_pkg("SPDXRef-GCC", "gcc"),
            ],
            relationships=[
                _rel(
                    "SPDXRef-GCC", "BUILD_TOOL_OF",
                    "SPDXRef-Root",
                ),
            ],
        )
        nodes, edges = extract_graph(doc)
        gcc_node = [
            n for n in nodes
            if n["id"] == "SPDXRef-GCC"
        ][0]
        self.assertEqual(gcc_node["group"], "build")

    def test_other_group(self):
        """Packages not in any rel get group='other'."""
        doc = _make_doc(
            packages=[
                _lib_pkg("SPDXRef-X", "unknown-pkg"),
            ],
        )
        nodes, edges = extract_graph(doc)
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0]["group"], "other")

    def test_file_counts(self):
        """CONTAINS relationships are counted."""
        doc = _make_doc(
            packages=[_root_pkg()],
            relationships=[
                _rel(
                    "SPDXRef-Root", "CONTAINS",
                    "SPDXRef-File-1",
                ),
                _rel(
                    "SPDXRef-Root", "CONTAINS",
                    "SPDXRef-File-2",
                ),
            ],
        )
        nodes, edges = extract_graph(doc)
        self.assertEqual(nodes[0]["fileCount"], 2)

    def test_edges_skip_describes_contains(self):
        """DESCRIBES and CONTAINS don't become edges."""
        doc = _make_doc(
            packages=[_root_pkg()],
            relationships=[
                _rel(
                    "SPDXRef-Doc", "DESCRIBES",
                    "SPDXRef-Root",
                ),
                _rel(
                    "SPDXRef-Root", "CONTAINS",
                    "SPDXRef-File-1",
                ),
            ],
        )
        _, edges = extract_graph(doc)
        self.assertEqual(len(edges), 0)

    def test_edges_only_between_packages(self):
        """Edges referencing non-package IDs are skipped."""
        doc = _make_doc(
            packages=[_root_pkg()],
            relationships=[
                _rel(
                    "SPDXRef-Root", "DYNAMIC_LINK",
                    "SPDXRef-NonExistent",
                ),
            ],
        )
        _, edges = extract_graph(doc)
        self.assertEqual(len(edges), 0)

    def test_full_graph(self):
        """Integration: root + static + dynamic + build."""
        doc = _make_doc(
            packages=[
                _root_pkg(),
                _lib_pkg(
                    "SPDXRef-S", "liblua", "5.4",
                ),
                _lib_pkg(
                    "SPDXRef-D", "libssl3", "3.0.2",
                ),
                _lib_pkg("SPDXRef-B", "gcc"),
            ],
            relationships=[
                _rel(
                    "SPDXRef-Root", "STATIC_LINK",
                    "SPDXRef-S",
                ),
                _rel(
                    "SPDXRef-Root", "DYNAMIC_LINK",
                    "SPDXRef-D",
                ),
                _rel(
                    "SPDXRef-B", "BUILD_TOOL_OF",
                    "SPDXRef-Root",
                ),
                _rel(
                    "SPDXRef-Root", "CONTAINS",
                    "SPDXRef-File-1",
                ),
            ],
        )
        nodes, edges = extract_graph(doc)
        groups = {n["name"]: n["group"] for n in nodes}
        self.assertEqual(groups["myapp"], "root")
        self.assertEqual(groups["liblua"], "depth-1")
        self.assertEqual(groups["libssl3"], "dynamic")
        self.assertEqual(groups["gcc"], "build")
        self.assertEqual(len(edges), 3)

    def test_version_and_comment_preserved(self):
        doc = _make_doc(
            packages=[{
                "SPDXID": "SPDXRef-P",
                "name": "pkg",
                "versionInfo": "1.2.3",
                "primaryPackagePurpose": "LIBRARY",
                "comment": "test comment",
            }],
        )
        nodes, _ = extract_graph(doc)
        self.assertEqual(nodes[0]["version"], "1.2.3")
        self.assertEqual(
            nodes[0]["comment"], "test comment",
        )


class TestGenerateHtml(unittest.TestCase):
    """Tests for generate_html."""

    def test_output_file_created(self):
        doc = _make_doc(
            packages=[_root_pkg()],
        )
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "graph.html"
            result = generate_html(doc, str(out))
            self.assertTrue(out.exists())
            self.assertEqual(result, str(out))

    def test_html_contains_d3(self):
        doc = _make_doc(
            packages=[_root_pkg()],
        )
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "graph.html"
            generate_html(doc, str(out))
            content = out.read_text()
            self.assertIn("d3.v7.min.js", content)

    def test_html_contains_doc_name(self):
        doc = _make_doc(
            packages=[_root_pkg()],
            name="nmap SBOM",
        )
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "graph.html"
            generate_html(doc, str(out))
            content = out.read_text()
            self.assertIn("nmap SBOM", content)

    def test_html_contains_graph_data(self):
        doc = _make_doc(
            packages=[
                _root_pkg(),
                _lib_pkg("SPDXRef-L", "libz"),
            ],
            relationships=[
                _rel(
                    "SPDXRef-Root", "DYNAMIC_LINK",
                    "SPDXRef-L",
                ),
            ],
        )
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "graph.html"
            generate_html(doc, str(out))
            content = out.read_text()
            self.assertIn('"libz"', content)
            self.assertIn("DYNAMIC_LINK", content)

    def test_creates_parent_dirs(self):
        doc = _make_doc(packages=[_root_pkg()])
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "sub" / "dir" / "g.html"
            generate_html(doc, str(out))
            self.assertTrue(out.exists())


class TestMain(unittest.TestCase):
    """Tests for CLI main()."""

    def test_main_default_output(self):
        """main() generates .html next to input."""
        doc = _make_doc(packages=[_root_pkg()])
        with tempfile.TemporaryDirectory() as td:
            inp = Path(td) / "test.spdx.json"
            inp.write_text(json.dumps(doc))
            with patch(
                "sys.argv",
                ["spdx_visualize.py", str(inp)],
            ):
                from spdx_visualize import main
                main()
            expected = Path(td) / "test.spdx.html"
            self.assertTrue(expected.exists())

    def test_main_explicit_output(self):
        """main() uses -o for output path."""
        doc = _make_doc(packages=[_root_pkg()])
        with tempfile.TemporaryDirectory() as td:
            inp = Path(td) / "input.spdx.json"
            inp.write_text(json.dumps(doc))
            out = Path(td) / "custom.html"
            with patch(
                "sys.argv",
                [
                    "spdx_visualize.py",
                    str(inp),
                    "-o", str(out),
                ],
            ):
                from spdx_visualize import main
                main()
            self.assertTrue(out.exists())


class TestConditionalLegends(unittest.TestCase):
    """Cover _build_conditional_legends branches."""

    def test_build_deep_legend(self):
        from spdx_visualize import _build_conditional_legends
        bl, gl = _build_conditional_legends(
            {"build_deep": 3}
        )
        self.assertIn("Build tool chain", bl)
        self.assertIn("(3)", bl)
        self.assertEqual(gl, "")

    def test_go_stdlib_legend(self):
        from spdx_visualize import _build_conditional_legends
        bl, gl = _build_conditional_legends(
            {"go_stdlib": 5}
        )
        self.assertEqual(bl, "")
        self.assertIn("Go stdlib", gl)
        self.assertIn("(5)", gl)

    def test_go_direct_not_in_legend(self):
        """Go direct uses unified direct_dep — no Go-specific legend."""
        from spdx_visualize import _build_conditional_legends
        bl, gl = _build_conditional_legends(
            {"direct_dep": 2}
        )
        self.assertNotIn("Go direct", gl)

    def test_go_indirect_not_in_legend(self):
        """Go indirect uses unified transitive_dep — no Go-specific legend."""
        from spdx_visualize import _build_conditional_legends
        bl, gl = _build_conditional_legends(
            {"transitive_dep": 7}
        )
        self.assertNotIn("Go indirect", gl)

    def test_only_go_stdlib_in_go_legend(self):
        """Only go_stdlib has a Go-specific legend entry."""
        from spdx_visualize import _build_conditional_legends
        bl, gl = _build_conditional_legends({
            "go_stdlib": 1,
            "direct_dep": 2,
            "transitive_dep": 3,
        })
        self.assertIn("Go stdlib", gl)
        self.assertNotIn("Go direct", gl)
        self.assertNotIn("Go indirect", gl)


class TestExtractGraphGo(unittest.TestCase):
    """Cover Go module type detection in extract.py.

    Go direct/indirect modules map to the universal
    direct_dep/transitive_dep types.  Only go_stdlib
    remains a Go-specific node type.
    """

    def test_go_node_types(self):
        pkgs = [
            _root_pkg("SPDXRef-Root"),
            {
                "SPDXID": "SPDXRef-Stdlib",
                "name": "net/http",
                "primaryPackagePurpose": "LIBRARY",
                "comment": "Go standard library module",
            },
            {
                "SPDXID": "SPDXRef-Direct",
                "name": "github.com/foo/bar",
                "primaryPackagePurpose": "LIBRARY",
                "comment": "Go module (direct)",
            },
            {
                "SPDXID": "SPDXRef-Indirect",
                "name": "github.com/baz/qux",
                "primaryPackagePurpose": "LIBRARY",
                "comment": "Go module (indirect)",
            },
        ]
        rels = [
            _rel(
                "SPDXRef-Root", "DEPENDS_ON",
                "SPDXRef-Stdlib",
            ),
            _rel(
                "SPDXRef-Root", "DEPENDS_ON",
                "SPDXRef-Direct",
            ),
            _rel(
                "SPDXRef-Direct", "DEPENDS_ON",
                "SPDXRef-Indirect",
            ),
        ]
        doc = _make_doc(pkgs, rels)
        nodes, edges = extract_graph(doc)
        types = {
            n["id"]: n["node_type"] for n in nodes
        }
        self.assertEqual(
            types["SPDXRef-Stdlib"], "go_stdlib"
        )
        self.assertEqual(
            types["SPDXRef-Direct"], "direct_dep"
        )
        self.assertEqual(
            types["SPDXRef-Indirect"],
            "transitive_dep"
        )


class TestExtractGraphJava(unittest.TestCase):
    """Cover Java direct/transitive depth detection."""

    def test_java_depth_classification(self):
        pkgs = [
            _root_pkg("SPDXRef-Root"),
            {
                "SPDXID": "SPDXRef-DirectDep",
                "name": "commons-io",
                "primaryPackagePurpose": "LIBRARY",
            },
            {
                "SPDXID": "SPDXRef-TransDep",
                "name": "commons-logging",
                "primaryPackagePurpose": "LIBRARY",
            },
        ]
        rels = [
            _rel(
                "SPDXRef-Root", "DEPENDS_ON",
                "SPDXRef-DirectDep",
            ),
            _rel(
                "SPDXRef-DirectDep", "DEPENDS_ON",
                "SPDXRef-TransDep",
            ),
        ]
        doc = _make_doc(pkgs, rels)
        nodes, edges = extract_graph(doc)
        types = {
            n["id"]: n["node_type"] for n in nodes
        }
        self.assertEqual(
            types["SPDXRef-DirectDep"], "direct_dep"
        )
        self.assertEqual(
            types["SPDXRef-TransDep"], "transitive_dep"
        )


class TestExtractGraphSibling(unittest.TestCase):
    """Cover sibling module filtering."""

    def test_sibling_transitive_filtered(self):
        pkgs = [
            _root_pkg("SPDXRef-Root"),
            {
                "SPDXID": "SPDXRef-Sibling",
                "name": "sibling-module",
                "primaryPackagePurpose": "LIBRARY",
                "comment": "Sibling module",
                "annotations": [{
                    "annotationType": "OTHER",
                    "comment": "sibling_module=true",
                }],
            },
            {
                "SPDXID": "SPDXRef-SibDep",
                "name": "sibling-dep",
                "primaryPackagePurpose": "LIBRARY",
            },
        ]
        rels = [
            _rel(
                "SPDXRef-Root", "DEPENDS_ON",
                "SPDXRef-Sibling",
            ),
            _rel(
                "SPDXRef-Sibling", "DEPENDS_ON",
                "SPDXRef-SibDep",
            ),
        ]
        doc = _make_doc(pkgs, rels)

        # Manually set sibling flag since extract_graph
        # looks for it in the package
        for p in doc["packages"]:
            if p["SPDXID"] == "SPDXRef-Sibling":
                p["sibling"] = True

        nodes, edges = extract_graph(doc)
        node_ids = [n["id"] for n in nodes]
        # SibDep should be filtered out as
        # sibling transitive dep
        self.assertNotIn("SPDXRef-SibDep", node_ids)


class TestExtractGraphBuildDeep(unittest.TestCase):
    """Cover build_deep node type at depth >= 2."""

    def test_build_deep(self):
        pkgs = [
            _root_pkg("SPDXRef-Root"),
            _lib_pkg(
                "SPDXRef-GCC", "gcc", "12.0"
            ),
            _lib_pkg(
                "SPDXRef-Binutils", "binutils", "2.38"
            ),
        ]
        rels = [
            _rel(
                "SPDXRef-GCC", "BUILD_TOOL_OF",
                "SPDXRef-Root",
            ),
            _rel(
                "SPDXRef-Binutils", "BUILD_TOOL_OF",
                "SPDXRef-GCC",
            ),
        ]
        doc = _make_doc(pkgs, rels)
        nodes, edges = extract_graph(doc)
        types = {
            n["id"]: n["node_type"] for n in nodes
        }
        self.assertEqual(
            types["SPDXRef-GCC"], "build"
        )
        # Binutils at depth 2 should be build_deep
        self.assertEqual(
            types["SPDXRef-Binutils"], "build_deep"
        )


class TestExtractGraphCppDepends(unittest.TestCase):
    """Cover C/C++ DEPENDS_ON with STATIC_LINK present."""

    def test_cpp_transitive(self):
        pkgs = [
            _root_pkg("SPDXRef-Root"),
            _lib_pkg(
                "SPDXRef-Static", "libfoo", "1.0"
            ),
            _lib_pkg(
                "SPDXRef-Trans", "libbaz", "2.0"
            ),
        ]
        rels = [
            _rel(
                "SPDXRef-Root", "STATIC_LINK",
                "SPDXRef-Static",
            ),
            _rel(
                "SPDXRef-Root", "DEPENDS_ON",
                "SPDXRef-Trans",
            ),
        ]
        doc = _make_doc(pkgs, rels)
        nodes, edges = extract_graph(doc)
        types = {
            n["id"]: n["node_type"] for n in nodes
        }
        self.assertEqual(
            types["SPDXRef-Static"], "static"
        )
        self.assertEqual(
            types["SPDXRef-Trans"], "transitive_dep"
        )


class TestExtractGraphVendoredStatic(unittest.TestCase):
    """Cover vendored static and static no-depth."""

    def test_vendored_static(self):
        pkgs = [
            _root_pkg("SPDXRef-Root"),
            {
                "SPDXID": "SPDXRef-Vendored",
                "name": "vendored-lib",
                "primaryPackagePurpose": "LIBRARY",
                "comment": "Vendored copy of lib",
            },
        ]
        rels = [
            _rel(
                "SPDXRef-Root", "STATIC_LINK",
                "SPDXRef-Vendored",
            ),
        ]
        doc = _make_doc(pkgs, rels)
        nodes, edges = extract_graph(doc)
        groups = {
            n["id"]: n["group"] for n in nodes
        }
        self.assertEqual(
            groups["SPDXRef-Vendored"], "vendored"
        )

    def test_static_no_depth(self):
        pkgs = [
            {
                "SPDXID": "SPDXRef-Root",
                "name": "myapp",
                "versionInfo": "1.0",
                "primaryPackagePurpose": "APPLICATION",
                "comment": "Root binary",
            },
            {
                "SPDXID": "SPDXRef-Lib",
                "name": "lib",
                "primaryPackagePurpose": "LIBRARY",
                "comment": "",
            },
        ]
        rels = [
            _rel(
                "SPDXRef-Root", "STATIC_LINK",
                "SPDXRef-Lib",
            ),
        ]
        doc = _make_doc(pkgs, rels)
        nodes, edges = extract_graph(doc)
        lib_node = [
            n for n in nodes
            if n["id"] == "SPDXRef-Lib"
        ][0]
        # Lib is static with depth >= 1
        self.assertEqual(
            lib_node["node_type"], "static"
        )


class TestExtractGraphSiblingBFS(unittest.TestCase):
    """Cover multi-level sibling BFS and edge filter."""

    def test_sibling_bfs_multi_level(self):
        pkgs = [
            _root_pkg("SPDXRef-Root"),
            {
                "SPDXID": "SPDXRef-Sib",
                "name": "sibling",
                "primaryPackagePurpose": "LIBRARY",
                "comment": "Sibling module",
            },
            {
                "SPDXID": "SPDXRef-L1",
                "name": "level1-dep",
                "primaryPackagePurpose": "LIBRARY",
                "comment": "",
            },
            {
                "SPDXID": "SPDXRef-L2",
                "name": "level2-dep",
                "primaryPackagePurpose": "LIBRARY",
                "comment": "",
            },
        ]
        rels = [
            _rel(
                "SPDXRef-Root", "DEPENDS_ON",
                "SPDXRef-Sib",
            ),
            _rel(
                "SPDXRef-Sib", "DEPENDS_ON",
                "SPDXRef-L1",
            ),
            _rel(
                "SPDXRef-L1", "DEPENDS_ON",
                "SPDXRef-L2",
            ),
            # Also root depends on L1 directly —
            # but since L1 is reachable only from sib,
            # it should still be filtered
            _rel(
                "SPDXRef-Root", "DEPENDS_ON",
                "SPDXRef-L1",
            ),
        ]
        doc = _make_doc(pkgs, rels)
        nodes, edges = extract_graph(doc)
        node_ids = [n["id"] for n in nodes]
        # L1 and L2 are sibling-transitive
        self.assertNotIn("SPDXRef-L2", node_ids)
        # Edges TO sibling deps should be filtered
        edge_tgts = [e["target"] for e in edges]
        self.assertNotIn("SPDXRef-L2", edge_tgts)


class TestVersionDetectorShim(unittest.TestCase):
    """Cover app/spdx/version_detector.py shim."""

    def test_import(self):
        from app.spdx.version_detector import (
            VendoredVersionDetector,
        )
        self.assertTrue(
            callable(VendoredVersionDetector)
        )


if __name__ == "__main__":
    unittest.main()
