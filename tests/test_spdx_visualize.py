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
        """STATIC_LINK targets get group='static'."""
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
        self.assertEqual(lib_node["group"], "static")
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
        self.assertEqual(groups["liblua"], "static")
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


if __name__ == "__main__":
    unittest.main()
